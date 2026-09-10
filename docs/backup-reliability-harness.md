# Backup reliability harness

## Purpose and acceptance contract

Exercise the production backup implementation against deterministic media faults,
invalid retained evidence, process interruption, scheduling collisions, timeline
changes and recovery. Each repairable scenario must prove refusal during the fault
and successful retry after repair. A successful archive command must preserve exact
source bytes and durable integrity evidence. A failed attempt must preserve older
recovery points. Simulation success is software evidence; physical PostgreSQL replay,
timeline promotion, restored application semantics, NAS durability and broker takeover
retain separate gates.

Base reviewed: `df4683b8bf1c80453b8f542f4e3ed441387ad3f5`.

## Incident sources

Issue bodies and discussion logs reviewed on 2026-09-10:

| History | Failure retained as a regression |
| --- | --- |
| #95, #145, #149 | Shared durability checks; emergency fencing remains reachable |
| #102, #112, #140 | Interrupted staging/metadata; concurrent writers; premature readiness |
| #104, #106 | WAL pruned after success; base corruption after creation |
| #105, #270 | Table presence does not prove restored application semantics |
| PR #154, #155, #306 | Private media, PostgreSQL/root authority split, marker initialization |
| PR #281, #300, #313 | Stale/uninitialized archival, outage recovery, fresh post-refresh proof |
| PR #316 | Recreated PostgreSQL clusters reuse WAL filenames |

## Design

1. The deterministic harness lives under `tests/backup`. It imports production
   guards and invokes the production archive and backup scripts. Fault injection
   replaces operating-system commands only at external process boundaries.
2. A strict database adapter represents PostgreSQL observations of temporary backup
   media. Unknown SQL fails the test. Production code owns all readiness decisions.
3. Fixed-seed campaigns retain their seed and event trace. They repeatedly lose and
   restore media, markers, archive objects and frontier observations against an
   independent expected-state oracle.
4. Physical gates use isolated PostgreSQL 16.14 instances, real base backups,
   manifests, archive commands and WAL recovery. Resources are uniquely named and
   cleanup is restricted to resources created by the harness.
5. Existing backup-root, GO-refresh, lock, emergency-fence and semantic-restore
   regressions remain part of the complete Sentinel safety suite.
6. The harness fixes reproduced defects while preserving PostgreSQL/root ownership,
   immutable archive publication, strategy economics and broker authority boundaries.

## Private-media authority

Container root remains the physical-base writer. The base parent is root-owned,
group `postgres`, mode 0750; completed base directories are root-owned, group
`postgres`, mode 0710. Exactly `backup_manifest`, `backup_label`,
`sentinel-recovery-marker` and `sentinel-pitr-base-identity` receive mode 0640 and
group `postgres`. Payload permissions remain private.

PostgreSQL may enumerate base generations and read those four metadata files. It
cannot list or read base payload directories, write metadata, create generations or
delete backups. Explicit backup initialization migrates only this metadata-read
grant. The grant validates root ownership, regular path identity and single-link
metadata before changing permissions. Symlink, hardlink and ownership drift are
falsified in the real Docker composition gate.

The durable-target markers remain cold-boot mount fences. Routine validation never
recreates a missing marker. Filesystem SQLSTATEs `58P01`, `42501` and `58030`, plus
OS I/O errors, retain `BackupRuntimeUnavailable`; malformed or contradictory
integrity evidence retains permanent `BackupRuntimeRefused`.

## Production mutation authority

Canonical feed seed/daily recovery and paper preparation/manual execution/automated
execution require a valid runtime restore horizon before their first mutation. The
common corpus writer lock and plan/execution writer lock independently repeat that
proof after acquiring exclusivity and before yielding mutation authority. Direct
internal imports therefore retain the same gate.

