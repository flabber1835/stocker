# October 15 incident and attended paper rehearsal

**INCOMPLETE: not a trading-readiness or installation certificate.**
Verified main: `71abaa4c158ffbeae762d7272b6204d59590fee8`.
[Design, incident timeline and pending decisions](../../docs/paper-system-rehearsal.md).

The overnight leader interruption overlapped a restore drill. The same worker
reacquired its lease; no container restart, OOM kill or Windows sleep was seen.
Resource contention is supported, but retained telemetry cannot distinguish
the exact CPU, I/O or memory bottleneck.

At the open, unchanged-book verification held the account writer. Execution
failed before creating a command or PENDING stamp. Recovery then permanently
refused the unstamped plan. Production submitted zero orders. The patch moves
one complete unchanged-book verification outside the writer and permits only
proven-unsent recovery with the exact current clean account reconciliation.
Any durable plan command or contradictory evidence still refuses. Auxiliary
health-file repair takes a brief lock after comparing the verified inventory;
it does not repeat a backup or hold the lock during a full book scan.

## Actual provider evidence

| Scenario | Result |
|---|---|
| Real market buy/fill and sell/fill | PASS on Alpaca paper |
| Resting limit order and cancellation | PASS; canceled, zero fill |
| Accepted acknowledgement deliberately lost | PASS; exact key recovered fill |
| Actual process death before journal acknowledgement | PASS; SEND_PENDING recovered without duplicate purchase |
| Repeated settled native SPY execution | PASS; no extra command |
| Canonical book scaled to $5,000 test purse | PASS; authenticated book, 11 nonzero stock targets |
| Full canonical basket execution | FAIL; five buys filled; next attempt locally refused on ATEX quote age 34.7s, retained UNKNOWN |
| Owner-authorized cleanup of five confirmed holdings | PASS; flat, no open orders; combined ledgers reconcile |
| Full service schedule, close/preparation and notifications | INCOMPLETE; intraday scheduling approval pending |
| Native partial fill / cancel-fill race | Not observed; no provider PASS claimed |

Independent Alpaca read at **16:07:19 UTC**: cash/equity **$49,995.80**,
positions **0**, open orders **0**. The native failure journal retains UNKNOWN;
cleanup is in a separate attended ledger. This is not clean native
reconciliation, and that failed run is closed to further use. Production stays
disabled/killed for the rehearsal and owner account reset. No installation.

## Backup and rendering evidence

The owner approved daily/8 GiB renewal, the 16 GiB hard bound and at most five
minutes of integrity reuse. Full semantic restore remains once per new selected
base; other callbacks reuse its exact receipt. Heavy work defers during market
and close preparation.

Actual PostgreSQL **16.14**, **512 MiB / 0.5 CPU**, 1,024 default WAL segments:
16 GiB sparse payload, cold double proof **91.01s**, reused proof **0.387s**,
every SQL statement within **3s**, test journal unchanged. This is isolated
payload measurement, not populated production or independent/NAS media
certification. A previous PostgreSQL 17 warm check took 7.45s; bulk lstat removes
thousands of forks. Positive path coverage refuses missing and successfully
omitted results as well as symlinks, hardlinks and nonregular files.

The final physical harness passed actual base creation, PostgreSQL proof,
missing/corrupt middle WAL, repair, metadata permissions and alias/ownership
refusal. Runtime reuse cannot extend its original expiry; operator full status
still hashes content.

A frozen incident replay used the actual retained pre-open plan: 13 ticker rows
at 390px and 1280px, no page overflow, readable words and a 650px horizontal
table. This is a rendering test, not today's active plan. The uninstalled
candidate is not claimed to have a green live dashboard.

## Exact local qualification

Python 3.12 lenses mounted source read-only, with Node for browser tests.
No `make test` or `tests/wealth_core` run.

