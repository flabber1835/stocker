# Sentinel — the execution and recovery contract

`docs/sentinel-paper-observation.md` defines the separate signed
`PAPER_OBSERVATION_ONLY` authority. It preserves this execution membrane and
all reconciliation/identity rules, cannot satisfy historical certification,
and adds only renewable short paper leases plus expiry-degraded exact-account
reconciliation/cancellation safety.

> **Status: DESIGN SETTLED, BUILT AND TESTED — against a simulator and an
> ephemeral PostgreSQL, never against a live broker.** This document is the
> source of truth for how Sentinel talks to a broker, what it persists before it
> does, and how it recovers when any of it goes wrong. It supersedes nothing in
> `sentinel-architecture.md`; it fills the layer that document leaves open below
> "execution projection".
>
> Read `docs/sentinel-deployment.md` first for operational ground truth, then
> `docs/sentinel-architecture.md` for the strategy/controller architecture, then
> this.

## Implementation status

```text
sentinel/execution/identity.py       derived client keys, takeover fencing
sentinel/execution/states.py         command state machine + permission kernel
sentinel/execution/contract.py       typed port, capabilities, completeness
sentinel/execution/commands.py       exact-delta sizing, dust, authorisation
sentinel/execution/recovery.py       send / resolve / confirm primitives
sentinel/execution/journal.py        durable journal + single-writer lock
sentinel/execution/reconcile.py      the ordered sequence, actions before blame
sentinel/execution/plan.py           immutable plans, economic fingerprint
sentinel/execution/projection.py     shadow x exposure -> whole shares
sentinel/execution/target_reprojection.py
                                      immutable action-aged execution target
sentinel/execution/executor.py       the session loop
sentinel/execution/simulator.py      the conformance ORACLE
sentinel/execution/alpaca.py         Alpaca mapped onto the contract
sentinel/execution/certification.py  which adapters are certified, and why not
sentinel/binding.py                  account binding + takeover epoch
sentinel/handover.py                 the administrative migration
sentinel/schema.py                   behavioural state DDL
sentinel/feed/publication.py         corpus versions + the visibility rule
sentinel/feed/repair.py              split-ratio audit and repair
sentinel/feed/staging.py             the chunk sort, in PostgreSQL
sentinel/feed/calendar.py            session freshness, not a day budget
sentinel/feed/readiness.py           the data contract + persisted verdicts
sentinel/core/catchup.py             convergence after absence, re-projection
sentinel/core/decision.py            canonical shadow/controller -> stamped plan
sentinel/paper.py                    read-only preparation + strict execution gate
sentinel/authority.py                signed certificate gate + rollout mode
sentinel/automation/                 disabled-by-default Stage 4 orchestration
sentinel/core/cashflow.py            external cash as a declared event
```

**NOT DONE, and none of it should be inferred from the green suite:**

```text
no live or paper broker has ever been contacted by this code
no migration or paper-plan execution has been run by the implementation work
the manual activation path remains operator-invoked; Stage 4 is installed only
    through its profile and starts disabled with its kill switch engaged
the RECONSTRUCTION tier of corpus versioning is deferred
crash injection is LOGICAL (state, journal, stale restore), not SIGKILL
the resource limits are declared and ENFORCED (every service carries
    mem_limit and cpus, asserted by test) but not yet MEASURED against a real
    run — that needs a Docker daemon on the NAS and cannot be done in CI
spinoffs, mergers, renames and other non-scalar book changes are NOT fabricated
    from incomplete Sharadar terms. A relevant event is detected and fences
    execution until authoritative broker-visible economics exist; only scalar
    split/reverse-split/share-dividend reprojection is implemented
Alpaca fills key on broker-native activity ids. Trade corrections/busts are not
    yet applied as reversal economics and remain part of the separate live-money
    promotion gate; the paper trial never invents them
```

The architecture document settles what Sentinel *decides*. This one settles what
happens between a decision and a share moving, and — more importantly — what
happens when that process is interrupted, duplicated, or resumed from a backup
that is behind the broker.

---

### The rehearsal manifest is evidence, not execution authority

A manifest whose lifecycle is `FINALIZED` and whose verdict is `PASS` is still
not, by itself, permission to submit an order. In particular, that shape can
coexist with strict expected-hash xfails or a Wealth Core `NO-GO`. Turning those
two generic strings directly into a runtime gate would convert known
certification debt into broker authority.

Paper execution therefore requires a separately issued and cryptographically
authenticated activation profile in the manifest. The profile names:

```text
schema                         sentinel.paper_execution_authority/1
status                         AUTHORIZED
scope                          ALPACA_PAPER
strict_xfails                  exactly 0
wealth_core_certification      GO
allowed_rollout_modes          PINNED_1_00 and/or CONTROLLER
controller_certification       PASS when CONTROLLER is allowed
runtime_identity_hash          exact certified environment/source identity
strategy_identity              strategy id + controller rule + Wealth Core hash
```

An operator-supplied SHA-256 authenticates bytes, not the party that asserted
`PASS`, `GO`, or `AUTHORIZED` inside them. Shape, completion, and runtime-hash
validation therefore cannot turn a self-authored JSON file into broker
authority. The signed-envelope, offline-issuer, public-root, rotation,
revocation, and repeated mutation-gate contract is specified in
`sentinel-stage-4-automation.md` section 7. Editing a generic `PASS` manifest or
inserting a PostgreSQL row is never a supported activation path.

The certification harness does not issue this activation certificate while
strict xfails and the Wealth Core `NO-GO` remain. Implementing and testing the
issuer does not enroll a real root, create a real certificate, activate
automation, or authorize a broker. Those remain explicit post-review and
post-certification operations.

The schema-3 execution-authority manifest and evidence index are generated only
by `tools/sentinel_authority_evidence.py` from retained producer artifacts. A
reviewed forward-chain artifact is a no-clobber derivative bound to the exact
raw report digest; resource and publication-policy PASS verdicts are computed,
not typed. The issuer requires the producer's base manifest, test summary,
automation configuration, resource policy, and all underlying evidence bytes in
the same indexed bundle. A deterministic blocked bundle is the correct output
while Wealth Core is `NO-GO` or a strict xfail remains.

The signed bindings for Git commit, runtime image digest, and test image digest
are compared at installation and every broker authority check with separately
configured deployment facts. Absence or drift refuses. The broker-capable
runtime is a distinct image, built from the reviewed Sentinel runtime by
`Dockerfile.sentinel-authorized`; it adds one fixed marker that is absent from
the ordinary image and changes the resulting image digest. Automation Compose
selects that authorized image by the same configured digest. The CLI refuses
every broker/admin/authority-enabling command unless both the baked marker and
the overlay's exact intent flag are present, before configuration, database, or
broker construction. The ordinary Compose service carries neither Alpaca
credentials nor artifact-identity environment values.

The certification test image is a tooling lens layered on that exact authorized
runtime, not a sibling built from the ordinary runtime. It receives no broker
credentials and does not set the authorized intent flag, so the marker alone
cannot enable broker access. Tests and the formal production forward-chain
therefore import `/app/sentinel` and Wealth Core from the bytes that will be
deployed, while test-only PostgreSQL binaries, fixtures, and the frozen
reference remain outside the production image.

Manual signed certificate, administrative, inspection, migration, preparation,
and execution commands use the separate digest-qualified
`scripts/sentinel-authorized-cli.sh` surface. Copying claim-shaped environment
strings into `sentinel:latest` is insufficient because that image does not
contain the baked marker. A host administrator who can replace images or mount
arbitrary files into containers already has direct database and deployment
authority and is outside the application membrane; the supported Compose and
CLI surfaces do not provide such a bypass.

### Rollout exposure is durable intent

The actuator has one versioned, one-row rollout state. A behaviorally empty
database starts at `PINNED_1_00`; this is a real operational mode, not a UI
label and not an inference from a numeric exposure. A durable behavioral-schema
migration ledger, not rollout-table absence, decides whether that initial row
may be seeded. Exactly two cases seed it: an empty behavioral database and a
recognized pre-rollout schema. The complete intact schema shipped at
`6113bffd896824ee24891b0c1aeada60c2b73ef5` has a one-time compatibility bridge
that records the migration as already applied and preserves its rollout row and
history unchanged.

The markerless bootstrap fingerprints are closed: empty, recognized
pre-rollout, or complete intact 6113. Any mixed/partial shape refuses. Once the
ledger is installed, a missing singleton, rollout table, ledger row/table, a
gap or unknown version, or a mismatch between the ledger and physical schema is
durable-state corruption. Restart is never a repair mechanism. Migration
inspection, DDL, seeding, the independent post-ledger structural witness, and
the ledger record are serialized under the transaction-scoped schema advisory
lock and commit atomically. Existing rollout state/events, plans, certificates,
account state, and command-event history are never rewritten. The recognized
legacy DDL retains the earlier deterministic backfill of missing current-command
identity from the singleton account binding; it does not alter command events.
A schema fingerprint covers all behavioral columns, defaults, constraints, and
indexes, not only rollout relations. Loss of a primary key, coherence check, or
the one-in-flight-command unique index therefore refuses startup instead of
silently accepting or recreating a weaker execution schema.
A genuine legacy plan receives
nullable, no-default rollout stamp columns and remains unexecutable until a new
plan is prepared; schema migration does not retroactively grant it
`PINNED_1_00` version 1 authority. Every newly prepared execution plan records
the rollout mode, rollout version, and the certificate that authorized a
controller transition, and those fields participate in the plan's economic
fingerprint.

The no-default columns and their named coherence constraint are the redundant
post-ledger witness. The constraint permits either one wholly `NULL` legacy
triple or one complete, internally valid rollout triple; a partial stamp is
corruption. The migration ledger and rollout tables are behavioral backup
state. A table-selective restore that omits either is not repaired at startup.
If every behavioral relation and every independent witness is lost, that empty
catalog is in-band indistinguishable from a genuinely new database. Likewise,
if an unledgered 6113 database loses *every* rollout/certificate relation and
all three plan-stamp columns, the remaining exact historical catalog is
indistinguishable from its genuine pre-rollout predecessor. PostgreSQL volume
identity and whole-database backup/restore are the boundary that must prevent
either complete witness loss from being presented as a new/legacy deployment.
Any surviving post-migration evidence makes missing authority a refusal.
Direct lookup or execution of a wholly unstamped legacy plan refuses. Current-
plan discovery may skip only that wholly unstamped legacy shape so normal
preparation can create a stamped replacement and transactionally supersede the
historical row; it never treats the legacy row as executable authority. A
committed mix of stamped and unstamped current rows is ambiguous and refuses
rather than selecting an older stamped plan.

```text
PINNED_1_00   plan target exposure is exactly Decimal("1")
CONTROLLER    plan target exposure is the durable controller decision
```

Changing to `CONTROLLER` is a separately named, confirmed and audited command.
It requires authenticated authority whose profile allows CONTROLLER and says
controller certification is `PASS`; because trusted issuance is not yet
implemented, this transition currently refuses. Changing back to
`PINNED_1_00` is also explicit and versioned and does not require controller
identity or controller authority. It is **not a de-risking transition**:
`PINNED_1_00` forces 100% Wealth Core exposure, so moving from a controller
target below 1.00 increases exposure and risk. Its confirmation flag and
operator output state that fact without euphemism. A plan prepared under an
earlier rollout version is stale even when its numeric exposure happens to
equal the current one.

