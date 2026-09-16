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

Retention is reference-driven, not a date cascade. This first boundary provides
no garbage-collection or production-cutover operation. Published generations,
reader pins, decision inputs, state checkpoints and restore retention must all
be accounted for before the later retention implementation can remove data.
No existing corpus, strategy state, command or historical record is deleted.

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
