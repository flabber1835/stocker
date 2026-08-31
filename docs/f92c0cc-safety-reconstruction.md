# f92c0cc safety reconstruction

Status: accepted implementation contract for the post-merge review of
`f92c0cc902a3121cbe37519bc1b2cba6f385ab5f`.

This record turns the confirmed review findings into one bounded reconstruction.
It does not change the repository's paper-only or Wealth Core `NO-GO` status.
Those gates remain authoritative until their existing certification evidence is
complete.

## 1. Callback authority and deadlines

An automation callback is an asynchronous application boundary. Every production
callback runs in a separately supervised child process. Its async declaration is
an interface contract; synchronous PostgreSQL, vendor, filesystem, or CPU work
inside that coroutine cannot stall the parent deadline, heartbeat-failure, or
operator-cancellation loop. Deadline, heartbeat loss, lease loss, and caller
cancellation set a process-shared revocation event and immediately send
`SIGKILL`; there is no cooperative or `SIGTERM` grace interval.

The callback is the leader of a dedicated process group inside the automation
worker's dedicated session. Every callback-created descendant inherits that
group unless it deliberately creates another group; the external supervisor
therefore enumerates and kills every process group in the worker session. The
worker kills the callback group after every result, exception, authority loss,
heartbeat loss, or deadline. Cleanup includes a group whose leader has already
exited. Callback completion is not durable progression until that group is
empty. The worker registers the callback state before starting the child, and
the external deadline is anchored to that registration timestamp. Every safety
termination is immediate `SIGKILL` of the complete session.

Each child receives one immutable `CycleContext` containing its cycle and leader
permit. It returns only a canonical JSON callback result over a one-way IPC
channel. The parent races child completion against the fingerprinted deadline
and the independently threaded database heartbeat. Deadline, lease loss,
heartbeat failure, or operator cancellation kills the process. The child checks
the process-shared revocation event at every explicit side-effect fence while
the kernel kill is being delivered. Parent-owned durable phase transitions
revalidate the current database fence.

Broker mutations keep their database-backed generation fence. Heartbeat
connection creation, use, and close are one guarded iteration with connection
and statement timeouts below the lease duration. Cancellation is rechecked after
connection creation and immediately before renewal. A heartbeat worker that
cannot join is a terminal supervisor failure that exits the automation worker.

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
New normalized order rows retain every economic field required to reconstruct
the canonical payload, including symbol, average fill price, submission time,
external-replacement state, and native replacement identifiers. The observation
provenance record retains the multi-request start boundary and a SHA-256 digest
of that reconstructed payload in the same transaction.
Re-genesis observation evidence uses schema version 2 so the same start and
replacement facts remain load-bearing during handover.
The integrity query reconstructs canonical evidence from normalized observation
and provenance rows, compares every retained identity and economic field,
checks the processed-session date, and verifies both the expected and stored
payload against the independent digest. Historical rows missing any source
field, provenance, serialized evidence, or digest are `UNCERTIFIABLE`.

Every account-derived result carries typed account provenance. Observations,
snapshots, close valuations, fill intervals, cash evidence, and exact-key reads
are rejected unless their identity matches the signed grant and durable account
binding. An exact-key read brackets the lookup with account identity reads and
retains both identities in the finalized observation. Reconciliation records no
evidence and changes no command state when either bracket differs from the
initial observation or binding. Empty-account enrollment and administrative
inspection likewise compare each observation identity with its paired snapshot
and signed account before treating the book as empty or stable.

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
recovery, and evidence production. Trusted composition issues a sealed identity
bound to the exact adapter implementation and source hash, broker mode,
certified capability set, and conformance suite. Broker-owned diagnostic labels
grant no authority. Runtime evidence separately records available methods,
declared capability bits, and independently certified capabilities.

Wrapper certification is a closed registry of exact canonical classes and
wrapper-kind strings. Subclasses are ineligible. The issued identity binds the
exact inner adapter instance and the exact immutable grant/guard configuration;
the registry rechecks those object bindings and the composition digest at every
production use. Paper activation additionally requires Alpaca,
`ALPACA_PAPER`, the canonical wrapper kind, and the complete required capability
set.

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