The deterministic production plan id is `sentinel-` followed by the complete
64-hex SHA-256 of its immutable economics. It is not a shortened display hash:
that id is mutation authority at the broker and therefore retains the full
collision resistance of the source, state, and certification identities it
binds.

## 0. Why this layer needs its own contract

Stocker's execution lineage is retired, and its defects are the reason this
document exists rather than a port. Four of them are structural, not bugs:

```text
an uncertain broker POST was recorded as FAILED
a retry could mint a new order identity
`partial_fill` and `partially_filled` were a split-brain for months
conflicting intents for one ticker had no resolution rule at write time
```

Each is a different face of one omission: **there was no durable, deterministic
identity for a broker side effect, and no state meaning "we do not know".** Every
recovery path then had to guess, and each guess was a chance to duplicate or
abandon a real order.

The contract below is built so that neither guess is ever necessary.

---

## 1. The two worlds, and the membrane between them

```text
DETERMINISTIC                          MESSY
─────────────                          ─────
Sharadar corpus (versioned)            broker
      ↓                                  ↑
Wealth Core shadow                     commands
      ↓                                  ↑
Sentinel controller                    execution plan
      ↓                                  ↑
target exposure ──────────────────→ desired basket
```

Everything on the left is reproducible from a snapshot plus a pinned corpus
version. Everything on the right is subject to fills, outages, halts, rejects and
manual intervention.

**The membrane is one-directional.** This is architecture invariant #10, restated
at the layer that would violate it: realized exposure, fills, cash and broker
positions are inputs to the *executor* and to *reconciliation*. They are never
inputs to Wealth Core or to the Sentinel controller. If the account is 72%
invested when the controller wants 100%, that is an execution status, not a
change of intent.

---

## 2. Command identity

### 2.1 The rule

> **Every broker side effect carries a deterministic identity that is derived,
> not generated, and is persisted before the network call.**

```text
client_key = H( deployment_id
              , broker_account_id
              , takeover_epoch
              , execution_plan_id
              , security_id
              , command_revision )
```

Each component earns its place:

| Component | Why it is in the key |
|---|---|
| `deployment_id` | two appliances must never mint the same key for different intent |
| `broker_account_id` | the key is meaningless outside the account it acts on |
| `takeover_epoch` | a restored replacement appliance must not collide with the corpse of the one it replaced |
| `execution_plan_id` | ties the side effect to the decision that justified it |
| `security_id` | permanent identity, never the ticker (see §7) |
| `command_revision` | lets a superseded command be replaced by a *deliberately different* key |

**Derived, not generated.** A UUID minted at send time cannot be recomputed after
a crash, so recovery cannot ask "did my command arrive?" — it can only ask "is
there anything that looks like mine?", which is a guess. A derived key turns
recovery into an exact lookup.

### 2.2 The falsifier

```text
crash after send, before response
    → restart
    → recompute client_key from durable state alone
    → query broker by that key
    → the answer is definitive: it exists, or it does not
```

If recomputing the key requires anything not in the database, the key is wrong.

### 2.3 Retry never re-identifies

> **A blind retry reuses the identity. A new identity is only ever minted by an
> explicit supersession that has first resolved the old command's outcome.**

This is the rule Stocker's executor lacked. Reuse is safe because the broker
rejects or returns the existing order; a fresh identity is unsafe because the
broker accepts it as a second order.

---

## 3. Command state, and the necessity of UNKNOWN

```text
PLANNED           durable, not yet sent
SEND_PENDING      about to hit the network; written BEFORE the call
ACKNOWLEDGED      the broker confirmed receipt, with its own id
UNKNOWN           the outcome is not established
PARTIALLY_FILLED  some quantity done, remainder still working
FILLED            economically complete
CANCEL_PENDING    cancellation requested, not yet confirmed
CANCELLED         confirmed gone, by OBSERVATION
REJECTED          the broker refused, definitively
SUPERSEDED        a newer plan replaced it; only legal from a resolved state
```

### 3.1 The invariant

> **A broker request whose outcome is uncertain is `UNKNOWN`, never `FAILED`.**

A timeout, a dropped connection, a 5xx, a proxy error, a process death between
send and response — all of these are `UNKNOWN`. None of them are evidence that
the order does not exist.

`REJECTED` requires the broker to have *said so*. There is no inferred rejection.

### 3.2 What UNKNOWN forbids

While any command for a security is `UNKNOWN`:

```text
no new economically overlapping command may be created for that security
```

Not "no new command" — a *non-overlapping* one (a different security) is fine.
The blocker is scoped to the security whose position is in doubt, because that is
the only quantity the ambiguity can corrupt.

### 3.3 Resolving UNKNOWN

Only two things resolve it, both observations, never an assumption:

```text
the broker reports an order under our client_key  → adopt its state
a complete observation shows no such order AND    → CANCELLED-equivalent:
  no fill attributable to it                        the command never landed
```

The second requires a *complete* observation (§5.2). An observation that admits
it may be truncated cannot resolve an `UNKNOWN`.

### 3.4 Cancellation is confirmed by observation

Carried forward from `sentinel/ownership.py`, which learned it the hard way on
2026-08-09: a broker can accept a cancel and cancel nothing. `CANCEL_PENDING`
becomes `CANCELLED` only when a fresh complete observation shows the order gone.
The API's return value is telemetry.

### 3.5 Emergency authority linearizes at `SEND_PENDING`

An emergency kill or certificate/key revocation is an immediate durable fence;
it must not wait for the execution writer lock. The local side-effect boundary
is therefore the committed `PLANNED -> SEND_PENDING` transition, not the first
network byte. A control transition committed before that durable state prevents
the command. A command already in `SEND_PENDING` may still cross transport under
its existing deterministic key and is recovered through the ordinary
`SEND_PENDING`/`UNKNOWN` rules; all later checks and commands are refused.

This is the only locally enforceable ordering that preserves both a non-blocking
emergency control and recoverable network effects. A database lock cannot make
an external HTTP request atomic, and serializing the control behind a broker
operation would weaken the emergency-control contract.

---

## 4. No autonomous broker-native close

### 4.1 The decision

> **Certified autonomous execution never calls a broker-native "close position"
> endpoint. Exits are ordinary commands for an exact remaining quantity.**

```text
fresh reconciled position
        ↓
desired qty = 0
        ↓
remaining delta = held − already-committed-in-working-orders
        ↓
SELL exact remaining quantity, deterministic client_key
```

### 4.2 Why

Alpaca's `DELETE /v2/positions/{symbol}` accepts no `client_order_id`, so a close
placed through it **cannot carry Sentinel's identity** and is unrecoverable by
§2.2. The IBKR adapter's equivalent is worse: it mints a fresh `uuid4()` per
attempt, so a timeout-and-retry produces two distinct identities for one economic
intent — the exact duplicate-position failure the contract exists to prevent.

The anti-oversell property that broker-native close was buying is re-derived, and
more generally, from three rules that are needed anyway:

```text
fresh reconciliation before sizing
remaining-delta arithmetic against observed quantity
no overlapping command while an outcome is UNKNOWN
```

Those cover trims and exposure scaling too, which broker-native close never did.
Sentinel scales exposure continuously; a mechanism that only handles the 100%
case was never sufficient.

### 4.3 What this requires

**Quantities are decimal, never float.** An exact-delta sell must reproduce the
held quantity to the broker's precision or it is rejected for over-sell. Binary
floating point cannot promise that. `Decimal` end to end, at the transport
boundary too.

**A dust policy is mandatory.** Reverse splits and corporate-action residuals
generate fractional remainders in an otherwise integer book. When a remaining
delta is below the broker's minimum tradeable increment:

```text
the position is flagged DUST_RESIDUAL
it is excluded from exposure-completeness accounting
it is escalated to an operator
it is NEVER retried in a loop
```

An autonomous retry against an unfillable remainder is an infinite loop that
looks like activity.

### 4.4 Administrative migration uses the same identity law

The one-time account migration remains an explicitly invoked administrative
act, but it is no longer exempt from recoverable command identity. Every legacy
SELL is persisted as `PLANNED` and `SEND_PENDING` with an account/epoch-bound
client key before transport. A timeout becomes `UNKNOWN` and must be resolved
through exact client-key lookup before another SELL can be minted. Complete
positions/open-orders reads still decide when the inherited book is flat; they
never prove that an uncertain submit did not land.

Administrative does not mean unsigned. Before binding, a distinct active
offline-signed certificate names the proposed deployment, exact Alpaca paper
account, epoch 1, and only `ADMIN_INSPECT` and/or `ADMIN_MIGRATE`. Restored-host
adoption uses `ADMIN_ADOPT` against the exact current binding and epoch. These
permissions are disjoint from execution permissions and never authorize a
daily plan, automation, a generic broker submit, or a cancel outside the exact
migration state machine.

The command verifies that authority before constructing a broker. The
administrative adapter then re-verifies signature, expiry, revocation, runtime
identity, paper endpoint, exact subject, and publication-policy chain on a
fresh database connection around each read and immediately before every
broker mutation. Exact-id cancellation is checked per id, not once for a
batch, and each ID must appear in the latest complete observation. A submit
must be the durable `SEND_PENDING` named legacy-migration SELL for the exact
signed deployment/account/epoch, full observed Decimal quantity, and observed
broker asset after all working orders disappear; generic broker close/cancel-
all/submit never crosses this membrane. The final account binding or takeover-
epoch increment repeats the check inside the execution writer lock. Loss of
authority fails closed and does not reinterpret a durable `UNKNOWN` submit as
absent.

Emergency tooling is outside certified execution and must be labelled as such.
It is not part of the migration, preparation, or execution commands.

### 4.5 A fresh empty paper account binds without migration authority

`ADMIN_MIGRATE` remains the only inherited-book handover.  It can cancel named
legacy orders and submit durable exact-quantity SELLs, so its historical
zero-debt / Wealth Core `GO` requirement is unchanged.

A brand-new empty Alpaca paper account uses a distinct one-time operation:

```text
ADMIN_BIND_EMPTY
```

Its signed certificate is a separate schema, not a weakened historical
execution or migration certificate.  It is Alpaca PAPER only, names the exact
deployment/account/epoch 1, is attended (`unattended_automation=false`), lasts
15 minutes by default and at most one hour, explicitly grants no historical
certification, and binds the current Git/source/image/runtime/strategy,
execution and automation configuration, publication chain/current corpus,
metadata snapshot, controller configuration, and durable pinned rollout.

The broker object admitted to this operation exposes only `account_snapshot()`
and `observe()`.  It has no submit, cancel, replace, close, liquidation, or
instrument-resolution method.  Each call repeats signature, trusted-root,
expiry, lifecycle/revocation, endpoint, subject, runtime/configuration, and
publication checks on a fresh database connection.

