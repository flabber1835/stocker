# Owned55 full-history comparison: run in progress

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

Completion still requires exact session coverage and continuity, independent
return/drawdown recomputation, final restart verification, 2011 response
analysis, adverse recovery attribution, and artifact hashes. Known archive
classification mistakes, action proxies, and scalar execution assumptions limit
absolute-return interpretation. No NAS or broker evidence is claimed.
