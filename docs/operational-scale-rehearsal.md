# Joint acquisition, startup and daily-operation rehearsal

The October 1 NAS failure exposed a composition gap: a large price corpus and
a large reference download had been tested separately, but full reference
storage had not been exercised through publication and the later readers.

Add a manually invoked local campaign outside routine CI. Use the real HTTP
acquirer, PostgreSQL schema, operational publisher, GO financial proofs,
canonical 126-session formation, durable shadow and automated daily refresh.
Follow those with the existing simulated paper preparation, execution and
reconciliation membrane. Retain the same database across consecutive sessions
and reopen connections to exercise restart and duplicate-wake behavior.

The representative profile combines 6,000 active securities, 30,000 ticker
records and 1,000,000 distinct historical action records. Startup contains
426 sessions; daily acquisitions contain 300. Synthetic actions outside the
decision window provide realistic reference pressure without manufacturing
unknown corporate-action economics. Separate focused economic fault tests
remain necessary; this is not a replacement for them.

PostgreSQL gets 1 GiB RAM and 2 GiB combined RAM/swap, matching the reported NAS
container. GO/formation and the shadow service's daily acquisition get 4 GiB RAM
and two CPUs. Paper preparation/execution runs in a separate persistent automation
process with its production 2 GiB RAM and one CPU limit, reading the same database.
The provider is a separate 512 MiB container. All
containers use an internal network and disposable volumes.
No actual provider credentials or broker endpoints are used. Keep per-phase
logs, cgroup counters, exact source/image identities, row counts and verdicts,
including failed runs. A missing phase is incomplete, never a pass.

This campaign exercises the production financial/automation functions; it does
not issue a deployable certificate. Its explicit fixtures are the clock,
provider, reviewed runtime/certificate authority and broker. The existing
canonical shell GO harness separately tests checkout/image promotion, backup
media and certification orchestration. Results must distinguish these scopes;
neither local campaign certifies NAS hardware or actual provider/broker behavior.

Acceptance requires actual large references stored and read through the new
TEXT representation, complete publication, GO parity/readiness/database checks,
formed startup matching preview, daily retained-state continuation, duplicate
wakes without duplicate publications/commands, reconciled simulated orders and
successful restart reads. Automation coverage also includes its scheduler,
lease and recovery tests. Do not infer that passing isolated storage alone
satisfies this acceptance. Run a small protocol profile first, then the large
profile; batch findings and their targeted regression fixes before publication.

## Findings and storage decision

The large campaign reproduced a second PostgreSQL OOM in
`sentinel_acquisition_parts.reference_payload`, before snapshot publication.
Apply the same 1 MiB JSONB / 256 MiB bounded canonical TEXT policy to reusable
acquisition reference parts. Add a nullable TEXT column, preserve existing JSONB
rows and logical content hashes, enforce exclusive representations and the TEXT
checksum in SQL, and verify parsed content on reuse. This covers startup and
daily acquisition without raising database memory limits. Existing ownership,
immutability, successor reuse and retention rules remain authoritative.

The small campaign also found that retained-action publication mapped dates
outside its coverage before filtering them, causing pre-1997 source records to
fail calendar conversion. Filter raw dates against the exclusive lower session
and inclusive upper session first. Daily correction checks keep the original
retained basis, not just the latest price-window start.

The canonical shell fixture still supplied roughly 385 sessions for a selected
426-session startup. Its source axis now derives from the selected formation
window plus one session for the pre-GO seed, rather than 560 calendar days.

The separate 2 GiB automation reader reproduced another OOM after publication:
`SnapshotReferences` held about 1.7 GiB, then a nested manifest check decoded the
same reference again. Separate stored-byte verification from semantic decoding.
Manifest, sealing and reader integrity checks verify existence, representation,
size and the exact TEXT checksum in PostgreSQL without returning/expanding the
whole document. `load_evidence` remains the semantic boundary and still checks
JSON decoding, object shape and canonical logical identity whenever a consumer
needs the contents. No verdict cache, cross-transaction trust or optional bypass
is introduced. Restore/content checks still verify stored bytes and price hashes;
runtime reference consumers still validate reference schemas and source meaning.

