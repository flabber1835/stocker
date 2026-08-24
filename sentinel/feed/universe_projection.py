"""Bounded current-state projection of append-only TICKERS snapshots.

`sentinel_universe` is immutable point-in-time evidence. It intentionally keeps
every dated SHARADAR/TICKERS snapshot, because ticker reuse and historical
listing windows are part of the trading record. It is therefore the wrong
relation for questions whose complexity should be "how many identities exist
now?". Daily full snapshots make those questions scale with corpus age.

`feed_universe_current` is a DERIVED read model, one row per
(permaticker,ticker) pairing. It retains the latest non-null authoritative
listing bounds and labels while keeping current resolver/meta/readiness work
bounded by identity cardinality rather than snapshot cardinality. The `feed_`
name is deliberate: this is rebuildable feed infrastructure, not a new
behavioral/authority-bearing `sentinel_*` relation.

Sparse vendor rows require field-level chronology. A later snapshot can omit a
value that an older one knew, so null means "no new observation", not "erase the
old value". Listing bounds follow the same latest-non-null rule as labels: they
are reference-data observations, not monotonic counters. A correction may move
`firstpricedate` later or `lastpricedate` earlier.

Publication is the authority boundary. A provenance-tracked candidate is merged
here in the SAME transaction that publishes its run; an unpublished snapshot can
therefore never leak into current planning. Legacy NULL-provenance rows are
already immediately readable under `visible_predicate`, so the legacy writer
merges those rows before its existing commit.

A published identity rebuild is also a membership boundary. Pre-rebuild rows are
still retained as immutable field evidence for pairings present in that complete
snapshot, but a pairing omitted by the replacement snapshot must not reappear the
next time schema migration reconstructs this derived table. Later published
snapshots remain free to add genuinely new pairings.
"""
from __future__ import annotations


_AUTHORITY_ROWS_CTE = """
WITH latest_identity_rebuild AS (
    SELECT p.version,p.run_id
      FROM sentinel_corpus_publications p
     WHERE p.evidence->'identity_rebuild'->>'schema'=
           'sentinel.identity-rebuild/1'
     ORDER BY p.version DESC
     LIMIT 1
), authority_rows AS (
    SELECT u.permaticker,u.ticker,u.category,u.sector,u.related_tickers,
           u.first_price_date,u.last_price_date,u.is_delisted,u.snapshot_date,
           COALESCE(p.version,0) AS authority_version
      FROM sentinel_universe u
      LEFT JOIN sentinel_corpus_publications p
        ON p.run_id=u.last_written_run_id
     WHERE NOT EXISTS (SELECT 1 FROM latest_identity_rebuild)
       AND (u.last_written_run_id IS NULL OR p.run_id IS NOT NULL)
    UNION ALL
    SELECT u.permaticker,u.ticker,u.category,u.sector,u.related_tickers,
           u.first_price_date,u.last_price_date,u.is_delisted,u.snapshot_date,
           COALESCE(p.version,0) AS authority_version
      FROM sentinel_universe u
      LEFT JOIN sentinel_corpus_publications p
        ON p.run_id=u.last_written_run_id
      CROSS JOIN latest_identity_rebuild floor
     WHERE (u.last_written_run_id IS NULL OR p.run_id IS NOT NULL)
       AND (p.version IS NULL OR p.version<=floor.version)
       AND EXISTS (
           SELECT 1 FROM sentinel_universe baseline
            WHERE baseline.last_written_run_id=floor.run_id
              AND baseline.permaticker=u.permaticker
              AND baseline.ticker=u.ticker)
    UNION ALL
    SELECT u.permaticker,u.ticker,u.category,u.sector,u.related_tickers,
           u.first_price_date,u.last_price_date,u.is_delisted,u.snapshot_date,
           p.version AS authority_version
      FROM sentinel_universe u
      JOIN sentinel_corpus_publications p
        ON p.run_id=u.last_written_run_id
      CROSS JOIN latest_identity_rebuild floor
     WHERE p.version>floor.version
)
"""


