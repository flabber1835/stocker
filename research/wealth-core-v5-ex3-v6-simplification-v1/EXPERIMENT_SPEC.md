# Wealth Core V5 / Sentinel EX3 V6: mechanics simplification v1

Preregistered 2026-09-10. Tracking issue: #349. User budget: **10 full-PIT replay starts maximum**, baseline plus nine treatments. Research only. No production promotion or merge is authorized.

## Authority and fixed economics

Repository base: `96f705c3b699ec283dbac7e93b973dba9769f038` (verified with authenticated fetch and GitHub). Delivery: feature branch and PR to main.

Economic oracle: `r40_m04_rec8`, run [34319850800](https://github.com/flabber1835/stocker/actions/runs/34319850800), experiment source `54af0c9e50e4bf0c0d4242dafcf7fff0b75eb0f3`. Exact generated source SHA256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`. This file is reused byte for byte; its inherited header describes an older non-PIT ancestor. Runtime mode, dataset verification and the generated implementation establish this experiment's full-PIT identity. Production-port changes in PR #342 are not the oracle.

Dataset SHA256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`. Warmup 2006-01-03; measurement 2006-07-31 through 2026-07-31, exactly 5,032 sessions. Frozen dependency/runtime checkouts and package digest match the impedance experiment. Python 3.12.14 and hash-locked dependencies.

Core remains Median5, leading three, 20 slots, 5% intended entries, one entry per day after initialization, 30% owned-episode trailing stop, 119-session review and 21-session cooldown. Preserve broad PIT universe, signal/raw price domains, total-cash one-share admission, 10bp reserve predicate, next-valid-open integer sizing, sells before buys, 10bp costs, one-session dividend lag, cash sleeve factors and overnight allocation timing. No broker inputs. Reuse the frozen research oracle; no replacement production book.

## Matrix (fixed before outcomes)

| Slot | Arm | Change from oracle | Intended claim |
|---:|---|---|---|
| 1 | baseline | Exact r40_m04_rec8 source | Reproduce authority |
| 2 | selective_peers | Skip peer calculations for holdings whose amber classification is already fixed by own damage or green; keep every holding eligible as a neighbor | Exact economic and allocation parity |
| 3 | bounded_counters | Saturate decision counters at their largest predicate thresholds; retain diagnostic totals and all cause flags | Exact economic and allocation parity |
| 4 | map65_to55 | Map final 65% output to 55%; preserve original internal recovery state and timing | Isolate value of the 65% exposure level |
| 5 | ramp10 | Fragile recovery: one 55% stage, 10 healthy closes, then full; preserve prior-close threshold-check timing | Remove a ramp stage |
| 6 | ramp20 | Fragile recovery: one 55% stage, 20 consecutive healthy closes, then full | Remove a stage with a longer confirmation |
| 7 | no_peers | Damaged breadth uses own DD <= -10% or own R21 <= -3%; green unchanged | Remove residual histories and peer network |
| 8 | no_cross_surface | Disable cross-surface early recovery route | Remove one recovery route and its required comparison |
| 9 | no_spy_rebound | Disable SPY rebound release for episode and divergence latch | Remove one recovery route |
| 10 | combined | no_peers + ramp20 + no_cross_surface + no_spy_rebound | Test a substantially smaller controller |

ramp20 is deliberately not described as equivalent to two ten-close blocks: intermediate resets and checkpoint timing differ. map65_to55 retains internal previous-desired memory to isolate exposure-level economics. The combined arm is fixed now and will run even if its individual components perform poorly; it is an interaction test, not adaptive selection.

The peer network links each held stock to up to three held stocks with the highest qualifying residual-return correlations (252 prior sessions, at least 120 observations, correlation >= .145; security-id tie break). Self is included when counting red neighbors; at least half red can make a non-green holding amber. It changes the controller's damage sensor, never Core selection.

## Gates and materiality

Before any replay: verify source hash, compile all ten generated sources, and enforce AST changes only inside `Native`, `CandidateA`, or `dynamic_peer_breadth`. Synthetic differential and boundary tests falsify exact-equivalence claims, peer short-circuit handling, output-only mapping, route removal, ramp timing, and source guard behavior. No Core AST change is permitted.

Baseline must reproduce the frozen full Core tape hash `3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f`, transaction hash `0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da` and close-decision hash `d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724`. Require 0/55/65/100 allocation counts 634/252/20/4126, 28 allocation transitions, 8 episodes, 2 cross-surface releases, and published 20y metrics within their rounding precision (CAGR 21.5572%, max DD -27.3755%, Sharpe 1.1211, multiple 49.6193). These are validation outputs only.

Every arm requires identical Core economic projection, transactions and close decisions. The original Core tape hash includes `damaged` and `green`; breadth treatments intentionally change `damaged`. Therefore compare a separate Core projection excluding those two sensor columns against the new verified baseline. All other original Core columns remain exact. Non-breadth arms also require the original full hash. Arms 2 and 3 require exact allocation, A NAV and reason paths; bounded diagnostic streak values may differ.

A candidate passes economic screening only when **every** trailing 5/10/15/20-year window meets: absolute CAGR difference <= 0.25 percentage points/year; max-drawdown deterioration <= 1.0 percentage point; absolute ending-multiple ratio change <= 5%. Improvements exceeding the symmetric return limits also fail the preservation claim. No selection on highest CAGR.

Report Sharpe, longest underwater spell, worst daily return, daily expected shortfall (worst 5%), allocation turnover, transition counts, changed-allocation sessions, maximum NAV path divergence, and crisis subperiods. These are review diagnostics, not post-hoc tunable pass thresholds. Economic screening is historical evidence and does not establish future equivalence. Prefer the smallest surviving mechanism set; call exact paths historical parity, not a universal proof.

## Budget, staging and evidence

Only the first run of this workflow may launch full replays. Each arm atomically claims a unique slot by creating a durable GitHub git reference immediately before `module.run()`. Reusing a slot fails closed, including workflow reruns. The branch refs under `research-budget/simplification-v1/slot-01` through `slot-10` bind slot consumption to a commit. Cheap preflight, dataset staging and analysis of retained tapes do not consume backtester slots. A failed replay after claiming its slot still consumes that slot. No automatic retries or eleventh arm.

Run baseline first, then nine arms only after its validation passes. Preserve generated source, source/runtime identity, manifests, daily tape, transactions, close decisions, telemetry, summary, logs and checksums as per-arm GitHub Actions artifacts (90-day retention). Aggregate all ten outcomes, including failures/missing evidence, into a machine-readable verdict and a GitHub issue comment. Missing evidence is INCOMPLETE, never a pass. All summaries include source/run identity and artifact links. Commit the final interpretation and relevant compact result files to this research branch after completion; artifacts retain large tapes.

## Design scope

Changes are confined to research scripts, specification and one explicitly scoped workflow. The workflow borrows the frozen impedance runtime staging. Production controller, execution, feed, data and golden fixtures are unchanged. A successful treatment is a candidate for a separately reviewed implementation and certification effort.
