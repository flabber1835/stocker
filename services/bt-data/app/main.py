"""
bt-data — the backtester's own data service. Fetches Sharadar SEP (prices),
SF1 (point-in-time fundamentals), and TICKERS (universe) into bt-postgres.

Runs ONLY on the separate backtest machine (docker-compose.backtest.yml). It has
no connection to the live trading stack — its own DB (BT_DATABASE_URL), its own
provider (Sharadar), no Alpaca, no Alpha Vantage.

Endpoints:
  GET  /health                 — liveness
  POST /jobs/backfill          — one-time historical load (prices+fundamentals+universe)
  POST /jobs/topup             — incremental load since the latest stored date
  GET  /data/coverage          — DATA-DEPTH REPORT (GO/NO-GO: earliest viable start)
  GET  /runs/latest            — last fetch job status
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar

from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.sharadar_client import (data_mode, fetch_table, is_mock,
                                 verify_data_mode)
from app.sharadar_adapter import (
    map_actions_row, map_sep_row, map_sf1_earnings_row, map_sf1_row,
    map_tickers_row, compute_growth,
)

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL (backtester's own DB)")

# DB-side timeouts so a blocked/runaway query can NEVER hang the backfill
# forever (root cause of the "chunk running for 65+ min, no error, no progress"
# wedge): a Postgres lock-wait has no default timeout, so an INSERT…ON CONFLICT
# blocked behind a stray/idle-in-transaction session awaited indefinitely with
# nothing to raise or log. With these, a blocked upsert raises after
# LOCK_TIMEOUT_MS (→ chunk fails with a real repr error → the resumable retry
# self-heals) and any runaway statement dies after STATEMENT_TIMEOUT_MS. Both
# are generous vs. real work (a 5k-row batch upsert is sub-second; the biggest
# read is the coverage aggregate), so they only ever fire on a genuine stall.
# asyncpg applies them as per-connection server settings.
LOCK_TIMEOUT_MS = os.getenv("BT_DB_LOCK_TIMEOUT_MS", "60000")          # 60s
STATEMENT_TIMEOUT_MS = os.getenv("BT_DB_STATEMENT_TIMEOUT_MS", "600000")  # 10 min
IDLE_TX_TIMEOUT_MS = os.getenv("BT_DB_IDLE_TX_TIMEOUT_MS", "120000")   # 2 min
CORPUS_LOCK_KEY = 0x4254_434F_5250_5553

engine = create_async_engine(
    BT_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5,
    connect_args={"server_settings": {
        "lock_timeout": LOCK_TIMEOUT_MS,
        "statement_timeout": STATEMENT_TIMEOUT_MS,
        # also reap a connection this service itself leaves idle-in-transaction
        # (the classic lock holder that wedges the OTHER writer)
        "idle_in_transaction_session_timeout": IDLE_TX_TIMEOUT_MS,
    }})

_INIT_SQL = Path(__file__).resolve().parent.parent / "sql" / "init_bt.sql"

from app.raw_close_coverage import SAMPLE_SESSIONS as _WC_SAMPLE_SESSIONS

_schema_ready = False

_CORPUS_POPULATED_SQL = (
    "EXISTS(SELECT 1 FROM bt_prices) OR "
    "EXISTS(SELECT 1 FROM bt_fundamentals) OR "
    "EXISTS(SELECT 1 FROM bt_earnings) OR "
    "EXISTS(SELECT 1 FROM bt_universe) OR "
    "EXISTS(SELECT 1 FROM bt_actions)"
)


async def _ensure_schema() -> list[str]:
    """Idempotently create the bt_* tables (so the service is self-sufficient even
    if no migrator ran on the backtest box).

    ONE TRANSACTION PER STATEMENT, deliberately. The whole file used to run in a
    single transaction, so ONE failing statement rolled back every other one —
    and the caller swallowed the exception into a WARN, leaving a service that
    reported healthy while missing columns it had just been told to add.

    That is not hypothetical. An `ALTER TABLE bt_universe` was added ~60 lines
    above the `CREATE TABLE bt_universe`, which fails on a fresh database; the
    rollback then also reverted an unrelated `ALTER TABLE bt_prices ADD COLUMN
    close_unadjusted`, and the first symptom was a 500 from a coverage endpoint
    three deploy steps later. Per-statement transactions confine a bad statement
    to itself.

    Returns the failures rather than raising: this is a best-effort bootstrap
    beside a real migrator, and refusing to serve because one idempotent ALTER
    is unhappy would be worse. But they are RETURNED so the caller can log each
    one individually instead of reporting "schema ensure failed" once.
    """
    sql = _INIT_SQL.read_text()
    failures: list[str] = []
    for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as exc:
            first = next((ln for ln in stmt.splitlines()
                          if ln.strip() and not ln.strip().startswith("--")),
                         stmt[:80])
            failures.append(f"{first.strip()[:120]} -> {exc.__class__.__name__}: {exc}")
    return failures


async def _assert_required_schema() -> None:
    """Required publication columns must exist before readiness is reported."""
    async with engine.connect() as conn:
        await conn.execute(text(
            "SELECT version, status, source_mode, updated_at, note "
            "FROM bt_data_version WHERE id=1"))
        await conn.execute(text("SELECT source_mode FROM bt_data_runs LIMIT 0"))
        await conn.execute(text(
            "SELECT revenue, eps FROM bt_fundamentals LIMIT 0"))
        await conn.execute(text(
            "SELECT ticker, fiscal_date_ending, reported_date, reported_eps "
            "FROM bt_earnings LIMIT 0"))
        vintage_index = (await conn.execute(text(
            "SELECT to_regclass('public.uq_bt_earnings_vintage') "
            "IS NOT NULL"))).scalar_one()
        if not vintage_index:
            raise RuntimeError("required bt_earnings vintage index is missing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schema_ready
    _schema_ready = False
    # FAIL LOUDLY before serving: configured for real data without a key used to
    # downgrade silently to a tiny synthetic corpus, and every downstream number
    # stayed shaped like a real backtest — feeding a promotion gate that
    # rewrites the live strategy.
    mode = verify_data_mode()
    print(f"[bt-data] data mode: {mode}"
          + ("  *** SYNTHETIC DATA — results are NOT research-grade ***"
             if mode == "mock" else ""), flush=True)
    # Retry briefly so a cold bt-postgres can finish starting.
    import asyncio
    last_db_error: Exception | None = None
    for attempt in range(30):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except Exception as exc:
            last_db_error = exc
            await asyncio.sleep(2)
    else:
        raise RuntimeError(
            "bt-data database did not become ready after 30 attempts") from last_db_error
    try:
        failures = await _ensure_schema()
        if failures:
            # Each one named. A single aggregate WARN made a schema bootstrap
            # that had silently stopped applying half the file look identical to
            # one that worked.
            print(f"[bt-data] WARN {len(failures)} schema statement(s) FAILED — "
                  f"columns they add are MISSING:", flush=True)
            for f in failures:
                print(f"[bt-data]   {f}", flush=True)
        else:
            print("[bt-data] schema ensured", flush=True)
    except Exception as exc:
        print(f"[bt-data] WARN schema ensure failed: {exc}", flush=True)
    await _assert_required_schema()
    _schema_ready = True
    print("[bt-data] required schema ready", flush=True)
    try:
        yield
    finally:
        _schema_ready = False


#: The last universe write report, so `GET /universe/last-write` can answer
#: "what actually survived?" without anyone parsing container logs. In memory
#: only — it describes the most recent write, not the corpus.
_state_last_universe_report: dict = {}

app = FastAPI(title="bt-data", lifespan=lifespan)


@app.get("/universe/last-write")
async def universe_last_write():
    """attempted / distinct_identities / persisted / rejected / collapsed.

    The acceptance test for the identity migration reads this: valid distinct
    identities must EQUAL persisted identities. Before the migration those two
    could differ by tens of thousands and nothing said so.
    """
    if not _state_last_universe_report:
        return {"available": False,
                "detail": "no universe write since this container started"}
    r = dict(_state_last_universe_report)
    r["available"] = True
    r["identities_match"] = r["distinct_identities"] == r["persisted"]
    return r


@app.get("/health")
async def health():
    if not _schema_ready:
        raise HTTPException(status_code=503,
                            detail="required database/schema readiness has not passed")
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT version::text, status, source_mode, "
            f"({_CORPUS_POPULATED_SQL}) AS populated "
            "FROM bt_data_version "
            "WHERE id=1"))).one()
    if row.status != "READY":
        raise HTTPException(status_code=503,
                            detail=f"corpus is {row.status}, not READY")
    if row.populated and row.source_mode is None:
        raise HTTPException(status_code=503,
                            detail="populated corpus has no bound source_mode")
    return {"status": "ok", "service": "bt-data", "mock": is_mock(),
            "data_mode": data_mode(), "data_version": row.version,
            "corpus_source_mode": row.source_mode}


# ── Fetch-run bookkeeping ──────────────────────────────────────────────────────

async def _open_run(job_type: str, table_name: str) -> str:
    rid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_data_runs "
            "(run_id, job_type, table_name, status, source_mode) "
            "VALUES (:r, :j, :t, 'running', :m)"
        ), {"r": rid, "j": job_type, "t": table_name, "m": data_mode()})
    return rid


def _d(v):
    """Coerce an ISO date string (or date) to datetime.date for asyncpg DATE
    binding. asyncpg rejects str for DATE columns — it needs a real date object."""
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


async def _close_run(rid: str, status: str, rows: int = 0,
                     dmin: Optional[str] = None, dmax: Optional[str] = None,
                     err: Optional[str] = None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE bt_data_runs SET status=:s, rows_written=:n, date_min=:dmin, "
            "date_max=:dmax, completed_at=:now, error_message=:e WHERE run_id=:r"
        ), {"s": status, "n": rows, "dmin": _d(dmin), "dmax": _d(dmax),
            "now": datetime.now(timezone.utc), "e": (err or "")[:2000] or None, "r": rid})


class CorpusPublicationError(RuntimeError):
    """The durable corpus state does not permit another mutation generation."""


async def _release_corpus_writer(conn: AsyncConnection) -> None:
    try:
        if conn.in_transaction():
            await conn.rollback()
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"),
                           {"key": CORPUS_LOCK_KEY})
        await conn.commit()
    finally:
        await conn.close()


async def _reserve_corpus_writer(note: str) -> AsyncConnection | None:
    """Try to fence all readers/writers and durably enter PUBLISHING.

    The session connection stays open for the lifetime of the background job,
    because PostgreSQL session advisory locks are released on connection close.
    PUBLISHING is committed before this function returns, hence before the first
    data-table mutation can occur.
    """
    mode = data_mode()
    if mode == "frozen":
        raise CorpusPublicationError(
            "BT_DATA_MODE=frozen cannot mutate the frozen corpus")
    conn = await engine.connect()
    locked = False
    try:
        locked = bool((await conn.execute(text(
            "SELECT pg_try_advisory_lock(:key)"),
            {"key": CORPUS_LOCK_KEY})).scalar_one())
        await conn.commit()
        if not locked:
            await conn.close()
            return None
        row = (await conn.execute(text(
            "SELECT status, source_mode FROM bt_data_version WHERE id=1"))).one()
        if row.status != "READY":
            raise CorpusPublicationError(
                f"corpus is {row.status}; explicit recovery or destructive "
                "reseed is required before another writer can start")
        if row.source_mode is not None and row.source_mode != mode:
            raise CorpusPublicationError(
                f"corpus source mode is {row.source_mode}, configured writer is "
                f"{mode}; implicit mode mixing is refused")
        if row.source_mode is None:
            populated = bool((await conn.execute(text(
                f"SELECT {_CORPUS_POPULATED_SQL}"))).scalar_one())
            if populated:
                raise CorpusPublicationError(
                    "populated corpus has no source_mode; explicitly reseed it "
                    "before binding a writer mode")
        await conn.execute(text(
            "UPDATE bt_data_version SET status='PUBLISHING', source_mode=:mode, "
            "updated_at=NOW(), note=:note WHERE id=1"),
            {"mode": mode, "note": note[:500]})
        await conn.commit()
        return conn
    except Exception:
        if conn.in_transaction():
            await conn.rollback()
        if locked:
            await _release_corpus_writer(conn)
        else:
            await conn.close()
        raise


async def _publish_ready(conn: AsyncConnection, note: str) -> None:
    result = await conn.execute(text(
        "UPDATE bt_data_version SET version=gen_random_uuid(), status='READY', "
        "updated_at=NOW(), note=:note WHERE id=1 AND status='PUBLISHING'"),
        {"note": note[:500]})
    if result.rowcount != 1:
        raise CorpusPublicationError("lost the durable PUBLISHING generation")
    await conn.commit()


async def _record_incomplete_generation(conn: AsyncConnection, exc: Exception) -> None:
    """Keep the unsafe generation unreadable after any caught failure."""
    if conn.in_transaction():
        await conn.rollback()
    await conn.execute(text(
        "UPDATE bt_data_version SET updated_at=NOW(), note=:note "
        "WHERE id=1 AND status='PUBLISHING'"),
        {"note": f"INCOMPLETE: {exc!r}"[:500]})
    await conn.commit()


T = TypeVar("T")


async def _run_reserved_generation(
    conn: AsyncConnection,
    operation: Callable[[], Awaitable[T]],
    note: str,
) -> T:
    try:
        result = await operation()
        await _publish_ready(conn, note)
        return result
    except Exception as exc:
        await _record_incomplete_generation(conn, exc)
        raise
    finally:
        await _release_corpus_writer(conn)


# ── Writers (upserts) ──────────────────────────────────────────────────────────

async def _upsert_prices(rows: list[dict]) -> int:
    if not rows:
        return 0
    for r in rows:
        r["date"] = _d(r["date"])
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_prices (ticker, date, open, high, low, close, adjusted_close, "
            "close_unadjusted, volume) "
            "VALUES (:ticker, :date, :open, :high, :low, :close, :adjusted_close, "
            ":close_unadjusted, :volume) "
            "ON CONFLICT (ticker, date) DO UPDATE SET "
            "  open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
            "  close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close, "
            "  close_unadjusted=EXCLUDED.close_unadjusted, "
            "  volume=EXCLUDED.volume"
        ), rows)
    return len(rows)


async def _upsert_fundamentals(rows: list[dict]) -> int:
    if not rows:
        return 0
    # strip the helper underscore fields before insert + coerce the date key
    clean = []
    for source in rows:
        row = {k: v for k, v in source.items() if not k.startswith("_")}
        row["revenue"] = source.get("_revenue")
        row["eps"] = source.get("_eps")
        clean.append(row)
    for r in clean:
        r["as_of_date"] = _d(r["as_of_date"])
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_fundamentals (ticker, as_of_date, fiscal_period, pe_ratio, "
            "  pb_ratio, roe, debt_to_equity, revenue_growth, eps_growth, "
            "  market_cap, shares_outstanding, shares_outstanding_prior, "
            "  gross_profit, total_assets, revenue, eps) "
            "VALUES (:ticker, :as_of_date, :fiscal_period, :pe_ratio, :pb_ratio, :roe, "
            "  :debt_to_equity, :revenue_growth, :eps_growth, "
            "  :market_cap, :shares_outstanding, :shares_outstanding_prior, "
            "  :gross_profit, :total_assets, :revenue, :eps) "
            "ON CONFLICT (ticker, as_of_date) DO UPDATE SET "
            "  pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio, roe=EXCLUDED.roe, "
            "  debt_to_equity=EXCLUDED.debt_to_equity, revenue_growth=EXCLUDED.revenue_growth, "
            "  eps_growth=EXCLUDED.eps_growth, market_cap=EXCLUDED.market_cap, "
            "  shares_outstanding=EXCLUDED.shares_outstanding, "
            "  shares_outstanding_prior=EXCLUDED.shares_outstanding_prior, "
            "  gross_profit=EXCLUDED.gross_profit, total_assets=EXCLUDED.total_assets, "
            "  revenue=EXCLUDED.revenue, eps=EXCLUDED.eps"
        ), clean)
    return len(clean)


async def _upsert_bt_earnings(rows: list[dict]) -> int:
    """Point-in-time quarterly EPS. Separate table (not a bt_fundamentals column)
    because its natural key is the FISCAL PERIOD, while bt_fundamentals is keyed
    by the filing date — one restatement can publish two filings describing the
    same quarter."""
    if not rows:
        return 0
    for r in rows:
        r["fiscal_date_ending"] = _d(r["fiscal_date_ending"])
        r["reported_date"] = _d(r["reported_date"])
    # Only exact duplicate vintages collapse. A different reported_date is a
    # later point-in-time revision and remains a separate row.
    dedup: dict[tuple, dict] = {}
    for r in rows:
        key = (r["ticker"], r["fiscal_date_ending"], r["reported_date"])
        dedup[key] = r
    rows = list(dedup.values())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_earnings (ticker, fiscal_date_ending, reported_date, "
            "  reported_eps) "
            "VALUES (:ticker, :fiscal_date_ending, :reported_date, :reported_eps) "
            "ON CONFLICT (ticker, fiscal_date_ending, reported_date) DO UPDATE SET "
            "  reported_eps=EXCLUDED.reported_eps"
        ), rows)
    return len(rows)


def coerce_universe_dates(rows: list[dict]) -> list[dict]:
    """Coerce EVERY date-typed column to datetime.date before binding.

    asyncpg rejects a str for a DATE column outright — `invalid input for query
    argument $5 ... ('str' object)`. `snapshot_date` was coerced from the start;
    when first_price_date/last_price_date were added to the INSERT they were
    not, and the whole bt_universe stage failed at the end of a multi-hour
    backfill. Split out as a pure function so the coercion is TESTABLE without a
    database — the mapper tests passed happily while this path was broken."""
    for r in rows:
        for col in ("snapshot_date", "first_price_date", "last_price_date"):
            if col in r:
                r[col] = _d(r[col])
        # related_tickers arrives from the mapper as a SORTED list. Flattened to
        # a space-joined string for the TEXT column; the sort is what makes the
        # issuer key stable, so it is preserved rather than re-derived on read.
        rt = r.get("related_tickers")
        if isinstance(rt, (list, tuple)):
            r["related_tickers"] = " ".join(rt) or None
    return rows


#: A permaticker is Sharadar's PERMANENT security id. Anything that is not a
#: non-empty string is not an identity, and a row without one cannot be keyed,
#: resolved, or distinguished from another company sharing its symbol.
def valid_permaticker(v) -> str | None:
    """The single definition of a usable identity, so the writer, the report and
    the tests cannot disagree about what 'valid' means."""
    if v is None:
        return None
    t = str(v).strip()
    # 'N/A' is a real value in this vendor's data — see docs/data-sources.md
    # "Defect D1", where the same sentinel reached a delivered-security field
    # through an `or None` that looked total and was not.
    if not t or t.upper() in {"N/A", "NA", "NONE", "NULL"}:
        return None
    return t


def partition_universe_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split mapped rows into (keepable, rejected, collapsed) — PURE.

    Pure and separate so the counts are testable without a database, which is
    the whole lesson of `coerce_universe_dates` above.

    REJECTED are rows with no usable permaticker. They cannot be keyed and every
    identity-aware reader already filters them out; they are counted and named
    rather than dropped in silence.

    COLLAPSED are second and subsequent rows for one (snapshot_date,
    permaticker). Sharadar TICKERS carries a row per source table, so one
    security can legitimately arrive several times in a single fetch. The
    survivor is chosen DETERMINISTICALLY — richest row first, then by ticker —
    because 'whichever the API returned last' is exactly the non-determinism
    this migration exists to remove, and moving it from the database to the
    writer would not be a fix.
    """
    keep: dict[tuple, dict] = {}
    rejected: list[dict] = []
    collapsed: list[dict] = []

    def richness(r: dict) -> tuple:
        # Prefer the row that actually carries the listing window and category:
        # a sparser duplicate overwriting a fuller one loses point-in-time data.
        return (r.get("decision_metadata_complete") is True,
                r.get("first_price_date") is not None,
                r.get("last_price_date") is not None,
                r.get("category") is not None,
                r.get("related_tickers") is not None)

    for r in rows:
        pt = valid_permaticker(r.get("permaticker"))
        if pt is None:
            rejected.append(r)
            continue
        r["permaticker"] = pt
        k = (r.get("snapshot_date"), pt)
        prior = keep.get(k)
        if prior is None:
            keep[k] = r
            continue
        winner, loser = ((r, prior)
                         if (richness(r), str(r.get("ticker") or "")) >
                            (richness(prior), str(prior.get("ticker") or ""))
                         else (prior, r))
        keep[k] = winner
        collapsed.append(loser)

    return list(keep.values()), rejected, collapsed


