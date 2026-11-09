# Coherent scheduler observation and foreground progress

Decision: 2026-11-08, before implementation. The owner authorized correction of
two demonstrated consistency defects after the separate diagnostic release.
Neither defect is retrospective attribution of the 00:46 scheduler alert:
that incident did not retain the pulse ages needed to establish its cause.

## One late temporal observation

Health currently reads a lease and holder instance in separate statements, then
samples database time after other work. A newer committed pulse can be absent
from the saved instance sample while its age is computed against a later clock.
Keep observation integrity, unresolved broker outcomes and notification checks,
then read the compact temporal policy inputs in one final MVCC statement:
control, lease, its exact holder instance, callback boundaries, latest relevant
cycle, certificate lifecycle/revocations and one database clock sample. Move
these reads rather than adding another round of readiness verification. Do not
hold an old repeatable-read snapshot while waiting for time to advance.

The late control generation, enabled/kill state and complete binding must equal
the control subject whose immutable lineage was validated earlier. A changed
subject refuses without an automatic retry. Same-generation authority verdict
fields are observations, not control transitions; consume their late values.
Preserve missing-singleton refusal, current-holder selection, negative-age
rejection, original lease duration, callback deadline, cycle wake/protected-wait
boundaries and certificate expiry/revocation semantics. PAPER observation-only
authority retains its existing distinct expiry rule. A query timeout remains an
unobservable dependency; it cannot establish a scheduler stall or readiness.

This is a bounded database observation, not broker/execution authority or a new
financial proof. It does not refresh old financial evidence or widen any window.

## One foreground publication

Instance registration and lease renewal currently commit separately. Even a
coherent reader can observe an instance whose timestamp predates the latest
successful foreground lease renewal by nearly a whole lease interval.

Add an explicit foreground instance publication to the existing acquire/renew
operations, preserving callers which request a lease alone. Production main-loop
progress and acquisition select this mode. Commit the exact instance progress
and its lease pulse together from one sampled database timestamp; moving two
different timestamps into a long transaction is insufficient. Owned renewal
keeps its existing path without the financial writer lock. New acquisition
retains that lock and all existing holder/fence/control/expiry predicates.

A missing or foreign permit may publish only its own instance state. A stale
foreground permit is discarded without acquiring another lease. There is no
background idle renewal: a blocked foreground stage must still expire. The
instance exists before first acquisition. Callback renewal remains a distinct
mode: require the existing exact callback instance and unexpired invocation,
renew its heartbeat atomically with the lease, and preserve its original start
and deadline. Never upsert a callback or turn renewal into a new invocation.

Wait for the lease and existing instance row locks before sampling the shared
pulse. A renewal that waited past lease or callback expiry must refuse. These
bounded row-lock reads establish the publication boundary; they are not repeated
readiness proofs. A caller creating a previously missing instance can still wait
on a concurrent uncommitted insert of that same identity after sampling. Its
aligned pair then conservatively retains the older timestamp; it never gains an
extended lease. Production uses one incarnation owner and publishes its instance
before acquisition, rather than adding retries for this cold-row case.

No schema, Wealth Core, controller, account, broker, command, financial window
or notification-history change is selected. The economic manifest and frozen
dependencies remain unchanged; retained runtime source compatibility is qualified
separately after the application bytes are finalized.

Negative leadership decisions may carry a closed optional scheduler diagnostic
from these same sampled facts, with exact failed predicate, original pulse and
callback times, generation/fence/process holder, freshness flags and finite
monotonic read duration. Existing early returns leave it absent. This adds no
queries and cannot renew a clock or alter policy. The alert owner handles bounded
emission and immutable occurrence compatibility separately.

## Acceptance and falsifiers

Use private PostgreSQL and deterministic reader interleavings, never production
fault injection. A pulse committed during earlier health work must be read at
the final boundary; an actually stale holder with a fresh standby must still
fail. Future pulses, expired leases, changed control and revoked/expired
certificates remain refusals. Independent connections must see the old committed
instance/lease pair until publication commits, then the aligned new pair.
Remove the late-read or paired-publication guard in memory and require these
regressions to fail. Preserve existing callback deadline and genuinely blocked
main-loop expiry tests. No full historical strategy suite is required.
