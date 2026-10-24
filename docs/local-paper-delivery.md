# Resumable local PAPER delivery

This is the current owner-authorized software delivery path. It uses the tracked
`scripts/sentinel_local_delivery.py` command on the Linux/WSL Docker host. It
does not merge a PR or grant financial authority. See the
[current operating contract](sentinel-deployment.md) and
[consolidation design](code-simplification-20261023.md).

## Required inputs

- A clean, committed feature checkout descended from the installed predecessor.
- Its completed predecessor installation receipt. The first generic delivery
  accepts the retained completed installer receipt; later deliveries consume a
  generic operation's authenticated `receipt.json` at `VERIFIED`.
- An independently reviewed JSON list of the exact changed paths and its SHA256.
  The source-only builder accepts additions/modifications, not deletions,
  renames or dependency changes.
- A completed qualification report and its SHA256, retained logs and complete
  tracked-file hashes. The report must describe the exact clean commit.
- A private operation directory **outside the qualified source checkout** with
  an existing parent. Use a distinct directory and operation ID per delivery.

The qualification schema is `sentinel.local-paper-qualification/1`. Its exact
top-level fields are `schema`, `commit`, `predecessor_commit`, `at`,
`source_files`, `results`, `source_files_unchanged` and `final`. The last two must
be true; `at` must be an aware UTC timestamp. `source_files` maps every tracked
path to its actual SHA256, including tests, scripts and documentation.

Each result has `name`, `exit_code`, `passed`, `skipped`, `deselected`, `log`,
`log_sha256` and `command`. Names are unique, exit code is zero, passed is
positive, and skipped/deselected are zero. Logs use absolute paths and retain
their exact hashes. Their final passing summaries must agree with the recorded
counts. A Boolean claim of success, an incomplete file list or a changed log is
insufficient. Produce this report from completed qualification; do not invent
results or re-pin historical fixtures to satisfy admission.

## Build, prepare and inspect

The following are templates, not literal paths or identities. Replace every
angle-bracket placeholder with the independently verified value. These shell
examples run in Linux/WSL; never shell-source the installed `.env`.

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py build \
  --source <absolute-source-checkout> \
  --deployment <absolute-installed-release> \
  --predecessor-receipt <absolute-completed-predecessor-receipt.json> \
  --qualification <absolute-final-qualification.json> \
  --qualification-sha256 <qualification-sha256> \
  --allowed-delta <absolute-approved-path-list.json> \
  --allowed-delta-sha256 <approved-path-list-sha256> \
  --operation-dir <absolute-new-operation-directory> \
  --commit <exact-40-character-candidate-commit>
```

Build is offline from the already installed exact foundation image. It copies
the qualified Sentinel sources into a new layer, preserves dependencies/runtime
configuration, verifies actual source and economic identities, and records
`build-started.json`, `build.log`, `source-context/` and `build.json`.
An existing build-start marker refuses automatic rebuilding. Preserve and
inspect it after failure instead of erasing it and guessing the outcome.

Use the `build_record` and `build_sha256` returned by the successful command:

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py prepare \
  --operation-dir <absolute-operation-directory> \
  --build-record <absolute-operation-directory>/build.json \
  --build-sha256 <returned-build-json-sha256> \
  --operation-id <unique-lowercase-operation-id>

python3 -B <source>/scripts/sentinel_local_delivery.py status \
  --operation-dir <absolute-operation-directory>
```

Prepare validates the retained build/qualification and creates an immutable
`request.json`; it refuses to replace an existing request or receipt. The
digest-linked `receipt.json` binds each completed stage and its artifacts to
that request. Do not hand-edit either record.

## Advance and recover supported stages

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py advance \
  --operation-dir <absolute-operation-directory> --one-stage

python3 -B <source>/scripts/sentinel_local_delivery.py resume \
  --operation-dir <absolute-operation-directory>
```

`advance` and `resume` use the same coordinator. Without `--one-stage`, they
continue supported stages until completion or a refused gate. With it, they
perform only the next transition. An exclusive host lock prevents competing
delivery operations. Inspect `status` and retained evidence after interruption.

| Stage | Meaning and supported continuation |
|---|---|
| `NEW` | Read-only old/new canonical proof, current prepared future plan/source, configuration, native PAPER positions and zero open orders are checked. |
| `PREFLIGHT_PASS` | The full proof and unchanged state are retained; a fresh idle sample permits recording stop intent. |
| `STOP_REQUESTED` | Durable intent precedes graceful application stop. Resume verifies identities, original proof freshness and idle/pending-worker evidence before completing the stop. |
| `APPLICATIONS_STOPPED` | All four applications are stopped. Install exact candidate runtime fields and start only shadow; recognize a matching interrupted start. |
| `SHADOW_STARTED` | Wait for exact-image healthy shadow, then require its complete canonical proof to equal preflight. |
| `SHADOW_VERIFIED` | Retain the fresh successor proof; verify unchanged state and record application-start intent. |
| `START_REQUESTED` | Recheck successor proof freshness and unchanged state, then complete the exact candidate application start. |
| `APPLICATIONS_STARTED` | Verify four healthy exact-image applications, advancing leadership, unchanged holdings/history and a fresh green dashboard with the same saved plan. |
| `VERIFIED` | This operation completed at its recorded time; retain its receipt as a historical installation witness. |

A future current-generation `WAITING_OPEN` plan must have over fifteen minutes
until execution, completed matching publication and no active source job,
overlapping financial cycle or uncertain/working command. Installation does not
create another plan or extend its trading window.

Preflight and successor handoff proofs each have a fifteen-minute freshness
bound. A persisted stop/start intent does not extend it. Stale proofs refuse
resume; diagnose the current state and choose an explicitly reviewed recovery.
Never change clocks, relax deadlines, edit receipts, reset a consumed stage to
`NEW`, or fabricate a replacement readiness proof. A passed preflight is reused
within its original bound; resume does not silently run a new canonical pair.
If `NEW` fails before any pass is recorded, inspect the retained failure before
deciding on an explicit retry; that retry repeats the read-only preflight.

`status` reads the receipt only. An old `VERIFIED` result is not a fresh health,
trading or readiness check. Continuing an already completed operation does not
refresh its verification time. Check the current dashboard and operational
evidence separately when a current assessment is needed.

## Preserved boundaries and private evidence

The literal environment parser retains credentials privately; commands use a
sanitized ambient environment. No credentials belong in source, requests,
reports, shell history or public diagnostics. Expanded command failures stay in
the operation's private error log; inspect it without printing secrets.

Database comparisons run server-enforced read-only with bounded statements and
small per-row hashes. Canonical corpus contention alone has a typed finite retry
inside its original proof deadline. Broker observation uses PAPER GET requests
for the exact configured account and requires zero open orders.

Only shadow, automation, panel and alert dispatcher are rolled, shadow first.
PostgreSQL, its physical identity, canonical book, plans, controls, authority,
commands, UNKNOWN outcomes, fills and notification history remain preserved.
This command submits/cancels no orders and sends no synthetic notifications.
Backups, archives, maintenance, restore drills and backup verification remain
disabled. The backtest and all its files, outputs, processes and resources remain
untouched; do not reset/prune Docker or WSL to recover an installation.
