import asyncio
import hashlib
import os
import random
import time
from collections import deque
from datetime import date, timedelta

import httpx

AV_BASE_URL = os.getenv("AV_BASE_URL", "https://www.alphavantage.co/query")


class AVError(Exception):
    """Alpha Vantage failure. `retryable` distinguishes transient faults (network /
    timeout / 5xx / in-band rate-limit) from permanent ones (bad symbol, invalid key,
    no data) so the client can back off and retry only the former (audit P1)."""
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


# AV signals rate-limit IN-BAND (HTTP 200 + a JSON "Note"/"Information" body), not via
# HTTP status. "Note" is always a throttle; "Information" is a throttle ONLY when the
# message looks rate-limit-ish — otherwise it's a permanent key/plan problem.
_RATE_LIMIT_HINTS = (
    "rate limit", "calls per", "requests per", "per minute", "per day",
    "premium", "higher api call", "thank you for using",
)


def _is_rate_limit_msg(msg: str) -> bool:
    m = (msg or "").lower()
    return any(h in m for h in _RATE_LIMIT_HINTS)


class AVClient:
    def __init__(self, api_key: str, rate_limit_rpm: int = 75, mock_mode: bool = False):
        self.api_key = api_key
        self.rate_limit_rpm = rate_limit_rpm
        self.mock_mode = mock_mode
        self._sleep_interval = 60.0 / rate_limit_rpm
        self._last_call_time: float = 0.0
        self._call_times: deque[float] = deque()  # monotonic stamps in the trailing 60s
        self._client = httpx.AsyncClient(timeout=30.0)
        # Retry/backoff (audit P1). Exponential base*2^n + jitter, capped.
        self._max_retries = int(os.getenv("AV_MAX_RETRIES", "3"))
        self._backoff_base = float(os.getenv("AV_BACKOFF_BASE_SECS", "2.0"))
        self._backoff_max = float(os.getenv("AV_BACKOFF_MAX_SECS", "30.0"))

    async def close(self):
        await self._client.aclose()

    async def _throttle(self):
        """Sliding-window rate limit (audit P2) + a minimum inter-call gap.

        The old fixed-gap-only limiter reset to "ready" after any idle pause, so a run
        that periodically stalled (DB upsert, checkpoint, a second AV call) could burst
        past the per-minute budget on resume. This enforces BOTH a hard cap of
        rate_limit_rpm calls per trailing 60s AND the ~0.8s smoothing gap, so neither a
        post-idle burst nor an instant rate_limit_rpm-call spike can occur."""
        window = 60.0
        now = time.monotonic()
        # Sliding-window cap: drop calls older than the window; if we're at the cap,
        # wait until the oldest call ages out.
        while self._call_times and now - self._call_times[0] >= window:
            self._call_times.popleft()
        if len(self._call_times) >= self.rate_limit_rpm:
            await asyncio.sleep(window - (now - self._call_times[0]) + 0.001)
            now = time.monotonic()
            while self._call_times and now - self._call_times[0] >= window:
                self._call_times.popleft()
        # Minimum inter-call gap (smooths bursts within the window).
        if self._last_call_time:
            gap = self._sleep_interval - (now - self._last_call_time)
            if gap > 0:
                await asyncio.sleep(gap)
                now = time.monotonic()
        self._last_call_time = now
        self._call_times.append(now)

    def _classify(self, data: dict):
        """Inspect a parsed AV body. Return the data dict on success, or raise AVError
        (retryable for in-band rate-limit, non-retryable for key/plan/error)."""
        note = data.get("Note")
        info = data.get("Information")
        if note:
            raise AVError(f"AV rate limit (Note): {note}", retryable=True)
        if info and _is_rate_limit_msg(info):
            raise AVError(f"AV rate limit (Information): {info}", retryable=True)
        if info:
            raise AVError(f"AV API key/plan issue: {info}", retryable=False)
        if data.get("Error Message"):
            raise AVError(f"AV error: {data['Error Message']}", retryable=False)
        return data

    async def _get(self, params: dict) -> dict:
        params["apikey"] = self.api_key
        last_exc: AVError | None = None
        for attempt in range(self._max_retries + 1):
            await self._throttle()  # respects the rate limit between retries too
            try:
                response = await self._client.get(AV_BASE_URL, params=params)
                response.raise_for_status()
                return self._classify(response.json())
            except AVError as e:
                if not e.retryable:
                    raise            # bad symbol / key / plan — retrying won't help
                last_exc = e
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code < 500:
                    raise AVError(f"AV HTTP {code}: {e}", retryable=False)
                last_exc = AVError(f"AV HTTP {code}", retryable=True)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = AVError(f"AV transport error: {e}", retryable=True)
            if attempt >= self._max_retries:
                break
            backoff = min(self._backoff_base * (2 ** attempt), self._backoff_max)
            await asyncio.sleep(backoff + random.uniform(0.0, 0.5))
        raise last_exc if last_exc else AVError("AV request failed", retryable=True)

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
            "gross_profit": _to_float(data.get("GrossProfitTTM")),  # Novy-Marx gross-profitability numerator
            "sector": data.get("Sector") or None,
            # Forward-looking analyst fields — ride in the SAME OVERVIEW payload (no
            # extra API call). Nested so the dict can be spread into the fundamentals
            # upsert untouched; the caller snapshots `analyst` separately (point-in-time
            # store for the revision factor). See _upsert_analyst_snapshot / migration 0029.
            "analyst": {
                "target_price": _to_float(data.get("AnalystTargetPrice")),
                "rating_strong_buy": _to_int(data.get("AnalystRatingStrongBuy")),
                "rating_buy": _to_int(data.get("AnalystRatingBuy")),
                "rating_hold": _to_int(data.get("AnalystRatingHold")),
                "rating_sell": _to_int(data.get("AnalystRatingSell")),
                "rating_strong_sell": _to_int(data.get("AnalystRatingStrongSell")),
                "forward_pe": _to_float(data.get("ForwardPE")),
                "peg_ratio": _to_float(data.get("PEGRatio")),
            },
        }

    async def get_earnings(self, ticker: str) -> list[dict] | None:
        """Quarterly earnings surprises from AV EARNINGS — the PEAD signal inputs.

        Returns a list of {fiscal_date_ending, reported_date, reported_eps,
        estimated_eps, surprise, surprise_percentage}, newest-first, or None if the
        symbol has no data. estimated_eps is the consensus AS OF the report (AV's
        `estimatedEPS`) — point-in-time, so the factor's reported_date<=score_date
        filter is a true no-look-ahead cut."""
        if self.mock_mode:
            return _mock_earnings(ticker)

        data = await self._get({"function": "EARNINGS", "symbol": ticker})
        if not data or not isinstance(data.get("quarterlyEarnings"), list):
            return None

        out: list[dict] = []
        for q in data["quarterlyEarnings"]:
            if not isinstance(q, dict):
                continue
            fde = q.get("fiscalDateEnding")
            if not fde:
                continue
            out.append({
                "fiscal_date_ending": fde,
                "reported_date": q.get("reportedDate") or None,
                "reported_eps": _to_float(q.get("reportedEPS")),
                "estimated_eps": _to_float(q.get("estimatedEPS")),
                "surprise": _to_float(q.get("surprise")),
                "surprise_percentage": _to_float(q.get("surprisePercentage")),
            })
        return out

    async def get_balance_sheet(self, ticker: str) -> dict | None:
        """Balance-sheet fields: total assets (gross-profitability denominator) and
        common shares outstanding now vs ~1 fiscal year ago (net-issuance factor).

        AV BALANCE_SHEET returns annual + quarterly reports newest-first. We take
        the freshest report's `totalAssets`, and shares from the ANNUAL reports
        (annualReports[0] vs [1]) — annual is the right cadence for a YoY issuance
        signal and avoids quarterly seasonality. Returns None only when there is no
        usable total_assets (keeps the existing contract); shares fields are
        best-effort and may be None (the issuance factor is optional, so NULL just
        means no issuance tilt for that ticker).
        """
        if self.mock_mode:
            return _mock_balance_sheet(ticker)

        data = await self._get({"function": "BALANCE_SHEET", "symbol": ticker})
        reports = data.get("quarterlyReports") or data.get("annualReports") or []
        if not reports:
            return None
        total_assets = _to_float(reports[0].get("totalAssets"))
        if total_assets is None:
            return None
        annual = data.get("annualReports") or []
        shares = _to_float(annual[0].get("commonStockSharesOutstanding")) if len(annual) >= 1 else None
        shares_prior = _to_float(annual[1].get("commonStockSharesOutstanding")) if len(annual) >= 2 else None
        return {
            "total_assets": total_assets,
            "shares_outstanding": shares,
            "shares_outstanding_prior": shares_prior,
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


_MOCK_SECTORS = [
    "Information Technology", "Health Care", "Financials",
    "Consumer Discretionary", "Communication Services", "Industrials",
    "Consumer Staples", "Energy", "Utilities", "Real Estate", "Materials",
]

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
        "gross_profit": round(rng.uniform(1e8, 5e10), 2),
        "sector": rng.choice(_MOCK_SECTORS),
        # Mock analyst block so mock-mode fetches + tests exercise the snapshot path.
        "analyst": {
            "target_price": round(rng.uniform(10.0, 500.0), 2),
            "rating_strong_buy": rng.randint(0, 10),
            "rating_buy": rng.randint(0, 15),
            "rating_hold": rng.randint(0, 15),
            "rating_sell": rng.randint(0, 8),
            "rating_strong_sell": rng.randint(0, 5),
            "forward_pe": round(rng.uniform(8.0, 45.0), 4),
            "peg_ratio": round(rng.uniform(0.5, 4.0), 4),
        },
    }


