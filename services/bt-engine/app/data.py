"""bt-engine DB loaders — the only DB-touching code besides main.py's run rows.

Reads the bt_* tables bt-data populated (Sharadar SEP prices, SF1 point-in-time
fundamentals, universe snapshots) into the frames sim.run_simulation expects.
All point-in-time slicing happens INSIDE the sim per day; these loaders just
bound the fetch window (prices back to start − FACTOR_LOOKBACK_DAYS, fundamentals
with as_of_date ≤ end) so nothing after `end` ever enters the process.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.sim import FACTOR_LOOKBACK_DAYS

# ── Memory-lean loading (full-history runs) ───────────────────────────────────
# The naive path — .fetchall() then a list of per-row dicts then pd.DataFrame —
# holds THREE full copies of a 35M-row corpus (~15-20GB peak) and OOM-killed the
# host. We instead STREAM a server-side cursor and build numpy arrays per chunk,
# so peak ≈ the final frame plus one chunk.
#
# dtypes (the other half of the win):
#   ticker → pandas Categorical (int32 codes + one small dictionary): 35M
#            repeated strings ~2GB → ~140MB.
#   prices → float32 by default: halves 1.1GB of price columns. Relative error
#            ~6e-8, i.e. ~1e-7 on a computed return — utterly negligible next to
#            the 10bps cost model, and determinism/truncation invariants are
#            unaffected (same dtype on both sides of every comparison). Set
#            BT_PRICE_FLOAT32=false to force float64 if ever in doubt.
_FLOAT32 = os.getenv("BT_PRICE_FLOAT32", "true").lower() in ("1", "true", "yes")
PRICE_DTYPE = np.float32 if _FLOAT32 else np.float64
LOAD_CHUNK_ROWS = int(os.getenv("BT_LOAD_CHUNK_ROWS", "250000"))
_NUM_COLS = ("open", "close", "adjusted_close", "volume")


async def load_universe(engine, limit: int | None = None) -> tuple[list[str], dict[str, str]]:
    """Tickers + sector map from the LATEST bt_universe snapshot. `limit` keeps
    smoke runs small: top-N by latest dollar volume (deterministic order)."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, sector FROM bt_universe "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM bt_universe) "
            "ORDER BY ticker"
        ))).fetchall()
        tickers = [r[0] for r in rows]
        sector_map = {r[0]: r[1] for r in rows if r[1]}
        if limit and len(tickers) > limit:
            dv = (await conn.execute(text(
                "SELECT ticker FROM ("
                "  SELECT ticker, AVG(close * volume) AS adv FROM bt_prices "
                "  WHERE date > (SELECT MAX(date) FROM bt_prices) - INTERVAL '30 days' "
                "  GROUP BY ticker) x ORDER BY adv DESC NULLS LAST LIMIT :n"
            ), {"n": limit})).fetchall()
            keep = {r[0] for r in dv}
            tickers = [t for t in tickers if t in keep]
    if "SPY" not in tickers:
        tickers.append("SPY")
    return tickers, sector_map


async def load_prices(engine, tickers: list[str], start: date, end: date,
                      on_progress=None) -> pd.DataFrame:
    """Stream bt_prices into a compact frame (categorical ticker, float32 prices).

    on_progress(rows_loaded) is called per chunk so the caller can show that a
    long full-history load is ALIVE (progress_pct sits at 0 until the sim starts,
    which is indistinguishable from stuck).

    Rows arrive already ordered by (ticker, date) — sim.run_simulation relies on
    that and skips its own sort when the order holds, saving another full copy.
    """
    px_from = start - timedelta(days=FACTOR_LOOKBACK_DAYS)
    # `date` comes back as an INTEGER day-number: converting 35M datetime.date
    # objects in Python costs ~45s, while int → datetime64[D] is a free C cast.
    sql = text("SELECT ticker, (date - DATE '1970-01-01') AS day_num, "
               "       open, close, adjusted_close, volume "
               "FROM bt_prices WHERE ticker = ANY(:tk) AND date BETWEEN :f AND :t "
               "ORDER BY ticker, date")
    params = {"tk": tickers, "f": px_from, "t": end}

    code_of: dict[str, int] = {}
    code_parts: list[np.ndarray] = []
    date_parts: list[np.ndarray] = []
    num_parts: dict[str, list[np.ndarray]] = {c: [] for c in _NUM_COLS}
    rows_seen = chunks = 0

    async with engine.connect() as conn:
        result = await conn.stream(sql, params)          # server-side cursor
        async for part in result.partitions(LOAD_CHUNK_ROWS):
            n = len(part)
            if not n:
                continue
            # factorize the chunk (C-level hash) then remap its few distinct
            # tickers into global codes — rows are ticker-ordered, so a chunk
            # holds only a handful of names.
            local, uniques = pd.factorize(np.asarray([r[0] for r in part], dtype=object))
            remap = np.empty(len(uniques), dtype=np.int32)
            for k, u in enumerate(uniques):
                g = code_of.get(u)
                if g is None:
                    g = len(code_of)
                    code_of[u] = g
                remap[k] = g
            code_parts.append(remap[local])
            date_parts.append(
                np.fromiter((r[1] for r in part), dtype=np.int32, count=n)
                .astype("datetime64[D]"))
            for j, col in enumerate(_NUM_COLS, start=2):
                num_parts[col].append(np.fromiter(
                    (np.nan if r[j] is None else float(r[j]) for r in part),
                    dtype=PRICE_DTYPE, count=n))
            rows_seen += n
            chunks += 1
            if on_progress is not None:
                on_progress(rows_seen)
            if chunks % 20 == 0:      # aliveness heartbeat in docker logs
                print(f"[bt-engine] loading prices: {rows_seen:,} rows, "
                      f"{len(code_of):,} tickers", flush=True)

    print(f"[bt-engine] prices loaded: {rows_seen:,} rows, {len(code_of):,} tickers",
          flush=True)
    if not code_parts:
        return pd.DataFrame({"ticker": pd.Categorical([]), "date": pd.to_datetime([]),
                             **{c: np.empty(0, dtype=PRICE_DTYPE) for c in _NUM_COLS}})

    categories = [t for t, _ in sorted(code_of.items(), key=lambda kv: kv[1])]
    data = {
        "ticker": pd.Categorical.from_codes(np.concatenate(code_parts), categories),
        "date": np.concatenate(date_parts).astype("datetime64[ns]"),
    }
    for col in _NUM_COLS:
        data[col] = np.concatenate(num_parts[col])
        num_parts[col].clear()          # free per-column chunks as we go
    code_parts.clear(); date_parts.clear()
    return pd.DataFrame(data)


async def load_fundamentals(engine, tickers: list[str], end: date) -> pd.DataFrame:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
            "       revenue_growth, eps_growth FROM bt_fundamentals "
            "WHERE ticker = ANY(:tk) AND as_of_date <= :t ORDER BY ticker, as_of_date"
        ), {"tk": tickers, "t": end})).fetchall()
    return pd.DataFrame([{
        "ticker": r.ticker, "as_of_date": r.as_of_date,
        "pe_ratio": _f(r.pe_ratio), "pb_ratio": _f(r.pb_ratio), "roe": _f(r.roe),
        "debt_to_equity": _f(r.debt_to_equity),
        "revenue_growth": _f(r.revenue_growth), "eps_growth": _f(r.eps_growth),
    } for r in rows])


def _f(v):
    return float(v) if v is not None else None
