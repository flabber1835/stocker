# Bounded checkpoint lineage discovery

Decision and qualification plan, 2026-11-06, before implementation.

Current qualification status, 2026-11-06: the ordered-witness candidate is
PRIVATELY QUALIFIED / NOT INSTALLED. Its full synthetic large-fixture run
completed all access-plan, migration, preservation and final coverage gates.
The initial B query remains unqualified: it chose the expensive JSON fallback
scan after writes. Preserve that failure and every earlier harness refusal;
they are not passes for the ordered candidate. The complete final result and
scope limits appear below. Required CI, native installation and installed
multi-cycle stability are not established by this private qualification.

The post-installation observer captured a real SHADOW `READ_TIMEOUT` and one
expired operational snapshot. PostgreSQL logged statement-timeout cancellation
twice, at01:07:38 and01:08:02 UTC, for the same333-character lineage inventory
query in `rolling_daily_checkpoint.load`. Its SQL SHA256 is
`251c144d218a3280db4150a063c7ba6dda3ccd37be5755f2ad066d581e1f1e5e`.
The table has about571 estimated rows,43 heap pages, and742MB total storage,
mostly TOAST; its only index is the cursor-name primary key. These are catalog
facts, not an execution-plan attribution of CPU, I/O or lock cost.

The healthy case must prove absence of foreign lineage. `LIMIT1` cannot bound
that negative search. The current dynamic CASE avoids JSON reads for the exact
current-observation exclusions, but supplies no indexed access path for the
remaining JSON key test. Increasing the statement/work deadline, exempting more
namespaces, caching a successful inventory, suppressing its failure or pruning
the book would leave that cause in place and is not selected.

## Required semantics

Preserve every existing exclusion and every suspect: the original three exact
cursor names, current session/input/authority LIKE patterns, `shadow-%`,
`rolling-%`, `catchup%`, and the top-level PostgreSQL JSON existence semantics for
`wealth_core` or `strategy_identity`. Key presence counts even for null/false
values and top-level arrays/scalars as the existing operator defines; SQL NULL
remains distinct. An unfamiliar PAPER or other namespace containing either key
must still refuse. Do not borrow dashboard presentation exemptions.

Detection must use one PostgreSQL statement snapshot, including during a writer
transaction that moves a row between the name and JSON suspect sets. Inserts,
updates, rollback and commit must affect eligibility through ordinary MVCC.
Keep all current admission, canonical history, native-state, source, HMAC,
queue/work/retry/supersession and observation clocks. No economic rule or golden
artifact changes. The protected backtest remains untouched.

## Access-path qualification before selection

Compare two exact derived access paths in an isolated PostgreSQL16 fixture:

- A nonunique partial B-tree containing only cursor_name for the complete static
  name-or-key suspect predicate, exposed identically at the query's top level.
- A single-statement UNION ALL of a name-only branch and a JSON fallback branch,
  with a sparse partial B-tree for that exact fallback predicate. Both branches
  retain the original current-observation exclusions and one shared statement
  snapshot. A static CASE may avoid JSON work for names handled by the first
  branch. PostgreSQL's any-key operator may replace two existence calls only
  after an executed equivalence matrix proves the original semantics.

