# Economic certification: remaining code closure

Forward-paper update: [autonomous paper readiness](autonomous-paper-readiness.md)
integrates main's recurring backup renewal and restore-gated retention with
bounded process execution, exact selected-generation verification, and durable
supervisor refusal fencing. It also applies the owner's informational-reporting
policy without relaxing current cash/order safety. The historical ledger below
is preserved. Scheduler installation, observed retention, target resource/restore
qualification and unsupported economic capabilities remain separate obligations;
this update does not close full economic certification.

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

### Finite supervisor timing (A1/A17 startup validation)

Review of main `8a9206c20f7fb2d224c1e3c044e9e0f3953eea5b` found a **P2
configuration-validation defect**: shadow deadline range comparisons admit
IEEE NaN, so elapsed-time comparisons never expire; automation poll/startup
grace comparisons admit NaN or positive infinity, defeating normal stall
supervision or causing a failure after worker launch. This does not establish
that a deployed configuration or historical economic output was affected.

Restore the existing bounded-supervision contract: all three environment
timings must be finite before any worker starts. Preserve the shadow deadline
range [30,7200], positive automation polling, and nonnegative startup grace
(including zero). Invalid timings refuse startup, without creating a child,
changing command identity or altering recovery policy. This clarification
introduces no new timing limits or strategy behavior. Tests must exercise the
public startup entrypoints, accept finite boundaries, and fail if any of the
three finiteness checks is removed. Filesystem stalls and externally qualified
resource limits remain separate open gates.

Local evidence: [commands, pre-fix failures, regression and falsifiers](../audit/economic_399/supervisor_finite_timing/README.md).
The public-entrypoint tests reproduced ten invalid admissions before the fix;
101 targeted tests pass afterward and all three guard-removal mutants fail.
The affected startup checks are `sentinel/shadow_supervisor.py:222` and
`sentinel/automation_supervisor.py:168`. This finding is locally fixed, pending
exact-head CI and owner merge. Step 1 and economic certification remain open.

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
| A2, P1 | `shadow_service.advance_once` â†’ `rolling_runtime.service_advance` â†’ `rolling_recovery.advance_one` preserves the canonical book and advances one missed session using retained dated inputs. Separate reconstruction receipts cannot grant prospective authority. Restart recovers committed candidates/receipts exactly once. | Continuous versus interrupted PostgreSQL clones with actual holdings, a stop shock, pending exits, cooldowns and a subsequent fresh session; equal full canonical state, unchanged genesis/capital and zero execution rows. Full restore validation reports reconstruction without attestation. |
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

### Bounded backup manifest follow-up

Reviewed from fetched main `65e261312ec219e014f062c0b6b374066db19d75`.
The runtime manifest query parsed an unlimited file (**P2 resource defect**,
`sentinel/backup_runtime_authority.py:182`). Its preliminary text-prefix
presence check could also split a valid UTF-8 character and reject a complete
base (**P2 availability defect**, `sentinel/backup_runtime_authority.py:118`).
The presence probe now reads one binary byte. Selected manifests use a single
bounded read of 8 MiB plus an overflow byte; oversized input is refused before
decoding or JSON conversion. Exactly-at-limit complete input remains accepted.
No fallback to an older base or proof-cache advancement follows refusal.

