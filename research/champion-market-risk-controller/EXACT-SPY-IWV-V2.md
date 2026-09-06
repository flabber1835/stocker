# Exact SPY / IWV V2 comparison

RESEARCH / NOT CERTIFIED

## Checkpoint and run

- Continuation checkpoint: `c59fe2007496515b933160eef99bb482441fbebf`.
- Executable workflow head: `988cb2cc51b0f61d7c5ed9351b04378f1106ba84`.
- Run: https://github.com/flabber1835/stocker/actions/runs/34013246755
- Workflow: `.github/workflows/champion-index-comparison-v2.yml`.
- Source: `backtester/research_champion_index_comparison_v2.py`.
- Regression suite: `tests/backtester/test_research_champion_index_comparison_v2.py`.

This continuation adds a dedicated V2 exact comparison workflow. The completed screens and refinements remain retained. The frozen Champion and production branches are unchanged by these commits.

## Preselected experiment

The two plateau centers were selected before this exact comparison.

| Settings | Annualized RV20 stress | RV20/RV40 stress | Annualized RV20 healthy | RV20/RV40 healthy |
|---|---:|---:|---:|---:|
| SPY center | 0.26 | 1.15 | 0.20 | 1.00 |
| IWV center | 0.22 | 1.15 | 0.19 | 1.00 |

Sources:
- SPY refinement: https://github.com/flabber1835/stocker/actions/runs/34010915257
- IWV refinement: https://github.com/flabber1835/stocker/actions/runs/34011426678
- IWV selected candidate: `v2r-r3000-vol-0075`.

Run all four fixed cells: SPY/SPY-center, IWV/IWV-center, SPY/IWV-center, IWV/SPY-center. Index contrasts hold the settings fixed. Parameter contrasts hold the index fixed. This supports controlled attribution of an apparent improvement to index choice, threshold choice, or their interaction. The baseline completed run is reused as the frozen-path witness.

## Exact experiment boundary

IWV supplies only Candidate A's market observations: realized volatility, volatility ratio, market returns/drawdown, the 11% rebound input and the market side of cross-surface recovery. The state-transition logic remains the retained V2 implementation.

Native Sentinel continues to use SPY. Candidate B and the SPY benchmark remain unchanged. Wealth Core classifications, eligible universe, ranking, holdings, sizing, exits, terminal conventions, transaction costs, cash factors and next-session raw-open execution remain frozen.

Every completed replay must reproduce all 5,032 baseline sessions and match its rankings, selected-position identities, eligible-universe counts, Native Sentinel targets and signals, raw Wealth Core equity/open-equity path, Candidate B path and SPY benchmark. Float comparisons use explicit 1e-12 tolerances. Candidate A promotion parity and the Native Sentinel allocation ceiling are checked separately.

## Retained data and runtime pins

- Profile: `strategy9-e3-research-champion-v1`.
- Profile SHA-256: `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`.
- Runtime commit: `887f479b15ad861313da666ad698034d3847121c`.
- Runtime Python: `3.12.14`; packages installed from the retained hash-locked runtime requirements.
- Canonical package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`.
- Warmup starts `2006-01-03`; measurement `2006-07-31` through `2026-07-31`.
- Baseline run: `34007704385`, artifact `champion-corrected-classification-34007704385-1`.
- Baseline daily SHA-256: `fbc8a18d2e6f01bbc5154fe359990633bbe93e28b4dbeba57da0be149f4811a8`.
- IWV witness run: `34011322722`, artifact `champion-r3000-proxy-screen-v2-34011322722-1`.
- IWV cutoff SHA-256: `ec57f38bc206466524091c31d0e73edc5b51cb115cfba4e26b62d2c44f712ce9`.
- VIX witness run: `34010233044`, artifact `champion-market-risk-screen-34010233044-1`.
- VIX cutoff SHA-256: `9bf13a7d758cd0727e3fb68d50a32715d6201ed7f0cd220841ecfe2a4901ee4b`.
- Historical-classification corrections SHA-256: `30f1e7223bc088714e4ee17b131f90da61bcbaf0684bfcb9c3331c9d1bc06db3`.

The comparison fetches these retained artifacts. IWV features require an exact date match for every replay session. Source and input hashes are recorded in each completed result.

## Preflight and finalization

The previous superseded V1 alternatives reached the final date and the inspected SPY-vol job failed while serializing `ca.concordance_releases`. V2 already retains that counter. This workflow exercises the actual V2 generated class and the final output-marking/report/checksum path before launching full replays.

The 13-test preflight covers four-cell source assembly, unchanged frozen classes/cash functions, unchanged Native/other-controller inputs, 5,000 exact-versus-screen state transitions, persistence/concordance/rebound routes, final-summary attribute serialization, pinned input coverage, source-tampering rejection, deliberate frozen-path mutations, finalization on the retained baseline fixture for both index labels, next-session execution assignments, causal feature-prefix invariance, and wrapper restoration after an injected failure. All tests must pass and none may be skipped before replay jobs start.

Preflight fixture outputs are regression-test products. They are not performance results of a new index replay.

## Evidence and reporting

Each full replay uploads generated source, full daily output, 5/10/15/20-year metrics, strategy-path worklists, identity manifests, log, immutable-file checksums and frozen-path validation. Live log output retains chronological quarterly/year-end progress. Each successful job publishes its metric table to the GitHub Actions step summary.

A final workflow job consumes compact evidence from all four successful replays and produces `exact-index-comparison-metrics.csv`, `controlled-attribution.json` and `REPORT.md`. Actions artifacts use 90-day retention. The workflow, source, tests and this reproduction note are committed to Git history.

## Reproduction

Check out the executable workflow head. Retrieve and authenticate the named artifacts and canonical package; install the runtime pinned above. Run the regression suite with the three witness environment variables set as in the workflow. Then execute each cell:

```bash
python backtester/research_champion_index_comparison_v2.py \
  --output index-comparison/IWV-iwv-center \
  --market-proxy IWV --parameter-set iwv-center \
  --baseline-daily /tmp/comparison-baseline/daily.csv.gz \
  --iwv-csv /tmp/comparison-iwv/iwv-cutoff-through-2026-07-31.csv \
  --vix-csv /tmp/comparison-vix/vix-cboe-cutoff-through-2026-07-31.csv
```

Repeat with the other three registered index/settings pairs. The workflow contains the full checkout, dependency, package-verification and artifact commands.

## Interpretation limits

The full twenty-year interval has been used for strategy research and parameter selection. This is an in-sample exact replay comparison. A stable parameter neighborhood is a local sensitivity result, not an out-of-sample performance guarantee.

IWV is the retained vendor-adjusted ETF-price proxy used by the completed screen. Its historical-vintage data certification remains pending. The repository's strategy-path PIT certification also remains pending. The stock-selection universe remains the corrected broad universe; this experiment does not restrict it to Russell 3000 membership.
