# Economic certification: remaining code closure

Base: `748d54e12a4cdb4b5403c56feb8d6b68e47d0104`, the verified merge of
PR #402. This is step 1 of the owner's certification sequence: eliminate known
implementation defects and exercise recovery locally before the independent
historical replay. It does not certify returns, a provider capability or NAS
deployment. Issue #399's GitHub closure does not change those evidence gates.

The baseline finding inventory is the
[pre-NAS ledger](economic-audit-399-pre-nas.md), including the relevant #400
dependencies. Preserve that historical evidence. No NAS or broker-account
access is part of this work. The final execution/disposition ledger below must
separate fixed defects, unsupported economic capabilities, and external evidence.

**Follow-up after #403:** current `main` was independently verified on GitHub
and by `git fetch origin main` as
`4dd5af636ed48d6c17d8a75af4209cbc23a17e48`. The endpoint-replacement and
streaming-timeout entries below now have local fixes and retained acceptance
evidence in [the follow-up package](../audit/economic_399/closure_followup_403/README.md).
Step 1 remains open; the rolling-admission and backup-lifecycle rows still name
implementation work, not merely NAS qualification.

## Decisions before implementation

### Streaming deployment deadlines (A24 follow-up after #403)

The optional command timeout also applies to streaming commands, including a
silent child, output without a newline, and a descendant holding stdout open.
Use one monotonic deadline for pipe reads and process exit. Start the command
in a private process group; timeout or interrupted streaming kills and reaps
that group without affecting the installer. Retain output already received in
the command log. A checked timeout refuses; an unchecked timeout returns 124.
This deadline bounds the child process and its pipe; the existing separate
host filesystem/output-device qualification remains required.

### Temporary dependencies and authority (A3/A4/A11/A13/A20)

Reviewed PostgreSQL query cancellation (`57014`), connection loss, transaction
conflict and temporary resource/lock unavailability are availability failures.
Authentication, permission, malformed evidence and explicit revocation remain
refusals. A broker-free helper owns the PostgreSQL availability predicate so the
shadow worker does not import broker automation merely to classify a failure.

The execution guard distinguishes a failed authority check from an explicit
authority refusal. Only the former may carry a reviewed temporary dependency
cause into retry classification. Unavailable authority never authorizes a read
result or transport. Retry re-observes authority and reconciles the existing
journal; no new command identity is created for uncertainty.

Apply this classification around the whole backup-guard operation, including
connection acquisition and cleanup, before callback subprocess serialization.
Do not turn an existing typed integrity failure into availability because its
exception context happened to contain an earlier transient failure.

A preparation claim blocked by a live lease or future retry time returns a
typed waiting outcome. It does not steal ownership, extend an immutable request
deadline or create a second active request. Expiry retains the prior attempt
and uses the existing locked successor enqueue from #402. Missing, corrupt or
terminal jobs remain distinct from a currently unavailable claim.

### Callback supervision (A1/A17)

A callback's service-instance start timestamp is its invocation marker: the
worker writes it once before starting that callback; lease heartbeats do not
rewrite it. The supervisor keys its monotonic deadline by phase and marker,
not phase alone. A new same-phase invocation gets its own deadline. Repeated
observations of one invocation never renew its deadline, including clock shifts.
Database loss preserves the last monotonic deadline.

Supervision must not wait indefinitely for database or notification I/O.
Independent killable operations, with connection/query bounds inside them,
separate dependency observation from worker kill decisions. Failed reporting
cannot clear a latch or delay the worker's recovery deadline.

### Returning economically inactive identities (A15)

Feed compaction already proves that a removed identity has neither retained
formation observations nor protected path-dependent state. A returning bar may
start a new feature series only if the identity is absent from both and the
dated reference/overlap checks still pass. It starts with that observed bar;
it cannot be admitted until the ordinary formation rules are satisfied. Do not
invent history or backfill unobserved sessions. Any holding, pending instruction,
cooldown, terminal or sensor dependency still requires its retained anchor.
Snapshot admission applies the same fresh-formation rule to an empty warmup
series: cold-start material has no prior economic state to protect. Dated
listing intervals and complete source coverage remain mandatory, including
the inactive interval between an old listing and its returning listing.
When comparing a historical reference prefix during such a gap, its retained
display label comes from a listing that had begun by that session. A future
returning listing must not rename the earlier inactive interval. This changes
no identity resolution or permission to trade during the gap.
The snapshot adapter supplies an explicit feed anchor for this proven inactive
case: current dated issuer identity and a fresh split basis of one. That basis
has no historical prices, peaks, shares or entitlement attached to it; future
observations establish formation normally. Existing economic dependencies may
never use it. The input archive retains the anchor and the continuity proof.

