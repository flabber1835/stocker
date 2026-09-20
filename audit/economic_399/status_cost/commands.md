# Commands and evidence provenance

Executed from `C:/GitHub/stocker/.codex-tmp/status-cost-worktree`. Windows host
Python: `C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The wrappers run Python 3.12 inside the pinned local test image; no network.

Delivery uses AGENTS workflow A: authenticated Git fetch/push plus the connected
GitHub PR API. `git remote -v` resolves fetch/push to
`https://github.com/flabber1835/stocker.git`. Original verified main was
`e255a78aaf4f89d25fc634864aafd2656c6cd176`; the later `git fetch origin main`
resolved `8bf86ed8ca1e9fa2a6cbb9ac1588c8bcda8712bb` and was integrated without
rewriting history. `git branch --show-current` is `codex/status-runtime-delivery`;
`git rev-parse HEAD` at the integrated source checkpoint is
`ffbf82b127784c145d697078ad1e8c03b70a0c46`. `git merge-base --is-ancestor
origin/main HEAD` passes. Only the feature branch is published; no self-merge.

## Final implementation and integrated delivery

At production `9bececa241052c43851f5da586499a6ae3a8039f`:

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py tests/sentinel/test_shadow_observation.py tests/sentinel/test_production_decision.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py tests/sentinel/test_status_memory.py tests/sentinel/test_production_state.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_issue_252_253_session_envelope.py
python audit/economic_399/status_cost/run_stages.py --universe 5000 --stages storage --evidence C:/GitHub/stocker/.codex-tmp/status-cost-storage-5000-exact
python audit/economic_399/status_cost/run_stages.py --universe 5000 --evidence C:/GitHub/stocker/.codex-tmp/status-cost-isolated-5000-final
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py::test_cursor_decoder_cache_is_released_and_connection_unchanged
python audit/economic_399/status_cost/postgres16.py --evidence C:/GitHub/stocker/.codex-tmp/status-cost-pg16
```

Results: **161 passed / 53.06 s**; overlapping integrated regression **397 passed /
759.62 s** (one existing Starlette/httpx warning); exact storage **58.00 s**;
expanded lifecycle **4 passed / 5.56 s**. The lifecycle parameterization adds two
cases beyond the 397-test copy. PG16: **30 passed / 22.93 s**, plus wide storage
**63.38 s**. Complete scale results are in the README and `measurements.json`.

After integrating owner-merged main `8bf86ed8ca1e9fa2a6cbb9ac1588c8bcda8712bb`,
from `C:/GitHub/stocker/.codex-tmp/status-cost-delivery-worktree`, source/tests
`ffbf82b127784c145d697078ad1e8c03b70a0c46`:

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_paper_reporting_continuity.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_supervisor_dependency_bounds.py tests/sentinel/test_production_decision.py
python audit/economic_399/status_cost/run_stages.py --universe 100 --evidence C:/GitHub/stocker/.codex-tmp/status-cost-main-integration-100
python -m pyflakes sentinel/core/session.py sentinel/shadow_observation.py sentinel/observation_storage.py tests/sentinel/test_status_memory.py audit/economic_399/status_cost
python tools/validate_test_responsibility.py --base 8bf86ed8ca1e9fa2a6cbb9ac1588c8bcda8712bb --output C:/GitHub/stocker/.codex-tmp/status-cost-delivery-ownership.json
git diff --check
```

Results: **163 passed / 143.72 s** (one existing warning); all eight smoke stages
pass, with advanced NAV **99903.33772**, exactly matching the pre-optimization
100-security result. Lint is clean for the listed files, **26 changed Python
files parse**, ownership **491 modules / zero unowned / PASS**. The separate
`decision.py` lint check retains its pre-existing `REFERENCE_SOURCE_SHA256`
redefinition warning (baseline line 277, current 278); it is not reported clean.

The existing #418 CI failure was solely its test's assumed Compose location.
At `ccf643ad22f9e19667f3742a7ae37df8162da6cb`, the same 13-test concurrency module
passes in **1.71 s** with tests copied to `/tmp/relocated/tests`, Compose absent
there, and `SENTINEL_REPO_ROOT=/source`. The full Docker argv and bootstrap are
retained in `status-cost-418-relocated-tests.log`; the previous CI failure excerpt
is retained separately. Production and previous evidence were unchanged.

## Earlier diagnostic campaigns

Historical corpus discovery and integrity scan (no replay, NAS or broker):

```sh
git ls-remote --heads origin '*backtest*' '*Backtest*'
git fetch origin research/backtester
git ls-tree -r --long e088bfd26c695309e259cfc44ab1e8982d6f858d
gh api repos/flabber1835/stocker/actions/artifacts/9832556817/zip
python audit/economic_399/status_cost/pit_inventory.py --archive C:/GitHub/stocker/.codex-tmp/pit-source-33588053707.zip --archive-sha256 4d0aa14b65c308f232e0a6d9896f797a49c109f6b423f2877964030729c293d7 --pointer C:/GitHub/stocker/.codex-tmp/status-cost-backtester-source/canonical-pit-20y.json --output C:/GitHub/stocker/.codex-tmp/status-cost-pit-inventory.json
```

