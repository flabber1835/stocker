# Idle leadership qualification

This qualifies the change described in [idle leadership resilience](idle-leader-resilience.md).
The independently fetched base is `c0be72ed708b20cc8fff25b0cd8e1796889377f0`.
No production settings, book, broker account, orders, alerts or services were
changed during this development and qualification task.

## Exercised failure boundaries

An established leader survives repeated uncertain clock samples without
acquiring a new fence or entering financial work. Separate slow stages retain
leadership through actual main-loop progress. A single blocked stage still
expires; expired, killed, replaced and foreign permits cannot be renewed.
The first worker instance exists before initial lease acquisition. Identical
cycle lineage is checked once per tick; changed state and execution still
require their own validation.

Idle attestation reuse expires thirty seconds after the original check start,
including a deliberately slow check; full revalidation occurs at the next
ordinary poll, rather than promising a hard completion interval. Both a
backwards skipped-poll clock and rollback
after slow completion invalidate reuse. Current revocation, lifecycle, rollout,
control and ownership remain observed; execution performs a fresh full gate.
Skipped checks do not write another PASS or move its evidence timestamp.

Leadership symptoms retain one immutable alert through cycle/holder churn and
brief recovery. Within that continuous incident sixty seconds of continuous
fresh ownership is required to rearm; an intervening independent failure
establishes a new incident boundary. Unknown reads, gaps, rollback, owner changes, expired observations and
dispatcher restart reset recovery. Current red and unacknowledged history stay
visible. Authority, integrity, overdue and unresolved-broker failures remain
independently actionable.

The source-admission campaign authenticates exact predecessor and successor
bytes, unchanged historical descriptors, missing-checker rejection, adjacent
source changes and profile/digest tampering. The full main source manifest has
344 Python files and SHA256
`a76df4344a915fda5f598db4b663636602aea4a5319b212dee60ba6cc17c2231`.
The actual formed-book boundary forbids reformation and reacquisition and
checks retained records, restart parity, idempotence and zero broker commands.
It extends the existing canonical upgrade integration test in
`test_operational_liveness_upgrade.py`. That test's declared synthetic-provider,
runtime-attestation and backup-policy fixture isolates book/admission behavior;
this is not a production GO, physical backup or real-provider certification.
The new source-pin module retains real default guards, without adding entries
to either legacy fixture registry.

## Isolated development results

The development interpreter is Python 3.12.13 with pytest 8.4.2 and psycopg
3.3.4. The private test container has no network, production volumes or broker
credentials, a 0.75 CPU ceiling, a 1 GiB memory ceiling and no extra swap.
Tests create their own PostgreSQL fixtures.

- `python -m pytest -q tests/sentinel/test_idle_leader_progress.py tests/sentinel/test_automation_clock_sampling.py tests/sentinel/test_automation_service.py`:
  97 passed, 70.28 seconds.
- `python -m pytest -q tests/sentinel/test_automation_service_fault_paths.py`:
  252 passed, 16.74 seconds. Three older mocked loop tests now permit initial
  progress records while retaining final-state, exception, notification and
  cleanup assertions. Their old single-registration expectations caused the
  initial sixteen parameterized failures; production behavior was unchanged.
- The adjacent callback-liveness module passed its 24 cases.
- `python -m pytest -q tests/sentinel/test_alert_leadership_episodes.py tests/sentinel/test_alert_attempt_fencing.py tests/sentinel/test_notification_recovery.py tests/sentinel/test_operator_monitoring.py`:
  126 passed, 143.49 seconds before the additional conservative dispatcher-start
  regression. That final regression is included in the later campaign.
- `python -m pytest -q -p no:cacheprovider tests/sentinel/test_alert_leadership_episodes.py::test_independent_failure_is_a_new_boundary_before_returning_leadership`:
  3 passed, 11.47 seconds. Authority, integrity and overdue failures each create
  an independent incident boundary; returning leadership starts a new alert,
  subsequent related symptoms reuse it, and all three original alerts retain
  their immutable payloads and unacknowledged states.

