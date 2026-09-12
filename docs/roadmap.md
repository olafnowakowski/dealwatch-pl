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

## M5 — Price History Logic 🚧

Goal: Provide usable historical price information for products.

Planned:

- [x] retrieve ordered observations
- [x] historical minimum from available observations
- [x] configurable recent minimum from available observations
- [x] current and previous observation retrieval
- averages/medians over useful periods
- price-change calculations

Exact statistics should be decided when enough real observations exist.

---

## M6 — Notification State & Deduplication

Goal: Ensure users are not repeatedly notified about the same unchanged deal.

Planned:

- record sent notifications
- know which price triggered an alert
- notify again only after meaningful conditions change
- support cooldown/state logic where appropriate

---

## M7 — Basic Deal Detection

Goal: Determine whether a price is genuinely attractive using DealWatch's own history.

Initial signals may include:

- price drop vs previous observation
- price vs recent median
- recent historical low
- retailer old/regular price as a secondary signal

Avoid relying solely on retailer promotion labels.

Advanced scoring is not required yet.

---

## M8 — Automatic Monitoring

Goal: Run DealWatch automatically.

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

Current milestone: **M5 — Price History Logic**.

Completed end-to-end pipeline:

```text
x-kom
→ GPU collector
→ normalized product
→ SQLite price observation
→ CLI
→ Discord webhook
→ verified real notification
```

The next goal is to expose useful history calculations before implementing deal
intelligence.