async def _upsert_universe(rows: list[dict], snapshot_date=None) -> dict:
    """Write one universe snapshot and REPORT WHAT SURVIVED.

    Returns a report, not a row count. The previous version returned
    `len(rows)` — rows ATTEMPTED — which is how 49,834 attempted against 21,733
    stored read as unremarkable for months: a ~56% loss to key collisions,
    reported by a number that looked like an answer. A writer that cannot say
    what it stored cannot be audited, so `persisted` here is MEASURED with a
    query after the fact rather than inferred from the input.
    """
    keep, rejected, collapsed = partition_universe_rows(list(rows))
    report = {
        "attempted": len(rows),
        "distinct_identities": len(keep),
        "persisted": 0,
        "rejected_no_permaticker": len(rejected),
        "duplicate_identity_collapsed": len(collapsed),
        # NAMED, not just counted: a bare total cannot distinguish a handful of
        # odd rows from a systematic mapping failure.
        "rejected_sample": sorted({str(r.get("ticker")) for r in rejected})[:20],
        "collapsed_sample": sorted({str(r.get("ticker")) for r in collapsed})[:20],
    }
    if not keep:
        return report

    coerce_universe_dates(keep)
    snap = snapshot_date or keep[0].get("snapshot_date")
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_universe (snapshot_date, ticker, name, sector, "
            "  first_price_date, last_price_date, is_delisted, category, "
            "  permaticker, related_tickers, decision_metadata_complete) "
            "VALUES (:snapshot_date, :ticker, :name, :sector, "
            "  :first_price_date, :last_price_date, :is_delisted, :category, "
            "  :permaticker, :related_tickers, :decision_metadata_complete) "
            # THE KEY IS THE IDENTITY, not the symbol. `ticker` is updated like
            # any other attribute — a security that changed symbol keeps its row
            # instead of forking into two.
            "ON CONFLICT (snapshot_date, permaticker) DO UPDATE SET "
            "  ticker=EXCLUDED.ticker, "
            "  name=EXCLUDED.name, sector=EXCLUDED.sector, "
            "  first_price_date=EXCLUDED.first_price_date, "
            "  last_price_date=EXCLUDED.last_price_date, "
            "  is_delisted=EXCLUDED.is_delisted, category=EXCLUDED.category, "
            "  related_tickers=EXCLUDED.related_tickers, "
            "  decision_metadata_complete=EXCLUDED.decision_metadata_complete"
        ), keep)
        report["persisted"] = (await conn.execute(text(
            "SELECT count(*) FROM bt_universe "
            " WHERE snapshot_date = :d AND permaticker IS NOT NULL"),
            {"d": _d(snap)})).scalar_one()
    return report


