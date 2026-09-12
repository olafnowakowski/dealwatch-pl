# DealWatch PL

DealWatch PL is a Python service for monitoring Polish electronics retailers and detecting genuinely good technology deals.

The long-term goal is to monitor retailers such as x-kom, Morele, Komputronik and others, build historical price data, evaluate whether a discount is actually attractive, and automatically send relevant deals to Discord.

## Current Status

🚧 Early development — x-kom GPU collection, SQLite price history and statistics,
hourly local history collection, and a Discord delivery test are implemented and
verified.

The current milestone is x-kom → GPU products → normalized product offers → local
SQLite observations → an explicit Discord delivery test. It deliberately does not
yet include deal scoring, automatic Discord alerts, or other retailers.

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
          ↓
coverage-aware price-history analysis
          ↓
 CLI JSON output / manual Discord test
```

`ProductIdentity` keeps retailer product identity separate from price. `ProductOffer`
records the observed price, availability, promotional information, and timestamp.
Each successful collection upserts products by retailer plus external product ID, then
appends one SQLite price observation per offer.

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

## Hourly local history collection on Windows

Automatic collection has been pulled forward solely to accumulate enough real history
for M5. The application still performs one collection and exits; Windows Task
Scheduler invokes the external PowerShell wrapper once per hour. It does not send
Discord notifications.

After `uv sync --all-groups`, register the task from the project root:

```powershell
.\scripts\register-hourly-collection.ps1
schtasks.exe /Run /TN "DealWatchPL-HourlyCollection"
schtasks.exe /Query /TN "DealWatchPL-HourlyCollection" /V /FO LIST
```

The task runs only while the current Windows user is signed in, avoids overlapping
runs with an exclusive local lock file, and appends clear output to the ignored
`data/logs/hourly-collection.log`. The lock records its process ID and is cleared if
that process is gone (or after two hours). To stop the schedule, run:

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
the collection it performs. Automated alerts and persistent notification deduplication
remain deferred.

## Development

```powershell
uv run ruff check .
uv run pytest
```

Tests use saved HTML fixtures and mocked HTTP clients; they do not contact x-kom or
Discord.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md). The documented retrieval and history
decisions are in [docs/decisions/](docs/decisions/).

## Disclaimer

This project is intended for personal/educational use. Retailer websites should be accessed responsibly and with reasonable request rates.
