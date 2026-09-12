# DealWatch PL

DealWatch PL is a Python service for monitoring Polish electronics retailers and detecting genuinely good technology deals.

The long-term goal is to monitor retailers such as x-kom, Morele, Komputronik and others, build historical price data, evaluate whether a discount is actually attractive, and automatically send relevant deals to Discord.

## Current Status

🚧 Early development — x-kom GPU collection, SQLite price history and statistics,
hourly x-kom monitoring, notification state, and rule-based deal delivery are
implemented and verified.

The current milestone is x-kom → GPU products → normalized product offers → local
SQLite observations → explained deal candidates → notification state → an explicit
Discord delivery. It deliberately does not yet include deal scoring, other retailers,
or candidate re-arming/cooldown policy.

## Planned Features

- Multiple Polish electronics retailers
- Configurable product categories
- Historical price tracking
- Deal detection
- Duplicate notification prevention
- Cross-store product matching
- Cross-store price comparison
- Deal scoring
- Discord notifications
- Configurable price/category filters
- Scheduled monitoring
- Docker deployment

## MVP Architecture

```text
x-kom GPU category HTML
          ↓
      x-kom adapter
          ↓
 ProductIdentity + ProductOffer
          ↓
       SQLite store
       ↙           ↓
price-history   deal engine
analysis             ↓
           candidate JSON → notification state
                              ↓
                   M6 eligibility check
                              ↓
                         Discord webhook
                              ↓
                    successful event record
```

`ProductIdentity` keeps retailer product identity separate from price. `ProductOffer`
records the observed price, availability, promotional information, and timestamp.
Each successful collection upserts products by retailer plus external product ID, then
appends one SQLite price observation per offer.

When x-kom exposes `priceInfo.minPrice`, the adapter also carries it as separately
stored reference evidence: `xkom_reported_lowest_price_last_30_days`. It is an
x-kom-reported, retailer-scoped 30-day reference associated directly with the x-kom
product—not a DealWatch observation or verified all-time low. It never contributes to
M5 coverage, averages, medians, or native lows.

Notification state is a separate SQLite table associated with the same stable product
identity. A future deal rule supplies an alert type, a stable fingerprint, and any
optional audit fields. The state layer uses that caller-defined fingerprint to decide
whether the product has already received an equivalent successful notification. It
does not decide whether something is a deal or apply a cooldown policy.

The pure deal engine evaluates a newly collected offer against local history that
predates it, so a current price never affects its own median or low baseline. It emits
an explained candidate only when a deterministic historical or young-history rule is
met; it does not send Discord messages or persist a notification event.

## Development Approach

Retailer data retrieval should use the simplest reliable method available:

1. JSON/API endpoint
2. HTTP + HTML parsing
3. Browser automation
4. External scraping services such as Firecrawl

More complex scraping technology should only be introduced when simpler methods are insufficient.

## Setup

