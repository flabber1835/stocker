# Autonomous Alpaca paper readiness

This implementation starts from `e3dfb033d25ed68e5e1f6d2386285afabc62e801`.
It integrates main `29cdd7727ba2adea27672830c538d76a2218943e` (PR #413), including PR #412.
The objective is a deployed forward paper trader. Historical performance,
provider acceptance and NAS qualification remain separate claims. Admission
already uses the selected strategy and rolling readers from PR #405.

## Recurring maintenance decision

### Audit remediation and integration, 2026-09-19

Integrate main `29cdd7727ba2adea27672830c538d76a2218943e` and use its
single recurring coordinator and restore-gated retention contract in
`backup-recurring-maintenance.md`. Its cluster-bound selected generation,
12-hour/256-MiB renewal policy, one-minute schedule, semantic restore receipts
and shared media lock supersede this PR's initial renewal-only policy. Missing
or invalid runtime selection must refuse maintenance, even if a newer complete
directory exists. Initial missing selection requires the verified producer;
maintenance must never call such a state healthy. Preserve bounded process
execution/output/cancellation around this coordinator, including loop ticks.
The outer tick budget is 3600 seconds to accommodate its full restore drill.

Before launching a shadow worker, exclusively create and fsync a pending-worker
marker in the durable state directory. Remove and fsync it only after observing
a recognized recoverable outcome or completing supervised termination. A terminal
refusal retains this marker even if writing its detailed critical latch times
out. Both markers fence startup and health; persistence failure is reported and
held unhealthy rather than escaping into an unlatched restart. Retry detailed
latch persistence while fenced. Never launch if arming or clearing the marker
has an unknown outcome.

This deliberately treats host/process loss during an unacknowledged attempt as
an unknown worker outcome requiring operator inspection and clearance, rather
than guessing it was recoverable. Normal success, availability retries and
supervised hard deadlines still permit continuation. To clear an incident, stop
the service, inspect the worker outcome and repair the underlying cause, then
archive both `shadow-supervisor-critical.json` and
`shadow-supervisor-pending.json` before restarting. Preserve these as incident
evidence. No broker or strategy authority changes.

The production entry remains `scripts/sentinel-backup-maintenance.sh`. A tick
runs through a bounded process supervisor before environment loading and lock
acquisition; the optional `--loop` delegates to the same bounded tick. Preserve
the canonical coordinator's immutable image/checkout binding, current primary
observation, selected-base read, exact-path verification, full semantic restore
receipt and guarded retention. There is no parallel renewal implementation.

Per-command and total invocation deadlines include output collection. Captured
stdout and stderr together are limited to 256 KiB; small receipt input is also
bounded. Final scheduler logging has a one-second child deadline. Timeout or
scheduler cancellation kills the outer private process group. Inner commands
remain in that group, and inherit the verified physical-backup lock. Actual
Docker workers retain main's shared media lock and independent lifetime limits;
a dead Docker client never proves its worker has stopped.

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

## Initial local acceptance and deployment boundary

The following campaign describes the pre-audit implementation at fc20305.
The audit-remediation acceptance below supersedes its backup policy and mutation seams.

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

## Audit-remediation acceptance

The two findings at head `efc20305114a9707d0f334ba3bf6270f21e3175d` are
covered by permanent regressions. A delayed detailed-latch write leaves the
pre-existing pending marker durable, reports critical state, and starts no
replacement worker after restart. Missing runtime selection after the producer's
promotion returns maintenance failure, even though ordinary directory-discovery
status succeeds. This is a safe refusal; an initial missing selection still
requires the verified producer, not inferred recovery authority.

Final validation used the same offline Python 3.12 test image and read-only
repository/empty `.env` overlay as above. Commands below use
`-q --tb=short --show-capture=no -p no:cacheprovider`:

```text
python -m pytest tests/sentinel/test_supervisor_dependency_bounds.py tests/backup/test_maintenance.py tests/backup/test_recurring_maintenance.py::test_promoted_backup_without_runtime_selection_cannot_be_healthy tests/sentinel/test_paper_reporting_continuity.py tests/sentinel/test_paper_performance_quarantine.py tests/sentinel/test_native_fill_acceptance.py
  86 passed in 62.07s
python -m pytest tests/host_python38/test_env_ingestion.py tests/backup/test_maintenance.py -k 'sentinel_backup_maintenance_sh or malformed_webhook_errors or test_maintenance.py'
  40 passed, 844 deselected in 20.34s
```

A broader integration run of `test_supervisor_dependency_bounds.py`,
`test_automation_p1_continuity.py`, `tests/backup/test_maintenance.py`,
`tests/backup/test_recurring_maintenance.py`, `tests/backup/test_shell_lifecycle.py`
and `tests/host_python38/test_env_ingestion.py` produced 987 passes and 29
entrypoint failures. Those failures exposed a fixture import side effect and
changed preflight argument/diagnostic routing. Both were corrected; every failed
case is included in the final 40-pass command above. The backup lifecycle and
recurring retention cases passed in that integration run.

The following `python tools/paper_readiness_mutation_check.py CASE` checks each
passed the original source and detected the intentionally broken guard:
`worker-arm`, `pending-health`, `latch-timeout`, `backup-selection`, `backup-age`,
`backup-wal`, `exact-backup`, `backup-group`, `backup-deadline`, `backup-output`,
`backup-log`, `container-copy-lock`. The logging case was repeated after the
diagnostic routing correction. Earlier renewal-only mutation seams were replaced
with the canonical coordinator's age, WAL and exact-selection guards.

Python AST and shell syntax checks passed, including Python 3.8 parsing of the
host coordinator and process helper. `git diff --check` and
`python tools/validate_test_responsibility.py --base 29cdd7727ba2adea27672830c538d76a2218943e`
passed (485 test modules, no unowned or new incident-named tests). The host
environment tests here ran under Python 3.12; target interpreter/NAS execution
and provider qualification remain separate deployment checks. No broker orders,
NAS changes or merge were performed.
