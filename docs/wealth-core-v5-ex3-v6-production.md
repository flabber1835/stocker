# Wealth Core V5 with Sentinel EX3 V6: production promotion

## Owner decision and authority

The owner selected Wealth Core V5 and **Sentinel EX3 V6, R40 -4% / REC8**
on the **broad Sharadar universe**. The controller arm is `r40_m04_rec8`.
The naming authority is `docs/sentinel-ex3-v6.md` from PR #341,
commit `ff60fff989dc1fd96bf15b30a3fad8d69573557b`. The owner clarified that
the earlier description “V5 configured with -4% / REC8” refers to V6. The
implementation already used that exact generated source; this changes its
production name and identity, not the selected research economics.
The reference is Actions run `34319850800`, artifact `10092241309`, experiment
commit `54af0c9e50e4bf0c0d4242dafcf7fff0b75eb0f3`. The source manifest on
research commit `b0c80cfb44bc419b9081420f0a7c98088623b3d6` documents that arm.
This explicit owner decision supersedes the research recommendation of -5%.
Other structural experiments with V6 in their branch name are not this profile.

Implementation starts from verified main
`df4683b8bf1c80453b8f542f4e3ed441387ad3f5`, on
`codex/wealth-core-v5-ex3-v6-production`. The relevant Median-5 port and its
independent comparison harness are reused from PR #333 at
`98079c6b4e28a9f5d23ccb00f1228edff6798041`. That PR remains unchanged.
Delivery is a reviewed pull request targeting main. The owner retains merge
review. Runtime activation and account operations retain their existing gates.

## Frozen economics

* Wealth Core: Median-5 ranking; 20 slots; 5% intended entry capital; one
  steady-state admission per session; 30% trailing stop; the existing
  119-session review and 21-session slot/security cooldowns.
* Admission: require cash above 10 bp of close NAV to be positive (research
  epsilon 1e-12), then require total cash plus 1e-12 to cover one share at the
  known raw close including the existing 10 bp per-side cost. These are
  separate predicates. Outstanding dividend receivables contribute to NAV,
  and only settled cash funds an entry. Dividend settlement lag is one session.
* The close reserves the slot/security and records intended dollars equal to
  5% of close NAV. Share quantity is unbound. At the opening boundary, sells
  execute before buys, and a buy uses
  `floor(max(0, min(intended_dollars, current_cash)) / (raw_open * 1.001))`.
  The close cushion is released into the funding pool. Entry fills are whole
  shares; splits may create fractional holding quantities.
* Invalid-market and zero-quantity entry attempts must be evidenced and release
  their reservations according to the frozen reference. Exits retain the
  canonical recovery and pending-order behavior. The exact invalid-open
  lifecycle is included in the differential and boundary tests.
* Sentinel EX3 V6: REC=8, recent R20 divergence threshold -8.5%, SPY rebound
  threshold +11%, shadow DD threshold -10%, divergence SPY floor 0%, divergence
  ceiling 55%, native FAST damaged breadth 88%, healthy damaged ceiling 63%.
  Full recovery requires positive recent-leadership R20 and recent-leadership
  R40 **strictly greater than -4%** for eight qualifying sessions. The same
  counter clears the divergence latch. Existing cross-surface and SPY-rebound
  release routes retain their exact reference semantics.
* Universe: the canonical broad PIT common-equity population and its existing
  causal eligibility/liquidity rules. There is no S&P 500 membership filter.

## Ownership, state and identity

The existing canonical Wealth Core book remains the sole owner of holdings,
cash, pending intent, terminal entitlements, and cooldowns. The established
Median-5 feature engine supplies ranking and mixed-precision numerical state.
The new V5 profile is explicit in configuration and strategy hashes. Historical
Median-5 and other profile identities retain their meanings.

Pending V5 entries persist intended dollars across serialization and declared
corporate actions. A split changes share units and prices, not dollar intent.
Old close-sized pending orders cannot be accepted under the V5 identity.
The canonical portfolio additionally persists its V5 `entry_sizing_profile`.
Loading or advancing V5 requires that marker even when the pending queue is
empty; replacing only the strategy identity cannot migrate a Median-5 book.
Fresh V5 state is selected consistently by paper preparation, shadow runtime,
authority construction, and automation. Restoring an old book under a new
identity is refused; ordinary startup never relabels or resets it.

Sentinel reads strategy observations and emits exposure only. It does not read
broker holdings, cash, or fills. Execution remains the sole broker-facing
layer, with its existing Decimal, long-only, unlevered and recovery guards.
Research source is an independent test oracle and has no production import.

## Verification and acceptance

The immutable broad PIT dataset hash is
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Replay begins 2006-01-03; measurement is 2006-07-31 through 2026-07-31,
5,032 measured sessions. The selected reference's Wealth Core hashes are:

* core tape: `3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f`
* transactions: `0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da`
* close decisions: `d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724`

Pin the generated reference bytes, normalized AST, dependency tree, dataset,
and executed production source. Independently advance production on raw
published-session inputs and compare eligible/ranked populations, admissions,
pending dollar intents, fills, holdings, cash/receivables, opening/closing NAV,
breadth, controller decisions, effective exposure, and scalar reference NAV.
Periodic JSON restart comparisons must match uninterrupted production.
Preserve the inherited declared monetary/ratio and fractional-split tolerances;
integer fills and discrete decisions require exact agreement.

