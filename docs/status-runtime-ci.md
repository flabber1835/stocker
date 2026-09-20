# Runtime cost review: CI integration, 2026-09-20

Integrate verified main `daa43caf995779bfa7e67195785520744021cb45` without
rewriting the published branch. The four conflicts repeat #418's implementation;
retain this PR's bounded encoder, exact-decimal comparisons and additional tests.
No production bytes need changing to resolve the integration.

Run 35487177277's Sentinel main lane exited 137 after 4,192 completed tests,
around the rolling recovery tests, without an assertion report. The old quiet
log and removed container do not identify the killed process or prove an OOM
root cause. Treat this as a killed CI workload, not a diagnosed strategy defect.
Separate `test_rolling_*.py` from the remaining main-lane modules into two fresh,
sequential containers. Keep the existing warmup/automation ownership exclusions,
all test cases, the 45-minute job deadline and production limits unchanged.
Merge both JUnit reports with duplicate detection; the existing independent
collection/owner gate must still prove complete passing coverage. Retain verbose
per-test progress for a subsequent failure instead of an anonymous dot prefix.
This fixture-lifetime isolation is not evidence of production memory headroom.

## Validation

Existing offline `sentinel-test:ci` image, network disabled, disposable source
copy, temporary PostgreSQL, 4 GiB / two-CPU test harness:

```sh
python audit/economic_399/rolling_status/run_local.py test tests/scripts/test_sentinel_ci_parallel_evidence.py tests/scripts/test_test_responsibility.py --maxfail=1
# 94 passed in 3.54s
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_initialization.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_rolling_reader.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_status_memory.py -v --maxfail=1
# 204 passed in 608.22s
python tools/validate_test_responsibility.py --base daa43caf995779bfa7e67195785520744021cb45
# PASS: 491 modules, zero unowned
python -m pyflakes tests/scripts/test_sentinel_ci_parallel_evidence.py
git diff --check
```

The workflow-shell test runs the actual YAML command with a Docker stand-in,
checks the module union including future ordinary/rolling modules, and requires
exit 7 from either failing container to propagate without producing the merged
report. In a disposable copy, replacing the rolling wildcard with only
`test_rolling_runtime.py` makes its positive coverage assertion fail: the omitted
module mutant is detected (one expected assertion failure, not an import error).

Independent real `pytest --collect-only -q -p no:cacheprovider` calls collected
the original selection and both actual new selections. The original 5,256 nodes
equal the disjoint union of 4,919 general and 337 rolling nodes. The baseline
selection retains the eight existing warmup/automation module exclusions; the
general selection adds `--ignore-glob=tests/sentinel/test_rolling_*.py`, and the
rolling selection expands that same module glob. No cases were removed.

The focused recovery cases covering the interrupted book passed. Observed
container memory at checkpoints was 257.2–377.4 MiB with zero `oom`/`oom_kill`
events; these samples are not a peak-memory measurement or production qualification.
AST syntax and all 16 retained status-cost artifact hashes also pass. Production
and the four conflict-resolved files are byte-identical to pre-merge #419 head
`25d43efb385fc431e66fe5a7a9c62ac442068e71`. Earlier evidence remains unchanged.

The original exit-137 root cause remains unproven. Only a successful new GitHub
run establishes this CI campaign's completion; local results do not do so.
No NAS, broker, strategy, golden fixture or runtime resource limit was changed.
