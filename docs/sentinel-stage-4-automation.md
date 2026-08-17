# Sentinel Stage 4 automation and signed execution authority

The bounded, renewable `PAPER_OBSERVATION_ONLY` authority and its NAS operating
sequence are defined in `docs/sentinel-paper-observation.md`. Observation mode
does not weaken or relabel the historical certification path described below.

> **Status: DESIGN CONTRACT FOR THE STACKED IMPLEMENTATION. NOT ACTIVATED.**
> Stage 4 is paper-only unattended orchestration around the existing canonical
> preparation and execution paths. Installing or starting the service does not
> authorize broker access. A fresh database is disabled, its kill switch is
> engaged, and it has no trusted certificate.

Read `sentinel-deployment.md`, `sentinel-architecture.md`, and
`sentinel-execution-contract.md` first. This document adds orchestration and a
cryptographic authority boundary; it does not change Wealth Core, controller,
portfolio, plan, reconciliation, or executor semantics.

## 1. Non-negotiable boundaries

```text
Wealth Core / SessionState     existing canonical strategy state
prepare_paper_plan             the only daily advance/adopt path
execute paper gateway          the only current-plan execution gate
execution.executor             the only order state machine
Stage 4                        schedules and records those paths; owns no book
```

The broker-independent `sentinel.automation` package imports none of the paper,
migration, handover, or administrative surfaces. The separate
`sentinel.automation_runtime` composition root injects the canonical feed,
preparation, read-only recovery, and execution callbacks. This is dependency
inversion, not a second implementation.

- Alpaca paper only. A non-paper URL refuses before broker construction.
- Historical missed sessions advance canonical state only. Only the newest
  closed-session plan can remain current and executable.
- Migration is never imported or callable by the automation package.
- Installation is inert. Activation and kill-switch release are separate,
  audited commands with unmistakable confirmations.
- The kill switch never cancels orders or liquidates positions. It prevents new
  broker reads and mutations and leaves UNKNOWN/open work for explicit recovery.
- A cycle state, a leader lease, or a green panel is never evidence that a
  broker side effect occurred. Only the command journal plus complete broker
  reconciliation establishes external truth.

## 2. Durable control and activation

`sentinel_automation_control` is a one-row operational authority. Its initial
state is `enabled=false`, `kill_switch_engaged=true`, generation 1. The row is
seeded only when its table is genuinely created; later absence is corruption.
It binds activation to deployment, broker, account, takeover epoch, certificate
digest, rollout mode/version, and a canonical automation-config digest.

Every activation, deactivation, kill engagement, and kill release increments
the generation and appends an immutable event. Activation requires the exact
paper binding, a currently valid signed certificate permitting unattended paper
automation, the current rollout state, no unresolved old-writer ownership, and
the operator's explicit reason. Activation leaves the kill switch engaged.
Release is a second command confirming account, deployment, certificate, and
unattended paper authority. Deactivation or emergency kill is allowed without
the leader lease and bypasses the shared execution writer advisory lock. It
serializes on the automation control row itself, increments the generation,
expires the lease, and is checked by the fresh broker membrane before any
further transport. A slow broker call or executor holding the writer lock
therefore cannot make the kill command unavailable. It performs no broker
mutation and does not cancel an already-sent request.

The supported emergency host path is `scripts/sentinel-emergency-kill.sh`. It
uses only the ordinary Sentinel runtime plus the behavioral PostgreSQL target;
it deliberately does **not** load the backup overlay, authorized-runtime
overlay, broker credentials, Git/image certification variables, backup-root
attestation, WAL write probes, or a leader lease. Database unavailability or a
corrupt/missing control singleton may still refuse because that row is the
fence authority. Ordinary startup and backup operations keep their existing
durability preflight unchanged.

Unattended runtime startup is also not a schema-migration surface. Once Stage 4
is installed, automation uses a read-only behavioral-schema validation gate.
Schema installation/upgrade remains explicit and serialized; its PostgreSQL
lock wait is bounded so an attempted migration fails visibly rather than
becoming an unbounded AccessExclusive queue head in front of heartbeat, status,
or emergency control traffic.

Changing the binding takeover epoch, certificate, rollout version, or automation
configuration makes the activation stale. If a running service observes a
different automation-config digest, it atomically engages the kill switch,
increments the generation, clears the old authority verdict, invalidates the
lease, and records both digests in the control event before returning. Reverting
the environment cannot resume that generation; an operator must explicitly
activate/release again. Restart never repairs or silently updates intent.

Generation changes fence workers, but they do not erase obligations. After a
later kill release or reactivation acquires a new live lease, the leader must
adopt every nonterminal older-generation cycle before it may create or advance
a current-generation cycle. Adoption is a conditional, current-generation
write that preserves the cycle id and all immutable cycle identity while
appending an event containing the adopting generation and fencing token:

- `DISCOVERED`, `REFRESHING_DATA`, `PREPARING`, `PLAN_READY`,
  `WAITING_OPEN`, and preparation/refresh retry cycles have no durable broker
  transport boundary. Adoption terminalizes them as `SUPERSEDED`; their old
  plan, if any, can never become executable.
