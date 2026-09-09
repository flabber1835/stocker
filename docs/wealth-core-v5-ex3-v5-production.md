# Wealth Core V5 with Sentinel EX3 V5: production promotion

## Owner decision and authority

The owner selected Wealth Core V5 and **Sentinel EX3 V5, R40 -4% / REC8**
on the **broad Sharadar universe**. The controller arm is `r40_m04_rec8`.
The reference is Actions run `34319850800`, artifact `10092241309`, experiment
commit `54af0c9e50e4bf0c0d4242dafcf7fff0b75eb0f3`. The source manifest on
research commit `b0c80cfb44bc419b9081420f0a7c98088623b3d6` documents that arm.
This explicit owner decision supersedes the research recommendation of -5%.
The V6 structural experiments are separate research and are not this profile.

Implementation starts from verified main
`df4683b8bf1c80453b8f542f4e3ed441387ad3f5`, on
`codex/wealth-core-v5-ex3-v5-production`. The relevant Median-5 port and its
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
* Sentinel EX3 V5: REC=8, recent R20 divergence threshold -8.5%, SPY rebound
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

## Status

Implementation and verification in progress. No production equivalence PASS
or main delivery is claimed by this initial design record.
