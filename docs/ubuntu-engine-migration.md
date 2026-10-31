# Sentinel engine migration into Ubuntu

Decision: 2026-10-31. The owner requests migration from Docker Desktop to
Docker Engine in the existing Ubuntu WSL distribution, followed by installation
and activation of the merged PR551 release. This removes the Desktop engine,
integration proxy and Windows credential helper from Sentinel's runtime path;
it does not migrate Windows itself or remove WSL.

## Preserved identities and ownership

Use Ubuntu's default local Unix Docker endpoint, with its own native Engine,
containerd and Compose plugin. Do not use an ambient Docker selector, proxy shim,
Windows Docker executable or remote daemon as the target. Disable Desktop's
integration for Ubuntu so it cannot reclaim that distribution's CLI/socket.
Preserve the previous private Docker configuration before removing its
Desktop-specific credential-helper selection. Existing credentials are never
printed or placed in command arguments.

Only Sentinel containers and its named volumes are in scope. Leave unrelated
Desktop workloads, volumes and image caches untouched. Stop the Desktop engine
only after positively proving every running container belongs to Sentinel and
after the supported fence and clean application/database shutdown; otherwise
leave it running for unrelated workloads. Never globally prune it. Keep the old Sentinel volumes
offline for rollback until target verification completes; after new financial
writes, the predecessor is stale and cannot simply be restarted.

Preserve both `sentinel_sentinel_pgdata` and `sentinel_sentinel_state`, the exact
PostgreSQL16 physical system `7691913275518591014`, account `PA3NDXAHULSS`, the
canonical book, binding, positions, plans/cycles, command/UNKNOWN journals,
authority files and notification history. Preserve PAPER-only owner-function-
first operation, the 100bps protected BUY policy, REQUIRED_V1 backups and WAL.
An engine change does not authorize a new database, account adoption, book
bootstrap, manual control edit, stale plan replay or fabricated recovery proof.

## Storage admission

Discovery found about15.2GiB of primary PostgreSQL data, but only about1.6GiB of
physical free space on C:. Ubuntu's reported virtual free space is not proof that
another copy fits. Admit the target only after identifying the actual physical
filesystem, its free space, private directory ownership and mount lifetime.

The positively verified external ext4 UUID
`2ed4fe3b-def6-45db-940b-e78186758164` already holds backup and restore media.
Keep it as the backup failure domain. Native Engine/containerd and primary data
therefore stay on Ubuntu's internal filesystem, after recovering actual physical
C: capacity. Never format the external disk or reuse disposable restore payloads
as primary data. Do not claim two directories on one device are independent.

Ubuntu's353.3GB backing VHD contains about182.8GB of allocated Linux filesystem
data. To recover already-unused allocation, trim only Ubuntu's root filesystem,
stop Ubuntu, positively verify its exact registry-bound VHD is detached with an
exclusive file handle, and invoke Microsoft's documented metadata-only
`CompactVirtualDisk` API without attachment or privilege changes. Use a new
one-shot evidence record. Do not operate on the Desktop data VHD or delete source
files for this reclamation. Observe actual C: free space afterward; unsuccessful
or insufficient reclamation does not admit a database copy.

Require the verified filesystem mount before starting Engine or any persistent
container, so a missing external disk cannot select an empty fallback directory.
Preserve the existing backup media and archive ownership; any path translation
must prove the same bytes and real filesystem rather than manufacture fresh
backup or restore receipts.

Cold-copy only after supported execution fencing, writer quiescence and clean
PostgreSQL shutdown. Stream each exact named volume directly to its positively
owned target, preserving numeric ownership, permissions, links and PostgreSQL
bytes. Check tablespace/WAL links explicitly. Do not create an intermediate
database archive or an additional base backup merely to migrate storage.
Reconcile source and target file inventories and digests while both are offline.
No source data is deleted to fund an unverified transfer.

## Host portability and restore scratch

On WSL with a native Ubuntu Engine, physical capacity discovery must depend on
the Ubuntu backing storage or its proved external mount, not on the existence
of Docker Desktop's VHD/settings. Docker Desktop selection retains its existing
exact backing-path proof. Preserve the existing physical free-space reserve and
all backup/restore allocation accounting; an unavailable backing identity still
refuses.

External scratch records belong to their original Docker Engine ID. The new
Engine must not rewrite, adopt, clean or infer absence of old Desktop-owned
scratch attempts. Keep them unchanged. Select a new empty private scratch root
on the verified UUID, outside primary, Engine, repository and backup trees, with
its Engine-visible path equal to its Ubuntu path. Ordinary native ownership and
UUID/inode/capacity checks remain mandatory.

## Cutover, release and acceptance

First prepare the target Engine and immutable images without starting a second
Sentinel writer. Then fence and stop only the predecessor Sentinel roles and
PostgreSQL, transfer and verify the offline volumes, and start the target only
through the supported canonical lifecycle. Restore the retained host authority
and literal private configuration. Use the exact merged source
`4da55f9db5db4fdbf7d70eb99871c14d1b2a3d18` and signed runtime
`ghcr.io/flabber1835/stocker/sentinel@sha256:943b645041e115c8e2aa3780b524057b2cd1db698a58a63bc391e2ed488180fb`.
Do not rebuild the application or rerun completed PR suites.

Run a new canonical full installation attempt and retain its immutable
INSTALLED/FENCED receipt. An unchanged schema does not need a new base, replay
or migration. Queue one supported dual activation from that successful receipt;
it must earn its own current financial/source/account/authority and archived
checkpoint evidence. Preserve native refusal gates and finite deadlines.

Completion requires an actual ACTIVE/operational-ready receipt, the preserved
physical database/account/history, six healthy exact-image roles, an advancing
leader, enabled/kill-released control, the actual eligible next-session plan,
healthy backup/WAL and notifications, and local/public dashboard observations.
Keep raw financial/historical verdicts distinct from human operating health.
Do not acknowledge active failures or call unresolved browser-image/flicker
issues fixed by this host migration.

Record and qualify startup ordering for the verified storage, Engine, backup
maintenance and application roles. WSL must itself be started by Windows; an
enabled Linux service alone is not proof of no-login or power-outage recovery.
Preserve existing Sentinel startup tasks where valid, and report any remaining
reboot/no-login qualification gap explicitly.

Use one current-user Windows logon task to retain a foreground Ubuntu WSL
request and supervise attachment of the existing shared backup USB device.
Before each one-shot attachment, match the Seagate instance
`USB\VID_0BC2&PID_231A\MSFT30NA85AJZ4` and persisted sharing GUID
`25b7e905-42ad-4df9-b558-418de3cd62de`; derive its current bus ID rather than
following an arbitrary replacement at a fixed port. Never bind, force, detach
or select another device. The supervisor waits while the device is absent and
does not write a log on every observation. A UUID-and-ext4-scoped udev add rule
requests `docker.service` after the backup device arrives. Docker still requires
the actual mount and its identity guard before starting.

Native systemd owns Engine and application/backup services. Give the Windows
task no execution-time limit, prevent duplicate instances, and restart a failed
foreground request. Do not change global WSL idle policy or store a Windows
password. This provides startup after that user logs in. It is not proof of
recovery before login after a cold boot.

Reuse the existing `sentinel-paper-backup-maintenance.service` after a successful
new installation: preserve its private unit/drop-ins and enabled state, then
select the new checkout and the canonical maintenance loop through a sanitized
environment. Its native supervisor and media locks remain the sole ownership
authority. Require a real read-only Windows capacity observation from that same
systemd environment before starting it; never persist a captured WSL interop
socket or substitute invented free-space data.
