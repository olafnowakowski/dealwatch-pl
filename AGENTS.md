# DealWatch PL

## Goal

Build a Python service that monitors Polish electronics retailers for genuinely good deals and sends notifications to Discord.

## Development principles

- Keep retailer-specific logic isolated in adapters.
- All retailers must eventually return the same normalized product model.
- Prefer the simplest reliable method for retrieving retailer data:
  1. JSON/API endpoint
  2. HTTP + HTML parsing
  3. browser automation
  4. external scraping service such as Firecrawl
- Do not introduce Playwright, Firecrawl, Crawlee or other major dependencies unless they provide a clear benefit.
- Do not implement future milestones unless explicitly requested.
- Keep changes small and reviewable.
- Add automated tests for parsing and retailer adapters.
- Avoid hitting real retailer websites unnecessarily in tests; use fixtures where practical.
- Preserve price history separately from product identity.
- Prevent duplicate Discord notifications.
- Respect reasonable request rates and retailer infrastructure.

## Initial MVP

Start with:

x-kom → GPU category → normalized product data → Discord notification.

Price history and advanced deal scoring come after basic collection works.

## Documentation

- Keep README.md aligned with the current state of the project.
- Update documentation when architecture or setup changes materially.
- Record significant architecture decisions under docs/decisions/.
- Do not create ADRs for trivial implementation details.
- Keep docs/roadmap.md aligned with implemented milestones.
- Mark completed roadmap items only after they have been verified.
- When implementing a GitHub issue, reference its number where appropriate.