_REBUILD_DELETE = _AUTHORITY_ROWS_CTE + """
, authority_keys AS (
    SELECT DISTINCT permaticker,ticker FROM authority_rows
)
DELETE FROM feed_universe_current c
 WHERE NOT EXISTS (
       SELECT 1 FROM authority_keys authority
        WHERE authority.permaticker=c.permaticker
          AND authority.ticker=c.ticker)
"""


_REBUILD_INSERT = _AUTHORITY_ROWS_CTE + """
INSERT INTO feed_universe_current
      (permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date)
SELECT u.permaticker,u.ticker,
  (ARRAY_REMOVE(ARRAY_AGG(
      u.category ORDER BY u.snapshot_date DESC,u.authority_version DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.category IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(
      u.sector ORDER BY u.snapshot_date DESC,u.authority_version DESC),NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.sector IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(
      u.related_tickers ORDER BY u.snapshot_date DESC,u.authority_version DESC),
      NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.related_tickers IS NOT NULL),
  (ARRAY_REMOVE(ARRAY_AGG(
      u.first_price_date ORDER BY u.snapshot_date DESC,u.authority_version DESC),
      NULL))[1],
  (ARRAY_REMOVE(ARRAY_AGG(
      u.last_price_date ORDER BY u.snapshot_date DESC,u.authority_version DESC),
      NULL))[1],
  (ARRAY_REMOVE(ARRAY_AGG(
      u.is_delisted ORDER BY u.snapshot_date DESC,u.authority_version DESC),
      NULL))[1],
  MAX(u.snapshot_date) FILTER (WHERE u.is_delisted IS NOT NULL),
  MAX(u.snapshot_date)
FROM authority_rows u
WHERE u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
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
  snapshot_date=EXCLUDED.snapshot_date
"""


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
    # Explicit migration reconstructs the bounded read model from published or
    # legacy evidence. The latest identity-rebuild publication is a membership
    # floor: older rows may fill sparse fields only for pairings that generation
    # still names; omitted pairings are durable negative space.
    _REBUILD_DELETE,
    _REBUILD_INSERT,
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


def _newer_bound(value: str) -> str:
    """Latest non-null listing bound; later authority may narrow the interval."""
    return f"""CASE
        WHEN EXCLUDED.{value} IS NULL THEN feed_universe_current.{value}
        WHEN EXCLUDED.snapshot_date >= feed_universe_current.snapshot_date
          THEN EXCLUDED.{value}
        ELSE feed_universe_current.{value} END"""


# Candidate aggregation is over ONE ingest generation, never over retained
# history. The conflict merge preserves latest non-null fields. Listing bounds
# deliberately REPLACE older non-null values when the candidate snapshot is
# newer; LEAST/GREATEST would make a vendor correction unable to narrow.
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
      (ARRAY_REMOVE(ARRAY_AGG(u.first_price_date ORDER BY u.snapshot_date DESC),
                    NULL))[1],
      (ARRAY_REMOVE(ARRAY_AGG(u.last_price_date ORDER BY u.snapshot_date DESC),
                    NULL))[1],
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
      first_price_date={_newer_bound('first_price_date')},
      last_price_date={_newer_bound('last_price_date')},
      is_delisted={_newer_value('is_delisted', 'is_delisted_snapshot_date')},
      is_delisted_snapshot_date={_newer_date('is_delisted_snapshot_date')},
      snapshot_date=GREATEST(feed_universe_current.snapshot_date,
                             EXCLUDED.snapshot_date)
"""


def retire_absent_from_run(conn, *, run_id: str) -> int:
    """Retire membership omitted by one complete replacement candidate.

    Caller owns the publication transaction. The candidate rows are still
    unpublished, so a rollback restores the previous projection exactly.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM feed_universe_current c"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM sentinel_universe candidate"
            "    WHERE candidate.last_written_run_id=%s"
            "      AND candidate.permaticker=c.permaticker"
            "      AND candidate.ticker=c.ticker)",
            (str(run_id),))
        return max(0, int(cur.rowcount or 0))


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