- `EXECUTING`, `RECONCILING`, and execution/recovery retry cycles may have an
  externally ambiguous command. Adoption first invokes only the injected
  read-only recovery path under the current signed paper-account authority.
  Clean recovery terminalizes the old cycle as `SUPERSEDED`, without loading
  or executing its stale plan economics; an explicit
  nonretryable authority/integrity result terminalizes it as `BLOCKED`; an
  incomplete transport observation remains durably retryable. Adoption never
  invokes the execution callback and never submits, cancels, or resurrects the
  old plan.

The adoption write matches the current control generation, holder, live lease,
and fencing token. It deliberately does not require the old cycle's generation
or `last_fence_token` to equal the current lease: those fields are durable
evidence of the authority that last touched the old cycle, not authority for a
new worker. The immutable cycle row retains its originating generation; the
append-only event records the adopting generation. A restored or rebound
account/deployment/takeover identity cannot adopt an ambiguous transport cycle:
it latches `BLOCKED` without broker contact and requires explicit operator
recovery. This makes generation turnover recoverable without making any old
plan executable.

An `EXECUTING` cycle, or an execution retry, that is observed at or after its
session close also enters read-only recovery immediately. It is never returned
as a merely in-memory blocked result and never resumes the mutation callback;
the recovery result is persisted as `SUCCEEDED`, `SUPERSEDED`, `RETRY_WAIT`,
or `BLOCKED`.

## 3. Leader lease and fencing

One PostgreSQL singleton lease contains the holder instance id, monotonically
increasing fencing token, control generation, acquisition/heartbeat/expiry
timestamps, and PostgreSQL's timestamp as the clock authority.

- Acquire/take over while briefly holding the existing execution writer lock.
- A live lease is not stealable. Expiry permits takeover with token +1.
- Renewal matches holder, token, generation, and an unexpired lease. It cannot
  resurrect an expired lease.
- Clean release expires the row but never resets the token.
- Every cycle/control-sensitive write conditionally matches the current
  generation, holder, live expiry, and fencing token. Zero affected rows is
  `StaleLeaderRefused`.
- The heartbeat uses a separate database connection so synchronous strategy
  work cannot disguise a dead worker. Losing heartbeat authority stops the
  cycle before the next broker boundary.

The lease fences workers sharing this database. It cannot fence a restored
second database whose host still owns valid credentials; credential revocation
and the existing explicit restored-account takeover ceremony remain mandatory.

## 4. Calendar scheduler and cycle state

All stored wake instants are UTC. Session decisions come only from the pinned
XNYS calendar:

- preparation: actual session close plus configured publication delay;
- execution: actual next-session open plus configured execution delay;
- final boundary: the actual effective-session close, including 13:00 ET
  half-days;
- holidays and DST are consequences of the calendar, never weekday arithmetic.

On restart, the service recomputes obligations from XNYS, the canonical
processed-session cursor, the current plan, unresolved commands, and the current
clock. It wakes at the earliest of the recomputed due time, persisted retry,
heartbeat, control poll, or alert delivery. Missing a historical execution
window never causes a late increase. Catch-up advances missed state and adopts
only the newest plan.

Before canonical catch-up begins, the composition root durably creates
deterministic historical `DISCOVERED` audit cycles for the observed cursor gap.
Only a successful canonical preparation callback may mark those rows
`MISSED_STATE_ONLY`, and the service performs that marking even when a restart's
idempotent preparation result no longer reports the already-created gap. A
crash before canonical persistence therefore leaves `DISCOVERED`, while a crash
after canonical persistence converges to `MISSED_STATE_ONLY`; neither boundary
can create an executable historical plan.

The deterministic id permits only one lifecycle row for an account and
decision session. If an earlier activation already terminalized that session as
`SUPERSEDED` or `BLOCKED`, later canonical catch-up reuses that terminal record
as the automation-side audit evidence instead of attempting to manufacture a
second historical row with different immutable authority fields. The canonical
processed-session cursor proves the later state-only advance; the terminal
cycle proves why no old plan can become executable. A nonterminal row, or a
`SUCCEEDED` row paired with a cursor that still claims the session is missed, is
an integrity conflict and catch-up refuses.

One deterministic full-hash cycle id names deployment/account/takeover epoch
and decision session. A cycle stores scheduled close/open/end, control
generation/fence, attempts, next wake, publication/rollout/certificate/state/
plan identities, last clean reconciliation, and diagnostic outcome. It stores
no target economics.

```text
DISCOVERED -> REFRESHING_DATA -> PREPARING -> PLAN_READY
           -> WAITING_OPEN -> EXECUTING -> RECONCILING -> SUCCEEDED

RETRY_WAIT          bounded retry with durable next wake
BLOCKED             integrity/authority failure requiring an operator
MISSED_STATE_ONLY   historical session advanced without an executable plan
SUPERSEDED          older cycle whose plan is no longer current
```

Data refresh invokes the existing canonical daily ingestion/publication path.
It recognizes an already published close after restart. It must not publish a
new version while unresolved current-plan commands still require the old plan's
authority; reconciliation/recovery comes first. No second corpus loader or
publication mechanism is permitted.

