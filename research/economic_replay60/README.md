# Economic replay with matched SPY and reference reporting

This isolated research runner calls unchanged production revision
`624395dd04c48af7de3a8930cfd586ca2cc81245` through the retained PR #426
January harness. It changes historical security-type assumptions and reporting,
not production strategy parameters, costs, valuation or controller code.
Read [the design](../../docs/economic-replay-60m.md) for the economic conventions.

The classifier input reconstructs the reference's reviewed historical universe.
It is not a new point-in-time certification or out-of-sample test. Unknown
classifications outside its dated intervals remain ineligible. Reference NAV is
used only for reporting; it is not passed to the kernel or controller.

## Inputs and invocation

Use a read-only checkout of the retained `research/bounded_20y` harness, with its
production source manifest intact, the original hash-bound PIT archive, and
`SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz` from that archive's source manifest.
Supply a new output directory and a separate supplemental-input file. The
runner refuses to overwrite an existing output directory.

```powershell
python -B -m research.economic_replay60.run `
  --harness <retained-production-replay-checkout> `
  --archive <pit-source-5bdc6b39.zip> `
  --sfp <SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz> `
  --supplements <this-run-only-supplements.json> `
  --output <new-segment-directory> --seconds 3600
```

The retained harness checkout used here is
`9b60e2ab10035df49c51c1432f3a5d6379dd61a2`; its production manifest pins
`624395dd04c48af7de3a8930cfd586ca2cc81245`.

Python 3.12 and the retained harness dependencies are required. The actual run
uses isolated dependencies; no existing simulation environment is modified.
`identity.json` records all runner, overlay, harness and production bindings.
`daily.jsonl` retains controlled-account NAV, separate Wealth Core NAV, exposure
decisions, SPY levels and all three matched-date comparisons. `status.json`
reports the latest completed session. A checkpoint is saved every 100 sessions,
at blockers, and at the deadline.

For a read-only restoration check, add `--resume <latest-checkpoint.json>
--verify-resume` to the same command. This validates and exits without creating
an output directory or advancing the simulation. An actual later continuation
requires owner authorization and a new output directory.

## Classification export

`classification-intervals.json.gz` is a frozen, hash-bound export of the exact
legacy classifier used by the retained reference:

- Baseline classifier/ledgers: `ba74e79490beb8950611b1d17f5d124833b3d91e`.
- Final interval integration: `eaddca3f04f279e99663f832bf7293e92ee15662`.
- Scenario: `reviewed_18`, including its historical type corrections and final
  reviewed intervals.
- 1,751 security identities; 1,760 intervals; 3,520 boundary oracle checks.
- Every source file hash is embedded in the compressed JSON.

For each identity's admitted unknown-first/unknown-last range, partition at
every final-interval, historical-correction and factual-case boundary. Query
the original `SecurityTypeEstimate.peek` on both ends of each partition and
require identical classifications. Emit the identity, ticker, first/last date
and class. At runtime, canonical known classes retain precedence; only unknown
rows are passed through this ledger. No rankings, positions or return outcomes
are exported into the classifier.

## Narrow verification

```powershell
python -B -m pytest -q -p no:cacheprovider research/economic_replay60/test_inputs.py
```

The tests cover classification precedence and date intervals, ticker identity,
a historical common/non-common transition, independent benchmark baselines,
CAGR arithmetic and preservation of baselines across continuation. Observed
run results and independent arithmetic checks are retained with the experiment
evidence after the segment completes.

## Result and independent verification

The [bounded result report](../../audit/economic_replay60/README.md) contains
all three matched series, separate Core attribution, assumptions and the
December 23 conversion blocker. The additional hour ended early at a preserved
checkpoint after this software integration issue was reproduced.

```powershell
python -B -m research.economic_replay60.verify `
  --segments <segment-001> <segment-002> `
  --reference <retained-reference-daily.csv.gz> `
  --sfp <SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz> `
  --archive <pit-source-5bdc6b39.zip> --supplements <supplements.json>
python -B -m research.economic_replay60.reference_analysis <segment-001> <segment-002>
```

These analysis helpers read completed files and never advance the strategy.
The reference comparison requires the retained reference commit in local Git.
