"""Bounded current-state projection of append-only TICKERS snapshots.

`sentinel_universe` is immutable point-in-time evidence. It intentionally keeps
every dated SHARADAR/TICKERS snapshot, because ticker reuse and historical
listing windows are part of the trading record. It is therefore the wrong
relation for questions whose complexity should be "how many identities exist
now?". Daily full snapshots make those questions scale with corpus age.

`feed_universe_current` is a DERIVED read model, one row per
(permaticker,ticker) pairing. It retains the complete listing-window envelope
needed to resolve old sessions, while keeping current resolver/meta/readiness
work bounded by identity cardinality rather than snapshot cardinality. The
`feed_` name is deliberate: this is rebuildable feed infrastructure, not a new
behavioral/authority-bearing `sentinel_*` relation.

Sparse vendor rows require field-level chronology. A later snapshot can omit a
label that an older one knew, so the projection stores the snapshot date of each
latest non-null label. That lets callers preserve the old exact "latest non-null
across history" semantics even when one permaticker has multiple ticker pairs.

Publication is the authority boundary. A provenance-tracked candidate is merged
here in the SAME transaction that publishes its run; an unpublished snapshot can
therefore never leak into current planning. Legacy NULL-provenance rows are
already immediately readable under `visible_predicate`, so the legacy writer
merges those rows before its existing commit.
"""
from __future__ import annotations


DDL = [
    """CREATE TABLE IF NOT EXISTS feed_universe_current (
        permaticker                  TEXT NOT NULL,
        ticker                       TEXT NOT NULL,
        category                     TEXT,
        category_snapshot_date       DATE,
        sector                       TEXT,
        sector_snapshot_date         DATE,
        related_tickers              TEXT,
        related_tickers_snapshot_date DATE,
        first_price_date             DATE,
        last_price_date              DATE,
        is_delisted                  BOOLEAN,
        is_delisted_snapshot_date    DATE,
        snapshot_date                DATE NOT NULL,
        PRIMARY KEY (permaticker, ticker))""",
    # Upgrade a projection created by an earlier development revision without
    # relying on CREATE TABLE IF NOT EXISTS to add the chronology columns.
    """ALTER TABLE feed_universe_current
        ADD COLUMN IF NOT EXISTS category_snapshot_date DATE""",
    """ALTER TABLE feed_universe_current
        ADD COLUMN IF NOT EXISTS sector_snapshot_date DATE""",
    """ALTER TABLE feed_universe_current
        ADD COLUMN IF NOT EXISTS related_tickers_snapshot_date DATE""",
    """ALTER TABLE feed_universe_current
        ADD COLUMN IF NOT EXISTS is_delisted_snapshot_date DATE""",
    # One explicit-migration scan converts an existing append-only deployment
    # into the bounded read model. Runtime never rebuilds this from history.
    # Re-running the migration is deterministic and repairs the projection from
    # published/legacy evidence rather than trusting a stale derived row.
    """INSERT INTO feed_universe_current
          (permaticker,ticker,category,category_snapshot_date,
           sector,sector_snapshot_date,
           related_tickers,related_tickers_snapshot_date,
           first_price_date,last_price_date,
           is_delisted,is_delisted_snapshot_date,snapshot_date)
        SELECT u.permaticker,u.ticker,
          (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          MAX(u.snapshot_date) FILTER (WHERE u.category IS NOT NULL),
          (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          MAX(u.snapshot_date) FILTER (WHERE u.sector IS NOT NULL),
          (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers
                                  ORDER BY u.snapshot_date DESC), NULL))[1],
          MAX(u.snapshot_date) FILTER (WHERE u.related_tickers IS NOT NULL),
          MIN(u.first_price_date),MAX(u.last_price_date),
          (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),
                        NULL))[1],
          MAX(u.snapshot_date) FILTER (WHERE u.is_delisted IS NOT NULL),
          MAX(u.snapshot_date)
        FROM sentinel_universe u
        WHERE u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
          AND (u.last_written_run_id IS NULL OR EXISTS (
                SELECT 1 FROM sentinel_corpus_publications p
                 WHERE p.run_id=u.last_written_run_id))
        GROUP BY u.permaticker,u.ticker
        ON CONFLICT (permaticker,ticker) DO UPDATE SET
          category=EXCLUDED.category,
          category_snapshot_date=EXCLUDED.category_snapshot_date,
          sector=EXCLUDED.sector,
          sector_snapshot_date=EXCLUDED.sector_snapshot_date,
          related_tickers=EXCLUDED.related_tickers,
          related_tickers_snapshot_date=EXCLUDED.related_tickers_snapshot_date,
          first_price_date=EXCLUDED.first_price_date,
          last_price_date=EXCLUDED.last_price_date,
          is_delisted=EXCLUDED.is_delisted,
          is_delisted_snapshot_date=EXCLUDED.is_delisted_snapshot_date,
          snapshot_date=EXCLUDED.snapshot_date""",
]