A crash in preparation reruns idempotent canonical catch-up/adoption. A crash in
execution re-enters through reconciliation and deterministic client keys. A
cycle succeeds only after a fresh COMPLETE/RUNNING/clean reconciliation, no
in-flight command, and no actionable delta. A successful submit response alone
is not cycle success. A clean current-generation recovery with remaining delta
may re-enter the executor only through a new durable `RETRY_WAIT` boundary with
`retry_phase=EXECUTE`, and only before that cycle's actual session close. After
the close it becomes `SUPERSEDED` and is never late-submitted. A rejected or
cancelled command with remaining delta becomes `BLOCKED`; automation never
mints unattended retry revisions for terminal broker refusals.

Callback failures have two durable classes. Explicit authority, certificate,
identity, publication-integrity, plan-integrity, or invariant refusals are
nonretryable and latch the affected cycle `BLOCKED`. Transport unavailability
uses bounded `RETRY_WAIT`; a partial or self-inconsistent broker observation
remains in read-only reconciliation until a fresh COMPLETE observation exists.
Temporary readiness, account availability, and lower unsettled buying power are
retryable, while account identity and margin-envelope violations are not.
Lease/fence loss cannot authorize either write. Kill, missed-window
supersession, generation adoption,
and blocked outcomes are notifier/outbox eligible so a safe inert result is not
silent. A kill alert is keyed to a durable `KILL_ENGAGED` control event and its
generation. The initial disabled/killed schema row and activation's deliberate
initial kill are inert installation state, not emergency-kill alerts.

## 5. Grants and the guarded broker membrane

Preparation, manual confirmation, and standing automation authority are
distinct typed grants into one shared private execution gateway:

- `PaperPreparationGrant` carries only the expected account and closed
  decision session.  The guarded broker rejects `submit` and `cancel`
  structurally for this grant, before either an authority callback or broker
  transport can run.

- `ManualExecutionGrant` carries the existing exact account, plan, effective
  session, and explicit paper-submit confirmations.
- `AutomationExecutionGrant` carries an exact `PREPARE`, `RECOVER`, or
  `EXECUTE` operation
  scope, cycle id, control generation, holder, fencing token, bound
  account/takeover epoch, rollout, and certificate digest. A `PREPARE`-scoped
  automation grant is structurally read-only just like
  `PaperPreparationGrant`; `RECOVER` is also read-only and may resolve durable
  UNKNOWN/working evidence outside the execution window. Only an
  `EXECUTE`-scoped grant can reach mutation authorization.

Neither grant can carry or replace plan economics. Automation must not fake the
manual CLI confirmation flag.

Every production execution adapter is wrapped by one guarded broker. Before the
first broker read it freshly verifies paper endpoint, signed certificate,
runtime/source/config identities, binding/account, rollout, current durable
plan, and the applicable grant. An automation grant additionally requires
enabled control, released kill switch, matching generation, current cycle, and
live holder/fence.

Immediately before **each** submit or cancel, on a fresh database connection,
the guard repeats certificate/revocation/expiry, binding/takeover epoch,
rollout/current-plan, kill, control generation, cycle, and lease/fence checks.
Database unavailability refuses transport. If authority disappears after
`SEND_PENDING` is committed but before transport, the row remains durably
`SEND_PENDING` and restart resolves it by exact key without inventing a broker
request. Once transport is attempted, an uncertain exception remains `UNKNOWN`.
Guard callback failures on reads are typed authority refusals and latch; an
inner broker read failure remains retryable transport uncertainty.

The control poll verifies the current signed automation certificate under its
live permit even when there is no cycle or the latest cycle is terminal. It
records a generation-bound `FAIL` attempt and enqueues an authority alert on
expiry or revocation. When a nonterminal cycle exists, the same poll latches
that cycle `BLOCKED`. When there is no nonterminal cycle to latch, it engages
the kill switch as a system action, increments the control generation, and
records the authority refusal in the control-event reason. The generation
change clears the superseded verdict display, but the kill and event remain
durable. Restoring certificate validity never resumes a blocked cycle or
releases that kill; either boundary requires a new explicit operator action.

### Administrative broker authority is separate and pre-binding

The inherited-account commands cannot use the bound execution certificate:
their first legitimate use occurs before an account binding exists. They also
must not fall back to an operator confirmation as trust. A distinct signed
administrative-certificate lifecycle therefore stages and activates the same
canonical Ed25519 envelope against an exact proposed deployment, Alpaca paper
account, and takeover epoch. Historical administrative certificates permit a
non-empty subset of `ADMIN_INSPECT`, `ADMIN_MIGRATE`, and `ADMIN_ADOPT`.
A distinct empty-account certificate permits only `ADMIN_BIND_EMPTY`, only for
an unbound epoch-1 account, and explicitly grants no historical causality.
`unattended_automation` is always false. An administrative certificate cannot
carry `PREPARE_READ`, `EXECUTE_READ`, `SUBMIT`, `CANCEL`, or `AUTOMATION`, so it
can never become daily execution authority.

Installation and activation are broker-free, separately named transitions:

```text
install-administrative-certificate   signature + exact subject/runtime checks;
                                     leaves the certificate STAGED
activate-administrative-certificate  exact SHA/deployment/account/epoch;
                                     makes one certificate ACTIVE
revoke-administrative-certificate    removes its authority without broker access
```

