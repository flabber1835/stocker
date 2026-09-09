# Wealth Core V5 research

Wealth Core V5 is the corrected affordability lineage after the pre-fix V3 AMZN zero-quantity defect and the over-restrictive fixed-V3 / V4 affordability repair.

## Read first

- [`LINEAGE_AND_DEFECT_ANALYSIS.md`](./LINEAGE_AND_DEFECT_ANALYSIS.md) — full V3 -> V4 -> V5 forensic history, performance comparison, first causal divergence, and root-cause analysis.
- [`EXPERIMENT_SPEC.md`](./EXPERIMENT_SPEC.md) — frozen V5 economic definition, behavioral witnesses, invariants, and evidence contract.
- [`PORTFOLIO_STABILITY_18_26_RESULTS.md`](./PORTFOLIO_STABILITY_18_26_RESULTS.md) — completed 18–26 holding stability sweep, V4 comparison, validation evidence, and the frozen decision to retain 20 holdings.

## One-line V5 rule

Keep the 10 bp close admission cushion, but test one-share feasibility against **total cash** because the cushion is released at the next open. Exact whole-share quantity remains determined only from actual cash and actual next-open price.

## Current portfolio-size decision

The completed V5 stability sweep (`34313794954`) supports a central robustness basin of approximately 19–23 holdings. The frozen default remains **20 holdings**. The 22-holding point is a local historical maximum and is not adopted as a post-hoc optimized parameter.
