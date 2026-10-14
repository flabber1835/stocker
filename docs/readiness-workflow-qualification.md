# Readiness workflow qualification

Local qualification uses Python 3.12.13, Node 20.19.2 and disposable PostgreSQL
databases. Test containers have no network, production database mounts or broker
credentials. CPU is bounded while the installed paper system continues running.
This is source qualification; it grants no image certification or activation.

## CI coverage ownership repair

The initial automation lane passed all 433 selected tests but failed its
unchanged 100% coverage gate at 99.26%. The clock sampling module had been
assigned to an ordinary shard instead of the automation coverage owner.
Registering it in the existing automation registry preserves one execution
owner and restores the coverage contract. No production code or threshold
changes are needed for this repair.

The corrected automation registry passed 444 tests under:

```sh
python -m coverage run --branch --source=sentinel.automation.service \
  -m pytest "${modules[@]}" -q -ra --junitxml=/evidence/automation.xml
python -m coverage report --precision=2 --fail-under=100.00 -m
python -m pytest tests/scripts/test_sentinel_ci_shards.py -q -ra
```

`modules` is the exact list returned by `automation_modules` from the same
registry used by protected CI. Coverage is 100.00%: 774 statements and 312
branches, with no missing statements or partial branches. All ten shard
inventory tests passed, including the clock module's unique coverage owner.

## CI regression fixture repair

The ordinary general shard passed 1,914 tests and found two fixtures that still
assumed the previous interface. Reviewed dual mode now includes the read-only
next-open plan alongside broker evidence. Finalization now requests exact
current-proof reuse when no earlier activation milestone is present.

The repaired dashboard test keeps the alternate-book readers forbidden, checks
that only dual mode reads the optional plan, and requires a missing plan to be
pending. The finalization test accepts the explicit reuse option, requires one
full-proof reuse request and checks that its exact backup reaches the receipt.
These repairs change tests only; production code and safety gates are unchanged.

The regression modules and their adjacent panel, plan and backup paths passed
all 189 tests in 36.02 seconds under:

```sh
python -m pytest tests/sentinel/test_current_dashboard_evidence.py \
  tests/sentinel/test_final_deploy_overnight_readiness.py \
  tests/sentinel/test_panel.py tests/sentinel/test_paper_plan_preview.py \
  tests/scripts/test_installation_efficiency.py \
  -q -ra --tb=short -p no:cacheprovider -o faulthandler_timeout=60
```

## Targeted results

The final general-2 CI lane passed all 1,538 tests in 44m24s. Its existing
45-minute whole-job deadline also included checkout and image loading, so the
job was cancelled before sealing its successful lane receipt. Both required
aggregators correctly refused that missing evidence. The documented repair
gives ordinary general shards the same bounded 60-minute setup/cleanup/evidence
allowance as rolling and warmup shards, without changing test selection,
coverage, source/attempt binding or aggregation. The cancelled result remains
unqualified; the new head requires a fresh protected CI run.
The CI ownership/evidence checks passed all 98 tests in 15.14 seconds. Invoking
the actual deadline regression against a missing budget and the obsolete
45-minute general-shard budget detected both deliberately broken configurations.

```sh
python -m pytest tests/scripts/test_sentinel_ci_parallel_evidence.py \
  tests/scripts/test_sentinel_ci_shards.py \
  -q -ra --tb=short -p no:cacheprovider
```

The following command passed 355 tests, with six cold formation fixtures
deselected because Wealth Core is unchanged. Exact retained-source admission
and the real authenticated origin are checked separately below.

