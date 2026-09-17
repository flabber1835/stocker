# Rolling action evidence and retirement

Decision, 2026-09-17. This is first-deployment work. Failed attempts and all
immutable decisions, commands, quantities, observations and fills remain intact.

## Action evidence

The feed owns an append-only, publication-bound action archive. Each publication
extends a contiguous coverage interval, initially beginning at its first price
session (the predecessor, not an inferred event day). Sparse session records
retain canonical scalar/material outputs and their input evidence: complete
source rows, permanent identity mappings, normalization dispositions, event and
predecessor price domains, and dividend-bearing canonical bars. BIL uses the same
consecutive-session domain evidence as the existing reconciliation algorithm.
No new corporate-action interpretation or brokerage ledger is introduced.

Coverage proves that the canonical reader inspected every session in the
interval; an absent sparse record within that interval means no observed event.
It does not attest to unknown pre-open events. Source identity, snapshot and
publication provenance remain attached. The archive is sufficient to reconstruct
the accepted scalar lookup and the existing dividend-entitlement inputs after
full price payloads expire. It does not reconstruct unrelated historical prices.

Archive advancement and the publication receipt commit together under the corpus
writer lock. Rollback loses both; lost acknowledgement returns the existing
publication. Half-open action intervals `(basis, through]` preserve original
command units and prevent duplicate application. Readers require contiguous
coverage; a date before the archive's initial basis is explicitly unavailable.

Current-window evidence is compared with retained semantics, and retained source
rows are compared with the current complete ACTIONS reference response. An
observed correction to an accepted historical scalar/absence cannot silently
change its meaning. Preserve original evidence and report the affected identity
as unresolved. Ordinary unsupported events retain the existing scoped execution
policy; routine aging and cleanup do not create a global trading gate. A genuine
historical correction is distinct from aging. No full-history price download or
strategy replay is added. The existing conservative shadow reference-continuity
contract remains in force.

Execution preparation/recovery/target projection, informational-paper unit checks
and paper dividend quarantine all use retained evidence. Dividend inputs are
evidence of an entitlement under the existing calculator, never synthetic cash.

## Durable dependencies and retirement

Retain the current operational publication, latest comparison, authenticated
current/restart checkpoint, and any active preparation candidate. Current daily
checkpoint replaces the origin's price dependency; origin and exact committed
input records remain audit evidence. Historical publication/plan/command digests
are audit references, not perpetual full-price pins. Their action and cash needs
are satisfied by the archive. A publication without the archive is not eligible
for automatic retirement. Existing failed attempts are preserved as records.

Preparation jobs remain durable, including terminal outcome, request, fence and
component checksums. Deadline expiration uses the existing job operation. A
candidate owned by an unexpired job cannot retire. Unattached private candidates
are not automatically presumed abandoned. Bulk scratch rows are disposable only
after their exact worker owner has no active lease.

Retirement keeps candidate manifests and publication/job receipts, appends a
tombstone, and removes only bulk price payloads in bounded batches. Readers of a
retired payload refuse explicitly. Ordinary UPDATE, DELETE and TRUNCATE remain
forbidden. New guarded database operations check live references and the existing
behavioral/corpus locks; no trigger disabling or arbitrary session bypass exists.
Large reference/source payloads used exclusively by retired candidates may be
released while their content identities remain. Reacquisition may restore only
bytes that hash to the original identity. Small validation and receipt evidence
remains available for historical publication identity checks.

Cleanup takes behavioral ownership before exclusive corpus ownership, matching
the runtime's ordering. Shared publication pins exclude cleanup. Explicit
generation readers also take a shared transaction pin, including in read-only
transactions. Candidate/job row locks and database reference checks exclude
worker races. Tombstone plus
batch deletion is atomic; interruption either rolls back or leaves explicit
progress that the next pass resumes. Cleanup failure rolls back only maintenance,
retains extra data, records retry diagnostics, and cannot undo a valid runtime
advance. The broker-free service invokes it after successful advancement and on
ordinary successful polls; publication preparation also supplies maintenance
opportunities. No separate operator cleanup action is necessary.

## Restart, backups and policy

The current checkpoint and its complete price closure remain present for restart
and the next overlap comparison. Exact historical decision inputs and compact
action evidence remain logged PostgreSQL state. A whole-database physical restore
replays archive publication, tombstones and deletes atomically through WAL.
Existing backup authority is required by both writer locks before retirement;
base production's common locks exclude destructive overlap. No external backup
file or WAL is deleted. The second target retains the existing seven daily and
four weekly verified bases and WAL from the oldest retained base. Those physical
copies own the historical restore horizon; copying that retention period into
every overlapping live price generation would duplicate it without adding a
restore guarantee. State snapshots retain their existing daily/monthly policy.

