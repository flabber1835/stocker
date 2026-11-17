# Structured Sentinel research

This offline first batch generates 576 seeded candidates across revised state
rules, trend/volatility rules, direct predictive models and fixed combinations.
It reads the authenticated fractional Core snapshot used by the earlier oracle;
it does not advance Core, repair the stopped replay, contact a broker or install
a controller. Design and exact selection boundaries are frozen in
`docs/sentinel-structured-search.md`.

Use the pinned Python 3.12 replay image with the existing isolated NumPy 2.4.6,
scikit-learn 1.7.2, SciPy 1.16.3 and Plotly dependencies. Set BLAS threads to one.
The source and snapshot mounts must be read-only, output a new separate folder,
network disabled, CPU limited to 0.5 and memory to 1 GiB.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=.:shared:/neural-libs:/plotting-libs \
python -B -m research.structured_search.run \
  --snapshot /read-only/snapshot --output /separate/new-search
```

The runner freezes the menu before scoring, then fits/selects on earlier data
before evaluating each later two-year block. The original Sentinel is always a
selection fallback. Labels start at the next open and never cross the fitting
cutoff. Each outer block refits learned models on then-available history, freezes
them, and carries the modeled account's actual overnight exposure into the new
block. No retrospective selection from the complete outer history is performed.

Outputs include the complete protocol, all 2,880 inner validation trials, every
fitted model as JSON, all candidate actions as compressed non-pickle arrays,
frozen choices and hashes, aggregate and monthly metrics, cost/delay stresses,
timing placebos, a batch-wide bootstrap diagnostic, episode attribution, an
independent raw-ledger audit, a Core-transition prohibition receipt, and an
offline interactive `report.html`. Historical data already inspected in earlier
research is explicitly identified; this is not an untouched research holdout.

```bash
PYTHONPATH=.:shared:/neural-libs:/plotting-libs python -B -m pytest \
  tests/sentinel/test_structured_search.py \
  tests/sentinel/test_structured_search_mutations.py \
  tests/sentinel/test_exposure_oracle.py tests/sentinel/test_exposure_logic.py \
  -q -p no:cacheprovider
```

The mutation suite deliberately breaks eleven timing, memory, fitting,
information-boundary and selection safeguards and requires the behavioral tests
to detect each fault. Its mutations are in memory; production and research files
are never rewritten by those tests.

To summarize the complete saved candidate universe without selecting a new
winner, run the separate read-only review. It records its own source hash and
refuses a different snapshot or changed protocol. Its whole-period ranking is
explicitly hindsight; it cannot promote a policy or change frozen choices.

```bash
PYTHONPATH=.:shared:/neural-libs python -B -m research.structured_search_review \
  --snapshot /read-only/snapshot --result /separate/completed-search
```

This writes `candidate-review.json` once, including every candidate's metrics,
distinct-behavior counts and validation-to-next-block transfer diagnostics.
