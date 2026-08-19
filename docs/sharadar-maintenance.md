# Sharadar current-source maintenance

Sentinel treats three different notions of progress separately. They must not be
collapsed into one cursor.

## 1. Market-session frontier

`feed-daily` still discovers newly closed market sessions from the published SEP
frontier. The normal overlap remains useful for newly published sessions and
recent price-date restatements, but it is **not** mutation authority.

A failed/unpublished ingest may advance the physical `MAX(session)` beyond the
published frontier. On retry Sentinel expands the overlap by that entire gap so
candidate-owned leading-edge rows cannot become permanently stranded.

## 2. SEP mutation watermark

Sharadar SEP exposes `lastupdated`, which is date-valued in the retained source.
Sentinel stores a separate durable `sharadar-sep-lastupdated:v1` cursor.

Rules:

- a complete source-stable seed earns the initial watermark;
- daily maintenance re-reads the complete preceding `lastupdated` date, so rows
  sharing one boundary date cannot be skipped;
- each mutation set is observed twice before it becomes input authority;
- changed historical price/open/volume fields are applied through the normal
  candidate/publication membrane;
- the mutation cursor advances only **after** the candidate publication exists;
- a crash after publication but before cursor commit causes replay, never a gap;
- missing identity or economically incomplete correction data fails closed.

`lastupdated` is current-source reconciliation. It does not recreate the vendor
vintage that existed on the historical session and must not be described as a
historical-as-of timestamp.

## 3. Complete negative-space reconciliation

An update timestamp cannot reveal a row that disappeared entirely. Sentinel
therefore performs complete source reconciliation in addition to CDC.

### SEP

Normal maintenance checks `SHARADAR_SEP_RECONCILE_YEARS_PER_RUN` complete
calendar-year partitions per `feed-daily` run (default: 1). A partition is read
twice from Sharadar, normalized through the same permanent-identity/domain path
as ingest, and its normalized `(security_id, session, ticker)` set is compared
to the published local set.

At one partition per trading day, a 1997-present corpus is revisited roughly once
per month. This avoids a multi-hour full history traversal every night while
ensuring deletions/key-set drift cannot remain invisible indefinitely.

For a new deployment or before starting a measurement/certification period, run
the complete sweep once:

```bash
python scripts/sentinel_reconcile_sep.py --through YYYY-MM-DD
```

The command is broker-free and holds the corpus writer lock. Any mismatch is a
hard refusal. It does **not** delete local rows or invent replacement data: a
key-set disagreement is evidence that requires an explicit complete repair/new
publication, not permission to mutate an already published version in place.

### ACTIONS

ACTIONS has no equivalent documented mutation cursor. Sentinel therefore performs
a complete two-observation ACTIONS reconciliation every
`SHARADAR_ACTIONS_RECONCILE_DAYS` days (default: 7). The existing full-row
PRESENT/REMOVED generation machinery remains authoritative: additions,
corrections, and removals are candidate state until the corpus publication
transaction activates them. A suspicious empty source or material mass shrink
is refused rather than interpreted as authoritative removal.

## Crash/restart rule

Every ordinary `feed-seed` / `feed-daily` rerun converges durable ingest state
before opening new work:

1. `RUNNING` runs left by a dead process are reclaimed/failed and their pending
   action/anomaly candidates are retired;
2. exactly one complete `SUCCESS` run lacking a publication is treated as
   validated-pending-publication and its publication is resumed;
3. more than one such validated candidate is ambiguous and is refused rather
   than ordered by timestamp/guess;
4. a run is never reported successful to the caller until its publication row
   exists.

This preserves the distinction between **physical rows**, **validated candidate**,
and **published authority** at every process-death boundary.