The administrative lifecycle has its own monotonic issuer and activation
generations, one-active-certificate constraint, revocation record, and
append-only events. It reuses the reviewed public trust roots and complete
certification evidence but not the execution-certificate active singleton or
rollout transition. Missing state is corruption once certificates exist; it is
never silently reconstructed.

The common signed-envelope schema still carries rollout fields, but an
administrative certificate must name only `PINNED_1_00` and an inert
`PINNED_1_00`-to-`PINNED_1_00` next-version claim. Administrative activation
does not write `sentinel_rollout_state`; those fields are compatibility evidence,
not controller or actuator authority.

`inspect-paper-account` and `migration-plan` require an exact proposed
deployment/account and an active `ADMIN_INSPECT` certificate.
`migrate-account` requires `ADMIN_MIGRATE` and an unbound database.
`inspect-empty-paper-account` and `bind-empty-paper-account` require the
dedicated `ADMIN_BIND_EMPTY` certificate. The latter uses a read-only broker
interface, requires two complete stable flat reads plus strict cash-account
facts, then commits the binding and one-time certificate consumption in the
same database transaction. It cannot inspect or liquidate an inherited book.
`adopt-restored-account` requires `ADMIN_ADOPT` for the exact current binding
and epoch; after the epoch increment that certificate is stale. Before a broker
object is constructed, the command freshly verifies the certificate, exact
subject, independently observed runtime/source/image/configuration identities,
paper endpoint, publication-policy chain, expiry, and revocation. The guarded
administrative broker repeats that check on a fresh database connection before
and after each read and immediately before each exact-id cancellation or named
liquidation submit. A batch cancellation is decomposed so every broker DELETE
gets its own fresh check. The account result must match the signed account
before later reads or mutations are allowed.

Mutation arguments are narrow signed consequences, not caller-selected broker
requests. Cancellation accepts only unique exact IDs from the latest complete
observation. Liquidation accepts only the durable `SEND_PENDING`, account/epoch-
bound legacy migration key, exact broker asset, full observed Decimal position,
and SELL side, after a further complete observation reports no working legacy
order. Generic close, cancel-all, arbitrary submit, and foreign-key lookup are
structurally unreachable.

The final ownership binding or restored-host epoch change repeats authority
under the execution writer lock. Authority loss can therefore leave a safely
flat but unbound account, never an account silently claimed by stale authority.
After initial binding, `ADMIN_MIGRATE` and `ADMIN_BIND_EMPTY` refuse before
broker construction even if their certificates remain cryptographically valid.
Administrative inspection is read-only by type; it has no submit or cancel
method that can reach transport.

## 6. Durable alert outbox

Alerts are state, not log lines. The outbox uses a full idempotency key and a
versioned payload, severity/type, `PENDING | DELIVERING | DELIVERED |
DEAD_LETTER`, attempts, next attempt, delivery lease, last error, delivery
timestamp, and separate acknowledgement fields. Attempt history is append-only.

Workers claim with `FOR UPDATE SKIP LOCKED`. Expired claims are recoverable.
Backoff is deterministic and bounded; exhaustion dead-letters. A crash after
remote delivery but before the local commit may redeliver, so adapters receive
the same idempotency key. Adapters come from an explicit registry, not an
environment-provided import string. The built-in log adapter is no-network;
the production composition accepts an already-constructed typed adapter for a
reviewed deployment integration, and tests use an in-memory adapter.
Kill/certificate/lease/UNKNOWN/overdue failures
enqueue alerts without broker contact. Alert delivery remains available while
automation is killed.

The orchestration service receives an injected notifier that writes this
outbox. It is invoked for durable blocked/retry/reconciliation outcomes and for
an exception that prevents a tick from producing an outcome. The persistent
loop invokes alert dispatch independently on every control/heartbeat wake, even
when automation is disabled or killed; alert authority is deliberately not
trading authority.

## 7. Signed certificate trust model

The certification manifest is evidence, not authority. Authority is a canonical
`sentinel.paper_execution_certificate/1` envelope signed offline with Ed25519.
Runtime images contain only a code-reviewed public trust-root set keyed by
`key_id`; issuer private keys are supplied only to the offline command and are
never copied into images, PostgreSQL, certificate output, or logs.

The signature covers the canonical UTF-8 JSON bytes of the unsigned envelope
(`schema`, `algorithm`, `key_id`, and `claims`) with sorted keys, compact
separators, duplicate-key rejection, finite values only, and no unknown fields.
The full signed envelope must itself be canonical. Unknown schema, algorithm,
key, field, malformed base64, or noncanonical bytes refuse.

Claims bind:

- certificate id, issuance/not-before/expiry instants, `ALPACA_PAPER` scope,
  unattended-automation permission, allowed rollout modes;
- deployment, broker, account, and takeover epoch;
- exact commit, Sentinel and Wealth Core source hashes, runtime/test image
  digests, dependency-lock hashes, runtime identity, strategy and automation
  configuration identities;
- immutable certification corpus generation/hash, reference artifacts, Wealth
  Core result, controller result when allowed, production forward-chain result,
  resource-envelope result, and completed certification-manifest digest;
