"""Bounded current-state projection of append-only TICKERS snapshots.

`sentinel_universe` is the immutable point-in-time evidence.  It intentionally
keeps every dated SHARADAR/TICKERS snapshot, because ticker reuse and historical
listing windows are part of the trading record.  It is therefore the wrong
relation for questions whose complexity should be "how many identities exist
now?".  Daily full snapshots make those questions scale with corpus age.

`sentinel_universe_current` is a DERIVED read model, one row per
(permaticker,ticker) pairing.  It retains the complete listing-window envelope
needed to resolve old sessions, while keeping current resolver/meta/readiness
work bounded by identity cardinality rather than snapshot cardinality.

Publication is the authority boundary.  A provenance-tracked candidate is
merged here in the SAME transaction that publishes its run; an unpublished
snapshot can therefore never leak into current planning.  Legacy NULL-provenance
rows are already immediately readable under `visible_predicate`, so the legacy
writer merges those rows before its existing commit.
"""
from __future__ import annotations


DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_universe_current (
        permaticker      TEXT NOT NULL,
        ticker           TEXT NOT NULL,
        category         TEXT,
        sector           TEXT,
        related_tickers  TEXT,
        first_price_date DATE,
        last_price_date  DATE,
        is_delisted      BOOLEAN,
        snapshot_date    DATE NOT NULL,
        PRIMARY KEY (permaticker, ticker))""",
    # One explicit-migration scan converts an existing append-only deployment
    # into the bounded read model.  Runtime never rebuilds this from history.
    # Re-running the migration is deterministic and repairs the projection from
    # the published/legacy evidence rather than trusting a stale derived row.
    """INSERT INTO sentinel_universe_current
          (permaticker,ticker,category,sector,related_tickers,
           first_price_date,last_price_date,is_delisted,snapshot_date)
        SELECT u.permaticker,u.ticker,
          (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers
                                  ORDER BY u.snapshot_date DESC), NULL))[1],
          MIN(u.first_price_date),MAX(u.last_price_date),
          (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          MAX(u.snapshot_date)
        FROM sentinel_universe u
        WHERE u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
          AND (u.last_written_run_id IS NULL OR EXISTS (
                SELECT 1 FROM sentinel_corpus_publications p
                 WHERE p.run_id=u.last_written_run_id))
        GROUP BY u.permaticker,u.ticker
        ON CONFLICT (permaticker,ticker) DO UPDATE SET
          category=EXCLUDED.category,
          sector=EXCLUDED.sector,
          related_tickers=EXCLUDED.related_tickers,
          first_price_date=EXCLUDED.first_price_date,
          last_price_date=EXCLUDED.last_price_date,
          is_delisted=EXCLUDED.is_delisted,
          snapshot_date=EXCLUDED.snapshot_date""",
]


# Candidate aggregation is over ONE ingest generation, never over retained
# history.  The ON CONFLICT merge preserves the latest non-null labels while
# expanding the historical listing envelope.  A later sparse TICKERS response
# therefore cannot erase a boundary a prior snapshot knew.
_PROJECT_RUN = """
    INSERT INTO sentinel_universe_current
      (permaticker,ticker,category,sector,related_tickers,
       first_price_date,last_price_date,is_delisted,snapshot_date)
    SELECT u.permaticker,u.ticker,
      (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),NULL))[1],
      (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),NULL))[1],
      (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers ORDER BY u.snapshot_date DESC),
                    NULL))[1],
      MIN(u.first_price_date),MAX(u.last_price_date),
      (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),NULL))[1],
      MAX(u.snapshot_date)
    FROM sentinel_universe u
    WHERE {predicate}
      AND u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
    GROUP BY u.permaticker,u.ticker
    ON CONFLICT (permaticker,ticker) DO UPDATE SET
      category=CASE
        WHEN EXCLUDED.snapshot_date >= sentinel_universe_current.snapshot_date
          THEN COALESCE(EXCLUDED.category,sentinel_universe_current.category)
        ELSE sentinel_universe_current.category END,
      sector=CASE
        WHEN EXCLUDED.snapshot_date >= sentinel_universe_current.snapshot_date
          THEN COALESCE(EXCLUDED.sector,sentinel_universe_current.sector)
        ELSE sentinel_universe_current.sector END,
      related_tickers=CASE
        WHEN EXCLUDED.snapshot_date >= sentinel_universe_current.snapshot_date
          THEN COALESCE(EXCLUDED.related_tickers,
                        sentinel_universe_current.related_tickers)
        ELSE sentinel_universe_current.related_tickers END,
      first_price_date=CASE
        WHEN sentinel_universe_current.first_price_date IS NULL
          THEN EXCLUDED.first_price_date
        WHEN EXCLUDED.first_price_date IS NULL
          THEN sentinel_universe_current.first_price_date
        ELSE LEAST(sentinel_universe_current.first_price_date,
                   EXCLUDED.first_price_date) END,
      last_price_date=CASE
        WHEN sentinel_universe_current.last_price_date IS NULL
          THEN EXCLUDED.last_price_date
        WHEN EXCLUDED.last_price_date IS NULL
          THEN sentinel_universe_current.last_price_date
        ELSE GREATEST(sentinel_universe_current.last_price_date,
                      EXCLUDED.last_price_date) END,
      is_delisted=CASE
        WHEN EXCLUDED.snapshot_date >= sentinel_universe_current.snapshot_date
          THEN COALESCE(EXCLUDED.is_delisted,
                        sentinel_universe_current.is_delisted)
        ELSE sentinel_universe_current.is_delisted END,
      snapshot_date=GREATEST(sentinel_universe_current.snapshot_date,
                             EXCLUDED.snapshot_date)
"""


def project_run(conn, *, run_id: str) -> int:
    """Merge one candidate generation; caller owns the publication transaction.

    This function NEVER commits.  `publication.publish` invokes it before the
    publication row is committed, so either both projection and publication
    become durable or neither does.
    """
    sql = _PROJECT_RUN.format(predicate="u.last_written_run_id=%s")
    with conn.cursor() as cur:
        cur.execute(sql, (str(run_id),))
        return max(0, int(cur.rowcount or 0))


def project_legacy_snapshot(conn, *, snapshot_date: str) -> int:
    """Merge immediately-visible NULL-provenance rows for one dated snapshot.

    Legacy rows are readable immediately by design.  Keeping the projection in
    the same transaction prevents the bounded reader and raw visibility rule
    from disagreeing during upgrades or explicit legacy imports.
    """
    sql = _PROJECT_RUN.format(
        predicate="u.last_written_run_id IS NULL AND u.snapshot_date=%s")
    with conn.cursor() as cur:
        cur.execute(sql, (snapshot_date,))
        return max(0, int(cur.rowcount or 0))
