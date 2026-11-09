# Bounded retention progress

Selected by the owner/root on 2026-11-08, before implementation, in the separate
`codex/retention-bounded-progress` worktree based on installed diagnostic ba05fe769.
The independently qualified operational bundle and its worktree remain frozen.
No schema, economic manifest, deployment or financial authority change is selected.

## Proven defect and storage facts

An ordered LIMIT bounds returned rows, not visits to dead index entries. The
existing retired-payload discovery repeatedly starts at an already depleted
candidate prefix. One cancelled branch of the eager seven-column scheduling
query prevents all disposal classes from reaching their guarded pass. Deletion
and the diagnostic/candidate cursor currently commit separately; RETRY can erase
the previous cursor.

The existing candidate metadata has immutable window bounds and a session_axis
of 300, 379 or 426 dates. The insertion trigger admits bars/benchmarks only on
that axis and refuses all insertion after retirement. Payload UPDATE and TRUNCATE
are forbidden. Retirement rows themselves are append-only: UPDATE, DELETE and
TRUNCATE are forbidden. New retirement still requires behavioral/corpus writer
locks, job/candidate locks and the existing complete pin checks. Candidate
metadata is never deleted. Only retention.py inserts retirement rows in current
production source; direct SQL remains subject to those same guards.

Session partitioning alone is insufficient: security_id is arbitrary bounded
text but its cardinality is not bounded, so the demonstrated 40,000 deleted keys
can all occupy one session. Reversing the scan only moves the depleted edge.

## One finite legacy bootstrap

On first use without the new progress record, read the append-only retirement
count under the existing writer/corpus locks. No retirements means no legacy
bootstrap is needed. Otherwise perform one shared physical traversal of the bar
and benchmark heaps for all already retired candidates. Do not rescan the whole
heap separately for each candidate.

For each table, bind the traversal to relation OID, current relation filenode,
and a fixed initial upper heap-block boundary. Initial extent quantum: **64 heap
pages**, independent of how many dead index entries exist. At the ordinary 8 KiB
block size this is at most 512 KiB of heap address space per extent. Use the
server's block size when deriving the fixed boundary, not an assumed file size.
No unbounded candidate-prefixed existence probe precedes this traversal.

The query must first MATERIALIZE only the selected CTID range, using PostgreSQL
16 TidRangeScan, and only then join that bounded set to retirements. Select
at most the row cap plus one eligible CTIDs in physical order. An empty extent
advances progress without authenticating an unchanged checkpoint body. For a
positive selection, authorize as below and delete only the selected capped CTID
set, retaining the same outer extent fences. Do not repeat the discovery SELECT.
A lookahead row retains the unhandled remainder; otherwise the selection proves
the extent exhausted and its successful deletion may advance to the upper bound.
Commit the deletion and this physical position in the same transaction.
The DELETE itself retains the same outer CTID bounds, so a planner choice cannot
turn bounded discovery into an unbounded whole-table modification scan.

Ordinary VACUUM does not move existing live tuples; tail truncation and a saved
extent beyond current EOF safely yield no rows. A changed OID/filenode invalidates
the physical location and starts another bounded traversal with a new fixed
upper boundary. No completed scan is reinterpreted as valid for a rewritten heap.
The existing retirement/insertion guards prevent retired payload from appearing
behind a completed position. Captured retired rows cannot acquire new payload at
a later block. New active candidate inserts do not authorize their deletion.

If a class exhausts its time budget while reading an extent, keep its last
committed position. A proposed conservative retry adaptation halves its page
quantum, down to one page, without increasing timeouts or declaring any rows
examined. Record that bounded work-plan change separately from scan completion.

## New retirement queue

After the legacy sweep, permit at most one newly retired candidate awaiting
payload completion. Retire it and initialize its logical cursor in the same
transaction. Drain bars by candidate plus the ordered (session, security_id)
primary-key seek, then benchmarks by candidate plus session. Each successful
delete advances its seek position atomically. A final empty seek is strictly
after the already deleted prefix; it never starts again at the candidate's low
key. The ordinary batch may fetch one extra key in the same bounded query to
prove the phase complete without a separate final empty seek. Finishing a table
advances its phase in that transaction; empty logical phases can share the same
class call. No separate maintenance proof is run solely for phase bookkeeping.
Completion is permanent because the retired candidate cannot accept inserts.
Only then may this owner retire another candidate. Pinned candidates still get
their bounded metadata scan cursor so one pin cannot hide later eligibility.
Reuse the existing cheap positive pin exclusions before full pin evaluation:
current publication/comparison, admitted jobs, unowned candidates and missing
action coverage cannot become deletion work. Remaining candidates still pass
the complete checkpoint-aware database pin guard before retirement.

