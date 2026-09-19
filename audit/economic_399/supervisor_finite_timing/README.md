# Finite supervisor timing: local closure evidence

Verified main base: `8a9206c20f7fb2d224c1e3c044e9e0f3953eea5b` (#406 merged).
Delivery branch: `codex/supervisor-finite-timing`. The containing PR identifies
the reviewed final commit. #407/#408 remain separate changes.

P2 configuration defect: IEEE NaN bypassed the shadow deadline range check;
NaN and positive infinity passed automation poll/startup-grace checks. A NaN
shadow deadline never expires. Invalid automation timing can defeat stall
supervision or fail after spawning a worker. There is no retained evidence that
deployed configuration or historical returns were affected.

The fix rejects non-finite values before worker startup, preserving documented
ranges, defaults, and zero startup grace. No strategy, broker authority,
command identity, golden artifact or provider capability changed.

## Commands and results

Commands run from repository root. The host Python executable was
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The runner prints its complete Docker invocation, retained in `results.zip`.

| Command | Result |
|---|---|
| `python -m pytest tests/sentinel/test_supervisor_timing_admission.py -q --tb=short -p no:cacheprovider` against pre-fix production sources | 10 failed, 16 passed in 7.88 s; failures reached the worker-launch tripwire rather than refusing invalid configuration. |
| `python audit/economic_399/supervisor_finite_timing/run_local.py regression` | 101 passed in 40.93 s; one Python fork-from-multithreaded-process deprecation warning. |
| `python audit/economic_399/supervisor_finite_timing/run_local.py mutations` | All three removed guards detected: shadow deadline, automation poll, automation startup grace. |
| AST parse and pyflakes on two changed production modules, new test, mutation driver and runner | Five files parse; zero findings. |
| `python tools/validate_test_responsibility.py --base 8a9206c20f7fb2d224c1e3c044e9e0f3953eea5b --output ownership.json` | PASS; 476 test modules, zero unowned. |
| `git diff --check HEAD^ HEAD` and `git diff --check origin/main HEAD` | Required before delivery. |

The regression covers public timing admission and finite boundary acceptance,
real process termination and replacement, a silent dependency, full logging
pipe, actual PostgreSQL lock/cancellation, persistent latch restart, callback
invocation deadlines, and alert dispatcher supervision. The new tests replace
worker launch with an exception tripwire to prove rejection precedes side
effects; existing acceptance tests exercise real harmless workers. No account
or NAS was accessed. No suite was run solely to raise a coverage count.

Offline Docker image `sentinel-test:ci`:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13, PostgreSQL 17.11. Current source copied to disposable storage,
input checkout read-only, network disabled, `.env` excluded. Exact-image CI
and deployed PostgreSQL 16 qualification remain distinct requirements.
`source-provenance.json` hashes Git-LF source bytes; `SHA256SUMS.json` hashes
the retained evidence package. Older audit packages remain unchanged.

## NAS handoff — not executed

Prerequisites: owner-reviewed merge, passing exact-head CI, accepted source and
runtime/test image digests, and an isolated clone without broker credentials
or network. Run the two runner campaigns above using the accepted local image
tag and retain raw results, source hashes and image identity. Pass requires all
tests passing without unexpected skips/xfails and all three mutants detected.

On the isolated deployment fixture, inspect the resolved environment for
`SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS`,
`SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS`, and
`SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS`. Test copies with `nan`,
`inf` and overflowing `1e309`; invalid values must refuse before any worker
starts. Accepted finite boundaries must retain ordinary restart/recovery.
Preserve the original environment and keep primary services untouched.

This does not qualify wedged state volumes, full-universe latency, arbitrarily
large finite timing values, recurring backup/horizon maintenance, provider
finality, or historical replay. Those gates remain in the certification ledger.
