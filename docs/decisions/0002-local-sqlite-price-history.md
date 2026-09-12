# Use local SQLite for initial product and price-history persistence

## Context

The x-kom collector produces stable product identities and time-bound offers, but
the application needs local history before it can evaluate price changes later.

## Decision

Use SQLite at `data/dealwatch.sqlite3` by default. Keep product identity in a
`products` table keyed by `(retailer, retailer_product_id)`, using x-kom's product
ID as the external identifier. Store each successful collection's offers in an
append-only `price_observations` table. Store currency values as canonical decimal
text to avoid SQLite floating-point rounding.

## Consequences

Repeated collection updates mutable product metadata without duplicating products and
adds a new price observation every time. The local database directory is Git-ignored.
No deal scoring, notification deduplication, scheduling, external database, or
migration framework is introduced in this milestone.