Boundary tests cover total-cash affordability (AGN1), true unaffordability
(AMZN), a positive reserve boundary, opening gaps in both directions, released
reserve funding, invalid opens, zero fills, pending-intent restart/splits, and
R40 strictness with REC7/REC8 boundaries. Mutate guards to demonstrate failures.
Run directly relevant component tests and the release safety workflow. Review
adjacent identity, persistence, warm-up, authority and execution paths.

Research scalar NAV equivalence and broker execution are separate claims. The
inherited opening audit records carried prices and leaves production's strict
opening-equity result intact. A partial replay cannot produce a full-PIT PASS.
Failures retain the first divergent session and concrete diagnostics.

## Opening-time paper integration

Opening sizing is part of the owner's V5 implementation instruction. Execution
plans retain typed canonical entry dollar intents and slot order, together with
zero provisional share targets for those entries. The plan fingerprint includes
the intents. The existing `sentinel_processed_sessions` journal stores the
versioned `plan-opening-intents:v1:<plan_id>` record atomically with plan adoption.
This uses the repository's established cursor mechanism and preserves its sealed
behavioral schema. The record binds the full plan fingerprint and effective
session. Deterministic plan IDs must match reconstructed economics, so a lost
intent record refuses reload. Historical share-only plans retain their identities.
Paper entry points translate journal identity refusals into their existing
`PaperActivationRefused` contract before broker reads.

At the effective session, execution reads raw SIP bars for the first regular
session minute from Alpaca's market-data endpoint. The read starts after that
minute completes and requires the exact XNYS opening timestamp, requested symbol
identity, positive open and volume, and complete response coverage. Unavailable
or malformed evidence defers execution. The read passes through the broker guard.
The endpoint contract is [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars).

A pure execution projection resolves the canonical pending entries in slot
order from the immutable shadow cash, due receivables and pending exit proceeds,
using the observed opening prices and V5's 10 bp costs. It applies the existing
account-NAV / shadow-NAV scale and Sentinel exposure to the resulting whole-share
core targets. Prices, funding calculation, resolved quantities and the original
plan fingerprint are persisted once in the target projection. Retry and recovery
reproduce that projection from the retained evidence. Direct execution of a plan
with unresolved dollar entries is refused. Deferred entry submissions follow
canonical slot order after reductions settle. Existing holding adjustments keep
their stable security order. An all-zero provisional basket containing dollar
intent requires affirmative pre-open authority; it cannot use the empty-book
no-op path. Incomplete price evidence is a retryable paper refusal.

This projection expresses the canonical opening intent in account share units.
It creates no canonical holdings or fills. Sharadar remains the source for Wealth
Core and Sentinel. The executor retains its reduction-settlement barrier and
fresh cash-only account authority before increases. DAY market fills remain
broker observations; a price move after the opening print can affect fills and
the cash-only account may reject an unaffordable order. Those observations never
change canonical strategy state.

Pre-open corporate-action coverage includes every deferred entry and pending
exit that funds it. Scalar actions transform share quantities and raw price
units; dollar intent is invariant. Material non-scalar actions retain the
existing refusal boundary. A zero exposure target requires no entry price read.

Acceptance adds price-domain/timestamp/coverage falsifiers, opening gaps, split
units, funding and whole-share limits, immutable plan/projection persistence,
restart after submission ambiguity, and the existing broker conformance gates.

The historical paper-decomposition manifest retains its original source and AST
hashes. Explicit successor records name this design for the changed target,
preparation, execution and validation definitions. New opening-price and journal
refusal helpers are recorded as introductions. The ownership test allows this
specific successor design and checks every current AST; economic golden fixtures
retain their original values.

## Status

Review correction: an adopted opening-intent plan may survive a restart before
its projection is persisted. After complete command reconciliation, an absent
projection is resumable only when the exact plan has no durable commands.
Recovery records no financial completion for that state. Automation returns it
to opening sizing inside the execution window, or supersedes it after close.
Any command for the plan makes a missing projection an integrity refusal.
Both dual and normal execution use the persisted projection for convergence;
zero provisional targets containing dollar intent cannot certify an empty no-op.
Split coverage retained during sizing also participates in finalization.
Opening asset/bar transport timeouts and HTTP 429/5xx remain retryable evidence
unavailability; authority and identity refusals retain their terminal meaning.

Historical conformance correction: published split-adjusted signal closes feed
the V5/Median-5 feature rings and leadership witness directly, as in the frozen
reference. Adjacent split records cannot infer another adjustment of those
prices. ABV's 2013-11-11 published signal is 7.44, not the port's inferred 37.20.
Raw execution prices, split share adjustments, ranking formulas, and V6
controller parameters retain their reference contracts.

The deterministic core/controller port and opening-time paper projection are
implemented and under verification. The atomic plan-intent record and versioned
projection retain the original dollar intent, price evidence, and final Decimal
quantities through journal reload and submission recovery. The earlier temporary
entry-extraction refusal is superseded by this opening-time contract.

The selected controller also requires CONTROLLER rollout: PINNED_1_00 must not
silently override EX3 V6's selected exposure. Historical identities retain their
existing rollout rules. Delivery remains draft until the full-PIT and
release-safety gates pass for the completed source revision.

Local opening-integration verification passed 244 targeted tests across V5,
Median-5, production planning, broker guards, target reprojection, and Alpaca
boundaries; 146 PostgreSQL cases required CI. All 17 reviewed V5/opening mutants
were killed. The prospective Wealth Core suite previously passed 762 tests with
the same three documented historical deselections as CI. The preceding V6 source
revision passed the complete container/PostgreSQL safety workflow on both the PR
head and synthetic merge. Full-PIT equivalence and the completed revision's
container/PostgreSQL safety workflow remain required.
