# Core/Sentinel matching: synthetic market pipeline extension

Registered before this extension's results, 2026-09-21. Production base remains
`da7b64a9429c9c73fb7efac90c8d4a5decb39e13`; this extends research PR #431.
Read `core-sentinel-impedance.md` for the preceding component experiments.

## Design and scope

Generate sixty synthetic common equities and a synthetic SPY series on real
XNYS dates. No historical prices, corporate-action data, reference exposure or
performance targets are loaded. Price formulas below are experimental stimuli,
not estimates of a market-return distribution. Dates only provide a valid
calendar. Declared metadata, positive volume, identity and prices are supplied
at the PublishedSession seam; database ingestion/publication and brokers are
not under test.

Run 252 sessions through production feature-only warmup, then 80 production
kernel sessions to form the actual twenty-slot Core and controller histories.
Starting capital is $100,000. Clone this common state for each 120-session path.
Production `advance_session` owns candidate selection, fills, cash, stops,
cooldowns, reviews, breadth, market observations, Native and Candidate A.
No holdings, classifier outputs, trigger values or source identities are edited
to cause a desired result. The rotation/staggered scenarios may use the fixed
held cohort known BEFORE the branches, never subsequent decisions or P&L.

### Prespecified scenario shapes

The common formation market has modest positive drift, a common periodic return
component and id-specific periodic components. These produce nonconstant
volatility and residual-peer inputs, unlike the prior flat-history probes.

- Healthy continuation.
- Synchronized equity shock: 18% one-session equity drop with 8% SPY drop;
  ordinary positive drift resumes.
- Staggered deterioration: four-fifths of the initial holdings lose roughly 1.2%
  per session for fifteen sessions; other stocks maintain their generated
  returns. On the sixteenth session the already-damaged cohort loses another 8%
  and the other names lose 18%, alongside an 8% SPY drop. The formula is an
  adversarial timing probe, not fitted to the historical 2011 case.
- Gradual decline: subtract 0.4% from daily stock returns for eighty sessions;
  SPY declines more slowly, then both resume ordinary generated returns.
- Temporary correction: synchronized 14% equity/8% SPY drops, reversed after
  eight sessions (exact shock multiplier reversal), then ordinary returns.
- Leadership rotation: initial held names decline for sixty sessions while
  unheld names rise, then former holdings recover. Membership defining the
  scenario is frozen at branch origin.
- Split-neutral control: healthy continuation with a two-for-one split in an
  initially held security at session 20. Raw prices halve, shares/volume units
  double, and the signal price remains on its original basis. Compare with the
  healthy branch rather than another custom economic book.

No scenario is tuned or dropped if it does not reproduce a previous isolated
counterexample. Any fixture correction must be recorded, with the reason.

## Diagnostics and comparisons

Record production observations/decisions, actual owned capital, cash,
concentration, count damage, damaged capital, and leadership versus Core returns.
Decompose changes in count damage into continuing-name label changes, exits,
entries and denominator effects. Continuing-name changes are not automatically
price recovery: changing residual peers can also change their labels.
Record current-session ledger events and the production Native evidence so that
review sales, stops, entries and actual trigger blockers can be distinguished.
For empty ownership use the production zero-breadth convention: liquidation
attributes the drop to exits; rebuilding from empty attributes the new fraction
to entries at the new denominator. There is no fictitious healthy cohort.

Apply the three previously registered research entry probes to the actual
production observations. They remain eligibility-only counterfactuals, not
complete alternative strategies or simulated executions. No candidate CAGR or
ranking by profitability will be produced. Recovery alignment is diagnosed
through the production Native and Candidate A outputs, not overridden.

Independent checks: cash plus marked holdings plus receivables equals Core NAV;
damage-change attribution adds to the observed fraction change; same-session
JSON restart at selected cuts matches the complete uninterrupted state; split
control preserves dollar economics/decisions; reordered published rows preserve
the transition; diagnostics leave the canonical state unchanged. A deliberate
misvaluation must fail its NAV oracle. None of these checks certifies provider
guarantees or real execution.

## Results