No state payload is included in either index. No full JSON GIN index or custom
PASS inventory is selected. A PostgreSQL-maintained partial index derives its
membership on writes; it does not require a second application's synchronization
or trust mechanism. The query must expose the static predicate in a form the
planner recognizes, including generic prepared plans. See PostgreSQL16's
[partial-index contract](https://www.postgresql.org/docs/16/indexes-partial.html)
and [JSON operators](https://www.postgresql.org/docs/16/functions-json.html).

Use a private large-TOAST fixture with ordinary and low all-visible coverage,
custom/generic plans, matching/missing foreign rows, original-query and removed-
guard controls. Record actual query plans, buffers, read/build cost and index
size. Measure mixed state-update/heartbeat CPU, WAL and HOT behavior, since a
state-dependent predicate can increase write cost. Do not assume an index is
used merely because it exists. The final selected form and measured limits must
be recorded here before changing the production guard.

## Selected query and measured limits

Select B: one SQL statement with a name-only branch and a sparse JSON fallback
branch, each retaining exactly the original dynamic exclusions and its own
LIMIT 1, under an outer LIMIT 1. Use four named psycopg parameters reused in both
branches so they bind the same four values. The fallback's static predicate is:

```sql
CASE WHEN (cursor_name LIKE 'shadow-%' OR cursor_name LIKE 'rolling-%'
           OR cursor_name LIKE 'catchup%')
     THEN FALSE ELSE state ?| ARRAY['wealth_core','strategy_identity'] END
```

The isolated PostgreSQL16.14 comparison passed all five cases, including1280
boolean combinations, JSON-any equivalence, mutation/rollback and a controlled
two-connection branch movement within one statement snapshot. Its87,990,272-byte
synthetic table stayed below the256MiB cap. Aggregate limits were one CPU and
2GiB across two socket-connected containers, both without network access or
production mounts. Natural custom/generic plans were tested with clean and dirty
visibility maps, with sequential scans enabled. Evidence is retained under
`20261106T015616Z-d3c9fce6`.

In that warm-cache ICU-collation fixture, the original healthy-negative query's
median was14.549–15.686ms with about13,600 shared-buffer hits. A achieved0.041ms
when all-visible, but a dirty custom plan naturally returned to a sequential
scan at16.678ms. B retained the fallback index in every tested plan, with
0.131–0.179ms medians and8–304 hits. Its index was8KiB and built in24.764ms;
A used32KiB. These are synthetic measurements, not production timing promises.
The exact PostgreSQL16.14 `en_US.utf8` database-default rerun also passed all five
cases in32.58 seconds (`20261106T015750Z-848d6384`). B used the JSON fallback
index in all twelve samples: clean custom/generic medians0.120/0.161ms and dirty
medians0.575/0.356ms. The original took20.910–64.688ms; A's dirty custom plan
again reverted to a sequential scan at65.743ms. B remained8KiB and built
in31.601ms. This confirms the selected plan across the tested collations;
concrete production-byte checks remain a qualification gate.

Both index variants reduced HOT updates from40 to16 in the40-update mixed
fixture. B produced3,463,496 WAL bytes versus3,461,704 for the original. The
partial predicate therefore has a real write tradeoff, even for excluded names;
its short-circuiting does not guarantee unchanged HOT eligibility. Accept that
bounded measured tradeoff for database-maintained membership, subject to the
larger migration and protected-writer qualification below. Do not present the
small warm-cache WAL difference as a production estimate or assume this query
change alone explains either dashboard snapshot expiry.

## Ordered JSON witness revision

Decision, 2026-11-06, before changing the production query. Select the same
single-statement split and exact sparse predicate, adding only
`ORDER BY cursor_name` before the JSON fallback branch's LIMIT 1. Keep the name
branch and outer LIMIT unchanged. The caller tests only whether a foreign row
exists; choosing an ordered qualifying witness preserves that contract. All
four exclusions, SQL/JSON presence semantics, one statement snapshot, migration
objects and original clocks remain unchanged. This is an access-path request,
not a database-wide planner switch or a clock exception.

The task-owned comparison `20261106T030859Z-21a4e8e0` used PostgreSQL16.14,
`en_US.utf8`, default fillfactor100 and autovacuum,571 synthetic rows, and a
256MiB storage cap. It retained plans and catalog/VM metadata before assertions.
The ordered candidate used the sparse JSON index in all36 samples across
vacuumed, stale dirty, three analyzed dirty and re-vacuumed states, with custom
and generic prepared plans. Its dirty execution times were0.123–0.248ms. The
unchanged B query reproduced a stale-dirty custom sequential scan at55–77ms;
after ANALYZE with actual visibility zero, both plan modes used sequential scans
at about40–83ms. The issue therefore persists with refreshed statistics and is
not established as merely stale `relallvisible` metadata.

The original, unordered and ordered forms passed1280-row presence and returned-
witness membership checks. Ordered insert/update/rollback and one-statement
writer movement passed, including removed-JSON-branch and split-snapshot
falsifiers. No planner-access switch, cost override or catalog edit was used.
This supports the revised query choice; it does not replace the complete large
fixture or installed-system qualification. PostgreSQL documents how a matching
B-tree can satisfy [ORDER BY with LIMIT](https://www.postgresql.org/docs/16/indexes-ordering.html)
without sorting the complete candidate set. Keep regression cases with actual
zero visibility both before and after ANALYZE, preserving the unordered failing
control rather than silently replacing its evidence.

## Signed coverage across the exact DDL

The global operational DDL epoch is part of both OBSERVATION and MIRROR coverage
inventories. Adding the index/function advances it; populated signed prefixes
cannot refresh themselves after that change because bootstrap and advance both
authenticate the old inventory first. An empty-coverage migration test therefore
does not qualify the installed predecessor. Do not reset coverage, skip its
inventory check, manufacture a new body or treat the resulting refusal as normal
convergence.

Factor the existing `panel.review_migration` exact DDL handoff into one shared
`sentinel.operational_ddl_handoff` implementation and use it for this additive
access path as well. This is explicit migration-only code. The caller retains
the original migration transaction, financial-writer exclusion and quiescence.
The handoff acquires SHARE locks on every source/inventory relation, locks both
coverage heads, and authenticates the existing signed prefixes against the
pre-DDL inventory before any DDL. Require the exact measured DDL epoch advance
(the index and function are expected to produce two; prove that on PostgreSQL16).
After the caller's exact catalog has validated, require unchanged heads,
incarnation, reset generation, binding, authenticated prefix and every inventory
coordinate except that precise epoch change. Re-sign only the inventory field
of each original prefix. Preserve body, through, stage and all other fields;
absent coverage remains absent. Existing stale coverage refuses before DDL and
rolls back the whole operation. An already installed component never repairs
old coverage by repeating installation.

Keep the presentation migration's original three-command allowance and refusal
behavior through the shared helper. Qualify populated COMPLETE prefixes,
pending/absent prefixes, original marker and source preservation, unexpected
DDL/source/head drift, rollback and removed-handoff/removed-epoch-guard
falsifiers. The larger private cost fixture must include populated coverage so
it exercises this actual installed-state boundary.

## Explicit installation boundary

The historical behavioral fingerprint includes every index. Removing the new
index from that comparison requires an exact, separately qualified `(table,
index)` catalog witness; unknown or altered indexes remain refusals. Do not add
the component to the immutable original operational installation's contracts
map. Use a separate additive access-path installation, preserving the original
marker and all canonical cursor rows.

Candidate/old canonical preflight precedes schema installation. Its exact clean
pre-index predecessor must remain readable through the original full guard;
absence is never a successful inventory result. Ordinary installation must earn
the new index under the existing genuine quiescence/migration ownership and
budgets before the candidate is accepted as installed. After its installation
marker exists, a missing, invalid, partial or altered component refuses. No DDL
occurs on runtime reads and no `IF NOT EXISTS` silently accepts an unknown object.

Choose transactional versus concurrent creation only after qualifying build
cost and writer/reader interaction. Concurrent creation's extra scans, waits and
invalid-index recovery are real obligations; a transactional build must fit the
existing migration budget and must not block a protected writer. See
[CREATE INDEX](https://www.postgresql.org/docs/16/sql-createindex.html) and
[HOT](https://www.postgresql.org/docs/16/storage-hot.html).

The common catalog implementation will declare exact `extension_index_pairs`
and a separate `ACCESS_PATH_COMPONENTS` registry. Capture and authenticate those
pairs before filtering only those indexes from the historical base view. Do not
hide their base table, primary key or any unknown neighboring index. This
registry does not participate in the original immutable contracts map. Its
components must distinguish genuine pre-installation absence from a partial,
lost or altered installed component using their own authenticated installation
and immutable marker guards.

Select the existing transactional quiescent migration boundary for initial
implementation and private qualification: original migration ownership and
financial-writer locks, actual uncertain-command/source-job/cycle refusal, the
existing120-second statement and150-second installer-child ceilings. An existing
original operational marker must still enter this separately owned additive
installation when needed; it must not be replaced or re-signed. No production
installation is allowed unless build/whole-migration cost and protected-writer
interaction qualify inside those existing limits. If they do not, revise this
decision before implementation of an alternative; do not extend the limits or
silently switch to concurrent creation. A transactional failure rolls back both
the access path and its installation marker.

Retain before/after canonical hashes, commands, PostgreSQL identity and genuine
backup/WAL evidence. Install through a new backed operation from the currently
verified local release, then qualify the actual access plan and multiple
financial/maintenance cycles. Preserve the observed failures and keep the PR on
hold until the root fix is locally demonstrated and required exact-head CI passes.

The concrete component is `sentinel.checkpoint_lineage_access`, with the exact
index name `sentinel_checkpoint_lineage_suspects_idx` on
`sentinel_processed_sessions`. Its marker is `checkpoint-lineage-access:v1`,
outside strategy cursor prefixes, and its schema is
`sentinel.checkpoint-lineage-access/1`. The authenticated installation records
the installation UUID, original UTC time/date, physical PostgreSQL identifier,
exact DDL contract digest and `authority_effect=NONE`. It does not wrap or replace
the original operational installation. Separate immutable UPDATE/DELETE and
TRUNCATE guards protect this marker; its exact index/function/trigger catalog is
independently pinned. Clean absence requires both marker and every owned object
to be absent. A surviving object without its marker, or a marker with missing or
changed objects, refuses rather than reinstalling or falling back.

Runtime validation never installs the component. The checkpoint reader uses the
unchanged full guard for the clean predecessor, and the qualified equivalent
query after authenticating the installed access path. The installer must require
the component explicitly after the additive phase and on its final read-only
schema check. Existing receipts retain their original shape and original
operational installation value. The migration commits before application start;
older executables cannot silently accept this extra index. Recovery therefore
uses the existing explicit forward-recovery operation with a capable executable,
not an automatic restart of the old image or removal of the new marker/index.

## Separate large-fixture qualification

Decision, 2026-11-06, before writing the qualification tool. Keep the large
workload outside the permanent pytest suite. A dedicated tool creates its own
fresh PostgreSQL 16 cluster inside the network-disabled, one-CPU, at-most-2-GiB
qualification container. It accepts no DSN, database input, production mount or
credential. Require the database's actual default `en_US.utf8` collation. The
default invocation describes the plan; execution requires an explicit flag.

Generate independent synthetic cursor rows, including 384 large incompressible
JSON payloads of approximately 2 MiB each, mixed with inline rows and the exact
current-observation name exclusions. Target approximately 768 MiB physical
table/TOAST storage and refuse a fixture outside 700 MiB–1.25 GiB. Check the upper
bound during construction and after qualification writes. No production book,
provider data or protected backtest input is used. Reproduce the original
operational installation before the separately registered access-path phase;
retain the original authenticated marker and synthetic cursor digests.

Run the real additive installer in a separately owned spawned child. Include
startup in its unchanged 150-second result-admission ceiling, retain the real
120-second migration statement limit and verify both original advisory locks at
the actual index-build boundary. Record index-build and complete migration
latency, index/table sizes and preservation of the original marker, synthetic
cursor rows, empty command journal and PostgreSQL identity. Exercise actual
financial-writer refusal before DDL and a stricter qualification-only index
statement timeout to demonstrate transactional rollback. This injected short
timeout does not change or qualify an enlarged production budget.

Observe independent read-only SELECTs during the real installation. Afterwards,
execute the exact production SQL under natural custom/generic prepared plans
with sequential scans enabled and both vacuumed and deliberately dirty
visibility maps. Retain EXPLAIN ANALYZE/BUFFERS plans, original-query controls,
matching/absent foreign rows and the stricter existing 3-second preparation-read
qualification cap. General financial source reads retain their separate
8-second limit; do not label every runtime SQL read as having a 3-second cap.
Report original-query cancellation honestly when no completed plan exists.
Install the private `pg_visibility` measurement extension in `pg_catalog` before
the original operational authority and signed coverage baseline. It earns no
inventory rebind and cannot invalidate a prefix during qualification. Dirty
visibility-map updates touch only the explicitly generated synthetic rows;
seeded broker observations, provenance, account binding and canonical broker
cursors retain their original contents and physical row tokens.

Measure a finite mixed metadata/state-update workload before and after the index,
including cgroup CPU, WAL interval and HOT counters. These measurements include
ordinary private-cluster background work and are synthetic warm-cache evidence,
not estimates of production write amplification or long-term stability. The
before/after write intervals have different heap/visibility histories and do
not isolate causal index overhead. Publish
bounded private metadata atomically, preserve failures, and stop/remove only
the freshly created private cluster. Execution awaits the independently captured
and pinned concrete component catalog and the qualified PostgreSQL 16 image.

The first large invocation refused at private-cluster STARTING, before fixture
loading or migration. Preserve its original metadata-only report and SHA256
`bb951f8bcdd56ae9f67b39229e90d7eb227577fcdbc5d7ee1e5de095fc19ad3f`;
that report does not identify the startup cause. For a fresh private startup
only, retain at most 4096 characters of the fixture helper's RuntimeError
(initdb/pg_ctl/createdb diagnostics) in the private report. This phase has no
application/provider data or inherited credentials. Later-stage failures keep
closed exception metadata; arbitrary runtime SQL or financial error text is
not recorded. Reproduce the startup cause before selecting a harness fix, and
use a new explicit attempt/evidence directory after qualification of that fix.

The next large invocation reached the natural-plan phase after successful real
installation and preservation checks, then refused with
`InvalidSqlStatementName`. Preserve that partial result, SHA256
`07b800bfdec95ee2ba268c386c2538abfbfff0d24fc81cb0b09822cfd03ec1e0`;
it is not a completed qualification. A separate tiny PostgreSQL 16.14 fixture
using the same original/selected SQL and EXPLAIN helper reproduced SQLSTATE
26000 at the first modeled dirty-phase custom-plan execution. The tiny fixture
tests prepared-statement lifecycle, not actual visibility-map or index behavior.
Installed psycopg 3.3.4's
automatic prepare cache became populated during the vacuumed controls, then
its rollback maintenance removed all server prepared statements, including the
explicit `lineage_selected` and `lineage_original` controls. Captured statement
names before and after rollback, and the installed PrepareManager source,
establish this cause; the tiny report SHA256 is
`f164338fc7197065309cb1bc843592b3efd3e4c04b2981e8803fa2ca4aa2dff2`.

Decision before correcting the tool: disable automatic preparation only on the
qualification's main control connection, immediately after opening it. Keep
the explicit SQL PREPARE statements, natural planner settings, original SQL,
custom/generic modes, rollback boundaries and query budgets unchanged. The
tiny `prepare_threshold=None` control completed both modes on both sides of
those rollback boundaries. This setting does not affect production connections,
the migration child, or runtime query behavior. A fresh complete large attempt
still requires explicit readiness and its own retained outcome.

The corrected-control attempt refused at
`NATURAL_INDEX_PLAN_NOT_QUALIFIED` in its first dirty lane; preserve report
SHA256 `58693db82a7f1ce1afab84fcae304c8cf5f31b707a481b6e70864729fdc0ce27`.
The two vacuumed plan modes were retained, but the tool enforced the dirty
selected-plan guard before storing the selected samples. That report cannot
distinguish an index-plan miss, query timeout or unexpected result count.

Decision before the next diagnostic invocation: append the phase/mode lane
before measuring it, and atomically retain each selected EXPLAIN outcome and
full plan before enforcing the existing guard. Record elapsed time, timeout,
actual root rows, index names, heap/index `relpages`, `reltuples`,
`relallvisible`, and the actual visibility-map summary at that mode's boundary.
The existing one-MiB report bound applies to all retained plans. The SQL, index,
natural planner settings, three-second cap, preservation checks and refusal
guard remain unchanged. One separate explicit diagnostic attempt will capture
the missing evidence; planner row-goal/visibility estimates are only a
hypothesis until its failing plan is retained. Do not select a production query
change, force sequential scans off or widen a clock from that hypothesis.

The separate diagnostic attempt `20261106T030013Z-b57f5344` retained the missing
evidence and refused at the same guard. Its report SHA256 is
`04fe9f4725c6e2b8eb83c59b638b161230b690a6894101df0cbe1ce7009c912d`.
On the approximately 797-MiB fixture, all three dirty/custom selected queries
completed with zero rows, no index use, and execution times of 399.235,
390.073 and 524.750 milliseconds. This is a failed natural access plan, not
a query timeout or a data mismatch. The JSON fallback used a sequential scan:
the first sample removed 575 rows, read 68,025 shared blocks, and spent
398.425 milliseconds in that node. Its separate name-only sequential scan
spent 0.767 milliseconds and did not traverse JSON state.

The dirty JSON fallback's estimated full cost was 69.94 for 280 rows, with its
LIMIT estimated at 0.25. Actual visibility-map all-visible pages were zero;
the stored heap metadata still reported `relpages=18`, `reltuples=575`, and
`relallvisible=18`. The sparse index had one page and zero estimated tuples.
Both vacuumed plan modes had 18 actual all-visible pages and used the sparse
index-only scan. The first vacuumed fallback had estimated startup 0.12,
full cost 10.25 for 144 rows, LIMIT cost 0.20, and actual node time 0.004
milliseconds. The retained plans demonstrate that the then-current B candidate can
choose the expensive JSON scan after ordinary writes. They do not retain the
rejected alternative index cost or prove a complete optimizer decision trace.

The diagnostic again passed recorded preservation, exact coverage epoch
transfer, installation locks, strict-budget rollback, writer-busy refusal and
overlapping read checks. Final write-cost and coverage checks were not reached;
the attempt is not a completed qualification. Preserve every earlier refusal.
Keep the production query unchanged while separately comparing the ordered
witness under dirty stale and refreshed statistics. Any selected query change
requires a new documented decision, semantics checks and one separately
authorized complete large qualification. No planner flag or deadline changes
are authorized by these findings.

## Completed private large-fixture qualification

The single approved ordered-candidate requalification
`20261106T032138Z-cb7bd9ad` completed with `QUALIFIED` / `COMPLETE`.
Its exact command was the task-owned isolated runner:

```text
wsl -d Ubuntu -u bron -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/checkpoint-lineage-large-run.py
```

Final evidence file:
`.codex-tmp/dashboard-probe-test-evidence/20261106T032138Z-cb7bd9ad/checkpoint-lineage-large.json`.
SHA256:
`f4b39457f55575db20a132a91bd1fb3edfae52f6a192369b48f73622792f71b0`.
An independent file-only review verified the hash and result. The unchanged
diagnostic tool SHA256 is
`b3fc4bc0ad6eb06872576b50bde427095a7b4588f7f7d1a1ae241505ef74670e`;
the ordered access module SHA256 is
`e04bee34940920868cf81417ed9193fabc43f49e8eb4de92ecb63deca7706a40`.

The actual server was PostgreSQL 16.14 with default libc `en_US.utf8`, inside
the pinned `aa61880b...` image with network disabled, one CPU and 2 GiB memory.
At the 384-large-row loading boundary, physical storage was 835,960,832 bytes;
the complete mixed fixture was 836,083,712 bytes (797.352 MiB), including inline
and allowed-name rows. Final storage after all qualification writes was
853,712,896 bytes, within the unchanged 1.25-GiB cap. No production data,
credentials, cluster, volumes or provider inputs were used.

All twelve selected samples completed with zero results, no timeout and the
sparse suspect index. The actual visibility map had 18 all-visible pages for
the vacuumed lanes and zero for both dirty lanes. Sequential scans remained
enabled and the qualification statement cap remained three seconds.

| Visibility | Plan mode | Selected execution, ms | Original control, ms |
| --- | --- | --- | --- |
| Vacuumed | Custom | 0.127–0.333 | 612.749 |
| Vacuumed | Generic | 0.179–0.232 | 583.810 |
| Dirty, actual VM zero | Custom | 0.169–0.303 | 606.378 |
| Dirty, actual VM zero | Generic | 0.176–0.289 | 493.859 |

Selected wall time was 0.820–2.183 milliseconds. These are synthetic
healthy-absence measurements with an empty suspect index. The dirty generic
execution retained a generic plan compiled earlier; it proves execution with
actual VM zero, not a freshly optimized dirty generic plan. The separate small
comparison and permanent regression cover stale and refreshed dirty statistics,
presence/witness semantics, actual insert/update/rollback, one-statement MVCC
and executed removal falsifiers. Neither scale is a production latency promise.

The real installer held both original migration and financial-writer locks.
Its original statement limit was 120,000 ms, lock limit 2,000 ms and whole
child/result-admission limit 150 seconds. Index build took 0.775 seconds;
complete migration took 1.803 seconds; whole child admission took 3.294 seconds.
The index occupied 8,192 bytes. Sixty-two independent read-only queries
completed without failure, fourteen overlapping index construction; maximum
reader wall time was 62.127 ms. The injected one-ms index statement produced
`QueryCanceled` with transactional rollback, and a real held financial-writer
lock produced `OPERATIONAL_MIGRATION_FINANCIAL_WRITER_BUSY` before DDL.

Before/after migration digests matched exactly for the original operational
marker/contracts, processed cursor/source state, seeded financial observations,
provenance, account binding and canonical broker cursor contents/physical row
tokens. The empty command/event counts and physical PostgreSQL identifier
remained unchanged. Both genuine COMPLETE OBSERVATION/MIRROR prefixes retained
their body, through, heads, binding, incarnation and reset-generation content.
The DDL epoch advanced exactly from 1 to 3 in the same incarnation; only their
authenticated inventory hashes changed. After the final mixed writes and
foreign-witness probes, coverage exactly equaled post-installation coverage
and the financial-row digest remained unchanged.

The two finite write intervals each performed 36 updates. Raw observations
were 34 versus 16 HOT updates, 11,395,880 versus 9,232,520 WAL bytes, 1.005 versus
0.733 seconds, and 702,269 versus 720,778 cgroup CPU microseconds, before versus
after the index. These intervals include ordinary background work and different
heap/visibility histories. They do not isolate causal index overhead or show
that production writes become faster or produce less WAL. A state-dependent
index can reduce HOT eligibility; these raw observations are retained without
re-pinning an economic fixture or changing financial behavior.

This result qualifies the finite private access/migration experiment. It is
not economic replay, required CI, PR delivery, image/native installation,
recurring backup proof, uninterrupted dashboard availability or long-term
stability. All historical refusals remain retained. No production action was
performed during this qualification.
