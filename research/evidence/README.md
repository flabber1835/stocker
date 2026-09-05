# Wealth Core research evidence archive

This branch is a durable GitHub archive for machine-readable research evidence. It is intentionally isolated from the active Strategy 9 experiment branches and does not participate in experiment execution.

## Experiment 5

- Experiment: Wealth Core E5 deterioration-triggered second review with E3
- Source branch: `research/backtester-wc-e5-deterioration-review`
- Exact experiment head: `ed79b9603e1e9d349c85ccd57db12953b5cc2c06`
- GitHub Actions run: `33930932163`
- Run URL: https://github.com/flabber1835/stocker/actions/runs/33930932163
- Artifact ID: `9959923294`
- Artifact SHA-256: `e512748d5d83997526771512fffa7317d57c99a7eee75904d7e1f2a26052ea19`
- Artifact size: `1432658` bytes
- Contract status: `PASS`
- Experiment budget after completion: `5/10`
- Research verdict: rejected as a candidate architecture; evidence is retained.

Permanent machine-readable evidence is stored under:

`research/evidence/wc-e5/ed79b9603e1e9d349c85ccd57db12953b5cc2c06/`

The archived SHA256SUMS file includes hashes of the two full daily replay files (`control_e3/daily.csv.gz` and `candidate_e5/daily.csv.gz`) plus every decision/result artifact used for the experiment. The exact replay source and workflow remain in Git history at the experiment head, so the full daily bundle is reproducible even after the GitHub Actions artifact retention window expires.

## Zero-budget WC -> Sentinel coupling diagnostic

- Diagnostic branch: `research/backtester-wc-sentinel-coupling-diagnostic`
- Exact diagnostic head: `6048825fae989bf747bd6346bb1b37a993559e0a`
- GitHub Actions run: `33935820712`
- Run URL: https://github.com/flabber1835/stocker/actions/runs/33935820712
- Economic experiment budget delta: `0`
- Budget remains: `5/10`

The diagnostic source and workflow are already committed in Git. Its resulting summary, episode ledger, predicate ledger, exit-event ledger, manifest and SHA256SUMS will be archived under `research/evidence/wc-sentinel-coupling/6048825fae989bf747bd6346bb1b37a993559e0a/` after the run emits them.

This archive branch must not be used as an execution branch for E5 or subsequent economic experiments.
