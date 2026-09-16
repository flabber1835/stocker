# Rolling price-reader checkpoint rehearsal

Status: comparison implementation, not operational cutover. This is the first
reader portion of step 3 in [the migration plan](rolling-operational-snapshots-design.md).

## Decision before implementation

Introduce an explicitly selected immutable-generation price reader and a
read-only, one-transition rehearsal from an existing attested shadow checkpoint.
Do not let a comparison version masquerade as a corpus publication version.
The reader returns price inputs, not a `PublishedSession` carrying production
authority. Only the rehearsal composes these prices with a pinned legacy
session for comparison through the **existing canonical kernel**.

The command selects an exact completed comparison job and an existing logical
shadow observation. It runs in one repeatable-read, read-only transaction under
the legacy publication pin. It refuses unsealed/unpublished candidates, changed
legacy versions, incompatible calendar/normalization, a different strategy,
missing runtime attestations, and anything other than the checkpoint's next
XNYS session. It verifies the candidate's retained content before comparison.

Checkpoint origin is the existing immutable genesis, record/state chain and
per-session PostgreSQL runtime attestations, checked by the existing observer
validators. No caller-supplied JSON checkpoint or newly computed hash is accepted
as origin. This is a one-time rehearsal: scanning immutable records is permitted;
reloading the original vendor warmup or historical prices is not necessary for
this structural origin check. It does **not** renew old `VERIFIED` status, prove
backup/restore authority, or admit a checkpoint for production. The old runtime
identity remains recorded unchanged; running this comparison with newer reader
code is not authorization to advance that lineage in production.

The reader bounds SQL to the selected candidate and requested XNYS interval.
The retained checkpoint's restart tail (at least its configured feed retention,
the candidate restart requirement and SPY requirement), with one predecessor,
must fit in the window through its cursor. Out-of-window outages refuse; they
do not create a new book. Signal anchors must exist at the exact dates required
by the baseline. Missing old live anchors refuse with a named dependency rather
than falling back to legacy prices or assuming a split factor of one.

For this stage, dated metadata, sectors, terminal/spinoff inputs, returning-name
absolute split anchors and the revision proof are deliberately shared from the
held legacy publication. The report names that limitation. This isolates the
price-reader seam; it does **not** qualify the candidate reference generation or
claim independent provider/loader parity. Their migration and persistent
out-of-window anchor ownership remain prerequisites to operational GO.

Require exact canonical input equality, then exact resulting state and decision
equality from independent copies of the same prior state. No warmup or genesis
is run. Even a harmless vendor-wide rebase is reported as an input difference in
this strict same-input rehearsal, not labeled an economic corruption. The
existing uniform-rebase equivalence policy is unchanged; it must be qualified
separately for new-format authority. Never repin a golden to resolve a difference.

## Invocation and result

With the existing database connection environment, run:

```text
python -m tools.sentinel_rolling_reader_compare --job-id UUID --observation-id NAME
```

The command prints a JSON report and rolls its read-only transaction back on
both success and failure. Success is `PRICE_READER_PARITY_PASS`, with
`operational_go: false`, candidate/snapshot identity, checkpoint record/state/
runtime-attestation identities, legacy publication and compared input/state/
decision hashes, plus the comparison process's source/environment identity.
Refusal exits nonzero. No table, cursor, authority, job, config,
automation route or broker is modified. This command does not deploy anything.

Remaining step-3 work: independently versioned reference/anchor readers and
dependency completeness, durable operational checkpoint admission/continuity,
versioned GO/status claims, migration and automation routing. The legacy
production path stays authoritative until those gates and NAS qualification pass.