def _newer_value(value: str, observed: str) -> str:
    return f"""CASE
        WHEN EXCLUDED.{observed} IS NULL THEN feed_universe_current.{value}
        WHEN feed_universe_current.{observed} IS NULL
          OR EXCLUDED.{observed} >= feed_universe_current.{observed}
          THEN EXCLUDED.{value}
        ELSE feed_universe_current.{value} END"""


def _newer_date(observed: str) -> str:
    return f"""CASE
        WHEN EXCLUDED.{observed} IS NULL
          THEN feed_universe_current.{observed}
        WHEN feed_universe_current.{observed} IS NULL
          OR EXCLUDED.{observed} >= feed_universe_current.{observed}
          THEN EXCLUDED.{observed}
        ELSE feed_universe_current.{observed} END"""


# Candidate aggregation is over ONE ingest generation, never over retained
# history. The conflict merge preserves latest non-null labels with their actual
# observation dates while expanding the historical listing envelope.
_PROJECT_RUN = f"""
    INSERT INTO feed_universe_current
      (permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date)
    SELECT u.permaticker,u.ticker,
      (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),NULL))[1],
      MAX(u.snapshot_date) FILTER (WHERE u.category IS NOT NULL),
      (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),NULL))[1],
      MAX(u.snapshot_date) FILTER (WHERE u.sector IS NOT NULL),
      (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers ORDER BY u.snapshot_date DESC),
                    NULL))[1],
      MAX(u.snapshot_date) FILTER (WHERE u.related_tickers IS NOT NULL),
      MIN(u.first_price_date),MAX(u.last_price_date),
      (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),NULL))[1],
      MAX(u.snapshot_date) FILTER (WHERE u.is_delisted IS NOT NULL),
      MAX(u.snapshot_date)
    FROM sentinel_universe u
    WHERE {{predicate}}
      AND u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
    GROUP BY u.permaticker,u.ticker
    ON CONFLICT (permaticker,ticker) DO UPDATE SET
      category={_newer_value('category', 'category_snapshot_date')},
      category_snapshot_date={_newer_date('category_snapshot_date')},
      sector={_newer_value('sector', 'sector_snapshot_date')},
      sector_snapshot_date={_newer_date('sector_snapshot_date')},
      related_tickers={_newer_value('related_tickers', 'related_tickers_snapshot_date')},
      related_tickers_snapshot_date={_newer_date('related_tickers_snapshot_date')},
      first_price_date=CASE
        WHEN feed_universe_current.first_price_date IS NULL
          THEN EXCLUDED.first_price_date
        WHEN EXCLUDED.first_price_date IS NULL
          THEN feed_universe_current.first_price_date
        ELSE LEAST(feed_universe_current.first_price_date,
                   EXCLUDED.first_price_date) END,
      last_price_date=CASE
        WHEN feed_universe_current.last_price_date IS NULL
          THEN EXCLUDED.last_price_date
        WHEN EXCLUDED.last_price_date IS NULL
          THEN feed_universe_current.last_price_date
        ELSE GREATEST(feed_universe_current.last_price_date,
                      EXCLUDED.last_price_date) END,
      is_delisted={_newer_value('is_delisted', 'is_delisted_snapshot_date')},
      is_delisted_snapshot_date={_newer_date('is_delisted_snapshot_date')},
      snapshot_date=GREATEST(feed_universe_current.snapshot_date,
                             EXCLUDED.snapshot_date)
"""


def project_run(conn, *, run_id: str) -> int:
    """Merge one candidate generation; caller owns the publication transaction.

    This function NEVER commits. `publication.publish` invokes it before the
    publication row is committed, so either both projection and publication
    become durable or neither does.
    """
    sql = _PROJECT_RUN.format(predicate="u.last_written_run_id=%s")
    with conn.cursor() as cur:
        cur.execute(sql, (str(run_id),))
        return max(0, int(cur.rowcount or 0))


def project_legacy_snapshot(conn, *, snapshot_date: str) -> int:
    """Merge immediately-visible NULL-provenance rows for one dated snapshot.

    Legacy rows are readable immediately by design. Keeping the projection in
    the same transaction prevents the bounded reader and raw visibility rule
    from disagreeing during upgrades or explicit legacy imports.
    """
    sql = _PROJECT_RUN.format(
        predicate="u.last_written_run_id IS NULL AND u.snapshot_date=%s")
    with conn.cursor() as cur:
        cur.execute(sql, (snapshot_date,))
        return max(0, int(cur.rowcount or 0))