Under the execution writer lock the operation refuses an existing binding
before broker contact, then requires two consecutive complete observations.
Each observation uses the certified orders/positions/orders race detector and
complete Alpaca open-order pagination.  Both account snapshots must be exact
and stable: ACTIVE, every block flag explicitly false, finite positive equity,
non-negative cash/buying power, multiplier 1, and buying power equal to cash
within the existing typed cash tolerance.  Both books must contain exactly zero
positions and zero open/working orders.  Any incomplete, changing, non-flat,
wrong-account, malformed, margin-capable, blocked, suspended, or unsettled
evidence refuses.

Only after every check passes, one transaction writes exactly one epoch-1
`SENTINEL_OWNED` binding and revokes the active bootstrap certificate as
consumed.  A failure writes neither.  A successful retry therefore refuses
twice: the binding already exists and the bootstrap authority is no longer
active.  `ADMIN_BIND_EMPTY` cannot authorize inherited-account inspection or
migration commands, restored-host adoption, plan preparation/execution,
rollout changes, or automation.  Its separately named inspection command is
limited to the same two read-only broker methods.

---

## 4a. Adapter status translation

> **Classify a broker status by "can a trade still occur?", never by whether it
> sounds finished.**

A wrongly-terminal status frees the security for a second command while the
first still fills — a doubled position. A wrongly-in-flight status stalls one
security until an operator looks. Those costs are not symmetric, so neither is
the default: anything uncertain maps to a state that blocks.

Alpaca's `stopped` was mapped to `REJECTED`, and that was a money bug. Alpaca
defines it as *the trade is guaranteed, usually at a stated price or better, but
has not yet occurred* — a fill that is certain and pending, which is nearly the
opposite of a rejection.

```text
stopped        guaranteed trade, not yet occurred      -> blocks
calculated     complete for the day, settlement pending -> blocks
done_for_day   no more execution TODAY; remainder open  -> blocks
replaced       externally altered; replacement may fill -> blocks + ANOMALOUS
```

An unmapped status **raises**. Guessing "still working" leaves a settled order
live in the journal; guessing "terminal" abandons one that is not.

---

## 4b. The economics belong to the plan

The executor reads `plan.target_basket` and has no other source of quantities.
It previously took a separate `desired` mapping alongside the plan, so a client
key could assert "plan P, security S" while carrying a quantity P never said —
and since the journal's upsert deliberately never rewrites quantity, the database
could hold X while the wire carried Y under one identity.

The parameter was **removed** rather than validated: a check can be skipped by a
future call site, an absent parameter cannot. `save_command` additionally refuses
outright if a stored key is rebuilt with different `security_id`, `side`,
`quantity` or `symbol`. New intent needs `CommandIdentity.superseding()`.

---

## 4c. The long-only envelope is enforced HERE

`compute_delta` will turn a desired quantity of −100 against a flat book into
`SELL 100`, which is an opening short. Alpaca supports short selling and runs its
own buying-power check, so the broker does not refuse it on Sentinel's behalf.
The final gate before anything reaches a broker asserts independently:

```text
0 <= target_exposure <= 1
no negative target quantity
```

An execution layer that relies on its caller to preserve the risk envelope has no
envelope.

---

## 5. Broker observation

### 5.1 Typed, not raw

The adapter returns domain objects, never vendor dictionaries passed upward:

```text
BrokerAccountIdentity   who we are actually connected to
BrokerPosition          security identity + Decimal quantity
BrokerOrder             our client_key when present, broker id, state, filled qty
BrokerFill              quantity, price, time, attributable command
BrokerObservation       positions + orders + completeness, as one value
BrokerCapabilities      what this adapter is certified to do
```

### 5.2 Complete, or explicitly incomplete

> **An observation states whether it is complete. A truncated read is never
> silently presented as a full one.**

The certified Alpaca adapter pages the complete **open** order set and reports
`TRUNCATED` if that set reaches its declared cap. Pagination uses Alpaca's
exclusive `before_order_id` cursor, advancing from the oldest order in each
descending page. A timestamp `until` cursor is not a substitute: it is
exclusive, so a page boundary containing multiple orders with the same
`submitted_at` can skip the tied remainder and falsely declare the order set
complete. On a path that can decide "there is no working order", a bounded or
gapped read may never answer an unbounded question.

Completeness also requires structurally trustworthy broker payloads. A
non-array order or position collection, non-object row, missing broker order
id, oversized order page, repeated id/security, or non-progressing cursor is
malformed evidence and fails the read; it is never filtered into an apparently
complete shorter list. Broker identity is what pagination, reconciliation, and
recovery depend on, so silently dropping an unidentifiable row would make an
absence conclusion unprovable.

Lifetime terminal history is deliberately **not** part of observation
completeness. An inherited account can hold more terminal orders than any
bounded API traversal can enumerate; reading `status=all` would then make the
account permanently `TRUNCATED` even when it has no open order. Completeness is
therefore the conjunction of:

```text
all broker OPEN orders, stably paged
all current positions
all CLOSED orders back through the durable *processed-terminal* watermark
    (with a bounded clock-skew overlap), stably paged for stale-restore recovery
positive terminal evidence for each durable nonterminal Sentinel command,
    fetched by exact client key when that command disappears from the open set
```

The closed-order recovery window is derived from PostgreSQL, not from wall-clock
convenience. A dedicated, bound-account-scoped watermark means "every
Sentinel-keyed terminal order submitted through this instant was durably
adopted or synchronized." It survives a takeover-epoch change for that same
broker account, but a watermark naming another account is corruption, not a
fallback. It advances only after reconciliation has processed the complete
recovery window. A raw
`sentinel_observations.observed_at` row is **not** that witness: observations are
recorded before adoption, so a crash in between must replay the same closed
window. When no processed watermark exists, recovery starts at the binding's
`established_at`; every query subtracts a fixed overlap for broker/host clock
skew and boundary replay.

Alpaca forbids combining `after`/`until` timestamps with its stable order-id
cursors. Closed recovery therefore pages `status=closed,direction=desc` using
only exclusive `before_order_id`. Every row must carry an aware, parseable
`submitted_at`, pages must be non-increasing by that value, and a full page at
the recovery floor is not exhaustion because tied timestamps can continue onto
the next page. The traversal is complete only after a short page exhausts
history or a validated descending page crosses strictly below the overlapped
floor. Reaching the page cap first is incomplete evidence and blocks execution.
The adapter captures an upper watermark before the read; rows newer than it may
be observed but cannot advance that watermark, so work arriving during the read
is replayed next time. A captured upper boundary older than the stored processed
boundary is a clock rollback or corrupt future watermark and refuses; it never
rewinds the cursor or treats the future boundary as already searched.

The bounded window discovers a Sentinel-keyed fill that happened after a stale
backup without making the account's lifetime terminal archive a readiness
dependency. Adoption and command updates are idempotent, so a crash before the
watermark commit causes safe replay rather than a gap.

Overlap is validation, not merely duplicate suppression. A previously adopted
client key must still name the same broker order, security, side and quantity;
its fill quantity may not regress, and unchanged fill quantity may not acquire
a different average price or terminal state. Every recovered row has a positive
quantity, `0 <= filled <= quantity`, an aware submission timestamp, and an
average fill price whenever anything filled. One client key attached to two
broker ids is ambiguous ownership. Any violation leaves the old watermark in
place and reconciliation blocked.

Absence from the complete open set proves only "not open". It does **not** say
FILLED, CANCELLED or REJECTED. A known `ACKNOWLEDGED`, `PARTIALLY_FILLED` or
`CANCEL_PENDING` command missing from the open set is looked up by its exact
client key before any transition. Positive terminal evidence is adopted. A
missing or failed exact lookup leaves the command unresolved and blocks new
overlapping work; terminal state is never inferred merely from open-order
silence. `SEND_PENDING`/`UNKNOWN` retain their separately defined never-landed
rule: exact key absence plus a complete open observation can prove that a POST
whose receipt was never established did not land. Positive evidence already in
the complete closed-recovery window is consulted first: an exact 404 can never
erase a matching observed fill.

Average fill price crosses the membrane as `Decimal` and is persisted on the
durable command whenever fill progress is observed or a broker-only Sentinel
order is adopted after restore. Cash reconciliation reads that durable value;
it does not require a terminal order to remain in every future broker response.
This is what makes restart cash authority bounded independently of account age.

Historical orders are resolved by permanent identity at their own submission
session, not at today's session. That timestamp is also persisted as the
durable command boundary when a stale restore adopts a broker-only Sentinel
order, so a later reconciliation applies only corporate actions that occurred
after the recovered command. A rename/delisting in terminal history must not
either retarget the security or block every current observation.

Every observation carries `completeness ∈ {COMPLETE, TRUNCATED, PARTIAL}`, and:

```text
an irreversible conclusion may only be drawn from COMPLETE
an UNKNOWN may only be resolved by COMPLETE
exposure-reducing action may proceed on PARTIAL
exposure-increasing action may not
```

### 5.3 Atomicity is not available, so do not assume it

No broker offers a transactional snapshot of positions and orders together.
Sentinel's own `SentinelBroker.observe()` docstring asserted the property — "the
state machine must never reason across a gap" — and its only implementation read
positions first and orders second, which is the one ordering that can lose an
object entirely:

```text
t0  positions read   → empty        (a resting BUY has not filled)
t1  the BUY fills
t2  open orders read → empty        (it is no longer open)
    ⇒ concluded FLAT, while holding a position
```

**Ordering rule: orders first, then positions.** Under that ordering a fill moves
the evidence from the not-yet-read set into the about-to-be-read set, so it
cannot vanish. The failure mode inverts from "falsely flat" (irreversible) to
"falsely not flat" (costs one cycle).

**Ordering is necessary and NOT sufficient**, and the contract has to say which
half it solves. Reversing the reads converts disappearance into *double
counting*: the same fill is a working order in the first read and a position in
the second, and netting those gives a delta that would SELL a holding acquired
seconds earlier.

```text
positions, then orders      the fill vanishes from both     -> false flat
orders, then positions      the fill appears in both        -> double count
orders, positions, orders   the disagreement is DETECTED    -> observe again
```

**Consistency rule: re-read the orders after the positions and compare.** If the
two order reads differ in state or filled quantity — not merely in the set of ids,
since an order that filled is present in both — the two halves describe different
instants and the observation is `INCONSISTENT`. That is a fourth completeness
value, it fails `require_complete`, and it is a reason to look again, never a
reason to trade. Convergence is what makes that an acceptable remedy: the next
observation is coherent and reports nothing to do.

**Stability rule for irreversible conclusions.** Even a consistent observation
does not cover a third party acting between cycles. Any conclusion that cannot be
walked back — account is flat, migration complete, an `UNKNOWN` resolved as
never-landed — requires two consecutive agreeing complete observations separated
by a reconciliation interval.

### 5.4 Activity SSE has separate economic and replay identities

The current Alpaca Trading/Paper adapter does **not** advertise account-cash
activity authority. Alpaca documents Activity SSE on its Broker API endpoint and
authentication/account model, while this adapter is bound to the Trading/Paper
API. Its SSE decoder remains a quarantined acceptance-harness candidate; method
presence cannot make the production guard call it or earn the identity scheme.
A reviewed, reachable, account-bound integration is required first.