The logical batch discovers its exact ordered keys once, then deletes only those
CTIDs with an outer exact candidate equality check. PG16 qualification found that
ordinary UUID equality plus sequential-scan discouragement still selected a
candidate Bitmap Heap Scan: 5,000 selected CTIDs visited 45,001 index tuples,
including the 40,000 dead prefix, and 693 heap blocks. Disabling metadata index
and bitmap paths removed that payload scan, but the exact unchanged deletion
trigger's nested guard then had cost 10,000,000,200.78 and compiled 11 JIT
functions. A private exact-trigger A/B measured 2.290 s versus 0.0389 s after
restoring normal metadata paths; both payload paths selected the same 5,000 TIDs.
The corrected guard cost was 198.51 with zero JIT functions. This was caught
before delivery, not attributed to the older production incident.

Use the residual equality `candidate_id::text=%s::uuid::text`. Canonical UUID
output preserves exact UUID identity, including nil, without offering the
ordinary candidate UUID index as a payload access path. Qualify NULL/foreign-TID
rejection and both actual payload and unchanged trigger plans. For this fixed
PG16 query capture actual enable_seqscan/enable_tidscan, locally discourage only
sequential scan and enable TID scan, then restore those actual values on success.
Require metadata indexscan and bitmapscan enabled; an unsupported caller profile
refuses without changing those settings or JIT thresholds. A class
SAVEPOINT rollback restores them on error; no finally query may mask the original
cancellation. This is local disposal planning, not global database tuning.
Disabling sequential scan discourages rather than universally prohibits that
plan. Qualify every payload scan node on the fixed PG16 query, including a large
CTID array and the removed-bias falsifier. Unsupported access must refuse under
the finite quantum rather than silently claim bounded physical work. Do not run
per-batch EXPLAIN or introduce another preparation framework.

Physical bootstrap admits only its qualified PG16 heap/TID configuration. A
disabled TID path or unsupported major version is a class-local refusal, not
permission for an unbounded fallback or a self-sustaining unknown retry loop.

### Acquisition pin compilation boundary

The real-schema incremental regression exposed separate avoidable compilation
inside the unchanged canonical acquisition-pin function. On the identical
populated private database, the exact one-part selection took 258.4 ms with JIT
and 20.6 ms without it. Its nested pin plan had cost 132,447.59 and compiled 53
functions for each of 15 target parts; the pin body took roughly 0.3–0.6 ms
without compilation. Selection plus the final immutable guard exhausted the
500 ms class slice; a cold invocation also overran its statement bound during
compilation. An empty canonical database is a counterexample with a cheap plan
and no JIT. These are private query facts, not historical production attribution.

Suppress JIT only around the bounded acquisition work class and its read-only
hint, preserving the exact canonical pin SQL and final database guards. Capture
the actual current JIT setting, use transaction-local Off, and restore the
actual setting on success. A private savepoint restores it and the class's own
changes on failure; cleanup must not mask the original exception. Existing
class, hint, pass and ownership bounds remain unchanged. Do not change global or
session configuration, JIT thresholds, the installed function, or guard logic.
Function-local DDL and a new set-valued pin function would require a separate
database migration and are not selected for this application-only patch.

This removes repeated compilation, not the underlying canonical lineage
verification. The retained plan also scans 600 synthetic price rows to discover
15 part identities before LIMIT 1, so this patch does not claim the acquisition
discovery query has bounded physical work. Further discovery/lineage changes
require their own measured design and preserved pin semantics.

The progress record tracks the known retirement count. Our own retirement and
its count increment are committed together with the active cursor. Because the
set is append-only, equal counts identify an unchanged set; there is no timestamp
ordering assumption. An unexplained larger count means another guarded owner or
operator inserted a retirement not represented by our active queue. Start a new
finite shared bootstrap instead of skipping it. A decreasing count, malformed
progress or impossible cursor is an integrity/refusal condition for that class;
never silently declare old payload absent. Rebootstrap is conservative data
cleanup only, not financial authority or permission to retire a candidate.

## Constant-size progress format

Use the existing singleton diagnostic JSONB, without DDL or a completed-ID cache.
The selected logical format is:

```json
{
  "schema": "sentinel.retention-progress/1",
  "known_retirement_count": 12,
  "metadata_cursor": null,
  "next_class": 0,
  "legacy": {
    "phase": "BARS",
    "relation_oid": 123,
    "relation_filenode": 456,
    "upper_block": 789,
    "position_block": 0,
    "position_offset": 0,
    "page_quantum": 64
  },
  "active": null
}
```

