# Sharadar publication authority

**Status: financial-grade source-authority follow-up to #177/#178/#186,
2026-08-19.** This document is the source-of-truth for the source-publication
boundary implemented by `sentinel/feed/authority.py`,
`sentinel/feed/coherence.py`, `sentinel/feed/snapshot_source.py`, and
`sentinel/feed/snapshot_export.py`. It supplements the price-domain and local
corpus-publication rules; it does not weaken any of them.

## 1. Stability is not completeness

A successful Nasdaq Data Link Tables traversal proves only that the HTTP
requests completed. Cursor pagination exposes no immutable generation token or
snapshot-isolation identifier binding all pages. Repeating a complete traversal
and obtaining the same multiplicity-sensitive content fingerprint is therefore
valuable **stability evidence**, but two identical partial traversals are still
partial.

The official Tables Exporter provides a stronger negative-space witness for the
small set of tables where an omitted row is itself economically authoritative.
With `qopts.export=true`, Nasdaq generates the requested table/filter as one
zipped CSV. The status response exposes:

```text
file.status              Fresh / Creating / Regenerating
file.data_snapshot_time  when file creation began
datatable.last_refreshed_time
                         when the table was last updated
```

Sentinel accepts an export as current only when `status == Fresh` and
`data_snapshot_time >= last_refreshed_time`. A credential-bearing download link
is transport-only and is never persisted or rendered in an exception.

Official documentation consulted:

- `https://docs.data.nasdaq.com/docs/in-depth-usage-1`
- `https://docs.data.nasdaq.com/v1.0/docs/parameters-1`
- Nasdaq's public `data-link-python` client (`export_table`)

The Exporter is deliberately not used for every value read. JSON pagination
preserves nullable-field semantics that CSV cannot, and SEP is too large to
export every evening. The authority model therefore combines independent
witnesses rather than pretending one transport shape is ideal for every table.

## 2. SEP authority

Strategy-bearing SEP fields are:

```text
date             session identity
ticker           permanent-identity lookup label
close            split-adjusted, dividend-unadjusted signal domain
closeunadj       as-traded close / marking domain
open             adjusted open used to reconstruct as-traded open
volume           Sharadar split-adjusted source volume; normalized at boundary
lastupdated      current-source mutation clock
```

`closeadj` is deliberately excluded from security-level Wealth Core authority;
SPY's total-return series is separately scoped through SFP.

### Daily negative-space proof

The #177 two-observation SEP fingerprint remains mandatory, but it is no longer
allowed to prove population completeness by itself. For every newly exposed
session, Sentinel takes the **same stable table=SEP TICKERS listing intervals**
and asks which ticker identities are supposed to be priced on that date. SEP
must contain at least **99.9%** of those expected keys.

This is not yesterday-population comparison and it is not portfolio
investability. A legitimate mass delisting contracts TICKERS and SEP together
and passes. A stable 80%-95% partial SEP publication does not.

Retained 2026 calibration through 2026-08-03:

```text
sessions measured                                      146
2026-07-31 SEP population                            6,256
2026-08-03 SEP population                            5,924
TICKERS-predicted 2026-08-03 population             5,924
worst legitimate expected-key coverage       6,223 / 6,226
                                             = 99.9518%
implemented daily floor                               99.9%
```

The three-name worst tail leaves deliberate room for observed source sparsity
without turning an incomplete page-scale response into authority.

Frontier-session signal close, raw close, reconstructable raw open, and volume
are still checked independently. A healthy 126-session history cannot dilute a
broken current decision session into PASS.

## 3. TICKERS authority

Sentinel's strategy universe is explicitly the `table=SEP` TICKERS partition.
Authority-bearing fields are:

```text
table
permaticker
ticker
category
relatedtickers
firstpricedate
lastpricedate
sector
isdelisted
```

`exchange` remains non-authoritative in current Sentinel behavior; enabling
exchange gating later requires adding it to the behavioral contract first.

### Values: paginated JSON

TICKERS metadata values remain sourced from the strict paginated JSON response.
That preserves a critical distinction:

- a real NULL means no new observation and may carry a prior non-null sparse
  field forward;
- an observed blank `relatedtickers` is authoritative evidence that the sibling
  set is empty and may clear a prior relationship.

Two complete TICKERS observations bracket the protected SEP read and must have
the same behavioral fingerprint.

### Keys: independent whole-table export

Every production TICKERS traversal additionally compares its complete
`(permaticker, ticker)` set for `table=SEP` with a fresh whole-table Exporter
snapshot. The key sets must match exactly. This prevents paginated TICKERS and
paginated SEP from common-mode false-greening on the same stable truncation.

### Historical identity corrections

`sentinel_bars` is keyed by `(security_id, session)`. Updating only
`feed_universe_current` cannot safely apply a later TICKERS correction that
changes an already-published listing interval: the old bar key may remain
visible under a resolver that no longer names it.

Therefore a complete TICKERS candidate is allowed to:

- extend an active listing only **beyond** the published frontier; and
- introduce a genuinely new listing whose first session is beyond that frontier.

It is refused before publication if it would, inside already-published SEP
history:

