# Bounded operation and explicit ownership

Decision: implement the architecture review against installed local PAPER
predecessor `b2e308bb664718da373175f1a7d988d07b159ae2`. This is an operational
architecture change, not a new strategy, account, market-data policy or order
policy. Delivery remains the owner-authorized local feature branch. Backups,
archives, restore work and backup verification remain suspended. The backtest
is outside this change. No live endpoint or live-money authority is introduced.

The broker-free alert sender retains the publication receipt authentication key
to verify durable observation coverage during its independent health check.
That key does not grant broker access; Alpaca credentials remain absent from
the sender, and push signing credentials remain absent from the collector.

## Boundaries and identities

Preserve one canonical Wealth Core transition and book, one exposure controller,
one serialized financial writer and one execution membrane. Broker outcomes
never enter strategy/controller inputs. Keep durable command identity, explicit
UNKNOWN outcomes, positive reconciliation, whole-share ownership, protected DAY
BUYs with the selected 100-basis-point maximum and all final financial guards.

Separate three claims: the exact executable source/image; economic semantics;
and authenticated published data. A strategy admission receipt binds the latter
two without making acquisition job ownership an economic rule. Existing source,
book, plan and publication identities remain immutable. Initial extraction uses
an exact independently checked predecessor-to-candidate witness, not wildcard
source acceptance. Unknown economic edits change/refuse economic identity. A
future operational-only edit still needs actual runtime admission and cannot
inherit financial authority from an economic identifier.

A new DATA_ONLY strategy receipt requires the caller's original live publication
pin, exact publication identity, connection and backend. Check that strict scope
before assessment and immediately before inserting the receipt. The optional
readiness reuse scope remains optional for independent read-only verification;
its absence never authorizes writing a strategy admission. Losing the pin during
assessment refuses rather than letting a storage reader reacquire it silently.
This current-only receipt writer also requires the supplied strategy identity
to equal the currently selected production strategy before assessment and again
immediately before insertion. Its data checks cannot pre-admit an arbitrary
future strategy by sealing a caller-supplied identity. A selection change during
assessment refuses without a receipt; authentic historical receipts remain
independently readable for their original exact identity.

Move pure current-window contracts/transforms and formation input calculations
out of database/runtime modules. Production and qualification import the same
implementation. State explicit caller-owned transaction APIs separately from
connection-owning validation/migration APIs; a connection-owning routine refuses
an already active caller transaction before it can commit or roll it back.

The economic manifest names pure contracts separately from conservative input
compilers. Pure contracts include the canonical kernel/session, controller
calculations, current-window material, provider price conversions, formation
input identities and warmup calculations. Input compilers still bind the exact
source-selection and normalization adapters; their source is not described as
pure. Storage layout, data-admission receipts, publication orchestration,
shadow observation/runtime, daily/checkpoint/recovery orchestration and
formation authority/persistence are runtime contracts. Their complete actual
bytes remain mandatory runtime inputs, while authenticated published material
binds the concrete economic data they deliver. Their scheduling or diagnostics
cannot by themselves invent a new strategy. The initial manifest is authenticated
against the exact predecessor source catalog and extracted function witnesses;
changed economic bytes produce a new actual identity and changed declared
dependency edges refuse. Tests exercise the actual candidate without historical
hash substitution.

Dependency admission is closed: every Sentinel import edge of an economic
contract/compiler must name either another authenticated economic contributor
or an explicitly reviewed operational port. Permanent identity lineage,
Alpaca identity/metadata interpretation and cached formation feature formulas
are economic contributors. SQL read routing and view column/price-domain
mapping live in a pure read-contract module and are economic contributors;
publication visibility and SEP retirement SQL predicates are also authenticated
input compilers because they select the rows exposed by a fixed publication.
The existing mixed publication implementation remains conservatively pinned
for its canonical split-repair SQL. Catalog validation, physical block lifecycle
and transaction ownership remain
operational ports. Imported operational ports may supply authenticated data,
storage, exceptions or lifecycle guards; they do not supply untracked economic
calculations. Relative imports resolve against the declaring module. Dynamic
import expressions in this closed economic source graph refuse. Qualification
mutates the concrete lineage, cached-feature, identity and query-domain
contributors as well as unknown relative/dynamic edges.
The finite per-module classification is recorded in
[economic-dependencies-20261023.md](economic-dependencies-20261023.md).

