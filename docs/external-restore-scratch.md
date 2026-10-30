# External scratch for isolated restore drills

## Decision

A physical base and its disposable restore currently allocate on the same Windows
backing drive when Docker Desktop and the backup directory share C:. Admission
correctly adds both copies, their growth estimates, and the free-space reserve.
An older base cannot be reused when its immutable recovery marker predates the
current feed schema. Its marker and historical restore receipts remain unchanged.

Support an explicitly configured external filesystem for disposable restore data.
The production PostgreSQL volume, WAL archive, backup root, maintenance owner,
base selection and immutable recovery markers keep their existing identities.
Default restore allocation remains the existing randomly named Docker local volume.
This is a host storage option; it grants no broker or activation authority.

The optional settings are an all-or-none group:

- `SENTINEL_RESTORE_SCRATCH_ROOT`: a pre-created, private operator-owned directory
  below an actually mounted ext4 filesystem, outside repositories and backup media.
- `SENTINEL_RESTORE_SCRATCH_UUID`: the expected mounted filesystem UUID.
- `SENTINEL_RESTORE_SCRATCH_DOCKER_ROOT`: the same directory as seen by the Docker
  engine. On native Linux this normally equals the host root. Docker Desktop may
  require its engine-visible WSL shared-mount path.

Literal environment validation accepts these settings only together. It rejects
relative or malformed paths and UUIDs. Storage admission additionally proves the
real mount, device, directory identity and permissions; configuration alone never
makes a missing mount or fallback directory acceptable.

## Ownership and transport

Reject symlinks, path normalization changes, root/home/repository/backup paths,
non-private roots, and a root that is not on the configured ext4 UUID. Resolve the
UUID through `/dev/disk/by-uuid` and match its block device to the actual host
mount and directory device. A restore owns a newly created random child; it never
uses a pre-existing child, arbitrary directory, production volume or backtest path.
Protected path comparisons work in both directions: scratch may be neither an
ancestor nor a descendant of a repository, primary data, WAL or backup subtree.
Separate scratch and backup directories may share one filesystem; capacity then
adds both allocations on that same physical backing device.
On WSL, this option supports only a positively identified physical USB device:
the UUID-bound block device must have an actual USB subsystem ancestor in sysfs.
A second C:-backed VHD with a valid ext4 UUID is not independent capacity.

Use Docker's native local named-volume driver with `type=none`, explicit
`o=bind,rw` for restore/cleanup or `o=bind,ro` for probes, and the engine-visible
child as `device`. Containers receive only the random
volume name. This avoids Docker Desktop treating an Ubuntu absolute source path
as an instruction to re-enter Ubuntu's automounter. An actual read-only local
volume probe on the approved USB filesystem verified identical device/inode and
marker bytes through this route on October 20, 2026. A separate writable probe
verified exact options, device/inode, nonce and a small write/readback with
`bind,rw`; bare `bind` was refused by the local WSL Docker path and is unsupported.

Before any restore write, a bounded network-free, read-only-rootfs probe must prove
that the named volume has the exact local driver/options/ownership labels and
maps to the host-verified external directory device/inode. A fresh private nonce
binds the probe to this invocation. Mounts use `volume-nocopy`. A missing mount,
unexpected inode/device, alias, consumer or volume configuration refuses rather
than falling back to Docker storage. Probes receive no provider or database
credentials. The restore's source backup retains its existing shared media lock.
Transient nonce files stay outside PostgreSQL data. The data child must be empty
and retain its verified identity immediately before the canonical copy. Recheck
UUID, mount and all recorded directory identities after capacity and before copy
or cleanup; a mount swap or disappearance refuses rather than choosing fallback.
The canonical restore worker independently compares its own mounted data
device/inode with the sealed expected identity and requires an empty target after
acquiring its media lock, immediately before `cp -a`. Host probing alone cannot
authorize the later first write. The optional guard is absent on default storage.
Probe and payload-cleanup containers also have independent in-container timeout
limits shorter than their host deadlines, so a lost Docker client cannot leave
an unbounded worker. Trading deadlines are unrelated and remain unchanged.

