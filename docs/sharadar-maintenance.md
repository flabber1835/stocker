# Sharadar current-source maintenance

Sentinel treats three different notions of progress separately. They must not be
collapsed into one cursor.

## 1. Market-session frontier

`feed-daily` discovers newly closed market sessions from the published SEP
frontier. The ordinary price-date overlap remains useful for new sessions and
recent restatements, but it is **not** mutation authority.

A failed/unpublished ingest may advance the physical `MAX(session)` beyond the
published frontier. On retry Sentinel expands the overlap by that entire gap so
candidate-owned leading-edge rows cannot become permanently stranded.

The ordinary production source is additionally guarded by whole-table TICKERS
key authority: the paginated `table=SEP` `(permaticker,ticker)` set must equal a
fresh Nasdaq Tables Exporter snapshot. For every newly exposed SEP session, the
same stable TICKERS listing intervals then provide the expected price-key
population. This prevents a stable partial TICKERS/SEP publication from becoming
local authority merely because it repeated twice.

## 2. SEP mutation watermark

Sharadar SEP exposes `lastupdated`, which is date-valued in the retained source.
Sentinel stores a separate durable `sharadar-sep-lastupdated:v1` cursor.

Rules:

- a complete source-stable seed can earn the initial watermark;
- an upgraded pre-#185 corpus may earn it only after the **complete value + key
  reconciliation** described below; guessing the cursor from today's maximum
  `lastupdated` is forbidden;
- daily maintenance re-reads the complete preceding `lastupdated` date, so rows
  sharing a boundary date cannot be skipped;
- each mutation set is observed twice before it becomes input authority;
- historical corrections are not patched into one row. Sentinel re-fetches the
  affected bounded XNYS window and runs the ordinary normalizer over the prior,
  effective and following sessions so split inference at both boundaries,
  dividends, rejections and anomaly evidence remain coherent;
- the mutation cursor advances only **after** the correction publication exists;
- a crash after publication but before cursor commit causes replay, never a gap;
- missing identity or economically incomplete correction data fails closed.

`lastupdated` is current-source reconciliation. It does not recreate the vendor
vintage that existed on the historical session and must not be described as a
historical-as-of timestamp.

Readiness binds maintenance to the **published decision frontier**, not to
wall-clock midnight. A Friday-close decision whose SEP cursor and complete
ACTIONS authority cover Friday remains valid at Monday open. Once Monday itself
is the published decision frontier, Monday-complete maintenance is required.

## 3. Complete negative-space and bootstrap reconciliation

An update timestamp cannot reveal a row that disappeared entirely. It also
cannot prove that an old local value was already current before a newly installed
cursor begins. Sentinel therefore performs complete source reconciliation in
addition to CDC.

### SEP

Normal maintenance checks `SHARADAR_SEP_RECONCILE_YEARS_PER_RUN` complete
calendar-year partitions per `feed-daily` run (default: 1). A partition is read
twice from Sharadar and normalized through the same permanent-identity/domain
path as ingest. Two independent commitments are compared with the published
local corpus:

1. normalized `(security_id, session, ticker)` membership; and
2. the exact strategy-critical persisted SEP values: signal close, raw close,
   raw open, and normalized raw-compatible volume.

Numeric values are canonicalized so equivalent PostgreSQL/Python spellings do
not produce false drift. A same-key price/open/volume mismatch is just as
blocking as a missing/deleted key.

At one rotating historical partition per trading day, a 1997-present corpus is
revisited roughly once per month. This rotation is a **detection** mechanism for
negative space that `lastupdated` cannot represent. Before launch,
certification, or any claim that the complete retained history matches current
vendor truth, the rotating cadence is not enough; use the complete sweep:

```bash
python scripts/sentinel_reconcile_sep.py --through YYYY-MM-DD
```

The command is broker-free and holds the corpus writer lock. It checks **every**
published partition. Only after all partitions pass may an existing corpus earn
its initial SEP mutation cursor. If any year fails, no CDC bootstrap is earned.

