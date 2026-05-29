"""
30-day simulation designed to exercise all four trade action types
(entry, exit, buy_add, sell_trim) and verify the sizing math for each.

Design:
  - 100 tickers so the ≥100 universe guard passes
  - 5 named positions seeded at deliberately wrong weights on day 0:
      AAPL  $20k (20% of $100k total) → sell_trim (>>3.3% equal-weight target)
      SNDK  $10k (10%)               → sell_trim (>10% cap, >3.3% target)
      V     $400  (0.4%)              → buy_add (<<3.3%, drift > 2% threshold)
      MU    $400  (0.4%)              → buy_add
      KEYS  $400  (0.4%)              → buy_add
    Remaining cash: $68,800 → account_value ≈ $100k total

  - Regime change at day 10: bull_calm → bear_stress
      bull_calm weights momentum heavily (0.30) — AAPL / SNDK stay ranked
      bear_stress weights low_vol / quality (0.35 / 0.27) — momentum falls
      Momentum stocks that drop below exit_rank for confirmation_days (3)
      produce exit intents; new low_vol/quality names produce new entries.

Trade type trigger timeline:
  Day  0-1  : sell_trim (AAPL / SNDK), buy_add (V / MU / KEYS),
               entry for ~20-25 unranked names
  Days 2-9  : mostly hold; small drift may produce additional buy_add/sell_trim
  Days 10-12: regime flip — at_risk for falling tickers
  Days 13-16: exit (confirmation met) + entry for new top-ranked names
  Days 17-30: portfolio stabilises in bear_stress regime
"""
from datetime import date

from tests.harness.harness.scenario import InitialPosition, RegimeChange, Scenario

# ── Named tickers ─────────────────────────────────────────────────────────────

_NAMED = [
    {"ticker": "AAPL",  "name": "Apple Inc",                 "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "SNDK",  "name": "Sandisk Corp",               "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "V",     "name": "Visa Inc",                   "sector": "Financials",             "exchange": "NYSE"},
    {"ticker": "MU",    "name": "Micron Technology Inc",      "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "KEYS",  "name": "Keysight Technologies Inc",  "sector": "Information Technology", "exchange": "NYSE"},
    # Extra named tickers (NOT seeded) to diversify the universe and ensure
    # there are quality/low_vol candidates ready to enter after the regime flip
    {"ticker": "JNJ",   "name": "Johnson & Johnson",          "sector": "Health Care",            "exchange": "NYSE"},
    {"ticker": "PG",    "name": "Procter & Gamble Co",        "sector": "Consumer Staples",       "exchange": "NYSE"},
    {"ticker": "KO",    "name": "Coca-Cola Co",               "sector": "Consumer Staples",       "exchange": "NYSE"},
    {"ticker": "VZ",    "name": "Verizon Communications Inc", "sector": "Communication Services", "exchange": "NYSE"},
    {"ticker": "XOM",   "name": "Exxon Mobil Corp",           "sector": "Energy",                 "exchange": "NYSE"},
]

COMPREHENSIVE_TRADE_TYPES = Scenario(
    name="comprehensive_trade_types",
    seed=20240102,
    # 10 named + 90 generated = 100 tickers (satisfies ≥100 universe guard)
    universe_size=100,
    start_date=date(2024, 1, 2),
    end_date=date(2024, 2, 15),   # ~30 trading days
    regimes=[
        RegimeChange(date(2024, 1, 2),  "bull_calm"),    # days 0-9
        RegimeChange(date(2024, 1, 16), "bear_stress"),  # day 10+: momentum falls
    ],
    run_vetter=False,   # disabled so all trade types depend on ranking math only
    # ── Initial positions (seeded after day-0 fetch-data) ────────────────────
    # initial_cash is the remaining cash AFTER position values are seeded.
    # Total account value = initial_cash + sum(seed values) ≈ $100k
    initial_cash=68_800.0,
    initial_positions=[
        InitialPosition(ticker="AAPL",  value_usd=20_000.0),  # 20% → sell_trim
        InitialPosition(ticker="SNDK",  value_usd=10_000.0),  # 10% → sell_trim
        InitialPosition(ticker="V",     value_usd=400.0),     # 0.4% → buy_add
        InitialPosition(ticker="MU",    value_usd=400.0),     # 0.4% → buy_add
        InitialPosition(ticker="KEYS",  value_usd=400.0),     # 0.4% → buy_add
    ],
    extra_tickers=_NAMED,
    description=(
        "30-day simulation exercising all 4 trade types: "
        "entry (day 0 unranked tickers), "
        "sell_trim (AAPL/SNDK seeded over-weight), "
        "buy_add (V/MU/KEYS seeded under-weight), "
        "exit (regime flip bull_calm→bear_stress day 10, "
        "exits from momentum stocks after confirmation_days=3)"
    ),
)
