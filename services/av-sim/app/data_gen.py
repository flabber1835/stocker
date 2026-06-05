"""
Deterministic data generation for the Alpha Vantage simulator.

All generated data is derived from a seeded RNG so that the same
scenario load_scenario() call always produces identical output. The
module owns no mutable global state — the caller (main.py) owns the
state dicts and passes them in.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTORS: list[str] = [
    "Information Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
]

# Benchmark ETFs that are always included in the universe (for price lookups
# by av-ingestor) but are NOT included in LISTING_STATUS because the
# av-ingestor filters them out (assetType != "Stock").
BENCHMARK_TICKERS: list[str] = ["SPY", "QQQ", "IWM", "SOXX"]

# GBM regime parameters: (drift_per_day, sigma_per_day)
REGIME_PARAMS: dict[str, dict[str, float]] = {
    "bull_calm":   {"drift": 0.0004,  "sigma": 0.008},
    "bull_stress": {"drift": 0.0001,  "sigma": 0.014},
    "bear_stress": {"drift": -0.0008, "sigma": 0.018},
    "bear_calm":   {"drift": -0.0003, "sigma": 0.011},
}

# Fundamentals quality/growth tier ranges
QUALITY_ROE: dict[int, tuple[float, float]] = {
    1: (0.15, 0.35),
    2: (0.08, 0.18),
    3: (-0.02, 0.10),
}
QUALITY_DEBT_EQUITY: dict[int, tuple[float, float]] = {
    1: (0.1, 0.8),
    2: (0.5, 1.5),
    3: (1.2, 3.0),
}
GROWTH_EPS: dict[int, tuple[float, float]] = {
    1: (0.15, 0.50),
    2: (0.02, 0.20),
    3: (-0.15, 0.05),
}
GROWTH_REVENUE: dict[int, tuple[float, float]] = {
    1: (0.10, 0.40),
    2: (0.02, 0.15),
    3: (-0.10, 0.05),
}

# Bearish news templates (for ~10% of tickers in bear_stress regime)
_BEARISH_TITLES: list[str] = [
    "{ticker} shares slide as SEC launches investigation",
    "{ticker} cuts full-year guidance amid softening demand",
    "{ticker} misses Q2 estimates; management cites macro headwinds",
    "{ticker} CFO departure raises governance concerns",
    "{ticker} probed by FTC over anti-competitive practices",
]
_BULLISH_TITLES: list[str] = [
    "{ticker} beats Q2 earnings estimates on strong revenue growth",
    "{ticker} raises full-year outlook, cites robust demand pipeline",
    "{ticker} announces $2B share buyback programme",
    "{ticker} wins major contract boosting backlog by 25%",
    "{ticker} reports record free cash flow; dividend increased",
    "{ticker} upgraded to Buy as analyst raises price target",
    "{ticker} reports better-than-expected margin expansion",
]
_NEUTRAL_TITLES: list[str] = [
    "{ticker} reports in-line Q2 results, maintains guidance",
    "{ticker} management hosts investor day; long-term targets reiterated",
    "{ticker} completes acquisition of mid-size competitor",
    "{ticker} files 10-Q; no material changes from prior quarter",
]

_SOURCES: list[str] = [
    "Reuters", "Bloomberg", "CNBC", "MarketWatch", "WSJ",
    "Seeking Alpha", "Barron's", "Yahoo Finance", "The Street",
]


# ---------------------------------------------------------------------------
# Ticker universe generation
# ---------------------------------------------------------------------------

def _ticker_hash_seed(ticker: str) -> int:
    """Stable integer seed derived from ticker name."""
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


def generate_universe_tickers(universe_size: int, seed: int) -> list[dict[str, Any]]:
    """
    Generate a universe of tickers with stable sector and name assignments.

    Returns a list of dicts with keys: ticker, name, exchange, sector.
    Does NOT include benchmark tickers — those are added separately by the caller.
    """
    rng = random.Random(seed)

    # Build ticker symbols: 4-letter codes (AATO, ABCO, …)
    # We generate more candidates than needed so that deduplication never
    # leaves us short.
    candidates: list[str] = []
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    seen: set[str] = set()
    attempt = 0
    while len(candidates) < universe_size:
        attempt += 1
        # Vary length (3–4 chars) to create a realistic mix.
        length = 4 if (attempt % 5 != 0) else 3
        ticker = "".join(rng.choices(alphabet, k=length))
        if ticker in seen or ticker in set(BENCHMARK_TICKERS):
            continue
        seen.add(ticker)
        candidates.append(ticker)

    tickers: list[dict[str, Any]] = []
    exchanges = ["NYSE", "NASDAQ"]
    for i, sym in enumerate(candidates):
        sector = SECTORS[i % len(SECTORS)]
        exchange = exchanges[i % 2]
        # Generate a plausible company name from the ticker
        name = _ticker_to_name(sym, rng)
        tickers.append({
            "ticker": sym,
            "name": name,
            "exchange": exchange,
            "sector": sector,
        })

    return tickers


def _ticker_to_name(ticker: str, rng: random.Random) -> str:
    """Generate a plausible company name for a ticker symbol."""
    suffixes = [
        "Inc", "Corp", "Holdings Inc", "Group Inc", "Technologies Inc",
        "Pharmaceuticals Inc", "Financial Corp", "Energy Corp",
        "Healthcare Inc", "Solutions Corp", "Systems Inc",
    ]
    return f"{ticker.capitalize()} {rng.choice(suffixes)}"


# ---------------------------------------------------------------------------
# Trading calendar
# ---------------------------------------------------------------------------

def trading_days(start: date, end: date) -> list[str]:
    """Return all weekday date strings between start and end (inclusive)."""
    days: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon=0 … Fri=4
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Price generation (GBM with regimes)
# ---------------------------------------------------------------------------

def _regime_for_date(date_str: str, regimes: list[dict]) -> str:
    """
    Find the active regime for a given date string.

    regimes is a list of {"start_date": "YYYY-MM-DD", "type": "bull_calm"} sorted
    ascending. The last entry whose start_date <= date_str wins.
    """
    active = regimes[0]["type"]
    for entry in regimes:
        if entry["start_date"] <= date_str:
            active = entry["type"]
        else:
            break
    return active


def generate_prices(
    tickers: list[str],
    start_date: str,
    end_date: str,
    regimes: list[dict],
    seed: int,
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Generate daily OHLCV price data for all tickers over the full date range.

    Returns: prices[ticker][date_str] = {open, high, low, close, adjusted_close, volume}

    SPY/QQQ/IWM/SOXX use GBM directly.
    Each non-benchmark stock has beta, alpha, idiosyncratic_sigma derived
    from its per-ticker seed so results are deterministic regardless of order.
    """
    rng = random.Random(seed)

    # Sort regimes ascending by start_date for binary-search-style lookup.
    sorted_regimes = sorted(regimes, key=lambda r: r["start_date"])

    # Pre-compute dates once.
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates = trading_days(start, end)

    if not dates:
        return {t: {} for t in tickers}

    # Build per-ticker GBM parameters using stable per-ticker seeds so that
    # adding/removing tickers from the list doesn't affect existing tickers.
    ticker_params: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        if ticker in set(BENCHMARK_TICKERS):
            ticker_params[ticker] = {"beta": 1.0, "alpha": 0.0, "idio_sigma": 0.0}
        else:
            t_seed = _ticker_hash_seed(ticker) ^ seed
            t_rng = random.Random(t_seed)
            ticker_params[ticker] = {
                "beta": t_rng.uniform(0.4, 1.8),
                "alpha": t_rng.gauss(0.0, 0.0002),
                "idio_sigma": t_rng.uniform(0.005, 0.020),
            }

    # Starting prices: stable per-ticker seed so they don't shift when more
    # tickers are added to the list.
    starting_prices: dict[str, float] = {}
    for ticker in tickers:
        t_seed = _ticker_hash_seed(ticker) ^ (seed + 1)
        t_rng = random.Random(t_seed)
        starting_prices[ticker] = t_rng.uniform(15.0, 600.0)

    # Build SPY path first (market return per day).
    spy_prices: list[float] = []
    spy_current = starting_prices.get("SPY", 450.0)
    spy_returns: list[float] = []
    for d_str in dates:
        regime = _regime_for_date(d_str, sorted_regimes)
        params = REGIME_PARAMS[regime]
        ret = params["drift"] + params["sigma"] * rng.gauss(0.0, 1.0)
        spy_current = max(1.0, spy_current * math.exp(ret))
        spy_prices.append(spy_current)
        spy_returns.append(ret)

    # Generate prices for every ticker.
    prices: dict[str, dict[str, dict[str, Any]]] = {}
    spy_price_path = dict(zip(dates, spy_prices))

    for ticker in tickers:
        is_benchmark = ticker in set(BENCHMARK_TICKERS)
        tp = ticker_params[ticker]
        current_price = starting_prices[ticker]

        # Per-ticker RNG for idiosyncratic noise (stable regardless of ticker order).
        t_seed = _ticker_hash_seed(ticker) ^ (seed + 2)
        t_rng = random.Random(t_seed)

        ticker_prices: dict[str, dict[str, Any]] = {}

        for i, d_str in enumerate(dates):
            if is_benchmark and ticker == "SPY":
                # SPY was already computed above — reuse.
                day_close = spy_prices[i]
            elif is_benchmark:
                # Other benchmarks: use their own GBM with SPY correlation.
                regime = _regime_for_date(d_str, sorted_regimes)
                params = REGIME_PARAMS[regime]
                market_ret = spy_returns[i]
                idio = params["sigma"] * 0.5 * t_rng.gauss(0.0, 1.0)
                ret = 0.95 * market_ret + idio
                current_price = max(1.0, current_price * math.exp(ret))
                day_close = current_price
            else:
                # Individual stocks: beta * market_return + alpha + idiosyncratic
                regime = _regime_for_date(d_str, sorted_regimes)
                params = REGIME_PARAMS[regime]
                market_ret = spy_returns[i]
                idio = tp["idio_sigma"] * t_rng.gauss(0.0, 1.0)
                ret = tp["beta"] * market_ret + tp["alpha"] + idio
                current_price = max(0.5, current_price * math.exp(ret))
                day_close = current_price

            # Generate realistic OHLV from the close price.
            intraday_range = day_close * t_rng.uniform(0.005, 0.025)
            day_open = day_close * t_rng.uniform(0.995, 1.005)
            day_high = max(day_open, day_close) + t_rng.uniform(0.0, intraday_range)
            day_low = min(day_open, day_close) - t_rng.uniform(0.0, intraday_range)
            day_low = max(0.01, day_low)
            volume = t_rng.randint(200_000, 80_000_000)

            ticker_prices[d_str] = {
                "open": round(day_open, 4),
                "high": round(day_high, 4),
                "low": round(day_low, 4),
                "close": round(day_close, 4),
                "adjusted_close": round(day_close, 4),
                "volume": volume,
            }

        prices[ticker] = ticker_prices

    return prices