The symbol-identity projection only consumes rename actions. Retain copied rename
evidence there, rather than copying every dividend and unrelated action into a
second long-lived collection. The authoritative reference document and the
economic action reader retain their full contents; rename matching/rejections
and economic decisions must remain identical.

The same retained 2,556,000-row publication and 185,998,932-byte reference bundle
killed the original read-only automation readiness reader at its 2 GiB cap
(`OOMKilled=true`, exit 137). The corrected reader completed in 103 seconds with
1,538,068,480 bytes sampled working peak and no client/database OOM. This direct
comparison exercises the data reader only: the changed source identity correctly
prevents the old publication from satisfying the full new strategy admission.
A fresh joint campaign must establish that admission and subsequent paper cycles.

The first paper composition bypassed broker guards and therefore did not measure
their repeated data/plan validation. The guarded profile must retain the real
fresh-connection guard and instrument its call count and time. Only signed
certificate issuance and scheduler control/lease authority are fixture boundaries
in that profile; the scheduler/fence suite tests those separately. A result from
the original unguarded profile cannot establish the callback's execution budget.

Automation constructs a broker symbol resolver before preparation/execution.
Its returned closure must retain only the historical and next-session identity
resolvers, not the whole `SnapshotReferences` object and its million action rows.
Otherwise that long-lived broker dependency overlaps the next full reference
read. Preserve all historical/next-session identity boundaries and add a lifetime
falsifier. The rehearsal must construct and retain this resolver too.

The guarded small profile already spent 57 seconds in its first 40 guard checks;
each execution check repeats the whole readiness scan twice. The full-size single
scan measured 103 seconds. Repeating that immutable-data work per broker call
cannot fit the 15-minute callback budget. Reuse only the compact readiness
material within one held publication pin, including nested fresh connections
to the same database. Do not retain the full references or cache an authorization
verdict. Every check still authenticates the publication/receipt/reference bytes,
checks the selected strategy, recomputes frontier/time-dependent readiness,
revalidates shadow/plan authority, and checks current lease/control/certificate.

The reuse scope owns a specific connection, backend PID, database endpoint and
publication identity. PostgreSQL must confirm that the originating backend still
holds the session-level shared corpus lock before and after material loading or
reuse. End the scope before releasing that lock; reject lost/closed pins and
prevent copied contexts from retaining authority after scope exit. A subsequent
callback, restart or new publication computes fresh material. Sealed rows remain
immutable; no cross-publication or global readiness cache is permitted. Test
fresh-connection reuse, new-scope recomputation, receipt corruption, strategy and
clock changes, lost pins, and expired copied contexts, with guard-removal mutants.
Check the originating pin at the operational-reader entry point, before storage
reads can acquire their own temporary transaction-level pin. Those temporary
locks must not hide loss of the original pin across transactions.

The guarded baseline completed three cycles with 594 fresh guard checks and
60 filled commands; guard validation alone took 1,071 seconds on the small
profile. The affected paper-input module passed 24 tests, and the six new
resolver/pin-reuse mutants were killed. Measure each preparation/execution
callback (including broker-resolver construction) against the ordinary
900-second callback budget. A cycle contains multiple callbacks, so its local
HTTP orchestration timeout is separate from that acceptance bound.

The corrected guarded small profile completed both daily top-ups and all three
paper cycles in 976 seconds. It retained 594 fresh guard checks and 60 filled
commands; cumulative guard validation fell from 1,071 to 692 seconds. Duplicate
wakes added no publications or orders. This establishes guarded composition on
the small fixture, not full-size callback timing or memory safety. The final
large profile additionally times broker-resolver construction within each
callback. Its outcome must be recorded separately.

## Running locally

### Bounded canonical encoding during fresh execution checks