Every broker `SUBMIT` and `CANCEL` also rechecks backup authority through its fresh
PostgreSQL authority connection. Media loss after plan preparation therefore fences
the next transport operation. Read-only broker observation/recovery and the scheduler
lease needed to reach it use the explicit `writer_lock(..., recovery_only=True)`
scope. Nested ordinary writer locks still require full mutation authority. Emergency
kill, disable and revocation retain their independent existing paths.

Runtime authority also requires current archiver health through `backup_guard`.
Disabled archiving, future-dated evidence, unresolved failures and failed active
liveness probes cannot be masked by an intact retained chain.

## Archive identity and integrity

Each PostgreSQL cluster owns `wal/cluster-<system_identifier>`. A normal 24-hex WAL
segment carries the system identifier in its long page header and the archive command
uses that value as its namespace authority. PostgreSQL timeline-history and backup-
history files are text metadata and have no WAL long-page header. For those objects,
the archive command reads `pg_control` from the server data directory identified by
PostgreSQL's `%p`/working-directory contract. A normal WAL segment is cross-checked
against the same control identity when available.

Supported archive objects are:

- `<24-hex-WAL>`
- `<8-hex-timeline>.history`
- `<24-hex-WAL>.<8-hex-offset>.backup`

Every supported object is atomically published together with a companion
`<archive-object>.sha256`. Publication succeeds only after source stability, exact
copy comparison, object fsync, sidecar fsync, directory fsync and final revalidation.
Identical concurrent writers converge; conflicting writers preserve the winning
immutable object and fail closed.

Retained pre-upgrade WAL is never retroactively granted checksum authority. After
installing the checksum-aware archive command, create a fresh verified base so its
required restore horizon consists of provenance-bearing archive objects.

## Bounded runtime integrity proof

The runtime proves only the archive objects required by the selected base-to-frontier
restore horizon. Older retained generations and later concurrently arriving objects
are outside that decision.

A complete SHA-256 byte scrub occurs on first use and at least every 300 seconds.
Between complete scrubs, each mutation check re-reads every required object's size,
mtime, ctime, sidecar contents and sidecar timestamps, and re-hashes every new or
metadata-changed object. The cache is scoped to the PostgreSQL target, system
identifier, selected base, restore start and WAL geometry. A recreated database,
new base, changed frontier object, changed metadata or expired scrub interval cannot
inherit an unrelated proof.

The runtime additionally executes a filesystem-identity probe under PostgreSQL's OS
identity on every check. Required base/WAL directories must not be symlinks; durable-
target markers, selected base metadata, required WAL/history objects and sidecars
must be non-symlink single-link files. Runtime and operator status therefore share
the same alias/hardlink acceptance contract.

Synchronous mutation-path proof is bounded to 1,024 required archive objects and
1 GiB of archive bytes. Exceeding either bound is a permanent fail-closed condition
with an instruction to create a fresh base backup. This caps restart/full-scrub cost
and prevents an arbitrarily old base from turning a broker mutation into an
unbounded historical scan.

## Timeline recovery

A recovered PostgreSQL cluster promoted after archive recovery creates a new timeline.
Its `<timeline>.history` file is recovery-critical and passes through the same
`archive_command` as WAL. The archive command now publishes that history file into
the current system-id namespace with the same atomic SHA-256 contract.

A base whose manifest names timeline 2 or later is accepted only when the matching
`<timeline>.history` object and checksum are present and valid. Runtime authority,
operator status and the standalone Python chain verifier enforce the same rule.

`tests/backup/test_pr344_final_seams.py` falsifies history loss, repair, aliasing,
bounded proof cost, incremental revalidation and forced periodic full scrubs.
`scripts/test-backup-timeline-promotion.sh` performs the real PostgreSQL sequence:
base on timeline 1 -> archive recovery -> promotion -> timeline-history archival ->
timeline-2 WAL archival -> fresh verified timeline-2 base.

## Operator status and restore

