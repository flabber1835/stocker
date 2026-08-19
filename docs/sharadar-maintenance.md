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

Readiness binds this maintenance to the **published decision frontier**, not to
wall-clock midnight. A Friday-close decision whose SEP mutation cursor covers
Friday remains valid at Monday's open; Monday's post-close CDC is not an input to
that frozen plan. Once Monday itself is the published decision frontier, however,
a cursor still at Friday fails readiness. ACTIONS cadence is measured at the same
decision frontier so a valid frozen plan does not expire merely while waiting for
its next-open execution.

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
2. the exact strategy-critical persisted SEP values: `close_signal`, raw close,
   raw open and Sharadar-reported volume.

Numeric values are canonicalized so equivalent PostgreSQL NUMERIC/Python-float
spellings do not produce false drift. A same-key price/open/volume mismatch is
just as blocking as a missing/deleted key.

At one partition per trading day, a 1997-present corpus is revisited roughly once
per month. This avoids a multi-hour full-history traversal every night while
ensuring deletions, key drift and stale strategy values cannot remain invisible
indefinitely.

For a new deployment, an upgrade from a corpus with no mutation watermark, or
before starting a measurement/certification period, run the complete sweep:

```bash
python scripts/sentinel_reconcile_sep.py --through YYYY-MM-DD
```

The command is broker-free and holds the corpus writer lock. It checks **every**
published partition. Only after all partitions pass may it create/advance the SEP
mutation cursor to the maximum `lastupdated` actually observed in that fully
proven source. If any year fails, no CDC bootstrap is earned.

The command does **not** delete local rows or rewrite values to match the vendor.
A disagreement is evidence requiring an explicit complete repair/new publication
(for example a new complete seed), not permission to mutate an already published
version in place.

### ACTIONS

ACTIONS has no equivalent documented mutation cursor. Sentinel performs a
complete two-observation ACTIONS reconciliation every
`SHARADAR_ACTIONS_RECONCILE_DAYS` days (default: 7). Acquisition itself is
bounded to the same explicit `1900-01-01..through` window that the resulting
candidate/publication claims; a future-dated row outside that authority boundary
is never pulled into an otherwise narrower generation. Full canonical source-row
identity detects additions, removals and corrections.

The existing PRESENT/REMOVED candidate-generation machinery remains authoritative.
When a changed row is a split or dividend, Sentinel first writes the candidate
ACTIONS generation, then re-normalizes the affected prior/effective/following SEP
session window **against that candidate action overlay**. A single corpus
publication activates the action state and corrected bar split/dividend economics
together. Terminal-only ACTIONS changes need no price re-normalization but still
remain candidate state until publication.

A suspicious empty source or material mass shrink is refused rather than
interpreted as authoritative removal. The same rule applies during legacy full
reseed: repeatability of an empty/collapsed source is not enough to authorize a
mass deletion.

## Crash/restart rule

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

Pre-#185 code could already have accumulated **several** overlapping unpublished
runs. Their timestamps are not source authority and Sentinel never sorts them and
publishes a guessed winner. `feed-daily` refuses that ambiguous state and names
the supported recovery: run a complete `feed-seed`.

`feed-seed` then:

1. identifies every success-unpublished or still-live failed candidate;
2. widens the **market-data** replacement range to cover the oldest/newest
   candidate-owned SEP/SPY row; ACTIONS is independently covered by the complete
   `1900-01-01..through` action contract, so a very old action cannot drag SEP
   price-history validation into decades the retained market corpus does not
   model;
3. durably classifies those runs FAILED/ABORTED while leaving published history
   untouched;
4. performs the ordinary double-observed seed source contract;
5. after each SEP year is stable and rewritten, retires only residual old-owner
   bars in that exact completed window. Because an unchanged source row would
   already have been re-owned by the new run, a residual is authoritative
   source absence/non-normalizability, not a guessed deletion;
6. only after the final cross-table stability proof retires residual old SPY /
   legacy-ACTIONS candidate rows against their respective replacement scopes;
   TICKERS retirement remains part of the atomic publication transaction;
7. publishes one coherent replacement generation and re-establishes the CDC /
   complete-ACTIONS maintenance cursors.

Old candidate rows are deliberately **not** deleted before replacement work
exists. If the process dies immediately after retirement classification they
remain coherence blockers. If it dies after a stable year has been replaced,
the new seed already owns candidate rows and remains a blocker. Thus no crash
boundary can expose a partially reconstructed old publication as READY, and a
second `feed-seed` can resume recovery without manual SQL.

This preserves the distinction between **physical rows**, **validated candidate**,
and **published authority** at every process-death boundary.