All seven paths completed. The common production-formed book had NAV
$107,704.82, 20 holdings, 98.39% in stocks and effective stock count 19.996.
Day zero below is the first scenario close. The drawdowns are **uncontrolled
Core shadow drawdowns**, not a simulated Sentinel account return. A close
decision cannot avoid the price move that produced it.

| Generated market | Worst Core drawdown | First Sentinel reduction | Closes below full Core | Minimum holdings / maximum cash |
| --- | ---: | ---: | ---: | ---: |
| Healthy | -1.84% | None | 0 | 20 / 1.61% |
| Synchronized shock | -17.69% | Day 0 | 69 | 8 / 60.47% |
| Staggered damage | -21.83% | None | 0 | 3 / 84.60% |
| Gradual decline | -13.04% | None | 0 | 0 / 100% |
| Temporary correction | -13.64% | Day 0 | 15 | 20 / 1.86% |
| Leadership rotation | -26.18% | None | 0 | 0 / 100% |
| Healthy plus split | -1.84% | None | 0 | 20 / 1.61% |

### A. Staggered damage reproduces the shock-gate mismatch

On day 15 the held book is down 20.42%, all twenty holdings are damaged, green
breadth is zero, Core r5 is -13.29%, Core r10 is -16.65%, SPY r20 is -6.94%, and
volatility acceleration is +1.058. All fast-entry conditions except damage
acceleration pass. Damage was already 80% five sessions earlier, leaving a
maximum increase of 20 percentage points against the required 30. This occurs
through actual selection, ownership and residual-peer calculations; it is no
longer just an inconsistent or supplied-observation possibility.

Ordinary stress starts on day 15, but only arms the slow detector; it does not
reduce exposure. The book does not lose the required additional 2% from that
anchor, and ordinary stress subsequently clears. See
`sentinel/controller/champion_frozen.py:46` (fast conjunction), `:78` (anchor),
`:86` (slow conditions), `:110` (actual Native target).

**Assessment: high-priority policy coverage gap if the mandate includes
persistent owned-book impairment.** The code follows the selected champion's
rule. The evidence does not establish a transcription or arithmetic defect.

### B. Leadership strength can coexist with a deteriorating owned book

In the rotation case, on day 30 Core r20 is -16.03% while recent-leadership r20
is +10.42%. The owned book eventually reaches -26.18% drawdown without any
Sentinel reduction. Fast entry lacks the necessary acceleration/volatility
combination; the LD divergence channel uses *weak recent leadership* and is
therefore not an owned-book-versus-leadership divergence detector
(`sentinel/controller/champion_frozen.py:205`).

Ordinary stress starts on day 22. By day 51 its duration is 30 and the book has
lost another 12.21% from its anchor, but Core has already sold every position:
current damaged breadth is zero. The slow gate consequently remains false.
Zero stock exposure is appropriate to show here; calling zero breadth a
recovered portfolio would be misleading.

The ledger identifies these sales as **EXIT_REVIEW_WEAKNESS**, not trailing
stops. Nineteen execute on day 41 and the last on day 42. The same review timing
drives the gradual-decline liquidation. This matters: the initially formed
book has nearly synchronized holding ages, so these results are conditional
on that review phase. We have not established how frequently this happens in
real markets or across other book ages. The earlier component study separately
exercised actual trailing-stop sales; this pipeline set did not produce one.

**Assessment: high-priority population/mandate ambiguity.** Strong opportunities
and healthy owned capital are different facts. It is not inherently incorrect
for a persistent Core to lag its opportunity set, but Sentinel must not be
described as guaranteeing protection against that divergence.

### C. Cash and changing membership explain exposure and recovery

In the gradual decline, Sentinel's multiplier remains 1 while Core becomes
100% cash on day 42. Its implied stock target is then zero. In the staggered
case, day 42 has a multiplier of 1 but only 15.40% stock exposure. Renormalizing
those positions to 100% stocks would override Core's reviewed strategy.

After the synchronized shock, review exits initially leave eight damaged
holdings: count damage stays at 100% despite cash exceeding 60%. Subsequent
healthy admissions reduce damage by changing the denominator. On day 69, eight
damaged holdings among fifteen give 53.33% damage and Native returns full;
Candidate A releases on its persistence route. None of the eight remaining
damaged names had to heal for that fraction to fall. The close-mark stock target
at release is 74.45%, and Core r20 is already slightly positive (+0.34%).