def coerce_action_dates(rows: list[dict]) -> list[dict]:
    """Coerce `date` to datetime.date before binding.

    Same trap the bt_universe stage fell into, and it fails in the same place:
    asyncpg rejects a str for a DATE column outright, and the mapper tests pass
    happily while this path is broken because they never touch a driver. Pure
    and separate so the coercion is testable without a database.
    """
    for r in rows:
        if "date" in r:
            r["date"] = _d(r["date"])
    return rows


async def _upsert_actions(rows: list[dict]) -> int:
    if not rows:
        return 0
    coerce_action_dates(rows)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_actions (ticker, date, action, name, value, "
            "  contraticker, contraname) "
            "VALUES (:ticker, :date, :action, :name, :value, "
            "  :contraticker, :contraname) "
            "ON CONFLICT (ticker, date, action) DO UPDATE SET "
            "  name=EXCLUDED.name, value=EXCLUDED.value, "
            "  contraticker=EXCLUDED.contraticker, "
            "  contraname=EXCLUDED.contraname"
        ), rows)
    return len(rows)


async def _load_actions(date_from: str, date_to: str,
                        job_type: str = "backfill") -> int:
    """SHARADAR/ACTIONS → bt_actions. The AUTHORITATIVE corporate-action stream.

    Its own stage, and its own bt_data_runs row, for the reason the SF1 stage
    learned the hard way: a stage that can only be replayed by re-running a
    multi-hour price backfill is a stage nobody replays. ACTIONS is small
    (thousands of rows, not millions), so it is fetched whole rather than
    chunked by year.

    Buffered rather than streamed to the DB: the whole table is a few MB, and a
    single upsert keeps the stage atomic — a half-written action stream is worse
    than none, because the replay would treat the missing half as "no event".
    """
    rid = await _open_run(job_type, "bt_actions")
    try:
        rows, skipped = [], 0
        async for raw in fetch_table("ACTIONS",
                                     params={"date.gte": date_from,
                                             "date.lte": date_to}):
            m = map_actions_row(raw)
            if m:
                rows.append(m)
            else:
                skipped += 1
        total = await _upsert_actions(rows)
        await _close_run(rid, "success", total, date_from, date_to,
                         err=f"skipped_unusable={skipped}" if skipped else None)
        print(f"[bt-data] ACTIONS: {total} rows ({skipped} unusable skipped)",
              flush=True)
        return total
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise


# ── Backfill ───────────────────────────────────────────────────────────────────

def year_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Pure: split [date_from, date_to] into calendar-year slices (inclusive).
    The SEP price fetch is ~3000 cursor pages over hours; chunking makes each
    slice a separately-committed, separately-resumable unit so a failure loses
    ONE chunk, not the whole night."""
    f, t = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if f > t:
        raise ValueError("date range must be ordered start <= end")
    out = []
    y = f.year
    while y <= t.year:
        cf = max(f, date(y, 1, 1))
        ct = min(t, date(y, 12, 31))
        out.append((cf.isoformat(), ct.isoformat()))
        y += 1
    return out


# Completed-chunk markers live in bt_data_runs as job_type='backfill_chunk'
# success rows whose error_message carries 'CHUNK:<from>..<to>:<tickers|ALL>'
# (zero schema change; error_message is unused on success rows). A re-POSTed
# backfill skips chunks already marked complete — resume instead of
# restart-from-zero. A skip additionally requires the DATA to actually be
# present in the chunk's range, so a TRUNCATE (clean restart) self-invalidates
# stale markers instead of skipping everything into an empty table.
_CHUNK_PREFIX = "CHUNK:"


async def _completed_chunks(table: str) -> set:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT error_message FROM bt_data_runs "
            "WHERE job_type='backfill_chunk' AND table_name=:t "
            "AND status='success' AND error_message LIKE :pfx"),
            {"t": table, "pfx": _CHUNK_PREFIX + "%"})).fetchall()
    return {r[0] for r in rows}


async def _chunk_has_data(cf: str, ct: str) -> bool:
    async with engine.connect() as conn:
        return bool((await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM bt_prices WHERE date BETWEEN :f AND :t)"),
            {"f": _d(cf), "t": _d(ct)})).scalar())


# Watchdog ceiling per year-chunk (~28 min typical). A hang trips this →
# TimeoutError → chunk fails → resume. Never fires on legitimate work.
CHUNK_TIMEOUT_SECS = float(os.getenv("BT_CHUNK_TIMEOUT_SECS", "2700"))  # 45 min


async def _load_price_chunk(cf: str, ct: str, tickers: Optional[str]):
    """Fetch+upsert one year of SEP prices. Returns (rows, dmin, dmax).
    Pulled out so the caller can wrap it in asyncio.wait_for (the watchdog)."""
    params = {"date.gte": cf, "date.lte": ct}
    if tickers:
        params["ticker"] = tickers
    batch, ctotal, cdmin, cdmax = [], 0, None, None
    async for raw in fetch_table("SEP", params=params):
        m = map_sep_row(raw)
        if m["adjusted_close"] is None:
            continue
        batch.append(m)
        cdmin = m["date"] if cdmin is None or m["date"] < cdmin else cdmin
        cdmax = m["date"] if cdmax is None or m["date"] > cdmax else cdmax
        if len(batch) >= 5000:
            ctotal += await _upsert_prices(batch); batch = []
    ctotal += await _upsert_prices(batch)
    return ctotal, cdmin, cdmax


# Benchmark ETFs (SPY etc.) are NOT in Sharadar SEP — that table is individual
# EQUITIES only. Funds/ETFs live in the SFP (Sharadar Fund Prices) table. The
# backtester needs SPY for regime detection + benchmark, so it is fetched
# separately from SFP into the same bt_prices table (identical column shape, so
# map_sep_row applies unchanged). Without this the full equity load still leaves
# spy.rows=0 and coverage go=false.
BENCHMARK_TICKERS = os.getenv("BT_BENCHMARK_TICKERS", "SPY,QQQ,IWM,SOXX")
BENCHMARK_SYMBOLS = tuple(
    symbol.strip().upper() for symbol in BENCHMARK_TICKERS.split(",")
    if symbol.strip())


def _equity_frontier_sql() -> tuple[str, dict[str, str]]:
    params = {f"benchmark_{i}": symbol
              for i, symbol in enumerate(BENCHMARK_SYMBOLS)}
    if not params:
        return "SELECT MAX(date) FROM bt_prices", {}
    placeholders = ",".join(f":{name}" for name in params)
    return (f"SELECT MAX(date) FROM bt_prices WHERE ticker NOT IN ({placeholders})",
            params)


async def _load_benchmarks(date_from: str, date_to: str) -> int:
    """Fetch benchmark ETFs from SFP into bt_prices.

    Failure propagates to the whole generation. Earlier stages may already be
    committed, so publishing READY here would cite a partial corpus under a new
    identity; the durable PUBLISHING marker must remain instead.
    """
    rid = await _open_run("backfill", "bt_benchmarks")
    try:
        params = {"date.gte": date_from, "date.lte": date_to,
                  "ticker": BENCHMARK_TICKERS}
        batch, total = [], 0
        async for raw in fetch_table("SFP", params=params):
            m = map_sep_row(raw)          # SFP shares SEP's price column shape
            if m["adjusted_close"] is None:
                continue
            batch.append(m)
            if len(batch) >= 5000:
                total += await _upsert_prices(batch); batch = []
        total += await _upsert_prices(batch)
        await _close_run(rid, "success", total, err=f"BENCHMARKS:{BENCHMARK_TICKERS}")
        print(f"[bt-data] benchmarks {BENCHMARK_TICKERS} DONE ({total} rows)", flush=True)
        return total
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        print(f"[bt-data] benchmark fetch FAILED: {exc}", flush=True)
        raise


async def _load_prior_fundamental_context(
    tickers: list[str], before: str,
) -> dict[str, list[dict]]:
    """Load the four prior filings needed by a narrow incremental SF1 fetch."""
    if not tickers:
        return {}
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "WITH ranked AS ("
            " SELECT ticker, as_of_date, revenue, eps, shares_outstanding, "
            " row_number() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) rn "
            " FROM bt_fundamentals "
            " WHERE ticker = ANY(:tickers) AND as_of_date < :before"
            ") SELECT ticker, as_of_date, revenue, eps, shares_outstanding "
            "FROM ranked WHERE rn <= 4 ORDER BY ticker, as_of_date"),
            {"tickers": tickers, "before": _d(before)})).fetchall()
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row.ticker, []).append({
            "ticker": row.ticker,
            "as_of_date": row.as_of_date,
            "_revenue": row.revenue,
            "_eps": row.eps,
            "shares_outstanding": row.shares_outstanding,
        })
    return out


async def _load_fundamentals(date_from: str, date_to: str,
                             tickers: Optional[str], job_type: str) -> int:
    """SF1 (ARQ) → bt_fundamentals + bt_earnings. Returns rows written.

    Extracted from _run_backfill so it can be re-run ON ITS OWN. That matters:
    every column added to the SF1 mapping (market_cap and shares_outstanding in
    2026-07, gross_profit and total_assets in 2026-08) is NULL on existing rows
    until this stage runs again, and the only way to re-run it used to be a full
    backfill — which redoes the ~35M-row price corpus first, for hours, to fix
    columns prices have nothing to do with. A stage that cannot be replayed
    independently is a stage nobody replays.

    The upserts are ON CONFLICT DO UPDATE keyed on (ticker, as_of_date), so
    re-running is idempotent: existing rows gain the new columns in place and the
    price corpus is untouched.
    """
    rid = await _open_run(job_type, "bt_fundamentals")
    try:
        params = {"dimension": "ARQ", "datekey.gte": date_from, "datekey.lte": date_to}
        if tickers:
            params["ticker"] = tickers
        # Group by ticker to compute YoY growth (this quarter vs ~4 filings ago),
        # but upsert PER TICKER and free each block as we go — never hold two
        # full-universe copies in memory at once (the whole-universe SF1 buffer
        # was an OOM risk after prices finished on a RAM-tight NAS).
        per_ticker: dict[str, list[dict]] = {}
        async for raw in fetch_table("SF1", params=params):
            m = map_sf1_row(raw)
            if m is None:
                continue
            per_ticker.setdefault(m["ticker"], []).append(m)
        prior_context = await _load_prior_fundamental_context(
            list(per_ticker), date_from)
        total = 0
        earnings_total = 0
        for t in list(per_ticker.keys()):
            rows = per_ticker.pop(t)          # free this ticker's block after use
            rows.sort(key=lambda r: r["as_of_date"])
            erows = []
            history = [*prior_context.pop(t, []), *rows]
            offset = len(history) - len(rows)
            for i, r in enumerate(rows, start=offset):
                prior = history[i - 4] if i >= 4 else None  # ~year-ago quarter
                r["revenue_growth"] = compute_growth(
                    r.get("_revenue"), prior.get("_revenue") if prior else None)
                r["eps_growth"] = compute_growth(
                    r.get("_eps"), prior.get("_eps") if prior else None)
                # issuance = shares_now / shares_year_ago − 1, computed by the
                # factor step; it needs the year-ago LEVEL, not a ratio, so the
                # same rows[i-4] anchor the growth fields use is carried across.
                r["shares_outstanding_prior"] = (
                    prior.get("shares_outstanding") if prior else None)
                er = map_sf1_earnings_row(r)
                if er:
                    erows.append(er)
            total += await _upsert_fundamentals(rows)
            earnings_total += await _upsert_bt_earnings(erows)
        print(f"[bt-data] SF1: {total} fundamentals rows, {earnings_total} "
              f"earnings rows", flush=True)
        await _close_run(rid, "success", total)
        return total
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise


async def _load_universe(snapshot_date: str, job_type: str) -> dict:
    """TICKERS → bt_universe for one snapshot date. Returns the WRITE REPORT.

    Its own function so it can be re-run ALONE. Every column added to this
    mapping is invisible in an existing corpus until the stage is replayed, and
    the failure is silent in the worst way: `permaticker` was mapped correctly
    and NULL in all 151,095 deployed rows, because the data predated the column.
    `load_meta` filters `WHERE permaticker IS NOT NULL`, so a Wealth Core
    rehearsal saw ZERO securities, admitted nothing, and completed successfully
    reporting a 0% return over 753 sessions.

    Same shape as the SF1 gp/assets gap and the first_price_date gap before it:
    already fetched, then thrown away, and then not replayable without redoing
    the 35M-row price corpus.
    """
    rid = await _open_run(job_type, "bt_universe")
    try:
        rows = []
        async for raw in fetch_table("TICKERS"):
            m = map_tickers_row(raw, snapshot_date)
            if m:
                rows.append(m)
        report = await _upsert_universe(rows, snapshot_date)
        total = report["persisted"]
        await _close_run(rid, "success", total)
        # EVERY category on one line, because the failure this replaces was a
        # single number that looked like an answer. attempted != persisted is
        # now readable rather than something you have to go and measure.
        print(f"[bt-data] universe @ {snapshot_date}: "
              f"attempted={report['attempted']} "
              f"distinct_identities={report['distinct_identities']} "
              f"persisted={report['persisted']} "
              f"rejected_no_permaticker={report['rejected_no_permaticker']} "
              f"duplicate_identity_collapsed={report['duplicate_identity_collapsed']}",
              flush=True)
        if report["rejected_no_permaticker"]:
            print(f"[bt-data]   rejected sample: {report['rejected_sample']}",
                  flush=True)
        if report["duplicate_identity_collapsed"]:
            print(f"[bt-data]   collapsed sample: {report['collapsed_sample']}",
                  flush=True)
        _state_last_universe_report.clear()
        _state_last_universe_report.update(report)
        return report
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise


async def _run_backfill(date_from: str, date_to: str, tickers: Optional[str],
                        job_type: str = "backfill") -> None:
    # Prices (SEP) — chunked by calendar year, resumable. Each chunk commits
    # and marks itself complete; a re-run after ANY failure skips completed
    # chunks instead of re-downloading 20 years from scratch.
    rid = await _open_run(job_type, "bt_prices")
    try:
        chunks = year_chunks(date_from, date_to)
        done = await _completed_chunks("bt_prices") if job_type == "backfill" else set()
        total, dmin, dmax = 0, None, None
        for cf, ct in chunks:
            marker = f"{_CHUNK_PREFIX}{cf}..{ct}:{tickers or 'ALL'}"
            if marker in done and await _chunk_has_data(cf, ct):
                print(f"[bt-data] prices chunk {cf}..{ct} already complete — skipped",
                      flush=True)
                continue
            crid = await _open_run("backfill_chunk", "bt_prices")
            try:
                # Per-chunk watchdog: a normal year is ~28 min, so this ceiling
                # never trips on real work but GUARANTEES no chunk can hang the
                # backfill forever, whatever the cause (DB lock, stuck read,
                # anything). asyncio.wait_for cancels the coroutine on timeout →
                # the chunk fails with a real error → the resume picks it up.
                ctotal, cdmin, cdmax = await asyncio.wait_for(
                    _load_price_chunk(cf, ct, tickers), timeout=CHUNK_TIMEOUT_SECS)
                await _close_run(crid, "success", ctotal, cdmin, cdmax, err=marker)
                done.add(marker)
                print(f"[bt-data] prices chunk {cf}..{ct} DONE ({ctotal} rows)",
                      flush=True)
            except Exception as exc:
                await _close_run(crid, "failed", err=repr(exc)[:1500])
                raise
            total += ctotal
            dmin = cdmin if dmin is None or (cdmin and cdmin < dmin) else dmin
            dmax = cdmax if dmax is None or (cdmax and cdmax > dmax) else dmax
        await _close_run(rid, "success", total, dmin, dmax)
    except Exception as exc:
        # repr, not str: several exception types (ReadTimeout, MemoryError)
        # stringify to '' — the "failed with no error message" mystery rows.
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise

    # Benchmark ETFs (SPY etc.) from SFP — the SEP load above is equities-only.
    await _load_benchmarks(date_from, date_to)

    await _load_fundamentals(date_from, date_to, tickers, job_type)

    # Corporate actions (ACTIONS) — the authoritative split / terminal stream.
    # AFTER prices, because a reader that has actions but no prices would see
    # events on securities it cannot value; the reverse degrades to today's
    # derived-split behaviour, which is a documented and tested fallback.
    await _load_actions(date_from, date_to, job_type)

    # Universe snapshot (TICKERS, as-of date_to). One snapshot for the backfill end;
    # the engine treats it as the listed set (delisted names still in bt_prices).
    await _load_universe(date_to, job_type)


# In-process guard: a backfill/topup is a long single-writer job. Without this,
# a repeated POST spawns ANOTHER background task, and N of them then starve the
# 8-connection pool and lock each other row-by-row on bt_prices upserts — the
# "five running tasks, zero progress" pileup. The flag lives in the process, so
# a container restart (which kills all tasks) correctly clears it; stale
# 'running' rows in bt_data_runs (orphaned by a restart) do NOT falsely block a
# fresh job. Check-then-set is atomic under asyncio (no await between them).
_job_active = False


async def _schedule_mutation(
    background_tasks: BackgroundTasks,
    *,
    note: str,
    operation: Callable[[], Awaitable[object]],
) -> bool:
    """Reserve the DB writer before returning an accepted HTTP response."""
    global _job_active
    try:
        reservation = await _reserve_corpus_writer(note)
    except CorpusPublicationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if reservation is None:
        return False
    _job_active = True

    async def _guarded() -> None:
        global _job_active
        try:
            await _run_reserved_generation(reservation, operation, note)
        finally:
            _job_active = False

    background_tasks.add_task(_guarded)
    return True


def _validated_range(date_from: str, date_to: str,
                     *, labels: str = "date_from/date_to") -> tuple[date, date]:
    try:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"{labels} must be ISO YYYY-MM-DD") from exc
    if start > end:
        raise HTTPException(status_code=400,
                            detail=f"{labels} must be ordered start <= end")
    return start, end


@app.post("/jobs/backfill")
async def start_backfill(background_tasks: BackgroundTasks,
                         date_from: str, date_to: str,
                         tickers: Optional[str] = None):
    """Kick off a one-time historical load. date_from/date_to are ISO dates;
    tickers is an optional comma-separated subset (default: full Sharadar universe).

    Refuses (returns already_running) if a backfill/topup is already in flight —
    re-POSTing does NOT spawn a competing task."""
    _validated_range(date_from, date_to)
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    started = await _schedule_mutation(
        background_tasks,
        note=f"backfill {date_from}..{date_to}:{tickers or 'ALL'}",
        operation=lambda: _run_backfill(date_from, date_to, tickers))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "date_from": date_from, "date_to": date_to,
            "tickers": tickers or "ALL", "mock": is_mock(),
            "data_mode": data_mode()}


# Re-fetch this many days behind MAX(date) on topup: upserts make the overlap
# free, and it picks up Sharadar restatements/late-published rows near the edge.
TOPUP_OVERLAP_DAYS = int(os.getenv("TOPUP_OVERLAP_DAYS", "5"))


@app.post("/jobs/fetch-benchmarks")
async def start_fetch_benchmarks(background_tasks: BackgroundTasks,
                                 date_from: str = "2004-01-01",
                                 date_to: Optional[str] = None):
    """Load ONLY the benchmark ETFs (SPY etc.) from SFP into bt_prices — the
    fast fix for 'equities loaded but spy.rows=0 / go=false', without re-running
    the full backfill. Idempotent (upserts)."""
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress"}
    from zoneinfo import ZoneInfo
    dt = date_to or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    _validated_range(date_from, dt)
    started = await _schedule_mutation(
        background_tasks,
        note=f"benchmarks {date_from}..{dt}",
        operation=lambda: _load_benchmarks(date_from, dt))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "job": "fetch-benchmarks",
            "tickers": BENCHMARK_TICKERS, "date_from": date_from, "date_to": dt,
            "mock": is_mock(), "data_mode": data_mode()}


@app.post("/jobs/topup")
async def start_topup(background_tasks: BackgroundTasks):
    """Incremental load: resume from the latest stored price date (minus a small
    restatement overlap) through today. Refused (409) while the DB is empty —
    topup extends a backfill, it cannot substitute for one; run /jobs/backfill
    first. bt-scheduler fires this nightly."""
    frontier_sql, frontier_params = _equity_frontier_sql()
    async with engine.connect() as conn:
        max_date = (await conn.execute(
            text(frontier_sql), frontier_params)).scalar()
    if max_date is None:
        raise HTTPException(status_code=409,
                            detail="bt_prices is empty — run /jobs/backfill first")
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    date_from = (max_date - timedelta(days=TOPUP_OVERLAP_DAYS)).isoformat()
    # Trading-calendar date, not container-UTC (audit F5): after the ET close,
    # UTC is already tomorrow — harmless with upserts, but ET keeps run rows
    # and Sharadar date params speaking the same calendar.
    from zoneinfo import ZoneInfo
    date_to = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    _validated_range(date_from, date_to)
    started = await _schedule_mutation(
        background_tasks,
        note=f"topup {date_from}..{date_to}",
        operation=lambda: _run_backfill(date_from, date_to, None, "topup"))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "job_type": "topup", "date_from": date_from,
            "date_to": date_to, "mock": is_mock(),
            "data_mode": data_mode()}


@app.post("/jobs/backfill-fundamentals")
async def start_fundamentals_backfill(background_tasks: BackgroundTasks,
                                      date_from: str, date_to: str,
                                      tickers: Optional[str] = None):
    """Re-run the SF1 stage ALONE — no prices, no benchmarks, no universe.

    Why this exists as its own endpoint: every column added to the SF1 mapping is
    NULL on existing rows until the stage runs again, and the only way to re-run
    it was /jobs/backfill, which redoes the ~35M-row price corpus first — hours of
    work to fix columns that have nothing to do with prices. A stage that cannot
    be replayed on its own is a stage nobody replays, which is how gross_profit /
    total_assets stayed missing long enough for the wind tunnel to score a quality
    factor live does not compute.

    IDEMPOTENT AND NON-DESTRUCTIVE. The upsert is ON CONFLICT (ticker,
    as_of_date) DO UPDATE, so existing rows gain the new columns in place;
    bt_prices is never touched. Safe to re-run, and safe to interrupt.

    Shares the same single-writer guard as backfill/topup — one long writer at a
    time, or they lock each other row-by-row on the same upserts.
    """
    _validated_range(date_from, date_to)
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    started = await _schedule_mutation(
        background_tasks,
        note=f"fundamentals {date_from}..{date_to}:{tickers or 'ALL'}",
        operation=lambda: _load_fundamentals(
            date_from, date_to, tickers, "backfill_fundamentals"))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "job_type": "backfill_fundamentals",
            "date_from": date_from, "date_to": date_to,
            "tickers": tickers or "ALL", "mock": is_mock(),
            "data_mode": data_mode(),
            "note": "SF1 only — bt_prices is not touched"}


@app.post("/jobs/backfill-actions")
async def start_actions_backfill(background_tasks: BackgroundTasks,
                                 date_from: str, date_to: str):
    """Re-run the ACTIONS stage ALONE — no prices, no fundamentals, no universe.

    Its own endpoint for exactly the reason /jobs/backfill-fundamentals has one:
    the alternative is /jobs/backfill, which redoes the ~35M-row price corpus
    first — hours of work to populate a table of a few thousand rows that has
    nothing to do with prices. That is how a stage becomes one nobody replays,
    and this one will need replaying, because the set of action types the engine
    consumes is going to grow (dividends and ticker changes are already
    sequenced).

    IDEMPOTENT. ON CONFLICT (ticker, date, action) DO UPDATE, so a re-fetch
    corrects terms in place and never duplicates an event. bt_prices is never
    touched. Safe to re-run and safe to interrupt — though note the stage
    commits ONCE at the end, so an interruption leaves the table as it was
    rather than half-written.
    """
    _validated_range(date_from, date_to)
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    started = await _schedule_mutation(
        background_tasks,
        note=f"actions {date_from}..{date_to}",
        operation=lambda: _load_actions(
            date_from, date_to, "backfill_actions"))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "job_type": "backfill_actions",
            "date_from": date_from, "date_to": date_to, "mock": is_mock(),
            "data_mode": data_mode(),
            "note": "ACTIONS only — bt_prices is not touched"}


@app.post("/jobs/backfill-universe")
async def start_universe_backfill(background_tasks: BackgroundTasks,
                                  snapshot_date: Optional[str] = None):
    """Re-run the TICKERS stage ALONE — no prices, no fundamentals, no actions.

    Its own endpoint for the same reason /jobs/backfill-fundamentals and
    /jobs/backfill-actions have theirs, and with a sharper motivating failure.
    `permaticker` was added to the mapping and was NULL in all 151,095 rows of
    the deployed corpus, because that data predated the column. The Wealth Core
    loader keys on it (`WHERE permaticker IS NOT NULL`), so a three-year
    rehearsal loaded ZERO securities, opened no position, and reported a 0%
    return as a SUCCESS.

    Without this endpoint the only remedy is /jobs/backfill, which redoes the
    ~35M-row price corpus first — hours, to repopulate a few thousand rows of
    metadata that have nothing to do with prices. That is how a stage becomes
    one nobody replays.

    IDEMPOTENT. ON CONFLICT (snapshot_date, permaticker) DO UPDATE rewrites every
    mapped column in place, so this both backfills the new ones and corrects
    stale ones. bt_prices is never touched.

    `snapshot_date` is an observation date, not the effective date of TICKERS
    metadata. It defaults to TODAY; the optional parameter exists only so old
    clients receive an explicit refusal instead of silently backdating today's
    delivery. A TICKERS-only retry on the same day updates that observation.
    """
    today = date.today().isoformat()
    snap = snapshot_date or today
    try:
        date.fromisoformat(snap)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="snapshot_date must be ISO YYYY-MM-DD")
    if snap != today:
        raise HTTPException(
            status_code=400,
            detail="snapshot_date is the TICKERS observation date and must be "
                   f"today ({today}); backdating current metadata would "
                   "fabricate point-in-time evidence")
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    started = await _schedule_mutation(
        background_tasks,
        note=f"universe {snap}",
        operation=lambda: _load_universe(snap, "backfill_universe"))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "job_type": "backfill_universe",
            "snapshot_date": snap, "mock": is_mock(), "data_mode": data_mode(),
            "note": "TICKERS only — bt_prices is not touched"}


# ── Data-depth report (GO/NO-GO gate) ──────────────────────────────────────────

async def _approx_rows(conn, table: str) -> int:
    """Planner-statistics row estimate (milliseconds at any size). A COUNT(*)
    over the 35M-row corpus takes 30-60s — longer than bt-scheduler's 30s poll
    timeout, which made every Lab coverage check 'fail' and the UI read
    'no coverage info' while go was true underneath. reltuples is -1 before the
    first ANALYZE; self-heal by ANALYZE (samples, seconds) then fall back to an
    exact count only for tiny/empty tables where it's cheap anyway."""
    q = "SELECT reltuples::bigint FROM pg_class WHERE relname = :t"
    est = (await conn.execute(text(q), {"t": table})).scalar()
    if est is None or est <= 0:
        try:
            await conn.execute(text(f"ANALYZE {table}"))
            est = (await conn.execute(text(q), {"t": table})).scalar()
        except Exception:  # noqa: BLE001 — stats are best-effort
            est = None
    if est is None or est <= 0:
        est = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar() or 0
    return int(est)