The command does **not** delete local rows or rewrite values to match the vendor.
A disagreement is evidence requiring an explicit complete repair/new publication,
not permission to mutate an already-published version in place.

### ACTIONS

ACTIONS has no documented `lastupdated` equivalent. Two identical paginated
traversals are insufficient negative-space authority because the same incomplete
set can repeat.

Production complete reconciliation therefore uses Nasdaq Data Link's **Tables
Exporter** for the explicit `1900-01-01..decision_frontier` filter. The Exporter
generates one zipped CSV and reports `file.status`, `file.data_snapshot_time`,
and `datatable.last_refreshed_time`. Sentinel accepts only `Fresh` with snapshot
generation beginning at or after the latest table refresh.

The stronger contract deliberately uses a new cursor:

```text
sharadar-actions-export-reconcile:v2
```

A pre-fix v1 cursor earned by double pagination cannot satisfy v2 readiness.
The default cadence is one decision day, so complete ACTIONS authority must cover
the decision frontier itself. This preserves next-open semantics: Friday's
complete snapshot remains valid for the frozen Friday plan at Monday open; after
Monday close, Monday authority is required.

The existing PRESENT/REMOVED candidate-generation machinery remains
unchanged. When a changed row is a split or dividend, Sentinel first writes the
candidate ACTIONS generation, then re-normalizes the affected
prior/effective/following SEP session window **against that candidate action
overlay**. One corpus publication activates the action state and corrected bar
economics together. Terminal-only ACTIONS changes need no price re-normalization
but still remain candidate state until publication.

A suspicious empty export or material mass shrink is refused rather than
interpreted as authoritative removal. Download URLs may carry credentials and
are never persisted or rendered in diagnostic evidence.

## 4. TICKERS historical identity corrections

Current TICKERS can legitimately extend a listing into a newly closed session.
It can also contain later vendor corrections to historical listing bounds.
Those are different operations.

Because `sentinel_bars` is keyed by `(security_id,session)`, publishing only a
metadata correction that changes identity inside already-published history would
leave the old bar key alive. Sentinel therefore refuses a full TICKERS candidate
when it changes, introduces, or omits a listing interval overlapping published
SEP history. Forward-only extension/new listings after the frontier remain
allowed.

This is a repair boundary, not a claim that vendor corrections cannot happen. A
real historical identity correction requires a complete identity-aware rebuild
that can re-key/tombstone affected bars atomically. Until then, prior authority
remains visible and operation is fenced rather than guessed.

## 5. Crash/restart rule

Every ordinary `feed-seed` / `feed-daily` rerun first classifies durable ingest
state under the corpus writer lock:

1. `RUNNING` runs left by a dead process are reclaimed/failed and their pending
   action/anomaly candidates are retired;
2. exactly one complete `SUCCESS` run lacking a publication is treated as
   validated-pending-publication and its publication is resumed;
3. one failed live candidate is retried by the operation capable of superseding
   its exact physical rows (`daily`, `sep_mutations`, or `actions_reconcile`);
4. a run is never reported successful to the caller until its publication row
   exists.

### Legacy multi-candidate recovery

Pre-#185 code could accumulate several overlapping unpublished runs. Their
process timestamps are not source authority and Sentinel never sorts them into a
guessed winner. `feed-daily` refuses that ambiguous state and names the supported
recovery: a complete `feed-seed`.

The reseed widens market-data replacement scope to cover old candidate-owned
SEP/SPY rows, treats ACTIONS under its independent complete 1900..through source
contract, retires only unpublished candidate lifecycle, refetches stable source
authority, and publishes one replacement generation. Published history is never
retired by recovery.

Old candidate rows are deliberately not deleted before replacement work exists.
At every crash boundary they remain either a coherence blocker or part of a new
candidate that a subsequent supported retry can resume. Thus no process death
can expose a partially reconstructed old publication as READY.

This preserves the distinction between **physical rows**, **validated candidate**,
and **published authority** at every process-death boundary.
