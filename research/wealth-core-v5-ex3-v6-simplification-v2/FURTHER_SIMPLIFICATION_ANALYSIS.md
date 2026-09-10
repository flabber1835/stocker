# Further simplification after round 2

Status: research reasoning and proposals. This document authorizes no new full-PIT starts or production changes. The campaign has consumed 21 starts: ten original arms, one combined follow-up, and ten round-2 arms. The remaining authorized replay budget is zero.

Tracking: [issue #349](https://github.com/flabber1835/stocker/issues/349), [PR #350](https://github.com/flabber1835/stocker/pull/350).

## Evidence and scope

Analysis is bound to result commit `2b4000b6ef12f076036cf16c4547a08fd1b0aa11`, [round-2 results](results/34480037109-1/RESULTS.md), [full metrics](results/34480037109-1/SUMMARY.json), and [clean_cached source](results/34480037109-1/sources/clean_cached.py). Measurement covers 2006-07-31 through 2026-07-31, 5,032 sessions, on the frozen broad-PIT dataset. The [earlier roadmap](../wealth-core-v5-ex3-v6-simplification-v1/RESULTS_AND_SIMPLIFICATION_ROADMAP.md) records round 1 and the coherent candidate. Its future-work statements describe the state before round 2; this document supersedes those proposals where round 2 supplied evidence.

Wealth Core's economic projection, transactions and close decisions remained identical across the completed arms. Sentinel continues to own exposure. Execution continues to own broker interaction. The proposed compact controller preserves these boundaries.

## What the results establish

### Representation cleanup has the strongest evidence

State cleanup, symmetric correlation caching and their combination exactly reproduced the simplified candidate's historical allocations and NAV. The combined result is 21.8332% 20-year CAGR, -27.3562% maximum drawdown and 51.9214x ending wealth. This demonstrates that some implementation complexity can be removed with exact historical equivalence.

Caching reduced pair calculations from 248,321 to 226,626: an additional 8.74% reduction, or 85.61% relative to the original 1,574,966. It does not halve the remaining work because selective evaluation already avoids many reverse-direction queries. Recorded runtimes range widely: 1,538 seconds baseline, 730 cached, 1,295 cleanup-only and 982 combined. Runner variability and single observations prevent attribution of those wall-clock differences to the code changes. The deterministic pair counts support the computational claim.

### Rare recovery decisions carry substantial economic weight

Deleting cross-surface recovery changed only 33 sessions, 0.656% of the measurement period, and reduced ending wealth by 9.56%. Zero-exposure sessions rose from 650 to 683, full-exposure sessions fell from 4,126 to 4,093, and 55%-exposure sessions remained 256. The baseline recorded five cross-surface releases.

The fixed COVID diagnostic window illustrates the effect: the ending multiple fell from 1.6654 to 1.5323, while maximum drawdown remained approximately -15.8941%. This supports the interpretation that delayed recovery can lose substantial rebound participation while barely affecting a headline drawdown statistic. Episode-level attribution still requires the retained daily tapes; five releases do not imply five independently measured causal effects.

Removing peers changed 142 allocation sessions, reduced ending wealth by 5.60%, and reduced episode count from eight to seven. The 2015-2016 diagnostic drawdown deteriorated from -12.5306% to -17.5847%, and underwater duration increased from 324 to 450 sessions. The unchanged 20-year maximum drawdown hides this local deterioration. Equal five-year returns also do not establish equal behavior in earlier regimes.

### The mandatory ramp changes the interaction between two recovery rules

The mandatory ten-close ramp produced 20.3491% CAGR and -30.8146% maximum drawdown. Its allocation counts were 484 zero, 518 at 55%, and 4,030 full, versus 650/256/4,126 in the baseline. It produced more exposure on some sessions as well as delaying full exposure on others.

The code explains a concrete route. CandidateA holds the previous desired exposure when an episode is active and Native requests 100% before recovery certification. When Native requests 55%, that full-recovery hold branch is bypassed. Starting from a previous desired exposure of zero, the original Native jump to 100% can therefore leave the final target at zero, while a mandatory Native ramp can produce a final target of 55%. A synthetic transition can reproduce this. This establishes a possible mechanism; attributing every changed historical session requires a tape audit.

Longest underwater duration rose from 640 to 733 sessions. The fixed 2022 diagnostic drawdown deteriorated from -14.5284% to -18.5975%. Making every recovery gradual is consequently not a monotonic reduction in final exposure or historical risk.

### Simplifications interact

Peer removal and cross-surface removal separately reduce terminal wealth by 5.60% and 9.56%. Multiplying their independent wealth ratios would imply a 14.62% reduction; their tested combination lost 11.78%. The combined effect is path dependent. Round 2 did not include the fixed-ramp plus persistence-only arm with peers retained, so it is not a complete three-factor design. The existing evidence does not identify every interaction.

These are historical observations on one fixed dataset. The four overlapping trailing windows are useful preservation checks, not four independent replications. Further parameter searches on the same history would increase selection risk.

## Proposed next reductions

### 1. Reduce the executable research runner to the active strategy

The generated source still constructs and steps `ControlLDRC` and `CandidateB`. The active `control` allocation is assigned `a_d`, CandidateA's result; `ctl_d` is unused. The `control` and `A` overlay tracks receive the same pending targets. CandidateB supplies a comparison track and comparison statistics.

Proposal: execute one Native/CandidateA strategy and one overlay track. Place optional historical comparators in a separate analysis adapter. Produce compatibility columns from the single authoritative track where evidence consumers require them. Once the comparator implementations are separated, their rebound-only configuration can leave the active executable.

This removes research scaffolding, duplicate state and duplicate accounting paths. It does not remove another active economic rule. Production's existing canonical Wealth Core must remain the implementation authority; the frozen generated file remains an immutable research oracle. Required proof: active allocations, reasons, costs, NAV and Core projections match; report-schema changes are explicit. Keep archived comparator results and sources.

### 2. Make the controller state reflect the information it actually uses

CandidateA has eight stored fields. `episodes` and `concordance_releases` are audit counters, and never determine the next target. Keep them in append-only diagnostics. `prev_native` is read only through the full-exposure threshold, so a `previous_native_was_full` boolean carries its decision information in this frozen three-level controller.

There is a stronger candidate reduction: combine `episode` and the decision-bearing use of `prev_desired` into three recovery states: `CLEAR`, `HOLD_ZERO`, `HOLD_55`. On reachable states, an active episode has a previous final target of zero or 55%. Outside an episode the old desired value is overwritten before it could be read by the recovery hold branch. Keep the divergence latch and both recovery counters independently.

That would represent CandidateA's decision state with five fields: recovery state, divergence latch, full-health streak, episode-positive streak, and previous-Native-full flag. The field count falls from eight including telemetry, or six excluding telemetry. This reduces redundant representations and snapshot validation cases; it does not establish fewer economically distinct behaviors.

Required proof: reachability and transition equivalence, all reason outputs, missing observations, all restart points, and versioned old-snapshot migration. Reject invalid old snapshots according to an explicit schema. Preserve diagnostic counter continuity separately. The proposed evidence script checks the information reduction on synthetic sequences; a production enum implementation remains future work.

Native can similarly group each active cause with its dwell and healthy-streak data. Inactive ages can be omitted from a canonical snapshot because every new entry resets them. Keep the ordinary, base-fast, fast and slow causes distinct: ordinary entry can suppress base-fast entry while fast still enters, and base-fast checks age >=10 while fast checks age+1 >=10. A shared record type can simplify schema and transition code; merging those economic states would change the contract.

### 3. Express exposure as three explicit ceilings

After preserving the existing update order, final exposure can be expressed as the minimum of Native's ceiling, the episode recovery ceiling and the divergence ceiling. The recovery ceiling is the previous desired value precisely when the existing full-recovery hold condition applies, and 100% otherwise. The divergence ceiling is 55% when latched and 100% otherwise.

Use one pure Sentinel transition with named phase results and typed observations. Keep Native and CandidateA's economic responsibilities visible within it. This makes the mandatory-ramp interaction inspectable and reduces scattered target assignments. Preserve the ordering of episode entry, streak updates, divergence clearing, recovery certification, divergence entry and final clamping, including reason priority.

A shared streak-update primitive can remove repeated counter code. Each counter retains its own predicate, cap, reset rules and clock. Ordinary recovery uses stop counts; Native health uses breadth; full recovery uses recent-leadership R20/R40; episode-positive recovery also requires Native exposure and an active episode. Those distinctions affect decisions.

### 4. Reuse the canonical observation history

Native stores six R40 values solely to compare the prior close's R40 with R40 six closes back when leaving a severe state. The runner already has immutable Core NAV history. Supply the exact prior-close fragility observation from that history and remove Native's duplicate `r40hist` snapshot field.

At close t the existing comparison is R40[t-1] minus R40[t-6]. Deriving both values requires Core NAV through t-46. Preserve the current finite-value checks and the rule that unavailable or nonpositive improvement takes the fragile ramp. The current close's R40 must not enter this decision. This reduces duplicated controller memory; the required historical information remains in the observation layer.

Also extract the prior-session SPY return window once per close for all held-stock residual calculations. Currently `_prior_residuals` repeats date lookup and SPY extraction for each security. Reusing that immutable window can remove substantial repeated pandas work. Retain each asset's observation mask, beta arithmetic order, 120-observation floor and prior-close timing. Vectorized or incremental correlation arithmetic needs separate numerical validation at the 0.145 cutoff and at ranking ties.

### 5. Reduce the peer classifier to its decision information

The controller consumes damaged and green breadth, not a durable network object. Keep the selected top-three peers and their ordering local to the observation calculation, and emit only the classifications plus optional audit detail.

Two exact local reductions are available:

- If no held stock is red, peer voting cannot damage any unresolved stock. Return the individual-damage and green counts immediately. Individual damage can still be present because its definition is broader than red. This is a logical shortcut for every such observation, not a calendar rule inferred from quiet historical periods.
- Use the integer condition `2 * red_votes >= neighborhood_size` for the 50% threshold. For a valid unresolved stock, self is non-red. With one qualifying peer, that peer must be red; with two or three qualifying peers, two red peers are required. No qualifying peers yields no peer damage.

Keep all holdings eligible as neighbors. Individually damaged and green holdings can change another stock's nearest peers. Preserve the 252-session window, minimum overlap, correlation floor, permanent-ID tie ordering and session-local cache. Diagnostic peer-work counters may change under the shortcut; economic breadth must match exactly. Emit skipped-work telemetry if needed.

This simplifies and short-circuits classification. The residual-history dependency remains economically relevant. A one-peer model or periodically refreshed network would still require that dependency and introduce new behavior; their expected structural benefit is limited.

### 6. Remove logical guards made redundant by the frozen conditions

Two small examples have direct proofs:

- Native's fast re-arm requires drawdown greater than -6%, while a fast signal requires drawdown at or below -10%. The additional `not fastsig` in both re-arm expressions is implied by the drawdown condition.
- In the simplified CandidateA, divergence clearing requires a full-health streak whose current observation has recent R20 greater than zero. Divergence entry requires recent R20 at or below -8.5%. Therefore clearing and re-entry cannot occur on the same close, and the `not cleared` entry guard is redundant. This proof is specific to the candidate with SPY rebound clearing removed. The original rebound-enabled controller permits a different clearing predicate.

Consolidate repeated finiteness and full-exposure checks into named observations where their domains match. Keep proofs tied to the frozen configuration. Fewer lines are useful when they also reduce duplicated contracts and ambiguous update ordering.

## Recommended evidence sequence

1. Record state-read dependencies and derive a candidate schema, including old-state migration and audit separation. Use the current exact `clean_cached` source as the research comparison point.
2. Check the mathematical shortcuts and state-information reduction on deterministic synthetic sequences, restart boundaries and adversarial observations. Include counterexamples that break deliberately weakened versions.
3. Build a fast Sentinel replay from retained causal observation tapes. It can replay a few thousand transitions per candidate while preserving the original next-open accounting. A changes-only report should identify the first different observation, state, target and reason for each episode. Tape inputs must include all Native fields, premeasurement warmup and the exact lagged Native clock. The current daily CSV does not directly contain every Native input, so input reconstruction and parity qualification are required. Peer changes additionally need held-stock and residual-history inputs; a stored aggregate breadth column cannot validate a new peer algorithm.
4. Require exact allocations, reasons, economic state after projection, and NAV for the proposed representation changes. Keep peer-work telemetry separate from economic equality. Follow this with a fresh full-PIT confirmation only under a newly authorized budget.

Full source removal, typed-state migration, history reuse and the complete proposed bundle have not received a full-PIT test. Synthetic evidence supports the stated local claims; it is not production certification. No convergence reset is part of this proposal. Economically active ages, anchors, re-arm flags, streaks and episode memory remain subject to exact future-transition equivalence.

## Reasoning checks completed

Command: `python research/wealth-core-v5-ex3-v6-simplification-v2/reasoning_checks.py`.

All six checks passed under Python 3.12.14 / NumPy 2.4.6. [Machine-readable evidence](REASONING_CHECKS.json) and [reproduction code](reasoning_checks.py) are retained. The loader verifies the stored source hash and extracts only pure functions/classes; it never loads the market dataset or calls the backtester.

- Guard removal: 10,000 Native observations plus 10,000 CandidateA observations matched outputs, reasons and all stored fields.
- Reduced CandidateA information: 25,000 observations matched after reconstructing the original class from the proposed five fields before every step; both audit counters were independently accumulated. All three recovery states and both recovery certification reasons were exercised.
- Rebound guard counterexample: applying the candidate-specific guard deletion to the archived rebound-enabled ControlLDRC comparator changed its target from 100% to 55%. This detects an invalid generalization of the proof.
- Mandatory-ramp interaction: a seeded transition produced final targets of zero for the baseline and 55% for the mandatory ramp.
- Peer vote reduction: all 30 boolean neighborhood configurations of sizes one through four, 1,000 zero-red books and a red-peer falsifier passed.
- Fragility clock: 2,001 observations matched history-derived values exactly; a deliberate current-close substitution differed on 1,955 observations.

The first synthetic fixture exercised cross-surface certification but missed persistence certification; its coverage assertion failed. The fixture was extended to include both recovery regimes before the final passing run. No strategy code changed and no full-PIT slot was consumed by these checks.

## Choosing the economic baseline

The existing simplified candidate improves original 20-year CAGR by 0.2760 percentage points and therefore fails the fixed symmetric 0.25-point original-preservation limit. Its exact round-2 equivalents inherit that status. That verdict remains explicit.

For a route that already passes the original screen, round 1's standalone ten-close ramp is a useful comparison point: 21.6701% CAGR and -26.7056% maximum drawdown, with SPY rebound release retained. Exact peer, bounded-counter and state-representation improvements can be investigated around that source. Their complete composition still requires verification. Candidate-specific proofs, especially the redundant divergence-clear guard, must not be transferred to the rebound-enabled source automatically.

The highest-value next proposal is a compact, typed, single-strategy implementation with shared causal observations and minimal sufficient controller state. The completed results support retaining the peer information, fragility-dependent recovery and cross-surface recovery while simplifying their representation and evaluation.
