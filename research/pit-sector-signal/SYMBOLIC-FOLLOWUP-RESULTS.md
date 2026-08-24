# Symbolic sector-signal follow-up — 2026-08-23

Research-only continuation of issue #241. No production/main changes.

## Exact branch-space result

Symbolic reduction of the 20-year 30pp Sentinel fast branch leaves only 25 peer-controllable sessions (42 impossible, 6 inevitable). Exact dynamic programming over those 25 binary choices gives a terminal-NAV upper bound within the frozen fast-branch abstraction:

- CAGR 20.1574953%
- Sharpe 1.120525
- MDD -24.1570%
- ending multiple 39.3595x

Oracle ON choices: 2008-07-08, 2011-08-04, 2015-08-24, 2018-10-12, 2022-04-26.

## Best causal approximation retained

Two-timescale hybrid:

- slow/stable breadth: causal SEC SIC -> FF12
- fast contagion: prior-252-session SPY-residual peer correlation, historical co-distress corroboration, and symbolic book-geometry relevance
- residual threshold 0.15
- Jaccard corroboration OR min_d <= 0.75
- dynamic peer signal evaluated only on symbolic-controllable dates; inevitable=ON, impossible=OFF

Result:

- CAGR 20.1117225%
- Sharpe 1.118670
- MDD -24.1570%
- ending multiple 39.0608x
- validation 2016-2026 CAGR 23.0247%

This is only ~4.58 bp/year below the exact fast-branch oracle, so there is essentially no remaining CAGR headroom in the fast peer branch without changing the controller abstraction itself.

## Walk-forward threshold test

Expanding historical selection at 5-year boundaries:

- train 2006-2010 -> threshold 0.13 -> test 2011-2015 CAGR 11.32%
- train 2006-2015 -> threshold 0.15 -> test 2016-2020 CAGR 18.63%
- train 2006-2020 -> threshold 0.15 -> test 2021-2026 CAGR 27.13%

Stitched pseudo-OOS 2011-2026:

- hybrid CAGR 19.13% vs FF12 17.69%
- Sharpe 1.075 vs 1.013
- MDD -24.16% vs -25.21%

## Further experiments after symbolic execution

### Symbolic rule synthesis

A depth-2 Boolean formula search was fitted only to pre-2016 controllable oracle labels. The best discovery formula was:

`jaccard AND spy_dd63 >= -11.222%`

It reproduced all three discovery oracle-ON dates with zero false positives, but failed to generalize: validation oracle balance 0.40, validation CAGR 22.8622%, full CAGR 20.0633%. It is rejected. This is evidence that simple hindsight rule synthesis overfits the tiny event set.

### Online predictive gate

Expanding causal ridge/logistic models trained to predict whether BIL would beat the shadow over the next 20 sessions were tested using only matured historical labels. Best tested versions were materially worse than the symbolic hybrid (full CAGR roughly 16.1%-18.2%). Rejected. The event sample is too sparse and daily labels do not line up cleanly with the controller's path-dependent value of a fast decision.

### Threshold ensembles

Majority voting across residual thresholds 0.13-0.17, 0.135-0.165, 0.14-0.16, and 0.145-0.155 produced exactly the same branch path as threshold 0.15 and therefore the same 20.1117% CAGR / 1.11867 Sharpe / -24.157% MDD. This shows the chosen path is a median-consensus path across a broad threshold neighborhood, even though one-sided threshold moves can still hit controller cliffs.

A stricter 80%-agreement policy gave 19.7943% CAGR, showing that simply refusing threshold-disputed events leaves measurable return on the table.

### Subwindow-persistence correlation

Residual correlations were recomputed independently in three adjacent 84-session subwindows and peer escalation required median / 2-of-3 / mean / minimum agreement. None improved on the main hybrid. Best validation result was the very strict minimum-correlation rule at 0.20 (22.77% validation CAGR) but full CAGR only 18.76%. Rejected. Persistence filtering removes useful crisis relations as well as noisy ones.

### Uncertainty-aware symbolic policy

The exact per-date threshold intervals were integrated against a Normal uncertainty distribution centered at 0.15. A decision rule requiring >=50% probability that the residual-threshold branch is ON reproduces the 20.1117% hybrid path for threshold-uncertainty sigma from 0.003 through 0.030. More conservative probability cutoffs reduce CAGR. This does not prove correlation-estimation robustness, but it shows the selected symbolic path is the median-probability decision over a wide calibration-uncertainty range.

## Research conclusion

Further attempts to beat 20.11% inside the frozen fast peer branch are now statistically counterproductive: the exact DP ceiling is only 20.1575%. The research problem should therefore shift from maximizing CAGR to falsifying and stabilizing the 20.11% causal approximation.

The strongest current interpretation is:

> Static causal SEC/FF12 peers are useful for slow structural stress; a dynamic market-residual peer graph is useful for fast contagion; symbolic execution should gate the dynamic signal to dates on which peer grouping can actually alter the controller branch.

No candidate is production-ready. The next worthwhile work is block/bootstrap perturbation of the underlying return windows, leave-crisis-out recalibration, and/or a separately symbolically bounded slow-branch analysis. Do not keep tuning the same 25 fast decisions for headline CAGR.
