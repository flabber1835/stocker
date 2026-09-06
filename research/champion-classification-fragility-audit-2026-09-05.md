# Research Champion classification fragility audit — interim

Status: diagnostic only; NOT CERTIFIED.

Source replay: GitHub Actions run 34005390953, reviewed_18 artifact 9981135703, artifact SHA-256 61a076d7ac47d5d4e297539272e698d43a7df032915e0ded2060b23e1d38352d.

Frozen Champion profile: strategy9-e3-research-champion-v1.

## Interim findings from completed reviewed replay

Measurement sessions: 5,032.

Selection-path churn:
- selected-position set changed on 815 sessions;
- 453 distinct securities had held_sessions > 0;
- 453 distinct securities had pending_sessions > 0;
- 5,111 securities reached durable-ranked state;
- 6,232 securities contributed to recent-leadership calculations;
- 6,656 securities were eligible at least once.

Outer-controller threshold proximity around LDRC_R20 = -0.085:
- |recent_r20 - threshold| <= 0.0005: 15 sessions;
- <= 0.0010: 23 sessions;
- <= 0.0025: 53 sessions;
- <= 0.0050: 104 sessions;
- <= 0.0100: 218 sessions.

Under the additional conditions wc_dd <= -0.10 and spy_r20 >= 0, which are relevant to the demonstrated divergence mechanism:
- <= 0.0005: 3 sessions;
- <= 0.0010: 4 sessions;
- <= 0.0050: 7 sessions;
- <= 0.0100: 11 sessions.

The four sessions within 0.0010 under those additional conditions were:
- 2020-06-24
- 2021-03-25
- 2026-07-21
- 2026-07-22

Leadership population was not near its minimum-size fallback in this replay: min 91, median 141, max 223. Eligible count ranged from 908 to 2,223, median 1,405.

## Interim interpretation

The reviewed replay does not show the outer controller continuously operating on a classification-sensitive knife edge. The June 24, 2020 event is a genuine narrow-threshold amplification event, but comparable threshold proximity under the relevant drawdown/SPY conditions is uncommon.

The larger structural fragility surface is stock-selection path dependence. Classification changes can alter eligibility, ranks, selections and subsequent holdings; the selected-position set changed 815 times and 453 distinct securities were held over the measurement window. A classification error can therefore redirect the portfolio path and compound for years even when the misclassified security itself is held briefly or never held.

## Next checks

1. Join the decision-relevant path worklist to the best-effort classification ledger and rank every INFERRED_COMMON name by economic contact: held/pending first, leadership contribution second, durable-ranked/candidate-displacement third.
2. Review high-risk legal/security categories (partnership, trust, units, conversions, preferred/depositary structures, identity discontinuities) with contemporaneous authority.
3. Compare corrected replay against reviewed baseline for first selection, raw-Wealth-Core and allocation divergences.
4. Use PDS-only and EQM-only replays as bounded causal diagnostics, not as the main fragility conclusion.
5. Quantify interaction residual after corrected baseline completes.
6. Run classification perturbation robustness tests on decision-relevant names to estimate how much 20-year CAGR changes from one-name and small-basket eligibility perturbations without changing Champion parameters.

No certification or corrected CAGR claim is made by this interim audit.
