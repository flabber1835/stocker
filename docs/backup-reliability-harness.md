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

## Review repairs: clocks, media errors, metadata authority and restore horizon

Archive timestamps are compared to the database clock at full precision. Epoch
seconds used for age arithmetic are floored consistently. Manifest age uses a
host-clock sample taken after the manifest stat, so publication during a status
check does not look future-dated. Tests include subsecond archive success,
subsecond future evidence and publication across a second boundary.
The status age limit is decimal, including leading-zero inputs. Values longer
than 15 digits refuse configuration before arithmetic can overflow.

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
migrates only the metadata-read permissions of completed retained generations.
Routine validation remains read-only. The grant verifies regular, root-owned paths
and rejects symlinks and hard-linked metadata before changing permissions. A real
Docker composition gate runs the actual producer, connects the production Python
guard to PostgreSQL over a local Unix socket against the same media, checks
payload/write denial, injects media loss and verifies repair.

PR #344 review found that the full restore-horizon authority existed but was not
on every production feed/plan/order entrypoint. Canonical feed seed/daily recovery
and the public paper preparation/manual-execution/automated-execution gateways now
require it before their first mutation. The backup Compose overlay enables that
authority for supported manual CLI operation, while unattended services retain the
same required authority. Read-only broker recovery stays available during a backup
outage.

The paper package initializer remains declarative. The canonical preparation
and execution functions call the paper validation helper directly, preserving
their explicit signatures and identical public/submodule function ownership.
The helper translates runtime backup exceptions into the established paper
retryable/permanent refusals. The historical decomposition AST fingerprints
remain frozen: the architecture test checks the exact added gate statements and
recovery lock keyword, then proves the remaining lifecycle bodies still match.
The new helper is covered by refusal tests through both import paths.

The common corpus writer lock and execution/plan writer lock independently
recheck the complete restore horizon after acquiring exclusivity and before
yielding mutation authority. Direct internal imports therefore retain the gate.
Each broker SUBMIT or CANCEL also rechecks the horizon on its fresh authority
connection. A loss after plan preparation fences the next transport operation.
Only broker-observation recovery and the scheduler lease needed to reach that
recovery may request `writer_lock(..., recovery_only=True)`. That scope retains
serialization for observed history and coordination; it grants no plan or broker
mutation authority, and nested ordinary writer locks still recheck the horizon.
Emergency kill, disable and revocation keep their independent existing locks.
Temporary media loss retains the retryable backup/connection-error identity;
contradictory integrity evidence retains permanent backup refusal.

Runtime hashing reads only the required manifest-to-frontier WAL names. Older
retention and later concurrently archived segments are outside this proof's
scope. Every required segment is hashed again on each mutation check.
The same runtime authority also requires current archiver liveness through
`backup_guard`, including archive mode, timestamp validity and its active probe
for stale evidence. A complete retained chain cannot authorize new writes after
archiving is disabled. These checks retain the existing typed retry/refusal split.

Every newly archived WAL now carries an atomically published `.<none>`-free
companion named `<24-hex-WAL>.sha256`. The sidecar contains one lowercase SHA-256
of the immutable source WAL. Archive success is withheld until the WAL, sidecar,
and containing directory have been durably synchronized and revalidated. Runtime
authority recomputes SHA-256 from every WAL byte in the complete manifest-End-LSN
to `last_archived_wal` chain. A full-size post-publication bit flip therefore
fails integrity validation just like a missing or truncated segment.

Checksum authority is never synthesized for retained WAL. An upgrade may grant
PostgreSQL read access to old backup metadata, but it does not hash old WAL and
call those hashes historical evidence. After deploying the checksum-aware archive
command, create a fresh verified base backup. Its required WAL horizon was archived
under the new producer and therefore has provenance-bearing sidecars. A missing
sidecar remains a write fence until such a fresh recovery horizon exists.

Operator `sentinel-backup-status.sh` now proves that same complete chain before it
can print `backup_ready:true`. It requires `backup_label` as part of a complete base,
derives the first required WAL from the selected base manifest, walks every segment
to the current archive frontier, requires the retained recovery-marker WAL to fall
inside that sequence, verifies every segment's exact configured size, and hashes
every segment against its sidecar. The proof executes under the PostgreSQL OS
identity inside the private-media boundary.

## Required fault families

Missing/remounted media; invalid or symlinked attestation; permissions, ENOSPC,
short writes, EIO, failed fsync and rename; interruption before/after publication;
identical/conflicting retries and simultaneous writers; cluster identity and WAL
timeline changes; missing/truncated middle or marker WAL; same-size WAL corruption;
missing/malformed checksum evidence; malformed/duplicate metadata; stale/future
timestamps; delayed successful archive and unresolved newer failure; interrupted
base creation and exact backup selection; post-creation bit rot; semantic corruption;
repeated outage and eventual recovery.

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
- Production feed/plan/order mutations could proceed while the full retained WAL
  chain was broken. Their canonical production gateways now require the complete
  restore horizon before mutation.
- Full-size WAL corruption could pass runtime authority because size was treated
  as integrity. Archive publication now emits durable SHA-256 evidence and runtime
  authority recomputes every required segment before accepting the horizon.
- Status could report ready for a missing middle segment while its recovery-marker
  and latest WAL objects were intact. It now walks and hashes the complete selected
  base-to-frontier chain and requires `backup_label` during base selection.
- Restore copied a previously verified base and started recovery before checking
  current checksums. It now verifies the disposable copy before altering it.
- Coreutils no-clobber exit behavior could reject an identical concurrent writer.
  The archive script accepts that race only when the temporary survives and the
  competing final exactly matches the complete source.
- A disappearing directory during runtime scanning could escape as an untyped
  filesystem/database exception. It now remains a retryable, write-fencing media
  failure. Malformed evidence continues to refuse.
