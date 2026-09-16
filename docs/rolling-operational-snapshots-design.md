# Atomic rolling operational snapshots

Status: **IMPLEMENTATION IN PROGRESS**. The additive private generation storage
and versioned scope descriptor are specified in
[rolling-snapshot-storage.md](rolling-snapshot-storage.md). Fenced preparation
jobs and immutable source-completion checkpoints are specified in
[rolling-snapshot-jobs.md](rolling-snapshot-jobs.md). The direct publisher,
reader/checkpoint cutover and retention are not yet implemented. Installing the
storage does not switch running services, verification verdicts, strategy,
provider selection or deployment authority. Sharadar remains the production
source; execution remains paper-only under the existing contract.

Base: `4417bd6523fb1a3b2bd53dc70f77214cbe7635ae`.
Tracking: [feature #384](https://github.com/flabber1835/stocker/issues/384).
Read the [dependency audit](rolling-operational-snapshots-audit.md) first.
Related: [Alpaca migration feature #376](https://github.com/flabber1835/stocker/issues/376).
Current operational authority remains [deployment](sentinel-deployment.md),
[bounded acquisition](bounded-operational-feed.md),
[execution contract](sentinel-execution-contract.md),
[compact champion](production-compact-champion.md), and
[production/certification separation](production-certification-separation.md).
Implementation PRs must update those contracts before changing behavior.

## 1. Decision and scope

Each daily preparation acquires a complete view of the most recent **300 XNYS
sessions**, ending at one fixed source-final session. It validates a private
candidate and atomically publishes it. Cold feed initialization and feed repair
use this same path. No operational daily-diff reconstruction, seed fallback or
automatic multi-year SEP fetch remains after cutover.

"Complete" means all expected observations for the independently established
universe and its causal dependencies, including SPY/BIL and action counterparties.
It does not mean 300 rows per IPO, delisted security or legitimately absent bar.
Expected absence needs evidence; unexplained disappearance is a refusal.
300 is a session count, not calendar days or a per-symbol API result limit.

Keep the canonical Wealth Core transition and its immutable shadow book.
Sentinel still controls exposure, not holdings. Market-data adapters cannot
read account, fill, order or realized-exposure state. If a future adapter uses
an Alpaca-hosted reference endpoint, it is a narrowly scoped market/reference
capability; all account and order access remains in execution. Broker actions
may inform execution reconciliation, never substitute for shadow-book action
inputs. This constrains any broader wording in feature #376.

Rejected alternatives: blindly truncate every table to 300 sessions; rebuild
the portfolio daily; accept unvalidated vendor data as ground truth; download
the full window twice and equate equality with atomicity; keep seed recovery
as a hidden fallback; migrate to Alpaca before its capabilities are proved.

## 2. Four separately owned data lifetimes

| Surface | Owner and lifetime | Rules |
| --- | --- | --- |
| Operational price snapshot | Feed; complete 300-session generation | Replaceable active view. No updates to a published generation's contents. |
| Reference and basis evidence | Feed identity/action layer; dependency-driven retention | Versioned security identities, aliases, issuer/sector/classification evidence, unresolved actions, counterparties and canonical split anchors. Not capped by price dates. |
| Decision records and input evidence | Existing durable evidence/backup system; dependency and existing retention policy | Preserve immutable decisions, input identities and available payloads. Record exact new canonical decision inputs as part of the durable commit. Historical replay uses available archives separately; reconstructing every legacy input is not a trading prerequisite. |
| Strategy and execution state | Existing owners; existing immutable/recoverable lifetimes | Positions, peaks, cursors, pending actions, controller history, commands and broker reconciliation are never replaced by a price refresh. |

Use additive generation-keyed PostgreSQL storage as the initial design, reusing
existing storage, backup and publication infrastructure. No new microservice or
parallel portfolio engine. Unchanged reference generations may be reused when
their freshness and completeness evidence remains valid. Exact committed input
bundles may reference retained immutable rows rather than copying identical
payloads; deduplication must not weaken restore independence. Restoring current
state and live dependencies is mandatory. Reproducing every historical decision
from genesis is a separate capability, not an operational startup gate.

Daily full-window generations introduce disk, index and WAL cost. Unreferenced
superseded price generations are collectible only after reader pins, candidate
jobs, decision references and restore retention permit it. Do not retain every
overlapping 300-session generation forever by accident. Do not collect action
anchors, certificates or commands by a simple date cascade.

## 3. Typed provider contract

Evolve the existing source adapter boundary using typed/Pydantic schemas, not a
generic plugin framework. A provider supplies:

- Universe evidence: dated canonical security mapping, listing/type eligibility,
  issuer grouping, sectors, aliases, known gaps and provenance.
- Bars: canonical security and session, raw OHLCV and explicitly identified
  signal-price/adjustment inputs, preserving numeric precision and price domains.
- Economic events: stable action identities, revision/removal evidence, precise
  splits, cash distributions, terminal/spinoff terms and counterparties.
- Basis anchors: the proven predecessor and accumulated basis needed at the
  window boundary or for returning securities; no implicit factor of one.
- Acquisition manifest: component identities, filters, coverage, row counts,
  checksums, observation times, source-final target, adapter/schema/calendar and
  normalization versions, plus the actual vendor consistency evidence.
- Capabilities: explicit availability of each required semantic field and
  consistency guarantee; an unsupported requirement refuses, never defaults.

Keep existing canonical permanent identities during migration. Do not replace
them with ticker strings or Alpaca asset UUIDs. A future provider mapping proves
dated identity intervals, reused symbols and share-class/issuer relationships.
Business issuer identity is not automatically a share-class identifier.

Sharadar normalization remains first. Move source-specific translation such as
terminal ACTIONS value interpretation behind this boundary only with exact
canonical-output/economic equivalence tests. Do not change strategy eligibility
or price-domain semantics to make an adapter fit.

For Sharadar, broader reference enumeration can still be needed to establish
complete identity/action evidence. Reuse or refresh a separate validated
reference generation; do not rebuild all action observations per price refresh.
Until a bounded reference projection is proved, disclose full-reference fetches
as such. This design guarantees bounded operational **price** acquisition, not
that every input is 300 sessions old or newer.

## 4. Acquisition and publication protocol

1. Resolve the source-final target using the exchange calendar/publication
   policy. Freeze the exact 300-session axis, request identity, strategy
   requirements, prior publication and referenced durable cursor. Refuse an
   unsupported dependency interval before a large download.
2. Establish provider capabilities and source readiness. A pending export is a
   wait state with a next poll and absolute deadline, not evidence of corruption.
   Persist the job so resuming does not restart every completed component.
3. Capture each required price component once for the attempt. Requests may be
   paginated or partitioned; "once" does not mean one HTTP call. Resume verified
   artifacts only when their request and generation evidence still match.
4. Stream into private generation-keyed staging using bounded batches and bulk
   loading. Keep raw capture checksums and canonicalization evidence. Avoid the
   current nested SQLite/pickle/seed capture pipeline and per-row observational
   reconstruction. Validation may scan staged data more than once.
5. Validate schema/types, uniqueness, exact session axis, independent universe
   coverage/negative space, identity continuity, price domains, actions, basis
   anchors and reference freshness. Compare overlapping economic inputs with
   committed evidence to classify corrections. Complete-set comparison is not
   reconstruction from daily diffs.
6. Seal the candidate manifest and archive references. All referenced evidence
   must be durable and satisfy existing WAL/restore authority before dependent
   state can be declared valid. A valid local hash alone is not backup proof.
7. Acquire the short publication lock; compare-and-swap the expected prior
   generation and recheck frontier/cursor/reference dependencies. A changed
   prerequisite invalidates READY and requires revalidation. Switch the active
   pointer and record publication identity atomically. No network call under
   this lock. Failed candidates remain invisible.
8. Readers resolve and pin a generation for their entire transaction. Every bar,
   metadata, event, benchmark and proof join must use that identity. Retain old
   pinned generations until readers release them; preserve lock ordering.
9. Advance missing strategy sessions using the real prior state and pinned exact
   inputs, committing state/cursor atomically. Emit only the current execution
   plan. Publish cleanup progress separately; cleanup cannot alter past inputs.

Distinguish a content-addressed snapshot ID, a monotonic publication version and
a resumable request/job ID. Identical canonical data and provenance is an
idempotent publication, not a second economic transition. A changed observation
timestamp alone must not manufacture changed economics. Older targets cannot
overwrite a newer active frontier. Concurrent candidate jobs cannot both win
against the same prior version.

Acquisition bytes become immutable local evidence, but this does not manufacture
vendor-wide atomicity. Preserve Sharadar partition generation and cross-component
compatibility checks, including JSON/CSV TICKERS distinctions. Record the exact
strength of each component's evidence. A provider without a documented immutable
revision must not be labeled revision-pinned. A weaker consistency mode requires
separate reviewed qualification; it is not activated in this design PR.

## 5. Operational verification, not a historical oracle

The trading system does not need to prove all historical vendor prices every
day. Current shadow verification imposes that dependency by rereading original
warmup and committed sessions against the current corpus. Remove that dependency
from routine startup, daily refresh and status checks. Do not replace it with an
equally unbounded local archive scan.

The recommended versioned operational gate has three responsibilities:

- **State continuity:** validate the durable checkpoint, its identity/hash,
  cursor, required restart state, basis anchors and live obligations; validate
  subsequent commits incrementally from the trusted checkpoint. A trusted
  checkpoint is an already validated, durably committed state under a recognized
  contract, not a new hash attached to arbitrary database rows.
- **Current inputs:** validate the complete rolling window and relevant
  longer-lived reference facts. Compare overlapping committed economic inputs
  within this closure, not all sessions since genesis. Record the checked scope.
- **Recoverability:** ensure current state, commands and required input evidence
  have valid backup/restore coverage under the existing safety contract.

Keep existing historical decision records unchanged. Write the canonical inputs
for new decisions with their durable evidence so future investigation is useful,
but do not require a retrospective backfill of every legacy price to start
trading. Historical replay and all-history vendor restatement audits are optional
investigation/certification activities, explicitly outside daily GO. Their
unavailability alone must not block an otherwise sound current state and input
window. Missing evidence required by a live dependency still blocks.

Retain incompatible-history refusal within the revalidated closure. Existing
economic equivalence rules may accept a proven uniform adjustment rebase;
changed returns, raw economics, volume, identity or event meaning may not be
silently accepted. Observed corrections outside the price window that affect a
live dependency still block. Missing evidence is UNKNOWN, not equivalent.

A correction affecting an already committed path cannot be repaired by replaying
the portfolio from today's window or by editing old decisions. It requires an
explicit reviewed continuity/recovery decision. A longer historical restatement
audit belongs to certification, not an automatic daily full-corpus fetch.

This intentionally narrows the operational verification scope while retaining
state integrity and existing records. Before implementation can authorize GO,
reviewers must
accept and version this claim in the shadow/execution/certification contracts,
identity fingerprints and report schemas. Legacy `VERIFIED` cannot be silently
reused as if its meaning were unchanged. If that policy change is rejected, a
strict 300-session-only current-source design is not feasible under the old
whole-history revalidation contract.

## 6. Cold start, outages and revisions

- Empty feed and no prior book: prepare the window, perform feature-only warmup
  under the selected strategy's aggregate requirement, then create prospective
  state. Do not invent historical point-in-time metadata or past holdings.
- Lost feed but intact durable state: restore its exact archived dependencies,
  acquire the current window and prove continuity before catch-up. Never treat
  this as a fresh portfolio.
- Short outage: process every missed session in order with appropriate dated
  evidence. Do not replay missed broker orders; reconciliation emits only the
  newest plan under existing execution rules.
- Cursor older than available window: use exact available archived inputs where
  the continuity contract permits; otherwise refuse with missing dates and
  dependencies. No automatic 20-year fetch or cursor jump. Explicit operator
  recovery is a separate reviewed path, not a hidden fallback.
- Corruption of required state/evidence, ambiguous identity or revised live action:
  refuse with the exact dependency. A healthy Alpaca account does not override
  financial input
  failure. No book reset or autonomous liquidation is authorized.

## 7. Asynchronous failure and progress contract

Persist job states `ACQUIRING`, `WAIT_SOURCE`, `STAGING`, `VALIDATING`, `READY`,
`PUBLISHED`, `RETRY_WAIT`, `INTERRUPTED`, `REFUSED` and `ABORTED`, with attempt,
owner lease, reason and stage. Only durable checkpoints are resumable. Crashes
mid-download/load/publish cannot expose partial data or falsely mark completion.
Cancellation must stop owned children, release resources and preserve the last
published generation. Reclaim abandoned candidates only after lease/pin checks.

Use one end-to-end budget plus explicit stage deadlines, monotonic elapsed time
within a process and persisted absolute deadlines across restarts. Fit callback
lifetimes by resuming a durable job, not nesting longer waits inside a shorter
callback. Reboots, clock skew, midnight, new source refreshes, expired URLs,
429/Retry-After and worker cancellation are tested paths. Freeze the target
during an attempt; schedule a later target separately. Coalesce duplicate daily
wakes and prevent overlapping writers. Source-generation changes invalidate
affected checkpoints explicitly; retries must not quietly mix generations.

Required human-readable and structured status fields:

- Actual active phase/subphase, target window, provider/table/partition, job ID.
- Rows and bytes processed, total only when known, phase and job elapsed time,
  last meaningful progress time; never call a repeated heartbeat progress.
- Wait category: vendor generation, network/backoff, database lock/I/O, CPU
  validation, certificate publication, or uninstrumented child. Report unknown
  honestly; database wait causes require actual telemetry.
- Attempt/budget/deadline/next retry, recoverability and required operator action.
- Specific safe diagnostic detail, not just a class name or a hash. Never expose
  credentials, signed download URLs, account identifiers or raw private inputs.

For example, use this shape with measured values, not fabricated percentages:

```text
WAIT source export SEP 2026-01-01..2026-01-31: creating; poll in 10s; deadline in 240s
LOAD candidate prices: 700,000/1,859,567 rows; phase 42s; target 300 XNYS sessions
VALIDATE identity coverage: 8,200 securities checked; total unknown; phase 19s
REFUSED action identity: required counterparty unresolved; candidate not published
SKIPPED readiness: financial preparation refused; reason ACTION_IDENTITY_UNRESOLVED
```

A completed substage must transition immediately to the next measured stage;
do not repeat `source replay ... completed` as a claim about ongoing work.
Wrapping bash is insufficient: instrument the owned child or name the actual
command purpose and state that progress is unavailable. Emit a diagnostic when
the stage-specific no-progress budget expires; never an invented ETA.

Dependent GO phases skip immediately on terminal preparation refusal. Any
independent diagnostic that continues is labeled diagnostic-only, not recovery.
Recoverable waits retain a pending/retrying state until success or exhaustion.
CI certificate publication is its own prerequisite with its own wait/deadline;
do not present missing publication as fourteen independently failed DB checks.
Reuse [operator monitoring](sentinel-operator-monitoring.md): amber requires
durable bounded recovery evidence; unknown or exhausted required facts are red.

## 8. Migration and rollback

1. Inventory the NAS's exact schema, visible publication, unresolved candidates,
   durable cursors, original warmup and committed evidence availability. Take and
   verify a restore-capable backup. This design PR performs none of those actions.
2. Add generation storage, archive references and version-dispatched loaders
   without deleting or modifying existing evidence. Fence operational writers
   during the actual cutover, not during lengthy network acquisition.
3. Establish the existing validated durable state as the migration checkpoint,
   preserving its source identity, state hash, cursor and immutable records.
   Prove its current restart inputs and live dependencies. Missing or invalid
   checkpoint/live evidence blocks migration; missing unrelated historical
   payloads do not. Report historical replay gaps separately. A legacy hash plus
   today's revised rows is not the original payload. No forged archive, reset
   portfolio or new genesis hiding an existing book. Define the checkpoint
   admission evidence and falsifiers in the contract implementation PR.
4. Qualify the new reader/publisher against the old reader using the same captured
   input artifacts and canonical kernel. The candidate path has no production
   write/decision authority during comparison. Prove input, state and decision
   equivalence; investigate discrepancies instead of repinning goldens.
5. Version the verification/source contracts and issue required certification for
   the actual implementation. Switch one authoritative writer/reader path after
   equivalence, restore, concurrency and performance gates pass. No permanent
   dual production engines.
6. Remove daily operational dispatch to seed/reseed/mutation reconstruction.
   Audit GO, CLI, automation, reboot and outage entry points for reachability.
   Retain historical certification evidence and only explicitly needed offline
   maintenance utilities. Delete dead production helpers after reference checks.
7. Only then enable reference-aware garbage collection. Publish an operator
   runbook with exact migration, verification and rollback commands from the
   implemented version, not guessed commands in this proposal.

Before a new-format decision is committed, rollback may select the validated
legacy publication under a writer fence. Afterward, rollback must preserve new
state, commands and evidence using a compatible reader or a forward fix. An old
binary unable to read the new contract is not a safe rollback. Never restore an
old DB over newer broker commands or pretend UNKNOWN outcomes failed.

## 9. Verification and performance gates

Implementation must add falsifiers and demonstrate that breaking each new
invariant makes its targeted test fail. Reuse existing fixtures and canonical
transitions. This design PR does not claim these gates have been executed.

| Gate | Required adverse cases | Existing test anchors |
| --- | --- | --- |
| Source lifecycle | Creating/regenerating, partial pages, expired/corrupt cache, generation change, rate limits, cancellation, restart and exhausted deadlines. | [lifecycle](../tests/sentinel/test_source_acquisition_lifecycle.py), [replay](../tests/sentinel/test_source_acquisition_replay.py) |
| Complete snapshot | Missing security/partition, duplicate key, legitimate IPO/delist absence, missing predecessor, SPY/BIL gap, exact bounded range. | [bounded publication](../tests/sentinel/test_bounded_operational_publication.py), [bounded feed](../tests/sentinel/test_bounded_operational_feed.py) |
| Atomicity and durability | Kill during bulk load/commit, stale READY candidate, concurrent publishers, pinned reader, WAL/restore failure and GC of referenced data. | [publication](../tests/sentinel/test_corpus_publication.py); new generation/archive tests |
| Economic continuity | Uniform vs nonuniform rebase, raw/volume correction, action revision, returning security basis, reused symbol, ambiguous counterparty and issuer grouping. | [warmup](../tests/sentinel/test_warmup_economic_contract.py), [history](../tests/sentinel/test_strategy_history_mutations.py), [identity](../tests/sentinel/test_reused_symbol_identity.py), [terminal](../tests/sentinel/test_terminal_identity.py), [actions](../tests/sentinel/test_action_lifecycle.py) |
| Long-lived book | Genesis older than 300 sessions without routine genesis reads; missing irrelevant historical payload does not block; invalid checkpoint or missing live dependency does block; short/out-of-window outage; no book reinitialization. | [outage](../tests/sentinel/test_production_outage_recovery.py), [reboot](../tests/sentinel/test_reboot_outage_recovery.py); new checkpoint/scope falsifiers |
| Authority and operator output | Refusal cannot trade; pending differs from failed; dependent phases skip; retry resumes checkpoints; exact stage/unknown totals; diagnostics redacted. | Targeted GO/automation/shadow tests selected with changed modules |

Benchmark on the NAS with the actual eligible universe and its dependency
closure, not a small ticker subset. Measure network bytes, parse/load/validation
time, row passes, peak memory, staging/retained disk, WAL, lock waits and atomic
commit duration separately. Cover cold start, daily replacement, source wait,
resumed acquisition and outage recovery; report run count and latency distribution
when sufficient samples exist. Compare against both successful top-up and current
bounded recovery on the same inputs.

Set and review per-stage SLOs from that benchmark before cutover, within the
existing operational deadlines. Do not call a longer timeout, smaller universe,
disabled operational guard or missing required restore evidence a performance
fix. A fresh full window can
cost more than a healthy one-day top-up; reduced reconstruction complexity is
the architectural advantage, not a guaranteed download speedup.

## 10. Implementation sequence and Alpaca exit gate

Deliver separately reviewable steps: (1) storage/archive and verification-scope
contracts; (2) Sharadar direct candidate publisher and progress/jobs; (3) loader,
GO and automation cutover with migrations; (4) removal of obsolete operational
recovery routes and measured retention; (5) separately qualified Alpaca adapter.
Each step is linked to the tracking feature and reports its own tests and risks.

The Alpaca step must prove universe breadth and classification (including the
current ADR admission), issuer/sector identity, dated aliases, required raw and
adjusted economics, action/counterparty completeness, benchmarks and source
consistency. Pin the intended market-data feed and entitlements explicitly; do
not substitute IEX for SIP or assume OTC/delisted coverage. An `asof` query is not
a vintage lock. Verify pagination completeness across all symbols.

Use the same canonical schema and kernel for side-by-side offline comparisons,
followed by prospective paper qualification under feature #376. Record input,
universe, feature, state and decision differences; do not declare vendor
equivalence from aggregate returns alone. No silent mixed-provider fallback.
If another reference source is necessary, document it as a multi-provider
architecture requiring separate approval. Retiring Sharadar is not authorized
by this rolling-window design PR.

## 11. Decisions requiring explicit review

The recommended defaults above are concrete, but these are release gates:

1. Accept current-window/live-dependency verification and durable checkpoint
   continuity, with changed verdict/identity contracts, instead of the old
   unbounded historical reread. Historical replay is not a daily gate.
2. Prove checkpoint admission and required current restart evidence before
   migration. Document historical replay gaps without treating unrelated missing
   old prices as a startup blocker.
3. Qualify reusable reference generations and their refresh triggers/completeness;
   measure any remaining broad ACTIONS/TICKERS acquisition.
4. Approve measured storage/backup/performance SLOs and rollback compatibility
   before deployment. No runtime or duration claim is certified by this document.
