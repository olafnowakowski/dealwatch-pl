# DealWatch PL Roadmap

## Project Goal

Build a reliable service that monitors Polish electronics retailers, builds historical
price data, detects genuinely attractive deals, and sends relevant notifications to
Discord.

The project should evolve incrementally. Do not implement later milestones before
earlier foundations are verified unless explicitly requested.

---

## M0 — Repository Foundation ✅

- Git repository
- GitHub remote
- AGENTS.md
- README.md
- documentation structure
- linting/testing setup

---

## M1 — x-kom Product Discovery ✅

Goal: Determine the simplest reliable method for collecting x-kom GPU listings.

Completed:

- x-kom server-rendered product state identified
- HTTP-based collection selected
- browser automation not required for current implementation
- pagination and rate limiting handled

---

## M2 — Normalized x-kom GPU Collection ✅

Goal: Reliably collect x-kom GPU products into a normalized application model.

Completed:

- x-kom GPU collector
- normalized product identity/model
- pagination
- retry handling
- fixtures
- automated tests
- CLI command

Example:

```text
dealwatch xkom collect-gpus
```

---

## M3 — Discord Notification MVP ✅

Goal: Verify the complete x-kom → application → Discord pipeline.

Completed:

- Discord webhook support
- Discord embed formatting
- manual notification command
- real Discord notification successfully verified

Example:

```text
dealwatch xkom notify-test PRODUCT_ID
```

Automatic deal notifications are intentionally not enabled yet because deal logic is
not implemented.

---

## M4 — SQLite Persistence & Price History ✅

Goal: Persist product identities and historical observations locally.

Completed:

- SQLite only
- product identity stored separately from observations
- stable store/external ID prevents duplicate products
- repeated collection records price observations
- current price and currency stored
- regular/old price stored when available
- availability and observation timestamp stored
- database files excluded from Git
- automated persistence tests

Do not implement deal detection yet.

---

## M5 — Price History Logic ✅

Goal: Provide usable historical price information for products.

- [x] retrieve ordered observations
- [x] historical minimum from available observations
- [x] configurable recent minimum from available observations
- [x] current and previous observation retrieval
- [x] absolute and percentage change versus the previous available observation
- [x] coverage-aware, time-weighted 7-day average and median
- [x] coverage-aware, time-weighted 30-day average and median
- [x] available observation counts and actual coverage for each statistics window
- [x] explicit sufficiency rules that suppress incomplete-window statistics

The hourly collector was pulled forward in M8 specifically so real observations can
accumulate while M5 statistics remain intentionally conservative about missing time.

---

## M6 — Notification State & Deduplication ✅

Goal: Ensure users are not repeatedly notified about the same unchanged deal.

Completed:

- successfully delivered notification events persisted in SQLite
- notification identity tied to the normalized retailer product identity
- caller-defined alert type, reason, and fingerprint stored for future rules
- observed price, currency, sent time, and non-secret destination label supported as audit data
- equivalent fingerprints queried and stored idempotently per product
- state recorded only after a caller-supplied delivery callback succeeds
- failed delivery remains eligible for retry

M6 intentionally does not define a deal, a cooldown, or an automatic notification.

---

## M7 — Basic Deal Detection ✅

Goal: Determine whether a price is genuinely attractive using DealWatch's own history.

Completed:

- deterministic, configurable rule-based candidate engine
- historical 7/30-day median, low-price, and previous-price signals
- coverage-aware history baseline exposed for every evaluation
- young-history sharp-drop fallback
- retailer old/regular price used only as supporting evidence
- stable candidate fingerprints for M6 eligibility checks
- manual candidate-inspection CLI with no automatic delivery or state writes

No Deal Score, automatic alert, cooldown, or re-arming policy is included. Same
product/same-price candidates remain deduplicated indefinitely until a later milestone
introduces an explicit re-arming rule.

---

## M8 — Safe Automatic Deal Delivery ✅

Goal: Safely connect M7 deal candidates to Discord through M6 notification state.

Completed:

- one-shot `dealwatch xkom monitor-gpus` monitoring command
- dry-run by default; explicit `--send` required for Discord delivery
- collection, SQLite observations, M7 evaluation, M6 eligibility, Discord transport,
  and post-success notification-state recording in that order
- serial delivery with no in-process webhook retry; failed candidates remain eligible
  for a later scheduled run
- hard three-eligible-candidate circuit breaker that sends and records nothing when
  tripped
- non-secret hash-derived Discord destination identity in notification audit records
- compact scheduler JSON summaries with history baseline and candidate signal counts
- existing hourly Windows Task Scheduler runner updated in place, retaining its
  overlap lock and task name
- best-effort local `msg.exe` notification for nonzero monitoring runs

The hourly external scheduler was originally pulled forward to gather the historical
data needed by M5. It now invokes safe M8 monitoring rather than collection alone;
no long-running Python scheduler was added.

Preferred architecture:

- application performs one monitoring cycle and exits
- external scheduler invokes it periodically

Possible schedulers:

- Windows Task Scheduler for local use
- cron/systemd timer for Linux/VPS later

Do not build a permanent while-loop scheduler unless there is a clear reason.

---

## M9 — Morele Support

Goal: Add the second retailer and validate the store-adapter architecture.

Requirements:

- Morele-specific collection logic remains isolated
- returns the same normalized product model
- existing storage/deal logic should require minimal or no changes

---

## M10 — Cross-Store Product Matching

Goal: Recognize the same physical product across multiple retailers.

Example:

```text
x-kom:  Gigabyte GeForce RTX 5070 Ti Gaming OC 16G
Morele: Gigabyte RTX 5070 Ti Gaming OC 16GB
→ same product
```

This enables:

- market price comparison
- cheapest-store detection
- stronger deal confidence

---

## M11 — Advanced Deal Intelligence

Potential features:

- 7/30/90-day statistics
- historical lows
- cross-store market median
- Deal Score
- unusual price-drop detection
- configurable thresholds
- category-specific rules

Only implement once sufficient historical and cross-store data exists.

---

## M12 — Additional Retailers & Categories

Possible retailers:

- Komputronik
- Media Expert
- RTV Euro AGD
- others where technically and legally reasonable

Possible categories:

- GPUs
- CPUs
- monitors
- SSDs
- RAM
- peripherals

Expand incrementally rather than adding many retailers at once.

---

## M13 — Production Deployment

Potential work:

- Docker
- VPS deployment
- health checks
- logs
- failure notifications
- backup strategy
- CI/CD

Do not introduce production infrastructure prematurely.

## Current Status

Current milestone: **M8 — Safe Automatic Deal Delivery is complete**, with a verified
manual-only guarded x-kom reference-price bootstrap available for separately approved
rollout.

Completed end-to-end pipeline:

```text
x-kom
→ GPU collector
→ normalized product
→ SQLite price observation
→ M7 deal candidate
→ M6 eligibility
→ Discord webhook (when `--send` is explicit)
→ post-success notification state
```

The automated delivery flow is protected by the M8 circuit breaker. The next roadmap
work must be explicitly selected before beginning it.

---

## Guarded x-kom Reference-Price Bootstrap ✅

Goal: Make limited, source-attributed x-kom reference context available while native
DealWatch history is still young, without weakening M5 statistics or changing the
hourly scheduler automatically.

Completed:

- x-kom `priceInfo.minPrice` maps only to the retailer-scoped
  `xkom_reported_lowest_price_last_30_days` reference kind
- separate SQLite reference-evidence episodes preserve first/last seen times without
  entering `price_observations`
- only the latest identical reference extends an episode; changed values, including a
  later reversion, create a new episode
- explicit `monitor-gpus --reference-bootstrap` enables a young-history candidate
  only when current price is at least 8% and 100 PLN below the x-kom reference
- sufficient native 7/30-day history remains primary; the x-kom value is supporting
  evidence there, never a qualifying replacement
- M6 fingerprints and the hourly `monitor-gpus --send --quiet` task remain unchanged
- live dry-run verified the guarded flow before any scheduler enablement

FPSGuru and Ceneo remain deferred. Their values must not be inserted into native
DealWatch observations if they are introduced later.
