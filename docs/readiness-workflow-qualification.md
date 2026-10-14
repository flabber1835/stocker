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

### Close-time source frontier correction

The installed October 14 cycle stopped at `REFRESHING_DATA` with
`NonRetryableCallbackRefused` wrapping the native `RollingSourceFrontierPending`.
Read-only primary evidence showed no plan, no transport/reconciliation event,
zero commands and zero fills. The preceding broker preflight was clean. The
adapter now preserves only the direct typed pending cause; matching text and
unrelated causes still refuse. Its existing refresh callback returns bounded
`SourceDataPending` without constructing a broker or racing the publisher.
The explicit unsent recovery recognizes only that reviewed unprepared failure
and retains all shared lineage, command/UNKNOWN, pre-open, binding, certificate,
kill, ownership, idempotency and fresh-plan guards. It never edits the failed
cycle or its events. The prepared version-3 activation seals this separate
recovery alongside the retained-key initial anchor repair.

The first overlapping native/architecture pass completed 78 tests in 51.55s.
The final adjacent modules passed 305 tests in 353.82s:

```sh
python -m pytest tests/sentinel/test_dual_reconciliation.py \
  tests/sentinel/test_unsent_cycle_recovery.py \
  tests/sentinel/test_automation_runtime.py tests/sentinel/test_rolling_go_inputs.py \
  tests/sentinel/test_source_wait_recovery.py tests/sentinel/test_close_cycle_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_paper_package_architecture.py \
  tests/scripts/test_deployment_recovery.py \
  tests/sentinel/test_autonomous_deploy_bootstrap.py \
  -q -ra --tb=short -p no:cacheprovider
```

The paired request, initial repair, routing and native restore fences passed
235 tests in 36.51s, including real queue sealing of both explicit recoveries
and refusal before handoff when any confirmation is omitted:

```sh
python -m pytest tests/sentinel/test_installation_activation_separation.py \
  tests/sentinel/test_initial_paper_recovery.py tests/sentinel/test_cli_routing.py \
  tests/sentinel/test_activation_restore_upgrade_fence.py \
  -q -ra --tb=short -p no:cacheprovider
```

Eleven in-memory guard mutations were killed by the actual targeted falsifiers:
nine recovery eligibility clauses and both deletion/bypass of the typed-cause
guard. These isolated checks made no broker calls, database writes or production
changes. The exact close-cycle profile is
`7e3da169e9bb46b7e144caa7552519684e37d1266de75ce710d4985e55af6ec8`.
Offline compatibility with the authenticated original genesis passed for source
closure `d49f4573b3da1c2dbaf2b8773f1f8f46e6a92ce7e8c148f6d4c4d7bd17b0f998`.
This diagnostic grants no admission, certification or activation. The earlier
commit's full CI, including all twenty warmup tests, passed; this new source
correction requires its own final exact-head protected CI before merge.

On exact head `5deab62edb2a62f98d1b67910000d68946118ccb`, safety run
`38611753074` passed every ordinary, rolling, automation, mutation and replay
lane. Warmup job `116020000428` collected all 20 tests, passed 19, and was
cancelled at the 60-minute whole-job deadline during the final daily/restart
test. Its diagnostics showed continuing loader, canonical strategy and source
preflight work; no assertion failed. The shared production-size seed first
completed after 43 minutes. The documented CI-only correction gives this one
lane 90 minutes while retaining its complete million-row fixture, inventory,
assertions, evidence sealing and all certification gates. The cancelled run
does not qualify the release; the corrected exact head needs fresh protected CI.

The warmup-budget correction passed 102 CI ownership and evidence tests in
13.73 seconds with the command below. Its negative cases invoke the actual
deadline regression against a missing budget and the obsolete 60-minute warmup
allowance; both refuse. Python syntax and `git diff --check` passed. No Sentinel
production source changed.

```sh
python -m pytest tests/scripts/test_sentinel_ci_parallel_evidence.py \
  tests/scripts/test_sentinel_ci_shards.py \
  -q -ra --tb=short -p no:cacheprovider
```

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

### Independent legacy restore upgrade blocker

The actual installed dashboard also records the executor's separate native
increase refusal: backup-capable state predates its physical incarnation
anchor. Read-only inspection at 2026-10-14T15:11:25Z confirmed the original
cluster `7691913275518591014`, timeline 1, takeover epoch 1, zero commands and
fills, and 172 backup markers dating to October 5, with no incarnation anchor.
The anchor was absent before today's reboot. Timing optimization does not
clear this refusal. The owner explicitly chose to retain the current paper
keys. The reviewed, attended initial-anchor repair in execution contract §11.1
is separate from restored-host adoption and never asserts credential revocation.
No ordinary activation or daily invocation initializes an anchor automatically.

