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

Install the optimized delete function through the composed feed migration.
The retention schema owns its SQL. The migration substitutes that one
definition before creating the trigger, keeping the exact acquisition read
dependencies and their economic witness. The migration and read-only catalog
validator use the same effective definition. Verify the normal migration
replaces the old guard and restores catalog admission.

Seal the changed retention migration sources in the existing complete
source profile. Preserve the installed signed PAPER revision
`93f2acb4fc328b1ad47da34507d0222910a5de6e` as an exact retained predecessor
with its original source inventory. The source transition carries no new
financial authority. Qualify the current candidate against both that installed
inventory and the existing historical witnesses, including the unknown-source
refusals.

## Recovering the invalidated execution evidence

The November 15 incident advanced the operational DDL epoch from 142 to 410.
The subsequent PR #593 installation ran the full feed migration and advanced
it by another 65 events to 475. The two complete authenticated execution
prefixes still name epoch 142. The runtime must continue to refuse them
until the operator proves that the data those prefixes certify survived.

Use a one-time coverage transfer for this exact maintenance and installation
sequence. Capture a signed witness from a verified, isolated, paused physical
restore taken before compaction. The retained base at 09:45 UTC predates
normal observation and plan writes. Use base `base-20261115T094526Z` and
replay through the commit at `45/62381E78` (15:12:06 UTC), after those writes
and before compaction. Verify the contiguous archived WAL and its SHA-256
sidecars through the selected segment. Require the restore to pause at the
exact commit end, `45/62381EA0`. The restored database is read-only and in
recovery. Its historical automation control need not have been fenced.
Require the original acquisition delete
function, the exact old epoch, the physical database and PAPER account binding,
both current authenticated prefixes, and streaming binary digests of their
watched source rows and change histories. Bind the witness to the selected
backup, recovery marker, backup metadata digest, and exact replay end.

Apply the witness under the existing lifecycle and journal writer locks while
automation is disabled and killed. Lock the watched relations, require the
installed successor schema and exact epoch 475 in the same audit incarnation,
and independently compare the account binding, source relations, source bytes,
tracking coordinates, and original authenticated prefixes. Market acquisition
payload retired by the documented operation is outside the two coverage
inventories. Normal activation still independently qualifies retained market
inputs. Write both prefixes atomically with their original bodies and
boundaries and the current inventory. Additional DDL, changed bytes, ambiguous
proof or a replayed witness must refuse. This operation issues no broker
command, grants no authority and cannot enable automation.

The one-time reader checks the pre-compaction and post-compaction feed catalogs
against the releases that produced them. This preserves the original 65-event
feed replay and both historical guard implementations across later changes
to the operational feed schema.

After installing the signed recovery release while fenced, run both steps
through the native systemd user manager so they see the canonical USB mount.
Use the verified pre-compaction backup and the successful installation receipt
for that release.

```sh
bash scripts/sentinel-restore-drill.sh --physical-only --backup EXACT_PRE_COMPACTION_BASE --backup-compaction-witness ABSOLUTE_NEW_WITNESS_PATH
python3 scripts/sentinel_order_amount_coverage_recovery.py --backup-compaction --installation-receipt EXACT_RECEIPT --witness EXACT_WITNESS --confirm-witness-sha256 FILE_SHA256 --backup BASE_NAME --output ABSOLUTE_NEW_TRANSFER_RECEIPT
```

The transfer receipt records evidence recovery only. Run normal PAPER
activation after the transfer has passed.
