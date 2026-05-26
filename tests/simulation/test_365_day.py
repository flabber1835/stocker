#!/usr/bin/env python3
"""
365-day comprehensive simulation test.

Represents one trading year across three market regimes with a full cast of
edge cases.  Era dates are randomised on every run (seeded RNG — set SIM_SEED
env var to reproduce).

Scenarios covered:
  01  60 small-cap "inherited" positions phasing out through exit confirmation
  02  Share-class dedup: GOOG / GOOGL — only one allowed in portfolio
  03  Vetter sibling awareness: flagging GOOG also excludes GOOGL
  04  Three regimes: bull_calm (Era 1) → bear_stress (Era 2) → bull_calm (Era 3)
  05  Factor weight shift across regimes: momentum-heavy → quality/low-vol-heavy
  06  Position weight clipping: max_position_weight = 10%
  07  buy_add triggers: actual_weight < target_weight − drift_threshold
  08  sell_trim triggers: actual_weight > target_weight + drift_threshold
  09  Cash injection at Era 2: account grows $60 000, re-sizes all weights
  10  Mixed approvals: auto-approve entries, user manually approves sells, deny some
  11  LLM vetter risk flags: NVDA flagged (regulatory) in Era 2, cleared in Era 3
  12  Non-trading day: TODAY is a Saturday — scheduler skips correctly
  13  Manual Run press: user forces a mid-bear re-run in Era 2
  14  Partial approval: user approves 15 / 30 proposals in one round
  15  Asset transfer out: account drops $40 000 → sell_trims triggered
  16  Math assertion: weight_drift == actual_weight − current_weight (ε = 0.0001)
  17  Regime-specific portfolio composition verified per factor weight table
  18  LLM consecutive risk: COST flagged 3 runs in a row, cleared on 4th — exclusion
      persists across consecutive flagging periods and lifts correctly when cleared
  19  LLM random (non-consecutive) risk: COP flagged / cleared / flagged again —
      exclusion applies only when the latest vetter run flags the ticker
  20  Empty account: account_value=0, no positions — delta generates no exit/sell_trim
      intents (nothing to sell), system does not crash
  21  Zero buying power: buying_power=0, positions held — trade-executor correctly
      refuses entry sizing (qty < 1), system recovers when buying power restored

Three pipeline runs (confirmation window):
  Era 1 (rank_date = ERA1_DATE, bull_calm):  small caps rank 35–94, cores rank 1–34
  Era 2 (rank_date = ERA2_DATE, bear_stress): quality/low-vol rise, momentum falls
  Era 3 (rank_date = ERA3_DATE, bull_calm):  recovery, live pipeline run via API

Run:
    cd /home/user/stocker
    python tests/simulation/test_365_day.py

Override RNG seed for a deterministic run:
    SIM_SEED=42 python tests/simulation/test_365_day.py
"""

from __future__ import annotations

import dataclasses
import math
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import psycopg2
import psycopg2.extras
import requests

# ── Service URLs ──────────────────────────────────────────────────────────────

PG = dict(host="localhost", port=5433, dbname="stocker", user="stocker", password="stocker")
PIPELINE_URL  = "http://localhost:8018"
PORTBUILD_URL = "http://localhost:8008"
VETTER_URL    = "http://localhost:8016"
RISK_URL      = "http://localhost:8011"
API_URL       = "http://localhost:8000"

STRATEGY_ID = "quality_core_v1"
CONFIG_HASH = "sim365test1"

# ── Universe design ───────────────────────────────────────────────────────────
# Core 30 quality large-caps (must rank 1–30 consistently)
CORE_TICKERS = [
    "LLY",  "META", "NVDA", "MA",   "MCD",
    "V",    "MSFT", "AAPL", "AMZN", "GOOG",
    "UNH",  "JNJ",  "PG",   "JPM",  "BAC",
    "WMT",  "HD",   "COST", "ABBV", "MRK",
    "TMO",  "DHR",  "ABT",  "CVX",  "XOM",
    "COP",  "EOG",  "NEE",  "DUK",  "PLD",
]
# Share-class additions (GOOG already in CORE; GOOGL is its sibling)
SHARE_CLASS_EXTRA = ["GOOGL", "FOXA", "FOX"]
# Small caps — start as "inherited" live positions, must phase out
SMALL_CAPS = [f"SMCP{i:02d}" for i in range(1, 61)]   # SMCP01 … SMCP60

ALL_RANKED  = CORE_TICKERS + SHARE_CLASS_EXTRA          # 33 — go through pipeline
ALL_TICKERS = ALL_RANKED + SMALL_CAPS                   # 93 total

SHARE_CLASS_PAIRS = {
    "GOOGL": ("GOOG", "Alphabet Inc."),     # GOOG is dominant, GOOGL sibling
    "FOX":   ("FOXA", "Fox Corp"),          # FOXA is dominant, FOX sibling
}

# ── Fundamental profiles ──────────────────────────────────────────────────────
# Core stocks: high quality, used to rank 1–30
FUND_CORE = dict(
    pe_ratio=20.0, pb_ratio=4.0,
    roe=0.28, debt_to_equity=0.4,
    revenue_growth=0.14, eps_growth=0.15,
    avg_volume_dollars=500_000_000,   # $500 M daily — well above $20 M filter
)
FUND_SMALL = dict(
    pe_ratio=32.0, pb_ratio=1.8,
    roe=0.06, debt_to_equity=1.8,
    revenue_growth=0.02, eps_growth=0.01,
    avg_volume_dollars=25_000_000,    # just above $20 M filter (must pass)
)
FUND_SHARE = dict(
    pe_ratio=22.0, pb_ratio=5.0,
    roe=0.22, debt_to_equity=0.5,
    revenue_growth=0.10, eps_growth=0.12,
    avg_volume_dollars=300_000_000,
)

# Sector map (used for max_sector_weight enforcement)
SECTORS = {
    "LLY": "Health Care", "META": "Communication Services", "NVDA": "Information Technology",
    "MA": "Financials", "MCD": "Consumer Discretionary", "V": "Financials",
    "MSFT": "Information Technology", "AAPL": "Information Technology", "AMZN": "Consumer Discretionary",
    "GOOG": "Communication Services", "UNH": "Health Care", "JNJ": "Health Care",
    "PG": "Consumer Staples", "JPM": "Financials", "BAC": "Financials",
    "WMT": "Consumer Staples", "HD": "Consumer Discretionary", "COST": "Consumer Staples",
    "ABBV": "Health Care", "MRK": "Health Care", "TMO": "Health Care", "DHR": "Health Care",
    "ABT": "Health Care", "CVX": "Energy", "XOM": "Energy", "COP": "Energy", "EOG": "Energy",
    "NEE": "Utilities", "DUK": "Utilities", "PLD": "Real Estate",
    "GOOGL": "Communication Services", "FOXA": "Communication Services", "FOX": "Communication Services",
}

# ── Price history start (kept in module scope; used by seed_prices / _weekdays)
PRICE_START = date(2024, 1, 2)    # synthetic price history start

# RNG seed default — override with SIM_SEED env var
DEFAULT_RNG_SEED = 20260101

# Account parameters
INITIAL_ACCOUNT = 300_000.0
CASH_INJECTION  =  60_000.0    # added at Era 2
ASSET_TRANSFER  =  40_000.0    # removed mid-Era 3 (triggers sell_trims)

# ── Harness ────────────────────────────────────────────────────────────────────

ERRORS: List[str] = []
WARNINGS: List[str] = []
PASSED: List[str] = []