async def _distinct_tickers(conn, table: str) -> int:
    """Exact distinct-ticker count via a loose index scan (one index probe per
    ticker, ~ms) instead of COUNT(DISTINCT ...) scanning all 35M rows."""
    return (await conn.execute(text(
        "WITH RECURSIVE t(tk) AS ("
        f"  SELECT MIN(ticker) FROM {table} "
        "  UNION ALL "
        f"  SELECT (SELECT MIN(ticker) FROM {table} WHERE ticker > t.tk) "
        "  FROM t WHERE t.tk IS NOT NULL) "
        "SELECT COUNT(*) FROM t WHERE tk IS NOT NULL"
    ))).scalar() or 0


@app.post("/jobs/backfill-prices")
async def start_price_backfill(background_tasks: BackgroundTasks,
                               start_date: str, end_date: str,
                               tickers: Optional[str] = None,
                               force: bool = True):
    """Re-run the SEP stage ALONE, IGNORING the completed-chunk markers.

    `force=True` by DEFAULT, and that default is the whole point. /jobs/backfill
    is chunk-resumable: it skips any year already marked complete, which is
    correct for resuming an interrupted load and catastrophic for a REPLAY. Every
    chunk of the price corpus is already marked complete, so a re-backfill run
    the ordinary way skips all of them, writes nothing, reports success, and
    leaves close_unadjusted NULL — the exact silent no-op that this endpoint
    exists to avoid. A caller who genuinely wants resume semantics has to ask
    for them.

    IDEMPOTENT AND NON-DESTRUCTIVE: the upsert is ON CONFLICT (ticker, date) DO
    UPDATE, so rows gain the column in place. Nothing is dropped, no volume is
    touched, and an interrupted run leaves a PARTIALLY covered corpus rather
    than a broken one — which is what GET /coverage/raw-close is for.

    Shares the single-writer guard with backfill/topup.
    """
    _validated_range(start_date, end_date, labels="start_date/end_date")
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress"}
    started = await _schedule_mutation(
        background_tasks,
        note=f"prices {start_date}..{end_date}:{tickers or 'ALL'}",
        operation=lambda: _run_price_stage(
            start_date, end_date, tickers, force=force))
    if not started:
        return {"status": "already_running",
                "detail": "another process owns the corpus writer lock"}
    return {"status": "started", "stage": "bt_prices", "force": force,
            "start_date": start_date, "end_date": end_date,
            "tickers": tickers or "ALL", "mock": is_mock()}


