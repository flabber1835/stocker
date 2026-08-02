"""Score calibration against a real, fully-migrated Postgres.

Two defects in the shipped version were only visible against real SQL, and both
biased the answer rather than erroring:

1. The forward-price CTE selected `date <= :d1` with NO lower bound. A ticker
   that stopped printing after d0 therefore resolved to its OWN baseline price,
   so a DELISTED position scored as exactly FLAT. Delisting for cause
   concentrates in low-ranked names, so this inflated the bottom deciles and
   SHRANK top-minus-bottom — the system's own diagnostic understated its ranking.

2. Ranking runs were selected on status and date only. If factor weights changed
   inside the window, curves produced by DIFFERENT MODELS were averaged into one.
   This repo added `_detect_config_skew` because mixing configs across a single
   chain was a bug; averaging them across a diagnostic is the same bug.

Both are asserted here by seeding the exact shape and reading the numbers back.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_EVAL = os.path.join(_ROOT, "services", "evaluator")

N_TICKERS = 60
HORIZON = 20


class _evaluator_packet_imported:
    def __enter__(self):
        self._saved_path = list(sys.path)
        self._saved_mods = {k: v for k, v in sys.modules.items()
                            if k == "app" or k.startswith("app.")}
        for k in list(self._saved_mods):
            del sys.modules[k]
        sys.path.insert(0, os.path.join(_ROOT, "shared"))
        sys.path.insert(0, _EVAL)
        import app.packet as pk  # noqa: E402
        return pk

    def __exit__(self, *exc):
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        sys.modules.update(self._saved_mods)
        sys.path[:] = self._saved_path
        return False


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _seed(eng, *, config_hash: str, anchor_offsets: list[int],
                delist_worst: int = 0, delist_after_days: int = 200) -> None:
    """Seed daily prices + ranking runs.

    Construction: rank 1 is the best name and forward returns fall monotonically
    with rank, so a working calibration MUST report a positive spread. The
    `delist_worst` names simply stop printing after their anchor — the shape that
    used to be scored as flat.
    """
    today = date.today()
    tickers = [f"C{i:02d}" for i in range(N_TICKERS)]
    async with eng.begin() as conn:
        # SPY + every ticker, daily for 3 years of calendar days (the packet's
        # session list comes from SPY's own dates, so calendar days are fine).
        for t in ["SPY"] + tickers:
            rank_pos = tickers.index(t) if t in tickers else None
            for i in range(1000):
                d = today - timedelta(days=999 - i)
                if t == "SPY":
                    px = 100.0 * (1.0 + 0.0002 * i)
                else:
                    # better rank -> steeper drift, so the decile curve is monotone
                    px = 100.0 * (1.0 + (0.0010 - 0.000018 * rank_pos) * i)
                if (rank_pos is not None and rank_pos >= N_TICKERS - delist_worst
                        and (today - d).days < delist_after_days):
                    break          # stops printing: delisted
                await conn.execute(text(
                    "INSERT INTO daily_prices (ticker, date, open, high, low, close, "
                    "adjusted_close, volume) VALUES (:t, :d, :p, :p, :p, :p, :p, 1000000) "
                    "ON CONFLICT DO NOTHING"), {"t": t, "d": d, "p": round(px, 4)})

        for off in anchor_offsets:
            run_id = str(uuid.uuid4())
            frun = str(uuid.uuid4())
            rank_date = today - timedelta(days=off)
            await conn.execute(text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, score_date) "
                "VALUES (CAST(:r AS uuid), 'calib_test', 'success', :d)"),
                {"r": frun, "d": rank_date})
            await conn.execute(text(
                "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                "config_hash, regime, rank_date, status, started_at, completed_at) "
                "VALUES (CAST(:r AS uuid), CAST(:f AS uuid), 'calib_test', :ch, "
                "'bull_calm', :d, 'success', NOW(), NOW())"),
                {"r": run_id, "f": frun, "ch": config_hash, "d": rank_date})
            for i, t in enumerate(tickers):
                await conn.execute(text(
                    "INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, "
                    "regime, rank_date, ticker, rank, composite_score) "
                    "VALUES (CAST(:r AS uuid), CAST(:f AS uuid), 'calib_test', "
                    "'bull_calm', :d, :t, :rk, :sc)"),
                    {"r": run_id, "f": frun, "d": rank_date, "t": t,
                     "rk": i + 1, "sc": 1.0 - i / N_TICKERS})


async def test_a_name_that_delists_mid_horizon_is_excluded_not_scored_as_flat(engine):
    """The forward CTE must bound BELOW.

    The shape that isolates it: a name with a GOOD baseline price at d0 that then
    stops printing before d1 — i.e. it delists DURING the horizon. The baseline
    window was always bounded, so a name that died long before d0 is dropped
    either way; only the mid-horizon case distinguishes a bounded forward lookup
    from an unbounded one. Unbounded, such a name resolves to its own p0 and
    lands in the bottom decile at exactly 0%, flattering it and shrinking the
    very spread this section exists to measure.

    One anchor, at 60 days; its horizon runs to ~40 days ago. The six
    worst-ranked names stop printing at 58 days — inside the window.
    """
    await _seed(engine, config_hash="aaaa111122223333", anchor_offsets=[60],
                delist_worst=6, delist_after_days=58)
    with _evaluator_packet_imported() as pk:
        async with engine.connect() as conn:
            out = await pk._score_calibration(conn, "aaaa111122223333", "calib_test")

    assert "note" not in out, out
    binned = sum(d["n"] for d in out["deciles"])
    assert binned == N_TICKERS - 6, (
        f"{binned} names were binned, expected {N_TICKERS - 6}: the six that "
        f"delisted mid-horizon were carried at their last print instead of being "
        f"excluded (the forward price lookup is unbounded again)")
    assert out["n_missing_endpoint"] == 6
    assert out["missing_endpoint_rate"] == pytest.approx(6 / N_TICKERS, abs=1e-3)


async def test_the_curve_is_monotone_on_a_constructed_relationship(engine):
    await _seed(engine, config_hash="bbbb111122223333",
                anchor_offsets=[45, 95, 145, 195, 245, 295])
    with _evaluator_packet_imported() as pk:
        async with engine.connect() as conn:
            out = await pk._score_calibration(conn, "bbbb111122223333", "calib_test")
    assert out["top_minus_bottom"] > 0
    assert out["monotone_fraction"] == 1.0
    assert out["per_date_ic"]["mean"] > 0.9
    assert out["spread_ci"] is not None, "no interval — the point estimate alone is not a result"


async def test_runs_from_another_config_are_excluded_and_the_exclusion_is_reported(engine):
    """Averaging curves produced by different factor weights is not a measurement
    of anything. A small sample must READ as a small sample, so the count that was
    left out is reported rather than quietly used to pad n_dates."""
    await _seed(engine, config_hash="cccc111122223333", anchor_offsets=[50, 100, 150])
    await _seed(engine, config_hash="dddd111122223333", anchor_offsets=[75, 125, 175])
    with _evaluator_packet_imported() as pk:
        async with engine.connect() as conn:
            out = await pk._score_calibration(conn, "cccc111122223333", "calib_test")
    assert out["config_hash"] == "cccc111122223333"
    assert out["rank_dates_excluded_other_config"] >= 3
    for r in out["sampled_runs"]:
        assert r["rank_date"] not in ("", None)
    assert out["n_dates"] <= 3


async def test_anchors_are_spaced_at_least_one_horizon_apart(engine):
    """Six anchors from a 70-day window against a 20-session horizon share most
    of one return path — they are not six independent observations, and a
    bootstrap over them understates the interval badly."""
    await _seed(engine, config_hash="eeee111122223333",
                anchor_offsets=[40, 42, 44, 46, 48, 50, 100, 160])
    with _evaluator_packet_imported() as pk:
        async with engine.connect() as conn:
            out = await pk._score_calibration(conn, "eeee111122223333", "calib_test")
    dates = sorted(date.fromisoformat(r["rank_date"]) for r in out["sampled_runs"])
    for a, b in zip(dates, dates[1:]):
        assert (b - a).days >= HORIZON, f"anchors {a} and {b} overlap"


async def test_an_unknown_config_says_so_instead_of_pooling(engine):
    await _seed(engine, config_hash="ffff111122223333", anchor_offsets=[60, 120])
    with _evaluator_packet_imported() as pk:
        async with engine.connect() as conn:
            out = await pk._score_calibration(conn, "0000deadbeef0000", "calib_test")
    assert "note" in out and "OTHER configs" in out["note"]
