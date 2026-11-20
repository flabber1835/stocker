# Acquisition guard upgrade and authenticated evidence

The #612 to #613 upgrade changes the acquisition retention and binding guards. PostgreSQL records public schema changes in a database-wide epoch. The journal binds both the observation and mirror coverage proofs to that epoch. The original installer replayed the feed catalog without transferring either proof. The pre-migration physical backup passed replay, and the first guarded activation refused the obsolete proofs.

For a prospective upgrade, the fenced migration owner must recognize the exact supported predecessor catalog, perform the reviewed guard DDL, validate the successor, and transfer existing authenticated proofs in the same transaction under the existing writer exclusion. Use the existing operational DDL handoff. Preserve coverage stage, body, through-boundary, source identities and binding. A current installation should do no DDL on repetition. First installations retain their ordinary empty-book path. Unknown catalogs and altered proofs on a bound installation refuse.

Explicit feed migration also reconstructs the derived current identity projection from published and eligible legacy evidence. Reuse the publication-generation membership and field precedence for repairs on a current schema. Hold the corpus writer lock through the migration transaction and update only changed rows. Ordinary runtime schema checks only read the catalog. The publication policy cutoff, historical action keys and action/anomaly lifecycle events belong to their original legacy bootstrap migrations. A current protected book retains those immutable records and must refuse missing authority.

For the installation already migrated, use the selected physical backup taken before the DDL. The restore owner must verify the #612 catalog and capture a signed witness from the database paused at its recorded recovery marker. The fenced apply owner must verify the exact #613 successor, the independently reproduced 67-event migration, the database and account binding, the original authenticated prefixes, and the source row evidence while holding the existing locks. Restrict recovery to this reviewed transition. Transfer both proofs atomically and verify them in the same transaction. Retain the backup, witness and transfer receipt. Ordinary runtime readers keep enforcing the evidence contract. Guarded PAPER activation must pass independently afterward.

## Operator recovery

Install the signed recovery release while fenced. Use the new installation receipt for the apply step. Select `base-20261120T073234Z` for the witness. A private physical replay of that backup paused at `4E/E5000000` and contained the original authenticated histories at epoch 475. The migration left the primary at epoch 542. The shorter prospective upgrade advances the epoch by four.

Run the following through the native user manager that owns the backup mount. Supply the canonical external backup root and an operator-owned private directory for the new artifacts.

```sh
bash scripts/sentinel-restore-drill.sh --physical-only \
  --backup "$BACKUP_ROOT/base/base-20261120T073234Z" \
  --acquisition-guard-witness "$PRIVATE/acquisition-witness.json"

python3 scripts/sentinel_order_amount_coverage_recovery.py --acquisition-guard \
  --installation-receipt "$INSTALL_RECEIPT" \
  --witness "$PRIVATE/acquisition-witness.json" \
  --confirm-witness-sha256 "$WITNESS_FILE_SHA256" \
  --backup base-20261120T073234Z --output "$PRIVATE/acquisition-transfer.json"
```

Read the witness file SHA-256 before applying it. Verify the resulting receipt against the installation and both evidence domains. Then request guarded dual PAPER activation for that installation. A failed earlier activation remains part of the history.
