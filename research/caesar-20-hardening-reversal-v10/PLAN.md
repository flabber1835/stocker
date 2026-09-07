# Caesar 20 hardening — adversarial reversal confirmation

## Objective

Confirm whether either of the two surviving hardening candidates actually reduces Caesar 20's demonstrated top-of-queue fragility under the same systematic top-three reversal stress that reduced frozen Caesar 20 to 14.88% 20-year CAGR.

## Frozen contracts

- 20 slots, 5% entry weight
- corrected certified one-session dividend settlement
- immutable canonical PIT package
- frozen classifier/source/runtime pins
- existing liquidity thresholds, costs, cooldown, review, stop, terminal, defensive, and admission-budget semantics
- no prerecorded decisions
- no future information

## Two authorized arms

1. `MEDIAN5_TOP3_REVERSE` — systematically reverse the current durable top three, maintain only the perturbed causal rank history, then apply the 5-session median-rank hardener.
2. `PERSIST3_TOP3_REVERSE` — systematically reverse the current durable top three, maintain only the perturbed causal rank history, then apply the 3-session top-three-persistence hardener.

The reversal is applied before the hardener and before the current session is appended to rank history. This is the strict adversarial formulation: the hardener never sees the unperturbed current ordering and historical state evolves from the same perturbed ordering available to the decision process.

## References

Frozen Caesar 20 canonical: 19.94% CAGR, -23.82% max drawdown, 1.082 Sharpe.
Frozen Caesar 20 top-3 reversal stress: 14.88% CAGR, -27.64% max drawdown, 0.891 Sharpe.
Discovery normal-path candidates:
- Consensus median 5: 19.70% CAGR, -26.39% max drawdown, 1.047 Sharpe.
- Top-3 persistence 3: 19.08% CAGR, -23.20% max drawdown, 1.048 Sharpe.

## Decision criterion

A genuine hardening improvement must preserve the already-observed strong normal-path economics and materially improve the adversarial reversal result versus 14.88%. A reversal CAGR in the 17–18%+ region, with acceptable drawdown and Sharpe, would be strong evidence that the hardener reduces top-of-queue path fragility.
