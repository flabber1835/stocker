# Autonomous Alpaca paper readiness

This implementation starts from `e3dfb033d25ed68e5e1f6d2386285afabc62e801`.
It integrates main `b1a9aadd1a9baca0c6f863ba09e29a8089e4a9f2` (PR #412).
The objective is a deployed forward paper trader. Historical performance,
provider acceptance and NAS qualification remain separate claims. Admission
already uses the selected strategy and rolling readers from PR #405.

## Recurring maintenance decision

Use the existing host physical-backup producer and exact-path verifier. A new
bounded host maintenance invocation is suitable for the NAS task scheduler;
schedule it every five minutes and on startup. It requires no broker credentials
and owns no strategy state. Do not introduce a second backup implementation, Docker
socket sidecar, or runtime schema migration.

Each invocation takes the existing physical-backup flock for the complete
observe/create/verify operation, including its children. Competing invocations
return without creating a second generation. Recompute obligations from current
verified backup evidence on every invocation: a prior success flag is never
authority. Renew at 24 hours, before the ordinary 30-hour stale boundary, or
when the verified WAL horizon reaches half the runtime byte/object budget.
Use exact segment bytes, not an assumed 16 MiB size. The scheduling interval
does not promise an unlimited write rate; archive growth and backup duration
must fit the measured NAS envelope.

Only named availability/freshness failures permit a new base. Contradictory
identity, unreadable evidence and failed integrity do not trigger deletion,
fallback, or a fabricated healthy result. A new base must pass the existing
producer and exact-path status verifier before maintenance reports success.
Failed attempts remain failures and are retried by the next scheduled run.
If an outage has already exhausted the runtime horizon, accept PR #412's exact
`BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED` status as a renewal obligation. This does
not claim integrity for the superseded chain; only the exact fresh base earns
new runtime authority. Unrecognized or duplicate status reasons still refuse.
Maintenance never deletes retained backups/WAL or changes restore authority;
capacity and a separately reviewed retention policy remain required.

The invocation has an outer process deadline and bounded captured output.
Its private process group is terminated on timeout or scheduler cancellation, including descendants;
it cannot wait indefinitely for a log line or pipe EOF. A terminated Docker
client does not prove an in-container backup stopped. Final log output also has
a bounded child deadline. Therefore the producer
also needs shared, in-container physical-backup serialization before stale
staging cleanup or copy. Keep the host lock as an additional exclusion layer.

## Informational paper reporting and execution

The owner confirmed that current reconciled paper trading must continue when
historical paper-performance certification is unavailable. Rolling deployment
already selects informational DUAL mode, whose successor path skips legacy
trial finalization. Preserve that distinction and the strict historical path.

There is a second reporting dependency: entitlement scanning requires complete
native fill rows even when current order/position/cash reconciliation is clean.
The production Alpaca adapter does not claim native history completeness.
For informational DUAL preparation only, a strictly incomplete native ledger
records an immutable reporting gap and defers entitlement calculation without
inventing fills, dividends, cash or certified returns. A later scan recomputes
coverage and can calculate entitlements when evidence arrives. Native rows that
exceed cumulative quantity/notional, disagree at complete quantity, or coexist
with unresolved commands remain refusals. Inspect all commands before deciding
that missing coverage alone explains the reporting gap.

This policy does not enable any provider capability. Current unexplained cash,
order uncertainty, ownership discrepancies, account binding, signed authority,
source integrity and exposure guards remain execution requirements. External
cash activity, trade corrections/busts, held spinoffs and restored-account
ownership still require their separately accepted source/protocol handling.

## Supervisor filesystem bounds

Run heartbeat/holder writes, latch reads and latch persistence in the existing
killable dependency observer. A failed heartbeat write leaves health stale but
cannot delay terminating an overdue active worker. Startup cannot spawn a worker
without reading latch state; unknown state refuses. Latch persistence remains
exclusive and fsynced. Bound the health command's complete structural read in a
child and return only its small verdict. No cached health result supplies runtime
or broker authority. Actual uninterruptible kernel I/O still requires independent
host monitoring; do not spawn replacements of an unreaped dependency observer.

## Local acceptance and deployment boundary

Validated offline with `sentinel-test:ci` image
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12 and temporary PostgreSQL 17 fixtures. The repository was mounted
read-only, networking disabled, and `.env` overlaid with an empty file. No NAS,
provider account or broker order was used. PostgreSQL 16/NAS qualification is
still an external deployment requirement.

All pytest commands below used
`-q --tb=short --show-capture=no -p no:cacheprovider`:

```text
python -m pytest tests/backup/test_maintenance.py tests/backup/test_shell_lifecycle.py
  74 passed (initial backup campaign)
python -m pytest tests/sentinel/test_paper_reporting_continuity.py tests/sentinel/test_paper_performance_quarantine.py tests/sentinel/test_native_fill_acceptance.py tests/sentinel/test_supervisor_dependency_bounds.py tests/sentinel/test_automation_p1_continuity.py
  59 passed
python -m pytest tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_supervisor_dependency_bounds.py
  26 passed
python -m pytest tests/sentinel/test_rolling_paper_inputs.py::test_real_paper_preparation_and_restart_reuse_only_verified_rolling_shadow tests/backup/test_maintenance.py
  30 passed (including Alpaca-named simulator and durable succeeded cycle)
python -m pytest tests/backup/test_maintenance.py tests/sentinel/test_paper_package_architecture.py tests/sentinel/test_paper_close_nav_gate.py tests/sentinel/test_shadow_service.py tests/sentinel/test_automation_runtime.py
  137 passed
python -m pytest tests/backup/test_maintenance.py tests/sentinel/test_supervisor_dependency_bounds.py
  40 passed (including bounded log and unknown latch)
python -m pytest tests/backup/test_maintenance.py tests/backup/test_shell_lifecycle.py tests/sentinel/test_go_backup_refresh.py -k 'maintenance or runtime_horizon or status_horizon or status_chain_object or go_backup_refresh'
  76 passed, 48 deselected (integration with main b1a9aadd)
```

Twenty `tools/paper_readiness_mutation_check.py` cases passed their unmodified
baseline and detected the intentional defect: `reporting-gap`, `partial-notional`,
`all-commands`, `unresolved-command`, `historical-finalization`, `heartbeat-bound`,
`health-bound`, `holder-bound`, `observer-replacement`, `unknown-latch`,
`backup-age`, `backup-wal`, `backup-integrity`, `backup-group`, `backup-deadline`,
`backup-output`, `backup-log`, `exact-backup`, `container-copy-lock`,
`backup-exhaustion`. Invoke each
with `python tools/paper_readiness_mutation_check.py CASE`. The maintained
`shadow-latch` and `reconstruction-health` cases also passed with
`python tools/economic_audit_mutation_check.py CASE`. Deliberate mutant test
failures are the expected result; surviving mutants or failed baselines fail
the checker. An initial log falsifier started a fresh pristine interpreter and
missed its in-memory mutant; it now forks the patched implementation and detects
the removed timeout.

Changed Python AST/shell syntax and `git diff --check` passed.
`python tools/validate_test_responsibility.py --base e3dfb033d25ed68e5e1f6d2386285afabc62e801`
passed with 484 test modules, no unowned tests and no new incident-named suites.
Only the documented paper-preparation AST delta was updated; frozen historical
fixtures and provider capability flags were preserved.

Before activation, deploy the reviewed image/schema, install and observe the
maintenance schedule, qualify backup/restore and resource budgets on the NAS,
obtain signed paper admission, and run the existing Alpaca paper acceptance
with the account's opening-price entitlement. Historical paper P/L remains
unverified when its sources are unavailable. Unsupported cash corrections,
held spinoffs or unexplained restored ownership still cause their existing safe
refusal; this change does not claim autonomous handling of those events.
