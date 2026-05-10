import asyncio
import hashlib
import os
import random
import time
from datetime import date, timedelta

import httpx

AV_BASE_URL = "https://www.alphavantage.co/query"


class AVError(Exception):
    pass


class AVClient:
    def __init__(self, api_key: str, rate_limit_rpm: int = 75, mock_mode: bool = False):
        self.api_key = api_key
        self.rate_limit_rpm = rate_limit_rpm
        self.mock_mode = mock_mode
        self._sleep_interval = 60.0 / rate_limit_rpm
        self._last_call_time: float = 0.0
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._client.aclose()

    async def _throttle(self):
        now = time.monotonic()
        elapsed = now - self._last_call_time
        wait = self._sleep_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call_time = time.monotonic()

    async def _get(self, params: dict) -> dict:
        await self._throttle()
        params["apikey"] = self.api_key
        response = await self._client.get(AV_BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "Note" in data:
            raise AVError(f"Alpha Vantage rate limit hit: {data['Note']}")
        if "Information" in data:
            raise AVError(f"Alpha Vantage API key issue: {data['Information']}")
        if "Error Message" in data:
            raise AVError(f"Alpha Vantage error: {data['Error Message']}")
        return data

    async def get_daily_prices(self, ticker: str, compact: bool = False) -> list[dict]:
        if self.mock_mode:
            return _mock_prices(ticker, days=400)

        outputsize = "compact" if compact else "full"
        data = await self._get(
            {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": ticker,
                "outputsize": outputsize,
            }
        )

        series = data.get("Time Series (Daily)", {})
        if not series:
            raise AVError(f"No price data returned for {ticker}")

        rows = []
        for date_str, values in series.items():
            rows.append(
                {
                    "date": date_str,
                    "open": _to_float(values.get("1. open")),
                    "high": _to_float(values.get("2. high")),
                    "low": _to_float(values.get("3. low")),
                    "close": _to_float(values.get("4. close")),
                    "adjusted_close": _to_float(values.get("5. adjusted close")),
                    "volume": _to_int(values.get("6. volume")),
                }
            )

        rows.sort(key=lambda r: r["date"])
        return rows

    async def get_overview(self, ticker: str) -> dict | None:
        if self.mock_mode:
            return _mock_overview(ticker)

        data = await self._get({"function": "OVERVIEW", "symbol": ticker})

        if not data or data.get("Symbol") is None:
            return None

        return {
            "pe_ratio": _to_float(data.get("PERatio")),
            "pb_ratio": _to_float(data.get("PriceToBookRatio")),
            "roe": _to_float(data.get("ReturnOnEquityTTM")),
            "debt_to_equity": _to_float(data.get("DebtToEquityRatio")),
            "revenue_growth": _to_float(data.get("QuarterlyRevenueGrowthYOY")),
            "eps_growth": _to_float(data.get("QuarterlyEarningsGrowthYOY")),
            "market_cap": _to_int(data.get("MarketCapitalization")),
            "avg_volume": None,  # AV OVERVIEW has no reliable avg_volume field; calculated from daily_prices locally
        }


def _to_float(val) -> float | None:
    try:
        f = float(val)
        return None if f != f else f  # filter NaN
    except (TypeError, ValueError):
        return None


def _to_int(val) -> int | None:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _stable_seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


def _mock_prices(ticker: str, days: int = 400) -> list[dict]:
    rng = random.Random(_stable_seed(ticker))
    price = rng.uniform(50.0, 500.0)
    today = date.today()
    rows = []
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        change = rng.gauss(0.0003, 0.015)
        price = max(1.0, price * (1 + change))
        open_ = price * rng.uniform(0.99, 1.01)
        high = price * rng.uniform(1.0, 1.02)
        low = price * rng.uniform(0.98, 1.0)
        rows.append(
            {
                "date": d.isoformat(),
                "open": round(open_, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(price, 4),
                "adjusted_close": round(price, 4),
                "volume": rng.randint(500_000, 50_000_000),
            }
        )
    return rows


def _mock_overview(ticker: str) -> dict:
    rng = random.Random(_stable_seed(ticker))
    return {
        "pe_ratio": round(rng.uniform(10.0, 50.0), 4),
        "pb_ratio": round(rng.uniform(1.0, 10.0), 4),
        "roe": round(rng.uniform(0.05, 0.40), 6),
        "debt_to_equity": round(rng.uniform(0.1, 2.5), 4),
        "revenue_growth": round(rng.uniform(-0.05, 0.30), 6),
        "eps_growth": round(rng.uniform(-0.10, 0.40), 6),
        "market_cap": rng.randint(1_000_000_000, 3_000_000_000_000),
        "avg_volume": rng.randint(1_000_000, 50_000_000),
    }
