# Rolling operational snapshots: dependency audit

Status: design-only investigation; no runtime changes or deployment authority.
Tracking: [feature #384](https://github.com/flabber1835/stocker/issues/384).
Audited base: `4417bd6523fb1a3b2bd53dc70f77214cbe7635ae` on
`flabber1835/stocker:main`. Findings describe that revision, not the NAS's
unobserved current state. The [proposed design](rolling-operational-snapshots-design.md)
defines the replacement and its review gates. Related vendor migration:
[feature #376](https://github.com/flabber1835/stocker/issues/376).

## Executive finding

The current system already bounds operational SEP acquisition to 300 XNYS
sessions. It does not yet publish each daily acquisition as an independent,
complete rolling snapshot. Daily mutation reconciliation can fall back into
seed capture, identity reconstruction and database replay. Reducing the download
date range again would not remove that path.

A direct snapshot publisher can remove operational daily-diff reconstruction and
its fallback reseed. It cannot remove acquisition latency, complete-set checks,
normalization, database writes, immutable strategy state, or corporate-action
semantics. The proposed change is a cross-module publication and verification
refactor, not a date-filter change.

**300 sessions is the replaceable operational price surface, not the entire
database.** Durable strategy/execution state, identity and basis anchors, and
existing decision records have longer lifetimes. An empty
feed is not the same as an empty trading system.

The unbounded historical checks below are dependencies of the **current code**,
not inherent requirements of a trading system. The proposed operational gate
checks the current window, durable state and live dependencies. Historical
reconstruction is optional investigation, not a daily prerequisite.

## Evidence and limits

The user-supplied NAS trace reported 765,364 SEP rows for July-December 2025 and
1,094,203 for January-September 2026, approximately 1.86 million rows in the
bounded interval. It later reported database ACTIONS processing around 5,047
seconds into preparation. A separate PostgreSQL sample showed an ACTIONS
observation insert waiting on `IO/DataFileRead` with no listed blockers.

These observations establish long processing after acquisition and an I/O wait
at that instant. They do not establish a complete performance profile, an ETA,
database corruption, or that all replay messages are new network downloads.
The generic `LOCAL_PUBLICATIONRECOVERYREFUSED` fallback label loses the specific
failed invariant; the underlying cause must be retained in future diagnostics.

## Dependency inventory

Paths and symbols below are implementation evidence. "Replace" means a proposed
implementation change after design review, not removal in this PR.

| Dependency / evidence | Current behavior | Proposed disposition |
| --- | --- | --- |
| [operational_source.py](../sentinel/feed/operational_source.py), `MAX_PRICE_SESSIONS`, acquisition | Limits prices to 300 sessions; captures into indexed temporary SQLite; supplies subsequent local replays. | Keep bounded acquisition and source evidence; replace nested capture/replay plumbing with a single candidate import boundary. |
| [outage_recovery.py](../sentinel/feed/outage_recovery.py), `catch_up`, `_catch_up` | Initial/expired feed seeds; otherwise daily processing can refuse and select bounded seed. | Replace feed repair dispatch with complete snapshot preparation. Strategy missed-session catch-up remains separate. |
| [ingest.py](../sentinel/feed/ingest.py) | Daily mutation and seed entry points share canonical publication machinery. | Route operational startup, daily preparation and feed repair to one snapshot publisher. Preserve safety semantics, not the old control flow. |
| [seed_capture.py](../sentinel/feed/seed_capture.py), `run_generation`, `CapturedRows` | Captures TICKERS, ACTIONS and year-chunked SEP; materializes rows before database replay. | Remove from automatic operational routing after equivalent direct-load proofs exist. |
| [coherence.py](../sentinel/feed/coherence.py), `StableSharadarFetch`; [source_authority/fetch.py](../sentinel/feed/source_authority/fetch.py) | Coverage, identity and negative-space validation can spool and replay rows again. | Keep complete-set and identity invariants; consolidate materialization. A local replay is not necessarily another vendor fetch. |
| [reseed.py](../sentinel/feed/reseed.py), `full_reseed_locked` | Reconstructs seed database state, including actions and identity dependencies. | Remove as normal daily/recovery implementation. Historical maintenance cannot silently become an operational fallback. |
| [snapshot_export.py](../sentinel/feed/snapshot_export.py); [snapshot_source.py](../sentinel/feed/snapshot_source.py) | Async export metadata, cache and generation checks; TICKERS JSON preserves distinctions lost in CSV. | Reuse proven adapter behavior. A checksum proves local bytes, not vendor-wide atomicity. |
| [actions_reconcile_v7.py](../sentinel/feed/actions_reconcile_v7.py); [actions.py](../sentinel/feed/actions.py) | Action observation identities, revisions and publish/abort lifecycle. | Replace repeated observational rebuild for a complete candidate; retain exact action keys, precision, lifecycle and economic adjudication. |
| [operational_coherence.py](../sentinel/feed/operational_coherence.py), `production_dependencies` | Closure includes window securities, durable state, plans/commands, aliases and related identities. | Preserve closure. Neither current broker holdings nor currently active tickers alone define the input universe. |
| [publication.py](../sentinel/feed/publication.py), `current`, `pinned`, `publish` | Versioned visibility, shared reader pin and exclusive writer coordination. | Keep atomic visibility; add immutable generation storage, short publication switch and reference-aware retention. Existing publication versions alone are not a complete old-row archive. |
| [core/loader.py](../sentinel/core/loader.py), `load_window`, metadata/sector loaders | Loads published prices and dated identity/sector evidence. | Require explicit snapshot/evidence identity throughout loaders; no implicit latest-view joins. |
| [core/production.py](../sentinel/core/production.py), `load_published_session` | Loads SPY/BIL, actions, metadata and split anchors; returning securities can require prices preceding the current window. | Persist canonical basis anchors and exact dependency references before eviction. Do not reset the split basis at each rolling boundary. |
| [core/terminal.py](../sentinel/core/terminal.py), `terminal_from_action`; [core/spinoffs.py](../sentinel/core/spinoffs.py) | Terminal and spinoff economics depend on source terms, counterparties and prices, not only daily bars. | Isolate vendor translation behind typed canonical inputs, preserve deterministic engine semantics. |
| [core/history.py](../sentinel/core/history.py), `require_history_compatible`; [feed/history_mutations.py](../sentinel/feed/history_mutations.py) | Rejects incompatible prior-history revisions and incomplete publication proofs. | Retain fail-closed economic continuity; version and review the new bounded revision-evidence contract. |
| [shadow_runtime.py](../sentinel/shadow_runtime.py), `_load_warmup_material`, `_warmup_loader` | Reloads the observer's original warmup, which moves outside a daily rolling window as the observer ages. | Replace routine genesis reload with a validated durable state checkpoint and current restart inputs. Old genesis replay belongs to investigation/certification. |
| [shadow_observation.py](../sentinel/shadow_observation.py), `_require_current_warmup_input`, `_require_committed_economic_inputs`, `durable_status` | Rechecks original warmup and committed sessions against the current corpus, not just the last 300 sessions. | Remove unbounded historical rereads from routine GO/status. Preserve current-window/live-dependency checks and incremental state integrity. Version the changed claim explicitly. |
| [identity.py](../sentinel/identity.py) | Economic/source identities bind semantics. | Version provider normalization and verification policy; qualify changes instead of relabeling existing evidence. |
| [automation/service.py](../sentinel/automation/service.py); [shadow_worker.py](../sentinel/shadow_worker.py) | Callback, worker and retry lifetimes interact with lengthy source preparation. | Durable resumable jobs, explicit deadlines and single-writer ownership; no retry loop that repeatedly discards completed acquisition. |

## Session budget and state beyond it

The selected strategy, not an assumed round number, must define the requirement.

| Input | Evidence at audited base | Implication |
| --- | --- | --- |
| Basic equity feature minimum | [requirements.py](../sentinel/feed/requirements.py) documents the engine-owned 127-close minimum; operational coherence imports the engine requirement. | A bare 127-close minimum is not the complete selected-strategy startup contract. |
| Preferred feature warmup | `PREFERRED_SESSIONS = 252`; [production-compact-champion.md](production-compact-champion.md). | Preserve selected Median-5 feature construction. |
| Median-5 persisted feed tail | `_warm_median5` sets `restart_sessions = 260`; [session.py](../sentinel/core/session.py) validates 260 for this state. | Audit restart as well as initial warmup. |
| SPY | Generic readiness minimum 41; Median-5 warmup retains a 254-entry SPY history. | A 41-session readiness check alone does not prove the selected strategy's needs. |
| Boundary predecessor | `ACTION_BOUNDARY_PREDECESSORS = 1` in operational coherence. | Count predecessor requirements inside the 300-session acquisition cap; prove selected-strategy sufficiency with tests. |
| Existing portfolio / controller | Persisted positions, peaks, reviews, pending actions, breadth/controller state and ledger. | Never regenerate the book from the latest price window. |
| Missed-session cursor | `operational_boundary` extends requirements to the durable cursor and predecessor. | Arbitrarily long outages are not solved by 300 prices. Exact archived inputs or explicit reviewed recovery are required. |
| Observer genesis and committed inputs | Original warmup plus all prior session commitments in shadow verification. | Preserve existing records; remove this unbounded reader from the operational gate. Exact payloads are necessary for historical replay, not for every next-session decision. |
| Returning securities and unresolved actions | Prior split factors, terminal/spinoff terms and identity linkage. | Retain dependency anchors beyond 300 sessions; do not filter every table by price dates. |

The bounded constants fit within 300 individually; this is not an exhaustive
proof of every combined predecessor/catch-up path. Implementation acceptance
requires an executable aggregate requirement for the selected strategy and
explicit refusal when its causal closure exceeds available evidence.

## Why ACTIONS currently starts at 1900

`seed_capture.py` deliberately requests ACTIONS from `1900-01-01` through the
target. It is a lower-bound sentinel for full reference history, not a millennium
bug or evidence that SEP prices are also downloaded from 1900. Old events can
establish identities, split basis, terminal obligations or counterparties that
remain relevant today.

The replacement must separate a reusable, versioned reference/anchor generation
from the rolling price generation. It must not assume every old action is needed
daily, nor assume every old action is irrelevant. Sharadar's ability to provide
a complete bounded dependency projection without full reference enumeration is
not proved by this audit. Initial reference acquisition and some reference
refreshes may remain broader than 300 sessions. The implementation must measure
and disclose that residual cost instead of hiding it behind "300-session load."

## Provider portability gaps

The existing adapter boundary is useful, but source semantics still reach core
terminal conversion and eligibility. A normalized bar schema alone is not a
replacement contract.

[eligibility.py](../shared/stock_strategy_shared/wealth_core/eligibility.py)
admits categories containing `Common Stock`, excluding warrants/preferreds;
this includes ADR common-stock categories. Issuer grouping uses permanent
identities and related tickers. Sector inputs and dated metadata also affect
economics. Substituting "Alpaca tradable equities" would change the strategy.

Alpaca's [bars endpoint](https://docs.alpaca.markets/us/reference/stockbars)
supports dated, paginated multi-symbol acquisition and explicit adjustments.
Pages are capped across all symbols, so every continuation token must be read.
Its `asof` parameter resolves symbol identity; it is not a historical data-vintage
lock. The documentation does not establish an immutable revision shared across
all pages. SIP and IEX are distinct coverage choices, not interchangeable inputs.

The documented [Assets filters](https://docs.alpaca.markets/us/reference/get-v2-assets-1)
do not provide an exact common-stock/ADR/issuer/sector contract. Therefore an
Alpaca-only universe equivalent to this strategy is **not established**. A future
adapter must prove classification, identity continuity, corporate actions and
economics, or name an additional reference provider and explicitly stop calling
the result Alpaca-only. No name-suffix heuristics or silent exclusions.

Nasdaq documents an [asynchronous exporter](https://docs.data.nasdaq.com/docs/in-depth-usage-1):
`creating` describes a file being generated; `regenerating` describes replacement
of an older available file. This does not by itself mean underlying financial
data is changing. File creation time and table refresh time are different facts.
Polling file readiness is appropriate; two entire downloads are not an atomicity
proof. Current adapter consistency safeguards must be preserved or replaced by
an explicitly reviewed evidence contract.

## Conclusions for design review

1. Use one complete rolling-snapshot preparation path for startup, daily refresh
   and feed repair; do not reconstruct that window from daily mutations.
2. Preserve path-dependent strategy state and decision records separately from
   the replaceable active price surface. Do not create a new mandatory historical
   archive reconstruction before the system can trade.
3. Explicitly change and version old-history verification semantics. Keeping
   only 300 sessions while claiming unchanged whole-history vendor verification
   would be false.
4. Persist identity/action/basis anchors before deleting any old input. No
   production database wipe is authorized or necessary for this design PR.
5. Keep Sharadar first. Make a future Alpaca adapter possible without claiming
   its universe, corporate actions or snapshot guarantees are already sufficient.
6. Benchmark real NAS acquisition, staging, validation and archival costs.
   Direct snapshots simplify control flow; daily full-window bandwidth and WAL
   can exceed a successful small top-up. No guaranteed runtime reduction yet.
