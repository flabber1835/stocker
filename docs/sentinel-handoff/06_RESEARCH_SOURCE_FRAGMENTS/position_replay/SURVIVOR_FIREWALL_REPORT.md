# Elastic Survivor Firewall experiment

## Executive verdict

The position-level idea is real, but the correct implementation is much milder than the original concept.

The best new hybrid was:

1. Keep the certified Wealth Core shadow unchanged.
2. At a 12% shadow drawdown, identify the three weakest **non-green** holdings.
3. Reduce only those three holdings to 50% of their shadow weights.
4. Freeze that damaged cohort. Re-rank only if the shadow drawdown deepens another five percentage points.
5. Preserve green holdings at 100%.
6. At a 15.5% shadow drawdown, activate the broad systemic backstop.
7. In the wealth-balanced version, retain 40% Wealth Core and place 60% in the SHY/BIL defensive sleeve.
8. Recover from the systemic state after at least 20 sessions and three healthy shadow sessions.

This produced 19.69% CAGR, a -33.50% maximum drawdown and 155.5× ending wealth.

It did **not** decisively beat the simpler binary controller:

| Strategy | CAGR | Maximum drawdown | Ending wealth | Trailing-10 CAGR | Trailing-10 drawdown |
|---|---:|---:|---:|---:|---:|
| Wealth Core | 19.97% | -41.16% | 166.0× | 22.13% | -31.40% |
| Binary 15.5% → 40% Core | 19.78% | -34.42% | 158.6× | 20.88% | -30.97% |
| **Selective three-position trim + 40% backstop** | **19.69%** | **-33.50%** | **155.5×** | **20.82%** | **-30.41%** |
| Binary 15.5% → 25% Core | 19.67% | -33.15% | 154.8× | 20.50% | -31.05% |
| Selective three-position trim + 25% backstop | 19.57% | -32.58% | 151.1× | 20.49% | -30.56% |

Relative to the 40% binary controller, the selective hybrid reduced maximum drawdown by 0.92 percentage points while costing 0.08 percentage points of CAGR.

Relative to the 25% binary controller, the selective 25% hybrid reduced maximum drawdown by 0.57 percentage points while costing 0.10 percentage points of CAGR.

These are useful but marginal improvements—not a new dominant strategy.

## What was tested

The corrected experiment set comprised more than 230 configurations across:

- rolling weakest-position firewalls;
- frozen damaged cohorts;
- cohort refresh only after deeper drawdown;
- three, five and eight protected positions;
- 0%, 25% and 50% retained position weights;
- natural position-count contraction;
- weak-entry admission gates;
- 25% and 40% systemic floors;
- SSO 2× recovery bridges;
- SPY 1× bridge controls;
- actual SHY/BIL defensive returns.

The Wealth Core aggregate path was exact. Position-level counterfactuals were reconstructed from 160,715 holding-day observations. Reconstructed holding contributions had 0.999855 correlation with the next-session certified Wealth Core return, with mean absolute residual of approximately 0.32 basis points per session.

## Backward symbolic findings

### 1. The rolling weakest-eight idea is wrong

Continuously re-ranking the weakest positions causes the firewall to migrate through the portfolio. Over a long drawdown, many temporary laggards eventually become protected or removed. This sacrifices future winners and creates excessive turnover.

The decision that should have been made was:

> Identify the damaged cohort when stress begins, then keep the cohort stable unless portfolio damage materially deepens.

### 2. Selective protection alone cannot solve systemic drawdowns

Mild standalone selective trims preserved compounding but only modestly reduced the worst drawdown:

| Standalone selective rule | CAGR | Maximum drawdown | Ending wealth |
|---|---:|---:|---:|
| Trim worst 3 to 50% at 12% DD | 19.97% | -40.29% | 165.9× |
| Trim worst 5 to 50% at 12% DD | 19.89% | -39.08% | 163.1× |
| Remove worst 5 at 12% DD | 18.85% | -35.34% | 127.6× |

The first two preserve Wealth Core's right tail, but they cannot prevent a GFC-style broad failure. Removing the positions entirely protects more, but destroys too much compounding.

### 3. Position count is a useful state variable, but aggressive contraction is costly

Allowing ordinary 30% stops to reduce the number of positions and leaving vacancies unfilled did reduce drawdown:

| Position-count rule | CAGR | Maximum drawdown | Ending wealth | Average live positions |
|---|---:|---:|---:|---:|
| Weak replacement gate at 10% DD | 19.19% | -38.12% | 138.2× | 22.30 |
| Natural contraction toward 23/21/18 positions | 18.58% | -37.21% | 119.6× | 21.97 |

But vacancies often open near the end of a decline. Refusing replacements then causes the portfolio to miss the early rebound. Position count should therefore be a soft constraint or admission-quality control, not a blunt crisis brake.

### 4. Green survivors really can be preserved

The best three-position selective hybrid retained essentially all green-position weight: 99.93% on average.

That validates the original intuition. The problem was not preserving raging bulls; the problem was that the selective layer could not absorb broad correlated damage by itself.

### 5. Leveraged catch-up contributed almost nothing

The best SSO bridge changed CAGR from 19.69% to 19.69%, with no improvement in maximum drawdown. Its average portfolio weight was only 0.0060%.

Why:

- A binary controller returns directly to full Wealth Core exposure, leaving no beta gap.
- The mild selective controller leaves only a small gap after recovery.
- The bridge signal therefore activated rarely and at tiny weights.
- SPY bridge controls were slightly worse after costs.

Leveraged recovery should not be added merely to recover a prior loss. It needs a genuine, persistent missing-beta state. This architecture does not create enough of one.

## Crisis behavior

The selective hybrids helped most when damage was concentrated, particularly 2018 and 2022. The broad backstop did most of the work in the GFC and COVID.

A notable exception was 2011: defensive rules slightly worsened the episode because the correction reversed before the protection could earn back its switching cost and missed exposure.

The complete crisis table is included in `crisis_drawdown_comparison.csv`.

## The most important architectural learning

Position-level intelligence is more valuable as a **classifier for the type of drawdown** than as a large independent liquidation engine.

A future controller should branch:

### Concentrated damage

When only a few weighted holdings or one cluster account for most deterioration:

- freeze a three-to-five-position damaged cohort;
- trim those positions modestly;
- preserve green leaders;
- continue admitting only exceptionally strong replacements.

### Systemic damage

When damage breadth becomes broad, or the shadow reaches the 15.5% backstop:

- stop trying to solve the problem stock by stock;
- activate the portfolio-level defensive sleeve.

This is more promising than always stacking selective trims on top of a fixed binary stop.

## Recommendation

Keep the 15.5% binary controller as the primary production challenger.

Retain the selective survivor logic as an experimental **drawdown-type classifier**, not yet as a permanent second layer.

The best candidate for the next experiment is an adaptive branch:

- concentrated damage → trim only three damaged holdings to 50%;
- broad damage → activate the 40% or 25% portfolio backstop earlier;
- do not apply both layers automatically;
- use damaged weight, cluster breadth and green breadth to choose the branch.

That mechanism directly incorporates the strongest lesson from this experiment while avoiding the repeated opportunity cost of stacking every defense.

## Status and limitations

This was a corrected close-to-close research overlay using the exact certified Wealth Core aggregate path, exact holding-state replay and actual Sharadar SHY/BIL/SSO histories. It is not yet an exact next-open ledger certification.

Before promotion, the selected adaptive branch would still require:

1. exact next-open execution;
2. leave-one-crisis-out validation;
3. rolling-start tests;
4. untouched forward shadow;
5. explicit tax and slippage analysis.
