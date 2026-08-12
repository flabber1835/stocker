# Sentinel production path — Stage 1 implementation record

## Reuse decision

Stage 1 reuses the canonical `PortfolioState`, `PendingOrder`, `Ledger`, `Feed`,
`SecuritySeries`, `SecurityMeta`, `VendorBar`, `TerminalTerms`, and
`wealth_core.live.plan_session` types. The resulting envelope is stored through
the existing `sentinel_processed_sessions.state` JSONB column by the existing
`catch_up` transaction. Execution plans and command journals remain untouched
until Stage 2.

The envelope adds no parallel portfolio model. Its `wealth_core`, `pending`,
`ledger`, and `feed` members are the existing types' restart representations.
It adds only composition-owned history: controller state, shadow NAVs, damaged
breadth history, publication version, strategy/config hashes, the last decision,
and its evidence.

## Changed production surfaces

* `sentinel/core/production.py` — versioned envelope, published-session loader,
  holdings adapter, one-session composition, and catch-up callback.
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

Wealth Core trailing-stop exits in the previous 20 sessions are durable
controller evidence.  They are recorded by session in the envelope rather than
reconstructed from the current book, because the exited episode is no longer
present after the evidence is created.  The boundary is exact: two stops remain
healthy evidence for `BinaryStress`; three do not.

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
fresh start.  Envelope version 2 introduces the lifetime peak and durable stop
history.  Version 1 is explicitly refused because neither value can be safely
inferred: rebuilding a peak from its truncated 64-session history would loosen
risk, and reconstructing departed stop episodes from the current book is
impossible.

## Deliberate Stage 2 boundary

Stage 1 produces and atomically persists the latest shadow/controller decision.
It creates no execution plan, submits no broker command, and adds no scheduler.
Stage 2 must project the latest shadow basket by `target_core_exposure`, add the
defensive sleeve, stamp the execution identities, and hand the result to the
existing journal/executor under freshness and ownership gates.
