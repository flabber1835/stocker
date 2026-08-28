# A/B/C sector-grouping experiment

**Branch:** `research/backtester`
**Experiment:** `2026-08-27-sector-abc`
**Strategy source:** exact `main@c502d077cae9c494f8b74a41ee8be7f40b25837d`
**Replay:** fresh chronological, no prerecorded decisions/oracles/tapes

This experiment implements the contract in `docs/backtester-experiment-contract.md`.

## Question

Measure the economic effect of changing only the grouping used by Sentinel's per-holding contagion / sector-stress clause while keeping Wealth Core, individual breadth predicates, native Sentinel, Simplified Concordance LD-RC, execution timing, accounting, and all other inputs/mechanics identical.

## Arms

### A — current production grouping

Run the exact current-main production strategy. The historical replay uses the same current Sharadar TICKERS metadata surface that the current-main no-oracle integration differential uses for its historical control. In particular, A uses current Sharadar `sector` labels. This metadata domain is explicitly **not PIT**.

### B — causal SEC SIC -> FF12 grouping

Identical to A except the `sector` grouping supplied to the breadth/contagion calculation is replaced by causal FF12 industry membership.

Authority already stored on this branch:

- `research/sentinel-fastgate/pit-evidence/generated/sec_sic_submissions.csv.gz`
- `research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz`
- `research/sentinel-fastgate/pit-evidence/ff12_sic_definition.txt`

Decision rule: issuer CIK evidence and SIC evidence must be public before the decision session; SIC uses the latest observation satisfying `filed < decision_session`. Missing causal evidence becomes a singleton `UNKNOWN:<security_id>` peer and never falls back to current Sharadar sector.

Only the grouping changes. Current-main category, issuer metadata, Wealth Core selection and accounting remain the same as A.

### C — causal dynamic correlation peers

Identical to A except sector contagion is replaced by a prior-only dynamic peer neighborhood.

For each decision session and each currently held security:

1. use at most the prior 252 trading sessions, ending strictly before the decision session;
2. require at least 120 common finite security/SPY return observations;
3. estimate beta from the prior observations and form market-residual returns;
4. calculate pairwise Pearson residual correlations among current holdings;
5. retain up to the three strongest peers with residual correlation >= `0.145`, ties broken by permanent security id;
6. define the holding's peer neighborhood as itself plus those peers;
7. replace current-main sector stress with RED fraction in that neighborhood;
8. apply the unchanged current-main contagion threshold (`>= 0.50`) and unchanged `not green` condition.

GREEN, RED, individual AMBER clauses, denominator, native Sentinel thresholds, LD-RC and all other logic remain current-main.

This is an experiment definition, not parameter tuning. The 252/120/3/0.145 values are frozen before the run and are derived from the retained causal dynamic-peer research configuration already on `research/backtester`.

## Chronology

The replay starts in 1998 to establish rolling features and path-dependent strategy state naturally. For every historical session:

1. build the causal/common session input;
2. evaluate A, B and C for that same session before advancing time;
3. assert Wealth Core economic state remains identical across A/B/C;
4. record each arm's controller/LD-RC response;
5. apply the decision at the next executable open using the same timing/accounting model for all arms;
6. advance to the next session.

No prior holdings, decisions, allocations, crisis dates or NAV curves may be read.

## Measurement windows

All windows end at 2026-07-31 and are measured from the replay's freshly generated NAV:

- 5 years: start 2021-07-30
- 10 years: start 2016-07-29
- 15 years: start 2011-07-29
- 20 years: start 2006-07-31

Report CAGR, daily Sharpe (`sqrt(252)`, zero risk-free rate), and maximum drawdown for A/B/C plus SPY.

## Input boundary

All market/PIT input files must already exist on `research/backtester` before this run. The experiment may validate/join/filter them in memory but may not construct missing PIT history or fetch replacement history.

The run must hash and retain its exact declared inputs and fail before economic replay on missing/mismatched required evidence.

## Output

GitHub Actions artifact only. The workflow has `contents: read` permission and no repository write path. Required outputs:

- `metrics.csv`
- `summary.json`
- `daily.csv.gz`
- `manifest.json`
- `SHA256SUMS.txt`

A headline result is valid only if the fresh A control completes, A/B/C Wealth Core parity holds, all declared input hashes are recorded, and the chronological replay completes without a causal/data refusal.
