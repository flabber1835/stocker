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
