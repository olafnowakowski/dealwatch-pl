# Use caller-defined fingerprints for successful notification state

## Context

DealWatch needs to avoid repeating a Discord alert after a future deal detector has
identified it. The criteria for equivalence will vary by retailer and future rule, so
SQLite persistence must not infer a price threshold, cooldown, or deal score.

## Decision

Store successful notification events in a `sent_notifications` SQLite table associated
with the existing stable `products` identity. The caller supplies an alert type, a
stable fingerprint, and an optional reason. Product identity plus fingerprint is the
unique key: the caller therefore defines what counts as the same alert.

Optional audit fields include observed price, currency, sent timestamp, and a
non-secret destination label. The schema deliberately has no webhook URL or secret
column; destination labels that look like URLs are rejected by the event model.

Use `deliver_once` as the generic post-delivery coordinator. It checks whether the
fingerprint was already recorded, invokes a transport callback, and records state only
when that callback returns successfully. A failed callback leaves no successful state,
so retry remains possible.

## Consequences

M6 can deduplicate a caller-selected alert without deciding whether it is a deal.
The state is reusable across future retailers and delivery transports. A process crash
after a transport succeeds but before SQLite records the event can still permit a
later duplicate; handling that distributed-delivery edge case requires a future
transport-specific delivery protocol and is outside this local persistence milestone.