For Alpaca financial activities, `ref_id` is the durable idempotency key for the
economic row and `event_id` is the durable replay cursor. `event_id` is persisted
after a complete batch and supplied as `since_id` on reconnect. Timestamp
`since`/`until` queries are permitted only to establish a bounded upper event
cursor. Discovery always starts at the fixed 1970 business-time floor, before
any possible Alpaca account activity; binding establishment and the stream's
2026-02-11 availability date are not valid `at` lower bounds. Timestamp filters
never authorize gap-free resumption because they filter business time (`at`)
rather than publication order. A delayed/backfilled event with old business time
must still be observed at the end of the `event_id` stream.

The candidate decoder validates the required common envelope before routing an
event: the account UUID must match the bound account, `status` must be exactly
`executed`, and `currency` must be USD. Missing/non-final status or any other
currency refuses the entire batch. Sentinel has no reviewed FX conversion
contract and must never add a local-currency `net_amount` to a USD cash ledger
or treat a local-currency fill price as USD.

The cash cursor therefore retains both ids plus the audited
`processed_through` time. An upgrade from the timestamp-only cursor performs the
same exhaustive discovery and deduplicates by `ref_id` before it earns the first
event cursor. A retained cursor disappearing from that discovery is source
contradiction, not an empty interval. Trade events filtered out of cash
accounting still advance the shared Activity SSE event cursor; otherwise an
account containing only fills would replay the same stream forever. Ordinary
`TRD/fill` cash is not added to the activity total because the exact durable
fill ledger already moves plan cash; booking both would count the same trade
twice. A correction or bust remains a refusal until the prior native fill can
be reversed.

An append-only event cursor proves only what has been published so far. Activity
SSE exposes no accepted fixed close interval or finality watermark. No global
scheme allow-list can promote old plan baselines into close authority: a future
source must retain a separate immutable finality witness bound to the exact
plan, account, and close session.
It cannot certify historical return even when its current cumulative amount and
last cash `ref_id` match the plan baseline. Retained v3 verifications re-read the
exact session cash ledger and embedded plan-cash baseline/finality reference on
every load and chain operation; a late insertion, source change, or finality
revocation invalidates the historical chain.

Cash journals (`JNLC`, including the legacy `JNL` spelling) cross the owned
account boundary and are external capital, never strategy income. Securities
journals/transfers (`JNLS`/`ACATS`/`FOPT`) are refused until an in-kind-flow valuation
and time-weighting contract exists. A known cash-impact event without
`net_amount` is malformed financial evidence rather than an ignorable event.

Terminal fill recovery does not yet own an independent durable event cursor.
Consequently its bounded recovery read traverses the complete available
Activity SSE lifetime and deduplicates native fill ids; narrowing that read to
the terminal timestamp watermark would recreate the same backfill gap. The
ordinary diagnostic `recent_fills(since)` call may retain its requested time
filter because it is not completion authority.

---

## 6. Execution plans and supersession

A plan is immutable and records the decision that produced it:

```text
plan_id
decision_session          the session whose close produced the decision
effective_session         the session whose open it executes at
shadow_snapshot_hash
sentinel_transition_hash
target_exposure
target_basket             security_id → Decimal quantity
data_version              the corpus version consumed (§8)
strategy_fingerprint
deployment_id, broker, broker_account_id, takeover_epoch
publication_fingerprint
account_nav, account_cash, explicit cash_residual, unpriced securities,
defensive instrument
```

The production adapter and command authority are specified in
`docs/sentinel-paper-activation.md`. In particular, final state advancement and
plan adoption are one transaction, the effective session is the next XNYS
session after the decision close, and the execution command accepts no plan
economics from its caller. A same-session preparation retry verifies and keeps
the already-current immutable plan; it does not silently re-size that plan from
a later account observation. Readiness is always judged against the actual
exchange-local observation time, never a caller-supplied future date.

For a production Sentinel plan, `plan_id` is itself an authority, not an
arbitrary database handle. Its only valid value is
`sentinel-<ExecutionPlan.fingerprint()>`, recomputed from every immutable
economic and identity field after the durable row is loaded. Same-session
preparation, current-plan inspection, and execution refuse a mismatch. The
execution gateway performs this check before any broker read or mutation, so a
database edit that preserves the old id and state/publication stamps cannot be
authorized merely by confirming that stale id.

The account NAV is the immutable sizing input, but a fixed share plan is not
invalidated merely because its holdings mark up or down overnight. Cash is the
separate recovery authority. Initial adoption requires no working broker order
and stamps the typed account-cash baseline. On retry/execution the strict
gateway reconciles that baseline to every durable fill at the average fill
price persisted with that command when the broker supplied positive evidence.
Any residual cash movement is unexplained and refused; it
is never guessed into P&L or a flow. The activation gateway has no same-session
cash-flow re-projection authority: the adopted plan remains unexecuted, the
flow is resolved and recorded separately, and a new plan is prepared from the
next closed decision session. The general re-projection contract in section
13.3 is not exposed as an activation-command override.

The gateway additionally accepts only a cash-only paper account whose broker
reports `status == ACTIVE`, all of `trading_blocked`, `account_blocked` and
`trade_suspended_by_user` explicitly boolean and false, `multiplier == 1`, and
buying power equal to cash (within the absolute cash-reconciliation tolerance).
A missing or non-boolean availability flag is malformed broker evidence, never
silently "unblocked". Buying power below cash means sale proceeds are not yet
spendable; buying power above cash exposes margin. Both refuse before an
increase. A DAY market order can still gap beyond its decision-close sizing
mark, so software cannot prove a bounded fill cost before the fill. The
cash-only broker envelope is therefore load-bearing: an unaffordable increase
is rejected rather than funded by margin. This runtime account fact is checked
on every preparation/execution entry and does not weaken the live-endpoint
refusal.
Binding creation and restored-host takeover-epoch adoption take the same
single-writer advisory lock as preparation and execution, and those operations
read the binding only after acquiring it. The full binding stamped into a plan
or command therefore cannot change in the authority-to-side-effect gap.

When a new session produces a new decision before the previous plan has
completed, **history is not mutated**. A new plan is created and may supersede
the old one's *unsent* commands. Commands already working at the broker must be
resolved — cancelled and confirmed cancelled, or allowed to complete — before a
replacement command for the same security is created.

```text
SUPERSEDED is only reachable from PLANNED, or from a resolved terminal state.
A command in UNKNOWN cannot be superseded. It must be resolved first.
```

---

## 7. Security identity to the broker boundary

Ticker is a display and transport form. It is never the financial identity.

```text
security_id          permanent, from the corpus
system_ticker        current display form
broker_instrument_id the broker's own stable identifier where one exists
broker_symbol        the transport spelling (BRK-B ↔ BRK.B ↔ BRK B)
```

Symbol translation stays at the transport boundary, as it already does. What
changes is that the *command* and the *position* are keyed on `security_id`, so a
rename between decision and execution cannot silently retarget an order.

---

## 8. Corpus versioning — an existing invariant, not a new proposal

Architecture invariant #3 already reads:

> Pinned input history. Every snapshot and decision records `data_version`.

The feed publication path assigns a monotonic `data_version`, records publication
identity/evidence, pins every production decision to that version, and hides
rows whose ingest run never became a publication. This implements the DETECTION
tier: an operator can distinguish broker drift from moved history. Bar revision
history is not retained, so a Sharadar restatement can still prevent exact
reconstruction of an earlier decision's inputs.

### 8.1 Two tiers, and their certification state

```text
DETECTION       "this decision read v47; the corpus is now v52, so a replay
                 may not reproduce it"                        ← IMPLEMENTED
RECONSTRUCTION  "show me exactly what v47 contained"          ← DEFERRED
```

Detection is what makes a divergence report interpretable — it separates "the
broker drifted" from "the history moved", which is the question
`sentinel-architecture.md` §5 actually poses. Reconstruction requires revision
history and is a much larger build; it is deferred to the end of the sequence.

The DETECTION tier is implemented; the RECONSTRUCTION tier remains deferred.

`data_version` identifies the published facts, but it cannot by itself identify
the code that interpreted those facts into a path-dependent book. Production's
strategy identity therefore also binds a versioned Sharadar book-semantics
source bundle: ACTIONS classification/effective dating, SEP price/share-domain
normalisation and its durable staging order, raw-action and anomaly generations,
historical replay/recovery, published overlays, security/session mapping, the
production corpus loader/session adapter, breadth/regime/controller transitions,
catch-up and shadow orchestration, terminal-action mapping, canonical target
extraction, account sizing, paper pre-open orchestration, execution-time split
projection, expected-book reconciliation, and the shared split/dividend and
terminal-coalescing helpers. The exact identity is
persisted in every canonical state and plan and is covered by activation
authority. If any bundled source changes, an older state is not migrated in
place or advanced under a new corpus version; startup refuses until a reviewed
reconstruction establishes a new state. This is deliberately stronger than
recording the deployment commit: an immutable old book cannot silently inherit
corrected data semantics merely because the next session exists.

### 8.2 The publication record

An ingest *run* is not a corpus *version*. A run that fails halfway has a
`run_id` and must never be citable as a version.

```text
corpus_publications
    version           BIGINT, monotonic
    previous_version  the chain; a gap means rows were written but never published
    run_id            which ingest produced it
    published_at
    evidence          row counts, window, digests, producing Git commit and
                      selected immutable runtime-image digest
```

Rules:

```text
the row is written ONLY after validation passes
readers resolve "current version" through this table, never by observing rows
the engine PINS a version at session start and treats the corpus as frozen
ingest MUST NOT publish while a session is being processed
every new run-backed publication requires the same non-blank producer binding
on its feed_ingest_runs row; publication copies it into immutable evidence
```

Producer identity is authorization as well as attribution. The supported host
wrapper admits a feed mutation only when the selected image's OCI revision
equals a clean repository `HEAD`, resolves the exact selected digest, and
injects both facts. The container checks its baked source revision against the
injected commit before database contact. Thus an old immutable image remains a
valid object for inspection but cannot publish after the source advances.
Environment compatibility and deployment certification are separate verdicts;
the former cannot authorize a corpus writer.

The last two matter more than they look. Without them a decision stamped `v52` is
only approximately true, and approximately-true provenance is worse than none —
it will be believed.

Bars and universe rows additionally carry `last_written_run_id`, which is nearly
free (`write_bars` already runs inside an `IngestRun`) and answers "which ingest
produced this value" without bar revision history. **Published is what readable
means**: `publication.visible_predicate` hides any row whose writer run has no
publication. Rows with a NULL run id stay visible because they predate tracking.

