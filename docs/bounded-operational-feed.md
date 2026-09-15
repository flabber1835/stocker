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

A private indexed disk capture serves subsequent normalization, membership,
CDC, overlap and reconciliation reads from those verified files. These are
local replays, not independent vendor observations. Independent exporter status
reads corroborate refresh stability before replay and publication. A changing
table refresh invalidates the capture; there is no paginated or full-history
fallback. Existing domain, canonical identity, duplicate, session membership,
normalized-source/local equality and negative-space retirement guards remain.

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
