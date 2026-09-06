# Research Champion market-risk controller robustness study

**RESEARCH / NOT CERTIFIED**

This directory records the methodology, provenance, experiment lineage, and final evidence for the classification-independence study. No Champion strategy economics are promoted by this work and no merge is implied.

## Frozen baseline

- Repository: `flabber1835/stocker`
- Frozen Champion source branch at study start: `research/champion-pit-metadata-closure`
- Study start head: `2423e4cb44e2e6fe7158b698d5aaeea1a6479c8c`
- Research branch: `research/champion-market-risk-controller-robustness`
- Frozen profile: `strategy9-e3-research-champion-v1`
- Corrected baseline replay: GitHub Actions run `34007704385`
- Baseline artifact id: `9981966560`
- Baseline `daily.csv.gz` SHA-256: `fbc8a18d2e6f01bbc5154fe359990633bbe93e28b4dbeba57da0be149f4811a8`
- Runtime source pin: `887f479b15ad861313da666ad698034d3847121c`
- Corrected 20-year baseline: CAGR `20.0888%`, max drawdown `-23.8319%`, Sharpe `1.1047`, ending multiple `38.9092x`.

## Research question

Determine whether the LDRC market-risk observation layer can be made materially independent of historical security classification while retaining the Champion's useful defensive behavior and economic quality.

The proven dependency under study is:

`security classification -> eligible universe -> recent leadership basket -> recent_r20/recent_r40 -> LDRC -> allocation`

The replacement target is the observation layer. Wealth Core, security universe, corrected classification ledger, ranking, position sizing, execution timing, transaction mechanics, Native Sentinel, cash mechanics, and unrelated controller economics remain frozen.

## Point-in-time market data

SPY observations come from the same immutable replay package used by the corrected Champion. VIX observations use Cboe VIX historical daily closing values. The study stores a cutoff witness ending `2026-07-31` so later Cboe rows cannot change this experiment. Pinned cutoff SHA-256:

`9bf13a7d758cd0727e3fb68d50a32715d6201ed7f0cd220841ecfe2a4901ee4b`

All market-close observations set targets for the next session open. No future-session observation is consumed by the controller.

## Controller families

The independent families are:

1. SPY price state: 20-day return, 40-day return, drawdown.
2. SPY realized volatility: 20-day realized volatility and 20d/40d volatility ratio.
3. VIX level/change: VIX level and five-session change.
4. VIX percentile: 252-session percentile and rolling z-score, with VIX direction for recovery confirmation.
5. SPY + VIX: joint SPY deterioration and elevated VIX state.

The current leadership controller remains the control.

## State-machine preservation rule

The methodology-valid V2 track preserves Candidate A's controller mechanics:

- Native-Sentinel episode creation
- persistence streak accounting
- existing `SPY 20d return > 11%` rebound route
- cross-surface early-recovery route
- latch and clear behavior
- `55%` allocation ceiling while latched
- one-session target timing
- transaction-cost and cash handling in exact replays

Only the observations supplying `stress`, `full healthy`, `positive/recovering`, and recovery-confirmation state are changed for independent families.

## Experiment lineage

### Exploratory V1 — superseded for final selection

- Coarse screen: run `34010233044`
- Refined screen: run `34010436487`
- Exact matrix: run `34010509495`

V1 identified SPY realized volatility as the strongest family in a proxy screen. During exact-replay review, V1 was found to simplify part of Candidate A's recovery state machine. V1 is retained as exploratory evidence and is excluded from the final controller-selection verdict.

### Methodology-valid V2

- Observation-only coarse screen: run `34010839114`
- Refined V2: pending the coarse result
- Exact V2: pending refined plateau selection

V2 is the authoritative controller-comparison track.

## Robustness design

Two separate robustness mechanisms are measured.

### Mechanism 1 — stock selection

A universe/classification perturbation can change the Wealth Core eligible set and stock-selection path. The existing EQM attribution replay already demonstrates this mechanism.

### Mechanism 2 — controller input

A universe/classification perturbation can change the leadership basket and therefore LDRC allocation even when stock selection is held fixed. New diagnostics perturb only the leadership witness after Wealth Core ranks and selected positions are fixed.

Generic leadership-only perturbations include cutoff removal/addition, small baskets, and deterministic seeded swaps. Targeted perturbations include reintroducing the known EQM/PDS classification defects to the leadership witness and removing high-contact inferred-common leadership names.

The intended property of a classification-independent controller is exact invariance to these leadership-only perturbations.

## Selection rule

No controller is selected from the highest-CAGR point. A replacement must show a broad parameter plateau, materially lower direct classification sensitivity, comparable drawdown control, reasonable CAGR retention, interpretable causal behavior, simple PIT-safe dependencies, and no obvious dependence on a single crisis episode.

## Required final evidence

The final committed evidence will include:

- exact comparison table
- 5/10/15/20-year trailing CAGR
- max drawdown, Sharpe, ending multiple
- reduced-exposure sessions and episode durations
- 2008, 2018, 2020, 2022 behavior and worst calendar year
- recovery timing
- first allocation divergence and changed sessions
- episode-level avoided loss / missed upside attribution
- parameter plateau data and plots
- leadership/classification perturbation dispersion
- equity, drawdown, allocation, and controller-state plots
- artifact/run provenance and SHA-256 manifests
- final verdict under the predefined four-way decision rule