ACTIONS uses the stronger snapshot form needed by a complete-source response.
`sentinel_actions` is the immutable pre-upgrade baseline;
`sentinel_action_generations` records each explicitly and completely fetched raw
date window, and `sentinel_action_observations` appends `PRESENT` or `REMOVED`
evidence for every affected economic key. `sentinel_active_actions` ranks the
legacy baseline and published observations by corpus publication and exposes
only the newest `PRESENT` disposition. A corrected value is another `PRESENT`
observation; a row absent from a later complete response is `REMOVED`, not
deleted. An unpublished or failed generation is durable history but cannot
change the active action set. The ingest may overlay its own candidate
generation while normalising that same run; all other consumers read the
published active view. This is deliberately narrower than bar reconstruction,
but it gives complete ACTIONS snapshots the lifecycle an upsert cannot express.
Each generation has append-only `PENDING` and terminal `PUBLISHED`, `ABORTED`,
or `SUPERSEDED` events. A successfully published covering retry supersedes an
older publication-failed candidate; a narrower fetch cannot. Recovery and
failed-ingest handling abort only pending generations under the corpus writer
lock. The same publication transaction activates the action generation,
anomaly disposition, and split-repair overlay, and rolls all activation back if
the publication row fails.

Complete ACTIONS authority does not define the retained SEP horizon. A
reconciliation may observe and retain rows from `1900-01-01`, but changed
actions trigger price re-normalization only when their effective XNYS session
falls inside the already-published market corpus, and the prior/effective/next
replay is clipped at that corpus boundary. This keeps historical action
negative-space complete without silently expanding a short operational price
seed. On retry, stable source replay first reclaims failed in-range bar keys and
durably records the retained market boundary and exact replay windows that can
prove current-source absence. Residual failed ACTIONS-reconciliation bars in
those windows, plus candidate-only rows outside the published market boundary,
remain untouched during candidate construction and are retired only by the
replacement publication transaction. A crash after ingest success can therefore
resume that same publication transaction without reconstructing coverage from
process memory.
SEP `lastupdated`
maintenance is bounded on both sides by the same retained horizon; a current
revision outside it belongs to a deliberately wider complete seed, not to
incremental corpus expansion.

Universe recovery is deliberately different because TICKERS is a complete
dated snapshot keyed by `(permaticker, ticker, snapshot_date)`. A retry on a
later date cannot overwrite the failed snapshot's keys. Once the retry is
durably successful and has written exactly one non-empty complete universe
snapshot, its publication transaction deletes only rows owned by durably failed
unpublished runs whose snapshot date is not later than the retry snapshot. The
publication evidence records each retired run and row count. A published row,
a future-dated candidate, or a candidate not durably failed is never retired by
this rule, and rollback restores the candidate if publication fails.

This retirement rule normally does not extend to destructive economic-key
tables. `sentinel_bars`, `sentinel_spy_total_return`, and the legacy
`sentinel_actions` surface may have overwritten a key that an earlier
publication named; deleting a failed owner during candidate construction would
then delete corpus history rather than restore it. The ordinary daily price
overlap and required 41-session SPY fetch must rewrite those keys under the
retry run, and publication refuses while any older unpublished owner remains.

The one bounded exception is a failed `actions_reconcile` bar that remains after
the replacement run has stably replayed the complete prior/effective/following
SEP window containing it. The surviving old owner is then an authoritative
source absence. Even in that case deletion is deferred to the replacement
publication transaction; the exact replay windows are explicit inputs, the
retired count is publication evidence, and any later failure rolls the deletion
back. Candidate-only failed ACTIONS bars outside the retained market boundary
follow the same transaction rule. Production ACTIONS, anomalies and split
repairs retain their append-only lifecycle rules.

### 8.3 Published is not enough on its own — the pin must freeze the ROWS

That rule buys the right property against a corpus that only GROWS. Against one
rewritten in place it is not sufficient, and the gap is not subtle:

```text
v41 published, AAA/2026-08-10 visible
a session pins v41 and starts reading
the daily ingest UPSERTs that row -> last_written_run_id = run42
the predicate now HIDES it
the same calculation, still nominally on v41, sees a different corpus
```

The version number never moved. `require_current` still answers 41. The snapshot
that number names changed underneath the reader — a bar can vanish mid-window,
or return with a restated split ratio, which does not even change the row count.
`visible_predicate` is re-evaluated per query, and what it evaluates is mutable.

So an ingest holds `store.corpus_write_lock` — `CORPUS_LOCK_KEY`, EXCLUSIVE —
for its whole duration. A reader's shared pin and a writer are then mutually
exclusive by construction rather than by two modules agreeing to be careful.
Whole run, not per chunk: per-chunk acquisition leaves a window between chunks
in which a reader pins a half-written corpus, the same defect one level down.
`write_bars(require_lock=True)` asserts the lock against `pg_locks`, so the rule
is enforced rather than documented.

**Why not generations, which would be better.** A `generation` column with an
atomic pointer move is the correct end state and is the RECONSTRUCTION tier of
§8.1. It answers "show me v47", which this does not. It also changes the write
path, the read path, repair, coherence and every test that touches the hottest
table in the system, and a daily re-fetching a 14-day overlap needs
content-change detection or it writes ~140k redundant rows a night. What is
implemented is the subset of that guarantee which closes the hazard — and it is
required under generations too, since the pointer move must still exclude a
reader mid-snapshot. For a single-writer appliance that decides once per session
and ingests in the evening, the exclusion costs nothing it does concurrently.

---

## 9. The ingest previous-observation seam

`normalise_sep_rows` recovers a split ratio by comparing a bar against **the
previous observation of the same security**, and initialises `prev = {}` on every
call. Both callers invoke it on a window:

```text
seed    one calendar year per chunk
daily   [frontier − 14 days, today]
```

So the first observation of each security within a window has no predecessor, and
`split_ratio_from_domains(None, None, …)` returns `1.0` — "no split".

### 9.1 This does not merely fail to detect; it overwrites

`_BAR_UPSERT` sets `split_ratio = EXCLUDED.split_ratio` unconditionally. The
14-day daily overlap exists to absorb vendor restatements, and at its leading
edge it recomputes a derived ratio with no predecessor and writes `1.0` over a
previously-correct value. **The repair mechanism corrupts at its own boundary.**

Protection today comes only from `authoritative_splits`, and the ingest's own
`SPLIT_ONLY_DERIVED` warning exists precisely because ACTIONS coverage is
incomplete.

Sparse securities are affected anywhere in the window, not just at its edge: a
name whose only print in the window is mid-window has no predecessor either.

### 9.1a Uncertain split evidence is cumulative and publication-scoped

An uncertain split is not made irrelevant by the security failing an admission
floor on the event date. The ratio changes its cumulative signal series for
every later session, so it can change later eligibility, rankings, selections,
holdings, accounting and hashes. The observed holdings are not a counterfactual
witness: incorrect split treatment can be why the security never appears there.
Consequently `SPLIT_ONLY_DERIVED` and `SEAM_SPLIT_UNCORROBORATED` block
certification unless a complete interval replay proves equivalence under every
plausible treatment. The present system has no such proof and uses no local
price, liquidity or book proxy. Direct authoritative, finite-price-interval,
and narrowly bridged split dispositions remain resolved.

Anomaly observations use the same publication boundary as their corpus. They
are append-only and carry `last_written_run_id`; the active disposition is the
one associated with the newest successful publication for the economic event.
Each stamped observation also has append-only lifecycle evidence: `PENDING`,
then exactly one terminal `PUBLISHED`, `ABORTED`, or `SUPERSEDED`. Only an
unpublished observation whose latest state is `PENDING` is live candidate work
and blocks corpus coherence. A terminal failed run and `reclaim_orphans()`
durably abort their candidates under the corpus writer lock; a successful
publication marks its observations published and supersedes older pending
observations for the same explicitly covered event in the same transaction as
the corpus publication. Historical observation and lifecycle rows are never
deleted. Repeating recovery is idempotent, and a recovery transition can touch
only pending evidence, so it cannot retire a newer published disposition. A
database constraint permits at most one terminal state per observation, and
publication refuses stamped anomaly evidence whose ingest is not durably
`success`.

Silence is not a disposition. A current ingest that proves a previously
anomalous event is clean emits an explicit `DIVIDEND_RESOLVED` or
`SPLIT_RESOLVED_NO_EVENT` observation. A dividend resolution requires a current
authoritative ACTIONS row for the same event with a usable positive amount. A
split no-event resolution requires a complete current ACTIONS generation, an
SEP comparison against a real predecessor whose unsnapped price-domain ratio is
within the no-split tolerance, no current authoritative split, and an effective
candidate split ratio of exactly `1.0`. If the base bar preserves an older
non-1 ratio, the corrective run appends a `1.0` split-repair overlay. The repair,
action removal, and resolved disposition become active through the same corpus
publication; publication failure leaves the older action, effective ratio, and
blocker active. Missing coverage or missing ratio correction emits no tombstone.
Legacy rows with no run identity remain the oldest baseline, never silently
discarded; ambiguous baseline ties remain fail-closed.

### 9.2 The fix

Seed `prev` from the last stored observation strictly before the window, keyed on
`security_id`:

```sql
SELECT DISTINCT ON (security_id) security_id, close_signal, close_unadjusted
FROM sentinel_bars WHERE session < %s ORDER BY security_id, session DESC
```

**Not a lookback window.** A security can be sparse for weeks; a fixed margin
cannot bound it. This is why chunking the *canonical loader* was withdrawn in
`926b313` and cannot be revived by widening a margin — but the *ingest* is a
different case, because it has a corpus to consult and the loader mid-window does
not. The ingest additionally already carries `_ACTION_LOOKBACK_DAYS` for the
corporate-action half of the same boundary.

### 9.3 Repair, not just prevention

Prevention leaves existing damage in place, and a correct loader reading a
corrupted stored value is still wrong.

**Audit (bounded, cheap).** `sentinel_actions` holds authoritative splits
independently. Every stored bar with `split_ratio = 1.0` on a `(ticker, session)`
that ACTIONS records as a split is a *confirmed* corruption. This is a **lower
bound** — it cannot see splits ACTIONS never recorded, which is the at-risk
population — so it sizes the damage and serves as the repair's acceptance test.
It does not replace the rebuild.

**Repair.** A contiguous re-derivation over the affected span with correctly
seeded `prev`. Re-running `daily` is not a repair: it recreates the defect at the
new leading edge.

---

## 10. Reconciliation

### 10.1 Order of operations after any gap

```text
1  verify account binding (§11)
2  acquire the single-writer lock
3  observe the broker COMPLETELY
4  recover commands by client_key namespace
5  apply corporate actions covering the gap        ← §10.2
6  classify anything still unexplained
7  only then compute a new desired basket
```

Nothing is submitted before step 7 completes.

### 10.2 Corporate actions are applied before foreign-activity classification

> **A quantity or instrument change that a corporate action explains is not
> foreign activity.**

This is not a refinement, it is a correctness requirement. A 2:1 split during an
outage doubles the broker's share count; a reverse split halves it; a spinoff
adds an instrument Sentinel never bought; a merger replaces one. All four match
the naive foreign-activity triggers, so without this rule the appliance latches a
block on re-risking after every corporate action it slept through — which is
every outage of more than a day or two in a 25-name book.

Reconciliation therefore loads `sentinel_actions` from the earliest durable
command through the observation and applies each supported share-count change
to each command only when the action occurred after that command was created.
The expected book is reconstructed from this action-aged lifetime basis before
it is compared with the broker. Using only `(last decision, today]` would appear
correct on the split day and forget the split as soon as the state cursor moved;
applying one aggregate lifetime multiplier to every fill would instead multiply
orders that were placed after the split. Neither is a durable reconciliation
basis.

