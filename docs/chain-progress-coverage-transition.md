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

The recovery-only writer-lock exemption is restricted to this native evidence
transfer function with its authenticated predecessor, durable fence and source
proofs. Financial plan and broker writers retain their runtime backup authority
gate. The central exemption audit must bind the function and these guards,
rather than granting a module-wide financial exception.

## October 29 local recovery correction

The owner authorized a locally qualified patch before open, with PR delivery
after open. The actual paused physical recovery refused a read of
`sentinel_sep_staging`: PostgreSQL cannot read unlogged relations during recovery.
The feed schema deliberately defines this relation as disposable vendor scratch,
never as the durable corpus. Keep it in the witness relation set. Bind its exact
relation identity, unlogged persistence and column contract instead of claiming
that a physical backup preserves its rows. On the primary, require this scratch
relation to be empty while the existing SHARE source lock is held. Refuse any
other unlogged source or a changed scratch contract. All durable source rows
retain their original streaming byte proof and every existing account, prefix,
DDL, ownership, fence and atomicity check remains mandatory.

The price-domain source scanner must distinguish the two exact static column
contract declarations in this recovery owner from reading a price. Recognize
only their parsed literal-token coordinates inside the named scratch branch of
`_source_digests`; do not add the recovery module to the price-reader allowlist.
Changed declarations, additional literals, dictionary or attribute reads and
the same declaration in another module must still fail. Derive the canonical
repository path independently from diagnostic labels so the CI metadata mirror
and imported test tree enforce the same boundary. Qualification includes an
executed broad-exemption falsifier. This changes the source audit only; the
recovery implementation and every financial price-domain rule remain unchanged.

Qualify on an actual paused physical restore, including the original PostgreSQL
refusal and nonempty-primary/changed-contract falsifiers. Local delivery changes
only the one-shot recovery utility, mounted read-only over the installed signed
foundation. Retain the exact local commit, worker hash, qualification report,
foundation image and original commands in operator evidence; do not label the
local worker CI-certified or change application service images. The same native
host lifecycle lock and one-shot logs still own application. Activation of the
unchanged installed release must independently pass normal financial admission.

The retained original installer command invokes both `schema.ensure_schema` and
`store.migrate_schema`. The first replaces the progress trigger; the second
reinstalls the existing feed guard declarations. The initial recovery test
measured only the first call. Reproduction of the complete canonical sequence
on private PostgreSQL 16 yields exactly 66 DDL events and preserves the complete
watched source-byte proof. Qualify and pin that complete sequence, rather than
the lower-level helper's single event. Accept only 66 for this incident; an
extra event, a helper-only migration, changed catalog or changed source bytes
still refuses. The authenticated pre-DDL witness remains valid and is reused;
no additional restore, DDL, counter reset or source mutation is needed.

The host publisher creates the original witness with owner-only permissions,
while the signed CLI runs as UID 10001. Preserve that original immutable file.
After exact-hash validation and host-lock acquisition, create a byte-identical
runtime copy inside an operation-private temporary directory, make only that
copy read-only and bind-mount it read-only. Keep the default container identity.
Remove the temporary copy on success or refusal; retain the original witness,
its hash and the command log. This fixes file access without granting new
database, filesystem or financial authority.