async def _run_price_stage(date_from: str, date_to: str,
                           tickers: Optional[str], *, force: bool) -> None:
    """The SEP stage on its own. Chunked by year and resumable within the run;
    `force` decides whether PRIOR runs' completion markers are honoured."""
    rid = await _open_run("backfill_prices", "bt_prices")
    try:
        done = set() if force else await _completed_chunks("bt_prices")
        total, dmin, dmax = 0, None, None
        for cf, ct in year_chunks(date_from, date_to):
            marker = f"{_CHUNK_PREFIX}{cf}..{ct}:{tickers or 'ALL'}"
            if marker in done and await _chunk_has_data(cf, ct):
                print(f"[bt-data] prices chunk {cf}..{ct} skipped (force=False)",
                      flush=True)
                continue
            crid = await _open_run("backfill_chunk", "bt_prices")
            try:
                ctotal, cdmin, cdmax = await asyncio.wait_for(
                    _load_price_chunk(cf, ct, tickers), timeout=CHUNK_TIMEOUT_SECS)
                await _close_run(crid, "success", ctotal, cdmin, cdmax, err=marker)
                print(f"[bt-data] prices chunk {cf}..{ct} DONE ({ctotal} rows)",
                      flush=True)
            except Exception as exc:
                await _close_run(crid, "failed", err=repr(exc)[:1500])
                raise
            total += ctotal
            dmin = cdmin if dmin is None or (cdmin and cdmin < dmin) else dmin
            dmax = cdmax if dmax is None or (cdmax and cdmax > dmax) else dmax
        await _close_run(rid, "success", total, dmin, dmax)
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise


@app.get("/coverage/raw-close")
async def raw_close_coverage(exact: bool = False, hash: bool = False,
                             # Defaults to the module constant rather than a
                             # literal: two places holding the same number is
                             # how the endpoint ended up probing 40 sessions
                             # while the module said 12.
                             sample_sessions: int = _WC_SAMPLE_SESSIONS,
                             hash_start: str = "1990-01-01",
                             hash_end: str = "2100-01-01"):
    """Is the AS-TRADED price domain populated enough for Wealth Core?

    Reported per SESSION and per TICKER, not as one number: a date range with no
    coverage means the backfill did not reach that far and should be re-run,
    while a ticker with no coverage means the vendor has none and re-running
    changes nothing. 97% looks identical in aggregate either way.

    FAST BY DEFAULT: planner row estimates, index-backed date bounds, and
    coverage SAMPLED across ~40 dates spread over the range. The first version
    scanned the whole 35M-row corpus and hit the statement timeout after ten
    minutes, returning a 500 — a diagnostic failing in a way indistinguishable
    from the fault it exists to diagnose.

    `exact=1` runs the full scan for a caller who wants the real counts and can
    wait. `hash=1` additionally hashes the normalised price stream — also slow,
    since it reads every row — so a deployed backtester and wind tunnel can be
    shown to be reading the same data rather than assumed to be.
    """
    from app.raw_close_coverage import build_report
    async with engine.connect() as conn:
        rep = await conn.run_sync(
            lambda sync_conn: build_report(
                sync_conn, exact=exact, sample_sessions=sample_sessions,
                hash_range=(hash_start, hash_end) if hash else None))
    return rep.to_dict()