Only an ACTIONS `split` row is listed-share authority; `adrratiosplit` is
depositary-ratio metadata and cannot independently resize a broker holding.
The `split` value is the direct new-float/old-float multiplier. The raw calendar
ex-date is snapped forward to its first XNYS session. For an equity, execution
consumes the active published split disposition together with the canonical
`effective_split_ratio`, including the latest published repair overlay. It does
not reinterpret the raw ACTIONS date from that date's bar alone. When the
published stream proves that the price/share transition occurred one session
before the raw ACTIONS date, the prior non-1 bar is the one and only scalar
event and the raw-date `SPLIT_RESOLVED_NO_EVENT` disposition contributes no
second event. A `SPLIT_RESOLVED_NO_EVENT` that proves the issuer action did not
change the listed instrument likewise contributes multiplier 1 and no material
execution event. A missing, contradicted, or unsafe disposition remains
blocking; a resolved disposition is never permission to suppress conflicting
current published evidence.
Because a disposition is observed at ticker/session grain, it may authorize a
permanent-security holding only when that published coordinate maps to exactly
one security id. A duplicate coordinate is blocking evidence; the disposition
cannot fan out into two books.
For the fixed `SENTINEL:BIL` defensive identity, which intentionally has no
stored split column, execution derives the independent ratio from the
immediately preceding XNYS session's published adjusted/as-traded domains and
calls the same shared corroboration resolver as ingest and canonical replay.
Absent or contradictory required evidence fences the intersecting book. The
scalar ACTIONS vocabulary is exactly `split`; `spinoffdividend` is a
cash-distribution row and does not by itself change share identity (unlike a
`spinoff`, which remains blocking).

### 10.2a Decision-close to execution-open target reprojection

A scalar share-count action in `(decision_session, execution_session]` changes
the units in which an immutable plan is expressed; it does not change the
plan's economic intent. Sentinel therefore writes an immutable, namespaced
target-projection record before the first order. The record binds the original
plan id and fingerprint, the through-session, each authoritative action source
row, the exact action multipliers, the resulting share basket, and a canonical
projection fingerprint. The executor accepts that basket only after loading the
identical durable record under its writer lock. The plan row is never edited,
and a retry cannot rebuild the same command identity with different quantities.

The projection must remain representable by the certified adapter. Alpaca's
certified quantity increment is `0.000000001`; a reverse split residual is
submitted exactly in that domain. Any target outside an adapter's declared
increment refuses rather than rounding into a new economic intent. An ambiguous,
unmapped, non-positive, or non-finite scalar action also refuses.

That broker increment applies only after the strategy's own pending-order
semantics have been preserved.  The immutable plan fingerprint binds the exact
canonical `SessionState`, and target reprojection must recover from that state
which shares are already held, which are pending closes, and which are pending
opens.  Held shares and pending closes retain the exact fractional entitlement
created by a split.  A pending open remains an entry trade, however: Wealth Core
cancels it when the action-aged quantity is non-positive or non-integral, before
examining broker tradeability.  Reprojection must therefore remove the matching
account-sized target contribution and record the cancellation; a broker's
ability to buy fractional shares is not authority to resurrect an entry the
strategy cancelled.  The check is performed at every effective action session,
not merely on the aggregate ratio: two material actions whose product is one
cannot resurrect an entry cancelled at the first boundary.  Applying one scalar
to an aggregate target without this intent lineage is forbidden.

Trial account evidence consumes that exact durable v2 target projection; it
does not independently action-age the flat immutable plan basket.  The
effective-session close target is the projection's target basket, and the
evidence binds its projection fingerprint and cancelled pending OPENs.  A
later observation target starts from that projected basket and applies only
scalar events strictly after the projection's through-session.  Reapplying the
decision-to-execution multiplier, or omitting the durable projection, is a
verification refusal.

Published market ratios are stored as binary floating point, so a repeating
ratio such as `1/30` is represented approximately even when the entitlement is
an exact whole share. Target reprojection may remove that representation noise
only by reconstructing the exact rational from the durable raw denominator and
per-event canonical multiplier. The canonical evidence product must reproduce
the aggregate multiplier and the rational result must already be an integer
number of broker increments. There is no nearest-increment fallback: `300/30`
is exactly `10`, while `301/30` remains fractional and refuses.

#### Pre-open share-unit authority is an affirmative execution input

The stable automation failure for this boundary is
`PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE`. Automation prepares from the
decision session's closed and published corpus, then executes at the following
session's open. The new session's SEP/SFP bar—and therefore its canonical
effective split ratio—does not exist until that close, while the ordinary
ACTIONS ingest is also bounded through the decision session. The
historical/recovery lookup remains correct once the event session is published;
silence at the open is not proof that no share-unit event exists.

Any invocation with a nonempty active share-unit set therefore requires one
immutable pre-open authority record. It binds the plan id and
fingerprint, effective XNYS session, provider and provider-publication id,
provider cutoff/as-of time,
complete covered permanent-security identities, an explicit oriented positive
multiplier for every covered identity (including `1` as an affirmative no-event
attestation), source event/revision identities, and a canonical evidence digest.
The covered set is exact: every nonzero plan target, every nonzero action-aged
durable expected-book identity, and every durable in-flight command identity.
This includes `SENTINEL:BIL` when its target, expected holding, or in-flight
command is nonzero/active. A zero-valued BIL basket key by itself is inactive;
including it as extra coverage is also a refusal. Wrong-session, stale, partial,
missing/extra identity, duplicate, revised, or digest-inconsistent evidence
refuses before target projection or command reservation.

A COMPLETE clean reconciliation may bypass the record only for an empty
share-unit domain: every target, holding and commitment is exactly zero and
neither a durable command nor a broker order is still working. Equality between
a nonzero raw plan target and a nonzero broker holding is not proof of no event;
an unobserved split can make incomparable units numerically equal. Dust is not
empty, and this exception cannot authorize a held, targeted or committed share.

Alpaca's corporate-actions endpoint is positive evidence only: its documentation
does not guarantee creation time and permits provider/processing delay. An empty
or repeatedly identical response, `data_quality=all`, a quote discontinuity, or
the absence of a broker position for a fresh target therefore cannot create the
required negative attestation. Raw ACTIONS values are not an acceptable
substitute either. The producer is operationally absent and no trusted
issuer/authenticator is configured. The existing persistence/validation shape
does not make an arbitrary locally inserted record reviewed market-data
authority. Every nonempty autonomous cycle therefore remains fail-closed until
a reviewed source with full-universe pre-open delivery,
negative-space/completeness authority, and an explicit trust/acceptance boundary
is integrated. This closes the unsafe execution path; it does not turn missing
market information into a deployment GO.

This refusal is scoped to broker execution. A broker-free forward observer has
no broker share-unit domain: it advances the canonical strategy state only
after the next session's open, close, and action data have been published. Such
an observer may receive `SHADOW_GO` when the NAS corpus, canonical engine,
freshness, exact tests, and zero-mutation boundary pass. It may not submit,
cancel, or replace orders; may not read an Alpaca holding as its economic book;
and may not translate dual-source silence into a multiplier. The independent
`PAPER_EXECUTION_GO` verdict continues to require this entire affirmative
pre-open contract. See `sentinel-nas-go-validation.md`.

Non-scalar events are different. A spinoff, stock/cash merger, rename,
reorganization, or terms-less terminal event can add an instrument, remove one,
or add cash. Sharadar ACTIONS is sufficient to detect those event classes but
not to manufacture broker-grade entitlements. If one intersects the plan,
shadow target, or durable command book, execution fences before sizing. Sentinel
does not create synthetic positions, cash, fills, or corrective orders to make
an Alpaca paper account resemble live clearing.

This is an explicit broker-boundary decision. Alpaca live accounts process
mandatory corporate actions and expose native activity evidence; Alpaca paper
accounts may leave positions unchanged. Paper is used as realistically as its
observable state permits, but a paper-only omission remains a visible limitation
rather than an invitation to build a second brokerage ledger.

### 10.3 Foreign activity

What remains unexplained after §10.2:

```text
a position Sentinel cannot attribute
an order with no client_key of ours
a quantity change no action explains
```

⇒ `FOREIGN_ACTIVITY`, which blocks exposure-*increasing* commands until an
operator acknowledges. Risk-reducing action continues, because the plausible
cause is a human intervening to de-risk and the appliance must not fight them —
but it must also not silently undo them by buying back to target.

---

## 11. Account binding, takeover epoch, and fencing

Persisted transactionally, in PostgreSQL, and checked at every startup:

```text
deployment_id
broker            alpaca | ibkr
broker_account_id
takeover_epoch    monotonic
ownership_state   SENTINEL_OWNED
```

At startup Sentinel asks the broker who it is connected to. A mismatch between
the configured/observed account and the persisted binding is a refusal to trade,
not a warning.

### 11.1 The impossibility boundary, stated plainly

No local software can prevent two restored appliances from both trading one
account while both hold valid credentials. That requires an external fence.

The operating rule is therefore procedural and must be documented as such:

```text
before activating a restored appliance against the same account,
revoke or rotate the previous appliance's broker credentials
then run an explicit adopt-restored-account with the exact bound paper account
confirmation. The replacement credentials must identify that account before
anything durable changes. Account verification, the adoption audit event, and
the takeover_epoch increment occur under the execution writer lock; a missing
credential, unreadable identity, or mismatch leaves the old epoch untouched
```

Ordinary reboots need none of this. Moving to a replacement host does.

### 11.2 Ownership moves to PostgreSQL

`ownership.jsonl` was chosen because Sentinel had no database. It now has one.
The file becomes optional audit evidence; the database becomes authoritative,
carrying the binding above in the same transaction.

**And the legacy-liquidation path leaves normal startup.** Today, losing one file
on one volume re-arms classification of a Sentinel-owned book as legacy. After
migration, ordinary startup must contain no automatically re-armable liquidation
at all: migration becomes an explicit administrative command that refuses to run
against a bound account.

---

## 12. Runtime states and their permissions

Not "healthy" or "failed".

| State | reconcile | reduce exposure | increase exposure | new commands |
|---|---|---|---|---|
| `RUNNING` | yes | yes | yes | yes |
| `RECONCILING` | yes | no | no | no |
| `DATA_DEGRADED` | yes | yes | no | reductions only |
| `BROKER_DEGRADED` | no | no | no | no |
| `FOREIGN_ACTIVITY` | yes | yes | no | reductions only |
| `DUST_ESCALATION` | yes | yes | yes | yes (residual excluded) |
| `INTEGRITY_HALTED` | no | no | no | no |
| `OPERATOR_PAUSED` | yes | no | no | no |

The shadow and the controller keep advancing in every state except
`INTEGRITY_HALTED`. Being unable to *act* is not a reason to stop *knowing*.

This table lives in a small pure kernel, checked immediately before durable
command creation. There is no remote risk service to ask.

---

## 13. Offline for days

The single most important behaviour that no amount of correct steady-state code
provides.