`sentinel-backup-status.sh` can print `backup_ready:true` only after it selects a
complete current-cluster base, checks age/archiver state, derives the first required
WAL from the base manifest, walks every segment through `last_archived_wal`, requires
the recovery-marker WAL inside the interval, verifies exact WAL size, validates all
sidecars, checks hardlink/symlink identity and, on timeline 2+, verifies the required
timeline-history object.

The restore drill copies the selected base into a disposable volume and runs
`pg_verifybackup` before changing the copy or beginning recovery. It replays through
the exact post-base marker, validates canonical Sentinel tables, promotes the
isolated database and runs semantic validation using the digest-qualified Sentinel
runtime image. Base-payload bit rot is therefore detected before restore execution.

`backup_ready:true` is a chain/readiness checkpoint; full base-payload manifest
verification remains a restore-drill checkpoint.

## Required fault families

Missing/remounted media; invalid or aliased attestation; permissions; ENOSPC; short
writes; EIO; failed fsync/rename; interruption around publication; simultaneous
identical/conflicting writers; source mutation during copy; PostgreSQL cluster
identity changes; timeline promotion/history loss; missing/truncated middle or marker
WAL; same-size corruption; missing/malformed checksum evidence; metadata aliases and
hardlinks; malformed/duplicate metadata; stale/future timestamps; delayed archive
success; unresolved archive failure; interrupted base creation; exact base selection;
post-creation base bit rot; semantic corruption; repeated outage and eventual repair.

Required physical gates must fail when prerequisites cannot run; they may not silently
skip.

## Commands and CI evidence

`python -m pytest tests/backup -q -ra --junitxml=backup.xml` runs deterministic media,
process, lifecycle, alias, integrity-cache and clock scenarios. Fixed seeds each
advance 120 events and preserve the failing event trace.

`bash scripts/test-backup-physical.sh` creates a real physical base, archives
post-base transactions through the production archive command, detects post-creation
base corruption, refuses missing/truncated WAL, repairs the media, restores and
compares exact SQL contents.

`bash scripts/test-backup-timeline-promotion.sh` exercises real archive recovery and
promotion to a new PostgreSQL timeline with archiving enabled and requires durable
history-file publication before accepting a fresh base on the new timeline.

`bash scripts/test-backup-runtime-media.sh` runs the real production base producer and
runtime SQL guard against the same private bind-mounted media, checks payload/write
permissions, middle-chain loss, same-size corruption, status parity, media loss and
repair.

The `Backup reliability` workflow executes all of these gates on both the exact PR
head and GitHub's synthetic merge tree. `Sentinel safety` supplies the wider runtime,
recovery, authority, operator-script, Python-3.8 host and mutation-test coverage.

## Defects exposed and fixed

- Flat archive scans after cluster namespaces were introduced: runtime and active
  probes now bind to the current PostgreSQL system identifier.
- Incomplete recovery metadata: exact required fields and identities precede the
  contiguous chain proof.
- Backwards clock jumps: future archive evidence is refused.
- Missing mutation wiring: canonical feed/plan/order gateways and common writer locks
  now require complete runtime backup authority.
- Full-size WAL corruption: archive objects carry SHA-256 evidence and runtime
  periodically re-scrubs bytes while revalidating metadata on every mutation gate.
- Unbounded broker-path hashing: proof reuse is metadata-bound and time-bounded, with
  hard byte/object ceilings and forced full-scrub renewal.
- Runtime/operator alias mismatch: both now refuse symlinks and hardlinks for required
  recovery objects.
- Missing middle WAL in status: status walks the complete selected base-to-frontier
  chain.
- Recovery promotion seam: timeline-history files are archived, checksummed and
  required for timeline-2+ restore authority.
- Restore after base bit rot: the disposable base copy is manifest-verified before
  recovery begins.
- Concurrent no-clobber differences: an identical writer is accepted only after the
  competing final is proven byte-identical and durable.
- Filesystem disappearance during runtime reads: media errors retain retryable,
  write-fencing identity.