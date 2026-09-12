# Use coverage-aware, time-weighted price-history statistics

## Context

DealWatch collects a point-in-time product offer about once per hour. A collection can
fail or be skipped, and an unavailable product must not be treated as an available
price. A simple average or median of stored rows would make a few observations look
like a trustworthy 7- or 30-day history and would give an unchanged price the same
weight whether it persisted for one hour or several days.

## Decision

Calculate history statistics in a retailer-neutral `dealwatch.history` module rather
than in CLI formatting. Use only available observations. Treat each available price as
covering the interval until the next observation, which makes repeated hourly values
represent how long that price persisted. Do not bridge a gap greater than two hours;
the missing interval contributes no coverage or price statistic.

For both the 7-day and 30-day windows, emit average and median only when both of these
requirements are met:

- at least 80% of the window has observed available-price coverage;
- at least 80% of expected hourly observations in the window are available.

The CLI returns `insufficient_history` and null statistics when either rule fails,
alongside observation counts and actual coverage so the limitation is visible.

## Consequences

Statistics are conservative during collector outages and before enough data exists.
They remain useful for a future deal detector because the calculation boundary is
independent of SQLite and the CLI. This decision does not add deal scoring, alerts,
notification state, or scheduling behavior.