```sh
python -m pytest \
  tests/backup/test_activation_checkpoint.py \
  tests/backup/test_activation_checkpoint_replay.py \
  tests/backup/test_recurring_maintenance.py \
  tests/sentinel/test_paper_plan_preview.py \
  tests/sentinel/test_paper_plan_notifications.py \
  tests/sentinel/test_shadow_ui_upgrade.py \
  tests/sentinel/test_startup_contention_upgrade.py \
  tests/sentinel/test_open_time_upgrade.py \
  tests/sentinel/test_dashboard_monitor_upgrade.py \
  tests/sentinel/test_autonomous_deploy_bootstrap.py \
  tests/sentinel/test_panel_browser_refresh.py \
  tests/sentinel/test_panel_refresh_inspection.py \
  tests/sentinel/test_panel_concurrency.py \
  -k 'not formed_book' -q -ra --tb=short -p no:cacheprovider \
  -o faulthandler_timeout=60
```

The following command passed 563 tests, including the real run loop after a
slow clock query, stale timestamp refusal, callback death, lease/authority
fencing, execution lateness and activation completion boundaries.

```sh
python -m pytest \
  tests/sentinel/test_automation_clock_sampling.py \
  tests/sentinel/test_automation_service.py \
  tests/sentinel/test_issue_201_automation_financial_grade.py \
  tests/sentinel/test_automation_service_fault_paths.py \
  tests/sentinel/test_activation_startup_contention.py \
  tests/sentinel/test_installation_activation_separation.py \
  tests/sentinel/test_activation_completion_protocol.py \
  tests/sentinel/test_autonomous_deploy_driver.py \
  -q -ra --tb=short -p no:cacheprovider -o faulthandler_timeout=60
```

## Guard falsification and recovery

Adjacent outbox recovery and Web Push attempt fencing passed another 62 tests:

```sh
python -m pytest tests/sentinel/test_automation_outbox.py \
  tests/sentinel/test_notification_recovery.py \
  tests/sentinel/test_web_push_attempt_fencing.py \
  -q -ra --tb=short -p no:cacheprovider
```

Changed Python files compile, host helpers parse with Python 3.8 syntax, and
`git diff --check` passes. Deprecation warnings come from the existing Starlette
test client and multiprocessing callback supervision.

The protected mutation lane's exact disposable-copy command completed with all
17 deliberately broken guards detected by failing tests:
exact immutable runtime, full restore receipt, selected metadata, committed
flush boundary, contiguous archive coverage, original archive deadline,
planned INFO delivery, notification expiry, fresh clock sampling, sample
precision, real drift, clock uncertainty, duplicate boundary fields, duplicate
opening slots, obsolete queued-plan delivery, independent critical delivery
and polling gaps after slow work.

`tools/sentinel_readiness_falsifiers.py` runs only in the disposable
`/tmp/repo` copy with `/source` mounted read-only. The actual workflow command
was syntax-checked and executed locally using the existing test lens.

The PostgreSQL recovery test creates one physical base, then commits a plan,
enabled-but-killed control and the production checkpoint marker in later
sessions. Restoring that same base through the captured flushed LSN recovers
all three while PostgreSQL is in recovery. No second base is created.

## Actual retained source and browser

A SELECT-only installed reader authenticated the original genesis and its
current admission. Candidate compatibility was then proved offline against the
origin's exact Git manifest, preserving the environment, strategy, capital and
source constraints. Original revision:
`368669bbb60abe946a11b1a527308a5106a1183e`. Candidate Sentinel source closure:
`0c3dc94d225abb85ff5c6868100f3abd37f830b754779032c035ca0651095585`.
There were no financial writes, broker calls, new admissions or certificates.

The actual browser, against a synthetic local fixture, showed:

- current green backup/plan cards and amber WAITING_OPEN;
- an expandable dated buy/sell target table with Pacific execution time;
- amber busy responses retaining the original timestamp;
- red expiry at the original 45-second budget;
- red known-negative cards and headline during a busy refresh;
- recovery only after a valid fresh CURRENT response.

The fixture and test tab were closed. The automated browser harness also covers
transport failures, malformed responses, offline/background restoration,
overlapping requests, finite retries and expiry without timestamp renewal.