- narrow or widen a prior listing interval;
- introduce a new `(permaticker,ticker)` pair; or
- omit a previously published pair whose interval overlaps published history.

This is intentionally fail-closed rather than repair-by-guessing. A real vendor
historical identity correction requires a complete identity-aware rebuild that
can re-key/tombstone the affected bars atomically. Until that repair exists, the
previous published corpus remains readable and new operation stays fenced.

## 4. ACTIONS authority

The complete canonical seven-field source row is authority:

```text
date, action, ticker, name, value, contraticker, contraname
```

No coarser `(ticker,date,action)` key replaces source identity. Exact semantic
repeats are idempotent; distinct sibling rows remain distinct.

Ordinary daily ACTIONS pagination still participates in the TICKERS/ACTIONS/SFP
bracket around SEP so new splits/dividends can normalize the candidate prices.
It **does not** earn negative-space/removal authority.

Complete ACTIONS reconciliation now uses a fresh filtered Tables Exporter
snapshot for `1900-01-01..decision_frontier`. The current v5 cursor is
deliberately separate from the pre-fix v1/v2/v3/v4 cursors so an upgraded database
must earn both complete-source authority and the reviewed split-semantics
migration before readiness can pass. That migration replays all active split
dispositions, including accepted/resolved dispositions, and all current or
previously active `split`/`adrratiosplit` source dates within retained SEP history.
It also replays every retained published bar whose effective ratio, after the
newest published repair is overlaid, is not one. This corpus selector covers
legacy derived or repaired economics that have no surviving disposition or raw
source row. Such a non-unit bar may be repaired to one only when the complete
covering ACTIONS generation has no authoritative stock split and SEP provides
explicit predecessor-based no-event evidence. Restricting replay to active
blockers or source rows would leave previously accepted ADR, reciprocal
stock-split, or orphaned non-unit economics untouched.

The default reconciliation cadence is one decision day. The cursor must cover
the published decision frontier itself. This does not invalidate a Friday-close
plan at Monday open: its frozen decision frontier is still Friday. Once Monday's
close becomes the published decision frontier, Monday-complete ACTIONS authority
is required.

A changed split/dividend source row is written as candidate ACTIONS state and its
prior/effective/following SEP window is re-normalized against that candidate.
One corpus publication activates both the corporate-action generation and the
corrected bar economics. Terminal-only changes require no price rewrite but
remain candidate state until publication.

If retry replay proves that a bar left by an older failed ACTIONS reconciliation
is absent from the complete bounded SEP response, the residual physical row is
not deleted during replay. Its covered retirement is applied only inside the
replacement publication transaction. Publication failure rolls that retirement
back, preserving both the row and the unpublished-owner coherence witness.

A suspicious zero-row export or material mass shrink still refuses rather than
turning an upstream outage into mass authoritative removals.

## 5. SFP / SPY regime authority

SFP authority for the current Sentinel regime path is intentionally narrow:

```text
date
ticker
closeadj
```

SFP is observed before protected SEP and corroborated after it. Readiness
requires the exact expected 41-session SPY total-return tail; a generic healthy
price population cannot substitute for the benchmark evidence.

## 6. Historical seed completeness

A one-time seed creates the foundation later daily generations inherit. Every
SEP year chunk is checked session-by-session before replay:

```text
expected exchange session present                 required
session row count                                 >= 4,000
session population / local 20-neighbour median    >= 90%
permanent identity resolution                     >= 99%
signal close                                      >= 99%
raw close (closeunadj)                            >= 99%
reconstructable raw open                          >= 99%
volume field present                              >= 98%
```

The retained 1998-01-02 through 2026-08-03 calibration found worst legitimate
values of 99.9516% identity resolution, 99.9829% raw-close coverage, 98.7660%
volume-field coverage, 94.1289% local population/median, and 5,310 rows at the
historical absolute minimum. The thresholds are below measured legitimate
sparsity; they are not derived from the production incident.

The retained TICKERS snapshot contained 21,939 `table=SEP` rows. `permaticker`,
`category`, both listing bounds, and `isdelisted` were complete; ticker coverage
was 99.9954% and sector 99.4120%. `relatedtickers` is legitimately sparse and is
fingerprinted by semantic value rather than subjected to a non-null floor.

## 7. Refusal and retry semantics

Source instability, Exporter incompleteness, TICKERS key disagreement,
SEP/TICKERS population disagreement, historical identity mutation, seed
incompleteness, and frontier-domain incompleteness are **data-authority
refusals**.

- No failed candidate publishes.
- Readers continue seeing the prior published generation.
- Active automation remains/re-enters `RETRY_WAIT` for refresh.
- A deployed-but-fenced runtime remains disabled/killed with
  `DATA_NOT_READY`; data becoming ready cannot release broker authority by
  itself.
- Durable signed authority, schema, account identity, or configuration
  contradictions remain a separate nonretryable class.

## 8. Invariants retained

```text
transport success != source authority
stability != negative-space completeness
candidate rows remain invisible until publication
publication remains atomic
published readers remain pinned against destructive movement
permanent identity is never guessed from ticker
corporate-action sibling source rows are not collapsed at acquisition
historical source corrections happen through a new generation, never in-place
execution still requires full readiness + signed execution authority
```
