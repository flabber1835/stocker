# Durable rolling cold start

The next [daily continuation boundary](rolling-daily-continuation.md) retains
this checkpoint as immutable origin and advances a separately versioned signed
checkpoint after each adjacent daily transition.

This boundary consumes #391's real DATA_ONLY publication and commits the first
canonical shadow state. It reuses `ShadowObserver`, its genesis/session format,
and the existing shadow cursor namespace. It creates no parallel portfolio,
paper catch-up cursor, execution plan or broker authority. Production GO and
daily advancement are connected by the separate
[rolling runtime](rolling-shadow-runtime.md), which earns its own post-commit
attestation rather than treating this candidate checkpoint as GO.

## Admission and transaction

Require both runtime schemas, the common Sentinel writer lock, backup authority,
the reviewed runtime/source/config identity, and the reviewed publication
subject. Match the acquisition request's strategy hash to the selected production
strategy. Pin the operational snapshot throughout input validation, canonical
feature warmup and first transition. Use explicit research capital, never broker
cash. Current metadata supplies prospective features only; do not fabricate a
historical witness or portfolio activity.

Inspect durable state before initialization. Any existing canonical book,
shadow observation/segment, rolling checkpoint, retained trial strategy evidence,
execution plan, command or fill
refuses fresh initialization, regardless of the requested observation name.
Unrelated setup, account binding and backup evidence are retained. No missing
table is interpreted as an empty table. The ordinary writer lock excludes the
existing runtime writers; the publication pin excludes concurrent feed writers.
Feed-owned operational publication tables are classified as feed relations by
the behavioral schema migration gate, allowing either installation order while
retaining each schema's own structural validation.

Add an explicit transaction-owned genesis option to the existing observation
store; its default immediate-commit behavior stays unchanged. The rolling path
commits genesis, first session and a signed checkpoint together. Recheck source
finality, the following official XNYS opening deadline and backup authority just
before the final write/commit. A failed transition/write leaves no partial seed.
An uncertain commit acknowledgement is recovered by inspecting the checkpoint.

The observation contract requires consecutive publication versions. Allocate
rolling versions from the preceding committed version under the existing
exclusive corpus lock, rather than consuming a nontransactional sequence value
that a failed publication cannot return. Ordinary legacy publication is already
fenced once a rolling version is active. This preserves contiguous committed
versions after an interrupted first publication.

## Checkpoint claim

Use a new, explicitly versioned `COLD_START_COMMITTED` checkpoint in the existing
namespaced JSON cursor store. Bind observation id, capital, complete strategy and
runtime identity, publication/snapshot, genesis hash, first session record/hash,
exact canonical decision inputs, warmup economic identity, pre-open timing and
transaction-specific PITR evidence. The clock evidence is explicitly precommit;
it does not claim the post-commit timing attestation required for SHADOW_GO.
Authenticate the complete checkpoint using
the configured publication receipt secret with a distinct purpose/schema.
This is an integrity checkpoint, not a GO or execution certificate. The existing
observation row remains `CANDIDATE`/`NOT_DEPLOYABLE`; no legacy `VERIFIED` claim
is broadened. The current receipt key remains required after restore, just as
for publication receipts; losing/rotating it does not silently re-sign evidence.

Restart validates the signature, the exact stored genesis/session and canonical
state, strategy/runtime identity and original signed publication. An explicitly
read-only repeatable-read transaction keeps these facts consistent. It reads a
fixed three-row checkpoint closure and the existing publication receipt chain;
it does not reload original price rows, re-warm features or rerun the first
transition. It refuses missing or additional lineage and never repairs it by
creating a new genesis. Return the original state even if the clock has passed
the first execution open; that historical integrity result grants no new order.

Future continuation must extend this checkpoint contract with current-window
overlap and live-dependency admission. This slice does not claim current data
readiness after refresh, multi-session catch-up, long-lived-book continuity,
paper activation or an observed NAS GO. No retention deletion is introduced.

## Verification

Real PostgreSQL tests cover source-to-publication-to-canonical-state cold start,
unspent cash/pending initial instructions, explicit capital/identity binding,
partial-state refusal, concurrent writer exclusion, rollback after genesis and
session writes, lost acknowledgement, restart without source/warmup access,
checkpoint/state/input tampering, cutoff expiry and backup refusal. Remove the
new guards and prove that the corresponding behavioral tests fail.