def _mock_balance_sheet(ticker: str) -> dict:
    # Seed offset keeps total_assets independent of the overview draw so
    # gross_profit/total_assets isn't a fixed ratio across mock tickers.
    rng = random.Random(_stable_seed(ticker) ^ 0x5A5A5A5A)
    shares = round(rng.uniform(5e7, 5e9), 2)
    # Net issuance in [-5%, +8%]: a spread of buybacks vs dilution across mocks.
    shares_prior = round(shares / (1.0 + rng.uniform(-0.05, 0.08)), 2)
    return {
        "total_assets": round(rng.uniform(5e8, 5e11), 2),
        "shares_outstanding": shares,
        "shares_outstanding_prior": shares_prior,
    }


def _mock_earnings(ticker: str) -> list[dict]:
    """8 quarters of mock earnings, newest-first, with a per-ticker stable surprise
    sign/size so mock runs produce a spread of beats/misses for the factor."""
    import datetime as _dt
    rng = random.Random(_stable_seed(ticker) ^ 0x3C3C3C3C)
    base_est = round(rng.uniform(0.20, 3.00), 2)
    bias = rng.uniform(-0.15, 0.15)  # per-ticker chronic beat/miss tendency
    today = _dt.date(2026, 6, 1)
    out: list[dict] = []
    for i in range(8):
        rep_date = today - _dt.timedelta(days=90 * i + 5)
        fde = today - _dt.timedelta(days=90 * i + 35)
        est = round(base_est * (1.0 + rng.uniform(-0.05, 0.05)), 4)
        surprise = round(est * (bias + rng.uniform(-0.10, 0.10)), 4)
        rep = round(est + surprise, 4)
        out.append({
            "fiscal_date_ending": fde.isoformat(),
            "reported_date": rep_date.isoformat(),
            "reported_eps": rep,
            "estimated_eps": est,
            "surprise": surprise,
            "surprise_percentage": round(100.0 * surprise / abs(est), 4) if est else None,
        })
    return out