```text
restore trusted snapshot
ingest every missing session
advance the shadow session by session
advance the controller session by session
record every missed decision as audit
DO NOT generate retroactive orders
reconcile the broker (§10)
compute the CURRENT desired basket
trade toward it under the missed-open policy
```

The consequence is the point: if the controller went `100% → 0% → 55% → 100%`
entirely while the machine was down, and the current legitimate target is again
`100%`, the appliance does **not** liquidate and rebuy to reproduce orders it
could never have placed. The shadow history still records that the episode
happened; execution records that the transitions were unavailable.

### 13.1 Missed-open asymmetry

```text
desired exposure BELOW realized   → may execute as soon as broker state is
                                    trustworthy and the market permits
desired exposure ABOVE realized   → waits for the next certified execution window
```

Selling late is dangerous; buying late is opportunity cost. Do not chase missed
recovery buys intraday because a server came back.

This is part of the execution model and therefore part of certification.

### 13.1a Two-phase execution: reduce, settle, re-observe, re-size, increase

§13.1 orders reductions before increases. That is not the same property as
sizing them separately, and the gap between *submitted* and *settled* is where
the whole failure lives. Every delta used to be sized against ONE observation
taken before anything was sent:

```text
observe            A: 50 held,  B: 0 held
submit SELL A 50   ... still working
submit BUY  B 100  <- sized against a book that no longer exists, funded by
                      proceeds that have not settled
```

**The money.** The purchase assumes the sale's proceeds. If the sale is partial,
still working, or UNKNOWN, the purchase is funded by margin — which §4c's
long-only unlevered envelope exists to exclude, and which the broker provides
without being asked.

**The quantity.** Anything that changes the book between the two submissions is
invisible to the second. A foreign fill, an order the broker closed
`done_for_day`, an over-fill on the sale — each makes `desired − held −
committed` stale arithmetic, and the machinery that exists to make convergence
exact converges to the wrong number.

So:

```text
1  size everything against the pre-trade observation
2  PRE-FLIGHT the increases: anything that can never be authorised on this
   evidence is REFUSED here, with its real reason
3  submit the reductions
4  SETTLE — reconcile until every required reduction is FILLED, bounded by
   settle_cycles. REJECTED, CANCELLED, PARTIALLY_FILLED, UNKNOWN, absent, or
   still-working reductions are not settlement
5  re-observe; require COMPLETE, RUNNING, clean reconciliation
6  in the strict paper path, re-read typed cash/buying power and require
   `multiplier == 1` plus buying power equal to cash; filled-but-unsettled
   proceeds are not spending authority
7  RE-SIZE the increases against the post-fill read and submit them
```

Steps 4-7 are skipped when there is nothing to settle for: a pure-buy session
has no proceeds to wait on, and an unconditional extra round trip is latency for
nothing.

**Settled means every required reduction is FILLED, on a COMPLETE, clean
reconciliation.** "Not working" is insufficient: rejected and cancelled orders
are not working and create no proceeds; a partial fill creates only part of the
proceeds. Reconciliation also repeats the account, UNKNOWN, foreign-activity and
completeness checks so a world change between phases cannot authorize a buy.
The set includes reductions already in flight at the start of this invocation,
including ones created before a restart or by a superseded current-plan
generation. Signed working quantity can make a newly-computed delta zero; it
does not make the proceeds settled. Any durable or observed working SELL keeps
the global increase barrier closed until reconciliation proves the required
sale fully filled (or a later observation/plan establishes that no increase may
depend on it).

**Pre-flight before settle, because refused and deferred are different answers.**
One means "never, on this evidence"; the other means "try again once the
proceeds exist". An increase blocked by FOREIGN_ACTIVITY reported as "waiting to
settle" sends an operator to look at the wrong thing. Survivors are authorised
again against the read they are actually sized from — the first pass classifies,
the second gates.

**When the settle fails, increases are DEFERRED.** §13.1's asymmetry applied to
input quality rather than to time: buying late is opportunity cost, buying wrong
is not. The bound is a cycle count, not a timeout — a sale still working after
it is a sale whose proceeds are not arriving this session, and waiting longer
converts a visible deferral into a hang.

### 13.2 The orchestrator, and its durable pointer

§13 described the sequence; nothing produced it. `sentinel/core/catchup.py` is
the implementation, and two of its properties are load-bearing rather than
incidental.

**The pointer advances with the state, in one transaction — structurally.**
`sentinel_processed_sessions` is one row per cursor, written in the same commit
as the state the session produced.

Saying so was not enough. The seam was `advance_state(session, state) -> state`,
which any in-memory object satisfies — and then the only durable half is the
pointer: a crash after the commit leaves the cursor saying Aug 10 is done while
the durable book still says Aug 9, and Aug 10 is skipped permanently. Two
enforcements, because either alone is escapable:

```text
advance_state(conn, session, state)    receives the transaction, so it CAN be
                                       atomic
_mark_processed(conn, session, state)  persists what it returned in the SAME
                                       STATEMENT as the pointer, so catch-up's
                                       own copy is atomic whatever the seam does
```

The state is JSON with no `default=` coercion: a fallback makes everything
encodable and nothing round-trip, so an unencodable state is refused at the
FIRST session rather than after four hours of replay. `catch_up` rolls back on
any exception — a killed process gets that from the server, a raised exception
on a surviving connection does not.

**The one thing no design here can prevent**, found by mutation testing and so
stated rather than implied: a seam that calls `conn.commit()` itself has made
its state durable ahead of the pointer, and a crash then REPLAYS a session,
double-ageing every episode. What survives is that catch-up's own copy never
disagrees with catch-up's own pointer, so a restart resumes from a coherent pair
and the seam's over-advance is detectable by comparing the two.

```text
pointer written AFTER the whole loop   a crash replays sessions that already
                                       advanced. Wealth Core's state is
                                       path-dependent, so a replayed session
                                       double-ages every episode
pointer written BEFORE the step        a crash SKIPS a session, permanently and
                                       silently. This is the worse one
```

One row keyed by a cursor name, not many rows ordered by timestamp: a wall clock
is not an ordering of trading sessions, and a re-run at 09:00 would look newer
than the session it is behind. The pointer takes `GREATEST` on update, so a
caller replaying an old window cannot rewind the frontier.

**Production names the canonical seams; tests may still inject them.** The paper
preparation path advances canonical v3 state through `advance_and_persist` and
converts the resulting Wealth Core shadow target plus controller exposure
through the production decision adapter. `advance_state` and `decide` remain
parameters of the catch-up kernel so transaction/restart behavior can be tested
with deterministic falsifiers; that injection is not a second production
portfolio or controller implementation. Historical catch-up advances state,
while adoption leaves only the newest plan executable.

### 13.3 External cash is a first-class recovery event

A deposit or a withdrawal changes what is investable. It does not change what
Wealth Core did, it is not strategy P&L, and it triggers no historical replay.

**NAV cannot be its own witness.** The balance moves for two reasons and the
number does not say which:

```text
NAV 100,000 -> 150,000
      |
      +--  a $50,000 wire arrived
      +--  the book was marked up
      +--  a reconciliation break: something is wrong
```

Guess *P&L* and a deposit is +50% in a day, permanently, in every performance
number the system will ever report. Guess *cash flow* and a genuine break gets a
benign label and stops being investigated. Both guesses are silent and neither
is recoverable later, because the evidence that would settle it is the moment
that has passed.

So a flow is **declared** — by an operator, or by a broker activity feed — and
what cannot be attributed stays `UNEXPLAINED`. Three attributions, and the third
is never resolved into one of the first two by default:

```text
MARKET       the move is within tolerance of the marked P&L
DECLARED     a recorded flow accounts for it
UNEXPLAINED  neither does. Recorded as such, durably
```

The tolerance is absolute (cents), not proportional. A percentage tolerance on a
large account silently absorbs exactly the size of discrepancy worth catching.

**Re-projection, not replay.** `catchup.reproject` re-sizes the CURRENT target
against the new NAV and advances no session. `last_processed_session` does not
move. Membership is Wealth Core's business and does not change because money
arrived — exposure scales the basket, never the membership.

**The asymmetry applies to input quality, not only to time.** §13.1 defers
increases when the window is missed. The same rule governs degraded inputs,
because both degrade an order's SIZE without degrading its direction:

```text
marks stale (corpus behind)     reductions proceed, increases refused
NAV UNEXPLAINED                 reductions proceed, increases refused
NAV unobserved (broker down)    NOTHING proceeds — NavUnobserved is raised
```

**A missing mark is not a target of zero.** `project` omits an unpriceable
security rather than sizing it, and omission alone is not enough — for the same
reason publication alone was not. To `compute_delta` an absent basket entry and
a zero are the same thing, so the omission became a liquidation. Two situations
were arriving at one place:

```text
not in weights        Wealth Core no longer wants it   -> SELL ALL. Correct, and
                      it needs no mark: the share count is exact
in weights, no mark   we cannot value it               -> HOLD. No decision
```

A blind security carries `held + committed` as its target — not `held` alone,
since 40 owned with 60 working is a position of 100 in flight. A zero or
negative mark counts as unpriceable, not as a price of zero. And a held security
the target drops now carries an EXPLICIT zero, because a plan that relies on a
reader's default is a plan that does not say what it means.

A withdrawal on a stale corpus still reduces. Doing nothing because the marks
are old leaves the account unable to settle the wire, which is not the
conservative choice it resembles. A withdrawal that cannot be sized at all —
because no NAV was observed — is refused outright rather than sized against a
guess, and the guess would be wrong by exactly the flow that prompted it.

When only part of an intent is permitted, **no plan is emitted** rather than a
reduced one. A plan carrying half of an intent has a fingerprint saying it was
fully satisfied when it was not.

**Cash movement during a partial fill.** A BUY 100 that is 40 filled with 60
working, when a deposit lands and the new target is 150:

```text
naive        new BUY 150  ->  40 held + 60 working + 150 = 250 for a 150 target
exact-delta  remaining = desired - held - committed = 150 - 40 - 60 = 50
```

and the working order is **cancelled and confirmed cancelled**, never silently
superseded. Supersession retires an UNSENT intent; a live order at the broker is
a real obligation, and declaring it superseded abandons it — the shares still
arrive and nothing is expecting them.

---

## 14. Backup restore is an operating mode

A restored database is *expected* to be behind the broker. This is not an
exception path.

```text
validate integrity and certification identity
verify account binding
acquire single-writer lock
enter RECONCILING
recover broker terminal orders since the processed watermark (with overlap)
recover Sentinel-owned commands by client_key namespace
advance missing corpus and strategy sessions
rebuild the current execution target
supersede stale unsent commands
resolve or cancel incompatible working orders
only then ARM
```

A broker order carrying a Sentinel client_key but absent from the restored
database is **recovered history**, not foreign activity, and must not be
duplicated.

The recovery watermark is committed after that history is durable, never when
the broker response is merely recorded. If the process dies after adoption but
before the watermark update, the same closed rows are replayed and adopted
idempotently. If it dies before adoption, the old watermark remains and the rows
are asked for again. Those are the only two crash shapes; neither skips an order.

### 14.1 The information-theoretic limit