Batch limits bound work per wake, not evidence lifetime. Diagnostics report
retained candidates and reference reasons, rows deleted, remaining work and
retryable failures. Qualification must use disposable PostgreSQL, including
deletion, restart/restore, concurrency and guard-removal falsifiers. No NAS
cleanup, GO, paper fill or deployment qualification is implied.

The metadata scan advances a durable UUID cursor, wrapping after the last
candidate. Thirty-two candidate/evidence/job entries per pass bounds bookkeeping;
the existing 5,000-row storage batch bounds payload deletion. Neither value is a
retention-age policy. Pinned candidates cannot starve later eligible candidates.
Identity evidence includes the relevant validated TICKERS rows and projected
aliases, plus the action rows supporting that identity, rather than relying on a
reference-bundle digest whose full payload may eventually retire.

## Reference inventory

| Durable reference / owner | Payload dependency and release |
| --- | --- |
| `sentinel_operational_snapshots`, `sentinel_corpus_publications` | Latest publication pins prices and references. Earlier receipts and validation hashes remain; authenticated action coverage satisfies their execution-history dependency. |
| `sentinel_snapshot_comparisons` | Latest comparison pins prices. Earlier immutable comparison, producer and validation evidence remains. |
| `sentinel_snapshot_jobs`, operational/comparison job registrations | A nonterminal preparation pins its candidate until the fenced terminal transition or deadline expiry. Completed comparison jobs defer to the latest-comparison pin. Requests, component checksums and outcomes remain. |
| `sentinel_snapshot_workers`, `sentinel_sep_staging` | Worker-to-job mapping fences scratch cleanup; terminal jobs with no matching current owner release scratch. Unknown owners are retained. |
| `sentinel_processed_sessions` origin and daily checkpoint | Authenticated current daily checkpoint pins its candidate; before it exists the origin pins its candidate. Unknown checkpoint shape refuses release. |
| Exact decision inputs, shadow state, plans, commands, observations, fills, paper mirror and quarantine | Immutable records remain. Original-unit action queries and historical cash-entitlement inputs use sparse archived evidence, not a full-price pin. |
| `sentinel_price_candidates`, snapshot validation and operational validation tables | Manifests and validation proofs remain. Shared source/reference bytes release only after **every** candidate using them retires; proof/producer references additionally prevent release. |
| Active publication and explicit generation readers | Existing shared corpus pin, plus read-only-compatible transaction pins, exclude retirement until the read finishes. |
| Backup/base production and restore authority | Existing behavioral and corpus ownership excludes cleanup; existing backup authority must pass. Historical restore points are owned by whole-database bases/WAL, not live generation copies. |

The archive intentionally retains sparse historical evidence for the existing
whole-command-history informational and cash consumers. Daily reconciliation
interprets only the current 300-session window and retained event dependencies;
it never downloads historical prices or replays the strategy. Small audit rows
and sparse action records grow with history; the bound applies to repeated full
price/reference payloads, not to immutable audit records. A genuinely active
reader/job/checkpoint or unauthenticated pre-archive publication may delay
retirement, and diagnostics identify it. No operational-book migration is inferred.

## Operational changes

Run the existing feed schema migration with the updated image. New logged tables
store action records/coverage, retirement tombstones, worker ownership and the
latest maintenance diagnostic. The existing evidence payload becomes nullable
only through guarded retirement; exact original bytes can be reacquired under
their unchanged SHA256. Migration is repeatable after cleanup. There is no new
retention-age setting, operator acknowledgement, or cleanup CLI prerequisite.

Inspect `SELECT updated_at, diagnostic FROM sentinel_snapshot_maintenance` for
deleted price/scratch rows, released evidence, sampled retained references, scan
cursor, remaining-work indication and retry status. Deletion makes PostgreSQL
pages reusable through normal autovacuum; it does not promise immediate file
shrinkage or run `VACUUM FULL`. Maintenance retries on subsequent publication
attempts and successful shadow-service wakes. A physical backup/restore drill
and NAS first-deployment qualification remain required.

The shadow service also drains pending work in its existing one-second idle
loop, between market-data polls. Each pass has independent short transactions
and releases ownership before the next pass; a retry stops draining until the
next normal poll. This uses the existing wake cadence, without changing market
acquisition frequency. One 5,000-row batch per default five-minute market poll
alone would not keep up with a full large-universe generation each day.