DealWatch PL requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --all-groups
uv run dealwatch xkom collect-gpus
```

The collector fetches x-kom's public GPU category pages through ordinary HTTP,
follows their pagination links, and parses the server-rendered hydration JSON. It
waits at least one second between category-page requests.

By default, successful collection commands persist data to the Git-ignored
`data/dealwatch.sqlite3` file. Set `DEALWATCH_DATABASE_PATH` to use another local
SQLite path; never commit database files.

## Hourly x-kom monitoring on Windows

The application performs one monitoring run and exits; Windows Task Scheduler invokes
the external PowerShell wrapper once per hour. The runner collects and persists
x-kom offers, evaluates M7 candidates, checks M6 state, sends eligible candidates to
Discord, then records state only after each successful webhook response.

`monitor-gpus` is dry-run by default. It writes no notification-state records and
does not require a webhook:

```powershell
uv run dealwatch xkom monitor-gpus
uv run dealwatch xkom monitor-gpus --quiet
```

For a deliberate inspection of the guarded young-history bootstrap, add
`--reference-bootstrap`. This allows an available offer to qualify only when it is at
least both 8% and 100 PLN below a usable x-kom-reported 30-day reference. With
sufficient native history, that reference can remain supporting evidence but cannot
qualify a candidate by itself. This switch is deliberately absent from the scheduled
task until separately approved:

```powershell
uv run dealwatch xkom monitor-gpus --reference-bootstrap --quiet
```

The monitoring summary reports `usable_xkom_reference_count` and
`reference_bootstrap_candidate_count`. Reference evidence is stored as contiguous
episodes: an unchanged latest value extends its last-seen time, while any change
(including a later return to a former value) creates a new episode.

Use `--send` only for deliberate delivery. The optional `--only-product PRODUCT_ID`
is useful for a controlled single-product check, but it never bypasses the global
safety checks:

```powershell
uv run dealwatch xkom monitor-gpus --send --only-product 1318534
```

Every run applies a hard circuit breaker: if more than three M6-eligible candidates
exist, it sends none, records none, returns nonzero, and reports the block. Eligible
candidates are sent serially. A failed webhook has no in-process retry, remains
eligible for the next hourly run, and does not prevent later candidates from being
processed. A compact summary includes collection/evaluation counts, factual history
baseline counts, candidate signal counts, delivery outcomes, and breaker status.

After `uv sync --all-groups`, register the task from the project root:

```powershell
.\scripts\register-hourly-collection.ps1
schtasks.exe /Run /TN "DealWatchPL-HourlyCollection"
schtasks.exe /Query /TN "DealWatchPL-HourlyCollection" /V /FO LIST
```

The task runs `monitor-gpus --send --quiet` only while the current Windows user is
signed in, avoids overlapping runs with an exclusive local lock file, and appends
clear output to the ignored `data/logs/hourly-monitoring.log`. The lock records its
process ID and is cleared if that process is gone (or after two hours). A nonzero
run also attempts a best-effort local `msg.exe` popup; that popup is independent of
Discord and cannot change monitoring results. To stop the schedule, run:

```powershell
.\scripts\unregister-hourly-collection.ps1
```

Inspect local price history without collecting or sending a notification. The recent
minimum defaults to the preceding 30 days and, like the all-time low, considers only
available observations:

```powershell
uv run dealwatch xkom price-history 1318534
uv run dealwatch xkom price-history 1318534 --days 14
```

The history JSON also includes reusable price-change and 7/30-day statistics. A price
change compares the newest available observation with the prior available one.
Window averages and medians are time-weighted: an available sampled price represents
the interval until the next observation, so unchanged hourly samples show how long a
price persisted. A gap greater than two hours breaks that coverage instead of being
assumed to have kept the old price.

To avoid misleading results, each 7/30-day statistic is emitted as
`"insufficient_history"` with `average` and `median` set to `null` unless it has both
at least 80% actual time coverage and at least 80% of the expected hourly available
observations. The JSON reports the observed count, required count, coverage seconds,
and coverage ratio for each window. This is expected until the hourly collector has
accumulated enough local history.

## Manual deal-candidate evaluation

Run one normal x-kom collection, persist it, and inspect rule-based candidates without
sending Discord notifications:

```powershell
uv run dealwatch xkom evaluate-gpus
```

The output reports how many products were evaluated, counts their factual history
baselines (`young_history`, `sufficient_7d`, or `sufficient_30d`), and gives each
candidate its price, reasons, comparisons, fingerprint, and M6 notification
eligibility. The first version requires at least `100 PLN` plus: `8%` below a 7-day
median, `10%` below a 30-day median, `5%` below the prior all-time low, or (when
history is young) an `8%` drop versus the previous available price. A new 30-day low
requires `8%` plus sufficient 30-day coverage. Retailer old prices are supporting
evidence only, never a qualification on their own.

Candidate fingerprints use `m7:v1:{currency}:{price_to_two_decimals}` and are
product-scoped by M6.
The same product at the same price is therefore deduplicated indefinitely in this
version. Re-arming after price recovery or a cooldown is intentionally deferred.

To configure a Discord webhook locally, copy the safe template to `.env`, then paste
the URL after `DISCORD_WEBHOOK_URL=`. The real `.env` is ignored by Git; only
`.env.example` is tracked.

```powershell
Copy-Item .env.example .env
notepad .env
git check-ignore -v .env
```

The CLI loads `.env` automatically and leaves an already-set shell variable unchanged.
To send an explicit test notification for one in-stock x-kom product, pass an ID
emitted by `collect-gpus`:

```powershell
uv run dealwatch xkom notify-test 1318534
```

`notify-test` is an explicit operator action and can be repeated. It also persists
the collection it performs.

Future notification delivery should use `dealwatch.notification_state.deliver_once`:
it checks the caller-provided fingerprint, invokes the transport, and records the
event only after that transport succeeds. Failed deliveries remain eligible for a
later retry. Notification audit records never contain webhook URLs or secrets; use a
non-secret destination label such as `discord:dealwatch-test` if a destination needs
to be recorded. The monitoring command stores a one-way hash-derived destination
label. If Discord accepts a post but SQLite cannot record it afterwards, the run
fails prominently and a later run may duplicate that alert; this distributed-delivery
edge is intentionally visible rather than hidden.

## Development

```powershell
uv run ruff check .
uv run pytest
```

Tests use saved HTML fixtures and mocked HTTP clients; they do not contact x-kom or
Discord.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md). The documented retrieval, history, and
notification-state decisions are in [docs/decisions/](docs/decisions/).

## Disclaimer

This project is intended for personal/educational use. Retailer websites should be accessed responsibly and with reasonable request rates.
