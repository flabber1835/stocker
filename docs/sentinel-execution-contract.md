# Sentinel — the execution and recovery contract

> **Status: DESIGN SETTLED, implementation in progress.** This document is the
> source of truth for how Sentinel talks to a broker, what it persists before it
> does, and how it recovers when any of it goes wrong. It supersedes nothing in
> `sentinel-architecture.md`; it fills the layer that document leaves open below
> "execution projection".
>
> Read `docs/sentinel-deployment.md` first for operational ground truth, then
> `docs/sentinel-architecture.md` for the strategy/controller architecture, then
> this.

The architecture document settles what Sentinel *decides*. This one settles what
happens between a decision and a share moving, and — more importantly — what
happens when that process is interrupted, duplicated, or resumed from a backup
that is behind the broker.

---

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

### 4.4 What is exempt

**The one-time account migration is an administrative act, not autonomous
execution**, and may use broker-native close. It is operator-invoked, runs once,
and its whole purpose is to remove a book Sentinel did not create and will never
reason about again. Requiring it to be rebuilt on the new command model before it
can be used would put a rewrite in front of a safety fix for no gain.

Operator/emergency tooling is likewise exempt, and must be labelled as such.

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

`AlpacaBrokerAdapter.list_orders` issues a single `GET` with `limit=500` and
`direction=desc` and no pagination. Truncation therefore drops the *oldest*
orders — precisely the stale resting ones most likely to be forgotten. On the
path that decides "the account is flat", a bounded read was answering an
unbounded question.

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
```

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

`sentinel/feed/schema.py` has no `data_version`, no publication identity and no
revision dimension; `sentinel_bars` is keyed `(security_id, session)` and written
by a destructive upsert. **The invariant is adopted and unimplemented.** A
Sharadar restatement currently rewrites, in place, the evidence underlying a
decision that has already been recorded.

### 8.1 Two tiers, and which one is being built

```text
DETECTION       "this decision read v47; the corpus is now v52, so a replay
                 may not reproduce it"                        ← BUILD NOW
RECONSTRUCTION  "show me exactly what v47 contained"          ← DEFERRED
```

Detection is what makes a divergence report interpretable — it separates "the
broker drifted" from "the history moved", which is the question
`sentinel-architecture.md` §5 actually poses. Reconstruction requires revision
history and is a much larger build; it is deferred to the end of the sequence.

### 8.2 The publication record

An ingest *run* is not a corpus *version*. A run that fails halfway has a
`run_id` and must never be citable as a version.

```text
corpus_publications
    version           BIGINT, monotonic
    previous_version  the chain; a gap means rows were written but never published
    run_id            which ingest produced it
    published_at
    evidence          row counts, window, digests
```

Rules:

```text
the row is written ONLY after validation passes
readers resolve "current version" through this table, never by observing rows
the engine PINS a version at session start and treats the corpus as frozen
ingest MUST NOT publish while a session is being processed
```

The last two matter more than they look. Without them a decision stamped `v52` is
only approximately true, and approximately-true provenance is worse than none —
it will be believed.

Bars, actions and universe rows additionally carry `last_written_run_id`, which
is nearly free (`write_bars` already runs inside an `IngestRun`) and answers
"which ingest produced this value" without any revision history.

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

Reconciliation therefore loads `sentinel_actions` for the entire gap interval and
applies the implied share-count and identity changes to its expected book
*before* comparing against the broker.

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
then run an explicit adopt-restored-account, which increments takeover_epoch
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

---

## 14. Backup restore is an operating mode

A restored database is *expected* to be behind the broker. This is not an
exception path.

```text
validate integrity and certification identity
verify account binding
acquire single-writer lock
enter RECONCILING
recover broker orders and fills predating the checkpoint
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

### 14.1 The information-theoretic limit

If the primary database is destroyed, the backup predates an event, and the
broker no longer exposes enough history to reconstruct it, exact reconstruction
is impossible. No code fixes missing information. This is why WAL archiving to a
second target and periodic verified restore drills are part of the architecture
rather than operations paperwork.

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
    broker orders absent locally are recovered, never duplicated.
```

Every one of these is falsifiable, and each should fail a test when violated.