Python package initializers are executable dependencies, including when a
submodule import does not spell them. The closed graph therefore authenticates
every existing ancestor package of an economic contributor and every declared
local import. Resolve these package files against the actual imported package
tree on each call, outside the syntax cache. Initializer bytes are conservative
input compilers, even where their current body is only documentation or
re-exports. In particular, `sentinel.feed.__init__` installs the canonical
publication-visibility predicates; pinning only the predicate functions would
miss removal of that existing installation hook. All initial initializer pins
must equal the independent `b2e308bb` source bytes. Their operational imports
retain finite reviewed port roles, and the complete Wealth Core tree remains
independently authenticated by the strategy's Wealth Core source identity.
Changing an initializer changes the economic identity; an added local package
or import edge refuses the old closed declaration. This conservative boundary
retains some package-level operational coupling instead of accepting an
untracked semantic installation path.

For `from package import name`, a missing child file is an attribute import
only when the package initializer explicitly declares that binding. Unknown
names retain their full unresolved child edge and therefore refuse the closed
manifest; they cannot collapse to an already-authenticated parent edge. Bound
names are syntax facts from the current exact initializer bytes, not a cached
admission verdict or Python attribute lookup with side effects.

Optional normalized storage is available only after the exact extension
catalog/installed-marker check. Complete loss after installation is a refusal,
never a switch back to legacy tables. Reads validate at their explicit API
boundary; no availability result is cached across financial operations.
Economic dependency parsing may reuse only immutable syntax facts keyed by
the exact module name and source bytes, bounded to 128 entries. Every call still
reads/hashes source bytes and resolves declared paths/edges afresh. Identity,
classification, source availability and admission verdicts are never cached.

## Incremental execution evidence

Install explicit database mutation tracking for observations, provenance and
canonical observation witnesses. A durable change sequence identifies affected
evidence; destructive/reset operations cannot erase their own evidence. Exact
account binding, schema/trigger contract, tracking incarnation and sequence
boundary bind an authenticated coverage record. Missing/recreated tracking
state, malformed coverage, unscopable changes and sequence gaps refuse.

Bootstrap old evidence with an explicit paged, resumable verification operation.
Routine producers validate exact changed records and advance only a complete,
contiguous mutation prefix under ownership. Routine health reads coverage and
current head; it never repairs, bootstraps or rereads the lifetime journal.
Updates/deletions inside a verified prefix invalidate/revisit that evidence.
Preserve the independent full-history validation API and corruption falsifiers.
Fresh account/source/clock/authority checks still occur at submission.

Preserve every historical informational-mirror stamp and result. An indexed
dependency projection binds a plan to exact securities and its action interval.
Action-domain publication changes enqueue affected plans; unknown changes require
a bounded rescan. Publication progress with no relevant change does not create
another complete plan-by-publication matrix. Replace the 370-record lifetime
cliff only after complete authenticated migration coverage; retain bounded batch
limits and explicit pending/refused states. Historical mismatches remain visible.

## Independently verified operational reads

A broker-free verifier role in the same immutable image owns the existing
separate shadow and PAPER verification operations. Persist positive and negative
results as versioned authenticated receipts, each bound to its exact current
subject key, original observation time and finite expiry. Shadow invalidation
must exclude broker-owned evidence; PAPER invalidation includes its own exact
account/control/command dependencies. Heartbeats cannot renew a proof.

The panel consumes these records and cheap current revision keys. It cannot start
an expensive financial observer. Missing, stale, changed-subject and malformed
receipts withdraw current styling; retained values remain explicitly historical.
Typed alignment/readiness facts govern severity, never substrings of display
copy. HTML, JSON and notifications project the same typed facts. A panel restart
may reuse a still-valid exact-subject proof but cannot extend its lifetime.

## Notification ownership

A bounded GET-only execution collector owns account/fill collection and enqueues
the existing durable notification receipts/outbox records. A separate sender
owns delivery, needs no broker credentials and does not wait for provider I/O.
Both are roles of the same image and use the same PostgreSQL database. Critical
alerts have bounded priority with fairness; per-incident ordering, idempotency,
original event times, subscription history and delivered-recipient recovery
bindings remain intact. Notification fill receipts confer no financial authority.

## Controlled application handoff

A finite authenticated drain request binds the exact supervisor incarnation and
runtime. Admission and drain acknowledgement share an ownership boundary: after
accepting a drain, the supervisor starts no new worker, lets admitted work finish
naturally and acknowledges quiescence. A new incarnation cannot reuse that ack.
Expiry or identity drift refuses handoff. Drain is not a kill-switch release,
trading-window extension or a way to resolve UNKNOWN commands.

Installation requires this acknowledgement before stopping applications. The
first transition from a predecessor without drain support needs an explicit,
qualified compatibility handoff; a sampled IDLE check alone is not a durable
acknowledgement. Preserve PostgreSQL identity and every existing financial row.

