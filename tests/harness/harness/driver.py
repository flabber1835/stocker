"""
SimulationDriver — drives the Docker Compose stack through a multi-day
simulation.  All HTTP calls use aiohttp; DB resets use asyncpg.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date
from typing import Any, Dict, List, Optional

import aiohttp
import asyncpg

from .scenario import DayObservation, Scenario, list_trading_days

log = logging.getLogger("harness.driver")

# ---------------------------------------------------------------------------
# Default service URL map (override by passing service_urls to SimulationDriver)
# ---------------------------------------------------------------------------
DEFAULT_SERVICE_URLS: Dict[str, str] = {
    "av_ingestor":       "http://localhost:8001",
    "pipeline":          "http://localhost:8018",
    "llm_vetter":        "http://localhost:8016",
    "portfolio_builder": "http://localhost:8008",
    "alpaca_sim":        "http://localhost:8020",
    "alpaca_sync":       "http://localhost:8009",
    "trade_executor":    "http://localhost:8012",
    "risk_service":      "http://localhost:8011",
    "av_sim":            "http://localhost:8021",
    "anthropic_sim":     "http://localhost:8022",
    "tavily_sim":        "http://localhost:8023",
    "api":               "http://localhost:8000",
}

# Default Postgres DSN for resets
DEFAULT_DSN = "postgresql://stocker:stocker@localhost:5433/stocker"

# ---------------------------------------------------------------------------
# Tables to truncate on DB reset (order respects FK constraints)
# ---------------------------------------------------------------------------
_TRUNCATE_TABLES = (
    "alpaca_orders",
    "execution_steps",
    "execution_traces",
    "delta_intents",
    "vetter_exclusions",
    "vetter_decisions",
    "vetter_runs",
    "portfolio_holdings",
    "portfolio_runs",
    "rankings",
    "ranking_runs",
    "factor_scores",
    "factor_runs",
    "regime_snapshots",
    "fundamentals",
    "daily_prices",
    "universe_tickers",
    "universe_snapshots",
    "ingest_runs",
    "live_positions",
    "alpaca_sync_runs",
    "risk_decisions",
    "pipeline_runs",
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def reset_database(dsn: str = DEFAULT_DSN) -> None:
    """TRUNCATE all harness-owned tables in the correct FK order."""
    log.info("Resetting database …")
    conn = await asyncpg.connect(dsn)
    try:
        tables_sql = ", ".join(_TRUNCATE_TABLES)
        await conn.execute(f"TRUNCATE TABLE {tables_sql} CASCADE")
        log.info("Database reset complete.")
    finally:
        await conn.close()


async def _get_pending_intents_from_db(
    dsn: str,
    run_id: str,
) -> List[Dict[str, Any]]:
    """Fetch tradeable pending delta_intents for a given delta run_id from Postgres.

    Only returns entry/exit/buy_add/sell_trim actions — hold, at_risk, and watch
    are informational and are not submitted to the trade-executor.
    """
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id::text, ticker, action, actual_weight "
            "FROM delta_intents "
            "WHERE run_id = $1 AND rejected_at IS NULL "
            "  AND action IN ('entry', 'exit', 'buy_add', 'sell_trim')",
            run_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# HTTP polling helper
# ---------------------------------------------------------------------------

async def poll_until_done(
    session: aiohttp.ClientSession,
    url: str,
    max_wait: float = 120.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Poll GET *url* every *interval* seconds until status is not 'running'.

    Returns the final response dict.  Raises TimeoutError if max_wait exceeded.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as r:
                if r.status == 404:
                    await asyncio.sleep(interval)
                    continue
                data = await r.json(content_type=None)
                status = data.get("status", "")
                if status not in ("running", "started", ""):
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("poll_until_done %s: %s", url, exc)
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out after {max_wait}s waiting for {url}")


async def poll_until_new_run(
    session: aiohttp.ClientSession,
    url: str,
    prev_run_id: str = "",
    max_wait: float = 120.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Poll GET *url* until a run with a *different* run_id from prev_run_id
    appears and has a non-running status.

    This avoids the race condition where /runs/latest still returns the
    previous run's 'success' status before the newly-triggered run has been
    created in the database.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as r:
                if r.status == 404:
                    await asyncio.sleep(interval)
                    continue
                data = await r.json(content_type=None)
                run_id = data.get("run_id", "")
                status = data.get("status", "")
                if run_id != prev_run_id and status not in ("running", "started", ""):
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("poll_until_new_run %s: %s", url, exc)
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out after {max_wait}s waiting for new run at {url}")


async def _post(
    session: aiohttp.ClientSession,
    url: str,
    payload: Optional[Dict] = None,
) -> Dict[str, Any]:
    """POST to *url* with optional JSON *payload*.  Returns parsed JSON dict."""
    try:
        async with session.post(url, json=payload or {}) as r:
            return await r.json(content_type=None)
    except Exception as exc:
        log.error("POST %s failed: %s", url, exc)
        return {"error": str(exc)}


async def _get(
    session: aiohttp.ClientSession,
    url: str,
) -> Dict[str, Any]:
    """GET *url*.  Returns parsed JSON dict."""
    try:
        async with session.get(url) as r:
            return await r.json(content_type=None)
    except Exception as exc:
        log.error("GET %s failed: %s", url, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Scenario loader
# ---------------------------------------------------------------------------

async def load_scenario_to_av_sim(
    scenario: Scenario,
    av_sim_url: str,
    session: aiohttp.ClientSession,
) -> Dict[str, Any]:
    """POST scenario metadata to the av-sim /admin/load-scenario endpoint."""
    payload: Dict[str, Any] = {
        "name":             scenario.name,
        "seed":             scenario.seed,
        "universe_size":    scenario.universe_size,
        "start_date":       scenario.start_date.isoformat(),
        "end_date":         scenario.end_date.isoformat(),
        "pre_history_days": 300,  # enough for pipeline's 200-day SMA on day 0
        "regimes": [
            {"start_date": rc.start_date.isoformat(), "type": rc.regime_type}
            for rc in scenario.regimes
        ],
    }
    if scenario.extra_tickers:
        payload["extra_tickers"] = scenario.extra_tickers
    url = f"{av_sim_url}/admin/load-scenario"
    log.info(
        "Loading scenario '%s' into av-sim (extra_tickers=%d) …",
        scenario.name,
        len(scenario.extra_tickers) if scenario.extra_tickers else 0,
    )
    result = await _post(session, url, payload)
    if "error" in result:
        log.error("load-scenario failed: %s", result["error"])
    else:
        log.info(
            "Scenario loaded: %d tickers, %d price rows",
            result.get("tickers", "?"),
            result.get("price_rows", "?"),
        )
    return result


# ---------------------------------------------------------------------------
# Main simulation driver
# ---------------------------------------------------------------------------

class SimulationDriver:
    """
    Drives the Docker Compose stack through a multi-day simulation.

    Usage::

        driver = SimulationDriver(dsn=DEFAULT_DSN, service_urls=DEFAULT_SERVICE_URLS)
        observations = await driver.run(scenario)
    """

    def __init__(
        self,
        dsn: str = DEFAULT_DSN,
        service_urls: Optional[Dict[str, str]] = None,
    ) -> None:
        self.dsn = dsn
        self.urls = {**DEFAULT_SERVICE_URLS, **(service_urls or {})}

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    async def run(self, scenario: Scenario) -> List[DayObservation]:
        """Execute the full simulation and return one DayObservation per day."""
        observations: List[DayObservation] = []
        trading_days = list_trading_days(scenario.start_date, scenario.end_date)

        log.info(
            "Starting simulation '%s': %d trading days (%s → %s)",
            scenario.name,
            len(trading_days),
            scenario.start_date,
            scenario.end_date,
        )

        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # ── Pre-simulation setup ──────────────────────────────────
            await reset_database(self.dsn)
            await self._reset_alpaca_sim(session, scenario)
            await load_scenario_to_av_sim(scenario, self.urls["av_sim"], session)

            # ── Day-by-day loop ──────────────────────────────────────
            for day_index, trading_day in enumerate(trading_days):
                obs = await self._run_day(
                    session=session,
                    scenario=scenario,
                    trading_day=trading_day,
                    day_index=day_index,
                )
                observations.append(obs)
                log.info(
                    "Day %d/%d %s: %d positions, $%.0f, regime=%s [%s]",
                    day_index + 1,
                    len(trading_days),
                    trading_day,
                    obs.position_count,
                    obs.account_value,
                    obs.regime,
                    obs.label or "ok",
                )

        log.info("Simulation '%s' complete.", scenario.name)
        return observations

    # ------------------------------------------------------------------
    # Single-day execution
    # ------------------------------------------------------------------

    async def _run_day(
        self,
        session: aiohttp.ClientSession,
        scenario: Scenario,
        trading_day: date,
        day_index: int,
    ) -> DayObservation:
        errors: List[str] = []
        pipeline_status = ""
        intents_submitted = 0
        intents_accepted = 0

        av_sim    = self.urls["av_sim"]
        av_ing    = self.urls["av_ingestor"]
        pipeline  = self.urls["pipeline"]
        vetter    = self.urls["llm_vetter"]
        pb        = self.urls["portfolio_builder"]
        a_sync    = self.urls["alpaca_sync"]
        executor  = self.urls["trade_executor"]
        api_svc   = self.urls["api"]

        # ── Step 1: set as-of date ───────────────────────────────────
        log.debug("Step 1: set as-of-date to %s", trading_day)
        r = await _post(
            session,
            f"{av_sim}/admin/set-as-of-date",
            {"as_of_date": trading_day.isoformat()},
        )
        if "error" in r:
            errors.append(f"set-as-of-date: {r['error']}")

        # ── Step 2a (day 0 only): fetch universe ─────────────────────
        if day_index == 0:
            log.info("Day 0: fetching universe …")
            start_r = await _post(session, f"{av_ing}/jobs/fetch-universe")
            if "error" not in start_r:
                try:
                    await poll_until_done(
                        session, f"{av_ing}/runs/latest",
                        max_wait=120, interval=0.5,
                    )
                    log.info("Universe fetch complete.")
                except TimeoutError as exc:
                    errors.append(str(exc))
            else:
                errors.append(f"fetch-universe start: {start_r.get('error')}")

        # ── Step 2: fetch data ───────────────────────────────────────
        log.debug("Step 2: fetch-data")
        # Capture the current run_id so we can detect when a NEW fetch-data
        # run completes (avoids the race where poll_until_done returns the
        # previous universe-fetch run's "success" before fetch-data starts).
        try:
            _prev = await _get(session, f"{av_ing}/runs/latest")
            _prev_run_id = _prev.get("run_id", "")
        except Exception:
            _prev_run_id = ""
        start_r = await _post(session, f"{av_ing}/jobs/fetch-data")
        if "error" not in start_r:
            try:
                await poll_until_new_run(
                    session, f"{av_ing}/runs/latest",
                    prev_run_id=_prev_run_id,
                    max_wait=120, interval=0.5,
                )
            except TimeoutError as exc:
                errors.append(str(exc))
        else:
            errors.append(f"fetch-data start: {start_r.get('error')}")

        # ── Step 2c (day 0 only): seed initial positions ─────────────
        # Prices are now in daily_prices so alpaca-sim can look them up.
        if day_index == 0 and scenario.initial_positions:
            await self._seed_initial_positions(session, scenario, trading_day)
            # Sync so live_positions reflects the seeded holdings.
            # Poll until the new sync run completes so the delta step on day 0
            # finds live_positions populated (not just a 2-second guess).
            try:
                _prev_sync = await _get(session, f"{a_sync}/runs/latest")
                _prev_sync_id = _prev_sync.get("run_id", "")
            except Exception:
                _prev_sync_id = ""
            await _post(session, f"{a_sync}/jobs/sync")
            try:
                await poll_until_new_run(
                    session, f"{a_sync}/runs/latest",
                    prev_run_id=_prev_sync_id, max_wait=30, interval=0.5,
                )
                log.info("Initial positions synced to live_positions.")
            except TimeoutError as exc:
                log.warning("alpaca-sync timed out on day-0 seed: %s", exc)
                errors.append(str(exc))

        # ── Step 3: pipeline (factors + rank) ───────────────────────
        # Capture prev_run_id BEFORE the POST so poll_until_new_run can detect
        # when the NEW run completes, not the previous day's still-cached success.
        log.debug("Step 3: pipeline run")
        try:
            _prev_pipe = await _get(session, f"{pipeline}/runs/latest")
            _prev_pipe_id = _prev_pipe.get("run_id", "") or ""
        except Exception:
            _prev_pipe_id = ""
        start_r = await _post(session, f"{pipeline}/jobs/run")
        if start_r.get("status") in ("already_running",) or "error" not in start_r:
            try:
                final = await poll_until_new_run(
                    session, f"{pipeline}/runs/latest",
                    prev_run_id=_prev_pipe_id, max_wait=120, interval=0.5,
                )
                pipeline_status = final.get("status", "")
            except TimeoutError as exc:
                errors.append(str(exc))
                pipeline_status = "timeout"
        else:
            errors.append(f"pipeline start: {start_r.get('error')}")
            pipeline_status = "error"

        # ── Step 4 (optional): vetter ────────────────────────────────
        run_vetter_today = (
            scenario.run_vetter
            and (day_index % scenario.vetter_every_n_days == 0)
        )
        if run_vetter_today:
            log.debug("Step 4: vetter")
            start_r = await _post(session, f"{vetter}/jobs/vet")
            if start_r.get("status") not in ("already_running", "error") and "error" not in start_r:
                try:
                    await poll_until_done(
                        session, f"{vetter}/runs/latest",
                        max_wait=300, interval=1.0,
                    )
                except TimeoutError as exc:
                    errors.append(str(exc))

        # ── Step 5: portfolio builder ────────────────────────────────
        log.debug("Step 5: portfolio-builder")
        try:
            _prev_pb = await _get(session, f"{pb}/runs/latest")
            _prev_pb_id = _prev_pb.get("run_id", "") or ""
        except Exception:
            _prev_pb_id = ""
        start_r = await _post(session, f"{pb}/jobs/build")
        if "error" in start_r:
            errors.append(f"portfolio-builder start: {start_r.get('error')}")
        else:
            try:
                await poll_until_new_run(
                    session, f"{pb}/runs/latest",
                    prev_run_id=_prev_pb_id, max_wait=60, interval=0.5,
                )
            except TimeoutError as exc:
                errors.append(str(exc))

        # ── Step 6: pipeline delta ───────────────────────────────────
        # Critical: must wait for the NEW delta run (not the prior day's still-
        # cached success) before reading intents — otherwise step 7 reads
        # delta_{N-1}'s intent IDs and step 8 hits 404 once delta_N's purge
        # deletes them.
        log.debug("Step 6: pipeline delta")
        delta_run_id: Optional[str] = None
        try:
            _prev_dl = await _get(session, f"{pipeline}/runs/delta-latest")
            _prev_dl_id = _prev_dl.get("run_id", "") or ""
        except Exception:
            _prev_dl_id = ""
        start_r = await _post(session, f"{pipeline}/jobs/delta")
        if "error" in start_r:
            errors.append(f"delta start: {start_r.get('error')}")
        else:
            try:
                final = await poll_until_new_run(
                    session, f"{pipeline}/runs/delta-latest",
                    prev_run_id=_prev_dl_id, max_wait=60, interval=0.5,
                )
                delta_run_id = final.get("run_id")
            except TimeoutError as exc:
                errors.append(str(exc))

        # ── Step 7: get pending intents ──────────────────────────────
        _TRADEABLE = {"entry", "exit", "buy_add", "sell_trim"}
        pending_intents: List[Dict[str, Any]] = []
        if delta_run_id:
            # Prefer the API endpoint; fall back to direct DB.
            # Only submit tradeable actions — hold/at_risk/watch are informational.
            api_delta = await _get(session, f"{api_svc}/delta/latest")
            if "error" not in api_delta and api_delta.get("intents"):
                pending_intents = [
                    i for i in api_delta["intents"]
                    if i.get("order_status") is None
                    and i.get("rejected_at") is None
                    and i.get("action") in _TRADEABLE
                ]
            else:
                # Fallback: query DB directly
                try:
                    pending_intents = await _get_pending_intents_from_db(
                        self.dsn, delta_run_id
                    )
                except Exception as exc:
                    log.warning("DB fallback for intents failed: %s", exc)
                    errors.append(f"get-intents-db: {exc}")

        # ── Step 8: submit intents ───────────────────────────────────
        for intent in pending_intents:
            intent_id = intent.get("id") or intent.get("intent_id")
            if not intent_id:
                continue
            intents_submitted += 1
            log.debug("Submitting intent %s", intent_id)
            submit_r = await _post(
                session,
                f"{executor}/jobs/submit",
                {"intent_id": intent_id, "mode": "immediate"},
            )
            outcome = submit_r.get("status", "")
            if outcome in ("submitted", "filled", "approved", "risk_approved"):
                intents_accepted += 1
            elif "error" in submit_r:
                log.warning("submit intent %s: %s", intent_id, submit_r.get("error"))

        # ── Step 9: alpaca sync ──────────────────────────────────────
        log.debug("Step 9: alpaca-sync")
        try:
            _prev_sync9 = await _get(session, f"{a_sync}/runs/latest")
            _prev_sync9_id = _prev_sync9.get("run_id", "")
        except Exception:
            _prev_sync9_id = ""
        await _post(session, f"{a_sync}/jobs/sync")
        try:
            await poll_until_new_run(
                session, f"{a_sync}/runs/latest",
                prev_run_id=_prev_sync9_id, max_wait=30, interval=0.5,
            )
        except TimeoutError as exc:
            log.warning("alpaca-sync step 9 timed out: %s", exc)

        # ── Step 10: record observations ─────────────────────────────
        position_count, account_value, cash = await self._read_alpaca_state(session)
        regime = await self._read_regime(session, api_svc)

        label = "; ".join(errors) if errors else ""

        return DayObservation(
            date=trading_day,
            position_count=position_count,
            account_value=account_value,
            cash=cash,
            regime=regime,
            label=label,
            pipeline_status=pipeline_status,
            intents_submitted=intents_submitted,
            intents_accepted=intents_accepted,
        )

    # ------------------------------------------------------------------
    # State readers
    # ------------------------------------------------------------------

    async def _read_alpaca_state(
        self, session: aiohttp.ClientSession
    ) -> tuple[int, float, float]:
        """Return (position_count, account_value, cash) from alpaca-sim."""
        alpaca_sim = self.urls["alpaca_sim"]

        # account value + cash
        acct = await _get(session, f"{alpaca_sim}/v2/account")
        account_value = float(acct.get("portfolio_value") or acct.get("equity") or 0.0)
        cash = float(acct.get("cash") or 0.0)

        # position count from admin state
        state = await _get(session, f"{alpaca_sim}/admin/state")
        positions = state.get("positions", {})
        position_count = len(positions) if isinstance(positions, dict) else 0

        return position_count, account_value, cash

    async def _read_regime(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
    ) -> str:
        """Return the current regime string from the API service."""
        r = await _get(session, f"{api_url}/regime")
        return r.get("regime") or "unknown"

    async def _reset_alpaca_sim(
        self,
        session: aiohttp.ClientSession,
        scenario: Scenario,
    ) -> None:
        """Reset the alpaca-sim to starting cash (no positions yet).

        If the scenario has initial_positions they are seeded later, on day 0,
        after fetch-data has populated daily_prices in Postgres.
        """
        alpaca_sim = self.urls["alpaca_sim"]
        await _post(session, f"{alpaca_sim}/admin/reset")
        cash = scenario.initial_cash if scenario.initial_positions else 100_000.0
        await _post(session, f"{alpaca_sim}/admin/seed", {"cash": cash, "positions": {}})
        log.info("Alpaca simulator reset (cash=$%.0f, positions will be seeded on day 0).", cash)

    async def _seed_initial_positions(
        self,
        session: aiohttp.ClientSession,
        scenario: Scenario,
        start_date: date,
    ) -> None:
        """Seed the alpaca-sim with initial positions using day-0 DB prices."""
        if not scenario.initial_positions:
            return

        # Query Postgres for the most recent price per ticker at start_date
        tickers = [ip.ticker for ip in scenario.initial_positions]
        conn = await asyncpg.connect(self.dsn)
        try:
            rows = await conn.fetch(
                "SELECT DISTINCT ON (ticker) ticker, adjusted_close "
                "FROM daily_prices "
                "WHERE ticker = ANY($1) AND date <= $2 "
                "ORDER BY ticker, date DESC",
                tickers,
                start_date,
            )
            db_prices: Dict[str, float] = {r["ticker"]: float(r["adjusted_close"]) for r in rows}
        finally:
            await conn.close()

        # Compute positions dict (ticker → share qty)
        positions: Dict[str, float] = {}
        for ip in scenario.initial_positions:
            price = db_prices.get(ip.ticker)
            if price and price > 0:
                qty = math.floor(ip.value_usd / price)
                if qty > 0:
                    positions[ip.ticker] = float(qty)
                    log.info(
                        "Initial position: %s qty=%d @ $%.2f (value=$%.0f)",
                        ip.ticker, qty, price, qty * price,
                    )
            else:
                log.warning(
                    "No DB price for %s at %s — skipping initial position",
                    ip.ticker, start_date,
                )

        # Seed alpaca-sim (reset + seed preserves the correct starting state)
        alpaca_sim = self.urls["alpaca_sim"]
        result = await _post(session, f"{alpaca_sim}/admin/seed", {
            "cash": scenario.initial_cash,
            "positions": positions,
        })
        log.info(
            "Alpaca-sim seeded: cash=$%.0f, %d positions",
            scenario.initial_cash,
            len(result.get("positions", positions)),
        )
