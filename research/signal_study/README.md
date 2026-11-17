# Retained-history signal study

Design: `docs/sentinel-signal-study.md`.
Findings: `docs/sentinel-signal-study-results.md`.

The modules read an authenticated fractional Core snapshot and saved target
oracle. They do not run the Core engine, restore a checkpoint, touch a broker or
produce a candidate for promotion. Extraction reads the four retained replay
directories without modifying them.

Run inside the pinned research environment with the same libraries as the
exposure/structured-search tools:

```text
image sha256:0b51f28b657f2e634fb8804bf3fb952b07261d40d295acaa6b9a2a9d78e0415a
Python 3.12.13
NumPy 2.4.6
SciPy 1.16.3
scikit-learn 1.7.2
Plotly 6.5.0
```

Use no network, read-only source/input mounts, a separate writable output, half
a CPU, 1 GiB, one BLAS thread and `PYTHONDONTWRITEBYTECODE=1`. In the retained
launch, `PYTHONPATH=/source:/source/shared:/plotting-libs:/neural-libs`.

```bash
python -B -m research.signal_study.extract \
  --snapshot /snapshot --archive /archive --output /output/observations-001

python -B -m research.signal_study.run \
  --snapshot /snapshot --observations /output/observations-001 \
  --anchor /anchor --output /output/run-001

python -B -m research.signal_study.review --result /output/run-001

python -B -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_signal_study.py tests/sentinel/test_signal_study_mutations.py
```

Both output directories must be new. Review refuses to overwrite its evidence.
The local Windows launch receipts in
`.codex-tmp/sentinel-signal-study-20261116/` contain exact Docker argument arrays
and source locations. They preserve the stopped source replay separately from
the common snapshot. Do not call any replay storage `restore` function: that is
a state-changing operation and is not needed for this study.

Important outputs:

- `observations-001/`: authenticated checkpoint inventory, observation values
  with original dates and preservation origins, coverage and Core guard receipt.
- `run-001/protocol.json`: predeclared feature/model/horizon settings, fold
  boundaries, source hashes and input identities.
- `anatomy.json`, `oracle-profiles.json`: existing target attribution and exact
  decision-close observations; retrospective percentiles are descriptive only.
- `features.jsonl`, `labels.jsonl`: causal features and separately bounded local
  hindsight outcomes. Missing values remain null, never imputed.
- `models.json`, `predictions.jsonl`, `unavailable.json`: all fitted probes,
  chronological predictions and unsupported fits.
- `audit.json`, `review.json`, `core-preservation.json`: independent accounting,
  model reconstruction, matched-date/scaler checks and event clustering.
- `summary.json`, `report.html`: all probe metrics and a self-contained report.

Local outcomes include the following rejoin overnight, so their endpoint is
decision index plus holding horizon plus one. Training purges on this complete
endpoint. The aggregate alert outcomes overlap and are not strategy CAGR.
The previous full-history optimized oracle path is never a training label.

The `core_peak_dd` feature uses the running maximum of the retained measurement
prefix; it is not claimed to reproduce a pre-measurement production peak. The
raw exact checkpoint observation remains separately retained. No feature uses
the date of the later checkpoint that happens to preserve its history.
