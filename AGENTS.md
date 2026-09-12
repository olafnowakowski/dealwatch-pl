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

## Git workflow

- Use Git to track all project changes.
- Before starting work, inspect the current Git status.
- Keep commits small and focused on one logical change or milestone.
- Use conventional-style commit messages where practical, for example:
  - feat(xkom): add GPU collector
  - fix(xkom): handle missing prices
  - test(xkom): add product parsing fixtures
  - docs: update project roadmap
  - chore: configure project tooling
- Do not commit secrets, API keys, Discord webhook URLs, credentials, `.env` files, or local runtime data.
- Update `.gitignore` when new local/generated files need to be excluded.
- Run relevant tests before committing implementation changes.
- Do not mark documentation or roadmap items as completed until the implementation has been verified.
- After a requested milestone is complete and verified, commit the changes and push them to the configured GitHub remote.
- Do not rewrite published Git history, force-push, or delete remote branches unless explicitly requested.
- Do not create unrelated commits or include unrelated working-tree changes.