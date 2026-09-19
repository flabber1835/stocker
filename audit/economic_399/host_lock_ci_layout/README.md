# PR #408 CI test-layout correction

Reviewed failing head: `43540abffff324a567e8cb2e8c8a3aa239a981a9`.
Base: `65e261312ec219e014f062c0b6b374066db19d75`.
GitHub run `35451543688`, job `105919459280`, failed during
`python -m pytest tests/scripts -q -ra`: **1 failed, 470 passed**.

The new inherited-owner process test derived its script directory from the
test location. CI separates `/work/tests` from `/work/repo/scripts`. Other
collected tests masked the incorrect path in the pytest process, but the child
received `/work/scripts` and exited before its handshake. Honor the existing
`SENTINEL_REPO_ROOT` contract, retaining the normal checkout fallback. All lock
acceptance assertions and production sources remain unchanged.

## Commands and results

Run at repository root with Python and Docker; the host commands used
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Each runner prints its complete Docker invocation in the retained log.

| Command | Result |
|---|---|
| `python audit/economic_399/host_lock_ci_layout/run_local.py scripts` before test correction | 1 failed, 470 passed in 18.13 s; exact CI failure reproduced. |
| Same command after correction | 471 passed in 19.08 s. |
| `python audit/economic_399/host_lock_ci_layout/run_local.py ownership` | 18 passed in 0.15 s independently, without other test modules adding import paths. |
| `python audit/economic_399/host_lock_ownership/run_local.py mutations` | All six existing mutants killed at behavioral assertions. |
| `python tools/validate_test_responsibility.py --base 65e261312ec219e014f062c0b6b374066db19d75 --output ownership.json` | PASS; 475 modules, zero unowned. |
| AST parse and pyflakes for changed test and new runner | Two files parse; zero findings. |
| `git diff --check HEAD^ HEAD` and `git diff --check origin/main HEAD` | Required before follow-up push. |

`results.zip` retains raw logs, including an initial unsuccessful harness attempt:
the cached image had older runtime source, causing 471 setup errors before
any test assertion. The corrected runner overlays current Sentinel source at
`/app/sentinel`, and current inspection source/tests/tools at their separate
CI paths. It leaves the repository off global PYTHONPATH. The failing and
passing full-lane runs use this same corrected harness. These runs validate
the directory contract, not a newly built exact CI image.

Local image `sentinel-test:ci`:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
Offline disposable Linux containers, read-only input checkout, Python 3.12.13.
No NAS, broker, production credentials, economic fixture repin, capability
change, or claim of economic certification. Previous evidence under
`host_lock_ownership` is unchanged. Fresh exact-head GitHub CI is required.

`source-provenance.json` hashes the corrected test and its unchanged production
dependencies using Git LF bytes; `SHA256SUMS.json` hashes this evidence package.