- zero strict xfails and all required verdicts, completion counters, and
  cross-evidence identities.

The operational corpus changes daily. A certificate therefore does **not** pin
one mutable daily `data_version`; it pins the immutable certification corpus and
the certified publication/data-contract implementation plus an approved
publication-chain policy/root. Each execution plan continues to bind its exact
current publication version and fingerprint, and runtime validation proves that
publication belongs to that approved chain. This distinction avoids either a
daily private-key ceremony or silently dropping daily plan currency.

The approved chain root is the canonical digest of the certification-time
publication row, including its version, predecessor, run id, window, and
evidence. Its version must exactly equal the immutable certification corpus
generation in the finalized base manifest and signed certificate; an arbitrary
earlier or later operational row cannot be selected as the root. Runtime scans
the durable publication chain, independently recomputes
row digests, requires exactly one row matching that signed root, and proves a
gap-free predecessor chain from that row through the currently pinned
publication. Copying the root string out of the certificate without this
database proof is not verification. The implementation digest is independently
computed over the source-matched publication, readiness, store, and catch-up
modules plus the versioned chain-policy description.

The offline issuer validates the complete manifest and every referenced evidence
artifact by digest and internal identity before signing. A manually asserted
`PASS` string is insufficient. Output publication is no-clobber, file- and
directory-fsynced, and atomic; failure leaves no authoritative final path. This
task may use ephemeral synthetic test keys, but must not issue a real activation
certificate or enroll a real private key.

Publication has an explicit rollback rule. Once a final file link or bundle
directory rename has become visible, any later temporary-file unlink, directory
open, directory fsync, or close failure changes the operation back to failed:
the producer removes the final path, retries transient cleanup, and best-effort
fsyncs the parent again before preserving the original exception. A caller may
therefore treat the final path's presence after a successful return as the only
publication result; an error is never allowed to leave a complete-looking
authoritative artifact behind.

The issuer consumes only a bundle produced by
`tools/sentinel_authority_evidence.py`; a hand-written schema-3 manifest is not
an issuance input. The producer starts from the exact finalized rehearsal
manifest and a canonical `sentinel.certification-test-run/1` record emitted by
the formal certification runner, the actual `wealth_core_expected_hashes.v1`
producer output and its formal baseline invocation record, the canonical
actual-invocation forward-chain record, target-host resource measurements, and the
durable certification-time publication row. It publishes a new, immutable
directory by no-clobber atomic rename. The directory contains the original
bytes, generated Wealth Core/controller decisions, the final execution-authority manifest, and an index
binding every byte. A failed or still-NO-GO decision produces a retained
`FINALIZED/BLOCKED` bundle; it never rounds missing evidence into PASS.

The Wealth Core/controller decision step is also a reviewed no-clobber
promotion, not a place to type `GO` or `PASS`. It requires the reviewer to
confirm one digest over the exact finalized manifest, formal test summary,
expected-hash output, baseline-replay export, reviewed forward-chain report,
and frozen reference bytes. The producer verifies the expected-hash tool and
canonical loader source digests, all seven replay hashes and corpus generation,
the zero-debt formal test result, and the full reviewed controller differential.
It then emits the only two decision schemas accepted by the bundle and issuer.
The repository's recorded Wealth Core `NO-GO` remains authoritative until those
real operational artifacts exist and pass; the command creates no shortcut to
issuance.

Here, “baseline-replay” means only the canonical
`sentinel.wealth-core-baseline-run/1` record emitted by
`python -m tools.wealth_core_baseline_run`. That one process retains the exact
finalized manifest and expected-hash bytes, submits the canonical request,
polls the exact accepted run UUID, binds the running engine image/source and
dependency closure, and atomically publishes the terminal row and invocation
log. A portable `sentinel.rehearsal_envelope/1` export—or any JSON assembled
from a row after the fact—is audit material, never authority evidence. Both the
decision producer and issuer rerun the formal validator and require its embedded
input bytes to equal the bundle's indexed manifest/expected-hash bytes.

Forward-chain review is its own no-clobber promotion, but its input is not an
operator-authored report. `scripts/sentinel_forward_run.py` owns the actual
broker-free Docker invocation of `tools.sentinel_forward_chain` in the exact
manifest-bound test image. It emits canonical
`sentinel.production-forward-chain-run/1` evidence only after a zero exit, empty
stderr, a complete 7,188-session read-only/repeatable-read production chain, all
5,032 reference sessions and 55,351 comparisons, and exact agreement with the
finalized manifest's commit, runtime/test images, source, publication, and
corpus identities. The record binds the producer and production-runner source
bytes, immutable argv, exact stdout/stderr bytes, and a re-derived completion
summary; it has no CLI that accepts a pre-existing JSON report. Publication is
atomic, no-clobber, fsynced, and rolled back if any post-publication durability
step fails.

