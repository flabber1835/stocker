# f92c0cc safety reconstruction

Status: accepted implementation contract for the post-merge review of
`f92c0cc902a3121cbe37519bc1b2cba6f385ab5f`.

This record turns the confirmed review findings into one bounded reconstruction.
It does not change the repository's paper-only or Wealth Core `NO-GO` status.
Those gates remain authoritative until their existing certification evidence is
complete.

## 1. Callback authority and deadlines

An automation callback is an asynchronous application boundary. Production
automation accepts asynchronous callbacks only; a synchronous callback cannot
promise a hard deadline because Python cannot safely terminate an arbitrary
in-process thread. Test and administrative code that needs synchronous work must
wrap it in a separately supervised, killable process before exposing an async
callback.

Each callback receives one immutable `CycleContext` containing its cycle,
leader permit, and a cancellation authority. The service races the callback
against the fingerprinted callback deadline. On deadline, lease loss, heartbeat
failure, or operator cancellation it invalidates that authority before
cancelling the task. The service does not wait indefinitely for a callback that
suppresses cancellation.

Every durable callback side effect must call the context authority immediately
before the effect. Broker mutations keep their existing database-backed
generation fence. Database and evidence writes use the same authority check.
A late callback may finish local computation, but cannot obtain authority for a
broker request or durable write after cancellation or leadership transfer.

## 2. Table-owned automation policy

Automation phase policy is data, not a repeated exception branch. The phase
table declares the callback, retry budget, retry state, and terminal state for
`REFRESH`, `PREFLIGHT_RECOVER`, `PREPARE`, `EXECUTE`, and `RECOVER`.

Expected callback failure classes are:

* `TransientInfrastructureFailure`: bounded retry according to the phase budget.
* `PermanentOperationalRefusal`: durable `BLOCKED` state.
* `DataIntegrityFailure`: durable `BLOCKED` state.
* `LeadershipLost`: immediate stale-leader exit; no state write by the stale
  holder.
* `HumanInterventionRequired`: durable `BLOCKED` state.
* `SoftwareDefect`: durable `BLOCKED` state with a stable exception fingerprint.

Unknown exceptions are `SoftwareDefect` by default. They never become a generic
transient outage. Each retry record retains phase, attempt count, first failure,
latest failure, next retry, class, and fingerprint. Exhausting a phase budget
transitions to `BLOCKED` and retains the same evidence.

Expected business refusals remain explicit result values. Exceptions are
reserved for the typed failures above and unexpected defects.

## 3. Transaction-owned broker evidence

One broker observation is one database transaction. The normalized observation,
position and order provenance, raw evidence, and canonical serialized evidence
are written by repositories that do not commit. An execution-journal
`UnitOfWork` owns the connection commit or rollback.

No observation row is externally valid without its serialized evidence row.
The integrity query reports historical rows missing either provenance or
serialized evidence as `UNCERTIFIABLE`. It may reconstruct only when all source
fields needed to produce byte-identical canonical evidence remain available.

## 4. Fail-closed calendar recovery

The restore DAY-order fence distinguishes a known non-session from inability to
evaluate the calendar. A known non-session remains non-executable at the paper
gateway. Calendar construction, horizon, timezone, malformed schedule, and
dependency failures return a blocking reason. Diagnostic evidence names the
exception class, requested session, calendar identity, and recovery generation
when available.

## 5. Certified runtime context and deterministic PIT time

Domain code receives an immutable runtime context containing the decision
session, observation ceiling, certified clock, runtime generation, source commit
and image identity, corpus/publication identity, broker account identity,
execution mode, transaction owner, logger, and evidence sink. Callers may use a
narrow projection when a boundary needs fewer fields.

PIT reconciliation requires an absolute observation ceiling. A CLI may derive
that date from an injected certified clock, then must print and persist it.
PIT domain modules may not call `date.today`, `datetime.now`, or an unscoped
clock.

## 6. Broker capabilities and compatibility removal

Composition validates runtime-checkable capabilities rather than concrete
broker classes. The capability graph covers cash observation, submission,
status resolution, open-order observation, broker clock, generation fencing,
recovery, and evidence production. Adapter certification remains explicit and
is recorded in runtime identity evidence; structural capability does not by
itself grant production certification.

CLI and paper compatibility behavior lives in explicit legacy adapters. Normal
entry points call canonical owners through immutable dependency objects. No
production entry point copies values into another module's globals or resolves
private dependencies through `sys.modules`. Architecture tests reject new
consumers while the dated legacy removal remains visible.

## 7. Wealth Core contracts and replay complexity

`SecurityBar.closes` includes missing source observations and therefore has the
type `Sequence[float | None]`. Signal boundaries explicitly handle optional
prices. Valuation marks, source observations, eligibility, and terminal states
remain separate concepts.

The feed keeps an explicit last-session value. Duplicate detection may retain
the session map, but monotonicity checking is constant time and never scans all
prior sessions.

## 8. Validation and promotion

The complete safety workflow runs for pull requests and every push to `main`.
Deployment and promotion consume only the exact tested commit and image digest.
The recorded evidence includes commit SHA, source-tree hash, workflow run ID,
dependency lock hash, image digest, test-manifest hash, and schema/semantic
epochs.

Risk-weighted coverage gates apply to safety predicates, transaction boundaries,
authority decisions, state transitions, and exception classification. The
reconstruction adds branch coverage, strict typing of changed public boundaries,
mutation checks for fail-open/fail-closed predicates, property/state-model
tests, and fault injection at callback, lease, broker, and commit boundaries.