### Notification delivery continuity (A6)

Retryable transport failures and expired delivery claims keep the same durable
alert pending, with capped exponential backoff, regardless of outage duration.
The historical `max_attempts` field remains immutable evidence of the original
enqueue configuration; it is no longer a deadline that discards a retryable
obligation. Dispatcher failure thresholds still make health red. Explicit
nonretryable failures still dead-letter and require operator attention.
Mixed recipient failures remain retryable while any captured recipient has a
temporary failure; successful recipients are not redelivered. Retrying another
recipient does not erase a permanent recipient failure or claim full delivery.

### Monitoring availability (A19/A25)

Missing installed control/lease state and uncertifiable observations are
critical even when their missing values prevent establishing `enabled` or
`kill_switch_engaged`. An intentionally uninstalled system remains distinct.
Browser subscription SQL runs in the framework's worker thread after bounded
request validation; a waiting database must not block the panel event loop.
Each subscription connection has a three-second connection budget and a
two-second statement budget (including lock waits); transaction/response
semantics remain unchanged. Thread isolation protects HTTP scheduling even
when a dependency fails to return normally. A kernel-level silent socket still
requires the process-level panel/deployment qualification described below.

### Deployment command propagation (A22/A24)

The hardened deployment method must propagate the same reviewed informational
DUAL flag as the base implementation. Readiness waits pass their remaining
monotonic budget into the actual subprocess invocation and reject a healthy
answer received after that budget. Neither change grants authority or contacts
an account in local validation.
Unreviewed/fenced installation builds the single runtime Dockerfile and tags
that image for the existing promotion path; it never builds the retired
authorized-runtime tombstone. The separate test lens consumes that exact tag.

### Retention reporting (A27)

The maintenance diagnostic is a separate best-effort transaction after the
bounded retention commit. Apply its own 250 ms lock and one-second statement
budgets; the previous transaction's LOCAL settings have expired. An unavailable
diagnostic must not prevent the next recovery wake or undo completed retention.

### Persistent shadow integrity latch (duplicate A5)

Keep the terminal shadow latch on the existing persistent Sentinel state volume,
not container temporary storage. Startup must honor an existing latch before
starting any worker. Persist the first refusal with an exclusive create and
fsync; later restarts must not overwrite its evidence. Clearing it is an
explicit operator recovery action after the underlying refusal is resolved.
The deployment handoff must preserve the file in the incident evidence before
clearing it. A shadow reconstruction in progress is also non-green health,
although its worker is allowed to continue making bounded recovery progress.

### Recurring health incidents (A18)

Generic operational health incidents need a durable occurrence, separate from
the control generation and latest trading cycle. Store the active health
identity and a monotonically increasing occurrence in a singleton notification
cursor, protected by a SQL row lock. Observing recovery clears the active
identity; recurrence allocates a new occurrence even when trading state has not
changed. Repeated reads and dispatcher restarts within one incident reuse the
same alert. Commit the cursor with outbox insertion so a crash cannot consume
an occurrence without its alert. Existing cycle/kill transition alerts keep
their canonical event identities. Unknown/unreadable health does not count as
recovery. Explicit schema migration installs the cursor; runtime never creates
it. Migration never reseeds a missing singleton or recreates a missing table
when occurrence history survives. The additive Stage-4 catalog fingerprint
changes to `5057d5abd499efdb1e7a6c3dcb04b3774077eaa5d18163c75da93b50263c56f7`,
measured from the declared DDL on isolated PostgreSQL; economic golden fixtures
are unchanged. This state affects notifications only, never strategy or execution authority.

### Independent dispatcher deadline (A1)

