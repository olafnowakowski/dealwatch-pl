# Keep x-kom's reported 30-day minimum as guarded reference evidence

## Context

DealWatch's M5 statistics intentionally require its own coverage-aware observations.
That history is initially sparse, but x-kom's server-rendered product data sometimes
contains `priceInfo.minPrice`, displayed by x-kom as a lowest price from the prior 30
days. Treating that retailer-provided field as though DealWatch had observed it would
make M5 averages, medians, coverage, and lows misleading.

## Decision

Map only `priceInfo.minPrice` to the source-attributed reference kind
`xkom_reported_lowest_price_last_30_days`. Store it separately from
`price_observations`, linked to the normalized x-kom product identity, with source,
retailer scope, direct product-match method, currency, 30-day reference window,
source URL, and first/last seen timestamps. Do not use `oldPrice`, promotion labels,
or `dateMinPrice` as reference history.

Persist values as contiguous evidence episodes. An identical latest episode updates
only `last_seen_at`. Any changed value creates a new row, including when a later
value returns to an older amount; old rows are never reopened or merged.

The pure M7 engine may inspect a usable direct x-kom reference. It emits the
source-attributed `below_xkom_reported_30d_minimum` signal when an available current
price is at least both 8% and 100 PLN below the reported reference. The signal can
qualify a young-history candidate only when the caller explicitly enables the
reference-bootstrap rule. With sufficient native history it is supporting evidence
only. The existing M6 candidate fingerprint remains unchanged.

`monitor-gpus --reference-bootstrap` is the explicit opt-in. The Windows hourly task
continues to run `monitor-gpus --send --quiet` without this flag until separately
approved.

## Consequences

The initial database can expose limited current retailer context without corrupting
DealWatch-native history or misrepresenting source scope. A malformed, absent, or
non-direct reference is ignored. The monitoring summary makes the number of usable
references and newly reference-created candidates visible for safe rollout.

This decision does not add external source integrations, alter M7's native thresholds,
change automatic scheduling, or implement re-arming/cooldowns. FPSGuru and Ceneo are
deferred; any future external history must remain source-attributed and outside native
price observations.