**The earlier isolated weak-Core recovery release was not reproduced in these
coherent paths.** Both observed full-risk releases have positive Core r20. Its
conditional possibility should not be presented as an observed integrated bug.

Likewise, the deliberately extreme capital/headcount example from the first
study is not typical of these generated books: the largest gap here is only
2.84 percentage points, in staggered damage. Capital weighting remains useful
diagnostic context, but this experiment does not support prioritizing it as
the explanation for the large historical return gap.

### D. Alternative eligibility shows tradeoffs, not a winning replacement

| Entry-only research probe | Synchronized shock | Staggered damage | Gradual decline | Temporary correction | Rotation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Remove damage acceleration | 0 | 15 | None | 0 | None |
| Five-session confirmation memory | 0 | None | None | 0 | None |
| Five-session persistent impairment | 4 | 19 | 31 | 4 | None |

Healthy and split controls produce no eligibility for any probe. Memory cannot
restore acceleration that never existed in its bounded window. Persistence
handles the staggered and gradual examples, but also qualifies the correction
before its day-8 reversal. It misses rotation because its inherited market/Core
short-horizon confirmation never qualifies in conjunction with its severity
conditions. These are first eligible closes, not executed exits or complete
alternative-controller performance.

In the correction, Native returns full on day 10, and Candidate A waits until
day 15. The price reversal occurred on day 8. Thus re-entry delay is a real
mechanical cost to assess alongside earlier protection. No alternative trading
cost, T-bill return, account P&L, CAGR or superiority claim is made.

## Recommended matching work

1. Retain these decision-neutral diagnostics: Core stock/cash fraction, damaged
   capital, continuing versus departed cohorts, and separate Core/leadership
   returns. Explain review/cooldown transitions explicitly. No policy change is
   needed to make those quantities visible.
2. If persistent loss of **owned capital** is within Sentinel's mandate, specify
   a separate owned-impairment channel that does not require a fresh shock or
   weak *new leadership*. Keep the existing shock channel distinct. Its dwell,
   severity, reset, cash treatment and complete recovery behavior require an
   explicit risk contract; the illustrative five-session probe is not a
   calibrated production choice.
3. Separate opportunity recovery from owned-book readiness, while allowing new
   holdings and cash to constitute a changed book. Keeping losses in diagnostic
   memory must not force fictitious ownership or permanent lockout until an old
   peak is regained. Broker fills and realized exposure remain outside both
   Core and controller inputs.
4. Before promotion, freeze one complete challenger against response-time and
   unnecessary-exit/re-entry limits. Test different initial review phases,
   concentrated books, gaps, missing observations and coherent action scenarios;
   then evaluate the frozen policy on held-out/forward evidence. Do not select
   its rules by which historical CAGR they recover.

These are policy/interface findings, not a recommendation to change Core's
stock selection or to restore a historical allocation path. No production
policy, threshold, source identity or golden fixture changed.

## Verification and limitations

The final run contains 252 feature-warmup sessions, 80 formation transitions and
840 branch transitions. All 920 full kernel transitions reconcile cash plus
marked ownership plus receivables with NAV. Forty-nine selected branch cuts
match complete state hashes after JSON restore; forty-nine also match with
reversed input rows. Diagnostics leave state unchanged at those cuts. An owned
two-for-one split actually executes; all 120 paired observations and decisions
match the healthy control, with dollar economics equal at the documented
floating tolerances.

Twenty-two targeted tests pass, including ten new pipeline/arithmetic checks.
NAV and split falsifiers detect deliberate guard removal. See the exact commands,
artifact digest and results in [pipeline validation](../audit/impedance/pipeline-validation.md).

An initial run was enriched with Native snapshots, ledger events and empty-book
attribution, then repeated. Every existing economic observation, decision and
summary matched exactly; no price scenario was retuned or discarded. Empty-book
attribution now uses explicit entry/exit conventions instead of returning null.

This small deterministic scenario set does not estimate real-world frequency,
market-distribution parameters, provider correctness, deployed restore
integrity or investment returns. It has one origin/review phase and does not
exercise the durable publication or broker membrane. Economic certification
remains blocked on its existing evidence gates.