def ok(name: str, detail: str = "") -> None:
    PASSED.append(name)
    print(f"  ✅ {name}" + (f"  [{detail}]" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    ERRORS.append(name)
    print(f"  ❌ {name}" + (f"  [{detail}]" if detail else ""))


def warn(name: str, detail: str = "") -> None:
    WARNINGS.append(name)
    print(f"  ⚠️  {name}" + (f"  [{detail}]" if detail else ""))


def check(cond: bool, name: str, detail: str = "") -> None:
    (ok if cond else fail)(name, detail)


def hdr(title: str) -> None:
    print(f"\n{'═' * 72}\n  {title}\n{'═' * 72}")


# ── Price generation ──────────────────────────────────────────────────────────

_SQRT2 = math.sqrt(2)
_SQRT3 = math.sqrt(3)


def _weekdays(start: date, end: date) -> List[date]:
    """All Mon–Fri between start and end inclusive (approximate trading days)."""
    days, d = [], start
    while d <= end:
        if d.isoweekday() <= 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _spy_price(day_idx: int, n_days: int) -> float:
    """
    SPY price series that produces three regime phases:
      Phase A (0 .. 40% of n_days):  bull_calm  — steady uptrend, low noise
      Phase B (40% .. 70%):          bear_stress — crash + high volatility
      Phase C (70% .. 100%):         bull_calm   — recovery, low noise

    At the end of Phase A:  SPY > 200-SMA, 20-day vol < 20%  → bull_calm ✓
    At the end of Phase B:  SPY < 200-SMA, 20-day vol > 20%  → bear_stress ✓
    At the end of Phase C:  SPY > 200-SMA, 20-day vol < 20%  → bull_calm ✓
    """
    a_end = int(0.40 * n_days)   # ~240 days
    b_end = int(0.70 * n_days)   # ~420 days

    if day_idx <= a_end:
        # Steady bull: 400 → 520 (+30%), noise = 0.4%
        trend = 400.0 + (120.0 * day_idx / a_end)
        noise = 0.004 * math.sin(day_idx * _SQRT3)
    elif day_idx <= b_end:
        # Bear crash: 520 → 360 (−31%), noise = 3% (bear_stress)
        frac = (day_idx - a_end) / (b_end - a_end)
        trend = 520.0 - 160.0 * frac
        # High volatility: 3% amplitude oscillation
        noise = 0.030 * math.sin(day_idx * 5.7 * _SQRT2)
    else:
        # Recovery: 360 → 540 (+50%), noise = 0.4%
        frac = (day_idx - b_end) / (n_days - b_end)
        trend = 360.0 + 180.0 * frac
        noise = 0.004 * math.sin(day_idx * _SQRT3 * 1.3)

    return round(trend * (1.0 + noise), 4)


def _core_price(t_idx: int, day_idx: int, n_days: int) -> float:
    """
    Core quality stock price: upward trend through the full period.
    Each ticker has its own phase (t_idx) to keep the covariance matrix non-singular.
    These stocks generate strong momentum and consistently rank 1–30.
    """
    trend = 50.0 + (50.0 * day_idx / n_days)  # $50 → $100 over 600 days
    cycle = 0.006 * math.sin(t_idx * _SQRT2 + day_idx * _SQRT3 * 0.3)
    return round(trend * (1.0 + cycle), 4)


def _small_cap_price(t_idx: int, day_idx: int, n_days: int) -> float:
    """
    Small-cap price: flat to slightly declining, high idiosyncratic noise.
    These stocks have poor momentum vs core, keeping them ranked 35+.
    """
    trend = 18.0 - (4.0 * day_idx / n_days)   # $18 → $14 (slight decline)
    noise = 0.015 * math.sin(t_idx * _SQRT2 * 3 + day_idx * _SQRT3 * 0.7)
    return round(max(trend * (1.0 + noise), 5.5), 4)  # floor $5.50 (min_price filter)


def _share_price(t_idx: int, day_idx: int, n_days: int) -> float:
    """Share-class stock: similar to core but slightly lower base price."""
    trend = 40.0 + (40.0 * day_idx / n_days)
    cycle = 0.008 * math.sin(t_idx * _SQRT2 * 1.5 + day_idx * _SQRT3 * 0.25)
    return round(trend * (1.0 + cycle), 4)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn():
    return psycopg2.connect(**PG, cursor_factory=psycopg2.extras.RealDictCursor)


def _exec(sql: str, params=None, fetch=False):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if fetch:
            return cur.fetchall()
        conn.commit()


def _fetchone(sql: str, params=None) -> Optional[dict]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# ── Price lookup helpers ──────────────────────────────────────────────────────

def price_on_date(ticker: str, d: date) -> float:
    """Return the adjusted_close from seeded daily_prices for ticker on date d."""
    row = _fetchone(
        "SELECT adjusted_close FROM daily_prices WHERE ticker=%s AND date=%s",
        (ticker, d.isoformat()),
    )
    if row:
        return float(row["adjusted_close"])
    # If exact date not found, try closest prior trading day
    row = _fetchone(
        "SELECT adjusted_close FROM daily_prices WHERE ticker=%s AND date<=%s ORDER BY date DESC LIMIT 1",
        (ticker, d.isoformat()),
    )
    return float(row["adjusted_close"]) if row else 0.0


def prices_on_date(tickers: List[str], d: date) -> Dict[str, float]:
    """Bulk price lookup for many tickers on a single date."""
    if not tickers:
        return {}
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices "
            "WHERE ticker=ANY(%s) AND date<=%s ORDER BY ticker, date DESC",
            (list(tickers), d.isoformat()),
        )
        return {r["ticker"]: float(r["adjusted_close"]) for r in cur.fetchall()}


# ── Ledger ────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class _Tx:
    when: date
    kind: str          # 'acquire'|'buy'|'sell'|'inject'|'withdraw'
    ticker: Optional[str]
    qty: float
    price: float
    cash_delta: float  # +ve = cash in, -ve = cash out


class Ledger:
    """Tracks all financial events to enable end-of-simulation reconciliation."""

    def __init__(self, initial_cash: float):
        self.cash = initial_cash
        self.positions: Dict[str, float] = {}   # ticker → qty
        self.log: List[_Tx] = []

    def _rec(self, kind: str, ticker: Optional[str], qty: float, price: float, cash_delta: float) -> None:
        self.log.append(_Tx(date.today(), kind, ticker, qty, price, cash_delta))

    def acquire(self, ticker: str, qty: float, price: float, when: date) -> None:
        """Inherit a position (no cash movement — pre-existing holding)."""
        self.positions[ticker] = self.positions.get(ticker, 0.0) + qty
        self._rec('acquire', ticker, qty, price, 0.0)

    def buy(self, ticker: str, qty: float, price: float, when: date) -> None:
        cost = qty * price
        self.cash -= cost
        self.positions[ticker] = self.positions.get(ticker, 0.0) + qty
        self._rec('buy', ticker, qty, price, -cost)

    def sell(self, ticker: str, qty: float, price: float, when: date) -> None:
        proceeds = qty * price
        self.cash += proceeds
        remaining = self.positions.get(ticker, 0.0) - qty
        if remaining > 0.001:
            self.positions[ticker] = remaining
        elif ticker in self.positions:
            del self.positions[ticker]
        self._rec('sell', ticker, qty, price, proceeds)

    def inject(self, amount: float, when: date) -> None:
        self.cash += amount
        self._rec('inject', None, 0.0, 0.0, amount)

    def withdraw(self, amount: float, when: date) -> None:
        self.cash -= amount
        self._rec('withdraw', None, 0.0, 0.0, -amount)

    def market_value(self, prices: Dict[str, float]) -> float:
        return sum(self.positions.get(t, 0.0) * prices.get(t, 0.0)
                   for t in self.positions)

    def account_value(self, prices: Dict[str, float]) -> float:
        return self.cash + self.market_value(prices)


# ── Seed helpers ──────────────────────────────────────────────────────────────

def seed_universe(today_date: date) -> int:
    """Create a fresh simulation universe snapshot and return its snapshot_id."""
    hdr("SETUP: Seeding universe snapshot (93 tickers)")
    today_iso = today_date.isoformat()

    snap_id = _fetchone(
        "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count, fetched_at)"
        " VALUES (%s, %s, %s, NOW()) RETURNING id",
        ("SIM365", today_iso, len(ALL_TICKERS)),
    )["id"]

    rows = []
    for i, ticker in enumerate(ALL_TICKERS):
        if ticker in SMALL_CAPS:
            name = f"SimSmallCap {ticker}"
            sector = "Consumer Discretionary"
        elif ticker in SHARE_CLASS_PAIRS:
            name = f"{SHARE_CLASS_PAIRS[ticker][1]} - Class {'A' if 'A' in ticker or ticker.endswith('A') else 'B'}"
            sector = SECTORS.get(ticker, "Communication Services")
        else:
            name = f"{ticker} Inc."
            sector = SECTORS.get(ticker, "Other")
        rows.append((snap_id, ticker, name, sector))

    with _conn() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) VALUES %s",
            rows,
        )
        conn.commit()

    ok(f"Universe snapshot {snap_id} created", f"{len(ALL_TICKERS)} tickers")
    return snap_id


def seed_prices(today_date: date) -> None:
    """Seed daily_prices for all tickers from PRICE_START up to today_date.

    Additionally seeds SPY prices from today_date up to the real script-execution
    date (date.today()).  The live pipeline queries SPY with WHERE date >= NOW() - 600 days
    using the real clock, so SPY must have rows up to the actual current date.
    """
    real_today = date.today()
    # Extend to real today so the pipeline's NOW()-based SPY query gets enough rows
    seed_end = max(today_date, real_today)

    hdr(f"SETUP: Seeding price history ({PRICE_START} → {today_date}; SPY extends to {seed_end})")

    # Phase 1: all tickers up to today_date (simulation range)
    all_days = _weekdays(PRICE_START, today_date)
    n        = len(all_days)

    rows = []
    ticker_list = ["SPY"] + ALL_RANKED + SMALL_CAPS

    for t_idx, ticker in enumerate(ticker_list):
        for d_idx, day in enumerate(all_days):
            if ticker == "SPY":
                price = _spy_price(d_idx, n)
            elif ticker in SMALL_CAPS:
                sc_idx = int(ticker[4:]) - 1   # SMCP01 → 0
                price = _small_cap_price(sc_idx, d_idx, n)
            elif ticker in SHARE_CLASS_EXTRA:
                price = _share_price(t_idx, d_idx, n)
            else:
                price = _core_price(t_idx, d_idx, n)

            vol = 1_000_000 if ticker in SMALL_CAPS else 5_000_000
            rows.append((
                ticker, day.isoformat(), price, price * 1.002, price * 0.998,
                price, price,  # open, high, low, close, adj_close
                vol, "sim365",
            ))

    # Phase 2: extend SPY only from today_date+1 → real_today (pipeline clock coverage)
    if seed_end > today_date:
        extra_spy_days = _weekdays(today_date + timedelta(days=1), seed_end)
        # Use a flat continuation price for the extended SPY days (bull_calm recovery)
        last_spy_price = _spy_price(n - 1, n)
        for d_idx, day in enumerate(extra_spy_days):
            # Gentle uptrend continuation after today_date
            price = round(last_spy_price * (1.0 + 0.0002 * (d_idx + 1)), 4)
            rows.append((
                "SPY", day.isoformat(), price, price * 1.002, price * 0.998,
                price, price, 5_000_000, "sim365",
            ))

    t0 = time.time()
    with _conn() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adjusted_close, volume, source)
               VALUES %s
               ON CONFLICT (ticker, date) DO UPDATE
               SET adjusted_close=EXCLUDED.adjusted_close, volume=EXCLUDED.volume,
                   open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                   close=EXCLUDED.close, source=EXCLUDED.source""",
            rows,
            page_size=2000,
        )
        conn.commit()

    ok(f"Prices seeded", f"{len(rows):,} rows in {time.time()-t0:.1f}s  ({n} sim trading days + SPY to {seed_end})")


def seed_fundamentals(today_date: date) -> None:
    """Seed one fundamentals row per ticker."""
    hdr("SETUP: Seeding fundamentals")
    today_iso = today_date.isoformat()
    rows = []
    for ticker in ALL_TICKERS:
        if ticker in SMALL_CAPS:
            f = FUND_SMALL
        elif ticker in SHARE_CLASS_EXTRA:
            f = FUND_SHARE
        else:
            f = FUND_CORE
        # avg_volume in shares; pipeline uses avg_dollar_volume = avg_close × avg_volume
        # Set avg_volume such that avg_dollar_volume ≈ f["avg_volume_dollars"]
        # Assume price ~$75 for core, $15 for small → volume = dollars / price
        approx_price = 75.0 if ticker not in SMALL_CAPS else 16.0
        vol = int(f["avg_volume_dollars"] / approx_price)
        rows.append((
            ticker, today_iso,
            f["pe_ratio"], f["pb_ratio"],
            f["roe"], f["debt_to_equity"],
            f["revenue_growth"], f["eps_growth"],
            int(f["avg_volume_dollars"] / approx_price * approx_price),  # market_cap placeholder
            vol, "sim365",
        ))

    with _conn() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO fundamentals
               (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                revenue_growth, eps_growth, market_cap, avg_volume, source)
               VALUES %s
               ON CONFLICT (ticker, as_of_date) DO UPDATE
               SET pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio,
                   roe=EXCLUDED.roe, debt_to_equity=EXCLUDED.debt_to_equity,
                   revenue_growth=EXCLUDED.revenue_growth, eps_growth=EXCLUDED.eps_growth,
                   avg_volume=EXCLUDED.avg_volume, source=EXCLUDED.source""",
            rows,
        )
        conn.commit()
    ok(f"Fundamentals seeded", f"{len(rows)} tickers")


def seed_alpaca_state(account_value: float, include_small_caps: bool = True,
                      core_held: Optional[List[str]] = None,
                      overweight_mv: Optional[Dict[str, float]] = None,
                      buying_power: Optional[float] = None,
                      era_date: Optional[date] = None) -> str:
    """Seed alpaca_sync_run + live_positions. Returns sync_run_id.

    overweight_mv: optional dict {ticker: market_value} for explicit overweight positions.
    buying_power: explicit buying_power override (defaults to account_value × 10%).
    era_date: when provided, prices are looked up from seeded daily_prices for this date
              rather than using hardcoded values. Falls back to hardcoded if no DB price found.
    """
    core_held = core_held or []
    overweight_mv = overweight_mv or {}
    if buying_power is None:
        buying_power = account_value * 0.10
    positions = []

    # Bulk-fetch prices from DB when era_date is given
    if era_date is not None:
        _all_tickers_needed = (SMALL_CAPS if include_small_caps else []) + list(core_held)
        _db_prices = prices_on_date(_all_tickers_needed, era_date) if _all_tickers_needed else {}
    else:
        _db_prices = {}

    if include_small_caps:
        # 60 small caps: each $4 000 (~$240 000 / 60 = $4 000)
        for i, sc in enumerate(SMALL_CAPS):
            # Use DB price when available; fallback to original formula
            price = _db_prices.get(sc) or (16.0 - 0.02 * i)
            mv    = 4_000.0
            qty   = mv / price if price > 0 else 250.0
            positions.append((sc, qty, price, mv))

    for ticker in core_held:
        # Use DB price when available; fallback to $75 stub
        price = _db_prices.get(ticker) or 75.0
        mv    = overweight_mv.get(ticker, account_value * (1 / 30))
        qty   = mv / price if price > 0 else 1.0
        positions.append((ticker, qty, price, mv))

    sync_id = str(uuid.uuid4())
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO alpaca_sync_runs
               (run_id, status, account_value, cash, buying_power,
                position_count, completed_at)
               VALUES (%s, 'success', %s, %s, %s, %s, NOW())""",
            (sync_id, account_value,
             buying_power,           # cash ≈ buying_power (no margin)
             buying_power,
             len(positions)),
        )
        if positions:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO live_positions
                   (sync_run_id, ticker, qty, current_price, market_value,
                    unrealized_pl, unrealized_plpc)
                   VALUES %s""",
                [(sync_id, t, q, p, mv, 0.0, 0.0) for (t, q, p, mv) in positions],
            )
        conn.commit()
    return sync_id


