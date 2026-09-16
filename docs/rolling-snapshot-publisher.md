# Direct Sharadar comparison publisher

This additive stage of #384 connects preparation jobs to the real Sharadar
transport and canonical normalization. It publishes **comparison snapshots**,
not the active corpus. Legacy readers still read mutable corpus tables; putting
a generation version into their publication ledger would misidentify those
rows. Therefore a separate, immutable comparison catalog is the only new
visibility boundary. No GO, service, automation or broker route is switched.

## Acquisition and restart

The request freezes exactly 300 XNYS sessions. Monthly complete SEP exports
must have one table refresh marker. ACTIONS is explicitly a full reference
enumeration from 1900 through the target, not a 300-session reference truncation.
TICKERS field authority remains strict paginated JSON, checked against complete
CSV identity keys: NULL and empty strings must not be collapsed. SPY/BIL use the
bounded SFP request and a second reference observation. Reference observations
and export refresh markers are corroborated after loading, outside writer locks.
This is the existing Sharadar consistency mode, not vendor-wide revision pinning.

Only one monthly price partition is materialized by the existing export decoder.
PostgreSQL scratch staging sorts the complete window. There is no nested seed,
SQLite price capture, pickle replay, corpus upsert or historical action-observation
reconstruction. The canonical disk-backed membership validator remains in use;
its scratch identity keys are not another price capture or book.

Completed component checkpoints bind request/refresh identity and exact content.
Cache artifacts are reverified on reuse. Missing cache data may be reacquired,
but changed content or refresh refuses the attempt. Scratch is never a durable
checkpoint. Each worker uses a distinct scratch scope, so a reclaimed worker
cannot clear its replacement's rows. A restart rebuilds scratch from verified
components under the original absolute deadline, not a fresh budget.

The private candidate build, seal and READY transition are one PostgreSQL
transaction. A crash rolls those back; committed source checkpoints remain
reusable. A crash after READY resumes the sealed candidate after rechecking its
source evidence. This first direct implementation intentionally uses
one bounded build transaction rather than promising resumable partial normalized
loads. The existing common writer lock and backup authority protect that
transaction; no network runs while it is held. Reference corroboration follows
that private commit, then comparison publication takes a separate short lock.
The private-build lock duration includes local validation/loading and must be
measured before operational cutover. This is a
qualification limitation, not a claim of a short production publication lock.

## Validation and visibility

Reuse dated canonical identity and negative-alias discovery, independent listing
coverage, exchange-session checks and the canonical price/action normalizer.
Independent source membership, not the normalized candidate itself, supplies
the seal's expected keys. Missing raw domains, unexplained eligible absence,
duplicate identities, incomplete benchmarks and unresolved split evidence
refuse. The first session is a predecessor, not proof of a returning holding's
historical accumulated basis. Raw reference bundles and normalization diagnostics
are retained for later economic comparison and checkpoint admission.
Ordinary no-split keys are summarized per bounded batch (count and digest), not
kept as a window-sized Python set or claimed as admitted historical basis anchors.

Before acquisition, freeze the expected comparison version in an immutable
per-job attempt. Under the common writer lock, compare-and-swap that version,
recheck the expected legacy corpus version, reject older target frontiers and
recheck worker ownership/deadline after validation. A stale candidate never
becomes visible. The comparison catalog entry and the job's comparison-complete
reason become visible together, naming the already immutable manifest and
evidence. Repeating a successfully published job returns its
existing publication, including after a lost commit acknowledgement.

Comparison version numbers are **not corpus publication versions**. Jobs remain
READY with reason `COMPARISON_ONLY` and no legacy publication version; they do
not become PUBLISHED or obtain financial authority. Exact completed requests
remain coalesced: rerunning the same request returns its original comparison,
not a fresh vendor observation. This opt-in qualification path is not a daily
refresh scheduler; operational completion/rescheduling belongs to cutover.
The catalog binds the frozen
request's strategy/cursor/dependency labels, but does not attest that an arbitrary
caller-supplied dependency hash proves current durable state. Recognized checkpoint
origin, live-dependency revalidation, overlapping committed economics, action
counterparties, basis continuity, financial receipts, pinned operational readers,
retention, restore and NAS performance qualification remain cutover gates.

The opt-in Python entry point is `rolling_publisher.prepare(conn, job_id)` after
explicit schema migration and job enqueue. It owns commits/rollbacks and expects
an otherwise idle connection. It is deliberately not installed into daily GO.
Source waits release ownership and persist a next retry; permanent validation
failures refuse, cancellation interrupts, and neither extends the original
deadline. Raw exception messages or authenticated source links are not persisted
as job reasons.
Retry-After is a lower bound on the persisted retry time; a requested delay that
cannot fit the remaining deadline refuses. Writer contention and unavailable
backup media are recoverable waits, not permission to bypass either fence.
During the atomic private build, the job row shows its last committed boundary;
the existing feed-progress stream reports actual identity, normalization, sealing
and publication subphases, rows and elapsed time. Byte totals are unavailable
from this adapter and are not presented as measured download throughput.