@app.get("/data/coverage")
async def coverage():
    """Report how deep the stored data goes — the GO/NO-GO gate for choosing a
    backtest start date. A backtest start needs ~1yr of prior price history for
    momentum/low-vol/covariance, plus fundamentals coverage for value/quality/growth.

    Row counts are planner ESTIMATES (see _approx_rows) so this endpoint answers
    in milliseconds at any corpus size; dates and the SPY/GO gate are exact
    (index-backed). The GO decision never depends on an estimated number.
    """
    async with engine.connect() as conn:
        px = {
            "n": await _approx_rows(conn, "bt_prices"),
            "tickers": await _distinct_tickers(conn, "bt_prices"),
            "dmin": (await conn.execute(text("SELECT MIN(date) FROM bt_prices"))).scalar(),
            "dmax": (await conn.execute(text("SELECT MAX(date) FROM bt_prices"))).scalar(),
        }
        fn = {
            "n": await _approx_rows(conn, "bt_fundamentals"),
            "tickers": await _distinct_tickers(conn, "bt_fundamentals"),
            "dmin": (await conn.execute(text(
                "SELECT MIN(as_of_date) FROM bt_fundamentals"))).scalar(),
            "dmax": (await conn.execute(text(
                "SELECT MAX(as_of_date) FROM bt_fundamentals"))).scalar(),
        }
        # SPY is exact and fast: PK-prefix (ticker, date) index scan.
        spy = (await conn.execute(text(
            "SELECT MIN(date) dmin, MAX(date) dmax, COUNT(*) n "
            "FROM bt_prices WHERE ticker='SPY'"
        ))).mappings().first()

    px_min = px["dmin"]
    earliest_start = None
    if px_min is not None:
        # need ~400 calendar days of lookback before the first tradeable day
        from datetime import timedelta as _td
        earliest_start = (px_min + _td(days=400)).isoformat()

    return {
        "prices": {"rows": px["n"], "tickers": px["tickers"],
                   "date_min": str(px["dmin"]) if px["dmin"] else None,
                   "date_max": str(px["dmax"]) if px["dmax"] else None},
        "fundamentals": {"rows": fn["n"], "tickers": fn["tickers"],
                         "date_min": str(fn["dmin"]) if fn["dmin"] else None,
                         "date_max": str(fn["dmax"]) if fn["dmax"] else None},
        "spy": {"rows": spy["n"],
                "date_min": str(spy["dmin"]) if spy["dmin"] else None,
                "date_max": str(spy["dmax"]) if spy["dmax"] else None},
        "earliest_viable_start": earliest_start,
        "go": bool(px["n"] and spy["n"] and earliest_start),
        "notes": "earliest_viable_start = first price date + ~400d lookback; "
                 "SPY required for regime + benchmark.",
    }


@app.get("/runs/latest")
async def runs_latest():
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT run_id, job_type, table_name, status, rows_written, date_min, "
            "date_max, started_at, completed_at, error_message "
            "FROM bt_data_runs ORDER BY started_at DESC LIMIT 10"
        ))).mappings().fetchall()
    return {"runs": [dict(r) for r in rows]}
