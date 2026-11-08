# Preserve the shared environment's native reader during installation

The diagnostic application roll replaced the shared deployment `.env` at
2026-11-08 01:37:25 UTC. Its temporary file belonged to the privileged installer,
so the replacement became root:root mode 0600. The existing native maintenance
owner ran as uid/gid 1000 and could no longer read it. Its next five-minute pass
refused environment preflight; the last genuine runtime-chain evidence expired
at 01:47:24 UTC and the dashboard correctly became red. Current WAL archiving
continued. This is an installation ownership/reader-continuity failure, not a
missing per-image restore drill.

Both generic and backed local installers must use the same atomic environment
replacement contract. Open the old file without following symlinks, require one
regular unaliased file, and retain its exact owner, group and permission bits.
Set those properties on the new file descriptor before durability and rename;
never widen mode or substitute the privileged installer's identity. Fence the
original directory/file inode, metadata and bytes until replacement and check
the new file afterwards. Unsupported extended metadata, including POSIX ACLs,
refuses rather than silently disappearing. No existing private configuration,
credential, financial permission or backup policy changes as a consequence.

For REQUIRED_V1, discover the actual native backup-maintenance owner whose exact
`sentinel_backup_maintenance.py --loop` invocation has the shared deployment as
its working directory. Require one matching owner, not a guessed username or the
parent directory's owner. Retain the process ID/start clock and filesystem
uid/gid/supplementary groups; refuse a changing or unavailable reader. The
maintenance script selects that working directory's exact `.env`. A non-required
legacy deployment still preserves file metadata; an existing matching reader
receives the same continuity checks.

Before rename, a finite helper drops to the actual reader's credentials and
reads both the original and temporary environment, comparing only bounded byte
hashes. After rename it reads the new target under those credentials again.
The installer also rechecks the native owner identity. A root-only successful
read is insufficient. These are finite file-access checks at the configuration
mutation boundary, not backup jobs, restore drills, filesystem/WAL scrubs,
readiness polling or new recurring loops.

If the installer lacks permission to preserve the exact metadata or assume the
known reader credentials, it refuses before replacement. A failed post-replace
continuity check refuses completion and retains the original metadata contract;
it never marks backup readiness successful or silently rolls financial state.
The existing native maintenance owner renews actual runtime-chain proof normally
after access is restored. Its original expiry is not extended or acknowledged
manually. Installation must not claim success from a still-current proof whose
producer lost access during the same roll.

Focused qualification must include a real private root writer and a distinct
non-root reader, exact uid/gid/mode preservation, actual credential-dropped read
success before/after replacement, and failure when ownership preservation is
removed. Cover malformed/foreign reader identity, native owner change, changed
original inode/metadata/bytes, links/symlinks, unsupported extended metadata,
unreadable candidate, and metadata operations failing before replacement. Keep
the 456-module application source seal and economic fixtures unchanged.