legacy is null when its sweep is complete; its phase is BARS or BENCHMARKS.
active, when present, contains candidate_id, phase, last_session, last_security_id
and row_quantum (initially 5,000; halve on cancellation to a minimum of one).
Its phase is BARS or BENCHMARKS. The last session/key are both null before the
first bar batch; BENCHMARKS has no security key. The effective row cap is the
minimum of the caller cap and row_quantum. There is no dynamic list of candidates
or completed blocks. Metadata
cursor and active IDs are strict UUIDs; dates, CTID components, nonnegative counts,
phase transitions and page limits are validated. The old scan_cursor can seed
only metadata_cursor, never claim legacy payload traversal. Missing progress
starts conservative bootstrap; malformed/new-unknown progress retains payload
and is visibly retryable. The final typed schema will be recorded before code.

## Fair classes and bounded admission

The seven independent work classes remain expired jobs, new candidate retirement,
retired payload, retired evidence, obsolete scratch, acquisition parts/prices,
and normalized blocks. Their scheduling predicates are hints, never deletion
permission. Do not read payload to prove scheduling absence.

Selected budgets: preserve the original **one-second total probe ceiling**
and **five-second total pass admission quantum**, never raise the existing
five-second mutation statement ceiling. Individual metadata hints have at most
100 ms; a timeout is UNKNOWN/possible, not false and not a global refusal. Stop
once known possible work suffices for guarded admission; unchecked classes remain
possible rather than being asserted empty.

Under the existing ownership/backup checks, rotate first class using next_class.
Each class gets a savepoint and at most **500 ms** of the remaining admission
quantum, with 200 ms reserved for bounded progress publication. Recompute SQL
timeouts from the remaining class/pass budget before admission; reject late
class results rather than extending a clock. A cancellation rolls back only that
class, advances fair scheduling, and permits independent classes to run while
the pass has budget. Partial successful work and its exact cursor survive.
The common current-checkpoint authentication remains mandatory before every
mutation category, including expiry, retirement, evidence, scratch, acquisition
and normalized payload writes. Run the full original origin/daily HMAC reads
lazily before the first positive mutation in the pass; reuse success only while
the same writer and corpus locks and transaction remain held. Bounded selection
may precede authentication, but no data mutation may do so. Empty traversal and
progress bookkeeping need no unchanged bulk checkpoint read. A failed common
proof is remembered only for this pass, so later classes cannot repeat it or
authorize another mutation. No cross-pass, cross-connection or persisted
authorization cache is selected.

Mutable scratch/price rows selected before authentication are row-locked while
ownership remains held, preventing deletion/reuse of their CTIDs during the
proof read. Retired snapshot rows already have the stronger immutable-generation
and corpus-writer boundary. Exact selected identities feed mutation directly;
do not rerun a disposal selection after authentication.

Authentication uses the remaining absolute five-second pass budget and original
five-second statement ceiling, rather than the class's 500 ms slice. After the
first successful authentication, the mutation gets at most 500 ms of the remaining
pass budget. Cached same-pass authorization does not restart another class's
budget. An authentication timeout does not shrink a payload batch: reducing rows
cannot repair an unavailable proof. If common ownership/checkpoint evidence is
unavailable, all dependent data stays intact while safe progress-only work can
still commit.

These are conservative admission bounds, not a claim that the host, a blocked
COMMIT or an unavailable dependency can be forced to run within wall time. Late
or unobservable outcomes never authorize more work. Resource waits use existing
finite database bounds; lost commit acknowledgement is resolved by rereading the
atomic data/progress state on the next ordinary wake.

Savepoint-success mutations, scan positions, candidate cursor, retirement count
and class rotation are written before the one commit while ownership remains
held. Outer failure rolls back all new state. A subsequent RETRY diagnostic write
updates only outcome fields and merges/preserves the latest committed progress,
including concurrent progress; it never writes a stale full diagnostic over it.

Continuing the existing idle drain loop requires actual committed deletion or
traversal/queue progress. Merely rotating unknown classes or repeating failed
observations does not count as progress and must not create a hot retry loop.
Otherwise retry occurs at the next existing ordinary wake. Opening-window
deferral remains before maintenance ownership. No background worker is added.