Run the existing alert loop in a disposable child. Only beginning a new loop
iteration emits progress to its parent through a private nonblocking pipe;
waiting SQL, transport or cleanup cannot refresh progress. The parent enforces
a monotonic wall-clock limit, terminates the whole child process group, and
restarts it. Pending/expired outbox attempts retain their existing identity and
fencing. Connections are created only in the child. Connection and statement
timeouts remain additional bounds, not proof against silent sockets.
The optional independent webhook reports a dispatcher stall under a separate
typed incident; it does not misclassify every stall as a database failure. That
report and local stderr are themselves bounded. With no independent webhook,
loss of the subscription database still cannot be reported through Web Push;
external health monitoring remains a deployment prerequisite.

### Global fence before deployment migration (A23)

Stopping local containers does not fence a standby connected to the same
database. Before backup or migration, require an independently read durable
kill switch and invalidated lease. Retry emergency fencing after PostgreSQL is
healthy, then inspect the actual database instead of trusting command prose.
The only first-install exception is a catalog proof that no Sentinel behavioral
relations exist; feed-only history may already exist. Partial behavioral state,
missing control/lease rows, a live lease or an unreadable database refuses before
migration. Repeat the proof in the migration process. This grants no broker
authority and does not manufacture a missing control row to silence a refusal.

## Execution and dispositions

A2 follows the user-approved preserve-and-replay policy in
[rolling missed-session recovery](rolling-missed-session-recovery.md).

This follow-up closes the implementation defects listed below. **Step 1 and
economic certification remain OPEN.** In particular, the backup-lifecycle and resource code dependencies below are
not NAS-only work. Passing
these acceptance tests is not a claim that no other economic defect exists.

| Finding | Locally established behavior and production path | Evidence |
|---|---|---|
| A2, P1 | `shadow_service.advance_once` → `rolling_runtime.service_advance` → `rolling_recovery.advance_one` preserves the canonical book and advances one missed session using retained dated inputs. Separate reconstruction receipts cannot grant prospective authority. Restart recovers committed candidates/receipts exactly once. | Continuous versus interrupted PostgreSQL clones with actual holdings, a stop shock, pending exits, cooldowns and a subsequent fresh session; equal full canonical state, unchanged genesis/capital and zero execution rows. Full restore validation reports reconstruction without attestation. |
| A3/A4/A11/A13/A20, P1/P2 | Typed dependency failures propagate through worker, preparation, guarded authority checks and backup cleanup. Explicit revocation/integrity remains terminal. Live leases/retry deadlines wait without replacing identity. | `test_dependency_recovery.py`, actual PostgreSQL lock/cancellation fixtures, `test_rolling_snapshot_jobs.py`; removal falsifiers for classification and waiting. |
| A15, P2 | Proven inactive returning identities start fresh formation; dated metadata does not import a future listing into earlier history. Protected holdings/pending/cooldown dependencies still require anchors. | `test_returning_identity.py`: real snapshot publication, restart and protected-anchor refusal; independent dated-label assertions. |
| A1/A17, P1/P2 | Callback invocation markers distinguish repeated same-phase calls. Killable database/alert observations and bounded stderr preserve supervisor progress. Dispatcher parent kills/reaps a silent dependency worker and restarts it. | Real lock, full log pipe, silent local socket, SIGTERM-resistant child, new invocation and expired invocation tests. No remote socket/account used. |
| Duplicate A5 latch, P1 | First shadow refusal persists on the Sentinel state volume; restart refuses to spawn a worker while latched. | Restart acceptance and latch-removal falsifier. |
| A6/A18/A19/A25, P2 | Retryable alerts retain identity beyond attempt-count configuration; temporary recipients survive permanent peers. Generic incident occurrences survive restart and rearm after observed recovery. Missing authority alarms remain critical. Browser SQL runs outside the event loop with database bounds. | Actual outbox/recipient persistence, occurrence crash boundaries, lost cursor migration refusal, attempt takeover regression, event-loop progress; duration/mixed-recipient/recurrence/alarm/thread falsifiers. Endpoint rotation remains open below. |
| A22/A23/A24/A26, P1/P2 | Public installer propagates reviewed DUAL mode, uses the current Dockerfile, proves global fencing before backup/migration, repeats that proof inside migration, and bounds/rejects late readiness replies. | Actual public class-dispatch tests, real PostgreSQL empty/partial/fenced/standby states, real harmless delayed subprocess, global-fence and ordering falsifiers. |
| A27 and A2 retention, P2/P1 | Diagnostics have their own post-commit timeout. SQL pins all unconsumed published recovery inputs; runtime refuses an older installed pin function. | Actual locked diagnostic table, actual SQL retirement rejection and successful negative control after removing that guard, stale-catalog falsifier. |

