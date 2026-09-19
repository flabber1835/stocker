# PR 403 CI build follow-up

Failing head: `4995818e4eabb333caa393124de2840990b1f8a6`.
[CI build job](https://github.com/flabber1835/stocker/actions/runs/35421534428/job/105840117213).

The test image's `python -m pytest tests/scripts -q -ra` build step reported
5 failed, 448 passed. Both public-installer subprocess tests selected their
working directory from the test file location (`/work`), then searched its
partial `scripts` directory. The full installer source is intentionally under
`SENTINEL_REPO_ROOT=/work/repo`. They failed on import before any behavioral
assertion. Dependent Sentinel jobs consequently could not run.

The fix reuses the established environment-aware `ROOT` already used by this
test module's deployment loader. It changes no production code, image boundary,
economic expectation, or assertion.

The split-directory local reproduction obtained the same five failures and
five passing controls before the fix. `results.zip` retains that output and
the full operator-test rerun. `commands.json` gives its exact Docker argument
array; `SHA256SUMS.json` authenticates the package and individual archive entries.

The local test lens mounts current production/test/helper sources in the CI
locations, preserves the separate `/work/scripts` and `/work/repo/scripts`,
uses an empty `.env`, disables network, and gives generated test artifacts a
disposable tmpfs. It is not claimed as a newly built exact CI image. Earlier
local reconstruction attempts used stale baked sources or a read-only artifact
directory; those fixture failures are retained and are not production defects.
GitHub must independently build and validate the follow-up head.

Syntax parsing and `git diff --check` pass. The original economic-certification
gates and earlier retained evidence remain unchanged.

Final local operator-test build surface: **453 passed in 46.46 seconds**.