```text
python -m pytest tests/backup/test_alias_probe_script.py tests/backup/test_runtime_backup_integrity.py tests/backup/test_runtime_backup_bounds.py tests/backup/test_recurring_maintenance.py -q --tb=short -p no:cacheprovider
129 passed

python -m pytest tests/sentinel/test_open_time_upgrade.py tests/sentinel/test_close_cycle_upgrade.py tests/sentinel/test_panel.py tests/sentinel/test_panel_plain_language.py tests/sentinel/test_panel_browser_refresh.py tests/sentinel/test_paper_plan_preview.py tests/sentinel/test_live_paper_rehearsal.py tests/sentinel/test_native_paper_rehearsal.py -k 'not actual_formed_book_preserved' -q --tb=short -p no:cacheprovider
280 passed, 2 deselected

python -m pytest tests/sentinel/test_paper_plan_preview.py -q --tb=short -p no:cacheprovider
16 passed (including retained ticker reader and ambiguity refusal)

python -m pytest tests/sentinel/test_native_paper_rehearsal.py tests/sentinel/test_live_paper_rehearsal.py -q --tb=short -p no:cacheprovider
34 passed (including exact single-use transport tickets, refusal before the adapter, mandatory exclusive ownership, closed-journal and exposure falsifiers)

python -m pytest tests/backup/test_activation_checkpoint.py tests/backup/test_runtime_backup_authority.py tests/sentinel/test_native_paper_rehearsal.py tests/sentinel/test_live_paper_rehearsal.py -q --tb=short -p no:cacheprovider
111 passed after correcting two CI expectations: the WAL fixture now reaches the approved 8 GiB renewal threshold, and auxiliary health repair is the only allowed recovery-only caller in rolling_runtime

python -m pytest tests/sentinel/test_automation_runtime.py -k unstamped -q --tb=short -p no:cacheprovider
11 passed, 64 deselected; each durable command state refuses and removing the command-absence guard permits the unsafe request

python -m pytest tests/sentinel/test_rolling_runtime.py tests/sentinel/test_shadow_health_projection.py -k 'same_session or projection or changed_inventory' -q --tb=short -p no:cacheprovider
25 passed, 21 deselected (native busy writer, one full read, missing/old-config health repair, I/O refusal and inventory falsifier)

python -m pytest tests/sentinel/test_open_time_upgrade.py tests/sentinel/test_close_cycle_upgrade.py -q --tb=short -p no:cacheprovider
41 passed on final source, including both actual formed-book upgrades

python -m pytest tests/backup/test_shell_lifecycle.py -k runtime_horizon -q --tb=short -p no:cacheprovider
7 passed; obsolete remaining count assertion corrected, real-manifest final rerun: 1 passed

bash scripts/test-backup-runtime-media.sh
PASS on final backup source; work explicitly on disk
```

Failed attempts remain recorded: first media test correctly refused small
RAM-backed /tmp; first native fixture refused archive_mode=off before transport.
Its successor used real archiving, pg_basebackup and pg_verifybackup. Missing
Node, an incorrect held-target assertion, old 1 GiB fixture geometry/counts,
per-object Python stat overhead and profile regeneration during collection were
corrected and rerun. No failing attempt is relabelled a pass. Full automation
runtime tests also passed in a 128-test runtime/compatibility follow-up.

A read-only comparison at 15:57:35 UTC preserved all **22** original production
financial records, binding, original plans, terminal cycles and events.
Production commands remained **0**. Private ledger digests/sizes are in
[evidence.json](evidence.json); credentials/account identities are excluded.

## Remaining acceptance

Approve and implement the isolated intraday service fixture. Requalify the
repaired pre-transport boundary, rerun the full basket in a fresh journal, and exercise
actual service transitions, restart, concurrency, close/preparation and
notification delivery. Preserve the failed journal. Complete exact-head CI
before review readiness. Installation/activation also requires signed release
certification and reconciliation after the owner's paper-account reset.