If the primary database is destroyed, the backup predates an event, and the
broker no longer exposes enough history to reconstruct it, exact reconstruction
is impossible. No code fixes missing information. This is why WAL archiving to a
second target and periodic verified restore drills are part of the architecture
rather than operations paperwork.

The archive boundary is durable publication, not pathname existence. A WAL
archive command may report success only after a same-directory temporary copy
has matched the completed source in size and content, the file has been
fsynced, a no-clobber atomic rename has published it, and the destination
directory has been fsynced. An already-published name is idempotent only when
its size and bytes exactly match the source; a partial or different object
fails closed. This prevents a failed copy from becoming false evidence that a
segment is recoverable and then allowing PostgreSQL to recycle its only good
source.

---

## 15. Certification

### 15.1 Layered claims

Certification is not one green number. Each layer makes a different claim:

```text
core                Wealth Core semantics are exact
controller          frozen input → exact transition output
data normalization  Sharadar rows → the certified price/identity/action domains
persistence         restart/snapshot/migration preserve deterministic state
execution projection shadow + exposure + basis → correct desired basket
execution machine   every crash/timeout/partial/supersession path converges
alpaca adapter      transport conforms to the contract
ibkr adapter        independently conforms
deployment          image, config, schema, data contract are the certified ones
resource envelope   all of the above inside the NAS limits
disaster recovery   restore converges to correct broker + strategy state
```

### 15.2 The simulator certifies the contract, not a broker

> **The broker simulator is a conformance oracle for the contract, not an
> emulator of Alpaca.**

Consequences, and they are the reason this distinction is worth stating:

- the execution-state-machine tests are broker-independent and run **once**, not
  per adapter;
- per-adapter suites become *mapping proofs* — "this IBKR reply-confirmation
  prompt maps to `ACKNOWLEDGED` / `UNKNOWN` / `REJECTED` under these conditions"
  — adjudicated against the contract rather than against the adapter's own
  behaviour;
- the simulator **must** be able to emit contract-legal states that no real
  broker happens to produce. If its state space is the union of what Alpaca and
  IBKR actually do, it is an emulator again and the contract is only as strong as
  the messiest adapter.

Fault modes it must produce on demand:

```text
accept-then-timeout          never-received            duplicate retry
partial fill                 fill between observations cancel race
outage and recovery          truncated history         foreign activity
reject                       dust residual             identity change
```

### 15.3 Crash injection

For every financially meaningful transition, kill the process at the boundary and
assert the resumed state is economically identical:

```text
before command reservation      after reservation commit
before broker send              after broker accepts, before response
after response, before local update
after first partial fill        while cancellation is pending
after final fill, before reconciliation
after snapshot, before plan     during corpus publication
```

### 15.4 Resource envelope

Container memory limits are set **early and generously**, and tightened to the
real envelope at the end. Nothing between the executor and the adapter suites is
certified in an unbounded environment — that is how the 8b OOM ended up inferred
rather than measured, and it is the same shape as the pipeline crash-loop in
Stocker's history. Enforcement early, calibration late.

---

## 16. What is explicitly NOT carried forward

```text
delta_intents / net_intents      Sentinel has one shadow target and one scalar
trade-executor                   replaced by the command state machine
risk-service (as a service)      replaced by the in-process permission kernel
alpaca-sync (as a service)       replaced by observation + reconciliation
target-portfolio sizing          replaced by the execution projection
generic dict/tuple broker API    replaced by the typed contract
broker-native close (autonomous) replaced by exact-delta commands
```

Stocker's execution defects are carried forward as **hostile test cases**, not as
an implementation backlog.

---

## 17. The invariants this document adds

Numbered from 15 to continue `sentinel-architecture.md` §12.

```text
15  Every broker side effect has a deterministic identity derived from durable
    state, persisted before the network call.
16  An uncertain broker outcome is UNKNOWN, never FAILED.
17  A retry reuses its identity. Only a resolved supersession mints a new one.
18  While a security has an UNKNOWN command, no overlapping command is created
    for it.
19  Cancellation is confirmed by observation, never by an API return value.
20  Observations declare completeness; irreversible conclusions require COMPLETE,
    and two consecutive agreeing ones.
21  Orders are observed before positions, and the orders are re-read afterwards;
    a disagreement makes the observation INCONSISTENT, which authorises nothing.
22  Certified autonomous execution never calls broker-native close.
23  Quantities are decimal end to end; a sub-increment residual escalates and is
    never retried in a loop.
24  Corporate actions covering a gap are applied before any foreign-activity
    classification.
25  Missed execution windows are never replayed retroactively.
26  Exposure-increasing action requires strictly stronger evidence than
    exposure-reducing action.
27  The corpus is published atomically under a monotonic version; the engine pins
    one per session; decisions record it.
28  Account binding and takeover epoch are verified before any command.
29  Unsupported broker capabilities fail closed; they never silently degrade.
30  A restored backup is assumed stale relative to the broker; Sentinel-keyed
    broker orders absent locally are ADOPTED into the journal, never merely
    reported and never duplicated. Identifying a recovered order without storing
    it leaves the position permanently unexplained — able to de-risk, never able
    to re-risk.
31  A broker status is classified by whether a trade can still occur under it,
    never by whether it sounds finished; an unmapped status raises.
32  The executor's quantities come from the plan plus, only for a scalar
    corporate action, its immutable action-aged target-projection record. A
    stored client key may never be rebuilt with different economics.
33  The long-only, unlevered envelope is asserted at the execution gate, not
    inherited from whatever produced the plan.
34  The single-writer lock is acquired inside the public execution entry point,
    not left to the caller.
35  A corporate action's raw calendar date snaps forward to its first exchange
    session, then resolves its ticker only on that exact published session;
    tickers are recycled. An executable equity split uses that bar's published
    canonical effective ratio, never the unoriented ACTIONS value.
36  PUBLISHED IS WHAT READABLE MEANS. A row written by an ingest that no corpus
    publication represents is invisible to every reader. A corpus BEHIND its
    version is detectable; one AHEAD of it is not.
37  Rows that no publication represents are REPORTED as well as hidden. Hiding
    alone freezes the corpus silently at the last published version while the
    fetch appears to be working.
38  Freshness is measured in SESSIONS against the exchange calendar, never in
    calendar days. A day budget wide enough for a holiday weekend also hides a
    three-session outage inside an ordinary week.
39  Unevaluable is never fresh, and neither is a frontier the exchange cannot
    account for.
40  No stage of an ingest holds more than a batch of vendor rows. The chunk sort
    happens in PostgreSQL, which has bounded memory and a disk to spill to.
41  The catch-up pointer is durable and advances in the SAME TRANSACTION as the
    state the session produced. It never moves backwards.
42  A catch-up emits exactly ONE execution intent, and it is the newest.
43  External cash is DECLARED, never inferred from a balance. An unattributable
    NAV move is UNEXPLAINED — never silently P&L and never silently a flow.
44  A cash flow triggers a RE-PROJECTION of the current target and never a
    replay. No session advances because money arrived.
45  Degraded inputs follow the missed-open asymmetry: stale marks or an
    UNEXPLAINED NAV permit reductions and refuse increases; an unobserved NAV
    permits nothing. Partial authorisation emits NO plan rather than a reduced
    one.
46  An increase is sized against an observation taken AFTER the reductions
    settled. Submitted is not settled.
47  Settled means no reduction is still WORKING and the read that established
    it was COMPLETE. An unsettled reduction defers every increase.
48  Refused and deferred are different answers. An increase that can never be
    authorised on this evidence is refused with its own reason, before any
    settle is spent on it.
49  An operator page READS a verdict; it never computes a contract. The check
    reads the corpus, so any timeout short enough to protect a page load is
    short enough to lose under exactly the ingest that makes the answer
    urgent.
50  A stored verdict is shown with its AGE. "Never measured" is not "not
    ready", and a stale PASS is reported as stale rather than downgraded to a
    failure or presented as current.
51  While a session holds the corpus pinned, the ROWS that pin names do not
    change. An ingest holds the same key exclusively for its whole duration;
    freezing the version number while the rows move is not a snapshot.
52  A security that is still wanted and cannot be priced HOLDS its current
    quantity. "We cannot value this" and "we want none of this" are different
    facts and only the second is a reason to sell.
53  A held security the target drops carries an explicit zero. Absent and zero
    are the same to a delta calculation, so a plan must not rely on the
    difference.
54  The catch-up seam receives the transaction, and catch-up persists the state
    it returns in the same statement as the pointer. A state that cannot be
    encoded is refused before the first session advances.
55  A decision-close-to-open scalar corporate action reprojects share units in
    an immutable record; it never edits plan intent. Non-scalar or incomplete
    terms fence execution and never create a compensating broker ledger.
56  Every effective-session invocation with a nonempty target, holding or
    commitment has affirmative, immutable pre-open share-unit authority
    covering its exact active permanent-identity set. Equal nonzero raw share
    counts do not prove no event; source silence never means multiplier 1. Only
    an all-zero empty book bypasses, and a zero-only BIL key is not coverage.
57  Once an adapter has accepted a broker close valuation, persistence binds
    that typed historical source point to the exact account and XNYS session.
    Production source-semantics promotion remains a separate acceptance gate; a
    local request bracket or current account balance is not such authority.
58  Close cash uses a plan baseline only when its append-only broker activity
    identity scheme is explicit and unchanged. A missing plan-time baseline is
    never backfilled from current state. Equal cumulative cash totals do not
    prove an unchanged event set: offsetting cash events still refuse.
59  A complete account-wide broker fill interval, not the command recovery
    cache, proves the close book. It starts at the plan cash boundary, reaches
    the close and later observation, retains native activity/order identities,
    and refuses every foreign, mislinked, missing, or post-close fill.
60  A successful cycle with missing or future close/fill source evidence stays
    pending and cannot be superseded. That obligation is caller-independent and
    stays bound to the old plan's effective session during manual or delayed
    preparation. Complete evidence that economically disagrees freezes an
    immutable `NOT_VERIFIED` verdict.
61  Shadow observation and paper execution have separate machine verdicts.
    SHADOW_GO authorizes only a broker-free canonical state transition after
    source publication. It never implies PAPER_EXECUTION_GO, never authorizes a
    broker mutation, and never makes Alpaca dashboard P/L a verified result.
62  Decision-close target reprojection preserves canonical order provenance.
    Splits may create fractional held or pending-close entitlements, subject to
    the broker's certified increment, but a pending OPEN that Wealth Core would
    cancel as non-integral contributes exactly zero to the executable target.
    Fractional-order support can never turn that cancelled entry into a buy.
63  Trial account evidence binds the exact durable v2 target projection used by
    execution. Its close target equals that projected basket, including pending
    OPEN cancellations, and later observation aging begins strictly after the
    projection boundary; flat plan-target aging cannot earn verification.
64  A canonical book cannot cross a Sharadar interpretation change. Its exact
    strategy identity binds the versioned data-semantics source bundle as well
    as Wealth Core/controller code. Missing or changed semantics identity
    refuses state restore, catch-up, planning and execution; a later
    `data_version` is not permission to launder an older path-dependent book.
```

Every one of these is falsifiable, and each should fail a test when violated.
