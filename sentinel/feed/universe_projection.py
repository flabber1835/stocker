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
old value". Listing bounds follow the same latest-non-null rule as labels during
ordinary seed/daily publication: they are reference-data observations, not
monotonic counters, and a correction may move `firstpricedate` later or
`lastpricedate` earlier.

Publication is the authority boundary. A provenance-tracked candidate is merged
here in the SAME transaction that publishes its run; an unpublished snapshot can
therefore never leak into current planning. Legacy NULL-provenance rows are
already immediately readable under `visible_predicate`, so the legacy writer
merges those rows before its existing commit.

A published identity rebuild is different from an ordinary observation. It is a
complete replacement generation authorized to correct historical membership and
bounds even when its immutable evidence had to use an observation date older
than a previously published snapshot. Runtime replacement and schema
reprojection use the same generation precedence. Later ordinary publications
resume the existing date-based merge semantics.
"""
from __future__ import annotations

IDENTITY_REBUILD_SCHEMA = "sentinel.identity-rebuild/1"


# Reprojection precedence is intentionally three-tiered around the latest
# identity-rebuild publication:
#
#   0  pre-rebuild evidence (may fill sparse fields for retained pairs)
#   1  the complete rebuild generation (wins despite an older snapshot_date)
#   2  later ordinary evidence whose observation date is at least the rebuild
#      candidate date (exactly the runtime `_newer_*` eligibility rule)
#
# A later publication carrying an older raw observation date remains tier 0 and
# therefore cannot acquire authority merely because migration was rerun.
_AUTHORITY_ROWS_CTE = f"""
WITH latest_identity_rebuild AS (
    SELECT p.version,p.run_id,
           (SELECT MAX(baseline.snapshot_date)
              FROM sentinel_universe baseline
             WHERE baseline.last_written_run_id=p.run_id) AS rebuild_snapshot_date
      FROM sentinel_corpus_publications p
     WHERE p.evidence->'identity_rebuild'->>'schema'=
           '{IDENTITY_REBUILD_SCHEMA}'
     ORDER BY p.version DESC
     LIMIT 1
), authority_rows AS (
    SELECT u.permaticker,u.ticker,u.category,u.sector,u.related_tickers,
           u.first_price_date,u.last_price_date,u.is_delisted,u.snapshot_date,
           COALESCE(p.version,0) AS authority_version,
           0 AS replacement_rank
      FROM sentinel_universe u
      LEFT JOIN sentinel_corpus_publications p
        ON p.run_id=u.last_written_run_id
     WHERE NOT EXISTS (SELECT 1 FROM latest_identity_rebuild)
       AND (u.last_written_run_id IS NULL OR p.run_id IS NOT NULL)
    UNION ALL
    SELECT u.permaticker,u.ticker,u.category,u.sector,u.related_tickers,
           u.first_price_date,u.last_price_date,u.is_delisted,u.snapshot_date,
           COALESCE(p.version,0) AS authority_version,
           CASE WHEN u.last_written_run_id=floor.run_id THEN 1 ELSE 0 END
             AS replacement_rank
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
           p.version AS authority_version,
           CASE
             WHEN u.snapshot_date>=floor.rebuild_snapshot_date THEN 2
             ELSE 0
           END AS replacement_rank
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


def _ordered_field(field: str) -> str:
    return f"""(ARRAY_REMOVE(ARRAY_AGG(
      u.{field} ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
                         u.authority_version DESC),NULL))[1]"""


_REBUILD_INSERT = _AUTHORITY_ROWS_CTE + f"""
INSERT INTO feed_universe_current
      (permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date)
SELECT u.permaticker,u.ticker,
  {_ordered_field('category')},
  (ARRAY_REMOVE(ARRAY_AGG(
      CASE WHEN u.category IS NOT NULL THEN u.snapshot_date END
      ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
               u.authority_version DESC),NULL))[1],
  {_ordered_field('sector')},
  (ARRAY_REMOVE(ARRAY_AGG(
      CASE WHEN u.sector IS NOT NULL THEN u.snapshot_date END
      ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
               u.authority_version DESC),NULL))[1],
  {_ordered_field('related_tickers')},
  (ARRAY_REMOVE(ARRAY_AGG(
      CASE WHEN u.related_tickers IS NOT NULL THEN u.snapshot_date END
      ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
               u.authority_version DESC),NULL))[1],
  {_ordered_field('first_price_date')},
  {_ordered_field('last_price_date')},
  {_ordered_field('is_delisted')},
  (ARRAY_REMOVE(ARRAY_AGG(
      CASE WHEN u.is_delisted IS NOT NULL THEN u.snapshot_date END
      ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
               u.authority_version DESC),NULL))[1],
  (ARRAY_AGG(u.snapshot_date
      ORDER BY u.replacement_rank DESC,u.snapshot_date DESC,
               u.authority_version DESC))[1]
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
    # and generation floor, not merely another observation date.
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


_RUN_CANDIDATE = """
SELECT u.permaticker,u.ticker,
  (ARRAY_REMOVE(ARRAY_AGG(u.category ORDER BY u.snapshot_date DESC),NULL))[1]
    AS category,
  MAX(u.snapshot_date) FILTER (WHERE u.category IS NOT NULL)
    AS category_snapshot_date,
  (ARRAY_REMOVE(ARRAY_AGG(u.sector ORDER BY u.snapshot_date DESC),NULL))[1]
    AS sector,
  MAX(u.snapshot_date) FILTER (WHERE u.sector IS NOT NULL)
    AS sector_snapshot_date,
  (ARRAY_REMOVE(ARRAY_AGG(u.related_tickers ORDER BY u.snapshot_date DESC),NULL))[1]
    AS related_tickers,
  MAX(u.snapshot_date) FILTER (WHERE u.related_tickers IS NOT NULL)
    AS related_tickers_snapshot_date,
  (ARRAY_REMOVE(ARRAY_AGG(u.first_price_date ORDER BY u.snapshot_date DESC),NULL))[1]
    AS first_price_date,
  (ARRAY_REMOVE(ARRAY_AGG(u.last_price_date ORDER BY u.snapshot_date DESC),NULL))[1]
    AS last_price_date,
  (ARRAY_REMOVE(ARRAY_AGG(u.is_delisted ORDER BY u.snapshot_date DESC),NULL))[1]
    AS is_delisted,
  MAX(u.snapshot_date) FILTER (WHERE u.is_delisted IS NOT NULL)
    AS is_delisted_snapshot_date,
  MAX(u.snapshot_date) AS snapshot_date
FROM sentinel_universe u
WHERE u.last_written_run_id=%s
  AND u.permaticker IS NOT NULL AND u.ticker IS NOT NULL
GROUP BY u.permaticker,u.ticker
"""


_REPLACE_RUN = """
WITH candidate AS (
""" + _RUN_CANDIDATE + """
)
INSERT INTO feed_universe_current
      (permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date)
SELECT permaticker,ticker,category,category_snapshot_date,
       sector,sector_snapshot_date,
       related_tickers,related_tickers_snapshot_date,
       first_price_date,last_price_date,
       is_delisted,is_delisted_snapshot_date,snapshot_date
  FROM candidate
ON CONFLICT (permaticker,ticker) DO UPDATE SET
  category=CASE WHEN EXCLUDED.category_snapshot_date IS NOT NULL
                THEN EXCLUDED.category ELSE feed_universe_current.category END,
  category_snapshot_date=COALESCE(
      EXCLUDED.category_snapshot_date,
      feed_universe_current.category_snapshot_date),
  sector=CASE WHEN EXCLUDED.sector_snapshot_date IS NOT NULL
              THEN EXCLUDED.sector ELSE feed_universe_current.sector END,
  sector_snapshot_date=COALESCE(
      EXCLUDED.sector_snapshot_date,
      feed_universe_current.sector_snapshot_date),
  related_tickers=CASE
      WHEN EXCLUDED.related_tickers_snapshot_date IS NOT NULL
      THEN EXCLUDED.related_tickers ELSE feed_universe_current.related_tickers END,
  related_tickers_snapshot_date=COALESCE(
      EXCLUDED.related_tickers_snapshot_date,
      feed_universe_current.related_tickers_snapshot_date),
  first_price_date=EXCLUDED.first_price_date,
  last_price_date=EXCLUDED.last_price_date,
  is_delisted=CASE WHEN EXCLUDED.is_delisted_snapshot_date IS NOT NULL
                   THEN EXCLUDED.is_delisted
                   ELSE feed_universe_current.is_delisted END,
  is_delisted_snapshot_date=COALESCE(
      EXCLUDED.is_delisted_snapshot_date,
      feed_universe_current.is_delisted_snapshot_date),
  snapshot_date=EXCLUDED.snapshot_date
"""


_IDENTITY_MISMATCH = """
WITH candidate AS (
""" + _RUN_CANDIDATE + """
)
SELECT COALESCE(candidate.permaticker,current.permaticker) AS permaticker,
       COALESCE(candidate.ticker,current.ticker) AS ticker,
       candidate.first_price_date AS candidate_first,
       current.first_price_date AS current_first,
       candidate.last_price_date AS candidate_last,
       current.last_price_date AS current_last
  FROM candidate
  FULL OUTER JOIN feed_universe_current current
    ON current.permaticker=candidate.permaticker
   AND current.ticker=candidate.ticker
 WHERE candidate.permaticker IS NULL
    OR current.permaticker IS NULL
    OR candidate.first_price_date IS DISTINCT FROM current.first_price_date
    OR candidate.last_price_date IS DISTINCT FROM current.last_price_date
 ORDER BY 1,2
 LIMIT 8
"""


class IdentityProjectionReplacementRefused(RuntimeError):
    """A complete identity-rebuild generation did not replace the projection."""


def _require_identity_rebuild_run(conn, *, run_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,publication_recovery->>'schema'"
            " FROM feed_ingest_runs WHERE run_id=%s AND kind='seed'",
            (str(run_id),))
        row = cur.fetchone()
    if row is None or str(row[0]) != "success" or str(row[1] or "") != (
            IDENTITY_REBUILD_SCHEMA):
        raise IdentityProjectionReplacementRefused(
            f"run {run_id} is not an explicitly authorized successful "
            "identity-rebuild generation")


def _assert_identity_projection(conn, *, run_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(_IDENTITY_MISMATCH, (str(run_id),))
        mismatch = cur.fetchall()
    if mismatch:
        raise IdentityProjectionReplacementRefused(
            "identity-rebuild candidate/current projection mismatch for "
            f"membership or listing bounds: {mismatch}")


def retire_absent_from_run(conn, *, run_id: str) -> int:
    """Atomically replace current identity projection from a complete rebuild.

    This is deliberately destructive only for a durable successful seed whose
    publication-recovery schema explicitly names the identity-rebuild contract.
    Candidate membership and listing bounds replace the prior projection even
    when the immutable candidate snapshot date is older. Sparse non-identity
    labels may retain their prior non-null evidence. Exact membership and
    first/last bounds are asserted before publication can become authoritative.

    Caller owns the publication transaction. A rollback restores the previous
    projection byte-for-byte together with any bar re-key/retirement work.
    """
    writer = str(run_id)
    _require_identity_rebuild_run(conn, run_id=writer)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe"
            " WHERE last_written_run_id=%s"
            "   AND permaticker IS NOT NULL AND ticker IS NOT NULL",
            (writer,))
        source_rows = int(cur.fetchone()[0])
    if source_rows <= 0:
        raise IdentityProjectionReplacementRefused(
            f"identity-rebuild run {writer} has no candidate universe rows")

    with conn.cursor() as cur:
        cur.execute(
            "WITH candidate AS (" + _RUN_CANDIDATE + ")"
            " SELECT COUNT(*) FROM feed_universe_current current"
            " WHERE NOT EXISTS (SELECT 1 FROM candidate"
            "  WHERE candidate.permaticker=current.permaticker"
            "    AND candidate.ticker=current.ticker)",
            (writer,))
        retired = int(cur.fetchone()[0])
        cur.execute(
            "WITH candidate AS (" + _RUN_CANDIDATE + ")"
            " DELETE FROM feed_universe_current current"
            " WHERE NOT EXISTS (SELECT 1 FROM candidate"
            "  WHERE candidate.permaticker=current.permaticker"
            "    AND candidate.ticker=current.ticker)",
            (writer,))
        if int(cur.rowcount or 0) != retired:
            raise IdentityProjectionReplacementRefused(
                "identity-rebuild projection membership changed during the "
                "replacement transaction")
        cur.execute(_REPLACE_RUN, (writer,))
    _assert_identity_projection(conn, run_id=writer)
    return retired


def project_run(conn, *, run_id: str) -> int:
    """Merge one ordinary candidate generation in the publication transaction.

    This function NEVER commits. `publication.publish` invokes it before the
    publication row is committed, so either both projection and publication
    become durable or neither does. For an identity rebuild the projection has
    already been replaced and asserted by `retire_absent_from_run`; merging the
    same candidate here is therefore an idempotent no-op with respect to bounds.
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


__all__ = [
    "DDL", "IDENTITY_REBUILD_SCHEMA", "IdentityProjectionReplacementRefused",
    "project_legacy_snapshot", "project_run", "retire_absent_from_run",
]
