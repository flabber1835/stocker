# Wealth Core V1 — 10 bp open-time sizing A/B insights

## Authority

- Workflow run: `34294467743`
- Trigger head: `428e9792bd7c63d604a95dfc3ae40a2b0fcc1fe8`
- Base evidence head: `3b5d70de258dadaac6272f2bd9d682d291117d29`
- Canonical PIT dataset: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Dividend lag remained one session in both arms.
- Production code was not modified.

## Execution result

| Metric | Certified 10 bp control | Open-time whole shares | Open-time fractional |
|---|---:|---:|---:|
| CAGR | 15.488288% | 14.647576% | 14.214093% |
| Max DD | -49.042739% | -50.569358% | -50.957407% |
| Sharpe | 0.805082 | 0.757490 | 0.748440 |
| Ending equity | $1,646,091.83 | $1,422,872.69 | $1,318,352.68 |
| Close admissions | n/a | 522 | 515 |
| Completed entries | 519 | 521 | 515 |
| Next-open blocks | 1 | 0 | 0 |
| Zero-quantity blocks | n/a | 0 | 0 |
| Invalid-open blocks | n/a | 0 | 0 |
| Rounding underfill | n/a | $21,402.80 | $0.00 |
| Fractional buys | 0 | 0 | 515 |

## Direct answers

**Did open-time whole-share sizing execute every admitted trade?** Yes. It recorded 0 next-open blocks.

**Did fractional sizing execute every admitted trade?** Yes. It recorded 0 next-open blocks.

**What does fractional sizing add?** Whole-share rounding left $21,402.80 of cumulative execution budget unused across executed buys. Fractional sizing left $0.00.

**Performance interpretation.** CAGR differences are path-dependent consequences of altered admissions and sizing. They are reported for completeness and are not the selection criterion.

## Research conclusion

The production-design question should be decided from execution completeness, sizing fidelity, operational broker support for fractional shares, and the path-divergence evidence. This experiment does not authorize a production change.
