# Operational rolling publication boundary

This slice extends #390's snapshot input adapter with opt-in, receipted corpus
publication. It does not install a GO or scheduler callback or admit durable
strategy state. Publication, state admission and execution authority remain
separate. The existing paper-only, producer and backup rules apply.

The subsequent [GO input integration](rolling-go-inputs.md) now uses this
publication boundary for preparation and read-only data probes. It still
refuses runtime activation; service and authority integration remain pending.

## One publication transaction

Reuse the ordinary corpus version sequence, append-only validation receipt,
receipt HMAC, predecessor receipt chain and transaction-specific PITR target.
Extract the existing receipt/row insertion into a transaction-only helper;
the legacy publisher keeps its existing commit semantics. The rolling publisher
holds the common corpus writer/backup lock and atomically inserts the ordinary
publication, immutable snapshot binding, and job PUBLISHED outcome. No vendor
I/O occurs inside this final transaction. Rollback leaves all three invisible.

An explicit operational job registration distinguishes operational acquisition
from a comparison request without reinterpreting old serialized requests or
hashes. Operational enqueue domain-separates its dependency identity. A completed
comparison cannot be promoted. The shared acquisition worker retains its lease,
fence, checkpoints, deadline, retries, producer checks and source corroboration;
only the publication boundary differs. Operational attempts compare-and-swap the
actual ordinary publication version frozen in their request.

Use the latest source-final XNYS session, where source finality retains the
existing 23:45 America/New_York policy. A close before that time does not yet
make that session publishable. Freeze its exact 300-session axis on enqueue;
recheck the target before acquisition and visibility. A job crossing a newer
source-final boundary refuses rather than publishing stale readiness. Retries
cannot renew its original deadline. Missed execution cutoffs remain execution
policy and cannot be overridden by source publication.

The publication evidence binds candidate UUID, snapshot hash, full reference
bundle hash, source evidence, structural validation, request identity, producer
and validation time. Verify sealed content, recognized normalization/calendar,
reference/identity/action inputs through the #390 adapter before publication.
Those checks do not pretend that the builder's comparison validation is GO
authority. The operational receipt explicitly describes DATA_ONLY admission.

## Reader and state boundaries

Legacy `current`, `require_current` and `pinned` readers must refuse a rolling
publication before they can associate its version with legacy rows. The new
explicit snapshot reader verifies the ordinary receipt chain and immutable
binding and uses the same shared pin for a whole input transaction. It returns
the actual corpus version separately from snapshot input material. Ordinary
legacy publication cannot supply a rolling marker or switch an active rolling
corpus back to legacy. Existing legacy price/reference/evidence rows are retained.

An existing published legacy corpus is not sufficient evidence to admit its
strategy state into a rolling version. This boundary may publish a new data
generation, preserving the old one, but it creates no state migration. Every
rolling publication establishes an explicit history-proof baseline at that
version. Consequently an older strategy state cannot cross it using the legacy
all-history compatibility rule. This is a deliberate temporary refusal until
bounded checkpoint/live-dependency admission is implemented; do not claim daily
strategy continuation from data refresh alone. A fresh state can later begin
under an admitted version without inventing historical executions.

The binding and PUBLISHED job are cross-checked on read and by deferred database
constraints at commit. A failed worker, lost acknowledgement, or repeated call
returns its committed receipt or the existing failure; it cannot publish a
second version for the same job. A later explicit refresh is a new acquisition
with the current expected version. No database reset, retention deletion,
strategy cursor mutation, execution-plan adoption or broker access is added.

## Acceptance and next integration

Use real PostgreSQL to prove cold acquisition with empty legacy tables,
ordinary signed receipts, atomic rollback, reader exclusion, stale CAS/fence/
deadline refusal, generation/source changes, no comparison promotion, lost-ack
idempotence and repeated fresh data publication. Falsify the new guards.

Still required before operational GO: connect bounded runtime authority and
the remaining execution reference consumers, inspect failed-attempt state,
and wire daily service preparation. Opt-in fresh initialization, authenticated
checkpoints and bounded continuation are implemented. Validate NAS backup,
first GO, paper activation/next-open handling, restart and subsequent refresh.
No local synthetic test is an observed NAS GO or paper fill.