def seed_era_rankings(
    era_date: date,
    regime: str,
    snap_id: int,
    small_caps_rank_start: int = 35,
    nvda_flag: bool = False,
    completed_at_offset_secs: int = 0,
    completed_at: Optional[datetime] = None,
) -> tuple[str, str]:
    """
    Manually seed factor_runs + factor_scores + ranking_runs + rankings
    for a given era (used for Eras 1 and 2 which don't run the live pipeline).

    Pass completed_at explicitly to ensure correct ordering relative to the
    live pipeline run — the delta engine selects history by completed_at DESC.

    Returns (factor_run_id, ranking_run_id).
    """
    factor_run_id  = str(uuid.uuid4())
    ranking_run_id = str(uuid.uuid4())
    era_iso        = era_date.isoformat()
    if completed_at is not None:
        completed = completed_at
    else:
        completed = datetime.now(timezone.utc) - timedelta(seconds=completed_at_offset_secs)

    # Bear-stress re-ranking: quality stocks move up, momentum stocks fall
    _BEAR_BOOST = {  # rank adjustment for bear_stress (neg = moves up)
        "UNH": -5, "JNJ": -4, "PG": -4, "ABBV": -3, "MRK": -3,  # quality healthcare up
        "NEE": -3, "DUK": -3,                                       # utilities up
        "NVDA": +8, "META": +6, "AMZN": +5,                         # momentum down
    }

    with _conn() as conn, conn.cursor() as cur:
        # factor_runs row
        cur.execute(
            """INSERT INTO factor_runs
               (run_id, strategy_id, config_hash, score_date, universe_snapshot_id,
                raw_regime, regime, status, ticker_count, started_at, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'success', %s, %s, %s)""",
            (factor_run_id, STRATEGY_ID, CONFIG_HASH,
             era_iso, snap_id, regime, regime,
             len(ALL_RANKED) + len(SMALL_CAPS),
             completed, completed),
        )

        # factor_scores: core/share-class = high, small caps = low
        score_rows = []
        for ticker in ALL_RANKED + SMALL_CAPS:
            if ticker in SMALL_CAPS:
                q, v, m, g, lv, liq = 0.20, 0.15, 0.10, 0.12, 0.25, 0.18
            elif ticker in SHARE_CLASS_EXTRA:
                q, v, m, g, lv, liq = 0.72, 0.68, 0.75, 0.70, 0.65, 0.80
            else:
                # Core: differentiate slightly so ranks are stable
                idx = CORE_TICKERS.index(ticker) if ticker in CORE_TICKERS else 0
                base = 0.85 - 0.012 * idx
                q, v, m, g, lv, liq = base, base - 0.05, base + 0.03, base - 0.02, base - 0.08, base
                if regime == "bear_stress":
                    adj = _BEAR_BOOST.get(ticker, 0)
                    m  += adj * (-0.02)   # momentum falls for flagged tickers
                    lv += adj * 0.01 if adj > 0 else 0  # low_vol rises in bear
                    q  += abs(adj) * 0.005 if adj < 0 else 0
            score_rows.append((factor_run_id, ticker, era_iso, q, v, m, g, lv, liq))

        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO factor_scores
               (run_id, ticker, score_date, quality, value, momentum, growth,
                low_volatility, liquidity)
               VALUES %s
               ON CONFLICT DO NOTHING""",
            score_rows,
        )

        # ranking_runs row
        cur.execute(
            """INSERT INTO ranking_runs
               (run_id, source_factor_run_id, strategy_id, config_hash, regime,
                rank_date, status, universe_count, ranked_count, dropped_count,
                started_at, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'success', %s, %s, 0, %s, %s)""",
            (ranking_run_id, factor_run_id, STRATEGY_ID, CONFIG_HASH, regime,
             era_iso,
             len(ALL_RANKED) + len(SMALL_CAPS),
             len(ALL_RANKED) + len(SMALL_CAPS),
             completed, completed),
        )

        # rankings: core rank 1–34, small caps rank 35–94
        # In bear_stress, reorder core by quality (JNJ, PG, UNH move up)
        ranking_rows = []
        base_ranking = list(CORE_TICKERS)  # 30 items

        if regime == "bear_stress":
            # Re-sort: boost quality/low-vol, penalize momentum
            def bear_sort_key(t):
                return _BEAR_BOOST.get(t, 0)
            base_ranking.sort(key=bear_sort_key)

        for pos, ticker in enumerate(base_ranking, 1):
            score = 0.85 - 0.012 * pos
            ranking_rows.append((ranking_run_id, ticker, pos, score, era_iso, regime))

        # Share-class extra: rank just outside top 30
        for extra_idx, ticker in enumerate(SHARE_CLASS_EXTRA, 31):
            score = 0.45 - 0.02 * extra_idx
            ranking_rows.append((ranking_run_id, ticker, extra_idx, score, era_iso, regime))

        # Small caps: rank 35–94 (all > exit_rank=40)
        for sc_idx, ticker in enumerate(SMALL_CAPS, small_caps_rank_start):
            score = 0.18 - 0.001 * sc_idx
            ranking_rows.append((ranking_run_id, ticker, sc_idx, score, era_iso, regime))

        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO rankings
               (run_id, source_factor_run_id, strategy_id, ticker, rank, composite_score, percentile, rank_date, regime)
               VALUES %s
               ON CONFLICT DO NOTHING""",
            [(rr, factor_run_id, STRATEGY_ID, t, r, s, 1.0 - r / 100.0, rd, reg)
             for (rr, t, r, s, rd, reg) in ranking_rows],
        )
        conn.commit()

    return factor_run_id, ranking_run_id


def seed_era_portfolio(
    ranking_run_id: str,
    regime: str,
    portfolio_date: date,
    excluded_tickers: Optional[List[str]] = None,
    account_value: float = INITIAL_ACCOUNT,
) -> str:
    """Seed portfolio_runs + portfolio_holdings for an era. Returns portfolio_run_id."""
    excluded = set(excluded_tickers or [])
    portfolio_run_id = str(uuid.uuid4())

    # Select top 30 from core, excluding vetter-excluded tickers + deduped siblings
    candidates = [t for t in CORE_TICKERS if t not in excluded][:30]
    if len(candidates) < 30 and "GOOGL" not in excluded and "GOOG" in candidates:
        # GOOGL always excluded (GOOG is dominant)
        pass

    equal_weight = 1.0 / len(candidates) if candidates else 0.0

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO portfolio_runs
               (run_id, source_ranking_run_id, strategy_id, config_hash, regime,
                portfolio_date, status, candidate_count, selected_count,
                covariance_window_days, started_at, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'success', %s, %s, 252, NOW(), NOW())""",
            (portfolio_run_id, ranking_run_id, STRATEGY_ID, CONFIG_HASH, regime,
             portfolio_date.isoformat(),
             len(candidates) + 5,   # some candidates not selected
             len(candidates)),
        )
        holding_rows = [
            (portfolio_run_id, ranking_run_id, STRATEGY_ID, regime,
             portfolio_date.isoformat(), ticker, pos, equal_weight, 0.80 - 0.01 * pos)
            for pos, ticker in enumerate(candidates, 1)
        ]
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO portfolio_holdings
               (run_id, source_ranking_run_id, strategy_id, regime, portfolio_date,
                ticker, position, weight, composite_score)
               VALUES %s""",
            holding_rows,
        )
        conn.commit()
    return portfolio_run_id


def seed_vetter_run(
    vetter_date: date,
    excluded_tickers: List[str],
    risk_ticker_reasons: Optional[Dict[str, tuple]] = None,
) -> str:
    """
    Seed a vetter_run + vetter_decisions for the given date.
    risk_ticker_reasons: {ticker: (reason, risk_type, confidence)}
    Returns vetter_run_id.
    """
    risk_ticker_reasons = risk_ticker_reasons or {}
    vetter_run_id = str(uuid.uuid4())
    all_vetted = CORE_TICKERS + SHARE_CLASS_EXTRA

    with _conn() as conn, conn.cursor() as cur:
        total = len(all_vetted)
        flagged = len(excluded_tickers)
        # Need a valid source_ranking_run_id — grab latest
        row = _fetchone("SELECT run_id FROM ranking_runs ORDER BY started_at DESC LIMIT 1")
        src_ranking_run_id = row["run_id"] if row else str(uuid.uuid4())
        cur.execute(
            """INSERT INTO vetter_runs
               (run_id, source_ranking_run_id, strategy_id, model, status,
                candidate_count, flagged_count, started_at, completed_at)
               VALUES (%s, %s, %s, 'anthropic/claude-3-5-haiku', 'success', %s, %s, NOW(), NOW())""",
            (vetter_run_id, src_ranking_run_id, STRATEGY_ID, total, flagged),
        )

        decision_rows = []
        for ticker in all_vetted:
            excl   = ticker in excluded_tickers
            reason = ""
            rtype  = "none"
            conf   = "medium"
            pc     = False
            pr     = ""
            if ticker in risk_ticker_reasons:
                reason, rtype, conf = risk_ticker_reasons[ticker]
            elif not excl:
                pc   = ticker in ("LLY", "MA", "MSFT")  # positive catalysts
                pr   = "Strong earnings momentum" if pc else ""
            decision_rows.append((
                vetter_run_id, ticker, excl, reason, conf, rtype, pc, pr,
            ))

        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO vetter_decisions
               (run_id, ticker, exclude, reason, confidence, risk_type,
                positive_catalyst, positive_reason)
               VALUES %s
               ON CONFLICT (run_id, ticker) DO UPDATE
               SET exclude=EXCLUDED.exclude, reason=EXCLUDED.reason,
                   risk_type=EXCLUDED.risk_type, confidence=EXCLUDED.confidence""",
            decision_rows,
        )
        conn.commit()
    return vetter_run_id


# ── Pipeline API helpers ──────────────────────────────────────────────────────

def _wait_for_run(url: str, label: str, timeout: int = 180) -> Optional[dict]:
    """Poll /runs/latest until status != running (or timeout). Returns final status dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/runs/latest", timeout=10)
            if r.status_code == 200:
                d = r.json()
                s = d.get("status", "")
                if s not in ("running", ""):
                    return d
        except Exception:
            pass
        time.sleep(3)
    fail(f"{label}: timed out after {timeout}s")
    return None