The reviewer confirms the SHA-256 of that formal run, identity, ticket, time,
and the fact that the retained decoded report changed no runtime authority.
Promotion embeds both the formal-run and decoded-report digests and changes
`manual_review_required` only in the derived reviewed artifact. It cannot
modify or overwrite either source artifact. Resource evidence is scored from the
exact measurement-report bytes under a versioned policy: all required phases,
elapsed limits, enforced-limit headroom, OOM/restart state, host-pressure
disposition, and CPU-enforcement policy are explicit. Publication evidence is
generated from a read-only query of the current durable publication row and an
independently computed digest of the running publication-policy implementation.
Neither verdict accepts operator-authored PASS fields.

The bundle retains the pre-review resource-policy candidate as well as the
reviewed policy. The issuer independently checks that the embedded review names
the candidate's exact digest and then recomputes every resource-phase verdict
from the retained canonical report and sample bytes. A reviewed policy without
its candidate, or a hand-authored envelope that merely copies `PASS`, is not an
issuance input.

The test-run record binds the exact pre-suite manifest identity and bytes,
source-matched Git commit and runtime/test image RepoDigests, executed argv, and
the exact producer-source digest. It retains canonical Base64 encodings of the
collection log and pytest log so `summarize-tests` can independently decode and
re-derive the sorted collected-node inventory and all outcome counts, as well as
check the raw pytest-log digest. `summarize-tests` accepts only canonical record
bytes and cross-checks them with both the retained no-clobber
`manifest-frozen-<window>.json` bytes and the finalized base manifest; it never
parses an arbitrary text file.
`scripts/sentinel-certify.sh` emits this record itself as
`artifacts/sentinel/test-run-<window>.json` under
`sentinel.certification-test-run/1`; it emits no record for a nonzero exit,
skip, xpass, failure, or error, while strict xfails remain explicit counted
debt. Collection and execution both use the immutable test image with
`--network none`; the suite's throwaway PostgreSQL runs inside that container,
so no test requires external transport. The canonical argv stored in the record
includes that isolation flag, and evidence without it is refused. Text
containing `1 passed` is not certification evidence. Resource measurement
reports likewise use `sentinel.resource-measurement/1` and bind the exact
commit/runtime/test image, automation configuration, resource-policy digest,
host capability identity, phase command, samples digest, and exact repository
measurement-producer source digest. The measurement command publishes each
report by fsynced no-clobber link and rolls the authoritative name back after
any post-link failure; a same-second retry cannot replace an earlier report.
The scorer and issuer re-hash the installed producer, reject schema-less reports,
and recompute every identity instead of trusting PASS text.
All scored resource quantities are canonical integers: bytes, CPU tenths of a
percent, declared CPU millicores, and memory-headroom basis points. Floating
JSON values are refused, so formatting or binary-float differences cannot alter
the retained measurement identity between producer, scorer, and issuer.

The producer sequence is explicit and broker-free (paths are illustrative; all
outputs refuse overwrite):

`completed_checks` is not an operator score. The bundle producer owns a
versioned, source-defined list of twelve gate identifiers and emits its exact
length only after evaluating those gates. The CLI confirmation must equal that
derived value; another number is refused rather than copied into the manifest.

```text
python -m tools.sentinel_authority_evidence summarize-tests \
  --test-run artifacts/sentinel/test-run-<window>.json \
  --pre-suite-manifest artifacts/sentinel/manifest-frozen-<window>.json \
  --base-manifest artifacts/sentinel/manifest-<window>.json \
  --output artifacts/authority/test-summary.json
SENTINEL_DATABASE_URL=<read-only-certification-url> \
python scripts/sentinel_forward_run.py run \
  --manifest artifacts/sentinel/manifest-<window>.json \
  --network sentinel_default \
  --output artifacts/authority/forward-run.json
python -m tools.sentinel_authority_evidence promote-forward-chain \
  --formal-run artifacts/authority/forward-run.json \
  --confirm-sha256 <reviewed-formal-run-sha256> --reviewer <identity> \
  --ticket <ticket> --reviewed-at <UTC-second> \
  --output artifacts/authority/forward-reviewed.json
python -m tools.sentinel_authority_evidence promote-resource-policy \
  --candidate config/resource-policy-candidate.json \
  --confirm-sha256 <reviewed-candidate-sha256> --reviewer <identity> \
  --ticket <ticket> --reviewed-at <UTC-second> \
  --output artifacts/authority/resource-policy.json
python -m tools.sentinel_authority_evidence score-resources \
  --policy artifacts/authority/resource-policy.json \
  --measurement artifacts/envelope/<required-phase>.json ... \
  --output artifacts/authority/resource-envelope.json
python -m tools.wealth_core_baseline_run \
  --expected-hashes artifacts/wealth-core/expected-hashes.json \
  --manifest artifacts/sentinel/manifest-<window>.json \
  --bt-engine-url http://127.0.0.1:8031 \
  --output artifacts/wealth-core/baseline-replay.json
python -m tools.sentinel_authority_evidence decide-certification \
  --base-manifest artifacts/sentinel/manifest-<window>.json \
  --test-summary artifacts/authority/test-summary.json \
  --expected-hashes artifacts/wealth-core/expected-hashes.json \
  --baseline-run artifacts/wealth-core/baseline-replay.json \
  --forward-run artifacts/authority/forward-run.json \
  --forward-reviewed artifacts/authority/forward-reviewed.json \
  --reference-artifact <frozen-reference> \
  --confirm-inputs-sha256 <reviewed-combined-input-sha256> \
  --reviewer <identity> --ticket <ticket> --reviewed-at <UTC-second> \
  --output artifacts/authority/decisions
python -m tools.sentinel_authority_evidence publication-policy \
  --publication-row artifacts/authority/publication-row.json \
  --base-manifest artifacts/sentinel/manifest-<window>.json \
  --output artifacts/authority/publication-policy.json
python -m tools.sentinel_authority_evidence finalize-bundle \
  --base-manifest artifacts/sentinel/manifest-<window>.json \
  --pre-suite-manifest artifacts/sentinel/manifest-frozen-<window>.json \
  --test-run artifacts/sentinel/test-run-<window>.json \
  --test-summary artifacts/authority/test-summary.json \
  --expected-hashes artifacts/wealth-core/expected-hashes.json \
  --baseline-run artifacts/wealth-core/baseline-replay.json \
  --wealth-core artifacts/authority/decisions/wealth_core.json \
  --controller artifacts/authority/decisions/controller.json \
  --forward-run artifacts/authority/forward-run.json \
  --forward-reviewed artifacts/authority/forward-reviewed.json \
  --resource-policy-candidate config/resource-policy-candidate.json \
  --resource-policy artifacts/authority/resource-policy.json \
  --resource-evidence artifacts/authority/resource-envelope.json \
  --publication-row artifacts/authority/publication-row.json \
  --publication-evidence artifacts/authority/publication-policy.json \
  --reference-artifact <frozen-reference> \
  --reference-checksums <frozen-checksums> \
  --automation-config artifacts/authority/automation-config.json \
  --execution-config-sha256 <independently-computed-sha256> \
  --completed-checks <count> --output artifacts/authority/bundle-<id>
```