The full-size guarded run passed acquisition, GO formation and durable startup
restart, but its first execution callback exceeded 900 seconds. Profiling the
retained 6,000-security book showed repeated canonical JSON traversal dominating
fresh plan re-derivation. Optimize encoding without retaining a validation or
authorization result: delegate small, bounded dictionaries and their scalar
arrays to the same standard-library C encoder. Bound aggregate elements, keys
and strings before encoding; larger or unusual structures retain the streaming
path. Canonical bytes, hashes, invalid-value refusal and detached state ownership
must remain unchanged. No strategy rule, broker guard, deadline or source identity
check is removed. Compare against independent standard JSON bytes, include late
corruption and circular-reference cases, and measure scratch allocation as well
as the full retained plan. A faster microbenchmark alone does not qualify the
automation callback; rerun the composed guarded path under its resource limits.

Within one synchronous pure operation, validate JSON once: hashing itself runs
the strict encoder, and canonical restoration runs it after normalization.
The private decision view may borrow feed arrays while it performs read-only
sizing; public serialization remains detached. Build a shadow target directly
from the state already canonicalized by plan construction, rather than restoring
that same state twice. Reuse a computed state digest only as a local variable
within one re-derivation. None of these values survives a broker call or bypasses
the next fresh database verification.

### Structural verification within a guarded callback

Pure encoding improvements reduced the retained plan microbenchmark from about
9 seconds to 3.8 seconds, but cannot alone accommodate hundreds of fresh guards.
Reuse structural checkpoint restoration and deterministic sizing within the
guarded callback only. Bind that reuse to the original live publication-pin
scope and execution writer-lock owner, database endpoint and backend PID. Every
guard reads the current processed-session row inventory and PostgreSQL row
versions (`tableoid`, `xmin`, `ctid`, session and cursor), relation file identity,
and transaction-ID epoch. Updates, inserts, deletes, rewrites, changed context,
or lost ownership force fresh verification or refusal. Inventory the whole
processed-session table to include genesis, checkpoints, lineage, authority and
sizing inputs without maintaining a second list of logical dependencies.

The checkpoint loader runs in its existing repeatable-read, read-only snapshot.
Revalidate the version inventory after loading; refuse change across snapshots.
Store a private detached copy and return detached copies so callers cannot alter
future checks. Cache only the structural closure and pure sizing proof: binding,
rollout, current plan, source/runtime identity, current readiness, clock, exchange
window, certificate, lease/control, segment approval and broker-result identity
remain fresh. New callbacks and restarts begin empty. Direct callers outside a
guard still perform full verification. This is not a durable authorization cache.