Each owned attempt keeps its immutable ownership record outside its PostgreSQL
data child. Cleanup first stops only the already-owned restore workers. It may
remove the named volume and its external data only after verifying the same UUID,
root/attempt/data identities, ownership record, exact volume options/labels and
absence of consumers. Cleanup uses a bounded network-free PostgreSQL-image worker
because restored files belong to the PostgreSQL UID. Unknown or changed ownership
preserves data and refuses cleanup; no global prune, mount change or broad path
removal is permitted. No cleanup operation can select the scratch root itself.
Docker must first atomically remove the original idle volume, proving that no
lost-client worker remains attached. A separate exactly owned cleanup volume
then provides bounded access to the recorded data child. Changed ownership or
unexpected consumers preserve the data instead of inferring worker death.
External data/probe/cleanup volumes use their own labels, outside the generic
Docker-local restore-volume reaper. A lost host therefore preserves the external
payload and its ownership record without making unrelated maintenance refuse an
unknown reaper name. The explicit `sentinel_restore_storage.py cleanup --volume
<owned-name> --backup-root <unchanged-root>` path can finish an idle recorded
attempt. It verifies the original Docker Engine ID as well as UUID and directory
identity; switching Docker endpoints never makes a missing handle proof of death.
An already-created exact cleanup volume permits resuming a partial cleanup only
after positive original-volume absence. Missing both handles preserves the data.

## Restart-safe ownership recovery (2026-10-30)

Linux device numbers describe the current mount, not permanent ownership across
boots. New `sentinel.restore-scratch/2` records retain captured device/inode pairs
as provenance, but persistent ownership binds the configured filesystem UUID,
original directory inodes, private operator ownership, engine identity and exact
volume options/labels. Each invocation freshly proves the UUID-backed USB mount
and binds its current device number. Root, attempt and data must stay on that
same device throughout the invocation; every existing before-use and in-worker
device/inode check remains mandatory. Ordinary reads never rewrite records.

Legacy version-1 records remain strict. The explicit `recover` mode may admit
only its named legacy attempt when all original ownership fields and inodes
match and the sole difference is one consistent historical device renumbering.
It requires the canonical backup ownership lock, a fresh host/engine nonce
mapping proof, the original engine, exact idle original or cleanup volume and
fresh current-directory checks. Missing both volume handles, changed inodes,
unknown contents or another engine preserve data and refuse recovery.

Before cleanup, publish a new private immutable admission receipt at the
operator-selected `--receipt` path, retaining the original ownership document
and its digest plus the freshly admitted identities. An existing receipt is a
refusal requiring inspection. Cleanup then uses the existing atomic original
volume removal and bounded exact-child cleanup protocol. An interrupted cleanup
retains its old owner record and can be explicitly recovered after inspecting
the prior receipt and exact volume state. No owner record is edited in place,
and no recovery authorizes production data, backup deletion or broker actions.

With the literal maintenance environment already loaded, use the exact recorded
volume name and a new absolute receipt path:

```sh
SENTINEL_BASE_BACKUP_LOCK_ROOT="$SENTINEL_BACKUP_DIR" \
  python3 scripts/sentinel_backup_lock.py hold \
  python3 scripts/sentinel_restore_storage.py recover \
  --backup-root "$SENTINEL_BACKUP_DIR" --volume "$EXACT_OWNED_VOLUME" \
  --receipt "$NEW_ABSOLUTE_RECOVERY_RECEIPT"
```

New attempts use version 2, so an ordinary reboot does not require another
legacy migration. A mount/device change during an admitted operation still
refuses. Tests must exercise device renumbering through admission and cleanup,
interrupted cleanup, and wrong UUID, inode, engine, symlink, active consumer,
missing-handle and mid-operation mount-swap refusals, including executed guard
falsifiers. No full strategy replay is part of this storage qualification.

## Capacity and financial gates

The existing copy estimate remains `ceil(1.5 * bytes) + 1 GiB`. The existing
10 GiB reserve remains on each physical backing disk. Both base admission and
restore admission observe the configured scratch disk. Copies sharing a disk are
added together; separate disks are checked separately. WSL virtual free space
never replaces the Windows backing-drive observation. The verified external
filesystem's actual free bytes supply its separate capacity observation.

An optional external-volume probe may allocate only bounded metadata before
capacity admission. It cannot copy a base. The full restore volume and copy start
only after admission succeeds, and identity is rechecked immediately before use.

Physical verification, recorded marker replay while paused in recovery, explicit
promotion, the exact current runtime's read-only `sentinel.restore_validation`,
metadata stability and append-only full restore evidence remain mandatory. A
physical-only or failed semantic drill still earns no current-image full receipt.
Activation still requires its normal current-source financial gates and freshly
archived activation-state checkpoint. This change does not qualify any trading
release or make the dashboard green by itself.

## Verification

Cover the unchanged default; explicit settings and all-or-none validation; actual
UUID/mount and host/engine identity mismatch; symlink/protected-path refusal;
consumer/label/option/ownership refusal; precise same-disk aggregation and separate
external capacity; failure before copying; bounded exact-owned cleanup; and full
semantic failure with no receipt. Falsify the inside-volume identity guard to prove
its mismatch test fails when that guard is removed. Qualification uses a new
private source and never reads or changes the running backtest.
