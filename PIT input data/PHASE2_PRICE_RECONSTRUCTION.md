# Orion Phase-2 PIT price reconstruction

This file documents the implemented Phase-2 reconstruction boundary for the Orion research branch.

The runner `.github/workflows/orion-build-pit-prices.yml` executes `PIT input data/build_phase2_prices.py` using only the pinned Sharadar SEP, ACTIONS, and SFP sources already committed to the research branch. It uses no TICKERS metadata and no external market-data source.

The builder may read Sharadar `open`, `close`, and `closeadj` only inside the temporary reconstruction workspace. Those levels are not copied into `PIT input data`. The committed outputs contain only causal or scale-invariant derived quantities.

For SEP, the output is annual and contains:

- `ticker`
- `date`
- `raw_open = open * closeunadj / close`
- `signal_open` and `signal_close` in a causal split-normalized coordinate whose scale is fixed at the ticker's first observed session
- `split_factor_step`, the event-local change in `close / closeunadj`
- `effective_split_ratio`, matching the frozen standalone split-reconciliation rule on ACTIONS split dates
- `dividend_basis`, emitted only for same-session split+dividend cases

For SFP SPY/BIL, the output contains:

- `ticker`
- `date`
- `raw_open`
- `raw_close`
- `close_to_close_factor`
- `prior_close_to_open_factor`
- `open_to_close_factor`

The adjusted SFP level is never retained; only ratios in which its arbitrary future adjustment scale cancels are emitted.

The workflow fails closed if source hashes do not match the Phase-1 manifest, output headers differ from the whitelist, an adjusted/raw source level leaks into an output schema, any generated file exceeds the normal GitHub file-size boundary, or the exact output set is not 30 data files.

The generated `PRICE_RECONSTRUCTION_MANIFEST.csv` and `PRICE_RECONSTRUCTION_AUDIT.json` are committed together with the data files.

This phase reconstructs the price domain only. It does not yet replace current-snapshot category, sector, issuer identity, or terminal-settlement evidence, and it does not by itself certify the full Orion CAGR replay.
