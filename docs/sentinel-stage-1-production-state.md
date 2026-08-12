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

## Deliberate Stage 2 boundary

Stage 1 produces and atomically persists the latest shadow/controller decision.
It creates no execution plan, submits no broker command, and adds no scheduler.
Stage 2 must project the latest shadow basket by `target_core_exposure`, add the
defensive sleeve, stamp the execution identities, and hand the result to the
existing journal/executor under freshness and ownership gates.