See [design and NAS criteria](backup-manifest-runtime-bound.md) and
[exact commands and retained evidence](../audit/economic_399/manifest_bound/README.md).
The separate archive-integrity changes in [PR #406](https://github.com/flabber1835/stocker/pull/406)
are not included in this branch's main base. Neither change establishes economic
certification. The new 8 MiB manifest ceiling still requires qualification
against deployed manifests and complete-caller resource limits.

**Directory discovery remains locally unresolved**: `_latest_complete_base`
still obtains a materialized directory listing. SQL LIMIT would not bound
PostgreSQL's internal enumeration. A bounded publication index/reader and its
producer ownership contract remain design/implementation work, along with
recurring verified backups and proactive horizon/retention maintenance.

### Known remaining gates

F19 partial-native-notional follow-up, reviewed on main
`8212a55335500b4bbb81853572019d9eb4443724`: **P2 consumer integrity defect**.
`sentinel/execution/fill_integrity.py:49` compared gross notional only when
native shares equalled the order's cumulative filled quantity. A partial set
could exhaust/exceed the whole order's notional, be journaled and emitted as
normal fill alerts while reconciliation returned RUNNING. The same gap crossed
restart when individually plausible responses formed an impossible durable
union. This is not evidence of affected deployed returns; the production native
history capability remains disabled.

The consumer now requires strictly positive residual notional whenever reported
cumulative fills still contain missing native shares. Exact rational products
preserve the boundary regardless of ambient Decimal precision. Full-history
equality, immutable IDs and all existing provider refusals remain unchanged.
The [additive evidence and NAS handoff](../audit/economic_399/partial_fill_notional/README.md)
retain the failed reproduction, real parser/reconciliation/PostgreSQL tests,
durable-union restart/recovery and four falsifiers. The independent oracle asks
whether the missing positive-price shares could account for the remaining cost;
valid recovery retains exactly ten shares/$1,000 and three distinct alerts.
Final local validation: 250 relevant tests passed and all four falsifiers were
detected. Five Python files parse with no pyflakes findings; 479 test modules
have declared ownership. The separate focused run passed 35 tests; these counts
overlap. Exact source hashes and raw results are retained in the evidence package.

Locally fixed: this partial-notional consumer invariant. Still unresolved:
F19 native producer authority, rounding semantics and correction/bust accounting;
C1/F6 cash producer completeness/fixed-close finality; C3 predecessor completeness
and ownership preimages. Historical broad-universe replay remains data-dependent,
and NAS/image/filesystem/device qualification remains unexecuted. The table below
retains those distinctions; neither these tests nor provider documentation grants
economic certification.

| Gate | Severity / category | Exact remaining work |
|---|---|---|
| C1/F6 | P1, provider contract plus producer implementation | `sentinel/paper/cash.py:188`, `sentinel/execution/alpaca.py:1938`: accepted account-bound exhaustive cash history, correction/classification rules and fixed-close finality are still absent. Empty/repeated snapshots cannot establish completeness. Preserve disabled production acceptance. |
| F19 | P2, provider contract plus accounting design | `sentinel/execution/alpaca.py:1724`, `sentinel/execution/fill_integrity.py:16`: native authority, cumulative-average precision and correction/bust reversal remain unaccepted. Refusal is safe but is not support for these lifecycles. |
| C3 | P1, predecessor recovery protocol | `sentinel/execution/recovered_order_policy.py:75`: retain takeover fencing until account/interval completeness and command preimages prove predecessor ownership and finality. A restored local journal cannot prove omitted provider activity. |
| A21 | P1 admission / P2 visibility, **locally fixed; NAS qualification pending** | `sentinel/feed/readers.py:57`, `sentinel/observation_authority.py:86`, `:187`, `:202`, `:338`, `sentinel/cli/authority.py:65`, `scripts/sentinel_autonomous_deploy_driver.py:384`: authenticated rolling publication/readiness/reference inputs now reach the observation CLI, signed installation/activation identities and generated installer programs. Warmup `/2` runs the selected canonical production strategy; the offline issuer rejects legacy or rehashed strategy/corpus mismatches rather than accepting counts alone. A publication pin spans readiness/warmup/claims; mismatched generation or strategy refuses. Panel readiness is generation-bound. See [design, limitations and NAS handoff](rolling-admission-readers.md) and [retained local evidence](../audit/economic_399/rolling_admission_403/README.md). Stale rolling renewal remains part of the separate open maintenance lifecycle. |
| A5 original / backup duplicate A6 | P1, **open maintenance implementation** | `docker-compose.sentinel-backup.yml:1`, `sentinel/backup_runtime_authority.py:42`: daily verified backup scheduling and proactive horizon rollover remain absent. A single-owner restart-safe maintenance lifecycle, bounded outage recovery and accelerated WAL/retention qualification are still required. This change does not add that service or weaken its guard. |
| A6 endpoint replacement | P2, **locally fixed after #403; device qualification pending** | `sentinel/panel/push_enrollment.py:127`, `sentinel/push_recipients.py:23`, `sentinel/web_push.py:316`: durable successors preserve pending obligations before/after capture. Current recipient revision and outbox attempt fence late results; explicit removal/re-enrollment cannot inherit old alerts. Policy-row serialization and consistent policy-to-outbox lock order exclude rotation during result commit. Real PostgreSQL tests cover endpoint/key rotation during HTTP, restart, delivered peers, targeted enrollment tests and conflicting-device refusal. |
| A12 / A1 residual | P2/P1, partially fixed locally; resource qualification open | `sentinel/rolling_runtime.py:95` still validates full current inputs during status. Shadow heartbeat writes/removal now use bounded observers; exceptional exit disposes of the active worker and a known terminal exit is latched before the next heartbeat (`sentinel/shadow_supervisor.py:36`, `:277`, `:313`). See [design and limitations](shadow-heartbeat-isolation.md) and [retained acceptance](../audit/economic_399/shadow_heartbeat/README.md). Startup latch checks, durable latch writes and automation holder publication still depend on filesystem progress. Full-universe latency, kernel-uninterruptible I/O, independent external health and any resulting bounded-reader/filesystem changes remain gates. |
| A14 / A16 | P1/P2, provider/economic policy | Recent SIP entitlement admission and held-spinoff continuation need accepted provider evidence and reviewed economic handling. Do not infer permission from a synthetic fixture or force continuation past an unsupported event. See the retained #400 dispositions. |
| A24 residual | P2, **locally fixed after #403** | `scripts/sentinel_autonomous_deploy.py:1127`: streaming uses one monotonic pipe/process deadline, kills its private process group, reaps the child, retains partial output and returns 124 or refuses. Actual subprocess tests cover silence, partial lines, closed/inherited stdout and a descendant's prevented late write. Host filesystem/output-device stalls remain the separate A1/resource qualification. |
| Full historical replay | Data-dependent, with an import/replay adapter still required | Supply the complete 20-year PIT corpus and warmup: SEP, SPY/BIL SFP, dated TICKERS/issuer/alias/exchange history, ACTIONS and terminal/spinoff terms, completeness/availability evidence, manifests and normalization versions. The user's corpus exists elsewhere; it was not accessed on the NAS. Retained operational publications cover only sessions actually published before their next open. A whole feed outage needs separately authenticated historical input; this recovery implementation does not backdate today's metadata. |
| Deployed qualification | NAS-only evidence after code/provider gates | Exact image/PostgreSQL version, storage capacity, physical WAL restore, real-device delivery, process/container/NAS restart and production-universe resource measurements remain unexecuted. |

The authoritative provider references and their precise limits are retained in
[the pre-NAS ledger](economic-audit-399-pre-nas.md#provider-and-implementation-gates).
No new provider promise is inferred here. Issue #399 is closed on GitHub after
the owner merged #402; that administrative state does not satisfy these gates.

### Bounded base selection follow-up

On main `58c3e071ede06c176e1ed814fb1a7e35b13c33b2`, runtime default base
selection still materialized and sorted the whole retained directory. This
**P2 resource defect** is locally addressed by a cluster-scoped, atomically
published selection record; it supersedes the foreground directory-discovery
gap described above. See [design and rollout](backup-runtime-selection.md).
`sentinel/backup_runtime_authority.py` now reads at most 257 selection bytes,
refuses oversized/malformed/wrong-cluster input and validates the selected
base through the unchanged manifest/WAL/content authority. Missing selection
waits; there is no discovery fallback. A final reread precedes recording a
successful proof, so selection loss/change cannot advance that observation.

`scripts/sentinel-base-backup.sh` invokes the root-owned selection publisher
after verified base promotion. A producer-call falsifier and actual shell/SQL
acceptance connect publication to consumption. Existing media without a record
requires a fresh verified backup through the updated command before ordinary
runtime admission; explicit checkpoint validation remains independently usable.
This rollout prerequisite is intentional and must not be bypassed with a
hand-written record or a capability flag.

The initial broader regression caught premature cache advancement after a
failed final reread (four failure-injection cases). The code was corrected;
those assertions were retained. The additive [evidence package](../audit/economic_399/bounded_base_selection/README.md)
records failed attempts, final results, commands and source hashes.
Final local regression: 291 passed; all seven guard/caller/producer falsifiers
detected. Eight Python files parse, pyflakes is clean, and all 479 test modules
have declared ownership. Exact-head CI, owner merge and NAS qualification remain
required. Key code: `backup_runtime_authority.py:137`, `:475`, `:537`;
`scripts/sentinel-base-backup.sh:202`; `scripts/sentinel-backup-publish-selection.sh:20`.

Recurring scheduling, single-owner maintenance, proactive horizon rollover,
retention, host status/cleanup enumeration, filesystem progress, full-universe
resource measurements and provider/data/NAS gates remain open. This change
does not prove historical economic output was affected or certify the system.

### Combined backup selection, ownership and horizon review

PR #410 now includes owner-merged #408 from verified main
`8212a55335500b4bbb81853572019d9eb4443724`. Conflict resolution retains both
contracts and includes both helpers in the actual shell-lifecycle fixture.
No production algorithm or authority guard changed during this integration.
The additive [retained evidence](../audit/economic_399/backup_selection_integration/README.md)
records 291 backup and 55 lock/concurrency passes, all seven selection and six
ownership falsifiers, and the source identities. Prior evidence is unchanged.

**A5 / backup A6, P1 maintenance remains open, locally quantified.** The actual
runtime interval code admits 64 16 MiB segments (1 GiB) on timeline 1 and refuses
65 before enumeration; a 288-segment daily interval also refuses. PostgreSQL
documents that timeout-switched archived files retain full segment length.
With continuing activity and five-minute switches, the 64-segment scale is
320 minutes; higher traffic or an already nonempty horizon shortens it. Daily
base creation alone is insufficient. This is an arithmetic scenario, not a
measurement of deployed traffic or a new acceptance policy. Required work is
still proactive renewal with verified successor publication, restart-safe
single ownership, bounded outage recovery and retention/restore qualification.

**A1/resource measurement, partially local; NAS qualification open.** The
existing isolated payload probe, limited to two CPUs and 2 GiB memory, completed
three 1 GiB proofs in 2.5663 / 1.6848 / 1.6512 seconds, each with 128 hashes and
2 GiB of payload reads. Container peak memory was 1,245,999,104 bytes. Sparse
zero-filled fixture, PostgreSQL 17.11, payload phase only: this does not prove
the full production caller meets its deadline or the accepted NAS memory limit.
Real populated WAL, complete admission, concurrent workload, exact PG16 image,
filesystem stalls and restart remain required. No economic return is inferred.

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

PR #410 CI follow-up (reviewed failing head `5fd72485c9bbe1e28a470ddbb9697f9ea7ba4aac`):
two P2 test-producer integration defects blocked the internal-state and
composition jobs. The physical fixture never published selection; the simulated
post-seed producer left selection on its old WAL horizon. Both default-admission
refusals reproduced locally. Correct the fixture producers according to the
documented protocol, preserving real verification/archive gates and the
stale/missing-selection refusals. Production code and economic oracles are
unchanged in this follow-up. Key references: `tests/internal_state/physical.py:159`,
`:163`; `tests/internal_state/test_physical.py:109`;
`tests/production_composition/test_canonical_go_e2e_harness.py:238`.

The additive [CI follow-up evidence](../audit/economic_399/backup_selection_ci/README.md)
retains reproduction, positive acceptance and four detected publication/order
falsifiers. Focused non-root tests: 27 passed; root physical tests: 7 passed.
All ten selected lifecycle scenarios passed, including real populated restore
and media repair in both simulated profiles, plus two deterministic seeds.
Both affected owner suites: 655 passed and one unchanged foreign-owner test
failed because the local image lacks `sudo`; GitHub Ubuntu provides that tool.
This is an explicit local environment limitation, not a passing ownership claim.
All 479 test modules remain owned. Fresh-head CI (including that ownership test
and PG16 physical/GO stages), owner merge and NAS qualification remain required.
Existing maintenance, provider, data and NAS-only gates remain open; neither
fixture integration nor green CI establishes economic certification.

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

### Concrete NAS handoff â€” not executed

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

### Backup proof resource and integrity follow-up

Reviewed against independently fetched main
`3c4fb030b3ad06bc8996771479b2d68b71cb17e6` (owner-merged #404).
The owner subsequently merged the rolling-admission implementation in
[PR #405](https://github.com/flabber1835/stocker/pull/405). PR #406 incorporates
freshly fetched main `65e261312ec219e014f062c0b6b374066db19d75` without source
conflicts. See the [combined validation record](
../audit/economic_399/combined_405_406/README.md); previous evidence remains
unchanged. Step 1 and economic certification remain open.

| Finding | Severity and disposition | Production path and acceptance |
|---|---|---|
| WAL enumeration preceded its real proof ceiling | P2, locally fixed | `sentinel/backup_runtime_authority.py:230`: inclusive interval count, history-object reservation and WAL byte subtotal refuse before name construction. Independent exact-limit/log-boundary cases and enumeration tripwires cover all three limits. |
| Re-statting payload size bypassed the checked read budget | P2, locally fixed | `sentinel/backup_runtime_authority.py:343`: SQL reads at most the already-checked length. Real PostgreSQL growth, short-file and missing-file cases exercise the query; a stat-sized-read mutant fails the independent digest oracle. |
| Coarse timestamps could authorize unchanged-content reuse after same-second replacement | P1, locally fixed; performance qualification open | `sentinel/backup_runtime_authority.py:423`: metadata can no longer skip fresh hashes. Two bounded content passes, final metadata and alias checks must agree. Actual SQL caught the original defect; deterministic precision-collision, replacement, sidecar, alias and cache-poisoning falsifiers verify refusal. Last observations detect horizon regression but never grant cached content authority. |

The final broader campaign passed **252 tests**, including physical-recovery
tests and every consumer of the changed backup test adapter; the focused
campaign passed **94** (overlapping counts). All **nine** new mutants failed at
their intended assertions. The media-fault campaign now derives all read
boundaries from the successful trace, testing four failure classes at all
18 reads (72 injections), instead of asserting an obsolete count of 15.
Failed intermediate campaigns are retained, including the real timestamp
failure; no golden return, xfail or capability was changed.

At the maximum 1 GiB distinct payload horizon, three local, two-pass SQL proofs
took 2.432, 1.559 and 1.550 seconds. PostgreSQL backend peak RSS was 35,040 kB;
whole-container peak memory was 1,215,889,408 bytes, including filesystem cache.
This used sparse synthetic zero files, PostgreSQL 17.11 and Docker capped at
2 GiB / two CPUs. It measures only the archive payload phase on this workstation,
not the complete caller, production media or PostgreSQL 16/NAS latency.

See [design, limits and NAS procedure](backup-proof-resource-bounds.md) and
[exact commands, source hashes and raw evidence](../audit/economic_399/backup_proof_bounds/README.md).
Open **P1 maintenance** remains: recurring verified backups, proactive horizon
rollover, single ownership, restart/outage recovery and retention. Open **P2
resource review** also includes base-directory enumeration
(`sentinel/backup_runtime_authority.py:131`) and full manifest parsing (`:175`).
The pre-existing full-universe status and filesystem-progress gates remain open.
No NAS or real broker account was accessed.

### GO renewal after runtime horizon exhaustion

Review on main `8212a55335500b4bbb81853572019d9eb4443724` found another connected
**P1 availability/recovery defect within A5 / backup A6**: status admitted intact
chains beyond the runtime payload ceiling, so GO reported a healthy backup and
skipped the renewal that runtime admission required. The new negative acceptance
tests reproduced two false-ready results and two missing early object refusals;
the new GO reason was also refused by the old classifier (five expected failures).

`scripts/sentinel-backup-verify-chain.sh:81` now counts the inclusive interval
and timeline history against the existing 1,024-object/1 GiB ceilings before
hashing. `scripts/sentinel-backup-status.sh:182` recognizes exhaustion only with
the exact exit-code/token pair. `scripts/sentinel_go_backup_refresh.py:34`
routes that reason into the existing certified single-refresh path. A successor
must pass production creation and exact-path checks; retained old media remains
intact. Bring-up uses the same classifier. There is no permission to treat the
unhashed old chain as intact or to waive any successor integrity check.

Local acceptance: **319 relevant regression passes**, plus **one real PostgreSQL
shell/manifest test** admitting 64 segments and refusing 65. **All eight mutants
detected**. The actual shell/GO path renews at a later WAL position, avoids a
second renewal on a fresh invocation, and refuses failed creation or corrupted
successor evidence. Six Python files parse/pyflakes clean; both changed shell
scripts pass syntax; 480 test modules owned after integration of owner-merged
#409/main `84582af2020a708ab076821693ffa4ea93ebed1c`. All eight changed production,
test and runner files are unchanged by that merge; all 22 focused cases passed
on the combined source. See [design](backup-horizon-renewal.md)
and [retained commands, failures, provenance and NAS handoff](../audit/economic_399/backup_horizon_renewal/README.md).

This closes exhausted-horizon GO classification/renewal, not unattended
maintenance. Recurring proactive renewal, supported-scope single ownership,
restart/outage scheduling, retention, host directory/manifest/read-race bounds
and complete physical/NAS qualification remain open. The existing explicit
restore drill can still examine older recovery points independently. Pending
#410's bounded selection remains separate and must retain both contracts on
integration. C1/F6, F19, C3 and authoritative replay/data gates are unchanged.
No historical-return impact or economic certification is established.

### Recurring proactive backup maintenance and retention

Implemented as Step 1 work, initially based on main
`84582af2020a708ab076821693ffa4ea93ebed1c`, incorporating #410 and #412.
The owner merged #410 during implementation; current-main integration and
reviewed source identities are retained in the
[maintenance evidence](../audit/economic_399/recurring_maintenance/README.md).

| Claim / finding | Disposition | Production path and limits |
|---|---|---|
| A5 / backup A6 recurring renewal and retention were absent | P1 implementation gap addressed locally | `scripts/sentinel-backup-maintenance.sh` enters `scripts/sentinel_backup_maintenance.py`: 12-hour / 256 MiB current-WAL triggers, exact successor status, full restore, durable identity-bound receipt, then offline retention. Single ticks and an optional single-owner loop are provided. Scheduler installation is a NAS prerequisite. |
| A worker could outlive its host client's lock | P1 lifecycle gap addressed for the documented one-host/one-account scope | Actual producer, restore and retention workers hold the same persistent media flock. Restore holds it continuously from copy through PostgreSQL shutdown. Worker deadlines, journal recovery and labeled disposable-resource reclamation handle interruption. NAS flock behavior remains unqualified. |
| Archive-end timing could auto-promote the restore before its recovery-state check | P2 restore availability defect fixed locally | `scripts/sentinel-restore-worker.sh` pauses at the recorded target LSN; `scripts/sentinel-restore-drill.sh` requires pause and marker replay, then explicitly promotes. Pinned PG16 positive acceptance and removal falsifier exercise actual PostgreSQL. |
| Equal timestamps could conceal a same-size `.env` rewrite | P2 input-consistency defect fixed locally | `scripts/sentinel_env.py:read_bytes` now requires two bounded complete byte observations to agree, preserving metadata/alias/type checks. A deterministic same-timestamp rewrite falsifier detects removal of the byte guard. |
| Safe deletion of obsolete bases and WAL | Locally verified under explicit scope | `sentinel/backup_retention.py` keeps selected/recent/daily/weekly bases; journals deletion before quarantine; revalidates protected identities after interruption; computes WAL floor from every retained Start-LSN. Boundary segments, timeline histories, other timelines and unknown names are preserved. Mixed timelines retain all WAL. |

Local results: 361 backup/GO/ownership regression passes; 930 final maintenance,
restore-contract and environment checks; 873 environment checks on actual host
Python 3.8.15 (overlapping cases); 15 code falsifiers plus the PG16 target
falsifier detected. Private PostgreSQL-owned 0700 WAL directories are exercised
through the actual worker CLI: missing capability refuses before base deletion;
the reviewed offline worker capability succeeds without weakening media modes.
Final receipt/semantic and provenance details are in the retained record.

**Still open:** NAS scheduling/reboot/alert delivery, the one-host/one-account
operational prerequisite, real target flock/rename/fsync guarantees, full-volume
capacity and throughput, populated exact-image restores, corpus-dependent
historical deltas and full-universe/callback resource qualification. C1/F6 cash
producer completeness/finality, native F19 provider authority and C3 predecessor
incarnation evidence are unchanged. No broker capability flag, golden economic
result or certification status was loosened. Step 1 and economic certification
are not marked complete.

### Compact rolling status input review (A12/A1)

Reviewed from current main `e3dfb033d25ed68e5e1f6d2386285afabc62e801`
(owner-merged #411). **P2, locally fixed:** the read-only status path discarded
its input material only after retaining 252 sessions for every security. A
5,000-security / 300-session synthetic input-phase probe measured 778,904 KiB
Python peak RSS, above the panel's 512 MiB limit. This is evidence of excessive
allocation, not evidence of a deployed OOM or an incorrect historical return.

`rolling_runtime._current` now uses compact readiness counts, with the same
complete sealed-content hashes, dated security mapping, action checks, source
clock, publication pin and readiness thresholds. The strategy materialization
API and economic state are preserved. Independent SQL counts, production status
tripwires and guard-removal failures accompany the existing runtime regressions.
The compact input phase measured 130,592 KiB peak RSS on the same synthetic scale;
it still took 28.70 seconds. Source identity changes require the existing reviewed
continuation boundary; prior certificates and golden artifacts are not rewritten.

**Open P2:** complete status/checkpoint and reference/action-history memory,
full-hash scan latency, concurrent panel requests and target resource limits.
The input-phase measurement does not close these gates. Proactive maintenance
and heartbeat supervision are tracked separately in pending #413 and #414.
Provider cash/fill/predecessor guarantees, authoritative historical economic
deltas and NAS qualification remain open. Step 1 and certification are not
complete. See [design](rolling-status-resource-bounds.md) and
[commands, retained evidence and qualification procedure](../audit/economic_399/rolling_status/README.md).

### Report-only caller closure and current resource inventory

Further tracing of #415 found nine remaining calls that discarded a materialized
warmup: operational assessment, strict readiness, execution readiness, already-
current acquisition, newly published acquisition, its inner operational validation,
runtime admission before an idempotent retry, and both historical recovery gates.
These now use compact assessment
without changing their failed-clause/refusal semantics, publication/owner checks,
source identity or DATA_ONLY scope. Six production-entrypoint tests reproduced
the allocation before the fix; the first-publication case covers both inner and
outer checks. Historical recovery has additional fresh-step and trailing-candidate
acceptance that preserves reconstruction-only authority and original state identity.
See the [additive evidence](../audit/economic_399/rolling_status/report_consumers/README.md).

The earlier backup directory/manifest implementation-gap descriptions are
historical: current main `e3dfb033d25ed68e5e1f6d2386285afabc62e801` includes
bounded selection (257 bytes including overflow) and bounded manifest reads
(8 MiB plus overflow), with no discovery fallback. Their previously retained
acceptance remains valid; deployed capacity/latency qualification remains open.
They must not be counted again as unimplemented fixes.

The remaining local resource review is the complete status/checkpoint and
reference/action load, concurrency and full-scan latency, plus actual material
consumers in strategy warmup/database-health certification. Compact counts do
not replace those consumers' economic inputs or warmup identity. Pending #413
implements recurring maintenance; pending #414 addresses heartbeat supervision.
Their CI/integration and independent filesystem/host qualification remain distinct.
No required provider/data/NAS gate is closed by these resource fixes.

### Complete public status and HTTP concurrency review

Reviewed against owner-merged main
`29cdd7727ba2adea27672830c538d76a2218943e`, with pending #415
`558673b1b434760673ee1de52c25c4e1e1f707c7` integrated in an isolated branch.
Main now contains #412 and #413; their earlier pending labels above are historical.

**P2 concurrency defect, locally fixed:** all three full panel routes previously
ran independent expensive builds. `sentinel/panel/app.py:39` now admits one build
and returns immediate 503 UNKNOWN with retry/no-store for contenders; completion
and exceptions release the slot. The deployed Uvicorn command explicitly selects
one worker. Real routed acceptance reproduces the defect before the fix; final
targeted regression passes 160 cases and all four removal mutants are detected.

**P2 single-request resource defect, still OPEN:** complete public shadow status
on 5,000 synthetic securities / 300 sessions reaches **2,013,424 and 2,012,992 KiB
VmHWM per reader**, well beyond the panel's unchanged 512 MiB budget. Two readers
sharing an 8 GiB / two-CPU test container take **131.21 / 131.33 seconds** each.
Closure/checkpoint/observer verification accounts for about 99 seconds; compact
current-input assessment takes about 31 seconds. The concurrency fix does not
resolve this allocation or establish a cumulative latency bound. No deployed OOM
or target performance is inferred from the fixture.

Both readers preserve initialized canonical state, session counts and zero
command/fill counts; retained outputs agree on NAV and authority. This is a
first-origin synthetic status probe, not a historical economic replay or the
entire HTTP build. Advanced held-position checkpoints, realistic retained
references/actions, actual strategy material consumers and full HTTP resource
qualification remain open. Repeated canonical-state construction needs further
local code work, not merely NAS evidence. Provider and historical-data gates are
unchanged; Stage 1 and economic certification remain incomplete.

See the [design](full-status-resource-review.md) and
[retained measurements, exact commands and NAS handoff](../audit/economic_399/full_status/README.md).

### Single-request status memory remediation

Reviewed implementation `d5c35410f6be7e93a0fdc66183e56de0009be351`, on verified
main `e255a78aaf4f89d25fc634864aafd2656c6cd176` after owner merge of #415; includes
the unchanged #417 concurrency fix. The previous single-request finding above
is now **locally fixed for the measured 5000-security synthetic scope**.

`sentinel/shadow_observation.py:963` streams every feed-series entry, while
`:1728` consumes and releases the verified seed before reading the checkpoint
session. `sentinel/rolling_checkpoint.py:98` and
`sentinel/rolling_daily_checkpoint.py:102` reuse one complete verification;
`sentinel/core/session.py:58`/`:319` avoid duplicate encoded/copied state. No
canonical field, economic invariant, source identity, hash or publication binding
is omitted. Status is bound to one repeatable-read, read-only transaction;
advancement keeps its reusable observer. A new lifecycle test caught retained
psycopg loader classes; fixed classes with disposable instance pools address it.

Two complete public status calls in one process peak at **401888 KiB (392.47 MiB)**,
preserving initialization state/authority, NAV and database counts. Complete
`/panel.json` peaks at **423884 KiB (413.95 MiB)**. Both containers exit 0 under
an actual 512 MiB/no-swap cap with zero OOM events. Bypassing the optimized route
causes the same cap to OOM-kill the negative control (exit 137). First-origin
latencies are 98.695/95.751 seconds for status and 92.853 seconds for HTTP under
the retained local load. These are observations, not an accepted latency SLO.

The actual next-session transition commits 20 positions. Its complete HTTP read
also passes the same cap, peaking at **437184 KiB (426.94 MiB)** in 91.089 seconds.
Two advanced public status calls preserve their state, authority, NAV and row
counts, both peaking at **419848 KiB (410.01 MiB)**, with zero OOM/limit events.
Independent Decimal accounting explains its NAV drop as $97.91628 of existing
10 bps entry costs on $97916.28 notional; residual float-mark/accounting differences
are below $0.00000001. The source-finality guard correctly refused the first
advanced probe's stale synthetic clock; only the probe clock was corrected.
Publication plus that real transition takes 1007.224 seconds, explicitly leaving
daily throughput qualification open. These fixtures do not qualify a backtest.

Locally verified: 77 canonical/memory tests, 277 restart/recovery/panel regression
tests (overlapping campaigns), ten guard-removal controls, unchanged historical
serializer output/ownership, full-payload and last-security corruption refusal,
bounded decoder lifetime, and 489 owned test modules with none unowned. No golden
repin, xfail, provider capability enablement, NAS or real broker access.

**Still open:** target workload/history and database-service memory qualification,
full-scan latency, provider C1/F6/F19/C3, authoritative historical economic deltas
and NAS-only deployment/restore evidence. The fixture setup process reaches
**2.82 GiB**, including retained synthetic producer data; this is not an isolated
production-runtime measurement. Material-consuming initialization/certification
under its configured 4 GiB limit remains a P2 local resource-review item, not something
the status fix closes or that this setup peak alone proves defective. Production
source changes require the existing reviewed continuation boundary. Stage 1 and
economic certification remain incomplete. See the
[complete commands, evidence scope, findings and NAS handoff](../audit/economic_399/status_memory/README.md).

### Separately capped runtime and PostgreSQL cost review

Measured production `9bececa241052c43851f5da586499a6ae3a8039f`, then integrated
owner-merged #416/main `8bf86ed8ca1e9fa2a6cbb9ac1588c8bcda8712bb` in a separate
checkout. Reviewed integrated source/tests:
`ffbf82b127784c145d697078ad1e8c03b70a0c46`. This includes unchanged #417/#418
production dependencies and #418's CI-only test-location fix. The four cost-review
production files are byte-identical across the measured and integrated commits;
the complete broad resource run does not silently claim the later source identity.

| Finding | Disposition | Evidence and remaining boundary |
| --- | --- | --- |
| P2: separately capped PostgreSQL OOM during large shadow persistence | Implementation fixed; local synthetic storage acceptance | `sentinel/observation_storage.py:31` parses bounded groups, assembles native JSONB transactionally and inserts one complete immutable row. The failed INSERT and subsequent old SQL-equality OOM are retained. PG17 and pinned PG16.14 complete the 5,000-series storage diagnostic under 1 GiB, with no OOM. Cache reaches the ceiling; this does not prove spare capacity or populated-restore qualification. |
| P2: whole-JSONB genesis equality duplicates the database parse | Implementation fixed; exact comparison acceptance | `sentinel/shadow_observation.py:1000` reads one coherent complete value, decodes exact decimals and compares every field/type via `sentinel/observation_storage.py:14`. Genesis/session retries reject sub-float-precision corruption. Independent PostgreSQL numeric/type equality, rollback, odd/final batches, immutable conflicts and decoder-lifetime controls pass. |
| P2: expensive scalar-by-scalar canonical serialization | Locally reduced; latency gate remains OPEN | `sentinel/core/session.py:58` batches at most 256 small scalars with standard strict JSON spelling. Independent hashes, malformed inputs, cycles, final-element changes and a measured scratch-allocation falsifier preserve the contract. Profiled 100-security transition improves 42.39 to 26.68 seconds without changing NAV. This is not a full-scale SLO claim. |
| Runtime material-consumer memory | Separately measured synthetic scope | Initialization uses 2,093,012 KiB VmHWM under the existing 4 GiB runtime cap. Its input producer and 1 GiB database are separate processes/services. The prior 2 GiB handoff/table was documentation drift from #235; no service limit was increased. Real retained reference/action targets remain required. |
| P2: full-scan status latency and real retained history | OPEN, local engineering plus workload-dependent acceptance | At configured 0.5 CPU, origin status takes 153.15/158.38 seconds; full HTTP takes 170.92 seconds. `sentinel/rolling_runtime.py:48` and `sentinel/shadow_runtime.py:793` still perform full content/authority verification. No accepted latency budget or authoritative retained-history workload is supplied. Synthetic completion cannot close this gate. |
| Authoritative historical economic replay | Located input; admission/integration OPEN | User-identified `research/backtester` supplies the retained schema-1 broad PIT artifact: 31,820,893 rows, 16,957 securities and 5,176 sessions, downloaded and integrity-scanned locally. Current replay requires schema 2 plus a metadata pointer absent from its named branch and pins older production blobs. Resolve these explicit version/adapter gaps; do not substitute another dataset or weaken admission. Largest observed session has 8,408 rows and a 300-session window has 2,474,682 rows, beyond the synthetic resource scope. No twenty-year multiple is claimed. |
| C1/F6, F19, C3 and deployed qualification | Unchanged OPEN | Provider cash/fill completeness, correction/bust semantics and predecessor ownership/finality remain separate from storage performance. #416 informational paper reporting does not certify those histories. NAS exact-image/runtime, filesystem/backup/restore, scheduling and capacity evidence are still required. |

Validation: **397** final-production integration regressions; **161** focused
storage/identity tests (overlapping); **4** expanded decoder-lifetime cases;
**11** removed/broken-guard controls detected after passing baselines; **30**
pinned-PG16 SQL/decoder cases. Following the main merge, **163** targeted tests
and the complete 100-security origin/advanced/HTTP smoke campaign pass; its
advanced NAV remains **99903.33772**, with independent Decimal accounting.
There are **491** owned test modules and zero unowned. Existing #418 CI's sole
Compose-location test failure was fixed and its 13 relocated tests pass.
No golden repin, xfail, provider capability enablement or broker/NAS access.

Stage 1 and economic certification remain incomplete. See the
[retained results, exact commands, economic explanation and NAS handoff](../audit/economic_399/status_cost/README.md)
and [design decisions recorded before implementation](status-runtime-cost.md).
