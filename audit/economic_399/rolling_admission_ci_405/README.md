# PR 405 CI correction

The original head `4d758ad993e96043c160f0421bb97881e87e1019` failed
[Sentinel main](https://github.com/flabber1835/stocker/actions/runs/35431437860/job/105867107232)
with **1 failed, 5,023 passed**. The old empty-account fixture supplied only
`{"schema": "sentinel.paper-observation-warmup/1"}` and expected acceptance.
The production `/2` evidence guard correctly refused it. Other failed safety
jobs were downstream evidence gates; five other workflows passed.

The old input now remains a negative assertion after account binding. Positive
before/after-binding coverage uses the existing 300-session sealed rolling
fixture, real canonical 252+1 warmup, unsigned candidate, offline signing,
installation and activation. The same real warmup is refused before binding
and accepted after binding. No production guard, golden or capability changed.

Current main was independently fetched at
`3c4fb030b3ad06bc8996771479b2d68b71cb17e6` (owner-merged #404) and merged
without conflicts in `21d3c27e`. In particular the generated installer reader
and streaming timeout changes coexist. Prior evidence remains immutable in
`../rolling_admission_403`; this package supersedes only the changed-source
validation claims. Source hashes identify the tested correction.

From the repository root:

```text
python audit/economic_399/rolling_admission_ci_405/run_local.py regression
python audit/economic_399/rolling_admission_ci_405/run_local.py mutations
python tools/validate_test_responsibility.py --base 3c4fb030b3ad06bc8996771479b2d68b71cb17e6 --output ownership.json
git diff --check
```

The runner prints the exact Docker argument array. Source is mounted read-only,
network disabled, `.env` replaced with an empty file if present, and PostgreSQL
is disposable. Runtime remains the recorded local Python 3.12.13/PostgreSQL
17.11 image from `../rolling_admission_403/commands.json`. GitHub uses its
separately built exact-head runtime; local results do not claim that CI image.

Results: **130 regression tests passed in 115.41 seconds**. Four Python files
parse, including Python 3.8 grammar for the merged host installer. Ownership:
**473 modules, zero unowned, PASS**. All **8 admission mutants were killed**
at behavioral assertions, including issuer/strategy binding, publication pin,
reader integrity, cache generation, provider refresh date, warmup capital and
source-final frontier. `results.zip` retains both local logs, the original CI
job log (line endings normalized), ownership output and static-check record.
`source-provenance.json` records source hashes with Git text normalization;
`SHA256SUMS.json` authenticates this package. Prior logs are not overwritten.

No NAS or real broker account was accessed. Step 1, provider guarantees,
historical replay and economic certification remain open as listed in
`docs/economic-code-closure.md`. Fresh CI on the delivered head is required.
