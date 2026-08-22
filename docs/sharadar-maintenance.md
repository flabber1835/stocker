# Sharadar current-source maintenance

Sentinel treats distinct notions of source progress separately. They must not be
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
- an upgraded pre-#185 corpus may earn it only after complete value + key
  reconciliation; guessing the cursor from today's maximum `lastupdated` is
  forbidden;
- daily maintenance re-reads the complete preceding `lastupdated` date;
- each mutation set is observed twice before it becomes input authority;
- historical corrections replay prior/effective/following sessions through the
  ordinary normalizer;
- correction replay is bounded on both sides by the already-published market
  horizon; a current revision outside it belongs to a deliberately wider
  complete seed and cannot expand the retained corpus incrementally;
- the mutation cursor advances only **after** the correction publication exists;
- a crash after publication but before cursor commit causes replay, never a gap;
- missing identity or economically incomplete correction data fails closed.

`lastupdated` is current-source reconciliation. It does not recreate the vendor
vintage that existed on the historical session.

Readiness binds maintenance to the **published decision frontier**, not to
wall-clock midnight. A Friday-close decision whose source authority covers Friday
remains valid at Monday open. Once Monday itself is the published decision
frontier, Monday-complete maintenance is required.

## 3. Complete SEP negative-space reconciliation

An update timestamp cannot reveal a row that disappeared entirely. It also
cannot prove an old local value was already current before a newly installed
cursor begins. Sentinel therefore performs complete source reconciliation in
addition to CDC.

### Recent decision-history proof

The rotating deep-history audit is not allowed to be the only deletion defense
for today's decision. After the ordinary daily publication, SEP mutation CDC,
and complete ACTIONS reconciliation have all finished, Sentinel takes a fresh
Nasdaq whole-file SEP export for the exact Wealth Core `REQUIRED_CLOSES` history
window and passes it through the existing canonical normalizer/reconciliation
path.

The proof compares:

1. normalized `(security_id, session, ticker)` membership; and
2. exact persisted strategy values: signal close, raw close, raw open, and
   normalized raw-compatible volume.

Its independent durable cursor is:

```text
sharadar-sep-recent-export-reconcile:v1
```

The cursor records both the decision frontier and the **exact corpus publication
version** that was reconciled. Readiness fails if the proof is missing, behind the
frontier, ahead of the observation clock, or names an older publication. Thus a
later mutation publication invalidates the prior proof automatically.

The recent proof is intentionally the final source-maintenance step in
`feed-daily`; it cannot certify an intermediate publication that ACTIONS/CDC then
changes underneath it.

### Deep-history rotation

Normal maintenance additionally checks
`SHARADAR_SEP_RECONCILE_YEARS_PER_RUN` complete calendar-year partitions per
`feed-daily` run (default: 1). A partition is read twice and normalized through
the same permanent-identity/domain path as ingest. The same key and value
commitments are compared with the published corpus.

At one rotating historical partition per trading day, a 1997-present corpus is
revisited roughly once per month. This is a forensic/deep-history detection
mechanism, not the current-decision deletion defense described above.

Before launch, certification, or any claim that the complete retained history
matches current vendor truth, run the full sweep:

```bash
python scripts/sentinel_reconcile_sep.py --through YYYY-MM-DD
```

The command is broker-free and holds the corpus writer lock. Only after all
partitions pass may an existing corpus earn its initial SEP mutation cursor. A
disagreement is evidence requiring an explicit complete repair/new publication,
not permission to mutate an already-published version in place.

## 4. ACTIONS

ACTIONS has no documented `lastupdated` equivalent. Two identical paginated
traversals are insufficient negative-space authority because the same incomplete
set can repeat.

Production complete reconciliation therefore uses Nasdaq Data Link's **Tables
Exporter** for the explicit `1900-01-01..decision_frontier` filter. Sentinel
accepts only a `Fresh` export whose snapshot generation began at or after the
latest reported table refresh.

The stronger contract deliberately uses a new cursor:

```text
sharadar-actions-export-reconcile:v2
```

A pre-fix v1 cursor cannot satisfy v2 readiness. The default cadence is one
decision day.

The existing PRESENT/REMOVED candidate-generation machinery remains unchanged.
When a changed row is a split or dividend, Sentinel writes the candidate ACTIONS
generation then re-normalizes the affected prior/effective/following SEP window
against that candidate overlay. Only actions whose effective XNYS session is
inside the already-published market horizon participate, and replay is clipped
to that horizon. The complete 1900 ACTIONS scope is metadata/negative-space
authority, never permission to widen a short SEP seed. One publication activates
both. Terminal-only changes remain candidate state until publication.

A suspicious empty export or material mass shrink is refused rather than
interpreted as authoritative removal. Credential-bearing download URLs are never
persisted or rendered in diagnostic evidence.

## 5. TICKERS historical identity corrections

Current TICKERS can legitimately extend a listing into a newly closed session.
It can also contain later vendor corrections to historical listing bounds. Those
are different operations.

Because `sentinel_bars` is keyed by `(security_id,session)`, publishing only a
metadata correction that changes identity inside already-published history would
leave the old bar key alive. Sentinel therefore refuses a full TICKERS candidate
when it changes, introduces, or omits a listing interval overlapping published
SEP history. Forward-only extension/new listings after the frontier remain
allowed.

A real historical identity correction requires a complete identity-aware rebuild
that can re-key/tombstone affected bars atomically. Until then, prior authority
remains visible and operation is fenced rather than guessed.

## 6. Crash/restart rule

Every ordinary `feed-seed` / `feed-daily` rerun first classifies durable ingest
state under the corpus writer lock:

1. `RUNNING` runs left by a dead process are reclaimed/failed and their pending
   action/anomaly candidates are retired;
2. exactly one complete `SUCCESS` run lacking a publication is resumed;
3. one failed live candidate is retried by the operation capable of superseding
   its exact physical rows (`daily`, `sep_mutations`, or `actions_reconcile`);
4. a run is never reported successful until its publication exists.

### Legacy multi-candidate recovery

Pre-#185 code could accumulate several overlapping unpublished runs. Their
process timestamps are not source authority and Sentinel never sorts them into a
guessed winner. `feed-daily` refuses that ambiguous state and names the supported
recovery: a complete `feed-seed`.

The reseed widens market-data replacement scope to cover old candidate-owned
SEP/SPY rows, treats ACTIONS under its independent complete source contract,
retires only unpublished candidate lifecycle, refetches stable authority, and
publishes one replacement generation. Published history is never retired by
recovery.

This preserves the distinction between **physical rows**, **validated
candidate**, and **published authority** at every process-death boundary.
