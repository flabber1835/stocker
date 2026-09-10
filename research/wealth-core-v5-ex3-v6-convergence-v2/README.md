# Wealth Core V5 + Sentinel EX3 V6 — Convergence V2

Research only. No production promotion authority is created by this experiment.

## Pinned authority

- Current published EX3 V6 authority: `main@96f705c3b699ec283dbac7e93b973dba9769f038`, `docs/sentinel-ex3-v6.md`.
- Variant: `r40_m04_rec8` (`LDRC_REC=8`, full-recovery `recent_r40 > -0.04`).
- V6 selected-source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`.
- Canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
- Measurement window: `2006-07-31` through `2026-07-31` (5,032 sessions).
- Frozen V5 Core tape / transaction / close hashes: `3b40a23a...`, `0e482822...`, `d1f557bd...` as recorded by the V6 authority.
- Replay harness authority reused by exact hash: `eaddca3f04f279e99663f832bf7293e92ee15662`. It is infrastructure, not controller authority.

## State map

### Wealth Core V5

| State | Classification | Why it can affect the future |
|---|---|---|
| slot `tid`, quantity, entry signal, entry day | economically necessary / irreducible path state | determines the assets owned, P&L, age and next vacancy |
| per-position trailing `peak` | economically necessary / irreducible path state | the 30% trailing stop depends on the path since entry |
| `reviewed`, pending sell and sell reason | economically necessary memory | the 119-session review is one-shot and can schedule a next-open exit |
| pending admission `tid/shares/signal_day/intended_capital` | economically necessary memory | preserves decision-close / next-open execution and V5 open-sizing economics |
| cash and receivables | economically necessary / irreducible path state | whole-share affordability and one-slot admission depend on available cash |
| `sec_ready` cooldown | economically necessary until expiry; canonicalizable after expiry | sold securities are excluded for 21 sessions |
| terminal pending and last trustworthy raw mark | economically necessary memory | terminal-event settlement can retain a position and affect cash/vacancies |
| slot `ready_day` | economically necessary memory | controls when a vacancy can admit a replacement |
| `initialized` | economically necessary mode bit | initial population can fill many vacancies; normal operation fills one vacancy per close |
| 260-close ring and 126/21/20 rolling arrays | bounded current evidence / implementation memory | momentum, volatility and liquidity are recomputed from bounded PIT observations |
| `prior_recent_sel`, `prior_close_map`, recent-leadership NAV history | bounded current evidence | creates causal R20/R40 leadership inputs used by EX3; it is not incumbent-holding preference |
| `shadow_eq` history / cumulative Core peak | economically necessary derived path state | Native Sentinel drawdown uses the Core NAV path/high-water mark |
| historical `durable` ranking | **not persistent** | V5 recomputes the ranking each close from current PIT evidence |
| incumbent ranking hardening | **absent in this authority** | held names are skipped during admission, but they receive no persistent ranking bonus |
| vacancy sequence | irreducible path consequence | after initialization only one ready vacancy is filled per close, so different exit dates create different replacement dates |
| telemetry/hash counters | implementation memory | no decision semantics |

The dominant Core butterfly mechanism is structural: `holding -> return path -> NAV/peak/exit -> vacancy date -> current ranking/affordability -> replacement -> new return path`. There is no baseline attractor and no daily portfolio rebalance that would erase this chain.

### Native Sentinel

Persistent state in the exact controller:

- ordinary episode: `ordinary`, `binary_armed`, `ordinary_age`, `ordinary_h`;
- base-fast episode: `base_fast`, `base_fast_armed`, `base_fast_age`, `base_fast_h`;
- slow-damage anchor: `base_anchor`, `base_dur`;
- fast episode: `fast`, `fast_armed`, `fast_age`, `fast_h`;
- slow episode: `slow`, `slow_age`, `slow_h`;
- recovery ramp: `ramp`, `ramp_idx`, `ramp_h`;
- severe-recovery evidence: six-value `r40hist`.

Classification:

- **Economically necessary hysteresis:** active episode bits, all armed bits, `base_anchor`, recovery-ramp mode/index, and R40 recovery evidence while a severe episode is active.
- **Potentially canonicalizable semantic quotients:** ordinary age `>=20`, base-fast age `>=10`, fast age `>=9`, slow age `>=19`, base duration `>=30`, healthy streaks once their thresholds are reached, ramp healthy streak `>=10`.
- **Implementation/dead state:** inactive episode ages/streaks, inactive ramp fields, and R40 recovery history when neither fast nor slow is active.
- **Irreducible upstream path input:** Core drawdown/high-water mark and Core NAV supplied to Native.

A fixed observation window cannot uniquely reconstruct all Native state. Armed flags can retain an old disarming event until a re-arm condition occurs. `base_anchor` can remain live for the complete duration of a base episode. The minimal sufficient representation is therefore finite-dimensional state plus current observations; it is not a pure rolling-window function.

### EX3 V6

Persistent state:

- `episode` — remembers a native defensive episode through the full-risk recovery decision;
- `latched` — retains the LD divergence cap until authoritative release evidence;
- `full_streak` — thresholded at REC8;
- `recent_positive_streak` — thresholded at REC8 while an episode is active;
- `prev_native` — only its full-vs-not-full equivalence class matters for the next episode-start transition;
- `prev_desired` — economically necessary because full-risk recovery can hold the prior desired exposure;
- `episodes`, `concordance_releases` — telemetry only.

V1 cleared `episode` and `latched` and wrote `desired=native` after a neutral timeout. Those are economically active variables. V1 therefore changed hysteresis and exposure; it did not merely canonicalize representation.

## V2 intervention

V2 implements the semantic quotient only:

1. run the untouched authoritative Native transition and compute today's native target;
2. normalize future-inert Native bookkeeping after the decision;
3. run untouched authoritative EX3 V6 logic using the treatment Native path;
4. normalize future-inert EX3 counters after the decision;
5. apply the resulting target at the same next-session open timing as the control.

V2 never writes an exposure target during canonicalization. It never clears an active episode, latch, armed bit or anchor. It has no baseline-path input and no future input.

The six-session R40 history is cleared only when both `fast` and `slow` are inactive. A newly entered fast episode cannot clear before its age reaches 9; slow cannot clear before age 19. Both exceed the six-value recovery lookback, so stale pre-episode R40 values are overwritten before they can be consumed.

## Causal trace from completed V1 evidence

A high-amplification deterministic leave-one-out case (`security_id=301606049357818446`) demonstrates the actual loop:

1. Core holdings first diverge on `2007-08-24`.
2. The excluded security is gone from the baseline after `2007-11-12`.
3. Core paths diverge again by `2007-12-11`; the original omission has become a replacement-path difference.
4. By `2010-05-28` the two runs have the **same held-security set**, the same damaged breadth (`0.7778`), the same green breadth (`0.2222`), and the same leadership R20/R40. Core NAV and high-water paths remain different.
5. Baseline had crossed the ordinary drawdown trigger earlier (`2010-04-16`); the perturbed run crossed later (`2010-04-27`). The baseline therefore reaches the 30-session base-duration slow condition first.
6. On `2010-05-28` baseline `slow_signal=True` and native target becomes `0`; perturbed `slow_signal=False` and native remains `1`.
7. The allocation difference appears at the next session open, preserving causal timing.

This is a full chain from one-security membership perturbation to a much later controller difference after the original security is economically gone. The key amplifier is the interaction of legitimate Core NAV/high-water path dependence with Native duration/anchor hysteresis.

The same V1 campaign contains ordinary leave-one-out cases where Core membership differs but Native and EX3 allocations never diverge. Exact portfolio-path equality is therefore neither necessary nor sufficient for controller-path equality.

## Hypothesis and decision rule

The key falsifiable hypothesis is:

> There exists materially harmful Sentinel butterfly amplification caused by state distinctions that are future-inert under the authoritative controller semantics.

If that is true, V2 can preserve the unperturbed baseline exactly while reducing native-target or final-allocation divergence under perturbation.

If V2 preserves baseline exactly and produces identical controller paths in perturbations, then the previous V1 gain came from weakening economically active hysteresis. The correct endpoint is to accept legitimate controller response, stop pursuing exact path convergence, and certify Wealth Core by perturbation-distribution stability.

## Staged experiment

1. **State tests:** idempotence, threshold-equivalence classes, active-hysteresis preservation, no exposure write, inactive-R40 horizon proof, exact source/timing seams.
2. **Exact 20-year baseline A/B gate:** require zero native-target differences, zero allocation differences and numerical NAV identity. Any failure stops V2.
3. **Small screen:** deterministic cases fixed before V2 outcomes: four known high-amplification V1 leave-one-outs, two ordinary V1 leave-one-outs, one fixed-seed 1% universe dropout.
4. **Full campaign:** only if the screen reduces controller divergence while the baseline gate remains exact; 16 deterministic leave-one-outs plus three fixed-seed 1% dropouts.

Primary reporting keeps Core, Native and EX3 divergence separate and reports post-exclusion persistence, durable/terminal reconvergence, path amplification and economic amplification.
