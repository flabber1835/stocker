# Exposure timing with perfect hindsight

This offline experiment reads the fractional Core replay's committed return
history. It searches daily switch timing among **0%, 55%, and 100%**, with the
same next-open convention and scalar costs. It reports a CAGR/drawdown frontier
and the best hindsight path within actual Sentinel's drawdown limit.

Run in an isolated Python 3.12 research environment with the repository's
existing dependencies and `requirements-report.txt` installed. The Plotly
dependency is only for the self-contained, interactive HTML report.

```bash
PYTHONPATH=.:shared python -B -m research.exposure_oracle.run \
  --source-run /read-only/fractional-replay \
  --output /separate/new-experiment
```

The output directory must not already exist and must be separate from the
source. The reader copies only the authenticated checkpoint's daily prefix;
it never restores or modifies the running replay. Mount the source read-only.

Select another period from that fixed snapshot, using exact trading-session
dates and a fresh output directory:

```bash
PYTHONPATH=.:shared python -B -m research.exposure_oracle.run \
  --snapshot /read-only/previous-experiment/snapshot \
  --start 2007-01-03 --end 2010-12-31 \
  --output /separate/new-period
```

The first selected close is the common NAV/drawdown baseline. Its held exposure
carries into the next overnight. If the original first funded deployment is
included, that deployment is fixed to the recorded path. No ending liquidation
is imposed. See `docs/fractional-exposure-oracle.md` for the equations, exact
dynamic programs, provenance and resource-limit behavior.

Outputs: `report.html`, `summary.json`, `frontier.json`, `frontier-paths.json`,
`paths.json`, `daily.jsonl`, `monthly.json`, `attribution.json`, Plotly figure
JSON, and a retained input snapshot when `--source-run` is used. The HTML embeds
its plotting library and needs no external services. Zooming a chart does not
rerun the optimization; use the CLI to optimize a different period.

Validation:

```bash
PYTHONPATH=.:shared python -B -m pytest \
  tests/sentinel/test_exposure_oracle.py -q -p no:cacheprovider
```

The oracle uses future knowledge. Its large performance advantage measures
hindsight opportunity and cannot establish a deployable improvement to Sentinel.

## Four causal exit and recovery cases

Run the four fixed hypotheses on an existing authenticated snapshot:

```bash
PYTHONPATH=.:shared python -B -m research.exposure_oracle.logic \
  --snapshot /read-only/previous-experiment/snapshot \
  --output /separate/new-logic-experiment
```

The cases are the recorded baseline, one-close owned-impairment entry instead
of five, a 55% bridge during the native-full/recovery-zero state, and both changes.
They retain the existing severe exits, full-recovery criteria and eight-close
owned release. Each close decision acts at the next open. No oracle decisions
or future returns enter the candidate rules. Baseline states and targets must
match every recorded row; the canonical accountant must reproduce the tape.

Optional `--start` and `--end` select exact completed-session closes. Candidate
state and returns are built from the shared original seed before the selected
window is rebased, preserving each candidate's own prior held exposure. This is
a diagnostic comparison on inspected history, not out-of-sample qualification.

Outputs include the interactive HTML report, summary, full close decisions,
applied exposures and NAV paths, monthly metrics, yearly returns, and returns
during each recorded defensive episode. See
`docs/sentinel-exit-recovery-experiment.md` for the frozen design and results.

```bash
PYTHONPATH=.:shared python -B -m pytest \
  tests/sentinel/test_exposure_logic.py tests/sentinel/test_exposure_oracle.py \
  -q -p no:cacheprovider
```

## Neural imitation of the ideal policy

The neural experiment fits a small 38 → 16 → 8 → 3 classifier to independently
bounded hindsight labels. Training ends in 2012, validation selects an epoch
using 2013–2015, and 2016–April 2019 is excluded from fitting and selection.
Every feature is known at its decision close; the predicted action executes
at the next open. The original ideal has no 55% examples at the selected cap.