PostgreSQL identifies row versions with `xmin` and changes `ctid` on updates or
table moves; relation identity and the transaction epoch bound their use to this
short-lived scope ([system columns](https://www.postgresql.org/docs/16/ddl-system-columns.html)).
Falsify changed rows, added/deleted lineage, table rewrites, changed sizing inputs,
copy isolation, expired pin and lost writer ownership. Then rerun the complete
guarded callback, including actual daily continuation, under the same limits.

The next full-size pass exposed a remaining eager origin read in `classify`,
before entering the reusable structural closure. It deserialized and authenticated
the large origin input on every guard just to decide whether startup existed.
Use a row-existence query for that dispatch only. The closure loader still reads
and authenticates the complete origin before granting structural status, and its
row-version inventory invalidates reuse after any change. Outside a guarded scope
the complete loader continues to run every time. Verify one origin authentication
across repeated unchanged guarded checks and refusal after origin tampering.
The authenticated checkpoint also contains historical input used only while
verifying its origin. Do not copy that input on every status return. After the
full closure has verified it, retain only the session/publication/snapshot fields
needed by the fresh status checks, the restored result and authority records.
Runtime writes/recovery continue to receive complete checkpoints. Falsify any
attempt to copy historical input through the read-only status material.

The long-lived measurement process aggregates each sample immediately into phase
maxima and a count. It must not retain every 100-ms sample during hours of idle
startup: that instrumentation itself otherwise consumes the automation budget.
Keep cgroup lifetime peaks/OOM counters and process RSS peaks in the final report.

Within each fresh broker guard, the dual sizing proof recomputes and binds the
current detached shadow state's canonical digest before its structural result
can be reused. Pass that just-verified digest to the remaining plan-authority
check in the same synchronous guard instead of hashing the full book a second
time. Direct preparation, execution and manual checks still compute their own
digest. This is a per-call value, never a retained authorization or a substitute
for the next guard's state, publication, account or clock checks.

The corrected small campaign at `d5ee3d30` passed in 393.33 seconds: two daily
top-ups, three paper cycles, 60 filled commands and 594 fresh broker guards.
Guard time totaled 192.967 seconds; the longest callback, including resolver
construction, took 58.098 seconds. Automation working memory peaked at
133,582,848 bytes and PostgreSQL at 111,452,160 bytes, with no OOM events.
The six structural-reuse mutants and two canonical-encoding guard mutants were
killed. Targeted checks passed: 56 paper/authority tests, 142 state/storage/plan
tests, 20 real structural-reuse/resource-measurement tests and the read-only
sizing ownership regression. These small results do not establish the full-size
callback budget. The prior full-size run passed acquisition, financial formation
and durable restart but was deliberately stopped after its execution callback
had exceeded 900 seconds; that run remains failed/incomplete for automation.

The daily-continuation, runtime recovery, reconciliation and re-genesis scope
regressions also passed (73 tests, 1,418.06 seconds). The complete paper-input
mutation sweep exposed two older coverage gaps: retained-history refusal masked
the snapshot fallback's separate dividend/action bounds. Extend those tests to
exercise the fallback directly, including an empty interval before available
history. Both tests pass normally and fail when their own guard is removed;
production behavior is unchanged by that test correction. Keep the canonical
encoding mutations reproducible with the repository runner:

```sh
python -m pytest tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_dual_reconciliation.py tests/sentinel/test_dual_regenesis_automation_scope.py -q --tb=short --disable-warnings
python -m tools.sentinel_rolling_paper_falsifiers
python -m tools.sentinel_canonical_state_falsifiers
```

Build from this checkout with the existing dependency test image available:

```sh
docker build -f tools/operational_rehearsal/Dockerfile -t sentinel-test:joint-rehearsal .
python -m tools.operational_rehearsal.runner --image sentinel-test:joint-rehearsal --commit "$(git rev-parse HEAD)" --small --output artifacts/joint-rehearsal/small.json
python -m tools.operational_rehearsal.runner --image sentinel-test:joint-rehearsal --commit "$(git rev-parse HEAD)" --output artifacts/joint-rehearsal/full.json
```

The host runner uses only Python's standard library and the Docker CLI. It
records the resolved image IDs and the worker's actual source digest; the commit
argument alone is not proof of the image contents. It removes only its uniquely
named containers, network and volumes, retaining the report and logs locally.
Allow up to six hours for the large profile. The runner requires cgroup v2 for
measurements and is a local Docker Desktop/Linux tool, not a NAS deployment step.

The separate-process small campaign passed in 244 seconds with 12,780 initial price rows,
100 ticker records and 500 actions. It completed GO financial proofs, 126-session
formation with a lost acknowledgement halfway through, restart, two daily
top-ups and three paper cycles containing 60 filled simulated commands. Duplicate
wakes created no additional publications or orders. The separately capped paper
process peaked at 124 MB; sampled PostgreSQL working memory peaked at 135 MB.
This establishes protocol
coverage; it does not establish full-size resource safety.

Targeted regression validation also passed: 68 automation scheduler/composition,
lease and recovery tests; 89 acquisition reuse, retained history and canonical GO
fixture tests; and 20 feed-schema tests. All 39 acquisition and 16 retained-history
mutations were killed, including the new storage bound/checksum and calendar-bound
mutations. The size-bound child was repeated after its source matcher was tightened
and failed at the intended missing refusal.
