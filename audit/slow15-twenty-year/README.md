# Slow15 full-history comparison: run in progress

This is a registered research experiment, not a production configuration change
or an economic certification. Only the slow defense persistence changes from
30 to 15 sessions. The design is in `docs/slow15-twenty-year.md`.

Verified base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`. The runtime's
305 production files match that Git revision byte for byte. Frozen helper source:
`f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb:research/impedance/parameters.py`.
The comparison retains both controller identities and source/input hashes in
every checkpoint. The prior golden artifacts remain unchanged.

## Local validation before launch

- Seven focused tests pass; `tests.xml` retains the latest result.
- Five deliberate faults are caught: source binding, cursor binding, checkpoint
  commitment, overnight ownership, and selecting a log instead of a resume
  directory. See `mutations.json`.
- The 90-second pilot completed 67 sessions through 2006-04-07, wrote a bound
  checkpoint, and the full worker restored it and continued on the next session.
  `launch-verification.json` retains hashes and the actual transition evidence.
- Syntax compilation and test ownership validation pass.
- An initial pytest invocation could not access the shared Windows pytest temp
  directory. The identical tests passed using a fresh repository-local temp
  directory; no assertion or fixture was relaxed.

Commands below run from the isolated `slow15-twenty-year` worktree. `python`
means `C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe`.

```powershell
$env:PYTHONPATH="$PWD;$PWD/shared;C:/GitHub/stocker/.codex-tmp/classification-check-runtime"
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
python -m pytest research/slow15_replay/test_model.py research/slow15_replay/test_continue.py -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/slow15-pytest-20260922-b --junitxml=audit/slow15-twenty-year/tests.xml
python -m research.slow15_replay.mutations
python -m compileall -q research/slow15_replay
python tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/slow15-twenty-year/test-ownership.json
```

Use a fresh explicit test temp directory for a repeat; the historical command
above identifies the recorded run, not permission to remove another run's data.

## Running locally

The pilot used `research.slow15_replay.run` with the same four input paths below,
`--output C:/GitHub/stocker/.codex-tmp/slow15-20y-run/segment-001`,
`--supplements C:/GitHub/stocker/.codex-tmp/slow15-20y-run/supplements.json`,
and `--seconds 90`. The continuation command is:

```powershell
python -m research.slow15_replay.continue_run --root C:/GitHub/stocker/.codex-tmp/slow15-20y-run --runtime C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz'
```

**Do not start a second worker while this process is alive.** The driver chains
one-hour segments, preserving full Core and research checkpoints every 100
sessions and on each segment's normal stop. A refusal stops the driver. Read the
newest segment directory's `comparison-status.json` and adjacent `.log` for
progress. The authoritative retained comparison starts at the July 31, 2006
close after January formation with $100,000 and ends July 31, 2026.

Do not edit `run.py`, `model.py`, the frozen helper, runtime, or supplement inputs
while continuing this run. Their identities are bound into resumable state.
The local continuation may run independently of an open assistant turn.

## Required before closing this experiment

Keep the research PR draft while the run is incomplete. On completion, retain
the stitched observation/account stream and final checkpoint identity; require
every expected archive session exactly once, including the measurement baseline
and final date. Independently recompute both account CAGR, multiple, and maximum
drawdown, verify decision/account continuity across all restarts, and attribute
the changed exposures and costs by episode, including adverse episodes. Report
any drift of the uniformly sourced control from the earlier mixed-source run.

Known archive classification mistakes, supplemental action proxies, and scalar
execution assumptions carry forward. These limit interpretation of the absolute
returns. This experiment tests a single frozen parameter change on common inputs;
it does not establish a globally optimal policy or deployed broker correctness.
