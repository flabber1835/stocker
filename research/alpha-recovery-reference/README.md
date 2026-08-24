# Alpha-recovery reference controller

**Status:** research-only; not wired to production, paper trading, certification, or deployment authority.

**Pinned baseline:** `main` at `22ebcf48addadbc7ec4531df415041d1b8674f48` (`Final overnight dual-deploy hardening (#245)`).

**Reference identity:** `sentinel-concordance-alpha-recovery-reference/1`.

## Objective

This reference aims to recover CAGR lost in the signal-to-exposure architecture without changing Wealth Core stock selection. It isolates two hypotheses:

1. **Fast-contagion discrimination.** Static structural peers remain useful for slow stress, while prior-only market-residual similarity and historical co-distress decide whether a symbolically controllable FAST branch is genuine contagion.
2. **Actuator composition.** The first unconfirmed FAST warning receives a cheap 55% provisional response. It does not create an LD-RC recovery episode. A persistent or independently corroborated warning becomes confirmed 0% severe risk-off. A provisional warning that disappears restores immediately rather than remaining at 55% for a seven-session recovery certification.

The current authoritative LD-RC starts a recovery episode on every native 100% -> below-100% transition. That remains the retained strategy, but it is a structural mismatch when a new provisional 55% state is composed in front of it. This candidate gives recovery ownership only to confirmed severe states.

## Architecture

```text
prior-only held-security histories
        |
        +-- exact min/max peer-damage geometry
        +-- 252-session SPY-beta residual correlation
        +-- 252-session co-distress/Jaccard
        |
FAST branch: impossible / controllable / inevitable
        |
        +-- inevitable -----------------------------> confirmed
        +-- controllable + causal corroboration ----> confirmed
        +-- controllable without corroboration -----> warning only
        |
RISK_ON 100%
   | first unconfirmed warning
   v
PROVISIONAL 55% -- warning clears --> RISK_ON immediately
   | second warning or independent confirmation
   v
CONFIRMED_SEVERE 0%
   | minimum hold + healthy recovery
   v
RECOVERY 55% -> 65% -> 100%
                    ^
                    final full risk requires seven live healthy
                    independent-witness sessions or SPY r20 > 11%
```

## Causal dynamic peer approximation

All return and distress histories must end at `t-1` for a close-`t` decision.

- Prior 252-session returns, minimum 120 aligned observations.
- Remove rolling SPY beta: `residual = asset return - beta * SPY return`.
- For vulnerable holdings, measure residual correlation to currently RED held names.
- Vote across `0.145`, `0.150`, and `0.155`; require two votes.
- Independently select three historical co-distress peers by Jaccard similarity.
- Confirm a controllable warning when residual voting passes and either co-distress corroborates or the exact symbolic minimum damage is at most 75%.

The threshold majority is deliberate. The retained exploratory result was brittle around one `0.15` cutoff, while the immediate neighborhood reproduced the same path. This is still a research prior, not a certified result.

`build_peer_snapshot()` accepts exact symbolic minimum and maximum damaged breadth. Its fallback bounds—current core-amber breadth as minimum and every non-green holding as maximum—are conservative scaffolding and are not promotion-grade substitutes for the exact geometry adapter.

## Confirmed recovery

- Minimum ten severe-state sessions.
- Three consecutive healthy sessions.
- Healthy: shadow `r20 > 0`, damaged breadth `<= 60%`, green breadth `>= 20%`.
- Fragile or non-concordant recovery begins at a real 55% basket.
- Ramp: 55% -> 65% -> 100%, ten healthy confirmations per promotion.
- Final 100% requires seven healthy recent-leadership witness sessions or `SPY r20 > 11%`.
- Once native full-risk promotion is earned, readiness stays latched while only the witness remains outstanding. A later unhealthy shadow day does not manufacture another ten-session delay.

The simplified LD-RC divergence trigger is retained:

```text
WC drawdown <= -10%
AND witness r20 <= -8%
AND SPY r20 >= 0%
    -> latch 55% ceiling
```

## Files

- `reference_implementation.py` — pure signal builder, branch classifier, state machine, durable state codec, next-open execution, and generic replay.
- `test_reference_implementation.py` — focused mechanics and sequencing tests.
- `TEST_RESULTS.txt` — retained local test output.

The code has no database, network, clock, broker, or production-controller dependency and uses only Python's standard library.

## Required 2x2 replay

| Arm | FAST peer signal | Provisional/LD-RC composition |
|---|---|---|
| A | Current authoritative | Current authoritative |
| B | Dynamic causal | Current authoritative |
| C | Current authoritative | Provisional decoupled |
| D | Dynamic causal | Provisional decoupled |

Before candidate CAGR is interpreted, Arm A must reproduce the current authoritative 20-year fingerprint session by session: `22.6302156206%` CAGR, `1.2138138710` daily Sharpe, `-21.6958215%` max drawdown, and `59.1542869x` ending multiple. A PIT control must separately reproduce corrected issue #244.

Report 5/10/15/20-year CAGR, Sharpe, max drawdown, SPY comparison, transitions/cost, time at each exposure, provisional and confirmed episodes, saved-loss and missed-rebound attribution, rolling starts, leave-one-crisis-out, and threshold-neighborhood stability.

## Performance claims and non-claims

This reference has **no full-corpus result yet**. It aims to recover alpha; it does not claim recovery until the control gates pass.

The earlier exploratory dynamic-peer harness suggested about +1.63 percentage points per year versus its own causal FF12 baseline. That issue was later retracted because its nominal current-sector baseline did not reproduce the authoritative 22.63% control. Therefore +1.63 pp/year is a design prior, not a transferable result.

## Test command

```bash
cd research/alpha-recovery-reference
python -m unittest -v test_reference_implementation.py
```

No file here authorizes modification of `sentinel/controller/`, `sentinel/core/production.py`, strategy identity, deployment artifacts, or live state. Promotion requires a separate reviewed implementation and recertification.