The existing dual plan/shadow reconciliation now checks the same native
read-only `upgrade_restore_reason` before activation and before resumed
automation starts. No additional observer, broker call or backup is introduced.
Qualification used the isolated Python 3.12/PostgreSQL runner:

```text
tests/sentinel/test_activation_restore_upgrade_fence.py
tests/sentinel/test_issue282_restore_upgrade_fence.py
tests/sentinel/test_activation_writer_handoff.py
tests/sentinel/test_activation_writer_processes.py
139 passed in 55.74s
```

Real PostgreSQL cases prove legacy backup history refuses, an existing anchor
passes, and a fresh no-backup database remains unmodified. All cases retain
the control fence and make zero broker calls. Removing the native guard is
detected. The adjacent real-process activation handoff checks passed unchanged.

The owner then explicitly retained the existing Alpaca paper keys. Qualified
the attended initial-anchor repair through the existing preparation membrane
and sealed activation request v3, with no takeover or credential operation:

```text
tests/sentinel/test_initial_paper_recovery.py
tests/sentinel/test_activation_restore_upgrade_fence.py
tests/sentinel/test_installation_activation_separation.py
tests/sentinel/test_activation_writer_handoff.py
tests/sentinel/test_activation_writer_processes.py
tests/sentinel/test_activation_completion_protocol.py
368 passed in 71.85s

tests/sentinel/test_initial_paper_recovery.py
tests/sentinel/test_activation_restore_upgrade_fence.py
tests/sentinel/test_activation_writer_handoff.py
tests/sentinel/test_close_cycle_upgrade.py
192 passed in 117.73s

tests/sentinel/test_paper_activation.py
tests/sentinel/test_cli.py
tests/sentinel/test_anytime_paper_activation.py
127 passed in 70.06s

tests/sentinel/test_rolling_paper_inputs.py -k production_alpaca_dual_preparation
2 passed, 35 deselected in 100.34s

tests/sentinel/test_initial_paper_recovery.py
tests/sentinel/test_activation_writer_handoff.py
169 passed in 30.89s (final added guard-removal cases)
```

The joined rolling test uses real PostgreSQL, the native Alpaca adapter,
generation-fenced preparation reads and mocked HTTP responses. Both ordinary
and explicit initial repair prepare/re-read the same canonical plan, preserve
the exact original shadow records and binding, make only GET requests, and
create zero broker commands. Historical fill transport remains quarantined.
The one-time receipt resumes after lost acknowledgement without another
repair observation or row update. Partial/foreign/nonempty/unstable/stale
broker evidence, incorrect cluster/timeline, a live lease, enabled control,
any command including UNKNOWN, changed authority and conflicting or tampered
receipts refuse. Actual second-insert and no-op receipt-claim failures roll
back the anchor through the existing canonical writer context.

Fifteen additional native/host guard removals were detected, covering the
local broker/cluster/timeline/control/lease/never-traded boundaries, declared
recovery, fresh authority, atomic receipt claim, the canonical writer boundary,
explicit confirmation, flat cash/equity, observation freshness, guarded read
transport and request forwarding. Final source compatibility against the
authenticated original genesis passed offline with candidate closure
`28232fe41bac4e716ce5ce1840a214b7c39178ef078bccf9539cc568509acd0a`.
This diagnostic still grants no admission, certificate or production authority.

The final protected general-0 shard passed 2,105 cases and rejected an
unreviewed edit to `shadow_service_status.py` correctly, but its older assertion
expected the later economic-source refusal. Since that file is also an exactly
pinned addition, the closure guard rejects it first. Corrected only the test
to require the literal closure refusal for additions and the exact economic
refusal plus filename for other successors; no product guard, profile, source
closure or golden fixture changed. Targeted final validation:

```text
tests/sentinel/test_shadow_ui_upgrade.py
tests/sentinel/test_close_cycle_upgrade.py
tests/sentinel/test_retained_source_compatibility.py
69 passed in 285.88s
```

The corrected protected run's general-2 shard passed 1,573 cases and found
that the current reviewed paper delta registry still described
`prepare_paper_plan` before its documented initial-recovery hook. Registered
that intentional change, its existing design and completed acceptance paths
in `production-champion-paper-deltas.json`. The frozen historical equivalence
manifest and historical AST hash remain unchanged. The current normalized
definition is `e58b347bd8f6a095177670b5834b09debfcddf4245c1c39833119853f59e45fa`.
A deliberately wrong preparation fingerprint still fails the exact registry
check. No product code or source closure changed in this correction.

```text
tests/sentinel/test_paper_package_architecture.py
tests/sentinel/test_initial_paper_recovery.py
tests/sentinel/test_cli_routing.py
tests/sentinel/test_installation_cli_boundaries.py
80 passed in 37.26s
```

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