While the repository's Wealth Core record remains `NO-GO` and the strict
expected-hash xfails remain, the final command must deterministically emit a
`FINALIZED/BLOCKED` bundle. The issuer then refuses that bundle before loading a
private key. No operator may edit the generated manifest to change this result.

Three artifact facts are independently observed again at certificate install
and every runtime authority check: the Git commit, runtime image digest, and
test image digest. They come from explicit deployment configuration, not from
the signed claims. Missing, malformed, or differing facts refuse. The reviewed
ordinary runtime is then wrapped by `Dockerfile.sentinel-authorized`, which
adds a fixed baked marker and therefore has its own immutable digest. Only that
authorized image is selected by the automation and authorized-CLI services as
`<repository>@${SENTINEL_RUNTIME_IMAGE_DIGEST}`. They also set one exact intent
flag. The application requires both the baked marker and the flag for every
broker/admin/authority-enabling command, before reading configuration or
opening the database.

`Dockerfile.sentinel-test` is built FROM this exact marker-bearing authorized
image. It adds only certification tooling and receives neither Alpaca
credentials nor the authorized intent flag. Consequently its `/app` imports are
the deployed runtime bytes, but even a test accidentally reaching a broker
command fails before broker construction. Building the test lens from the
ordinary sibling image is refused because that could leave the deployed wrapper
untested while still producing a green suite and formal forward-chain.

The base `sentinel:latest` service has neither the marker, the intent flag,
Alpaca credentials, nor configured artifact identities. Copying claim values
or the flag into that environment is therefore insufficient. A host
administrator who can replace an image or bind arbitrary files into a container
already controls the deployment and database and is outside this application
membrane; no supported Compose command supplies that bypass.

The authorized CLI receives reviewed offline inputs only through one explicit
read-only bind mount. Before invoking its wrapper, the operator sets
`SENTINEL_AUTHORITY_ARTIFACTS_DIR` to an existing, dedicated host directory
containing the reviewed certificate/evidence files. The wrapper resolves that
directory and Compose mounts only it at `/var/lib/sentinel-authority:ro`;
certificate arguments therefore use, for example,
`--certificate /var/lib/sentinel-authority/certificate.json`. A host pathname
passed directly to the container is invalid, and neither the repository nor an
operator home directory is mounted as a convenience fallback.

Installation verifies the signature and all current immutable/account claims
before one atomic transaction stores exact bytes and appends an install event.
Runtime re-verifies exact durable bytes, signature, time window, root status,
revocation, binding/account, environment, rollout, configuration, publication
chain, and evidence identities before broker reads and before every mutation.
Certificate and key revocation are durable and take effect immediately. Rotation
adds a reviewed public root; overlapping validity permits planned replacement,
unknown/retired keys refuse new installs, and revoked keys refuse existing rows.
Rollback to an older valid-looking certificate is prevented by monotonic install
generation and explicit supersession history.

Signed-certificate activation is the only route into `CONTROLLER`. That
activation requires the explicit `--confirm-controller-rollout`
acknowledgement. Activating or rotating a certificate whose target is
`PINNED_1_00` requires the separate
`--confirm-pinned-rollout-may-increase-exposure` acknowledgement, because
pinned one can increase exposure from a defensive controller state. The generic
rollout command may explicitly hold or return to `PINNED_1_00` as fail-closed
emergency intent, invalidating the prior plan/certificate binding; it can never
enter `CONTROLLER` and directs the operator to stage and activate a signed
certificate instead.

