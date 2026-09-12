# Use deterministic, coverage-aware rule-based deal candidates

## Context

DealWatch has local price observations, coverage-aware 7/30-day statistics, and
notification-state persistence, but needs to determine which newly collected prices
are worth presenting as possible alerts. The early database still has incomplete
history for many products, so a historical rule alone would miss meaningful sudden
drops.

## Decision

Use a pure rule engine that receives the current offer and only observations predating
it. It reports `young_history`, `sufficient_7d`, or `sufficient_30d` as the factual
history baseline and explains every qualifying comparison.

With sufficient coverage, local historical evidence is primary: 7-day median at least
8% and 100 PLN above current price, 30-day median at least 10% and 100 PLN above, a
strict all-time low at least 5% and 100 PLN lower than the previous low, or a strict
30-day low at least 8% and 100 PLN lower with sufficient 30-day coverage. With young
history, an 8% and 100 PLN drop from the previous available observation is allowed as
a fallback. Retailer old price is supporting evidence only.

Use a product-scoped M6 fingerprint of `m7:v1:{currency}:{price_to_two_decimals}`.
This makes repeated unchanged candidate prices idempotent without embedding delivery
state in the engine.

## Consequences

The manual `evaluate-gpus` command can inspect candidates without sending Discord or
recording notification events. Same-product/same-price candidates remain suppressed
indefinitely after a successful M6 delivery; price-recovery re-arming and cooldowns
are explicitly deferred. No Deal Score or automatic notification behavior is added.
