# Recurring proactive backup maintenance: Step 1 evidence

No NAS or real broker account was accessed. No economic golden artifact,
capability flag, strategy choice or certification state was changed.

Initial verified main: `84582af2020a708ab076821693ffa4ea93ebed1c`.
This work incorporates the bounded selection (#410) and exhausted-horizon
renewal (#412) implementations. The owner merged #410 during the work;
independently fetched main became `ec8351ff2f535885d5a1cefcbca9b9bb83498b5c`.
The PR records the final reviewed commit. `source-provenance.json` binds the
reviewed source bytes; `SHA256SUMS.json` binds the retained package. Original
audit/evidence packages remain unchanged.
The integration commit is `cdfdae6dc904317eeb9ce640ce2b548c4bd3214e`; its tree
is byte-identical to the validated implementation commit `a658cc8d` after
resolving two fixture-helper-list conflicts. No production source changed on
integration. The canonical `Dockerfile.sentinel` built successfully with that
revision label, yielding immutable local image
`sha256:f860878ad1da60718a43ff7895e664fffc4df3ef74463fee5f0ad94194c73ba3`.
The private-media driver also passed against this baked image without a source
mount or PYTHONPATH override. An initial `--network=none` build missed the pip
cache and failed to resolve dependencies; the ordinary hash-locked build reused
its pinned dependency layer and succeeded. Both build logs are retained.

## What is established locally

- A scheduler-callable tick and optional single-owner loop invoke the existing
  producer, exact-path status verifier and full semantic restore drill. Renewal
  uses current primary WAL, before archival, at 256 MiB or 12 hours. A changed
  timeline renews; regressed clocks/positions refuse.
- Full restore evidence binds cluster, base, marker, target LSN, all four
  metadata byte identities and immutable runtime image. Empty, physical-only,
  wrong-image or wrong-generation evidence cannot authorize pruning. Restart
  reuses only matching durable evidence; missing evidence repeats the drill.
- An independent 72-generation calendar fixture retains exactly ten expected
  bases: seven daily representatives, four weekly representatives (overlapping),
  and recent/newest/selected protection. Its independently expected earliest
  segment is 131: segment 130 is deleted; 131 and later, history, other timelines
  and unknown names remain. Every manifest Start-LSN contributes. Mixed timelines
  retain all WAL.
- Partial deletion resumes from a durable journal after revalidating protected
  identities and its clock. A surviving worker retains its media flock after
  parent death. Private PostgreSQL-owned 0700 WAL namespaces work through the
  actual offline Docker worker without changing ownership or permissions.
- Pinned PostgreSQL 16 physically replays a post-base marker, pauses at its
  target, retains the shared media lock inside the actual PostgreSQL process,
  promotes explicitly and releases ownership on shutdown. Actual
  `pg_verifybackup` rejects changed relation bytes.
- The canonical semantic validator and actual production receipt SELECT/INSERT
  run against an isolated real PostgreSQL bootstrap database. This fixture has
  **no account, commands or economic book**; it does not establish populated
  restore semantics or economic performance.

## Commands and results

From the repository root, with the cached `sentinel-test:ci` image:

```text
python audit/economic_399/recurring_maintenance/run_local.py focused
python audit/economic_399/recurring_maintenance/run_local.py regression
python audit/economic_399/recurring_maintenance/run_local.py final
python audit/economic_399/recurring_maintenance/run_local.py semantic
python audit/economic_399/recurring_maintenance/run_local.py mutations
python audit/economic_399/recurring_maintenance/private_media.py
python audit/economic_399/recurring_maintenance/private_media.py --runtime-image sha256:f860878ad1da60718a43ff7895e664fffc4df3ef74463fee5f0ad94194c73ba3
python audit/economic_399/recurring_maintenance/physical_worker.py
python audit/economic_399/recurring_maintenance/physical_worker.py --mutate-target
```

The runner copies source into a disposable Linux filesystem, excludes `.env`
and Git state, has no network and no Docker socket. The physical/private-media
drivers create only local disposable Docker resources. The PG16 positive worker
gate is also connected to `.github/workflows/backup-reliability.yml`.

Results (overlap is intentional; do not add them as coverage):

| Campaign | Result |
|---|---|
| Initial focused backup/maintenance | 91 passed, 236.80 s |
| Backup/GO/ownership regression | 361 passed, 252.58 s |
| Final maintenance, restore contract and environment | 930 passed, 42.11 s |
| Real PostgreSQL bootstrap semantics and receipt query | 1 passed, 3.79 s |
| Actual Python 3.8.15 environment suite | 873 passed, 43.929 s |
| Code falsifiers | All 15 detected |
| Actual PG16 target-removal falsifier | Detected: automatic archive-end promotion fails the pause assertion |
| Actual private-media worker | Permission-negative control refused before deleting any bases; reviewed capability removed 62 obsolete bases and one obsolete WAL object, preserving the exact floor and modes |

The final driver adds the subsequently introduced semantic case to its selector
(931 cases); the retained 930-case run plus the separate passing semantic run
cover that source. A retained failed integration run had one real same-timestamp
environment rewrite admission and three incomplete environment adapter handoffs.
The loader now compares two bounded byte observations; the adapter now follows
the lock helper's child handoff. No xfail, skip or golden repinning was added.
An initial physical-worker attempt failed its recovery-state check; diagnostic
and target-pause runs are retained along with the deterministic removal falsifier.
The first disposable-run command also exposed a stale image source-root setting;
the final runner explicitly binds the disposable checkout. These failures are
not counted as passing evidence.

Python 3.8.15 command (cached image, no network):

```bash
docker run --rm --network none --entrypoint python \
  -v "$PWD:/source:ro" -w /source -e PYTHONDONTWRITEBYTECODE=1 \
  python:3.8.15-slim -m unittest discover -s tests/host_python38 \
  -p test_env_ingestion.py -q
```

`static.log` records Python parsing and pyflakes; `shell-static.log` records
individual `bash -n` checks, and `ownership.json` records test responsibility.
No unrelated Wealth Core suite was run.

Relevant entry points and guards (line references refer to the reviewed source):
`scripts/sentinel_backup_maintenance.py:102` owns renewal; `:134` receipt binding;
`:194` the connected tick and exact successor check; `:241` supervisor ownership.
`sentinel/backup_retention.py:197` owns protected sets, `:229` journal recovery,
`:266` WAL floors and `:303` the gated deletion entry point.
`scripts/sentinel-restore-worker.sh:7` owns the shared media lock and `:16` the
target pause; `scripts/sentinel-restore-drill.sh:190` requires the paused proof.
`scripts/sentinel_env.py:131` owns stable configuration reads.
The certification ledger records severity and disposition; source hashes allow
these claims to be checked independently of changing PR line numbers.

## Concrete NAS handoff — not performed

1. Merge reviewed prerequisites and this PR through the normal owner process.
   Deploy/build the immutable Sentinel image for the **exact clean checkout**.
   Preserve `git rev-parse HEAD`, the image digest and image revision label. The
   maintenance caller refuses stale image/source identity. Preserve existing
   backup media and failed-attempt artifacts; do not synthesize selection or
   restore receipts. Establish a fresh verified base through the updated producer
   before scheduling a first tick if selection is absent.
2. Verify the independent durable target is mounted, marker checks pass, and it
   has room for retained daily/weekly bases, required WAL, one new base and one
   disposable restore. Confirm this is the **same NAS host and host account**
   used for manual backup/restore/GO. Cross-host or cross-account coordination is
   not qualified by the per-account host lock.
3. As that account, from the reviewed checkout, run:

   ```bash
   git rev-parse HEAD
   git status --short
   bash scripts/sentinel-base-backup.sh
   # Use the exact verified_base_backup path emitted above:
   bash scripts/sentinel-backup-status.sh --backup /ABSOLUTE/BACKUP/base/base-YYYYMMDDTHHMMSSZ
   bash scripts/sentinel-restore-drill.sh --backup /ABSOLUTE/BACKUP/base/base-YYYYMMDDTHHMMSSZ
   bash scripts/sentinel-backup-maintenance.sh
   ```

   Require the full `restore_semantics_ready:true` result and a primary
   `sentinel_backup_evidence` RESTORE_DRILL row with matching metadata digest and
   runtime image. Require `maintenance_ready:true` and `retention_ready:true`
   from the tick. A physical-only result, empty response, missing row or nonzero
   exit is a failure. Retain stdout/stderr, timestamps, exact paths and receipts.
4. Install a DSM user-defined scheduled task, under that same account, invoking
   the absolute path to `sentinel-backup-maintenance.sh` at least once a minute.
   Configure retained output and failure notification. If DSM cannot provide
   that cadence, supervise `sentinel-backup-maintenance.sh --loop` using a boot
   task plus periodic restart task; its separate flock prevents duplicate loops.
   The loop requires separate log/failure monitoring. Merely observing a running
   process is not a passing health check. Retain the scheduler configuration and
   test an intentional failure notification to the approved operator destination.
5. On **disposable qualification media and restored database copies**, interrupt
   a producer, restore and deletion after publication/quarantine. Verify active
   worker exclusion, marker pause, receipt revalidation, journal resumption and
   eventual disposal of expired unused restore artifacts. Reboot the NAS; verify
   scheduling resumes, missing mounts refuse, and no task uses the wrong UID.
   Do not simulate media loss or corruption on the sole production backup.
6. Measure full-size backup, restore and retention durations, free space, memory
   and WAL production under the expected workload. Demonstrate successor
   selection before the 1 GiB runtime ceiling and seven distinct daily/four
   distinct weekly recovery representatives over real elapsed history. A burst
   that outpaces the 256 MiB headroom trigger must fence runtime mutation; do not
   increase limits or silently skip verification to claim success.
7. Run the full semantic drill on a populated retained economic book and retain
   independent cash/NAV/share/action/command comparisons before and after restore.
   Local empty-bootstrap acceptance cannot substitute for those deployed inputs.

Until these pass, deployed maintenance qualification remains open. C1/F6 cash
completeness/finality, F19 native fill authority, C3 predecessor-incarnation
proof, full-universe/resource gates and authoritative historical economic-delta
work retain their prior unresolved dispositions. Economic certification is not
complete, and no 20-year return multiple is claimed here.