The paired replay detects recovery divergence, not all possible errors shared
by both runs. The stop-shock assertions independently require exits, lower NAV,
and the documented cooldown age. Exact sizing/NAV/terminal/action/cash/fill
oracles and the unchanged synthetic historical economic-delta analysis remain
in the #402 evidence package. No old golden, xfail, reference return or provider
capability was changed in this follow-up. The 20-year broad-universe multiple
has **not** been computed.

### Rolling admission follow-up after #403

The independent reader follow-up uses verified base
`4dd5af636ed48d6c17d8a75af4209cbc23a17e48`. Its local acceptance covers the
actual public observation-candidate CLI, competing publication exclusion, sealed
metadata and source refresh dates, canonical warmup/production initializer
agreement, offline signing and installation/activation, and the generated
installer's Python programs against isolated PostgreSQL. Legacy readiness and
execution reader regressions remain covered. Strategy/data-semantics identity
changes with the new reader; old runtime certificates and reviewed input
identities cannot simply be reused. No economic golden or provider capability
was changed. The sibling [PR #404](https://github.com/flabber1835/stocker/pull/404)
contains the separate A6/A24 fixes and has six passing CI workflows on
`d79e4207cbc4b12093d9911fb0f3f37e70080b66`; that result does not qualify this
reader branch or the NAS. Detailed commands, source hashes and failure traces
are retained in the reader evidence package linked in A21.

PR #405 CI on `4d758ad993e96043c160f0421bb97881e87e1019` found one
obsolete acceptance fixture: the empty-account test expected a candidate from
warmup `/1` containing only a schema label. The new `/2` guard correctly refused
it (1 failed, 5,023 passed in that lane). The correction retains that input as
a rejection test and moves the positive before/after-binding assertion into
the real sealed-input warmup, signing and activation test. No production guard
or economic expectation is relaxed. The owner-merged #404 base
`3c4fb030b3ad06bc8996771479b2d68b71cb17e6` is incorporated; the original
evidence package remains unchanged. See the [CI follow-up evidence](
../audit/economic_399/rolling_admission_ci_405/README.md) for the exact regression,
mutation and ownership commands on the combined source. Fresh CI remains a
separate requirement; none of this closes the remaining certification gates.

### Known remaining gates

| Gate | Severity / category | Exact remaining work |
|---|---|---|
| C1/F6 | P1, provider contract plus producer implementation | `sentinel/paper/cash.py:188`, `sentinel/execution/alpaca.py:1938`: accepted account-bound exhaustive cash history, correction/classification rules and fixed-close finality are still absent. Empty/repeated snapshots cannot establish completeness. Preserve disabled production acceptance. |
| F19 | P2, provider contract plus accounting design | `sentinel/execution/alpaca.py:1724`, `sentinel/execution/fill_integrity.py:16`: native authority, cumulative-average precision and correction/bust reversal remain unaccepted. Refusal is safe but is not support for these lifecycles. |
| C3 | P1, predecessor recovery protocol | `sentinel/execution/recovered_order_policy.py:75`: retain takeover fencing until account/interval completeness and command preimages prove predecessor ownership and finality. A restored local journal cannot prove omitted provider activity. |
| A21 | P1 admission / P2 visibility, **locally fixed; NAS qualification pending** | `sentinel/feed/readers.py:57`, `sentinel/observation_authority.py:86`, `:187`, `:202`, `:338`, `sentinel/cli/authority.py:65`, `scripts/sentinel_autonomous_deploy_driver.py:384`: authenticated rolling publication/readiness/reference inputs now reach the observation CLI, signed installation/activation identities and generated installer programs. Warmup `/2` runs the selected canonical production strategy; the offline issuer rejects legacy or rehashed strategy/corpus mismatches rather than accepting counts alone. A publication pin spans readiness/warmup/claims; mismatched generation or strategy refuses. Panel readiness is generation-bound. See [design, limitations and NAS handoff](rolling-admission-readers.md) and [retained local evidence](../audit/economic_399/rolling_admission_403/README.md). Stale rolling renewal remains part of the separate open maintenance lifecycle. |
| A5 original / backup duplicate A6 | P1, **open maintenance implementation** | `docker-compose.sentinel-backup.yml:1`, `sentinel/backup_runtime_authority.py:42`: daily verified backup scheduling and proactive horizon rollover remain absent. A single-owner restart-safe maintenance lifecycle, bounded outage recovery and accelerated WAL/retention qualification are still required. This change does not add that service or weaken its guard. |
| A6 endpoint replacement | P2, **locally fixed after #403; device qualification pending** | `sentinel/panel/push_enrollment.py:127`, `sentinel/push_recipients.py:23`, `sentinel/web_push.py:316`: durable successors preserve pending obligations before/after capture. Current recipient revision and outbox attempt fence late results; explicit removal/re-enrollment cannot inherit old alerts. Policy-row serialization and consistent policy-to-outbox lock order exclude rotation during result commit. Real PostgreSQL tests cover endpoint/key rotation during HTTP, restart, delivered peers, targeted enrollment tests and conflicting-device refusal. |
| A12 / A1 residual | P2/P1, code/resource limits | `sentinel/rolling_runtime.py:95` still validates full current inputs during status. `sentinel/shadow_supervisor.py:35` and `:138`, `sentinel/automation_supervisor.py:150` still depend on local filesystem progress. A tiny universe and killable SQL do not establish full-universe latency or resilience to a wedged state filesystem. Qualify independent external health and resource limits; any required bounded-reader/cache or filesystem-isolation implementation remains code work. |
| A14 / A16 | P1/P2, provider/economic policy | Recent SIP entitlement admission and held-spinoff continuation need accepted provider evidence and reviewed economic handling. Do not infer permission from a synthetic fixture or force continuation past an unsupported event. See the retained #400 dispositions. |
| A24 residual | P2, **locally fixed after #403** | `scripts/sentinel_autonomous_deploy.py:1127`: streaming uses one monotonic pipe/process deadline, kills its private process group, reaps the child, retains partial output and returns 124 or refuses. Actual subprocess tests cover silence, partial lines, closed/inherited stdout and a descendant's prevented late write. Host filesystem/output-device stalls remain the separate A1/resource qualification. |
| Full historical replay | Data-dependent, with an import/replay adapter still required | Supply the complete 20-year PIT corpus and warmup: SEP, SPY/BIL SFP, dated TICKERS/issuer/alias/exchange history, ACTIONS and terminal/spinoff terms, completeness/availability evidence, manifests and normalization versions. The user's corpus exists elsewhere; it was not accessed on the NAS. Retained operational publications cover only sessions actually published before their next open. A whole feed outage needs separately authenticated historical input; this recovery implementation does not backdate today's metadata. |
| Deployed qualification | NAS-only evidence after code/provider gates | Exact image/PostgreSQL version, storage capacity, physical WAL restore, real-device delivery, process/container/NAS restart and production-universe resource measurements remain unexecuted. |

The authoritative provider references and their precise limits are retained in
[the pre-NAS ledger](economic-audit-399-pre-nas.md#provider-and-implementation-gates).
No new provider promise is inferred here. Issue #399 is closed on GitHub after
the owner merged #402; that administrative state does not satisfy these gates.

### Host lock ownership follow-up

Review from main `65e261312ec219e014f062c0b6b374066db19d75` found a **P1
serialization-integrity defect** in both host lock verifiers:
`scripts/sentinel_backup_lock.py:50` and `scripts/sentinel_go_lock.py:26` proved
contention at the expected inode, not ownership by the inherited descriptor.
Both now require the same bounded, read-only Linux descriptor-ownership proof
in `scripts/sentinel_lock_ownership.py:8`. Independent, shared and released
descriptors refuse; verification cannot acquire, upgrade or release a lock.
The kernel-owned descriptor remains accepted after the original parent exits.
No historical economic discrepancy is attributed to this finding without
deployed evidence.

See [documented contract and NAS prerequisites](host-lock-ownership.md) and
[retained commands, results and falsifiers](../audit/economic_399/host_lock_ownership/README.md).
This fixes ownership verification within existing lock scopes. Backup locking
is still scoped to the canonical target and host UID; GO locking is scoped to
its checkout. Cross-UID/cross-host backup ownership and cross-checkout GO
coordination are not established by these tests and must be resolved by the
maintenance/deployment ownership contract. Do not claim global single ownership
from a descriptor-level proof.

Recurring maintenance, bounded directory discovery, horizon rollover/retention,
filesystem-progress and other listed provider/data/NAS gates remain open.
PRs #406 and #407 are separate changes; this follow-up does not supersede them.

PR #408's initial head `43540abffff324a567e8cb2e8c8a3aa239a981a9` failed
the operator image-build test lane: the inherited-owner process test passed
`/work/scripts` to its child while CI stores the ownership helper under
`/work/repo/scripts`. The test now honors `SENTINEL_REPO_ROOT`, matching the
inspection-source contract. This is a test execution defect; no production
ownership or economic assertion changed. The original local checkout layout
missed this discrepancy. The separate [CI-layout evidence package](../audit/economic_399/host_lock_ci_layout/README.md)
retains its reproduction and corrected validation; the earlier evidence is
preserved. Exact-image GitHub CI remains required.

### Local execution record

The follow-up package records 239 relevant regression passes before the final
lock-order correction, followed by 29 notification/attempt tests on that
correction and 30 on the stale-rotation/re-enrollment guard. The final expanded
regression passes 242 tests, including removal through successor chains without
crossing an independent re-enrollment boundary. Eleven new
falsifiers each pass unmodified and fail when the named
guard is broken. The first conflict mutant did not reach FastAPI's registered
handler; its failed harness attempt is retained, and the corrected mutant
patches the transaction helper actually called by that route. Syntax/static and
test ownership checks are retained with exact commands and source hashes.
These tests change no strategy calculation or historical reference result.

Verified base and still-current `origin/main`:
`748d54e12a4cdb4b5403c56feb8d6b68e47d0104`. GitHub confirms #402 merged and
all six workflows on its final head `12415629f9a30fb69353990ea24ec3cc99f86255`
succeeded. Those results do not transfer to this follow-up head.

The [new retained evidence](../audit/economic_399/code_closure/README.md)
contains reproduction argument arrays, source provenance, output and checksums.
All Docker campaigns used an empty `.env`, a read-only checkout, `--network none`,
Python 3.12.13, psycopg 3.3.4 and disposable PostgreSQL 17.11. This is not an
exact NAS image or PostgreSQL 16 qualification. Counts overlap.

| Campaign | Result |
|---|---|
| `notification-fence-green` | 126 passed in 50.71 s; one existing Starlette/httpx deprecation warning. |
| `deployment-regression-final` | 77 passed in 10.35 s. Host compatibility tests here run under Python 3.12; actual host Python 3.8 remains its CI lane. |
| `recovery-source-final` | 86 passed in 72.32 s. |
| `continuation-restore-regression` | 41 passed in 582.64 s, including full reconstructed restore and real SQL pin removal. |
| Earlier expanded reconstruction regression | 81 passed in 616.89 s; includes flat and stop-shock paths, clock/input refusal, service waiting, retention and latch integration. Later restore/SQL additions are covered by the 41-case run. |
| Earlier production dependency/notification regression | 282 passed in 104.36 s, before the final occurrence schema/dispatcher additions; not represented as a final-head run. |
| Audit mutation driver | All 22 new named mutants killed, each after an unmodified passing baseline; see `commands.json`. |
| Rolling daily falsifiers | All 15 killed: archives, keys, raw economics, source-precision signal/benchmark rebases, BIL, metadata/actions, prior-state binding, signature, CAS, final timing/backup and read-only restart. |
| Syntax/static/ownership | Changed Python sources parse; no introduced pyflakes warnings; 472 test modules owned, PASS; `git diff --check` passes. Detailed counts/files are retained. |

Failed attempts remain evidence, not acceptance: stale inactive-return and
notification mocks; a source-normalization change during a rolling run; a
mocked async loop that spun after its connector signature changed (terminated
in its isolated container); and an outdated red-alarm object fixture. The
corrected fixtures exercise actual SQL or assert the timeout contract. The
mutation harness initially copied module globals, hiding monkeypatches in two
cases; it now shares the production module namespace. Both affected falsifiers
were rerun and killed. No acceptance was obtained by xfail, fixture repinning,
removing an economic assertion or promoting a capability bit.

### Concrete NAS handoff — not executed

For the notification follow-up, explicitly migrate the isolated clone through
the reviewed fenced installer before starting the dispatcher. Runtime schema
inspection must reject the old catalog and accept the measured Stage-4 digest
`9d80e0801cf8c8e98b739e337eab3d883f3aac3495e47766b3214423ff90b7c1` afterward.
Run `python audit/economic_399/closure_followup_403/run_local.py regression`
and each mutation named in its `commands.json` using the accepted test image.
Retain raw output and the exact source/image/database identities. Pass requires
zero unexpected failures/skips/xfails and detection of every mutant. On a
separately authorized device test, rotate the subscription before capture and
during an in-flight request; retain the original alert/delivery row, successor
link, HTTP attempt and visible notification. Pass requires eventual delivery
on the successor without resending an already-confirmed peer. A stale response
must not retire or complete the successor. Remove/re-enroll must not deliver
the predecessor's pending history. Existing terminal rows are not resurrected.

The earlier [NAS handoff](economic-audit-399-pre-nas.md#concrete-nas-handoff-not-executed)
continues to apply. Add these prerequisites and checks for this change:

1. Resolve/review the open code and provider gates above before claiming a GO.
   Merge only after owner review and exact-head CI. Record the accepted source
   SHA, runtime/test image digests, strategy/economic identity and capability
   evidence. Existing source-bound shadow histories/certificates do not acquire
   compatibility with changed code automatically; use an explicitly accepted
   migration/continuation path, never rewrite their recorded identity.
2. On an isolated physical restore with no broker credentials/network, retain
   `python -m sentinel.restore_validation` output and run the four named local
   campaigns using `python audit/economic_399/code_closure/run_local.py <campaign>
   --image <accepted-test-image>`. Run `rolling-falsifiers` and the 22 mutation
   names separately. Pass requires zero unexpected failures/skips/xfails and
   the intended invariant failure for every mutant.
3. Before migration, retain the actual catalog/global-fence report from
   `sentinel.deployment_fence.require(conn)` on that clone. Pass only for a proven
   empty behavioral catalog or durable kill with invalidated lease. A second
   standby must fail to acquire authority. Explicit migration must install the
   occurrence singleton and current retention SQL. Removing an existing cursor
   must refuse rather than reset occurrence numbering. No primary migration is
   authorized by this document.
4. Stage continuous and interrupted **copies** of the accepted shadow on the
   same dated inputs. Invoke `sentinel.shadow_service.advance_once(config)` once
   per wake with configuration pointing solely at the clone. Retain each
   publication receipt, checkpoint/input/state/genesis hash, reconstruction
   receipt, actual clock, health and execution-table counts. Pass requires equal
   economic state, unchanged original capital/genesis, no retroactive execution,
   reconstruction-only health until the next fresh prospective receipt, exact
   retry after commit/ack loss and named waiting for a missing historical day.
5. Retain unconsumed publication identities across retention and physical restore.
   Interrupt during an outage longer than the ordinary retention window and
   measure disk/resource growth. Pass requires every owed session still available
   and unchanged. A missing/late/ambiguous day must wait/refuse without resetting
   the book. Failure of these criteria blocks qualification.
6. On the separately authorized target fault-injection environment, test silent
   SQL sockets, full log pipes, callback death, repeated same-phase work, stalled
   dispatcher and state-volume failure. Preserve
   `/var/lib/sentinel/shadow-supervisor-critical.json` before any reviewed manual
   clearance. Pass requires bounded kill/reap/restart, original command and alert
   identities, durable refusal across restart, and external alarms when the
   notification database is unavailable. HTTP acceptance alone does not prove
   real-device display or endpoint-rotation continuity.
7. For 20-year replay, inventory/hash the supplied corpus first. Stream daily
   inputs through the canonical production transition in overlapping 300-session
   windows, retaining continuous state across boundaries and scheduled process
   restarts. Use enough prior input for the documented formation rules; never
   restart capital or warmup at each chunk. Retain cash/NAV/share/action/terminal/
   exposure deltas and independently reconcile the event ledger. An unexplained
   difference blocks a reference or multiple; preserve the old golden bytes.
