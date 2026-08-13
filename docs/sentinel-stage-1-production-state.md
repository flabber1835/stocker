# Sentinel production path — Stage 1 and Stage 2 implementation record

## Reuse decision

Stage 1 reuses the canonical `PortfolioState`, `PendingOrder`, `Ledger`, `Feed`,
`SecuritySeries`, `SecurityMeta`, `VendorBar`, `TerminalTerms`, and
`wealth_core.live.plan_session` types. The resulting envelope is stored through
the existing `sentinel_processed_sessions.state` JSONB column by the existing
`catch_up` transaction.

The envelope adds no parallel portfolio model. Its `wealth_core`, `pending`,
`ledger`, and `feed` members are the existing types' restart representations.
It adds only composition-owned history: controller state, shadow NAVs, damaged
breadth history, publication version, strategy/config hashes, the last decision,
and its evidence.

Stage 2 keeps that same version-3 `SessionState` as the only behavioral state.
It connects the latest canonical shadow/controller decision to the existing
`ExecutionPlan`, journal, reconciliation, and executor components. Broker
observations remain execution evidence only; they do not feed Wealth Core or
the controller.

## Changed production surfaces

* `sentinel/core/production.py` — versioned envelope, published-session loader,
  holdings adapter, one-session composition, and catch-up callback.
* `sentinel/core/decision.py` — production shadow-to-share adapter, including
  committed pending entries/exits, controller exposure, BIL/cash treatment,
  unavailable-price preservation, and immutable plan identity.
* `sentinel/paper.py` — paper-only preparation, durable current-plan
  inspection, and the separately confirmed execution gateway.
* `sentinel/__main__.py` — explicit preparation, current-plan inspection, and
  paper-execution commands. Exact operator invocations live only in
  `docs/sentinel-paper-activation.md`.
* `sentinel/controller/machine.py` — the production `step` that derives the
  parent severe state from observations instead of consuming an oracle parent
  allocation.
* `sentinel/feed/{schema,staging,domains,store,universe}.py` — a narrow
  `closeadj` transport into a dedicated SPY-only published table and persisted
  sector metadata. `closeadj` never enters `VendorBar` or Wealth Core.

## Resolved architecture differences

The standalone holds vectorized history in numpy arrays; production persists
the canonical Wealth Core objects and the minimum rolling histories needed by
breadth/controller. The standalone reads `TICKERS.sector` and `SEP.closeadj`
directly; production now preserves sector and puts SPY total-return closes in a
separate table, behind the corpus publication visibility boundary.

The frozen transition tape supplies a parent allocation to the certification
entry point. Production may not do that. `Controller.step` therefore computes
fast/slow parent state from typed evidence and only then applies the existing
1.1 recovery ramp. The frozen rule JSON remains a digest-verified runtime
configuration artifact; no oracle CSV or standalone output is read.

## Production-state semantics (decided 2026-08-12)

The production envelope persists the **lifetime** Wealth Core shadow high-water
mark.  Shadow drawdown is always current shadow NAV divided by that durable
peak; a rolling NAV-history window must never reset the controller's loss
anchor.  Rolling NAV history remains only for return features.

The production parent controller is a transcription of the state machines in
`docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`, not a new
interpretation of the frozen-rule prose.  In particular, production preserves
the exact `BinaryStress`, base-mode `FastState`, parent-mode `FastState`, and
`SlowState` ordering: armed/rearm happens before entry, binary stress prevents a
base-fast entry on that close, dwell clocks retain their distinct inclusive
semantics, and slow recovery occurs on the sixth healthy observation after five
already-established confirmations.  The already-certified Sentinel 1.1 ramp
remains unchanged and consumes the resulting parent transition.

Wealth Core trailing-stop exits in the current controller session plus the
preceding 19 controller sessions are durable controller evidence.  They are
recorded by session in the envelope rather than reconstructed from the current
book, because the exited episode is no longer present after the evidence is
created.  The boundary is exact: two stops remain healthy evidence for
`BinaryStress`; three do not.

