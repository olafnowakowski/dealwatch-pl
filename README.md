# DealWatch PL

DealWatch PL is a Python service for monitoring Polish electronics retailers and detecting genuinely good technology deals.

The long-term goal is to monitor retailers such as x-kom, Morele, Komputronik and others, build historical price data, evaluate whether a discount is actually attractive, and automatically send relevant deals to Discord.

## Current Status

🚧 Early development

Current MVP:

x-kom → GPU products → normalized product data → Discord notification

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

## Initial Architecture

Retailer
↓
Store Adapter
↓
Normalized Product
↓
Deal Engine
↓
Discord

Storage and historical price tracking will be added after basic collection is working.

## Development Approach

Retailer data retrieval should use the simplest reliable method available:

1. JSON/API endpoint
2. HTTP + HTML parsing
3. Browser automation
4. External scraping services such as Firecrawl

More complex scraping technology should only be introduced when simpler methods are insufficient.

## Tech Stack

The final stack has not yet been decided.

Expected core technologies:

- Python
- SQLite initially
- Discord Webhooks
- HTTP-based scraping where possible

## Roadmap

### Phase 1 — MVP

- [ ] Investigate x-kom product data
- [ ] Create normalized product model
- [ ] Implement x-kom GPU collector
- [ ] Add tests
- [ ] Send test deals to Discord

### Phase 2 — Price Intelligence

- [ ] Store products
- [ ] Build price history
- [ ] Prevent duplicate notifications
- [ ] Implement basic deal detection
- [ ] Add scheduled monitoring

### Phase 3 — Multiple Stores

- [ ] Morele
- [ ] Komputronik
- [ ] Media Expert
- [ ] Other retailers

### Phase 4 — Advanced Deal Detection

- [ ] Cross-store product matching
- [ ] Cross-store price comparison
- [ ] 7/30/90-day statistics
- [ ] Historical lows
- [ ] Deal Score

## Disclaimer

This project is intended for personal/educational use. Retailer websites should be accessed responsibly and with reasonable request rates.