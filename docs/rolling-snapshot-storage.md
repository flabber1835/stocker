# Rolling snapshot storage contract

Implementation of the first storage boundary in
[feature #384](https://github.com/flabber1835/stocker/issues/384), following
[the rolling snapshot design](rolling-operational-snapshots-design.md).

## Ownership and admission

Use logged PostgreSQL tables for private candidates, sealed price generations,
and content-addressed reference/input bundles. A candidate id is a UUID; its
content identity is assigned only after independently reading its persisted
contents in canonical key order. Storage does not add acquisition time, job id
or publication version to that identity. Provider adapters must supply stable
source evidence separately from incidental observation timestamps; changing
only an observation time must not manufacture changed economics.

The storage boundary accepts normalized canonical bars, not raw vendor rows.
Normalization, independent universe/absence evidence, source finality and
economic continuity remain publisher responsibilities. Storage sealing proves
only the exact XNYS axis, duplicate rejection, typed price domains, complete
SPY/BIL observations and correspondence with an independently supplied expected
key set. It does **not** grant READY, SHADOW_GO, VERIFIED or execution authority.
The direct publisher must earn those other facts before attaching a generation
to the ordinary publication transaction. Legacy readers and writers remain
authoritative until that integration is qualified.

The fixed axis has exactly 300 XNYS sessions, including its end session. The
aggregate selected-strategy requirement includes its 260-session restart tail,
254-session SPY tail and an action predecessor, within the same cap. A durable
cursor before the available interval is a named missing-dependency refusal;
storage never fetches more history or initializes another book.

## Transaction and retention rules

### Large reference representation

The NAS exhausted its PostgreSQL container's 1 GiB memory budget while inserting
the complete reference bundle into JSONB (2026-10-01). Export streaming alone
does not bound PostgreSQL's expansion of a large nested JSON document.

Evidence larger than 1 MiB of canonical UTF-8 JSON is stored in a nullable TEXT
column, `canonical_payload`, instead of the JSONB `payload`. Smaller evidence
keeps its existing representation. The logical SHA-256, exact input contents,
reader result and publication identities do not change. Legacy JSONB rows remain
readable; installing the additive column does not rewrite existing evidence.
At most one representation may be present. Both NULL means retired, as the
existing NULL payload did. Canonical documents over 256 MiB are refused before
database insertion with the existing acquisition resource-limit classification;
this does not authorize truncation, partial publication or a larger memory cap.

Readers decode TEXT in the Python process and verify the canonical content hash.
The database never casts large TEXT back to JSONB, including restoration.
Restoration verifies the TEXT bytes against the immutable evidence identity in
the database. Existing JSONB restoration retains its exact-byte/hash check.
Ordinary updates and deletion remain prohibited. Retirement clears both payload
columns only under the existing ownership and dependency guards; candidate
admission checks both representations. No storage helper commits its caller's
transaction. This applies to GO and recurring acquisition alike.

Validation must cover legacy and large round trips, duplicate insertion,
rollback, digest mismatch, direct SQL mutation, retirement/restoration and
candidate admission. A separate local PostgreSQL container with a 1 GiB memory
limit must exercise a large nested reference document through this production
storage path. That witness measures database resource behavior, not NAS latency
or economic performance. The evidence-size boundary must have a falsifier.

Local witness (PostgreSQL 16.13):
`python -m tools.acquisition_resources.evidence_probe --database-url
postgresql://postgres@127.0.0.1/evidence_witness --mebibytes 240` completed storage,
readback and retirement/restoration of 1,677,721 nested synthetic records
(251,658,226 canonical bytes) in 37.03 seconds. The server ran separately with
Docker `--memory 1g --memory-swap 2g`; the Python client had a separate 3 GiB
limit. The server recorded zero OOM events/kills and no container restart. This
was not a zero-pressure test: memory reached the 1 GiB cgroup limit and measured
peak swap across two runs was 27,951,104 bytes. The probe requires an empty
disposable database and is not part of GO or an automatic CI workload.

Every row belongs to one candidate. Batches can commit while the candidate is
private. Sealing locks its parent row; every row insert takes the same parent
lock and refuses a sealed parent. Sealed rows and manifests cannot be updated
or deleted by ordinary SQL, including TRUNCATE. Database triggers enforce this
as well as Python. A new parent cannot be inserted already sealed.
Thus a concurrent late batch cannot change a sealed digest.

Reference bundles have a separate content identity and contain their exact
canonical payload, including identity/action/basis evidence supplied by the
publisher. They are not filtered to the price dates. Missing bundles refuse;
foreign keys prevent orphaned generation references. New decision-input
bundles can use the same immutable evidence store. A hash is integrity evidence,
not evidence of source completeness or backup/restore coverage.

The storage API never commits a caller's transaction. Callers explicitly commit
private batches and atomically commit a seal with its verification evidence.
Errors require rollback. No network calls occur in storage operations.

Readers name an explicit sealed candidate and stream typed rows in canonical
order. A newer candidate cannot change that read. `verify_content` recomputes
every retained payload/key digest for comparison or restore verification; it
does not treat a valid manifest hash as proof that the payload survived. This
full scan is an explicit integrity operation, not a recurring startup gate.

Retention is reference-driven, not a date cascade. The integrated
[history and retirement contract](rolling-history-retention.md) now supplies
guarded bulk-payload retirement, shared reader pins, checkpoint/job dependencies,
and retained action evidence. Manifests, decisions, commands and failed-attempt
records remain immutable. A retired manifest authenticates historical identity;
it does not promise that its complete price payload remains readable.

## Verification scope

The new policy identifier is `sentinel.operational-verification/1`. Its explicit
scope is `CURRENT_WINDOW_AND_LIVE_DEPENDENCIES`; it cannot be interpreted as
legacy all-history verification. It binds the exact window, snapshot, reference
bundle, strategy identity, checkpoint and durable cursor. A scope descriptor
does not admit a checkpoint: the runtime must separately prove its recognized
committed origin, state hash, restart image and live obligations before use.

Historical replay availability is reported separately. Missing unrelated old
prices cannot be relabeled as broken current input, and missing live evidence
cannot be relabeled as optional historical replay. No legacy verdict is
automatically upgraded by installing these tables.

## Acceptance

Tests use real PostgreSQL for batch/seal rollback, duplicate and off-window
rejection, late writes after sealing, content identity, missing benchmarks,
independent expected-key mismatches and missing reference evidence. Calendar
tests include a holiday and a missing middle session. Guard-removal falsifiers
must fail. The publisher/loader cutover still requires the comparison, restore,
concurrency and NAS performance gates in the parent design.