`stops20` counts **executed** Wealth Core trailing-stop exits, never
close-time intents.  A trailing stop detected on session *t* creates a pending
SELL and contributes no stop evidence until that SELL fills at a later
executable open.  A pending trailing-stop exit that cannot execute remains
pending and contributes no evidence; if it fills several controller sessions
later, it is counted on that actual fill session.  The production transition
captures the ledger boundary immediately before planning and considers only
new ledger events for its published session whose typed event is `SELL` and
whose canonical reason is `EXIT_TRAILING_STOP`.  Multiple completed fills on
one session are retained individually.  Evidence expires exactly when its exit
session is 20 controller sessions behind, never by calendar-day arithmetic.

Missing stop evidence is `UNAVAILABLE`, never zero.  BinaryStress recovery
therefore needs an available nonnegative `stops20` at or below two alongside
its positive `shadow_r20`; unavailable or invalid stop evidence resets the
healthy streak.  Slow-entry evidence likewise retains named predicate results
for stress duration, return since the base-stress anchor, `shadow_r40`,
damaged breadth, and green breadth.  A missing input yields
`SLOW_EVIDENCE_UNAVAILABLE` naming the predicate rather than an ordinary
negative.

A production session owns one corpus publication pin for the complete input and
state transition: published input loading, Wealth Core advancement, breadth
calculation, and controller transition all occur while that same pin is held.
The loaded `data_version` must equal the yielded pinned version.  Loading under
one pin and calculating after releasing it is forbidden even if publication is
normally atomic.

The envelope carries a deliberate schema version and the identity of the
strategy, frozen controller rule, and canonical Wealth Core source.  Before any
state is advanced, all three persisted identities must exactly match the
running code/configuration.  A mismatch is refused; it is never treated as a
fresh start. Envelope version 2 introduced the lifetime peak and durable stop
history. Version 3 bounds restart feed/evidence history while retaining every
path-dependent security anchor; version 2 migrates deterministically to that
shape on load. Version 1 is explicitly refused because neither its missing peak
nor departed stop episodes can be inferred safely.

## Stage 2 production handoff (implemented 2026-08-12)

The production adapter now aggregates the canonical filled shadow episodes and
committed pending entries/exits by permanent security id, applies the durable
controller exposure, keeps Wealth Core cash distinct from the defensive sleeve,
and projects the result to whole `Decimal` shares through the existing
execution projection. Missing marks preserve still-wanted observed quantities;
they never become an implicit liquidation. BIL is defensive-only, and an
unpriceable BIL sleeve remains cash while any committed BIL quantity is
preserved.

Preparation loads or creates the canonical state, performs a 252-session
feature warm-up on fresh boot, advances every missed XNYS session through
`advance_and_persist`, and transactionally adopts exactly one latest plan.
Historical sessions update state only; their plans are superseded. Preparation
may read the paper broker for account and reconciliation evidence, but it has no
broker submit, cancel, replace, or close operation.

Current-plan inspection reads only PostgreSQL. The separate execution gateway
reloads the durable current plan itself, repeats paper URL, certification,
ownership, account, readiness, publication, frontier, state, session, and
reconciliation checks, then delegates to the existing executor. Reductions run
before increases; increases wait for filled reductions and a fresh complete,
clean re-observation and re-sizing pass.

## Operational boundary after Stage 2

This is an implemented, reviewable activation path; it is **not an activated
deployment**. Alpaca paper remains the only permitted endpoint. The certified
adapter submits operator-timed DAY market orders, not market-on-open orders.
There is no scheduler or long-running engine service: preparation and execution
remain separately invoked operator actions, and ordinary Compose startup cannot
perform either one. No legacy migration or paper-order submission is authorized
by this implementation record. The sole operator sequence and checkpoints are
in `docs/sentinel-paper-activation.md`.
