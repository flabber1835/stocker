# Download Sharadar and Alpaca for offline inspection

This command only reads provider APIs and writes local files. It does not run
GO, write the production database, backtest, or submit broker orders. Use the
NAS credentials already in `.env`; never include keys on the command line.

It is optional and separate from GO, deployment and automation. None invokes
this tool or requires its output. Deploy first; run the comparison manually
later, once the deployment is stable. Missing comparison files do not affect GO.

The capture covers the trailing 300 XNYS sessions through an explicit completed
session. Its universe is the union of active Alpaca US-equity assets, current
Sharadar SEP tickers, and SPY/BIL. Metadata preserves each provider's classification,
status and identifiers; membership is not a claim of common-stock eligibility or
cross-provider identity equivalence. Sharadar SEP rows for other symbols are
retained raw but excluded from the normalized comparison files. Missing symbols
and sessions remain missing and appear in `coverage.csv`, including zero-row names.

Use an existing Sentinel Python 3.12 runtime image on the NAS and the checkout
containing these tools. Set `IMAGE` to that image's local name or immutable digest.
This tool runs independently after deployment, using its own output directory.

```sh
cd /volume1/docker/github/stocker
mkdir -p artifacts/provider-comparison/20260929
IMAGE='your-existing-sentinel-runtime-image'
docker run --rm --memory 1g --env-file .env -v "$PWD:/capture-code:ro" -v "$PWD/artifacts/provider-comparison/20260929:/capture" -w /capture-code -e PYTHONPATH=/capture-code:/capture-code/shared -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMAGE" -m tools.provider_capture --end 2026-09-29 --output /capture
```

Choose the latest complete source session for `--end` and a matching new output
directory. Repeat the identical command after an interruption: validated response
pages are reused, and an incomplete pagination chain resumes. Different requests
require a new directory. Do not run two writers against the same output directory.
HTTP failures have bounded retries and print no credential-bearing URL or body.

Copy the entire output directory locally after completion. It contains:

- `raw/`: timestamped original JSON response pages, secret-free request parameters
  and response hashes, including both providers' metadata and action records.
- `request.json`, `universe.json`, `manifest.json`: exact axis/universe, completed
  page chains and completion status. These are capture diagnostics, not certificates.
- `sharadar.csv.gz`, `alpaca.csv.gz`: raw open/close, split-only close, raw volume
  and reported split-adjusted volume by symbol/session.
- `coverage.csv`, `preprocessing.json`: row counts/date coverage and mismatched
  Alpaca raw/split page populations. No absent prices or actions are invented.

Rerun preprocessing offline with `python -m tools.provider_capture --output PATH
--preprocess-only` inside the same Python environment. No credentials are needed.

Alpaca requests explicitly select `feed=sip`, `asof=END`, and separate `raw` and
`split` adjustments. Sharadar raw open equals `open * closeunadj / close`; raw
volume equals `volume * close / closeunadj`, matching production price domains.
Original response rows preserve all other available fields. Absolute adjusted
levels can differ between providers; analysis must compare aligned returns and
rebased series. Symbol mapping is not a historical metadata-vintage guarantee.

Requests across pages and providers occur at different times; neither API gives
this tool an atomic cross-provider snapshot. Capturing raw and adjusted prices
separately can expose revisions during acquisition. Keep those differences for
investigation rather than interpreting every difference as an economic defect.
Alpaca actions are captured with `data_quality=all`; its date filter is process
date, while Sharadar uses its own action date. Absence is not proof of no action.

Provider references: [Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars),
[Alpaca actions](https://docs.alpaca.markets/us/reference/corporateactions-1),
[Nasdaq tables API](https://docs.data.nasdaq.com/docs/tables).