The installed release remains unchanged pending protected CI and immutable-image
certification. The owner authorized three additional merges and the certified
install, deferred until Wednesday's original opening cycle finished.

## October 14 restart and opening-path qualification

Windows System events record planned update restarts at 23:29 and 23:32 Pacific.
Docker/WSL resumed at 05:35. The installed publisher's legacy interrupted marker
was preserved under `operator-incidents` after authenticated current-book
verification, and the same publisher resumed. Automation and PostgreSQL stayed
running during that targeted recovery. All nineteen original book records,
the original cluster/account binding and the earlier failed-cycle histories
remained unchanged. Five inspected, recovered clock/restart alerts were
acknowledged through the supported CLI, preserving incident/delivery history.

The Wednesday cycle fired at 06:31, submitted zero commands, and was superseded
at 06:43:54 with MAX_EXECUTION_LATENESS_EXCEEDED after clean reconciliation.
GET-only Alpaca evidence confirmed zero orders/positions and $50,000 cash/equity.
The cycle has not been reopened and no late orders were sent.

Exact additional commands used the existing isolated test lens and
`python -m pytest -q -ra --tb=short -p no:cacheprovider`:

```text
tests/sentinel/test_shadow_restart_recovery.py
tests/scripts/test_sentinel_ci_shards.py
tests/sentinel/test_shadow_active_worker_health.py
tests/sentinel/test_review_followup_20260825.py
77 passed in 41.92s (before the production-size startup budget adjustment)

tests/sentinel/test_rolling_shadow_restart_recovery.py
tests/sentinel/test_supervisor_dependency_bounds.py
tests/sentinel/test_shadow_worker_monitoring.py
63 passed in 179.81s

tests/sentinel/test_rolling_snapshot_verification_scope.py
tests/sentinel/test_rolling_paper_inputs.py
tests/sentinel/test_shadow_restart_recovery.py
tests/sentinel/test_automation_runtime.py
tests/sentinel/test_automation_clock_sampling.py
tests/scripts/test_sentinel_ci_shards.py
160 passed in 691.20s

tests/sentinel/test_automation_runtime.py
-k 'operational_execute_pins or removed_operational_execution_pin'
3 passed, 60 deselected in 1.17s

tests/sentinel/test_supervisor_timing_admission.py
tests/sentinel/test_activation_writer_processes.py
tests/sentinel/test_shadow_heartbeat_isolation.py
51 passed in 72.87s

tests/sentinel/test_shadow_heartbeat_isolation.py
7 passed in 22.45s after forwarding the real inherited owner descriptor
```

The completed passes include eight restart guard removals, four snapshot reuse
guard removals, the execution pin removal and the obsolete shard-weight falsifier. The real PostgreSQL
restart checks preserved checkpoint and plan/command/fill row counts, refused
candidate/tampered/foreign state, and constructed no broker. The final separate
run verifies pin acquisition before resolver construction and release on both
resolver and execution failures, including removal of that sequencing guard.

The actual 1,582,763-row production input closure was measured with the proposed
two source files mounted read-only in a disposable diagnostic container. One
complete unchanged hash verification took 31.954 seconds. Five reference
readers took 0.758–0.824 seconds each; canonical readiness counts took 20.600
seconds. Exactly one full scan occurred under the real publication pin. No
broker credentials or execution grants were supplied, the connection remained
read-only, and no financial state was changed. This unsigned benchmark grants
no GO, activation or trading authority and does not by itself certify the full
network execution latency.

The latest original-genesis compatibility diagnostic passed offline against
the authenticated origin, preserving source/environment/strategy/capital
constraints. Candidate Sentinel closure:
`c723590e43bf7190d1c0c4adca70e7d48cc1bd2db7587c1527673be7abd9a333`.
This is unsigned compatibility evidence, not a new admission or certificate.
Windows unattended startup before login still needs host qualification;
publisher recovery does not establish that property.
