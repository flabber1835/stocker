# Bounded operational feed acquisition

GO preparation and production daily ingestion acquire at most 300 XNYS price
sessions ending at their explicit source-final target. This exceeds the selected
production strategy's 252-session feature requirement and includes the split
boundary predecessor. Startup requirements are checked against this cap; a
larger requirement refuses rather than silently widening acquisition.

Production recovery replaces this operational interval using the canonical seed,
normalizer, identity reconstruction and atomic publication machinery. It never
selects the oldest retained price row as its automatic reseed start. An empty
feed can use the same bounded seed. Persisted portfolio, execution, reconciliation
and account records are preserved. Feature warmup never reconstructs an existing
book. A feed frontier older than the acquisition window selects bounded reseed
without attempting an out-of-window daily traversal. Stable operational SEP
key/value drift may also select that same recovery; unproved negative space still
refuses at the canonical publication/proof guards. A durable catch-up cursor
requiring older inputs refuses with the exact
required interval and requires explicit operator recovery.

Older published price rows are retained, not deleted. Older unpublished rows
remain hidden and are classified by the existing operational dependency closure.
They may be left historical-only, but any remaining production-blocking input
prevents publication. Operational identity replacement proves and retires keys
only inside its recorded interval; it does not claim full-history correction.
Full-history seed and reconciliation remain explicitly invoked maintenance
operations. Daily operations no longer run the rotating historical-year audit.
Daily database persistence remains incremental. Its source proofs may reread the
bounded operational interval once per run; this is not a delta-only network
contract and does not delete retained published history.

## Source authority

Nasdaq's filtered Table Exporter is the single-file acquisition authority:
[Table Exporter filters](https://docs.data.nasdaq.com/v1.0/docs/in-depth-usage-1).
Before downloading source data, probe ACTIONS, TICKERS and every bounded SEP
partition. All must be fresh with snapshot time at or after table refresh.
Creating/regenerating exports refuse immediately and identify the table and
interval. GO's preliminary read-only probe checks export availability and local
watermarks only; it does not perform a separate SEP CDC data download. Identity
and CDC validation belong to the canonical certified preparation over the one
captured snapshot. Price partitions are calendar-month slices of the same 300-session
interval to bound peak memory. Every SEP partition must name the same table
refresh. Each file is downloaded once and its SHA256, interval, row count and
vendor timestamps are bound into publication evidence.

The preliminary probe observes exports only after the target session's reviewed
23:45 America/New_York source-final boundary. A cold database before that
boundary still reports its local recovery requirement; a generating export is
not negative source authority yet. CI's real-container cold-start fixture fixes
the observation clock, not the finality verdict. Its clock-only import seam and
calendar clock use the same explicit instant; the pinned XNYS calendar and
production `publication_not_before` comparison remain unchanged. Tests cover
before, exactly at, and after finality, including standard time and a half-day.
Runtime-check diagnostics report the check, child exit, status, reason and
failure phase without printing commands, credentials or raw child output.

A private indexed disk capture serves subsequent normalization, membership,
CDC, overlap and reconciliation reads from those verified files. These are
local replays, not independent vendor observations. Independent exporter status
reads corroborate refresh stability before replay and publication. A changing
table refresh invalidates the capture; there is no paginated or full-history
fallback. Existing domain, canonical identity, duplicate, session membership,
normalized-source/local equality and negative-space retirement guards remain.

During an active operational capture, normalization predecessors come from the
same verified SEP capture, resolved by permanent identity at their source date,
not from older-vintage stored signal closes. Each security's first captured
observation is a baseline when no captured predecessor exists. Comparing a
restated source row to an out-of-window older adjustment factor would invent a
share-count event. This does not supply no-split evidence: explicit ACTIONS
splits retain the canonical authoritative/unsafe disposition rules, genuine
price/action disagreement still blocks, and the bar upsert still cannot erase a
previously proven split ratio. The mandatory
253-session operational dependency interval, including its action predecessor,
must fit inside the 300-session capture; older durable dependencies still
refuse. Explicit retained-history normalization keeps its stored-predecessor
query and guards.

ACTIONS and TICKERS retain their complete metadata authority: historical renames
and corporate actions are needed even when price acquisition is bounded.
TICKERS field values still use JSON to preserve NULL versus empty semantics.
SFP reference acquisition remains independently corroborated. This decision
bounds price acquisition, not the number of permanent identities in the universe.

SEP mutation watermarks record the acquired price interval as their proof scope.
Readiness may consume this operational authority, but an explicitly requested
full-history CDC operation refuses an operational watermark until a complete
manual seed/reconciliation earns unscoped authority. Advancing the operational
watermark must never advertise that retained older prices have been audited.

## Operator visibility

Credential-free structured progress names preflight, table, export status,
requested interval, partition index/count, snapshot/refresh timestamps, received
rows, database chunk/replay, proof and publication. GO heartbeats repeat the
latest actual phase and report elapsed time and time since its last progress
event. An uninstrumented subprocess explicitly reports that it has supplied no
internal progress. No guessed percent or ETA is displayed. Status messages never
include download URLs, database URLs, API keys or raw exception payloads.

## Replay evidence boundaries

The Sharadar research replay distinguishes the public bounded `ingest.daily`
entry point from its canonical retained-history `_daily` orchestrator. Existing
pagination, repeated failed-owner and between-observation fault schedules remain
explicit retained-history component evidence: they call the orchestrator with
the default source, not an injected fetch that omits authority checks. They do
not certify the operational acquisition wrapper or authorize an automatic
full-history fallback. Scenarios must declare their acquisition mode explicitly;
reports name that mode and the tested entry point, and evidence aggregation
rejects mislabeled or missing bounded acquisition proof.

Separate bounded operational scenarios exercise the public entry point through
real simulated Exporter HTTP, local file replay and PostgreSQL. An independent
XNYS fixture oracle requires exactly the 300-session download interval, no
repeat download per table/partition, no paginated SEP/ACTIONS acquisition and
unchanged older published history. Fresh normal arrivals, corrections/actions,
export preflight refusals, archive failure and table-generation changes have
explicit expected corpus, readiness and recovery outcomes. Neither evidence
surface substitutes a source proof, publication verdict or readiness result.