The one-time `b2e308bb` bridge stops admission at a kernel process boundary.
An exact-image helper identifies the sole single-thread supervisor by PID and
start ticks, sends SIGSTOP only to that supervisor and observes the stopped
state. It then proves no worker or live descendant, no pending/critical work
and a fresh authenticated same-incarnation IDLE state. A busy observation
resumes the unchanged supervisor and refuses; no worker is signalled. After a
successful proof it durably writes an authenticated, finite operation-bound
barrier acknowledgement and sends SIGKILL directly to the still-stopped idle
supervisor. It never resumes admission between proof and termination. The host
must verify both the exact acknowledgement and the stopped exact container;
an expected exec disconnect alone is not completion. An interrupted barrier
can finish only against the same stopped PID/start ticks and acknowledgement.
Qualify this bridge in isolated processes, including admission-race falsifiers,
before using it. Successors use cooperative drain, not this compatibility path.

Before the legacy bridge, record the exact shadow container restart policy and
temporarily set that application's restart policy to `no`. Otherwise Docker
could restart admission after the fatal stop. A pre-barrier refusal restores
only the recorded unchanged predecessor policy. After a held barrier, keep
restart disabled until exact successor Compose replacement installs its reviewed
policy. Bind the hold to operation/container identity and retain it through
interruption; PostgreSQL and other workloads are outside this policy change.

## Normalized storage sharing

Retain the logical SnapshotManifest and snapshot identity. Add an immutable
physical layout manifest binding candidate/snapshot to ordered content-addressed
session partitions. Each block digest includes its row schema, normalization,
calendar and exact ordered content. Verify complete content before reuse.
Never presume overlapping sessions are unchanged: actions, restatements,
metadata and normalization can change them. Raw-source observation authority
remains distinct even when physical bytes can be shared.

New production writers should finish bounded session blocks without accumulating
another complete persistent window. Legacy candidates remain readable through
the single owner read interface. Reference creation and sealing stay atomic under
current leases/pins. Retirement can release only unreferenced blocks, with SQL
reference guards; no historical generation or financial provenance is rewritten.

## Migration and delivery

Feature schema installation is an explicit, bounded, quiescent application
migration; runtime reads never create/repair schema or coverage. Validate exact
recognized predecessor catalogs and exact new extension definitions. Do not
silently ignore additional triggers, missing relations or changed functions.
Candidate read-only preflight must remain possible against the predecessor
schema; new optional projections may fall back to the original independent
verification until explicitly installed, without claiming new coverage.

The operational DDL epoch is installed last, in the same transaction that then
creates the central immutable guard and authenticated installation marker. Its
persisting public relation therefore prevents runtime from treating a missing
marker as a never-installed predecessor, even if all central guard objects were
also removed. Such loss refuses a fresh proof and explicit reinstallation; it
does not reconstruct authority. Individual component installs before the epoch
remain available to isolated qualification fixtures. Privileged simultaneous
erasure of the epoch, marker and every guard is outside the supported database
writer contract.

The delivery command must understand reviewed additive schema and same-image
role/Compose additions, bind their exact qualified bytes, and retain resumable
stage evidence. PostgreSQL is not restarted/recreated; no volume reset, source
history rewrite, backup or restore gate is part of this operation. Shared state
and historical rows are compared before/after migration. Any refused stage
preserves evidence and remains diagnosable.

## Qualification and future live operation

Current operational qualification is an explicit composed workflow: source
publication, canonical transition, saved intent, preparation, submission,
reconciliation, notification and dashboard. Exercise it with isolated real
PostgreSQL and the production components, substituting only external providers
and the paper transport. Cover interruption before/after durable boundaries,
duplicate delivery, changed identities, old-row corruption/deletion, tracking
loss, stale proofs, drain races and repeated continuation. New guards require
falsifiers that fail when each guard is broken. Preserve historical economic
oracles; do not repin them to pass an operational change.

Migrate legacy fixtures in explicit families to real current contracts. Keep
the legacy registry finite and shrinking; a legacy unit pass is not composed
current-operation evidence. Retain exact source, commands, counts and logs for
all qualification. Validate the exact image and existing canonical book before
local application activation.

These boundaries prepare for a separately authorized real-money operating
profile: explicit authority, least-privilege roles, deterministic migrations,
finite evidence and recoverable handoffs. This delivery remains PAPER only.
Operational qualification does not confer investment-performance certification
or live-trading permission; suspended reliability controls are not represented
as having been tested or enabled.


## Detecting privileged source-guard bypass

Incremental coverage also binds a durable DDL epoch installed after the other
extensions. An independent PostgreSQL event trigger advances that epoch for
source-table, trigger and function definition changes. Disabling a source
trigger, editing historical evidence, and enabling that trigger again therefore
invalidates the old authenticated prefix even when the final catalog looks
unchanged. Runtime checks validate the event-trigger definition as well as the
source tracking definitions. Requalification is explicit and bounded; ordinary
reads never reseal changed evidence.

