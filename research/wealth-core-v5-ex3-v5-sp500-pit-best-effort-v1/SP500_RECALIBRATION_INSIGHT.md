# S&P 500 recalibration insight

## Context

A full 20-year replay of Wealth Core V5 paired with Sentinel EX3 V5 was run using the S&P 500 PIT best-effort universe.

GitHub Actions evidence:

- Run: https://github.com/flabber1835/stocker/actions/runs/34391894523
- Branch: `research/wealth-core-v5-ex3-v5-sp500-pit-best-effort-v1`
- Measurement horizon: 2006-07-31 through 2026-07-31

## Headline result

The S&P 500-constrained system materially underperformed the broad-universe V5 + EX3 V5 system.

| 20-year result | CAGR | Max DD | Sharpe |
| --- | ---: | ---: | ---: |
| Broad Wealth Core V5 | 17.07% | -50.34% | 0.840 |
| Broad Wealth Core V5 + Sentinel EX3 V5 | 21.56% | -27.38% | 1.121 |
| S&P 500 Wealth Core V5 | 10.11% | -46.78% | 0.639 |
| S&P 500 Wealth Core V5 + Sentinel EX3 V5 | 11.65% | -32.23% | 0.804 |
| SPY | 11.26% | -55.20% | 0.647 |

The broad-universe full system compounds to roughly 49.6x over the period. The S&P 500-constrained full system compounds to roughly 9.1x.

## Interpretation

This run should be treated as an **uncalibrated S&P 500 baseline**.

Wealth Core V5 and Sentinel EX3 V5 were developed and impedance-matched on the broad universe. Restricting Wealth Core to the S&P 500 changes the opportunity set, ranking depth, turnover path, recovery behavior, and drawdown structure.

The universe restriction therefore changes the economic system that Sentinel observes.

### Wealth Core selectivity changes

The broad universe provides substantially more eligible securities and leadership candidates per session. A 20-position portfolio is highly selective in that environment.

Inside the S&P 500, the same 20-position book consumes a much larger fraction of the leadership cohort. Selection pressure is lower and Wealth Core is forced further down its ranked candidate set.

The S&P 500 version should therefore have its structural parameters recalibrated, beginning with portfolio size and corresponding position sizing.

### Sentinel impedance changes

Sentinel EX3 V5 remains helpful on the S&P 500 path, but its improvement is materially smaller than on the broad-universe path.

Broad universe:

- CAGR: 17.07% -> 21.56%
- Max DD: -50.34% -> -27.38%
- Sharpe: 0.840 -> 1.121

S&P 500:

- CAGR: 10.11% -> 11.65%
- Max DD: -46.78% -> -32.23%
- Sharpe: 0.639 -> 0.804

The S&P 500 Wealth Core path has different drawdown and recovery timing, so the existing EX3 V5 thresholds should be re-swept specifically against that path.

## Research conclusion

If an S&P 500 production variant is desired, recalibrate both layers:

1. **Wealth Core**
   - Sweep portfolio size first.
   - Preserve causal next-open execution and V5 affordability economics.
   - Re-evaluate whether 20 holdings remains the correct selectivity level for the smaller universe.

2. **Sentinel**
   - Re-run impedance matching after the S&P 500 Wealth Core configuration is frozen.
   - Re-sweep recovery persistence and damage/release thresholds, including REC, R40, FAST-damaged and healthy-damaged parameters.

3. **Validation**
   - Treat run 34391894523 as the frozen baseline for all S&P 500 calibration experiments.
   - Require sensitivity/stability testing around any selected configuration.
   - Preserve the S&P 500 PIT best-effort claim boundary; this universe is not formally PIT-certified.

## Primary insight

The result is evidence that the current broad-universe configuration is strongly coupled to universe breadth. It is not evidence that an S&P 500 implementation is intrinsically poor.

Any S&P 500 implementation should be considered a distinct calibrated variant of Wealth Core + Sentinel, with its own portfolio-size selection and Sentinel impedance match.
