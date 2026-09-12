# Use a one-shot, circuit-broken monitoring command for automatic delivery

## Context

DealWatch has a pure M7 candidate engine, M6 notification-state persistence, an
explicit Discord transport, and an existing hourly Windows Task Scheduler wrapper.
The project needs automatic delivery without introducing a second scheduler, coupling
the deal engine to Discord, or risking a large alert burst from bad retailer data.

## Decision

Add `dealwatch xkom monitor-gpus`. It performs exactly one cycle: collect offers,
persist observations, evaluate M7 candidates, check their M6 fingerprints, deliver
eligible candidates serially when `--send` is explicit, and persist each notification
event only after a successful Discord response. The default is dry-run and cannot
send or write notification state.

Before selecting an optional `--only-product`, count every eligible candidate. If more
than three exist, trip a hard circuit breaker: send none, persist no notification
events, report the condition, and exit nonzero. A webhook failure has no in-process
retry, leaves the candidate eligible for a later external-scheduler run, and does not
stop later candidates. The run reports baseline and signal aggregates for threshold
inspection.

The Windows Task Scheduler task keeps its existing name and invokes the existing
runner file, which now calls `monitor-gpus --send --quiet` under its exclusive lock.

## Consequences

M7 remains transport- and persistence-independent, and M6 still owns only successful
notification state. The audit record uses a hash-derived non-secret webhook identity,
not the raw URL. If Discord accepts a message but SQLite fails before the successful
event can be stored, the run reports a potentially duplicated future delivery instead
of claiming an atomic distributed transaction. Re-arming, cooldowns, new scheduler
infrastructure, and a Deal Score remain out of scope.
