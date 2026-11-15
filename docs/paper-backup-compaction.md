# Compact the active PAPER backup

The November 15 PAPER maintenance removes retired acquisition payload and
reclaims physical space before creating another full PostgreSQL base backup.
The production cluster, its WAL archive, and the exact installed release remain
the recovery authority. No fresh provider request is needed for recovery.

Recover the pre-maintenance verified base and its recorded WAL marker in an
isolated PostgreSQL 16 container with a disposable volume. Export the disabled
October 17 predecessor database from that recovered instance. Restore the
logical archive into a second database in the private instance and compare its
contents before sealing the archive with its checksum on independent media,
outside ordinary base and WAL retention. Only then may the exact disabled
predecessor be dropped from the primary. The backtest and its database are
outside this operation.

On the active database, enter the ordinary backup-authorized writer lock and
the corpus writer lock outside the trading window. Authenticate the existing
checkpoint records. Freeze the set of retained acquisition price parts using
the existing canonical pin function. Retire only price payload for unpinned
parts, in independently committed physical extents. On PostgreSQL 16, require
the actual TID range scan for each extent over the original relation identity
and heap boundary. This avoids the random heap access seen when retiring an
entire part by its index. Keep the installed statement
trigger enabled so it checks the deleted part IDs against the current pin
lineage and requires both locks on every batch. Use the guard installed
through the qualified release. It materializes the distinct part IDs from
its transition table before running the pin predicate. PostgreSQL can
otherwise push the pin filter below DISTINCT and re-run the lineage check
for every price row.

The November 15 operation temporarily used the equivalent function body
inside each extent transaction and restored the installed definition before
each commit. The operational DDL audit correctly recorded both changes for
each extent. The MIRROR and OBSERVATION coverage records still authenticated,
and their heads and account binding matched. Both inventories matched the
original DDL epoch of 142. The 268 recorded function replacements advanced
the epoch to 410 and invalidated the old operational proof. Future maintenance
should use the already installed guard and avoid transaction-local replacement.

Keep acquisition manifests,
bindings, current normalized input, historical evidence and the financial
journal. Abort on unexpected identity, state, or lock contention.

After verifying the pinned payload is unchanged, compact the acquisition
relation and reclaim index space from the legacy bars table only after
confirming that it has zero rows. Keep the PostgreSQL system identifier and
all normal WAL archiving and retention. Create a fresh verified physical base
with the ordinary deadlines and replay its recorded WAL marker in the
canonical full private restore drill with the exact installed runtime image.
Verify the logical archive and the new physical base independently.

## Release qualification

Seal the acquisition guard's exact successor bytes in the existing complete
source profile. Preserve the installed signed PAPER revision
`93f2acb4fc328b1ad47da34507d0222910a5de6e` as an exact retained predecessor
with its original source inventory. The source transition carries no new
financial authority. Qualify the current candidate against both that installed
inventory and the existing historical witnesses, including the unknown-source
refusals.