The `gh api` stdout was streamed directly to a binary file using Python
`subprocess.run(..., stdout=out, check=True)`, avoiding shell text conversion.
The registry pull returned `denied`; the connector cannot download artifacts over
512 MiB. The existing authenticated CLI successfully retrieved the 1.5 GB Actions
artifact; credentials were neither changed nor copied. Whole-archive, manifest,
27 data-member, aggregate identity and row/order checks pass in **110.42 s**.
Replacing the expected archive SHA with 64 zeros refuses before any inventory
output. The published pointer, manifest, workflow and launcher source are retained
under `status-cost-backtester-source` in the raw archive. The dataset itself stays
outside the PR. Current metadata/schema/source-admission gaps are in the README.

Later #418 CI: its corrected Sentinel-main lane passed. The synthetic-merge proof
refused a changed main/base, and one operator worker refused a downloaded bundle
inventory/hash mismatch while the other exact-bundle lanes passed. Failure
excerpts are retained; no integrity check was relaxed. Main's owner merge of #417
was integrated and both documentation sections retained. A Windows text-decoding
error briefly left markers in the merge commit; the immediate follow-up removed
them and passed `git diff --check`. Verified PR #418 head
`e3e5eeedb235162f74229a63ca30b176c52ca95c` targets main
`67b6301e3b0f1c35dc41eb45367e96a449dd6e76`; CI reruns on that exact head.
The delivery branch integrates that head at
`4812aa4beeecc29034a559c1ac0276ae9bff9ce6`. Comparing its production, test,
script and Compose paths to the tested `ffbf82b1` source yields no differences;
only the inherited review documentation changes. Final syntax validation parses
**22 changed Python files relative to the now-merged #417 main** (the earlier
26-file count used the earlier base). The focused lint command and complete-PR
`git diff origin/main --check` pass. Previous status-memory/full-status audit
directories and golden CSVs remain byte-for-byte unchanged.

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py tests/sentinel/test_production_state.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_issue_252_253_session_envelope.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py
python audit/economic_399/status_cost/run_stages.py --universe 100 --evidence C:/GitHub/stocker/.codex-tmp/status-cost-isolated-100-v2
python audit/economic_399/status_cost/run_stages.py --universe 5000 --evidence C:/GitHub/stocker/.codex-tmp/status-cost-isolated-5000
python tools/validate_test_responsibility.py --base e255a78aaf4f89d25fc634864aafd2656c6cd176 --output C:/GitHub/stocker/.codex-tmp/status-cost-ownership.json
python -m pyflakes sentinel/core/session.py sentinel/shadow_observation.py tests/sentinel/test_status_memory.py audit/economic_399/status_cost
git diff --check
```

Each stage wrapper prints the complete Docker argv, with cap, source/evidence
mounts, namespace and bootstrap. The raw log preserves those exact invocations.
Evidence directories must be new so a stale database or response cannot be reused.
The first `status-cost-isolated-100` run is diagnostic/failed, not acceptance.

Profiling and mutations run in a disposable `/tmp/repo` copy with `/source`
mounted read-only. This bootstrap was passed as the `python -u -c` argument:

```python
import os, shutil, subprocess, sys
shutil.copytree('/source', '/tmp/repo', ignore=shutil.ignore_patterns('.git', '.env', '__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',
                  SENTINEL_REPO_ROOT='/tmp/repo', PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable, '-u',
    'audit/economic_399/status_cost/call_profile.py', '--universe', '100']).returncode)
```

Docker argv prefix: `docker run --rm --network none --memory 4g --cpus 2
--mount type=bind,source=C:/GitHub/stocker/.codex-tmp/status-cost-worktree,target=/source,readonly
--mount type=bind,source=<profile-directory>,target=/evidence
--entrypoint python sentinel-test:ci -u -c <bootstrap>`.
The profile directory was `C:/GitHub/stocker/.codex-tmp/status-cost-profile-baseline`
before implementation and `C:/GitHub/stocker/.codex-tmp/status-cost-profile-after`
afterward. The failed first bootstrap used the original `profile.py` filename.

Mutation execution uses the same source-copy bootstrap and Docker caps, without
the evidence mount, invoking `audit/economic_399/status_cost/mutations.py` instead.
It verifies a passing baseline for each test before breaking tail completeness,
finite-value rejection, cycle refusal or bounded encoding. An assertion failure
is required; collection errors/timeouts do not count. The final cycle control
returns silently at the cycle instead of recursing indefinitely.

The final invocation used `runpy.run_path` in that disposable copy to execute
`audit/economic_399/status_cost/mutations.py` then
`audit/economic_399/status_cost/storage_mutations.py`: **ten killed**, each after
a passing baseline (`status-cost-final-mutations.log`). Storage controls cover
full genesis, row date, exact decimals, final write batch, immutable conflict,
and source identity. The later command
`python audit/economic_399/status_cost/storage_mutations.py --case decimal-decoder-lifetime`
in the same copied-source bootstrap kills the eleventh control. Tests are
selected with `python -m pytest tests/sentinel/test_status_memory.py::<case> -q
--tb=short -p no:cacheprovider`; timeout/collection errors do not count as kills.

`raw-logs.zip` retains the original logs, Docker inspections, profile files and
local inventory. `raw-log-sha256.json` binds each archive member. Source hashes
are computed from committed Git blobs; artifact hashes bind the new package
and documentation. Older audit packages and golden CSVs are unchanged.
