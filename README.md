# DealWatch PL

DealWatch PL is a Python service for monitoring Polish electronics retailers and detecting genuinely good technology deals.

The long-term goal is to monitor retailers such as x-kom, Morele, Komputronik and others, build historical price data, evaluate whether a discount is actually attractive, and automatically send relevant deals to Discord.

## Current Status

🚧 Early development — x-kom GPU collection, SQLite price history, and a Discord
delivery test are implemented and verified.

The current milestone is x-kom → GPU products → normalized product offers → local
SQLite observations → an explicit Discord delivery test. It deliberately does not
yet include deal scoring, automatic alerts, scheduling, or other retailers.

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

See [docs/roadmap.md](docs/roadmap.md). The documented retrieval decision is in
[docs/decisions/0001-xkom-http-hydration.md](docs/decisions/0001-xkom-http-hydration.md).

## Disclaimer

This project is intended for personal/educational use. Retailer websites should be accessed responsibly and with reasonable request rates.