Use the pinned Python 3.12 replay image (NumPy 2.4.6), install
`requirements-neural.txt` and `requirements-report.txt` into isolated research
locations, and limit BLAS threads to one. Mount the snapshot and earlier oracle
result read-only. Training refuses mismatched dependency/source identities.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=.:shared \
  python -B -m research.exposure_oracle.neural \
  --snapshot /read-only/previous-experiment/snapshot \
  --oracle /read-only/previous-oracle-result \
  --output /separate/new-neural-experiment
```

The output includes `evaluation-model.json`, `all-history-model.json`, every
epoch's loss, frozen test probabilities/actions, bounded teacher labels,
test-period paths, cumulative monthly metrics, provenance and an interactive
HTML report. The evaluation model is exported before test labels are scored.
The second model refits all available ideal labels for the already selected
epoch count; it has no held-out result on its training history.

Saved models contain finite arrays and feature order as JSON, without pickle.
For a research prediction from the last completed close of an authenticated
snapshot:

```python
from pathlib import Path
from research.exposure_oracle import inputs, neural_data, neural_model

_, rows = inputs.load(Path('/read-only/snapshot'))
model = neural_model.FrozenModel.model_validate_json(Path('all-history-model.json').read_text())
assert model.features == list(neural_data.FEATURES)
probabilities = model.probabilities(neural_data.feature_matrix(rows)[-1:])[0]
target = model.actions[int(probabilities.argmax())]  # For the following open.
```

No model is installed in Sentinel or allowed to contact a broker. See
`docs/sentinel-neural-imitation.md` for exact features, fixed settings, boundary
semantics and limitations. Test with:

```bash
PYTHONPATH=.:shared python -B -m pytest tests/sentinel/test_exposure_neural.py \
  tests/sentinel/test_exposure_oracle.py tests/sentinel/test_exposure_logic.py \
  -q -p no:cacheprovider
```

## Target CAGR closest to existing decisions

The target experiment searches for 25–30% CAGR after modeled costs, with MaxDD
no worse than current Sentinel over the same completed period. Closeness means
fewest changed daily decisions, then smallest exposure deviation, then fewest
switches. It combines growth-budget dynamic programming, conservative transition
pruning and an exact sparse MILP. A separate raw-ledger and exhaustive audit
checks the selected result. No predictive policy is trained by this command.

Use the pinned replay image with `requirements-target.txt` and
`requirements-report.txt` installed in isolated research locations. Limit BLAS
and the solver to one thread. Mount the authenticated snapshot read-only; all
outputs belong in a separate new directory. Defaults allow 128 changed days and
120 seconds per solver objective. A time limit is never reported as infeasibility.

```bash
PYTHONPATH=.:shared python -B -m research.exposure_oracle.target \
  --snapshot /read-only/snapshot --output /separate/new-target-run
PYTHONPATH=.:shared python -B -m research.exposure_oracle.target_analysis \
  --snapshot /read-only/snapshot --result /separate/new-target-run
PYTHONPATH=.:shared python -B -m research.exposure_oracle.target_report \
  --snapshot /read-only/snapshot --result /separate/new-target-run
PYTHONPATH=.:shared python -B -m research.exposure_oracle.target_audit \
  --snapshot /read-only/snapshot --result /separate/new-target-run
```

The HTML report contains monthly CAGR, multiple and MaxDD for Sentinel, target
and SPY. JSON outputs retain the complete path, solver bounds, signal comparisons,
fixed causal-rule diagnostics and all changed episodes including their rejoin
overnights. See `docs/sentinel-target-cagr.md` for design, evidence and limitations.

```bash
PYTHONPATH=.:shared python -B -m pytest tests/sentinel/test_exposure_target.py \
  tests/sentinel/test_exposure_target_analysis.py tests/sentinel/test_exposure_oracle.py \
  -q -p no:cacheprovider
```