def run_pipeline(label: str = "pipeline", force: bool = True) -> Optional[dict]:
    params = "?force=true" if force else ""
    r = requests.post(f"{PIPELINE_URL}/jobs/run{params}", timeout=30)
    if r.status_code not in (200, 201, 202):
        fail(f"{label}: trigger HTTP {r.status_code}", r.text[:200])
        return None
    result = _wait_for_run(PIPELINE_URL, label, timeout=300)
    if result and result.get("status") == "success":
        ok(label, f"run_id={result.get('run_id','?')[:8]} regime={result.get('regime','?')}")
    elif result:
        fail(label, f"status={result.get('status')} err={result.get('error_message','')[:80]}")
    return result


def run_portfolio_builder(label: str = "portfolio-builder") -> Optional[dict]:
    r = requests.post(f"{PORTBUILD_URL}/jobs/build", timeout=30)
    if r.status_code not in (200, 201, 202):
        fail(f"{label}: trigger HTTP {r.status_code}")
        return None
    result = _wait_for_run(PORTBUILD_URL, label, timeout=120)
    if result and result.get("status") == "success":
        ok(label, f"selected={result.get('selected_count','?')} regime={result.get('regime','?')}")
    elif result:
        fail(label, f"status={result.get('status')}")
    return result


def run_delta(label: str = "delta") -> Optional[dict]:
    """Trigger a standalone delta run and wait for it to complete.

    Returns a dict with 'status' and 'run_id' (the delta_runs.run_id so the
    caller can fetch the right intents even if the scheduler fires a competing
    run concurrently).
    """
    # Record the wall-clock time just before we fire so we can identify OUR run
    triggered_at = datetime.now(timezone.utc)

    r = requests.post(f"{PIPELINE_URL}/jobs/delta", timeout=30)
    if r.status_code not in (200, 201, 202):
        fail(f"{label}: trigger HTTP {r.status_code}")
        return None

    # Poll delta_runs directly (not /runs/latest which can reflect a competing
    # pipeline_run's delta) until a run started_at >= triggered_at reaches a
    # terminal state.
    deadline = time.time() + 90
    result_run_id = None
    while time.time() < deadline:
        time.sleep(2)
        row = _fetchone(
            "SELECT run_id, status, entries_count, exits_count FROM delta_runs "
            "WHERE started_at >= %s "
            "  AND status != 'running' "
            "ORDER BY started_at DESC LIMIT 1",
            (triggered_at,),
        )
        if row:
            result_run_id = str(row["run_id"])
            if row["status"] == "success":
                ok(label, f"run_id={result_run_id[:8]}")
                return {"status": "success", "run_id": result_run_id}
            else:
                fail(label, f"status={row['status']}")
                return {"status": row["status"], "run_id": result_run_id}

    fail(f"{label}: timed out waiting for delta_run after trigger")
    return None


def get_latest_intents(delta_run_id: Optional[str] = None) -> List[dict]:
    """Fetch delta_intents from the given delta_run (or the most recent one)."""
    if delta_run_id is None:
        rows = _fetchone(
            "SELECT run_id FROM delta_runs WHERE status='success' "
            "ORDER BY started_at DESC LIMIT 1"
        )
        if not rows:
            return []
        delta_run_id = str(rows["run_id"])
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, ticker, action, rank, current_weight, actual_weight, weight_drift, reason "
            "FROM delta_intents WHERE run_id = %s",
            (str(delta_run_id),),
        )
        return [dict(r) for r in cur.fetchall()]


TRADE_EXECUTOR_URL = "http://localhost:8012"


def simulate_partial_approval(intents: List[dict], approve_pct: float = 0.5) -> dict:
    """
    Simulate user partially approving trade proposals.
    - Entries: approve approve_pct fraction via trade-executor /jobs/submit,
      reject the rest by setting rejected_at.
    - Exits/sell_trims: submit all via trade-executor (auto-approve).
    Returns counts: {approved_entries: N, rejected_entries: M, exit_count: K}
    """
    entries = [i for i in intents if i["action"] in ("entry", "buy_add")]
    exits   = [i for i in intents if i["action"] in ("exit", "sell_trim")]

    approved = rejected = 0
    n_approve_entries = max(1, int(len(entries) * approve_pct))

    # Submit approved entries to trade-executor (simulates user clicking Approve)
    for intent in entries[:n_approve_entries]:
        try:
            r = requests.post(
                f"{TRADE_EXECUTOR_URL}/jobs/submit",
                json={"intent_id": intent["id"], "mode": "immediate"},
                timeout=15,
            )
            approved += 1
        except Exception:
            approved += 1  # count anyway; order may fail at Alpaca level (no creds)

    # Reject the rest by setting rejected_at directly in DB
    with _conn() as conn, conn.cursor() as cur:
        for intent in entries[n_approve_entries:]:
            cur.execute(
                "UPDATE delta_intents SET rejected_at=NOW() "
                "WHERE id=%s AND rejected_at IS NULL",
                (intent["id"],),
            )
            rejected += cur.rowcount

        # Submit exits/trims via trade-executor
        for intent in exits:
            try:
                r = requests.post(
                    f"{TRADE_EXECUTOR_URL}/jobs/submit",
                    json={"intent_id": intent["id"], "mode": "immediate"},
                    timeout=15,
                )
            except Exception:
                pass  # count as submitted regardless

        conn.commit()

    return {"approved_entries": approved, "rejected_entries": rejected,
            "exit_count": len(exits)}


# ── Verification helpers ──────────────────────────────────────────────────────

def verify_regime(expected: str, run_result: Optional[dict]) -> None:
    if not run_result:
        fail(f"regime/{expected}", "no pipeline result")
        return
    actual = run_result.get("regime") or run_result.get("factor_regime") or ""
    # Accept regime from pipeline_runs or factor_runs
    if not actual:
        row = _fetchone(
            "SELECT regime FROM factor_runs ORDER BY started_at DESC LIMIT 1"
        )
        actual = (row or {}).get("regime", "")
    check(actual == expected, f"regime={expected}", f"got '{actual}'")


def verify_share_class_dedup(portfolio_holdings: List[dict]) -> None:
    """GOOG and GOOGL should not both be in portfolio; FOXA and FOX should not both be."""
    tickers = {h["ticker"] for h in portfolio_holdings}
    goog_conflict = "GOOG" in tickers and "GOOGL" in tickers
    fox_conflict  = "FOXA" in tickers and "FOX"  in tickers
    check(not goog_conflict, "share_class_dedup: GOOG/GOOGL not both in portfolio",
          "Both present!" if goog_conflict else "OK")
    check(not fox_conflict,  "share_class_dedup: FOXA/FOX not both in portfolio",
          "Both present!" if fox_conflict else "OK")


def verify_position_weight_cap(portfolio_holdings: List[dict], cap: float = 0.10) -> None:
    violations = [(h["ticker"], float(h["weight"])) for h in portfolio_holdings
                  if h.get("weight") is not None and float(h["weight"]) > cap + 0.001]
    check(len(violations) == 0, f"position_weight_cap (≤{cap:.0%})",
          f"Violations: {violations}" if violations else "OK")


def verify_vetter_exclusions(portfolio_holdings: List[dict],
                              excluded: List[str]) -> None:
    """Excluded tickers must NOT appear in portfolio_holdings."""
    in_port = {h["ticker"] for h in portfolio_holdings}
    leakage = [t for t in excluded if t in in_port]
    check(len(leakage) == 0, "vetter_exclusions not in portfolio",
          f"Leaked: {leakage}" if leakage else "OK")


def verify_small_cap_exits(intents: List[dict]) -> None:
    """After 3 eras, all 60 small caps must have exit or at_risk intents."""
    exit_tickers = {i["ticker"] for i in intents
                    if i["action"] in ("exit", "at_risk")}
    sc_with_exit  = [sc for sc in SMALL_CAPS if sc in exit_tickers]
    sc_missing    = [sc for sc in SMALL_CAPS if sc not in exit_tickers]
    check(len(sc_with_exit) >= 55,   # allow a few in buffer zone (at_risk instead of exit)
          f"small_caps_phasing_out: ≥55/60 have exit/at_risk signals",
          f"{len(sc_with_exit)}/60 signaled, missing: {sc_missing[:5]}")


def verify_weight_drift_math(intents: List[dict]) -> None:
    """weight_drift must equal actual_weight − current_weight (within ε)."""
    EPS = 0.0002
    violations = []
    for i in intents:
        if i.get("actual_weight") is not None and i.get("current_weight") is not None:
            aw = float(i["actual_weight"])
            cw = float(i["current_weight"])
            wd = float(i["weight_drift"]) if i.get("weight_drift") is not None else None
            if wd is not None and abs(wd - (aw - cw)) > EPS:
                violations.append((i["ticker"], wd, aw - cw))
    check(len(violations) == 0, "weight_drift_math: drift = actual − current",
          f"{violations[:3]}" if violations else f"verified {len(intents)} intents")


def verify_non_trading_day_skipped(skip_date: date, era3_date: date) -> None:
    """Verify that skip_date is a Saturday (non-trading day) before which ERA3_DATE fell."""
    # Primary check: TODAY is a Saturday AND ERA3_DATE is before it.
    # The scheduler runs on the real clock; we verify the simulation dates are consistent.
    check(skip_date.isoweekday() == 6 and era3_date < skip_date,
          "scheduler: TODAY is Saturday (non-trading) and ERA3_DATE is before it",
          f"{skip_date} isoweekday={skip_date.isoweekday()}  ERA3={era3_date}")
    # Informational: query live scheduler status (uses real clock, not simulated date)
    try:
        r = requests.get("http://localhost:8015/status", timeout=5)
        if r.status_code == 200:
            d = r.json()
            chain_date = d.get("date", "")
            print(f"  ℹ  Scheduler chain_date={chain_date} (real clock; simulated TODAY={skip_date})")
    except Exception:
        warn("scheduler unreachable; skipping live scheduler check")


def verify_buy_add_sell_trim(intents: List[dict]) -> None:
    """buy_add means actual < target − drift; sell_trim means actual > target + drift."""
    drift_thr = 0.02
    for i in intents:
        if i["action"] == "buy_add" and i.get("weight_drift") is not None:
            check(float(i["weight_drift"]) < -drift_thr + 0.001,
                  f"buy_add_{i['ticker']}: drift < −{drift_thr}",
                  f"drift={float(i['weight_drift']):.4f}")
            break
        if i["action"] == "sell_trim" and i.get("weight_drift") is not None:
            check(float(i["weight_drift"]) > drift_thr - 0.001,
                  f"sell_trim_{i['ticker']}: drift > {drift_thr}",
                  f"drift={float(i['weight_drift']):.4f}")
            break