The final focused compatibility selection includes the full runtime module,
retained-source compatibility, all fifteen upgrade-contract modules and the
complete leadership-episode module, with unchanged historical `formed_book`
variants deselected. It completed 525 passing cases and found one older
mutation test whose guard was now protected by an additional independent guard.
The test now isolates the old boundary in memory, proves that it refuses first,
then removes that guard and requires failure. Both that corrected falsifier and
the new composed current-source falsifier passed on rerun; no production guard
was removed or relaxed. The single new main-to-successor formed-book boundary
passed separately:

`python -m pytest -q tests/sentinel/test_operational_liveness_upgrade.py::test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition -k idle_leader_preceding`

Result: 1 passed, 8 deselected, 127.08 seconds. The default-guard new-module
duplicate initially stopped at setup because its disposable PostgreSQL fixture
has no physical archive. No exception was added: the scenario was assigned to
the existing integration test owner and its declared controlled fixture, as
documented above. The production archive requirement remains unchanged.
All 87 final runtime tests, including slow-check and rollback cases, passed in
the focused campaign.

`python -m pytest -q -p no:cacheprovider tests/sentinel/test_idle_leader_upgrade.py`
then passed all 57 cases independently in 31.42 seconds, including the
composed current-source falsifier and full predecessor manifest closure.

An initial broader selection was interrupted after 116 passing cases and no
failures, when timings showed repeated reconstruction of unchanged historical
economic books. This is not claimed as a completed suite. Historical manifest
and predecessor contracts remain in the focused run; only the new formed-book
transition needs fresh economic reconstruction in this change.

Seven independently executed in-memory mutations were caught at their intended
assertions: removing main-progress renewal, allowing a foreign permit, splitting
leadership symptoms, removing the recovery minimum, ignoring observation gaps,
ignoring holder/fence continuity and ignoring rollback. The idle cadence and
fresh lifecycle checks also have independently observed failing mutations.
Source-admission guard falsifiers are retained as executable pytest tests.

## Mandatory automation coverage

The complete twelve-module `tools.sentinel_ci_shards.AUTOMATION` owner was run
with `python -m coverage run --branch --source=sentinel.automation.service -m
pytest`, followed by `python -m coverage report --precision=2
--fail-under=100.00`. The initial run passed 493 cases in 377.77 seconds and
found two `AttributeError: _idle_attestation` failures in an older startup
fixture that bypasses `ProductionAutomation.__init__` with `object.__new__`.
The fixture now initializes the two new idle-observation fields to `None`,
matching the real constructor. No production source or guard changed.

The affected parameterized node and the CI ownership tests were rerun with
coverage append:

```bash
python -m coverage run --append --branch --source=sentinel.automation.service -m pytest -q tests/sentinel/test_activation_startup_contention.py::test_retained_generation_first_tick_completes_actual_post_tick_hooks tests/scripts/test_sentinel_ci_shards.py
python -m coverage report --precision=2 --fail-under=100.00
```

Result: 23 passed in 20.00 seconds: both corrected startup cases and all 21
registry cases. Across the campaign all 495 mandatory automation cases passed.
The final coverage report has 816 statements, zero missed statements, 322
branches and zero partial branches: **100.00%**. The original failing run and
corrected-node JUnit/logs are retained separately rather than reporting a
single uninterrupted green run.

The first measured private-container memory peak was 431,267,840 bytes, with
zero memory-limit and OOM events. This is a measurement of this isolated test
workload, not a qualification of laptop capacity or global memory pressure.
Delays are injected without exhausting the installed host's RAM or swap.

## Scope of the claim

Local test images are development evidence and grant no deployment or broker
authority. Signed publication, existing-book admission, supported installation
and post-install observation remain required. No new trade or next-open outcome
is claimed by this report. The exact workload that originally caused WSL
resource pressure and the previous shadow container's exit path remain unproven.
