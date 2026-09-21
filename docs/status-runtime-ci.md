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

## Workflow assertion follow-up

Run `35492495339` at `86b2680f19d48e026a38d09d893b15a95ffddeda`
completed the general partition, exposing three stale workflow assertions in
`test_adversarial_certification_tools.py` and `test_operational_surface.py`.
They still required a single main JUnit invocation, quiet verbosity, or a
per-command tee instead of the new combined shell group. This is an assertion
update to the already documented partition contract; no workflow or production
code changes. Both actual JUnit inputs, the combined output, verbose summaries,
and pipefail-protected log group remain checked. The existing executable shell
acceptance separately proves exact module coverage and failure propagation.

Validation (offline local PostgreSQL test image, current source copied inside):
`python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_adversarial_certification_tools.py tests/sentinel/test_operational_surface.py tests/scripts/test_sentinel_ci_parallel_evidence.py tests/scripts/test_test_responsibility.py`
passes **128 tests in 3.73 seconds**. `git diff --check` passes. The rolling
partition was not reached after the failed general partition; only new green
GitHub CI can establish completion of the entire campaign.

## Fresh rolling-container import follow-up

Run `35520455438`, job `106103999586`, at
`06aa33187d3a1e6b7a09a032f680aad7b7202485` passed all **4,919** general
tests and **334** rolling tests. Three rolling cases failed with
`ModuleNotFoundError`: generated installer programs, GO preparation/readiness,
and operational parity's host validator. They located scripts relative to
`/work/tests`, but the certified test image intentionally stores those host
scripts under `/work/repo/scripts`. Previous combined collection had incidentally
added that directory to the process import path; the fresh container exposed
the dependency. No economic assertion failed in this run.

The two affected test modules now use the existing `SENTINEL_REPO_ROOT`
inspection contract, prepend only its scripts directory through `monkeypatch`,
and assert each imported host module's actual file identity. The repository root
stays off PYTHONPATH; production imports remain `/app/sentinel`. No production,
workflow, resource limit, test selection, or golden artifact changes.

The three original failures were reproduced locally in a fresh split-layout
container (**3 failed in 15.88s**, each at its missing host-script import).
After the fix, both complete affected modules plus image-layout acceptance pass:

```text
python -m pytest tests/sentinel/test_rolling_admission_readers.py tests/sentinel/test_rolling_go_inputs.py tests/sentinel/test_image_layout.py -q --tb=short -ra -p no:cacheprovider
72 passed in 92.65s
```

To reproduce the local layout, run the existing `sentinel-test:ci` image with
`--rm --network none --memory 4g --cpus 2`, mount the reviewed source read-only
at `/source`, and use this Python bootstrap via `--entrypoint python -u -c`:

```python
import os, shutil, subprocess, sys
shutil.copytree('/source', '/work/repo', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('.git', '.env', '__pycache__'))
for source, target in [('tests', '/work/tests'), ('tools', '/work/tools'),
                       ('sentinel', '/app/sentinel')]:
    shutil.copytree('/work/repo/' + source, target, dirs_exist_ok=True)
os.chdir('/work')
os.environ.update(PYTHONPATH='/work:/app', SENTINEL_REPO_ROOT='/work/repo',
                  SENTINEL_IN_IMAGE='1', PYTHONDONTWRITEBYTECODE='1')
probe = ('import sentinel,sys; assert sentinel.__file__.startswith("/app/"); '
         'assert "/work/repo" not in sys.path; '
         'assert "/work/repo/scripts" not in sys.path')
subprocess.run([sys.executable, '-c', probe], check=True)
raise SystemExit(subprocess.run([sys.executable, '-m', 'pytest',
    'tests/sentinel/test_rolling_admission_readers.py',
    'tests/sentinel/test_rolling_go_inputs.py',
    'tests/sentinel/test_image_layout.py', '-q', '--tb=short', '-ra',
    '-p', 'no:cacheprovider']).returncode)
```

This is a current-source layout reproduction using the local dependency image,
not a claim that the whole exact-head CI image was rebuilt locally. The earlier
`run_local.py` convenience harness adds the scripts path and therefore cannot
falsify this particular import defect. AST and diff checks pass; pyflakes has
only the same existing pytest-fixture diagnostics as the base. Ownership passes
with 491 modules and zero unowned. Full GitHub CI must still pass before merge.

## Main-lane wall-time budget, 2026-09-20

Run `35536479801`, job `106146878585`, at #425 head
`fa24fddc2a1982c91e6be76181b6b4c7af587ec5` passed all **5,001 general tests in
1,249.42 seconds**, then reached 71% of the separately executed rolling tests
before its 45-minute job budget cancelled the process. Both aggregate jobs
correctly refused the cancelled dependency. This is incomplete CI evidence,
not a newly observed economic assertion failure.

Decision before implementation: allow **75 minutes for sentinel-main only**,
because it runs both complete partitions serially. All other lanes, including
the independently passing 39m48s warmup lane, retain 45 minutes. Keep the same
module selections, separate processes, assertions, JUnit merge and mandatory
dependency checks. This is a CI execution budget, not a relaxed production
latency threshold or a claim of certification. A successful rerun is required.

Focused validation: `python -m pytest tests/scripts/test_sentinel_ci_parallel_evidence.py
-q -p no:cacheprovider` passes **54 tests in 2.05 seconds** in the offline local
test image. The existing executable-shell cases verify module conservation,
separate-process selection and failure propagation. The timeout change neither
adds an xfail nor removes a test. Permanent ownership passes for 495 modules,
zero unowned. Full GitHub CI is pending after publication of this correction.
