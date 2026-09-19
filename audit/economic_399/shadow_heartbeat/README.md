# Stage 1: shadow heartbeat failure containment

Verified main: `ec8351ff2f535885d5a1cefcbca9b9bb83498b5c`.
Work branch: `codex/supervisor-filesystem-bounds`; PR-only delivery to
`flabber1835/stocker:main`. Design was recorded in
[shadow-heartbeat-isolation.md](../../../docs/shadow-heartbeat-isolation.md)
before implementation. No NAS, provider or broker account was accessed.

## Findings and dispositions

| Finding | Severity | Local disposition |
|---|---|---|
| Synchronous heartbeat touch can suspend the deadline thread | P2 liveness | `sentinel/shadow_supervisor.py:36`: one-second killable observer, including a test touch that ignores SIGTERM. |
| Heartbeat exception exits without cleaning up the active worker | P2 lifecycle | `sentinel/shadow_supervisor.py:313`: finally disposes/reaps the worker before best-effort bounded heartbeat removal. Actual test worker ignores SIGTERM and requires SIGKILL. |
| Heartbeat failure can discard an already-observed terminal exit before durable latching | P1 integrity-refusal persistence | `sentinel/shadow_supervisor.py:277`: classify/persist terminal outcomes before touching the heartbeat. A real exit-2 worker plus write failure must still leave the original refusal on disk. |

The first acceptance run against unchanged main reproduced **2 failures and
1 positive pass**. The first implementation passed **119** related cases. A
subsequent ordering case reproduced the lost latch (**1 failed, 4 passed**),
first using a substituted exit classification, then independently using an
actual exit-2 process. Only the latter is acceptance evidence for the final
ordering fix; both attempts are retained. No historical economic value is
involved and no golden or capability flag changed.

## Reproduction and final results

Use local Docker and the repository's `sentinel-test:ci` image. The runner
copies sources into disposable `/tmp/repo`, excludes `.env` and `.git`, binds
the source read-only, and disables container networking. Related SQL tests use
disposable PostgreSQL inside that container. No host database is addressed.

```
python audit/economic_399/shadow_heartbeat/run_local.py regression
# 121 passed, 1 existing Starlette/httpx deprecation warning, 27.52s
python audit/economic_399/shadow_heartbeat/run_local.py mutations
# touch_boundary, exception_cleanup, refusal_order, cleanup_boundary: KILLED
```

Each mutant first runs its unmodified passing acceptance case in a fresh
interpreter; the altered case must exit 1 with exactly one failed test. Mutation
is restricted to the disposable source copy and original bytes are restored.
The tests always clean up their own processes on failure. The normal-stop
positive case retains real signal handling, heartbeat writes and worker reaping.
Only the test worker payload/config and termination grace (0.1s instead of the
production 5s) are substituted. Production worker/deadline semantics are unchanged.

Static and ownership commands:

```
python -m pyflakes sentinel/shadow_supervisor.py tests/sentinel/test_shadow_heartbeat_isolation.py audit/economic_399/shadow_heartbeat/run_local.py audit/economic_399/shadow_heartbeat/mutations.py
python tools/validate_test_responsibility.py --base origin/main --output <evidence>/ownership.json
git diff --check
```

Pyflakes and syntax parsing pass; ownership: **483 modules, zero unowned**.
`results.zip` retains the failed attempts, passing final output and ownership
report. `SHA256SUMS.json` binds source and artifact bytes. Prior audit packages
remain unchanged; test counts overlap and are not a coverage percentage.

## NAS handoff and remaining gates

1. After owner merge and accepted CI, record commit/tree and immutable runtime
   image identities. Use only an isolated qualification clone, no broker
   credentials or external network. Preserve existing latch/checkpoint evidence.
2. Run the regression and four mutations above with a test environment matching
   the deployed dependencies. Retain full output. Pass: all cases pass without
   unexpected skips/xfails and every mutant fails its named acceptance case.
3. In that separately authorized clone, inject failed/stalled heartbeat writes
   and removal while recording parent/worker/observer PIDs and monotonic times.
   Pass: the observer reaches its one-second timeout, the active worker is
   disposed within the existing five-second grace plus kill/reap overhead, no
   replacement starts in the failed supervisor, and independent health is red.
   A known terminal worker outcome must retain its original durable latch across
   restart. Any live orphan, renewed deadline or missing refusal fails the gate.
4. Separately qualify kernel-uninterruptible I/O, persistent-state mount failure,
   parent SIGKILL, container/NAS restart, real external alert delivery and full
   universe status/resource limits. These tests do not prove those guarantees.

C1/F6 cash completeness/finality, F19 provider fill authority/corrections, C3
predecessor-incarnation evidence, entitlement/spinoff handling, and authenticated
historical inputs/replay remain separate. Stage 1 and economic certification
are not complete. Pending maintenance PR #413 is independent of this source fix.