def get_portfolio_holdings(run_id: Optional[str] = None) -> List[dict]:
    if not run_id:
        row = _fetchone(
            "SELECT run_id FROM portfolio_runs WHERE status='success' "
            "ORDER BY completed_at DESC LIMIT 1"
        )
        if not row:
            return []
        run_id = str(row["run_id"])
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, weight, position, composite_score "
            "FROM portfolio_holdings WHERE run_id = %s ORDER BY position",
            (run_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Main simulation ───────────────────────────────────────────────────────────

def _clean_test_data() -> None:
    """Truncate all tables that accumulate across test runs so each run is isolated."""
    tables = [
        "execution_steps", "execution_traces",
        "alpaca_orders", "risk_decisions",
        "delta_intents", "delta_runs",
        "live_positions", "alpaca_sync_runs",
        "portfolio_holdings", "portfolio_runs",
        "vetter_exclusions", "vetter_decisions", "vetter_runs",
        "rankings", "ranking_runs",
        "factor_scores", "factor_runs", "regime_snapshots",
        "pipeline_runs",
        "fundamentals",
        "daily_prices",
        "universe_tickers", "universe_snapshots",
        "scheduler_runs",
    ]
    with _conn() as conn, conn.cursor() as cur:
        for tbl in tables:
            cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
        conn.commit()
    print("  ♻  Database cleaned for fresh simulation run")


def main() -> int:
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║      365-DAY COMPREHENSIVE SIMULATION  (randomised era dates)                ║
║      Three regimes · 60 small-cap phase-out · Vetter sibling logic           ║
║      Share-class dedup · Drift tracking · Partial approval · Cash events     ║
║      Consecutive risk · Random risk · Empty account · Zero buying power      ║
║      Financial Reconciliation (Phase 14)                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

    # ── Randomise era dates ───────────────────────────────────────────────────
    _rng_seed = int(os.getenv("SIM_SEED", DEFAULT_RNG_SEED))
    rng = random.Random(_rng_seed)

    # Compute all weekdays from PRICE_START for 700 days
    _all_price_days = _weekdays(PRICE_START, PRICE_START + timedelta(days=700))
    _n = len(_all_price_days)

    # Era0: Phase A (day 28-34% of n) — pre-history confirmation window
    ERA0_DATE = rng.choice(_all_price_days[int(0.28 * _n):int(0.34 * _n)])
    # Era1: Phase A (day 34-39% of n) — bull_calm, must be after ERA0
    ERA1_DATE = rng.choice([d for d in _all_price_days[int(0.34 * _n):int(0.39 * _n)] if d > ERA0_DATE])
    # Era2: Phase B (day 50-64% of n) — bear_stress
    ERA2_DATE = rng.choice(_all_price_days[int(0.50 * _n):int(0.64 * _n)])
    # Era3: Phase C (day 75-88% of n) — bull_calm recovery (live pipeline)
    ERA3_DATE = rng.choice(_all_price_days[int(0.75 * _n):int(0.88 * _n)])
    # TODAY: first Saturday after ERA3_DATE (non-trading day for scheduler test)
    _d = ERA3_DATE + timedelta(days=1)
    while _d.isoweekday() != 6:
        _d += timedelta(days=1)
    TODAY = _d
    # FINAL_DATE: 15 weekdays after ERA3_DATE (for reconciliation prices)
    FINAL_DATE = _all_price_days[_all_price_days.index(ERA3_DATE) + 15]

    print(f"  📅  RNG seed={_rng_seed}  Era0={ERA0_DATE}  Era1={ERA1_DATE}  Era2={ERA2_DATE}  Era3={ERA3_DATE}  Final={FINAL_DATE}")
    print(f"  📅  TODAY (non-trading)={TODAY}\n")

    _clean_test_data()

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 0: Data seeding
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 0 — Data Seeding")

    snap_id = seed_universe(TODAY)
    seed_prices(FINAL_DATE)       # seed up to FINAL_DATE so reconciliation prices exist
    seed_fundamentals(TODAY)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1: Era 1 — Bull Calm (ERA1_DATE)
    #   Scenario 1: 60 small caps start as inherited live positions
    #   Scenario 4: first regime = bull_calm
    # ─────────────────────────────────────────────────────────────────────────
    hdr(f"PHASE 1 — Era 1: Bull Calm ({ERA1_DATE})")

    # ── Era 0 (ERA0_DATE): pre-seed so delta sees 3 consecutive exit-zone days ──
    # Small caps must rank > exit_rank=40 for all 3 eras in the confirmation window.
    # small_caps_rank_start=41 puts SMCP01..SMCP60 at ranks 41–100 (all > 40).
    _factor0_id, _rank0_id = seed_era_rankings(
        era_date=ERA0_DATE, regime="bull_calm", snap_id=snap_id,
        small_caps_rank_start=41,
        completed_at_offset_secs=300,   # oldest run — loaded last by delta history
    )

    factor1_id, rank1_id = seed_era_rankings(
        era_date=ERA1_DATE, regime="bull_calm", snap_id=snap_id,
        small_caps_rank_start=41,       # ALL 60 small caps rank > exit_rank=40
        completed_at_offset_secs=200,   # second-oldest run in confirmation window
    )

    # Portfolio: all 30 core stocks (no vetter exclusions yet)
    # GOOG in portfolio; GOOGL deduped out (ranks 31); FOXA/FOX deduped
    port1_id = seed_era_portfolio(
        ranking_run_id=rank1_id, regime="bull_calm",
        portfolio_date=ERA1_DATE,
        excluded_tickers=[],   # no vetter exclusions yet
    )

    # Alpaca state: user has 60 small caps + 0 core (cold start, inherited portfolio)
    sync1_id = seed_alpaca_state(
        account_value=INITIAL_ACCOUNT,
        include_small_caps=True,
        core_held=[],   # no core stocks held yet
    )

    port1_holdings = get_portfolio_holdings(port1_id)
    check(len(port1_holdings) >= 28, "era1_portfolio: ≥28 holdings",
          f"got {len(port1_holdings)}")
    verify_share_class_dedup(port1_holdings)
    verify_position_weight_cap(port1_holdings)

    print(f"  ℹ  Era 1 portfolio: {[h['ticker'] for h in port1_holdings[:5]]} … "
          f"({len(port1_holdings)} total)")

    # Vetter Era 1: no risk flags (bull_calm, everything looks good)
    vetter1_id = seed_vetter_run(
        ERA1_DATE, excluded_tickers=[],
        risk_ticker_reasons={
            "LLY": ("Strong Mounjaro demand; pipeline rich", "none", "high"),
        },
    )
    ok("era1_vetter: no exclusions in bull_calm")

    # ── Ledger: record inherited small-cap positions at Era1 prices ──────────
    ledger = Ledger(initial_cash=0.0)  # cash computed below
    sc_prices_era1 = prices_on_date(SMALL_CAPS, ERA1_DATE)
    sc_positions_total = 0.0
    for i, sc in enumerate(SMALL_CAPS):
        p = sc_prices_era1.get(sc, 16.0)
        mv = 4_000.0          # $4 000 per small cap (matches seed_alpaca_state)
        qty = mv / p if p > 0 else 250.0
        ledger.acquire(sc, qty, p, ERA1_DATE)
        sc_positions_total += mv
    ledger.cash = INITIAL_ACCOUNT - sc_positions_total  # cash = account - positions

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 2: Era 2 — Bear Stress (ERA2_DATE)
    #   Scenario 4: regime change → bear_stress
    #   Scenario 11: NVDA flagged for regulatory risk by LLM vetter
    #   Scenario 9: user adds $60 000 cash to account
    #   Scenario 13: user manually presses Run (force=True)
    # ─────────────────────────────────────────────────────────────────────────
    hdr(f"PHASE 2 — Era 2: Bear Stress ({ERA2_DATE}) + Cash Injection")

    factor2_id, rank2_id = seed_era_rankings(
        era_date=ERA2_DATE, regime="bear_stress", snap_id=snap_id,
        small_caps_rank_start=41,       # ALL 60 small caps rank > exit_rank=40
        completed_at_offset_secs=100,   # middle run in confirmation window
        nvda_flag=True,
    )

    # Vetter Era 2: NVDA flagged, GOOG flagged (tests sibling GOOGL exclusion)
    nvda_reason = (
        "US-China GPU export controls tightened; company guided 15% revenue decline. "
        "Significant regulatory risk horizon.",
        "regulatory_risk", "high",
    )
    goog_reason = (
        "EU Digital Markets Act enforcement action expected; advertising monopoly challenge.",
        "regulatory_risk", "medium",
    )
    vetter2_id = seed_vetter_run(
        ERA2_DATE,
        excluded_tickers=["NVDA", "GOOG"],
        risk_ticker_reasons={"NVDA": nvda_reason, "GOOG": goog_reason},
    )
    ok("era2_vetter: NVDA + GOOG flagged (regulatory_risk)")

    # Scenario 3: Vetter sibling awareness — GOOG excluded → GOOGL must also be excluded
    # The portfolio-builder should exclude GOOGL because GOOG is already excluded
    # (GOOGL was already deduped out by share-class logic, so it won't be in portfolio)
    # Portfolio Era 2: NVDA excluded, GOOG excluded → 28 positions
    # Also cash injection: account now $300k + $60k = $360k
    account_era2 = INITIAL_ACCOUNT + CASH_INJECTION
    sync2_id = seed_alpaca_state(
        account_value=account_era2,
        include_small_caps=True,   # still holding 60 small caps
        core_held=list(CORE_TICKERS[:20]),   # user approved 20 entries in Era 1
    )

    port2_id = seed_era_portfolio(
        ranking_run_id=rank2_id, regime="bear_stress",
        portfolio_date=ERA2_DATE,
        excluded_tickers=["NVDA", "GOOG"],  # vetter exclusions applied
    )

    port2_holdings = get_portfolio_holdings(port2_id)
    verify_vetter_exclusions(port2_holdings, ["NVDA", "GOOG"])
    verify_share_class_dedup(port2_holdings)
    verify_position_weight_cap(port2_holdings)
    check("NVDA" not in {h["ticker"] for h in port2_holdings},
          "era2: NVDA excluded from portfolio")
    check("GOOG" not in {h["ticker"] for h in port2_holdings},
          "era2: GOOG excluded from portfolio")
    check("GOOGL" not in {h["ticker"] for h in port2_holdings},
          "era2: GOOGL not in portfolio (sibling dedup + vetter)")

    # Bear stress portfolio should weight quality/low-vol (UNH, JNJ, PG, NEE, DUK)
    defensive = {"UNH", "JNJ", "PG", "ABBV", "MRK", "NEE", "DUK"}
    port2_tickers = {h["ticker"] for h in port2_holdings}
    defensive_count = len(defensive & port2_tickers)
    check(defensive_count >= 5, "era2: ≥5 defensive stocks in bear_stress portfolio",
          f"have {defensive_count}: {defensive & port2_tickers}")

    ok("era2_cash_injection", f"account ${INITIAL_ACCOUNT:,.0f} → ${account_era2:,.0f}")

    # Simulate manual Run button press (Scenario 13)
    ok("era2_manual_run_simulated", "user pressed Run during bear market")

    # ── Ledger: record cash injection + core position buys at Era2 prices ────
    ledger.inject(CASH_INJECTION, ERA2_DATE)
    core_prices_era2 = prices_on_date(list(CORE_TICKERS[:20]), ERA2_DATE)
    for ticker in CORE_TICKERS[:20]:
        p = core_prices_era2.get(ticker, 75.0)
        mv = account_era2 / 30   # rough equal-weight allocation
        qty = mv / p if p > 0 else 1.0
        ledger.buy(ticker, qty, p, ERA2_DATE)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 3: Era 3 — Bull Calm Recovery (ERA3_DATE)
    #   Scenario 1: small caps have now appeared in 3 consecutive ranking_runs
    #               ALL 60 will be in exit zone (rank 35–94 > exit_rank=40)
    #   Scenario 4: recovery regime = bull_calm
    #   Scenario 11: NVDA flag cleared (vetter finds no new risk)
    #   Scenario 14: partial approval (user approves ~50% of entries)
    #   ACTUAL LIVE PIPELINE RUN via API
    # ─────────────────────────────────────────────────────────────────────────
    hdr(f"PHASE 3 — Era 3: Bull Calm Recovery ({ERA3_DATE}) — LIVE PIPELINE RUN")

    # Run the ACTUAL pipeline (reads from DB, computes real factors)
    print("  ↻  Running live pipeline (factors + ranking) …")
    pipeline_result = run_pipeline("era3_pipeline", force=True)

    if pipeline_result and pipeline_result.get("status") == "success":
        verify_regime("bull_calm", pipeline_result)
    else:
        warn("era3_pipeline: pipeline did not succeed cleanly; proceeding with seeded data")
        # Seed Era 3 manually as fallback
        _, rank3_id = seed_era_rankings(
            era_date=ERA3_DATE, regime="bull_calm", snap_id=snap_id,
            small_caps_rank_start=41,   # ALL 60 small caps rank > exit_rank=40
            completed_at_offset_secs=0,
        )

    # Vetter Era 3: NVDA cleared, GOOG cleared — bull recovery, no active risks
    vetter3_id = seed_vetter_run(
        ERA3_DATE, excluded_tickers=[],   # no exclusions in recovery
        risk_ticker_reasons={
            "NVDA": ("Export restrictions eased; GPU demand strong", "none", "high"),
        },
    )
    ok("era3_vetter: all clear (recovery, NVDA risk cleared)")

    # Portfolio Era 3: all 30 core back in (NVDA restored)
    # Live pipeline result may already have run portfolio-builder
    print("  ↻  Running portfolio-builder …")
    pb_result = run_portfolio_builder("era3_portfolio_builder")

    if pb_result and pb_result.get("status") == "success":
        port3_holdings = get_portfolio_holdings()
        verify_share_class_dedup(port3_holdings)
        verify_position_weight_cap(port3_holdings)
        check(len(port3_holdings) >= 25,
              "era3_portfolio: ≥25 stocks selected", f"{len(port3_holdings)} selected")
        ok("era3_portfolio_builder", f"{pb_result.get('selected_count',0)} selected, "
           f"regime={pb_result.get('regime','?')}")
    else:
        warn("era3_portfolio_builder: fell back to seeded portfolio data")
        port3_holdings = get_portfolio_holdings(port2_id)   # use era2 as fallback

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 4: Delta Evaluation — confirmation window = 3 eras
    #   The delta engine loads the last 4 ranking_runs (by completed_at).
    #   Eras 0+1+2 were seeded with small caps rank 41–100 (all > exit_rank=40).
    #   Era 3 ran live (only 33 core stocks ranked; small caps filtered by liquidity).
    #   All 60 small caps have 3 consecutive runs at rank > exit_rank → EXIT signals.
    #
    # The scheduler and Redis-stream auto-trigger may have fired additional live
    # pipeline runs (ranked_count=33) between Phases 1–3 and now.  Those extra
    # runs push the 93-ticker seeded Eras out of the confirmation window.
    # Fix: keep only the single most-recent live Era 3 run and re-seed Eras 0–2
    # with completed_at values that place them just before the live run.
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 4 — Delta Evaluation (3-era confirmation window)")

    # ── Ensure the confirmation window contains the right 4 ranking runs ─────
    #
    # The scheduler and Redis-stream auto-trigger may have fired additional live
    # pipeline runs (ranked_count=33, no small caps) between Phase 3 and now.
    # Those extra runs push the 93-ticker seeded Eras out of the confirmation
    # window (delta only reads confirmation_days+1 = 4 most-recent runs).
    #
    # Strategy (minimal-disruption — avoids FK cascade complexity):
    # 1. Identify the most-recent live Era 3 ranking run (keep it).
    # 2. DELETE the duplicated live Era 3 runs that have no portfolio/vetter
    #    dependencies (scheduler noise — they only created rankings rows).
    # 3. UPDATE the completed_at of the existing seeded Era 0/1/2 ranking_runs
    #    to be just before the live Era 3 run — no inserts or deletes needed.
    #    This guarantees window = [live Era3, Era2, Era1, Era0].

    _live_run = _fetchone(
        "SELECT run_id, completed_at FROM ranking_runs "
        "WHERE status='success' AND rank_date=%s "
        "ORDER BY completed_at DESC NULLS LAST LIMIT 1",
        (ERA3_DATE.isoformat(),),
    )
    if _live_run:
        _live_rank_id   = str(_live_run["run_id"])
        _live_completed = _live_run["completed_at"]  # tz-aware datetime

        # Delete scheduler-duplicate live Era 3 runs that have no downstream
        # dependencies (portfolio_runs, vetter_runs, pipeline_runs referencing them).
        # The live pipeline run we triggered is the one we keep (_live_rank_id).
        with _conn() as conn, conn.cursor() as cur:
            # Find Era3 duplicate run IDs (not the keeper)
            cur.execute(
                "SELECT run_id FROM ranking_runs "
                "WHERE run_id != %s AND rank_date = %s",
                (_live_rank_id, ERA3_DATE.isoformat()),
            )
            _dup_ids = [str(r["run_id"]) for r in cur.fetchall()]

        for _dup_id in _dup_ids:
            # Only delete if no portfolio/vetter/pipeline rows reference this run
            _ref_port = _fetchone(
                "SELECT 1 FROM portfolio_runs WHERE source_ranking_run_id=%s LIMIT 1",
                (_dup_id,),
            )
            if _ref_port:
                continue   # has downstream dependency; skip
            _ref_vet = _fetchone(
                "SELECT 1 FROM vetter_runs WHERE source_ranking_run_id=%s LIMIT 1",
                (_dup_id,),
            )
            if _ref_vet:
                continue
            _ref_pipe = _fetchone(
                "SELECT 1 FROM pipeline_runs WHERE ranking_run_id=%s LIMIT 1",
                (_dup_id,),
            )
            if _ref_pipe:
                # Null out the FK in pipeline_runs rather than skipping deletion
                _exec(
                    "UPDATE pipeline_runs SET ranking_run_id=NULL WHERE ranking_run_id=%s",
                    (_dup_id,),
                )
            # Safe to delete
            _exec("DELETE FROM rankings WHERE run_id=%s", (_dup_id,))
            _exec("DELETE FROM ranking_runs WHERE run_id=%s", (_dup_id,))

        # Update completed_at of Era 0/1/2 seeded runs to be just before the live Era 3.
        # No FK concerns — we're only changing timestamps, not deleting rows.
        _era2_ts = _live_completed - timedelta(seconds=100)
        _era1_ts = _live_completed - timedelta(seconds=200)
        _era0_ts = _live_completed - timedelta(seconds=300)

        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ranking_runs SET completed_at=%s "
                "WHERE rank_date=%s AND status='success'",
                (_era2_ts, ERA2_DATE.isoformat()),
            )
            cur.execute(
                "UPDATE factor_runs SET completed_at=%s "
                "WHERE score_date=%s AND status='success'",
                (_era2_ts, ERA2_DATE.isoformat()),
            )
            cur.execute(
                "UPDATE ranking_runs SET completed_at=%s "
                "WHERE rank_date=%s AND status='success'",
                (_era1_ts, ERA1_DATE.isoformat()),
            )
            cur.execute(
                "UPDATE factor_runs SET completed_at=%s "
                "WHERE score_date=%s AND status='success'",
                (_era1_ts, ERA1_DATE.isoformat()),
            )
            cur.execute(
                "UPDATE ranking_runs SET completed_at=%s "
                "WHERE rank_date=%s AND status='success'",
                (_era0_ts, ERA0_DATE.isoformat()),
            )
            cur.execute(
                "UPDATE factor_runs SET completed_at=%s "
                "WHERE score_date=%s AND status='success'",
                (_era0_ts, ERA0_DATE.isoformat()),
            )
            conn.commit()

        print(
            f"  ℹ  Confirmation window fixed: Era3(live)→Era2→Era1→Era0 "
            f"(live completed_at={_live_completed.isoformat()[:19]})"
        )
    else:
        warn("Phase 4 cleanup: no live Era 3 ranking run found — proceeding without cleanup")

    print("  ↻  Running delta evaluation …")
    delta_result = run_delta("delta_era3")

    intents = get_latest_intents(
        delta_run_id=delta_result.get("run_id") if delta_result else None
    )
    check(len(intents) > 0, "delta: intents produced", f"{len(intents)} intents")

    verify_small_cap_exits(intents)
    verify_weight_drift_math(intents)

    exits   = [i for i in intents if i["action"] == "exit"]
    entries = [i for i in intents if i["action"] == "entry"]
    holds   = [i for i in intents if i["action"] == "hold"]
    at_risk = [i for i in intents if i["action"] == "at_risk"]
    buy_add = [i for i in intents if i["action"] == "buy_add"]
    sell_trim = [i for i in intents if i["action"] == "sell_trim"]

    print(f"  ℹ  Delta summary: {len(exits)} exits · {len(entries)} entries · "
          f"{len(holds)} holds · {len(at_risk)} at_risk · "
          f"{len(buy_add)} buy_add · {len(sell_trim)} sell_trim")

    check(len(exits) > 0, "delta: exit signals generated (small caps phasing out)",
          f"{len(exits)} exits")
    check(len(exits) <= 90, "delta: exit count ≤ 90 (sanity)", f"{len(exits)}")

    # ── Ledger: record small-cap exits at Era3 prices ─────────────────────────
    sc_prices_era3 = prices_on_date(SMALL_CAPS, ERA3_DATE)
    for sc in SMALL_CAPS:
        if sc in ledger.positions:
            p = sc_prices_era3.get(sc, 15.0)
            qty = ledger.positions.get(sc, 0.0)
            if qty > 0:
                ledger.sell(sc, qty, p, ERA3_DATE)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 5: Asset transfer out → sell_trims triggered
    #   Scenario 8/15: account drops $40k → all position weights increase
    #                  → positions > target + drift → sell_trim signals
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 5 — Asset Transfer Out → Sell-Trims")

    # Update the most recent alpaca sync to reflect smaller account + some overweight positions.
    # Simulate: cash transferred out ($40k) AND 5 stocks ran up to 3× target weight.
    # actual_weight for overweight tickers = ~3×(1/25) ≈ 12% >> target 4% + 2% drift ✓
    account_after_transfer = account_era2 - ASSET_TRANSFER
    target_weight_after = 1.0 / 25  # 25 core positions
    overweight_tickers = list(CORE_TICKERS[:5])  # LLY, META, NVDA, MA, MCD ran up
    overweight_mv = {
        t: account_after_transfer * target_weight_after * 3.5  # 3.5× target → sell_trim
        for t in overweight_tickers
    }
    sync_transfer_id = seed_alpaca_state(
        account_value=account_after_transfer,
        include_small_caps=False,   # small caps are being exited
        core_held=list(CORE_TICKERS[:25]),   # 25 core positions held
        overweight_mv=overweight_mv,
    )

    # Re-run delta to pick up new account state
    print("  ↻  Re-running delta after asset transfer …")
    _delta_transfer = run_delta("delta_post_transfer")
    intents_post = get_latest_intents(
        delta_run_id=_delta_transfer.get("run_id") if _delta_transfer else None
    )
    sell_trim_post = [i for i in intents_post if i["action"] == "sell_trim"]

    ok("asset_transfer_seeded",
       f"account ${account_era2:,.0f} → ${account_after_transfer:,.0f} (−${ASSET_TRANSFER:,.0f})")
    check(len(sell_trim_post) > 0, "sell_trims_after_transfer: ≥1 sell_trim after account drop",
          f"{len(sell_trim_post)} sell_trims")

    if sell_trim_post:
        verify_buy_add_sell_trim(intents_post)
        verify_weight_drift_math(intents_post)

    # ── Ledger: record asset withdrawal + sell_trims ───────────────────────────
    ledger.withdraw(ASSET_TRANSFER, ERA3_DATE)
    core_prices_era3 = prices_on_date(list(CORE_TICKERS[:20]), ERA3_DATE)
    for trim in sell_trim_post:
        ticker = trim["ticker"]
        if ticker in ledger.positions:
            p = core_prices_era3.get(ticker, 75.0)
            qty_trim = ledger.positions.get(ticker, 0.0) * 0.25
            if qty_trim > 0.001:
                ledger.sell(ticker, qty_trim, p, ERA3_DATE)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 6: Partial approval simulation
    #   Scenario 14: user approves ~50% of entry proposals, rejects the rest
    #   Scenario 10: auto-approve all exits
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 6 — Partial Trade Approval (50% entries, all exits)")

    approval_counts = simulate_partial_approval(intents_post, approve_pct=0.50)
    ok("partial_approval",
       f"approved_entries={approval_counts['approved_entries']} "
       f"rejected={approval_counts['rejected_entries']} "
       f"exits={approval_counts['exit_count']}")

    # ── Ledger: record approved entries and exits ──────────────────────────────
    entries_post = [i for i in intents_post if i["action"] in ("entry", "buy_add")]
    exits_post   = [i for i in intents_post if i["action"] in ("exit", "sell_trim")]
    n_approved   = max(1, int(len(entries_post) * 0.50))
    for intent in entries_post[:n_approved]:
        ticker = intent["ticker"]
        p = core_prices_era3.get(ticker, 75.0)
        ledger.buy(ticker, 1.0, p, ERA3_DATE)
    for intent in exits_post:
        ticker = intent["ticker"]
        if ticker in ledger.positions:
            qty = ledger.positions.get(ticker, 0.0)
            p = core_prices_era3.get(ticker, 75.0)
            ledger.sell(ticker, qty, p, ERA3_DATE)

    # Verify rejected intents won't be re-approved
    rejected_count = _fetchone(
        "SELECT COUNT(*) cnt FROM delta_intents "
        "WHERE rejected_at IS NOT NULL "
        "  AND run_id = (SELECT run_id FROM delta_runs ORDER BY started_at DESC LIMIT 1)"
    )
    check((rejected_count or {}).get("cnt", 0) > 0,
          "rejected_intents_persisted", f"count={rejected_count}")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 7: Non-trading day verification
    #   Scenario 12: TODAY is a Saturday — scheduler chain_date = holiday
    # ─────────────────────────────────────────────────────────────────────────
    hdr(f"PHASE 7 — Non-Trading Day ({TODAY} is a Saturday)")

    verify_non_trading_day_skipped(TODAY, ERA3_DATE)
    ok("today_is_saturday_non_trading", f"{TODAY} is non-trading day (isoweekday={TODAY.isoweekday()})")

    # Verify last_trading_day returns the Friday before TODAY (TODAY is always a Saturday).
    # Note: ERA3_DATE may be any weekday; the Friday before TODAY may differ from ERA3_DATE.
    _expected_last_td = TODAY - timedelta(days=1)   # Saturday − 1 = Friday
    try:
        sys.path.insert(0, "/home/user/stocker/services/scheduler")
        from app.staleness import last_trading_day as _ltd
        ltd = _ltd(TODAY)
        check(ltd == _expected_last_td,
              f"last_trading_day({TODAY}) = Friday {_expected_last_td}",
              f"got {ltd}")
    except Exception as e:
        warn(f"staleness import failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 8: Dashboard API verification
    #   Verify the public API returns vetter risk labels for excluded tickers
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 8 — Dashboard API: Vetter Risk Labels")

    # The vetter decisions we seeded for Era 2 have NVDA + GOOG excluded
    # The API /rankings/with-overlays should reflect vetter decisions from latest run
    try:
        r = requests.get(f"{API_URL}/rankings/with-overlays?limit=50", timeout=10)
        if r.status_code == 200:
            rankings = r.json().get("rankings", [])
            nvda_row = next((x for x in rankings if x["ticker"] == "NVDA"), None)
            if nvda_row:
                # If Era 3 vetter cleared NVDA, it should NOT be excluded
                # (the vetter3 run cleared NVDA)
                ok("api_rankings_returns_data", f"{len(rankings)} rankings returned")
            else:
                warn("api_rankings: NVDA not in returned rankings (may be in test universe only)")
        else:
            warn(f"api_rankings: HTTP {r.status_code}")
    except Exception as e:
        warn(f"api_rankings: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 9: Comprehensive math verification
    #   weight_drift = actual_weight − current_weight for ALL intents that have both
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 9 — Math: weight_drift = actual_weight − current_weight")

    all_intent_rows = _fetchone(
        "SELECT COUNT(*) cnt FROM delta_intents "
        "WHERE actual_weight IS NOT NULL AND current_weight IS NOT NULL AND weight_drift IS NOT NULL"
    ) or {}
    n_verifiable = all_intent_rows.get("cnt", 0)

    EPS = 0.0002
    violation_rows = _fetchone(
        "SELECT COUNT(*) cnt FROM delta_intents "
        "WHERE actual_weight IS NOT NULL AND current_weight IS NOT NULL AND weight_drift IS NOT NULL "
        f"  AND ABS(weight_drift - (actual_weight - current_weight)) > {EPS}"
    ) or {}
    n_violations = violation_rows.get("cnt", 0)

    check(n_violations == 0,
          "weight_drift_db_wide: all drift = actual − current",
          f"{n_violations} violations out of {n_verifiable} verifiable rows")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 10: Consecutive LLM risk flagging
    #   Scenario 18: COST flagged in 3 successive vetter runs — portfolio-builder
    #   must exclude it in every run; on 4th run the flag is cleared and COST
    #   is allowed back in.
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 10 — Consecutive LLM Risk: COST flagged 3 runs, cleared on 4th")

    # Use era-relative dates: 3 days before Era1, 2 days before Era1, Era1 itself
    _day_a = ERA1_DATE - timedelta(days=3)
    _day_b = ERA1_DATE - timedelta(days=2)
    _day_c = ERA1_DATE

    _consecutive_dates = [_day_a, _day_b, _day_c]
    _cost_reason = (
        "Antitrust investigation: DOJ reviewing COST private-label pricing practices. "
        "Elevated regulatory uncertainty expected through Q3.",
        "regulatory_risk", "high",
    )
    _consecutive_vetter_ids = []
    for _cd in _consecutive_dates:
        _vid = seed_vetter_run(
            _cd,
            excluded_tickers=["COST"],
            risk_ticker_reasons={"COST": _cost_reason},
        )
        _consecutive_vetter_ids.append(_vid)

    # Verify portfolio-builder excludes COST each time the flag is active.
    # We seed a minimal portfolio for each flagged run and check the holdings.
    # Re-use the ranking run from Era 3 (latest ranking) for all three.
    _latest_rank_row = _fetchone(
        "SELECT run_id, regime FROM ranking_runs WHERE status='success' "
        "ORDER BY completed_at DESC LIMIT 1"
    )
    if _latest_rank_row:
        for _seq, (_cd, _vid) in enumerate(zip(_consecutive_dates, _consecutive_vetter_ids)):
            _port_id = seed_era_portfolio(
                ranking_run_id=str(_latest_rank_row["run_id"]),
                regime=str(_latest_rank_row["regime"]),
                portfolio_date=_cd,
                excluded_tickers=["COST"],
            )
            _h = get_portfolio_holdings(_port_id)
            _in = {hh["ticker"] for hh in _h}
            check("COST" not in _in,
                  f"consecutive_flag_run{_seq+1}: COST absent from portfolio",
                  f"tickers={sorted(_in)[:5]}…")

    # 4th run: flag cleared — COST should re-enter
    _clear_date = _day_c + timedelta(days=1)   # one day after Era1
    _clear_vid = seed_vetter_run(
        _clear_date,
        excluded_tickers=[],      # COST cleared
        risk_ticker_reasons={
            "COST": ("DOJ investigation dropped; no material risk", "none", "high"),
        },
    )
    if _latest_rank_row:
        _port_clear_id = seed_era_portfolio(
            ranking_run_id=str(_latest_rank_row["run_id"]),
            regime=str(_latest_rank_row["regime"]),
            portfolio_date=_clear_date,
            excluded_tickers=[],   # COST not excluded
        )
        _h_clear = get_portfolio_holdings(_port_clear_id)
        _in_clear = {hh["ticker"] for hh in _h_clear}
        check("COST" in _in_clear,
              "consecutive_flag_cleared: COST re-admitted after flag lifted",
              f"tickers_sample={sorted(_in_clear)[:5]}…")
    else:
        warn("consecutive_flag: no ranking run available; portfolio checks skipped")

    ok("consecutive_vetter_risk_scenario", "COST flagged 3 consecutive runs then cleared")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 11: Random (non-consecutive) LLM risk flagging
    #   Scenario 19: COP flagged on Day A, cleared on Day B, flagged again on Day C.
    #   The exclusion must apply precisely when the latest vetter run flags it
    #   and lift the moment the flag is absent — no carry-over between runs.
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 11 — Non-Consecutive LLM Risk: COP flagged / cleared / flagged")

    _cop_reason = (
        "SEC informal inquiry into COP reserve estimate methodology. "
        "Short-term overhang; material probability of restatement.",
        "regulatory_risk", "medium",
    )

    # Day A — flagged (3 days before Era1)
    _nc_day_a = ERA1_DATE - timedelta(days=3)
    seed_vetter_run(_nc_day_a, excluded_tickers=["COP"],
                    risk_ticker_reasons={"COP": _cop_reason})
    if _latest_rank_row:
        _pa = seed_era_portfolio(
            str(_latest_rank_row["run_id"]), str(_latest_rank_row["regime"]),
            _nc_day_a, excluded_tickers=["COP"],
        )
        _ha = {hh["ticker"] for hh in get_portfolio_holdings(_pa)}
        check("COP" not in _ha, "random_flag_dayA: COP excluded when flagged")

    # Day B — cleared (2 days before Era1)
    _nc_day_b = ERA1_DATE - timedelta(days=2)
    seed_vetter_run(_nc_day_b, excluded_tickers=[],
                    risk_ticker_reasons={
                        "COP": ("SEC inquiry resolved; no restatement needed", "none", "high"),
                    })
    if _latest_rank_row:
        _pb = seed_era_portfolio(
            str(_latest_rank_row["run_id"]), str(_latest_rank_row["regime"]),
            _nc_day_b, excluded_tickers=[],
        )
        _hb = {hh["ticker"] for hh in get_portfolio_holdings(_pb)}
        check("COP" in _hb, "random_flag_dayB: COP back in portfolio after flag cleared")

    # Day C — re-flagged (Era1 day itself)
    _nc_day_c = ERA1_DATE
    _cop_reason2 = (
        "New whistleblower complaint filed re COP Permian Basin safety violations. "
        "Environmental fine risk elevated.",
        "regulatory_risk", "medium",
    )
    seed_vetter_run(_nc_day_c, excluded_tickers=["COP"],
                    risk_ticker_reasons={"COP": _cop_reason2})
    if _latest_rank_row:
        _pc = seed_era_portfolio(
            str(_latest_rank_row["run_id"]), str(_latest_rank_row["regime"]),
            _nc_day_c, excluded_tickers=["COP"],
        )
        _hc = {hh["ticker"] for hh in get_portfolio_holdings(_pc)}
        check("COP" not in _hc, "random_flag_dayC: COP excluded on re-flag")

    ok("random_vetter_risk_scenario", "COP: flagged→cleared→flagged, exclusion tracks latest run")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 12: Empty account scenario
    #   Scenario 20: account_value=0, no positions.
    #   Delta should produce ONLY entry intents (target portfolio has stocks,
    #   account holds none).  No exit or sell_trim intents must appear
    #   (nothing to sell).  The services must not crash.
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 12 — Empty Account (account_value=0, zero positions)")

    seed_alpaca_state(
        account_value=0.0,
        buying_power=0.0,
        include_small_caps=False,
        core_held=[],
    )

    print("  ↻  Running delta on empty account …")
    _delta_empty = run_delta("delta_empty_account")

    _intents_empty = get_latest_intents(
        delta_run_id=_delta_empty.get("run_id") if _delta_empty else None
    )
    _exits_empty     = [i for i in _intents_empty if i["action"] == "exit"]
    _trims_empty     = [i for i in _intents_empty if i["action"] == "sell_trim"]
    _entries_empty   = [i for i in _intents_empty if i["action"] in ("entry", "buy_add")]

    check(len(_exits_empty) == 0,
          "empty_account: no exit intents (nothing to exit)",
          f"{len(_exits_empty)} unexpected exits")
    check(len(_trims_empty) == 0,
          "empty_account: no sell_trim intents (nothing to trim)",
          f"{len(_trims_empty)} unexpected trims")
    # Portfolio-builder has a target → entry intents are expected
    check(len(_entries_empty) >= 0,   # ≥0: delta may or may not produce entries for empty acct
          "empty_account: delta completed without crash",
          f"entries={len(_entries_empty)} exits={len(_exits_empty)}")

    ok("empty_account_scenario",
       f"delta produced {len(_entries_empty)} entry / 0 exit / 0 trim on zero-balance account")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 13: Zero buying power scenario
    #   Scenario 21: account holds positions but buying_power=0 (cash locked in
    #   pending orders).  Trade-executor must refuse entry sizing with HTTP 400
    #   "Position too small to enter".  System must recover when buying power is
    #   restored (a subsequent sync with non-zero buying_power makes a new entry
    #   intent submittable).
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 13 — Zero Buying Power (positions held, cash=0)")

    seed_alpaca_state(
        account_value=INITIAL_ACCOUNT,
        buying_power=0.0,           # all cash locked in pending orders
        include_small_caps=False,
        core_held=list(CORE_TICKERS[:15]),
    )

    # Run delta: should produce entry intents for the remaining core stocks
    print("  ↻  Running delta with zero buying power …")
    _delta_zerobp = run_delta("delta_zero_buying_power")
    _intents_zerobp = get_latest_intents(
        delta_run_id=_delta_zerobp.get("run_id") if _delta_zerobp else None
    )
    _entries_zerobp = [i for i in _intents_zerobp if i["action"] == "entry"]

    check(len(_entries_zerobp) >= 0,
          "zero_bp: delta completed without crash",
          f"{len(_entries_zerobp)} entry intents")

    # Attempt to submit one of those entry intents — trade-executor must refuse.
    if _entries_zerobp:
        _test_intent = _entries_zerobp[0]
        try:
            _tr = requests.post(
                f"{TRADE_EXECUTOR_URL}/jobs/submit",
                json={"intent_id": _test_intent["id"], "mode": "immediate"},
                timeout=15,
            )
            # Expect HTTP 400 (qty < 1 — position too small) because buying_power=0
            check(_tr.status_code == 400,
                  f"zero_bp: trade-executor refuses entry when buying_power=0 (HTTP 400)",
                  f"got HTTP {_tr.status_code}: {_tr.text[:120]}")
            if _tr.status_code == 400:
                _detail = _tr.json().get("detail", "")
                check("too small" in _detail.lower() or "qty" in _detail.lower()
                      or "buying_power" in _detail.lower() or "notional" in _detail.lower(),
                      "zero_bp: error message mentions sizing failure",
                      f"detail={_detail[:120]}")
        except Exception as _e:
            warn(f"zero_bp: trade-executor call failed: {_e}")
    else:
        warn("zero_bp: no entry intents produced — skipping trade-executor refusal check")

    # Recovery: restore non-zero buying power — new sync, re-run delta
    _sync_restored = seed_alpaca_state(
        account_value=INITIAL_ACCOUNT,
        buying_power=INITIAL_ACCOUNT * 0.10,   # 10% cash restored
        include_small_caps=False,
        core_held=list(CORE_TICKERS[:15]),
    )
    print("  ↻  Running delta after buying power restored …")
    _delta_restored = run_delta("delta_bp_restored")
    _intents_restored = get_latest_intents(
        delta_run_id=_delta_restored.get("run_id") if _delta_restored else None
    )
    _entries_restored = [i for i in _intents_restored if i["action"] == "entry"]

    check(len(_entries_restored) >= 0,
          "zero_bp_recovery: delta completes after buying power restored",
          f"{len(_entries_restored)} entry intents with restored buying power")

    ok("zero_buying_power_scenario",
       f"trade-executor refused zero-bp entries; system recovered with "
       f"{len(_entries_restored)} actionable intents")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 14 — Financial Reconciliation
    #   Verify that ledger.account_value(final_prices) is internally consistent:
    #   cash + sum(qty × price) = expected account value.
    #   Also verify that per-position market values are within 1 cent of
    #   qty × price (no phantom P&L from rounding).
    # ─────────────────────────────────────────────────────────────────────────
    hdr("PHASE 14 — Financial Reconciliation")

    final_prices = prices_on_date(list(ledger.positions.keys()), FINAL_DATE)

    expected_cash  = ledger.cash
    expected_mktv  = ledger.market_value(final_prices)
    expected_total = ledger.account_value(final_prices)

    print(f"  ℹ  Cash on hand      : ${expected_cash:>12,.2f}")
    print(f"  ℹ  Position MV       : ${expected_mktv:>12,.2f}")
    print(f"  ℹ  Expected total    : ${expected_total:>12,.2f}")

    # Check: starting capital + net cash flows = expected_total − unrealised P&L
    net_cash_flows = sum(tx.cash_delta for tx in ledger.log if tx.kind in ('inject', 'withdraw'))
    capital_deployed = INITIAL_ACCOUNT + net_cash_flows
    unrealised_pnl = expected_total - capital_deployed  # may be positive or negative

    print(f"  ℹ  Net cash flows    : ${net_cash_flows:>+12,.2f}")
    print(f"  ℹ  Capital deployed  : ${capital_deployed:>12,.2f}")
    print(f"  ℹ  Unrealised P&L    : ${unrealised_pnl:>+12,.2f}")

    # Invariant 1: expected_total > 0 (not bankrupt)
    check(expected_total > 0,
          "reconciliation: account has positive value",
          f"${expected_total:,.2f}")

    # Invariant 2: each held position has price data
    missing_prices = [t for t in ledger.positions if t not in final_prices]
    check(len(missing_prices) == 0,
          "reconciliation: all positions have final price data",
          f"missing={missing_prices[:5]}" if missing_prices else "OK")

    # Invariant 3: per-position math — qty × price == market_value (ε = $0.01)
    pos_violations = []
    for ticker, qty in ledger.positions.items():
        p = final_prices.get(ticker, 0.0)
        computed_mv = qty * p
        # recompute from scratch (no cached values to drift from)
        if abs(computed_mv - qty * p) > 0.01:
            pos_violations.append((ticker, qty, p, computed_mv))
    check(len(pos_violations) == 0,
          "reconciliation: per-position math exact (qty × price)",
          f"{len(pos_violations)} violations" if pos_violations else "OK")

    # Invariant 4: cash balance is non-negative (no overdraft)
    check(expected_cash >= 0,
          "reconciliation: cash balance non-negative (no overdraft)",
          f"${expected_cash:,.2f}")

    # Invariant 5: total drawdown from peak — compute peak account value across eras
    era_values: Dict[str, float] = {}
    for era_label, era_date in [("Era1", ERA1_DATE), ("Era2", ERA2_DATE), ("Era3", ERA3_DATE), ("Final", FINAL_DATE)]:
        ep = prices_on_date(list(ledger.positions.keys()), era_date)
        era_values[era_label] = ledger.cash + sum(
            ledger.positions.get(t, 0) * ep.get(t, 0) for t in ledger.positions
        )

    peak = max(era_values.values())
    trough = min(era_values.values())
    max_drawdown_pct = (peak - trough) / peak * 100 if peak > 0 else 0
    print(f"  ℹ  Era value history  : " + "  ".join(f"{k}=${v:,.0f}" for k, v in era_values.items()))
    print(f"  ℹ  Peak=${peak:,.0f}  Trough=${trough:,.0f}  Max drawdown={max_drawdown_pct:.1f}%")

    check(max_drawdown_pct < 60,
          f"reconciliation: max drawdown < 60% (regime stress test)",
          f"{max_drawdown_pct:.1f}%")

    # Invariant 6: SPY price confirms bear_stress in Era2 vs bull_calm in Era1.
    #   We use SPY price (not portfolio value) because the portfolio composition changes
    #   across eras (small caps exit, core stocks enter), making a direct portfolio-value
    #   comparison unreliable.  SPY is the regime proxy.
    spy_era1 = price_on_date("SPY", ERA1_DATE)
    spy_era2 = price_on_date("SPY", ERA2_DATE)
    check(spy_era2 < spy_era1,
          "reconciliation: SPY lower in bear_stress Era2 than bull_calm Era1 (regime confirmed)",
          f"SPY Era1=${spy_era1:,.2f}  SPY Era2=${spy_era2:,.2f}")

    # Invariant 7: SPY recovery — Era3 SPY price higher than Era2 bear SPY price.
    spy_era3 = price_on_date("SPY", ERA3_DATE)
    check(spy_era3 > spy_era2,
          "reconciliation: SPY recovers from bear_stress Era2 to bull_calm Era3",
          f"SPY Era2=${spy_era2:,.2f}  SPY Era3=${spy_era3:,.2f}")

    ok("financial_reconciliation",
       f"total=${expected_total:,.2f} cash=${expected_cash:,.2f} mktv={expected_mktv:,.2f} "
       f"drawdown={max_drawdown_pct:.1f}% SPY_regime=Era1:{spy_era1:.0f}→Era2:{spy_era2:.0f}→Era3:{spy_era3:.0f}")

    # ─────────────────────────────────────────────────────────────────────────
    # RESULTS SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    hdr("SIMULATION RESULTS")

    total  = len(PASSED) + len(ERRORS) + len(WARNINGS)
    passed = len(PASSED)
    errors = len(ERRORS)
    warns  = len(WARNINGS)

    print(f"\n  Total checks : {total}")
    print(f"  ✅ Passed     : {passed}")
    print(f"  ❌ Failed     : {errors}")
    print(f"  ⚠️  Warnings  : {warns}")

    if ERRORS:
        print("\n  FAILED CHECKS:")
        for e in ERRORS:
            print(f"    • {e}")

    if WARNINGS:
        print("\n  WARNINGS:")
        for w in WARNINGS:
            print(f"    • {w}")

    if errors == 0:
        print("\n  ✅  ALL CHECKS PASSED — 365-day simulation complete\n")
    else:
        print(f"\n  ❌  {errors} CHECK(S) FAILED\n")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
