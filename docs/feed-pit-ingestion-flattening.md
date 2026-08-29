# Feed/PIT ingestion flattening

Base: `main` at `14bd93569c2d63bf62523c17757e538542c49742` (PR #282 merged).

This note records the Step 2 architecture before implementation. The refactor is behavior preserving: the same causal/source-authoritative rows must reach the same publication and downstream decision at the same simulated or real-world time.

## Current effective call graph

Production feed entry points resolve through public modules under `sentinel.feed`, but several of those modules copy implementation namespaces or mutate implementation modules so the function visible in source is not necessarily the function executed.

- `ingest.py` fronts `ingest_authority_impl.py`, which fronts `ingest_impl.py`.
  - `seed()` selects production snapshot authority, obtains a start-update boundary, takes the corpus writer lock, performs recovery, runs a source-stable seed/reseed, proves post-seed source/local coherence while the run is still unpublished, publishes, establishes the SEP mutation cursor, performs complete ACTIONS reconciliation, then proves the recent SEP frontier.
  - `daily()` requires an explicit through-session, performs failed-candidate recovery, refreshes current TICKERS authority before historical maintenance, runs the canonical daily generation, publishes it, then performs complete SEP rotation, SEP CDC, ACTIONS reconciliation, and the recent complete frontier proof.
- `publication.py` fronts `_publication_impl.py`. The public wrapper adds mandatory durable seed-coherence evidence before the retained publication transaction executes.
- `readiness.py` fronts `readiness_impl.py`. The public layer preserves the historical rolling checks and adds current-frontier domain coverage, split-disposition, SEP mutation-watermark, ACTIONS complete-authority, and recent complete reconciliation checks.
- `maintenance.py` fronts `maintenance_impl.py`, then routes SEP CDC through `source_authority.reconcile_sep_mutations` and substitutes the typed identity-refresh mutation validator.
- `staging.py` fronts `staging_impl.py` and adds a canonical `(ticker, session)` duplicate check before staged iteration.
- `sep_reconciliation.py` fronts `sep_reconciliation_impl.py` and binds every source fingerprint/reconciliation call to an explicit observation ceiling through `CanonicalSourceFetch`/`SepUpdateEnvelope`.
- `seed_coherence.py` fronts `_seed_coherence_impl.py` and adds durable exact source-coverage evidence plus strict publication-time proof validation.

## Runtime mutation mechanisms to remove

1. `publication.py`
   - copies `_publication_impl` names into `globals()`;
   - detects public monkeypatches, temporarily `setattr()`s the implementation module for a call, then restores it;
   - replaces `_publication_impl.publish` with the public wrapper at import time.
2. `maintenance.py`
   - assigns `maintenance_impl._validate_sep_mutation_rows` at import time;
   - copies the implementation namespace into `globals()`;
   - installs a custom `ModuleType.__setattr__` that propagates later public assignments into the implementation module.
3. `staging.py`
   - copies the implementation namespace into `globals()`;
   - installs a custom module class that propagates assignments into `staging_impl`.
4. `sep_reconciliation.py`
   - copies the implementation namespace into `globals()`;
   - replaces `sep_reconciliation_impl._source_fingerprint` and `reconcile_year` with guarded public wrappers;
   - installs a custom module class that propagates assignments into the implementation module.
5. `readiness.py`
   - copies the full `readiness_impl` namespace into `globals()`; effective behavior is split across copied symbols and public overrides.
6. `seed_coherence.py`
   - copies almost the full `_seed_coherence_impl` namespace into `globals()` and then overrides selected functions.
7. `ingest_authority_impl.py`
   - copies the `ingest_impl` namespace into `globals()`.
8. `ingest.py`
   - replaces `ingest_authority_impl.coherence` with a proxy object;
   - replaces `ingest_authority_impl._seed_source` at import time;
   - copies the authority namespace into `globals()`;
   - during production seed, temporarily replaces `store.IngestRun.__init__`, `store.IngestRun.finish`, `identity_rebuild.record_plan`, `identity_rebuild.publish_completed_run`, and `ingest_authority_impl._seed_source`;
   - after defining the public wrappers, assigns `seed`/`daily` into both ingest implementation modules;
   - installs a custom module class that propagates monkeypatch assignments into both hidden implementation modules.

These mechanisms make import order and monkeypatch location part of the production control path.

## Canonical ownership after flattening

- `sentinel.feed.ingest`: public seed/daily orchestration and PIT/source-authority chronology. Low-level row normalization/write helpers may remain in `ingest_impl` only as ordinary statically imported helpers until a later mechanical move; they carry no runtime override authority.
- `sentinel.feed.publication`: publication membrane, including seed-coherence binding. `_publication_impl` may remain only as a static lower-level transaction helper during this step; it may not be mutated by import or public monkeypatches.
- `sentinel.feed.readiness`: readiness authority and all current-frontier/source-maintenance additions. `readiness_impl` is a static historical-check helper only.
- `sentinel.feed.maintenance`: public maintenance authority. The typed SEP mutation validator is selected explicitly by the canonical call path.
- `sentinel.feed.staging`: staging API and canonical-key duplicate defense.
- `sentinel.feed.sep_reconciliation`: complete SEP reconciliation API and observation-ceiling authority.
- `sentinel.feed.seed_coherence`: durable post-seed proof API.
- `sentinel.feed.reseed`: full-reseed engine with explicit lifecycle callbacks needed by canonical ingest; no process-global replacement of `IngestRun` or identity-rebuild functions.

## Invariants that must remain unchanged

- Sharadar SEP/SFP/ACTIONS/TICKERS interpretation and price-domain semantics.
- Explicit daily through-session authority and no wall-clock fallback for production daily ingestion.
- Snapshot/source stability, canonical-key/cardinality checks, update-envelope bounds, source-finality and PIT chronology.
- TICKERS identity reconstruction and fail-closed `HistoricalIdentityMutation` handling.
- Split/corporate-action interpretation, anomaly evidence, share-count treatment and settlement inputs.
- Whole-duration corpus writer lock, publication advisory lock, publication transaction boundaries, atomic universe/action/anomaly projection, and rollback behavior.
- Seed proof occurs while the candidate is RUNNING and before ordinary `finish("success")`; identity-rebuild proof occurs before its atomic finalizer.
- A failed seed proof durably finishes the run FAILED and cannot publish or establish maintenance cursors.
- Publication remains version authority; unpublished rows remain invisible and coherence remains fail-closed.
- SEP mutation cursor and ACTIONS/recent reconciliation authority advance only after the publication they name exists.
- Readiness remains fail-closed on missing/stale current-frontier source authority.
- Retry/restart ordering and deterministic failed-candidate recovery remain unchanged.
- No strategy, Wealth Core, Sentinel, execution, accounting, ranking, sizing, share-count, price, cash, or allocation semantics change.

## Equivalence tests

The refactor must preserve existing financial/safety tests and add direct regressions for:

1. importing feed modules leaves peer/implementation module attributes unchanged;
2. importing the public feed modules in different orders produces identical callable identities/behavior;
3. seed and daily execute the canonical public functions visible in source;
4. an explicit public monkeypatch cannot silently mutate a hidden implementation path;
5. production daily still refuses an omitted through-session and retains PIT/source-envelope guards;
6. production seed proof is recorded before SUCCESS/publication and failure remains fail-closed;
7. identity-rebuild seed proof occurs before atomic identity publication;
8. historical identity mutation still escalates only through complete retained-history rebuild;
9. staging canonical-key duplicate refusal remains active;
10. complete SEP reconciliation remains bounded by the observation ceiling;
11. publication remains atomic and requires the durable seed-coherence proof when the run opted into that authority;
12. restart/retry recovery produces the same publication/cursor ordering.

No golden or economic fixture is repinned for this work.
