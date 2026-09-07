# Median-5 adversarial validation plan

## Objective

Run eight isolated causal 20-year PIT stress tests on the hardened Median-5 candidate before any promotion decision.

## Frozen candidate

- Caesar 20 accounting: 20 slots, 5% entry weight
- Median-5 admission hardener: reorder only today's canonical top three by median durable rank over the latest five decision sessions
- corrected one-session dividend settlement
- immutable canonical PIT package
- frozen classifier/source/runtime pins
- baseline costs, liquidity, cooldown, review, stop, terminal and defensive semantics except for the single stress dimension named by each arm
- no prerecorded decisions and no future information

## Arms

1. `M5_ENTRY_DELAY_1` — one additional session before reserved entry execution.
2. `M5_ENTRY_DELAY_2` — two additional sessions before reserved entry execution.
3. `M5_EXIT_DELAY_1` — one additional session before ordinary stop/review exit execution; first signal date is sticky.
4. `M5_COST_25BPS_RT` — symmetric 12.5 bps each side, 25 bps round trip.
5. `M5_COST_50BPS_RT` — symmetric 25 bps each side, 50 bps round trip.
6. `M5_LIQ_ADV40M` — ADV20 floor raised from $20M to $40M.
7. `M5_LIQ_ADV80M` — ADV20 floor raised from $20M to $80M.
8. `M5_LIQ_DAYDV10M` — same-day dollar-volume floor raised from $5M to $10M.

The previously completed strict top-3 reversal confirmation for Median-5 is not repeated here.

## Acceptance interpretation

Median-5 is considered broadly hardened only if these stresses preserve economics comparable to the corresponding Caesar 20 stresses and reveal no new dominant fragility. The suite is diagnostic; no arm is selected by outcome information.
