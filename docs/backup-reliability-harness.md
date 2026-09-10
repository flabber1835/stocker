# Backup reliability harness

## Purpose and acceptance contract

Exercise the production backup implementation against deterministic media faults,
invalid retained evidence, process interruption, scheduling collisions and recovery.
Each repairable scenario must prove refusal during the fault and successful retry
after it clears. A successful command must preserve exact source bytes. A failed
attempt must preserve older recovery points. Simulation success is software
evidence; physical PostgreSQL replay and restored application semantics have
separate gates. NAS media durability and broker takeover remain operational gates.

Base reviewed: `df4683b8bf1c80453b8f542f4e3ed441387ad3f5`.

## Incident sources

Issue bodies and discussion logs reviewed on 2026-09-10:

| History | Failure to retain as a regression |
| --- | --- |
| #95, #145, #149 | Shared durability checks; emergency fencing remains reachable |
| #102, #112, #140 | Interrupted staging/metadata; concurrent writers; premature readiness |
| #104, #106 | WAL pruned after success; base corruption after creation |
| #105, #270 | Table presence does not prove restored application semantics |
| PR #154, #155, #306 | Private media, PostgreSQL/root authority split, marker initialization |
| PR #281, #300, #313 | Stale/uninitialized archival, outage recovery, fresh post-refresh proof |
| PR #316 | Recreated PostgreSQL clusters reuse WAL filenames |

Repository links use `https://github.com/flabber1835/stocker/issues/<number>`
and `https://github.com/flabber1835/stocker/pull/<number>` respectively.

## Design decided before implementation

1. Keep the harness under `tests/backup`. It imports production guards and invokes
   the actual archive shell entrypoint. Fault injection replaces operating-system
   commands only at the external process boundary. No production test-mode switch.
2. A strict database-observation adapter represents PostgreSQL reads of a temporary
   backup filesystem. Unknown SQL fails the test. It does not decide readiness;
   production code does. A controlled clock supports repeatable timing sequences.
3. Seeded multi-event campaigns retain their seed and failing event trace in
   pytest/JUnit output. They test repeated loss and restoration of media, markers,
   segments and frontier observations, with an independent expected-state oracle.
4. The physical gate uses an isolated PostgreSQL environment, real base backups,
   manifest verification, WAL replay and exact SQL contents. Every resource has a
   unique test name. Cleanup is scoped to resources created by the harness.
5. Reuse existing backup-root, GO-refresh, lock, emergency-fence and semantic
   restore regressions in the dedicated command. Keep each layer's evidence
   explicit. Never report simulated I/O as physical recovery proof.
6. Fix defects reproduced by the harness on this PR. Preserve the documented
   PostgreSQL/root media ownership model, immutable archived objects, production
   strategy economics and broker authorization boundaries.

## Review repairs: clocks, media errors and metadata authority

Archive timestamps are compared to the database clock at full precision. Epoch
seconds used for age arithmetic are floored consistently. Manifest age uses a
host-clock sample taken after the manifest stat, so publication during a status
check does not look future-dated. Tests include subsecond archive success,
subsecond future evidence and publication across a second boundary.

Filesystem SQLSTATEs `58P01`, `42501` and `58030`, and OS I/O errors, retain
`BackupRuntimeUnavailable` through every metadata read, including manifest JSON
parsing. Malformed JSON and contradictory metadata retain integrity refusal.
Faults at every SQL read must fence writes and heal after the fault clears.

Issue #345 requires a narrow metadata-read grant. Container root remains the
base-backup writer. The base parent is root-owned, group `postgres`, mode 0750;
completed base directories are root-owned, group `postgres`, mode 0710. Exactly
`backup_manifest`, `backup_label`, `sentinel-recovery-marker` and
`sentinel-pitr-base-identity` receive mode 0640 and group `postgres`. Payload
permissions and ownership are preserved. PostgreSQL can enumerate generations
and read these four files; it cannot list or read payload directories, write
metadata, create generations or delete backups. The host account retains no
access through other-user permissions.
Bind mounts identify groups numerically. A host account sharing PostgreSQL's
numeric group receives the same metadata read grant. Payload read denial and
base/metadata write denial still apply. The physical gate records both identities
and separately checks an unrelated UID/GID.

The production producer grants this access after verification and metadata
publication, before atomic generation promotion. Explicit backup initialization
also migrates completed retained generations. Routine validation remains read-only.
The grant verifies regular, root-owned paths and rejects symlinks and hard-linked
metadata before changing permissions. A real Docker composition gate runs the
actual producer, connects the production Python guard to PostgreSQL over a local
Unix socket against the same media, checks payload/write denial, injects media
loss and verifies repair.

## Required fault families

Missing/remounted media; invalid or symlinked attestation; permissions, ENOSPC,
short writes, EIO, failed fsync and rename; interruption before/after publication;
identical/conflicting retries and simultaneous writers; cluster identity and WAL
timeline changes; missing/truncated middle or marker WAL; malformed/duplicate
metadata; stale/future timestamps; delayed successful archive and unresolved newer
failure; interrupted base creation and exact backup selection; post-creation bit
rot; semantic corruption; repeated outage and eventual recovery.

The output records failures separately from prerequisites that could not run.
The harness must never silently skip a required physical gate in CI.

## Commands and evidence

`python -m pytest tests/backup -q -ra --junitxml=backup.xml` runs the deterministic
media, process, lifecycle and clock scenarios. Three fixed seeds each advance
120 events; failed assertions retain their seed and event trace. Shell lifecycle
tests execute copied production scripts with a strict command adapter, actual
temporary filesystem operations and the real kernel lock. Their PostgreSQL
observations and checksum oracle are explicitly simulated.

`bash scripts/test-backup-physical.sh` runs PostgreSQL 16.14 from the repository's
pinned image in one disposable network-isolated container. It creates a physical
base with streamed WAL, archives post-base transactions through the production
archive script, detects post-creation relation corruption, refuses a missing
middle segment and a truncated marker segment, restores after repair, and compares
every probe row and decimal amount to the original database.
It first runs the retained NAS permission regression: the host account cannot
write either private backup directory, while the correct PostgreSQL/root
container authorities can initialize and verify their markers.

The `Backup reliability` workflow runs both commands and retains JUnit and physical
logs. The existing `Sentinel safety` workflow retains the wider backup-root,
private-authority, GO refresh, emergency-fence, lock and semantic-restore tests.
The physical probe table does not certify a populated trading account's semantic
restore or broker takeover. Those remain the deployment runbook's separate gates.

## Defects exposed and fixed

- Runtime restore-horizon scans and active WAL probes still used the flat archive
  path after PR #316 introduced cluster namespaces. Both now bind to the current
  PostgreSQL system identity; old-cluster base evidence cannot authorize writes.
- The runtime accepted incomplete recovery metadata. Exact required fields and
  unique identities now precede the contiguous WAL proof.
- A backwards clock jump could turn future archive evidence into age zero. It
  now refuses. Status also rejects future manifest mtimes and checks age in seconds.
- Status could report ready for partial markers and truncated required WAL. It
  now validates the marker and full-size regular marker/latest WAL objects.
- Restore copied a previously verified base and started recovery before checking
  current checksums. It now verifies the disposable copy before altering it.
- Coreutils no-clobber exit behavior could reject an identical concurrent writer.
  The archive script accepts that race only when the temporary survives and the
  competing final exactly matches the complete source.
- A disappearing directory during runtime scanning could escape as an untyped
  filesystem/database exception. It now remains a retryable, write-fencing media
  failure. Malformed evidence continues to refuse.
