# Coverage across the backup progress migration

Decision: 2026-10-29. Implementation and qualification are required before use.

The progress-guard-v2 migration replaces only the backup progress function and
trigger. The conservative independent DDL epoch also invalidates the existing
OBSERVATION and MIRROR coverage prefixes. Neither restarting the verifier nor
software installation may silently reseal them. Normal runtime coverage loading
continues to refuse changed inventory.

Use an explicit, one-time migration transition with a witness from a physically
verified pre-migration backup. The existing restore owner obtains the witness
from its isolated, paused-at-marker database using a server-enforced read-only
connection. It validates the exact pre-chain-progress schema, operational
extensions, independent DDL witness, account binding, both tracking heads and
both authenticated coverage prefixes. Each prefix must be complete and current.
The witness binds the selected backup, recovery marker, metadata digest,
physical system, DDL incarnation/epoch, source relation inventory and exact
prefix payload/signature digests. Also bind streaming binary digests of every
watched source relation, including physical tuple coordinates. Restrict the
watched set to the declared financial sources, present feed-owned relations and
normalized/generation data relations; include their partition descendants.
Restrict the processed-session relation to its two tracked witness namespaces. Disable
parallel/index/synchronized scans for deterministic physical tuple order; the
same preserved PostgreSQL system and relation identities are mandatory.
Authenticate the witness with the existing
receipt key and preserve it as immutable operator evidence. No broker access,
new base backup, source ingestion or financial writer is involved.

Application of that witness is a separate explicit native operation. It requires
the exact witness digest, expected backup/account/deployment, current reviewed
schema, disabled+killed execution, invalidated lease, canonical host/writer
ownership and finite database lock/statement deadlines. Lock the watched source
relations against writes and lock both heads/coverage rows. Require unchanged
physical system, account, DDL incarnation, tracking incarnation/head/reset,
source relation inventory and exact old authenticated prefix bytes. The only
permitted independent-epoch advance is the count produced by the exact reviewed
progress migration, qualified using real PostgreSQL. Additional DDL, source
changes, recreated tracking, altered prefixes or partial proofs refuse. Compare
the source-row digests independently, so source preservation does not depend
solely on change tracking or the DDL event counter.

Only the coverage inventory and its authentication may change. Preserve every
prefix body, through-boundary, binding, incarnation and reset generation, all
tracking history and all financial rows. Commit both domain transfers atomically;
any refusal rolls both back. An old witness cannot authorize a later reseal
because its exact prefix digest no longer matches. A witness from an already
migrated database is invalid. Never delete a prefix, reset a counter, substitute
current evidence for the old witness, or infer success from a heartbeat.

This transition preserves an existing proof across an exactly identified DDL
change. It grants no source freshness, broker authority, plan, command replay or
operational readiness. Activation must still pass its original financial,
backup, source, account, authority, reconciliation and scheduling gates.

Qualification must execute the real old-schema witness and migration on private
PostgreSQL, prove the exact DDL increment, exercise both domain transfers and
rollback, and kill missing-fence, extra-DDL, changed-head, changed-binding,
changed-prefix, missing/recreated-tracking and witness-authentication falsifiers.
The restore integration must preserve physical replay/marker checks, private
networking, finite worker deadlines and cleanup on every outcome.
Witness capture and application each have one 600-second worker deadline and
bounded streaming memory. Existing restore, archive and installation deadlines
are unchanged. This exceptional recovery reuses the existing pre-DDL base; it
does not create a new base backup or run a strategy comparison.

After the reviewed software installation finishes, an operator obtains the
one-time witness with the canonical restore command:

```
bash scripts/sentinel-restore-drill.sh --physical-only --backup EXACT_PRE_DDL_BASE --chain-progress-witness ABSOLUTE_NEW_WITNESS_PATH
```

With its actual file SHA256 and the successful current installation receipt:

```
python3 scripts/sentinel_chain_progress_recovery.py --installation-receipt EXACT_RECEIPT --witness EXACT_WITNESS --confirm-witness-sha256 FILE_SHA256 --backup BASE_NAME --output ABSOLUTE_NEW_TRANSFER_RECEIPT
```

The host owner verifies the exact signed CI runtime and installed checkout,
confirms the backed owner PAPER profile, acquires the existing host lifecycle
lock, and calls the native transfer with only database/receipt-key access. A
retained result or command log prohibits another automatic attempt. Inspect an
interrupted operation rather than rerunning it. Only after this boundary passes
may the original canonical activation proceed.