## 8. Service, panel, and deployment

`docker-compose.sentinel-automation.yml` adds two profile-gated, immutable-image
surfaces only when explicitly merged with the ordinary Compose file. Both use
the distinct marker-bearing image built by `Dockerfile.sentinel-authorized`.
The
`sentinel-automation` service uses the exact digest-qualified, source-matched
Sentinel image, no ports, bounded CPU/memory, database dependency,
`restart: unless-stopped`, and a SELECT-only health command. Health is green
while correctly disabled or killed so supervisors do not turn policy into a
restart loop. Operational readiness is a separate durable panel fact. Starting
the service while disabled must not construct a broker.

The run-once `sentinel-authorized-cli` service selects the same digest-qualified
authorized image and is the only Compose service permitted for signed
certificate installation/activation and any manual command that can construct
a broker. The ordinary service's command parser refuses those commands even if
someone copies the overlay's environment strings.
`scripts/sentinel-authorized-cli.sh <sentinel-command> ...` validates all three
artifact facts and invokes that service directly; it cannot be redirected to
the mutable development service. `scripts/sentinel-automation-compose.sh`
validates the same facts for automation lifecycle commands. The ordinary
`docker-compose.sentinel.yml` remains resolvable without them for read-only
development CLI, panel, backup, feed, and certification work, but exporting
claim values to that service never authorizes broker access.

The overlay passes the complete `AutomationConfig` environment to both the
run-once lifecycle CLI and persistent worker: publication/execution delays,
lease/heartbeat/control-poll intervals, retry bounds, and alert claim/attempt
bounds. Their canonical fingerprint is therefore identical at certificate
install, activation, and runtime. A changed value does not inherit authority:
the worker durably bumps the control generation, engages the kill switch,
clears the cached authority verdict, invalidates the lease, and requires an
explicit reviewed activation/release under the new fingerprint.

The operator surface is intentionally verbose:

```text
sentinel automation-status
sentinel activate-paper-automation \
  --confirm-paper-account <id> --confirm-deployment-id <id> \
  --confirm-certificate-sha256 <sha256> --actor <name> --reason <ticket> \
  --confirm-old-writer-fenced \
  --confirm-enable-unattended-alpaca-paper-automation
sentinel release-paper-automation-kill-switch \
  --confirm-paper-account <id> --confirm-deployment-id <id> \
  --confirm-certificate-sha256 <sha256> --actor <name> --reason <ticket> \
  --confirm-release-unattended-paper-kill-switch
sentinel engage-paper-automation-kill-switch --actor <name> --reason <why>
sentinel deactivate-paper-automation --actor <name> --reason <why>
sentinel acknowledge-paper-alert --alert-id <id> --actor <name> \
  --acknowledgement <text>
sentinel automation-health
sentinel automation-run
```

Activation verifies the active signed certificate's `AUTOMATION` operation,
unattended claim, exact binding/rollout/config, runtime identity, publication
policy, and chain before writing control. It leaves the kill switch engaged.
Release repeats those checks and exact confirmations before making the service
operational. Deactivation and kill engagement remain available without
certificate authority because removing authority must not depend on the thing
being removed. None of these commands constructs a broker; only an enabled,
unkilled, fenced cycle does so after its fresh checks.

The panel remains SELECT-only and shows installed/enabled/killed state, leader
holder/fence/heartbeat/expiry, certificate verdict, last and next cycle, last
successful reconciliation, current failure, and pending/dead-letter/
unacknowledged alerts. It reads the service's durable authority verdict rather
than contacting Alpaca or manufacturing a new verdict. A cached PASS is green
only while it is still bound to the currently active certificate and the
durable lifecycle says that certificate is active, unrevoked, and inside its
validity window at database time. Revocation, expiry, a missing lifecycle, or a
certificate mismatch overrides the cached PASS and renders failure.

## 9. Required adversarial evidence

Tests use deterministic clocks, ephemeral PostgreSQL, and `SimulatedBroker`:

- holiday, DST, half-day, missed wake, and post-close refusal;
- concurrent leader acquisition, heartbeat, expiry/takeover, stale fence, and
  writer-lock collision;
- disabled/killed/uncertified/wrong-account/live-URL/DB-outage zero-call paths;
- kill or revocation between reconciliation and each mutation;
- restart around plan adoption, `SEND_PENDING`, accepted timeout, partial fill,
  settlement, cycle commit, alert claim, and delivery result;
- UNKNOWN/key reuse, reductions-before-increases, superseded plans, and
  historical state-only catch-up;
- duplicate outbox insert/delivery, expired claim, backoff, dead letter, ack;
- signature tamper, wrong/unknown/retired key, malformed/noncanonical envelope,
  expiry/not-yet-valid, revoked cert/key, account/environment/image/config/
  corpus/evidence mismatch, rollback, restart, and rotation;
- Compose/resource/health truth and a source inspection proving automation
  cannot import migration.

These are software proofs only. NAS resource measurement, full-corpus formal
certification, independent-target restore drill, real paper-account rehearsal,
real root enrollment, certificate issuance, activation, and kill release remain
later operational actions.
