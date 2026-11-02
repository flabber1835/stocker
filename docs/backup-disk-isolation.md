# Backup disk isolation

Owner decision: 2026-11-01. Surprise removal of the backup USB must not stop
Docker, PostgreSQL, the trading services, or read-only broker recovery. The
physical removal test preserved the Ubuntu boot and Windows supervisor but
stopped Docker through its `RequiresMountsFor` dependency. That is a separate,
confirmed availability defect; it does not identify the morning supervisor exit.

## Runtime and storage ownership

Primary PostgreSQL data and its unarchived WAL remain on the existing internal
volume. The independent USB remains the external backup target. Remove only
the external-media requirement from Docker startup; retain primary-storage
identity checks. USB arrival starts the backup mount transport, never Docker.
One native mount transport exposes the external base/WAL submounts beneath an
always-present internal parent. PostgreSQL receives that parent with one-way
recursive mount propagation. Its empty underlying directories contain no
independent-target markers and must never become archive destinations. Loss and
return of the exact USB UUID withdraw and restore those submounts without a
database or Engine restart. Do not initialize fallback markers.

PostgreSQL health means database availability. External backup health is a
separate status and financial policy. Keep the existing archive command's
atomic copy, byte comparison, fsync, immutable name, cluster namespace and
checksum checks. A missing target returns failure: PostgreSQL retains the
unarchived segment internally and retries. Never acknowledge a local buffer as
an independent external archive.

## Explicit bounded PAPER continuity

The existing `REQUIRED_V1` policy remains strict by default. The separate opt-in
`SENTINEL_BACKUP_OUTAGE_POLICY=BOUNDED_30H_V1` applies only to the exact bound
owner-authorized PAPER account with `REQUIRED_V1` backups. Unknown selections
refuse; LIVE and ordinary certified authority do not acquire this exception.

After a successful complete external restore-chain proof, the runtime may
retain a domain-separated HMAC-authenticated checkpoint in the primary data
directory. It binds the actual account/deployment/takeover epoch, current
runtime commit/image, physical PostgreSQL system, postmaster incarnation,
archive frontier and actual last successful archive time. Store and read it
through the PostgreSQL OS identity, atomically, with bounded bytes; it is not
an observability row repurposed as authority. Repeated reads and degraded
operations cannot refresh it. A restart or changed identity requires a fresh
healthy external proof.

When, and only when, the external mounts are genuinely absent, ordinary PAPER
mutations may use that previously verified checkpoint for at most 30 hours
since its last successful archive. An unresolved failure while media remains
mounted, corrupt bytes, contradictory metadata, missing prior proof, changed
identity, clock regression or an expired checkpoint still refuses. Heavy
seeding, restore, installation and activation continue to require current
external proof. The returned evidence explicitly says `DEGRADED`; it is never
recorded as a newly successful `RUNTIME_CHAIN` proof.

Continuity additionally requires a fresh authenticated capacity observation
from the existing native backup maintenance owner, independently of USB
availability. Measure both Linux primary-filesystem capacity and the physical
Windows disk backing the WSL VHD, using the existing native capacity reader.
Keep at least the existing 10 GiB reserve on both and bound retained primary
WAL. Missing, stale, foreign, future or malformed capacity evidence refuses
continued writes. No sparse-VHD virtual-free figure substitutes for Windows
physical free space. Publish capacity before media-dependent maintenance work;
do not create another recurring loop. Existing maintenance deadlines remain.
Failure to refresh capacity withdraws continuity permission; it must not stop
otherwise healthy external backups. Maintenance reports continuity readiness
separately from successful external backup/retention work. Missing or stale
capacity never produces a new checkpoint, while authenticated-record tampering
remains an integrity refusal.

The existing supervisor's flock namespace is the canonical configured backup
path, even while that directory is absent. That is lock naming, not media
admission: every physical backup child still validates the real mounted target.
Ordinary Compose availability commands may validate the root-owned transport
configuration and active parent service instead of requiring USB presence.
Financial readers and writers still check their own actual PostgreSQL-visible
media and the explicitly selected policy. Heavy feed publication and new
installation/admission remain strict; continuity never invents a future plan.

## Delivery and qualification

Implement through a feature PR from authoritative main, with targeted tests and
executed guard-removal controls. Prove actual private mount loss/reappearance,
stable Engine/database/role identities, ordinary database writes, bounded PAPER
admission, archive retry and truthful degraded status. Include absent/wrong
media, stale mount, missing/tampered/foreign/expired checkpoint, unsafe/stale
capacity, clock and reconnect-race refusals. Preserve source/book/account,
command/UNKNOWN history, original PG volume/system identity, independent
backup bytes and immutable historical receipts. Do not repeat the physical
surprise-removal test while preparing this fix or restart WSL/Docker.

Only reviewed, qualified source and exact signed publication may reach the
running application. Installation may perform its normal scoped transition;
USB reconnection itself must not require a database/Engine restart. Keep the
supervisor diagnostic and the separate dashboard-history work unchanged.

Host cutover order is explicit. After exact-head CI, reviewed merge, protected
main validation, signed immutable publication and native software certification:

1. Stage a clean new release and preserve literal private configuration, adding
   only the three reviewed continuity/transport selections. Keep the actual
   external backup path and all credentials unchanged.
2. Install the root-owned public transport configuration, the published transport
   helper and its two native units. Start only those new mount units. Preserve
   Docker's old drop-in and udev rule at this stage and prove its PID unchanged.
3. Use the canonical full fenced installation/activation to select the new
   PostgreSQL parent bind while preserving its data volume and physical identity.
   Require genuine immutable ACTIVE/operational-ready records and a healthy
   current external checkpoint, not a shell handoff result.
4. Compare the exact old Docker drop-in and USB udev-rule hashes again. Replace
   only those owned files with the reviewed internal-parent dependency/primary
   storage guard and transport-arrival rule. Reload systemd/udev configuration
   without restarting Docker or triggering the USB device. Keep the old public
   bytes and hashes in exclusive operation evidence.
5. Hand over the same existing backup maintenance unit to the new checkout,
   preserving its fragment and every prior drop-in. Add one uniquely named
   drop-in, respect native lifecycle/media ownership and retain actual native
   capacity/checkpoint/backup health evidence. Never create a second loop.

Operational launchers must bind the eventual real commit/image and refuse before
any credentials, host writes or service calls while either is unspecified.
Existing operation evidence means inspect its owner/result, never replay it.
This delivery does not claim the historical supervisor failure is repaired.

References: [PostgreSQL archive failure and retained WAL](https://www.postgresql.org/docs/16/continuous-archiving.html),
[systemd mount requirements](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html#RequiresMountsFor=),
[Docker bind propagation](https://docs.docker.com/engine/storage/bind-mounts/).