# ---------------------------------------------------------------------------
# Fundamentals generation (per ticker, stable)
# ---------------------------------------------------------------------------

def generate_fundamentals(
    tickers: list[str],
    seed: int,
    sector_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """
    Generate stable fundamental data for each ticker.

    quality_tier and growth_tier are derived from a per-ticker hash so they
    are stable regardless of universe ordering. Tickers differ meaningfully
    in ROE, debt/equity, earnings growth, etc. so rankings are non-trivial.
    """
    fundamentals: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        hash_seed = _ticker_hash_seed(ticker) ^ seed
        quality_tier = (hash_seed % 3) + 1          # 1=high, 2=mid, 3=low
        growth_tier = ((hash_seed // 3) % 3) + 1    # 1=high, 2=mid, 3=low

        t_rng = random.Random(hash_seed)

        roe_min, roe_max = QUALITY_ROE[quality_tier]
        roe = t_rng.uniform(roe_min, roe_max)

        de_min, de_max = QUALITY_DEBT_EQUITY[quality_tier]
        debt_to_equity = t_rng.uniform(de_min, de_max)

        eps_min, eps_max = GROWTH_EPS[growth_tier]
        eps_growth = t_rng.uniform(eps_min, eps_max)

        rev_min, rev_max = GROWTH_REVENUE[growth_tier]
        revenue_growth = t_rng.uniform(rev_min, rev_max)

        # PE ratio: inversely related to quality tier (better companies trade at premium)
        pe_base = {1: (18.0, 45.0), 2: (10.0, 25.0), 3: (5.0, 18.0)}[quality_tier]
        pe_ratio = t_rng.uniform(*pe_base)

        # P/B ratio: correlated with ROE
        pb_ratio = max(0.5, roe * t_rng.uniform(40.0, 80.0))

        # Market cap: broad range, tier-1 quality slightly larger on average
        mc_ranges = {1: (5_000_000_000, 500_000_000_000),
                     2: (1_000_000_000, 100_000_000_000),
                     3: (200_000_000, 20_000_000_000)}
        mc_min, mc_max = mc_ranges[quality_tier]
        market_cap = t_rng.randint(mc_min, mc_max)

        sector = sector_map.get(ticker, "Information Technology")

        # Gross profit (Novy-Marx numerator): scaled off market cap, tier-correlated
        # so higher-quality names show stronger gross profitability.
        gp_frac = {1: (0.20, 0.45), 2: (0.10, 0.25), 3: (0.03, 0.12)}[quality_tier]
        gross_profit = int(market_cap * t_rng.uniform(*gp_frac))

        fundamentals[ticker] = {
            "Symbol": ticker,
            "PERatio": f"{pe_ratio:.4f}",
            "PriceToBookRatio": f"{pb_ratio:.4f}",
            "ReturnOnEquityTTM": f"{roe:.6f}",
            "DebtToEquityRatio": f"{debt_to_equity:.4f}",
            "QuarterlyRevenueGrowthYOY": f"{revenue_growth:.6f}",
            "QuarterlyEarningsGrowthYOY": f"{eps_growth:.6f}",
            "MarketCapitalization": str(market_cap),
            "GrossProfitTTM": str(gross_profit),
            "Sector": sector,
        }

    return fundamentals


def generate_balance_sheet(ticker: str, seed: int) -> dict[str, Any]:
    """Deterministic AV BALANCE_SHEET shape (most-recent-first quarterly reports).

    Only totalAssets is consumed by av-ingestor (the gross-profitability
    denominator); generated independently of the overview draw so GP/assets is
    not a fixed ratio across tickers."""
    t_rng = random.Random((_ticker_hash_seed(ticker) ^ seed) ^ 0x5A5A5A5A)
    total_assets = t_rng.randint(1_000_000_000, 2_000_000_000_000)
    return {
        "symbol": ticker,
        "quarterlyReports": [
            {"fiscalDateEnding": "2024-03-31", "totalAssets": str(total_assets)},
            {"fiscalDateEnding": "2023-12-31", "totalAssets": str(int(total_assets * 0.97))},
        ],
    }


# ---------------------------------------------------------------------------
# News generation (deterministic per ticker+date)
# ---------------------------------------------------------------------------

def generate_news(
    ticker: str,
    as_of_date: str,
    current_regime: str,
    limit: int = 50,
    max_articles: int = 3,
) -> list[dict[str, Any]]:
    """
    Generate 1–3 news articles for a ticker, deterministic from ticker+date.

    ~10% of tickers receive bearish articles when the regime is bear_stress.
    """
    date_seed = int(hashlib.sha256(f"{ticker}:{as_of_date}".encode()).hexdigest()[:8], 16)
    rng = random.Random(date_seed)

    count = min(rng.randint(1, 3), max_articles, limit)
    articles: list[dict[str, Any]] = []

    # Determine if this ticker gets bearish news in bear_stress
    ticker_seed = _ticker_hash_seed(ticker)
    is_bearish_candidate = (ticker_seed % 10) == 0  # ~10% of tickers

    for article_idx in range(count):
        a_rng = random.Random(date_seed + article_idx + 1)

        # Choose sentiment
        if current_regime == "bear_stress" and is_bearish_candidate:
            title_template = a_rng.choice(_BEARISH_TITLES)
            sentiment_label = "Bearish"
            sentiment_score = round(a_rng.uniform(-0.35, -0.10), 3)
        elif current_regime in ("bull_calm", "bull_stress") and article_idx == 0:
            title_template = a_rng.choice(_BULLISH_TITLES)
            sentiment_label = "Positive" if a_rng.random() > 0.3 else "Neutral"
            sentiment_score = round(a_rng.uniform(0.05, 0.40), 3)
        else:
            title_template = a_rng.choice(_NEUTRAL_TITLES)
            sentiment_label = "Neutral"
            sentiment_score = round(a_rng.uniform(-0.05, 0.10), 3)

        title = title_template.format(ticker=ticker)
        relevance = round(a_rng.uniform(0.3, 1.0), 3)
        source = a_rng.choice(_SOURCES)

        # Published within the last 7 days before as_of_date
        days_ago = a_rng.randint(0, 6)
        pub_date = date.fromisoformat(as_of_date) - timedelta(days=days_ago)
        hour = a_rng.randint(7, 20)
        minute = a_rng.randint(0, 59)
        time_published = f"{pub_date.strftime('%Y%m%d')}T{hour:02d}{minute:02d}00"

        summary = (
            f"{ticker} — {title.split(' ', 3)[-1] if len(title.split()) > 3 else title}. "
            f"Analysts are watching closely as the company reports its latest results. "
            f"Market reaction has been {sentiment_label.lower()} with volume elevated."
        )

        articles.append({
            "title": title,
            "time_published": time_published,
            "summary": summary,
            "source": source,
            "ticker_sentiment": [
                {
                    "ticker": ticker,
                    "relevance_score": str(relevance),
                    "ticker_sentiment_score": str(sentiment_score),
                    "ticker_sentiment_label": sentiment_label,
                }
            ],
        })

    return articles


# ---------------------------------------------------------------------------
# Earnings calendar generation
# ---------------------------------------------------------------------------

def generate_earnings_calendar(
    tickers: list[str],
    names: dict[str, str],
    seed: int,
) -> list[dict[str, str]]:
    """
    Assign a stable quarterly earnings date to each ticker.

    Returns a list of CSV-ready dicts covering the next 12 months from an
    arbitrary reference date. The caller filters by as_of_date and horizon.
    """
    entries: list[dict[str, str]] = []

    # Reference date: 2024-01-01, so we generate quarters for all of 2024/2025
    quarters = [
        date(2024, 1, 22), date(2024, 4, 22), date(2024, 7, 22), date(2024, 10, 22),
        date(2025, 1, 22), date(2025, 4, 22), date(2025, 7, 22), date(2025, 10, 22),
        date(2026, 1, 22), date(2026, 4, 22),
    ]

    for ticker in tickers:
        t_seed = _ticker_hash_seed(ticker) ^ seed
        t_rng = random.Random(t_seed)

        # Offset from the standard quarterly date (deterministic per ticker)
        day_offset = t_rng.randint(-10, 10)
        estimate = round(t_rng.uniform(0.50, 5.00), 2)
        name = names.get(ticker, f"{ticker} Corp")

        for q_date in quarters:
            report_date = q_date + timedelta(days=day_offset)
            # Fiscal date ending is one month before report date
            fiscal_end = date(
                report_date.year,
                report_date.month - 1 if report_date.month > 1 else 12,
                30 if report_date.month != 3 else 31,
            )
            entries.append({
                "symbol": ticker,
                "name": name,
                "reportDate": report_date.isoformat(),
                "fiscalDateEnding": fiscal_end.isoformat(),
                "estimate": str(estimate),
                "currency": "USD",
            })

    return entries