This detects source-guard bypass by a privileged maintenance connection. A
superuser deliberately disabling both the independent DDL audit and all source
guards, or replacing the entire database, is outside the supported writer
contract. Future live deployment needs separate least-privilege operational,
migration and database-administration roles; this PAPER change does not claim
protection against an arbitrary hostile database superuser.

### Exact operational proof invalidation

Shadow and PAPER revisions bind every former independent-observer key
dependency. PAPER additionally binds cycle-event adoption history and recorded
broker-account evidence used to classify a retired cycle. Control revisions
compare enabled/kill/generation, full account and rollout/config/certificate
bindings, authority verdict/detail and activation/deactivation times; only the
authority check timestamp and generic update timestamp are polling annotations.
Cycle revisions compare all persisted semantic columns, including plan/source
fingerprints, account/generation/certificate bindings, session and execution
clocks, failure/diagnostic state, attempt count and completion; only next-wake,
last-fence and generic update stamps are excluded. Certificate lifecycle compares
its certificate key and status. These additions close predicate dependencies
that the earlier in-memory key omitted, while ordinary heartbeat polling cannot
continually invalidate a finite proof. The independent DDL epoch binds each
subject so disable/edit/enable cannot restore an old positive receipt.

Unchanged native account polling is not a new financial-proof subject. A
BEFORE INSERT account trigger compares the indexed preceding latest account
record's complete meaningful row, excluding only sequence and observation time.
It still invalidates on any semantic change, backward/older observation, New
York observation-date boundary or observation gap over ten minutes. UPDATE,
DELETE and TRUNCATE always invalidate. The BEFORE timing also covers a bulk
insert without allowing its rows to compare only against each other.
Historical account rows remain append-only. A retired-cycle display eligibility
is typed and carries the original account observation's ten-minute expiry,
tightened by any native reservation's session close. That deadline survives the
PAPER row/receipt codec and consumer restart; unchanged polling cannot extend a
cached proof's clocks. Freshness recovery after an actual stale gap changes the
subject and requires a new independent proof.

The retired display uses the explicit typed `PRIOR_CYCLE_FAILED` alignment:
amber only while its original finite eligibility deadline is current, red when
that deadline is missing/expired or its fact clock is future-dated. This is
historical display eligibility, not automatic recovery or scheduled readiness.
The headline's scheduled-ready exception remains exclusive to `SCHEDULED`;
other WARN classification is unchanged.

A read-proof subject also binds the physical PostgreSQL system identifier,
current database name and authenticated central installation ID when installed.
A copied receipt cannot cross a database replacement at the same connection URL.
During verifier shutdown, stop creating requests and retain the session owner
until every already-admitted Reader job has finished its original bounded
queue/work/reap path. Waiting for those existing deadlines does not renew them;
release ownership only after the jobs are drained.


## Borrowed read-only schema validation

The established runtime schema validators are also called inside existing paper
operations after read-only authority/binding queries. They validate in an owned
read-only transaction when idle and in a force-rolled-back nested savepoint when
the caller already owns a transaction. Their local settings and locks end with
the proof; caller data and transaction ownership survive success and refusal.
An unconditional rollback or a blanket idle precondition would discard work or
refuse legitimate composed paper calls. Explicit migrations and the bounded
connection-owning evidence-advance operation still require an idle connection.

Canonical rolling status and compact guard status prove the committed book.
When their caller is idle they own its repeatable-read, read-only proof
transaction and return it idle. When borrowing an already active caller,
they open a separate proof connection using the existing exact-target,
password-preserving connection factory. Only that connection is rolled back
and closed. Uncommitted caller changes never become canonical status authority,
and successful or refused status does not end caller work or change its local
settings. Capture and check the original publication-pin token before and
after the proof in rollback-only owned transactions, or nested savepoints when
the caller already has work. Record the caller's original transaction status
before capture. Even an idle connection borrowing another backend's active
session pin, or owning its own session pin while idle, returns idle; token
checks retain the original session/transaction pins and never roll back caller
work. Compact structural reuse still checks the original callback
owner's publication and writer locks through the proof backend. PAPER continues
to compare the returned committed state/publication with its pinned plan
inputs; no proof can release or reacquire the caller's pin silently. Dispatch
SELECTs and ordinary authority reads therefore cannot depend on a schema
validator discarding their transaction as an undocumented side effect.

The shared public owner is `sentinel.committed_read.proof_connection`.
Rolling initialization resume, daily resume, canonical runtime status and
historical panel source-wait evidence all use this same boundary. Resuming a
committed book or reading historical display evidence never commits a caller's
transaction, and none of these reusable readers rolls it back on refusal.
The source-wait reader keeps its original historical session/attestation clocks
and still grants no current GO. Read-only service probes which create their own
fresh connection already have an explicit owner and retain that behavior.