The installed supervisor admits maintenance once per 300 seconds, so one empty
64-page extent per wake would make legacy convergence unnecessarily slow. The
64 pages and 5,000 selected rows bound each SQL quantum, rather than the entire
class. Within its existing 500 ms slice, the legacy class may finish up to 64
extents, stopping at its caller's total payload-row cap or time boundary. It
reserves 25 ms within that slice for rollback and returning completed progress.
Every extent has an inner savepoint: canceling the last attempted extent rolls
back that extent, while earlier completed extents and their cursor remain in
the class transaction. The outer late-result guard still rejects a class that
cannot return before its original deadline. The other six classes retain their
own finite slices and rotation; no poll interval or deadline is widened.

Before sampling each heap witness, acquire ACCESS SHARE on that payload relation
inside the same budget. This closes the gap between a metadata function's short
relation access and the first physical SELECT. The witness is checked once per
relation in this class transaction and is reused only while that lock remains
held. A successful rewrite cannot
interleave with those reads. The first authentication attempt uses its separate
remaining pass budget; its duration is excluded from the mutation slice whether
it succeeds or fails. Cached success or failure never restarts that clock. A
failure cannot authorize mutation, but earlier empty extents may still be
checkpointed. All completed extents and actual deletions persist together at the
existing single pass commit. This improves bounded progress at the actual wake
cadence; it does not promise a cleanup completion time.

## Qualification and delivery scope

The private CI test lens must select PostgreSQL 16 explicitly, matching the
production retention access contract. Debian's unversioned `postgresql` package
currently selects 17 and cannot qualify the PG16-only physical and logical
planner paths. Install versioned server/client packages from the
[signed PostgreSQL Apt repository](https://www.postgresql.org/download/linux/debian/),
verify its published signing-key fingerprint, and assert major version 16 in
the lens build. This changes test tooling only; the deployable runtime and the
production `postgres:16` selection remain unchanged.

Before implementation, prove the actual MATERIALIZED CTID query's PG16 plan and
cumulative buffer work on a private already-depleted prefix, with an old ordinary
MVCC snapshot that holds no canonical corpus/advisory read lock. Count heap/index
work over multiple extents and partial batches, rather than asserting latency.
The held snapshot is a valid amplification test, not historical attribution.

Test initial legacy bootstrap, partial final extent, ordinary VACUUM/tail shrink,
rewrite witness, unknown newly inserted retirement, restart and malformed/old
progress. Remove traversal/seek advancement in memory and require failure of the
cumulative-work/convergence assertion. Inject failure between DELETE and progress
publication and simulate lost commit acknowledgement: either both persist or
neither does. A cancelled class must not roll back another class's completed
work. A pass with only unknown/no progress must stop its idle retry loop.

Keep actual current/ancestor checkpoint, active reader, job, comparison, action
archive and acquisition-ancestor pin refusals. Preserve behavioral/corpus writer
locks, backup requirement and the exact opening window. No production query,
vacuum/reindex, timeout increase, broker call or financial-source compiler edit
is part of qualification. Work remains retention.py, focused tests and the new
design document. Release/sealing of the other four fixes proceeds independently.

## Qualified access mechanism, before application implementation

The private PG16 qualification succeeded on 2026-11-08 with 41,000 synthetic
rows, the first 40,000 deleted, and an old ordinary repeatable-read snapshot
held without a corpus pin. The original indexed one-row probe still performed
40,001 heap fetches and 860 buffer accesses. The proposed actual bounded DELETE
and measured position committed 17 passes with a 127-row cap, removed all 1,000
remaining rows, and traversed a 631-page heap with 798 cumulative range-buffer
accesses. Every heap scan was Tid Range Scan; none exceeded the 64-page extent.
The partial final extent advanced only to each batch's last deleted CTID.

Artifact: `/var/tmp/retention-physical-bootstrap-20261108T021945Z/result.json`.
Harness: `.codex-tmp/retention-physical-bootstrap-proof-20261108.py`.
The disk-backed private server used pinned PostgreSQL 16, 0.5 CPU, 256 MiB and
network none; exact-ID finally cleanup removed it. The initial harness attempt
misclassified a ModifyTable parent as a scan and stopped safely; correcting
that measurement filter produced the successful run. These work counts prove
the access mechanism, not application pin safety, deadline fairness or release
readiness. Those remain implementation acceptance gates.

The completed implementation subsequently passed 101 focused private tests:
90 progress/hint/scoped-compilation cases, the unchanged real reader-pin
incremental regression, and 10 real-schema cap/guard/ownership/backup/opening
and acquisition-ancestor cases. The implementation source was identical across
all final processes. Full commands, hashes, default-settings causal A/B,
executed falsifiers and the remaining acquisition-discovery boundary are in
`.codex-tmp/retention-final-qualification-20261108.md`.
