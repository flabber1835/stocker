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
