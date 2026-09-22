# Owned55 full-history comparison: completed local research replay

This is a registered research experiment, not a production configuration change
or economic certification. It preserves PR #432's independently persisted
five-bad/eight-healthy owned-book cause and changes only its active ceiling from
zero to 0.55. The existing champion's fast/slow causes retain their zero ceiling.
See `docs/owned55-twenty-year.md`.

Verified base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`. Parent owned
policy: `7250ce3d65cc38a103989d460fe3c557a38343c8`. Current-controller
adapter: `f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb`. The stopped Slow15
experiment remains separately retained and is not a seed for this identity.

## Pre-launch validation

- Eight focused tests pass in `tests.xml`: exact parent-rule inheritance and
  sole ceiling delta, fifth-bad entry, eighth-healthy recovery, independent zero
  causes, next-open accounting, measurement baseline, resume fencing, and safe
  segment selection.
- Seven deliberate faults are killed in `mutations.json`.
- Syntax compilation and repository test-ownership validation pass.
- A 90-second pilot completed 68 sessions through 2006-04-10 and wrote a
  source/input/controller/account-bound checkpoint. Segment 002 restored it and
  advanced normally; exact current-controller and independent accounting parity
  are required on every close.

Commands run from the isolated `owned55-twenty-year` worktree. `python` below is
`C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe` with the
worktree, `shared`, and the existing classification runtime on `PYTHONPATH`.

```powershell
python -m pytest research/owned55_replay/test_model.py research/owned55_replay/test_continue.py -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/owned55-pytest-20260922-c --junitxml=audit/owned55-twenty-year/tests.xml
python -m research.owned55_replay.mutations
python -m compileall -q research/owned55_replay
python tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/owned55-twenty-year/test-ownership.json
```

The active continuation command is:

```powershell
python -m research.owned55_replay.continue_run --root C:/GitHub/stocker/.codex-tmp/owned55-20y-run --runtime C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz'
```

Do not start a second worker. Do not edit `run.py`, `model.py`, the runtime, or
input files while the run is active; their byte identities are checkpoint-bound.

## Completed result

The source-bound replay reached 2026-07-31 without refusal. The independent
`research/owned55_replay/audit.py` pass checked all 5,176 sessions across eight
checkpointed segments against the retained current-controller daily record. It
found no missing or duplicated session, decision or NAV drift, broken segment
identity, daily-accounting failure, or reported return/drawdown discrepancy.
There are 5,032 measured closes from 2006-07-31 through 2026-07-31. Exact
checkpoint hashes, segment boundaries, controller events, and recomputed
metrics are in `final-audit.json`.

| Matched-date run | Final multiple | CAGR | Maximum drawdown |
| --- | ---: | ---: | ---: |
| Research champion | 56.2653x | 22.32% | Not retained here |
| Owned55 | 30.6610x | 18.67% | -28.47% |
| Current Sentinel | 29.2438x | 18.39% | -29.77% |
| SPY | 8.4433x | 11.26% | Not retained here |

Owned55's final NAV was $2,836,980 versus current Sentinel's $2,705,852.
The first different target was 2011-08-10, and only 73 daily targets differed
over the 5,176-session run. The relative NAV ratio improved 6.25% during the
2011-08-10 to 2011-11-04 impairment episode. Later entry/recovery windows
were mixed: 2018 improved the relative ratio 1.13%, while 2020 reduced it
2.87% and 2021 reduced it 0.17%. In 2008 both policies were already at zero
exposure, so the owned cause made no target or economic difference. These are
episode attributions, not evidence that 55% is an optimal ceiling.

Validation command, from this worktree:

```powershell
python -m research.owned55_replay.audit C:/GitHub/stocker/.codex-tmp/owned55-20y-run
```

The run's final status and checkpoint are retained under
`C:/GitHub/stocker/.codex-tmp/owned55-20y-run/segment-008`; no checkpoint or
source input was altered. Focused tests and syntax compilation were repeated
after completion: eight tests passed. Known archive classification mistakes,
action proxies, and scalar execution assumptions limit absolute-return
interpretation. This experiment does not authorize production promotion,
paper deployment, or economic certification. It contains no NAS or broker
evidence.
