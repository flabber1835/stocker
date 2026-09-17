# Rolling history and retention validation

2026-09-17, base `ae5d983d6eac5287585635319eb29023faa3e76c` (merged PR #397).
Authoritative `origin/main` was fetched again before delivery and still matched.

Tests ran in disposable source copies inside the existing `sentinel-test:ci`
image (`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`),
with `--network none` and the host checkout mounted read-only. Python used
`PYTHONPATH=<copy>:<copy>/shared` and `SENTINEL_REPO_ROOT=<copy>`.
PostgreSQL fixtures created their own local server/databases inside the container.
No NAS, deployment database, provider or broker was contacted. The exact inner
Python commands and results follow; the container wrapper extracted a base Git
archive and the working-tree overlay before invoking them.

## Final affected regression run

```sh
python -m pytest tests/sentinel/test_rolling_snapshot_storage.py tests/sentinel/test_rolling_go_inputs.py tests/sentinel/test_rolling_history_retention.py tests/sentinel/test_rolling_retention_runtime.py tests/sentinel/test_shadow_service.py -q --tb=short --show-capture=no --disable-warnings --maxfail=3
```

**116 passed in 96.64s.** Includes old original-unit commands, two scalar actions
across successive windows, no-action aging, BIL predecessor evidence, immutable
original evidence, scoped correction/restoration, historical dividend inputs,
publication rollback/lost acknowledgement, coverage gaps, real price deletion,
active workers/read-only readers, backup refusal, interrupted cleanup, exact-hash
rehydration, scan progress, repeated migration, idle draining, checkpoint handoff,
and PostgreSQL dump/restore followed by authenticated runtime status.

The restore test uses `pg_dump -Fc` and `pg_restore --exit-on-error` into another
disposable database. It is a database closure/restart test, not a NAS physical
base/WAL restore drill or backup certification.

## Surrounding regressions and corrected failures

```sh
python -m pytest tests/sentinel/test_rolling_history_retention.py tests/sentinel/test_rolling_retention_runtime.py tests/sentinel/test_rolling_snapshot_storage.py tests/sentinel/test_rolling_snapshot_jobs.py tests/sentinel/test_rolling_snapshot_publisher.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_automatic_share_units.py tests/sentinel/test_informational_paper_mirror.py tests/sentinel/test_action_source_identity.py tests/sentinel/test_journal_and_reconcile.py tests/sentinel/test_issue_165_feed_schema_postgres.py tests/sentinel/test_schema_migrations.py -q --tb=short --show-capture=no --disable-warnings --maxfail=5
```

**347 passed, 2 failed in 550.52s** before the scan-wrap fix. Both failures exposed
an incomplete cursor wrap retaining extra old generations. The implementation
was fixed; both regressions pass in the final 116-test run above. The surrounding
job/publication/runtime/daily/initialization, automatic share-unit, informational
mirror, legacy journal/reconciliation and schema regressions passed.

```sh
python -m pytest tests/sentinel/test_operational_snapshot.py tests/sentinel/test_rolling_history_retention.py tests/sentinel/test_rolling_retention_runtime.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_rolling_reader.py tests/sentinel/test_rolling_inputs.py tests/sentinel/test_rolling_go_inputs.py -q --tb=short --show-capture=no --disable-warnings --maxfail=3
```

**132 passed, 1 failed in 177.82s.** The old missing-pin test disabled only the
outer publication pin; the new explicit-generation transaction pin still
correctly excluded writers. The falsifier now removes both ownership paths to
measure an actually missing pin. It passes in the final run; the generation-pin
regression independently proves writer exclusion and transaction-end release.

The original storage fixture also installed only the old storage DDL. It now
installs the full feed DDL; explicit migration/catalog validation has its own
tests. This allows behavioral trigger-removal falsifiers to reach their actual
assertions instead of failing during fixture setup. No economic fixtures changed.

## Guard removal

```sh
python -m tools.sentinel_rolling_history_falsifiers
python -m tools.sentinel_rolling_storage_falsifiers
```

**13/13 new mutants killed; 7/7 existing storage mutants killed.** Every kill
requires an actual pytest test failure, not collection/setup failure. Each child
changes only its own module namespace in a disposable container copy.

New falsifiers remove/break idle-drain integration, coverage-gap refusal, writer
ownership, historical correction detection, missing-event evidence detection,
exactly-once scalar use, initial coverage, current-generation pins, active-job
pins, read-only generation pins, rehydration identity, incremental scan progress,
and automatic publication cleanup. Existing falsifiers cover calendar gaps,
independent identity, sealed/presealed insertion, benchmark gaps, TRUNCATE
protection and restored-payload integrity.

## Syntax and static checks

All changed/new Python files passed `py_compile.compile(path, doraise=True)`.
`git diff --check` passed. With pyflakes 3.4.0 in the local disposable Python 3.12
environment, this PowerShell command passed:

```powershell
$rollingFiles = @(git diff --name-only -- '*.py') + @(git ls-files --others --exclude-standard sentinel tests tools | Where-Object { $_ -like '*.py' })
$rollingChecked = $rollingFiles | Where-Object { $_ -notin @('sentinel/core/decision.py','tests/sentinel/test_rolling_go_inputs.py') }
& .codex-tmp/bounded-feed-venv/Scripts/python.exe -m pyflakes $rollingChecked
```

An unrestricted check of all changed files reports existing warnings in those
two exclusions: the duplicate `REFERENCE_SOURCE_SHA256` import and pytest fixture
imports/shadowing. The base revision has the same warnings; both files were
syntax-checked and their relevant regressions ran. No `make test` or
`tests/wealth_core` suite was run.

## Deployment scope

Merge/review, image and feed-schema rollout, failed-attempt inventory, NAS
backup/physical restore qualification, first GO and observed paper operation
remain deployment work. Historical correction restrictions remain scoped and
clear when original accepted evidence is restored; accepted transformations are
never silently rewritten. Sparse audit evidence grows with history, while bulk
snapshots retire as references clear. Pre-archive/unowned data is retained
conservatively. These local tests establish no NAS GO or real paper fill.
