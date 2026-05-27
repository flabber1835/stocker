"""
SimulationDriver — drives the Docker Compose stack through a multi-day
simulation.  All HTTP calls use aiohttp; DB resets use asyncpg.
"""
from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import time
from datetime import date
from typing import Any, Dict, List, Optional

import aiohttp
import asyncpg

from .scenario import (
    DayObservation, Intervention, RestartRecoveryDay, Scenario, list_trading_days,
)


# Container groups for outage simulations. These map to docker-compose service
# names; the harness uses `docker compose stop/start` to toggle them.
_CORE_SERVICES = [
    "pipeline", "scheduler", "portfolio-builder", "llm-vetter",
    "alpaca-sync", "trade-executor", "api", "dashboard", "risk-service",
    "av-ingestor", "llm-gateway",
]
_INTERNET_SERVICES = [
    "av-sim", "alpaca-sim", "anthropic-sim", "tavily-sim",
]

# Maps harness step name → docker-compose service to restart for recovery tests.
_STEP_SERVICE_MAP: Dict[str, str] = {
    "fetch_data":         "av-ingestor",
    "pipeline":           "pipeline",
    "vetter":             "llm-vetter",
    "portfolio_builder":  "portfolio-builder",
    "delta":              "pipeline",   # same service, different endpoint
    "alpaca_sync":        "alpaca-sync",
}

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
    "delta_runs",
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
    prev_status: str = "",
    max_wait: float = 120.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Poll GET *url* until a fresh run reaches a terminal status.

    Two cases the caller may be in:

    1. prev_status was terminal (success/failed/skipped/no_runs/empty) — the
       previous /runs/latest snapshot showed yesterday's completed run. We
       need a NEW run_id with a terminal status to return.

    2. prev_status was 'running' or 'started' — a new run was already in
       progress when we captured the snapshot (e.g. Redis-triggered pipeline
       runs that beat the harness's POST to the lock). The run_id we captured
       IS the run we should wait on; just wait for it (or any successor) to
       reach a terminal status.

    Returning on `run_id != prev_run_id AND terminal` alone breaks case 2 —
    the running row we already saw will eventually become terminal, but its
    run_id never changes, so the original guard waits forever.
    """
    deadline = time.monotonic() + max_wait
    prev_was_running = prev_status in ("running", "started")
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as r:
                if r.status == 404:
                    await asyncio.sleep(interval)
                    continue
                data = await r.json(content_type=None)
                run_id = data.get("run_id", "")
                status = data.get("status", "")
                if status in ("running", "started", ""):
                    pass  # keep polling
                elif prev_was_running or run_id != prev_run_id:
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("poll_until_new_run %s: %s", url, exc)
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out after {max_wait}s waiting for new run at {url}")


async def poll_until_running(
    session: aiohttp.ClientSession,
    url: str,
    prev_run_id: str = "",
    max_wait: float = 8.0,
    interval: float = 0.1,
) -> Optional[str]:
    """Poll until a new run appears (any status, including success for fast jobs).

    Returns the new run_id as soon as it differs from prev_run_id, or None on timeout.
    The caller restarts the service immediately on detection — even if the job
    completed, the restart still tests recovery from an idle-service restart and
    the re-trigger path.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    run_id = data.get("run_id", "")
                    if run_id and run_id != prev_run_id:
                        return run_id
        except Exception:
            pass
        await asyncio.sleep(interval)
    return None  # timed out — step didn't start within the window


async def poll_until_aborted(
    session: aiohttp.ClientSession,
    url: str,
    aborted_run_id: str,
    max_wait: float = 90.0,
    interval: float = 0.5,
) -> bool:
    """Wait for the interrupted run to reach a terminal state (failed or success).

    Returns True when a terminal state is found. False on timeout.
    A 'success' result means the job completed before the restart killed it;
    'failed' with RESTART_ABORTED means it was killed mid-run (the interesting case).
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    run_id  = data.get("run_id",       "")
                    status  = data.get("status",        "")
                    err_msg = data.get("error_message", "") or ""
                    # Terminal state on the same run (success OR failed)
                    if run_id == aborted_run_id and status not in ("running", "started", ""):
                        aborted = status == "failed" and "RESTART_ABORTED" in err_msg
                        log.info("[restart] run %s terminal: status=%s aborted=%s",
                                 run_id[:8], status, aborted)
                        return True
                    # A different run already appeared — previous abort was processed
                    if run_id and run_id != aborted_run_id:
                        log.info("[restart] new run %s already started — prior run terminal implicit", run_id[:8])
                        return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


def _restart_service_sync(service_name: str) -> None:
    """Blocking docker compose restart (runs in executor to avoid blocking event loop)."""
    log.info("[restart] docker compose restart -t 3 %s", service_name)
    subprocess.run(
        ["docker", "compose", "restart", "-t", "3", service_name],
        check=False, capture_output=True, timeout=30,
    )
    log.info("[restart] %s restarted", service_name)


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
        self._alpaca_state_snapshot: Optional[Dict[str, Any]] = None
        self._current_scenario: Optional[Scenario] = None
        self._current_trading_day: Optional[date] = None

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
        if scenario.interventions:
            log.info("Scheduled interventions: %d", len(scenario.interventions))
            for iv in scenario.interventions:
                log.info("  day %d (%s): %s%s",
                         iv.on_day_index,
                         trading_days[iv.on_day_index] if iv.on_day_index < len(trading_days) else "?",
                         iv.action,
                         f" duration={iv.duration_days}d" if iv.duration_days else "")

        # Build per-day outage map: day_index → outage kind ("stack"|"internet")
        # An intervention with action="stack_off" or "internet_off" creates an
        # outage spanning [on_day_index, on_day_index + duration_days - 1].
        outage_by_day: Dict[int, str] = {}
        for iv in scenario.interventions:
            if iv.action in ("stack_off", "internet_off"):
                kind = "stack" if iv.action == "stack_off" else "internet"
                for d in range(iv.on_day_index, iv.on_day_index + iv.duration_days):
                    outage_by_day[d] = kind

        restart_by_day: Dict[int, List[str]] = {
            rrd.day_index: rrd.steps for rrd in scenario.restart_recovery_days
        }
        force_days: set = set(scenario.force_pipeline_days)

        self._current_scenario = scenario
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # ── Pre-simulation setup ──────────────────────────────────
            await reset_database(self.dsn)
            await self._reset_alpaca_sim(session, scenario)
            await load_scenario_to_av_sim(scenario, self.urls["av_sim"], session)

            # ── Day-by-day loop ──────────────────────────────────────
            prev_outage: Optional[str] = None
            for day_index, trading_day in enumerate(trading_days):
                self._current_trading_day = trading_day
                current_outage = outage_by_day.get(day_index)

                # Transition into an outage at its first day
                if current_outage and prev_outage != current_outage:
                    await self._begin_outage(current_outage, session)

                # Transition out of an outage (we just left a window)
                if prev_outage and not current_outage:
                    await self._end_outage(prev_outage, session)

                if current_outage:
                    # Skip normal day processing while services are down
                    obs = DayObservation(
                        date=trading_day,
                        position_count=0,
                        account_value=0.0,
                        cash=0.0,
                        regime="unknown",
                        label=f"outage:{current_outage}",
                    )
                    log.info(
                        "Day %d/%d %s: OUTAGE (%s) — skipping",
                        day_index + 1, len(trading_days), trading_day, current_outage,
                    )
                else:
                    obs = await self._run_day(
                        session=session,
                        scenario=scenario,
                        trading_day=trading_day,
                        day_index=day_index,
                        force_pipeline=(day_index in force_days),
                        restart_steps=restart_by_day.get(day_index),
                    )
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

                observations.append(obs)
                prev_outage = current_outage

                # Fire any one-shot interventions scheduled for this day,
                # AFTER the day's processing completes
                for iv in scenario.interventions:
                    if iv.on_day_index != day_index:
                        continue
                    if iv.action == "liquidate_and_withdraw":
                        await self._apply_liquidate_and_withdraw(session, iv)
                    elif iv.action == "manual_run":
                        log.info("[intervention] manual_run on day %d (%s)", day_index + 1, trading_day)
                        obs_rerun = await self._run_day(
                            session=session, scenario=scenario,
                            trading_day=trading_day, day_index=day_index,
                            force_pipeline=True,
                        )
                        log.info("[intervention] manual_run result: %d positions, $%.0f [%s]",
                                 obs_rerun.position_count, obs_rerun.account_value,
                                 obs_rerun.label or "ok")
                        obs_rerun.label = (obs_rerun.label + " manual_rerun").strip()
                        observations.append(obs_rerun)

            # End any outage that ran through the final day
            if prev_outage:
                await self._end_outage(prev_outage, session)

        log.info("Simulation '%s' complete.", scenario.name)
        return observations

    # ------------------------------------------------------------------
    # Intervention handlers
    # ------------------------------------------------------------------

    async def _apply_liquidate_and_withdraw(
        self, session: aiohttp.ClientSession, iv: Intervention,
    ) -> None:
        """Liquidate one position via alpaca-sim admin, then drain cash to $0."""
        alpaca_sim = self.urls["alpaca_sim"]
        # Find the ticker to liquidate
        async with session.get(f"{alpaca_sim}/admin/state") as r:
            state = await r.json()
        positions = state.get("positions", {})
        if not positions:
            log.warning("[intervention] liquidate: no positions to liquidate")
            return
        if iv.ticker and iv.ticker in positions:
            ticker = iv.ticker
        else:
            # Pick the largest position by qty × avg_entry_price (cost basis)
            ticker = max(positions.items(), key=lambda kv: float(kv[1]["cost_basis"]))[0]

        log.info("[intervention] liquidating position %s (note=%s)", ticker, iv.note)
        async with session.post(
            f"{alpaca_sim}/admin/liquidate-position", json={"ticker": ticker}
        ) as r:
            liq = await r.json()
        log.info("[intervention]   → sold qty=%.2f @ $%.2f, proceeds=$%.2f, cash now=$%.2f",
                 liq.get("qty", 0), liq.get("price", 0),
                 liq.get("proceeds", 0), liq.get("cash_after", 0))

        # Drain remaining cash to zero
        async with session.post(
            f"{alpaca_sim}/admin/withdraw-cash", json={"amount": None}
        ) as r:
            wd = await r.json()
        log.info("[intervention]   → withdrew $%.2f, cash now=$%.2f",
                 wd.get("amount", 0), wd.get("cash_after", 0))

    async def _begin_outage(self, kind: str, session: aiohttp.ClientSession) -> None:
        services = _CORE_SERVICES if kind == "stack" else _INTERNET_SERVICES
        log.info("[intervention] BEGIN %s OUTAGE: stopping %s", kind, " ".join(services))
        # For internet outages, snapshot alpaca-sim state before it's stopped.
        # The in-memory sim loses state on restart; we restore it afterwards so
        # the simulation accurately models "internet is down" (broker state persists
        # on their servers, we just can't reach them).
        if kind == "internet":
            try:
                async with session.get(
                    f"{self.urls['alpaca_sim']}/admin/state",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as r:
                    if r.status == 200:
                        self._alpaca_state_snapshot = await r.json()
                        log.info("[intervention] alpaca-sim state snapshot: cash=%.2f positions=%d",
                                 self._alpaca_state_snapshot.get("cash", 0),
                                 len(self._alpaca_state_snapshot.get("positions", {})))
            except Exception as exc:
                log.warning("[intervention] could not snapshot alpaca-sim state: %s", exc)
                self._alpaca_state_snapshot = None
        subprocess.run(
            ["docker", "compose", "stop", "-t", "5"] + services,
            check=False, capture_output=True, timeout=120,
        )

    async def _end_outage(self, kind: str, session: aiohttp.ClientSession) -> None:
        services = _CORE_SERVICES if kind == "stack" else _INTERNET_SERVICES
        log.info("[intervention] END %s OUTAGE: starting %s", kind, " ".join(services))
        subprocess.run(
            ["docker", "compose", "start"] + services,
            check=False, capture_output=True, timeout=120,
        )
        # Wait for services to become healthy before resuming
        await asyncio.sleep(10)
        await self._wait_for_health(session, kind)
        # For internet outages, restore the alpaca-sim state that was snapshotted
        # before the outage began so broker positions survive the restart.
        if kind == "internet":
            if self._alpaca_state_snapshot:
                try:
                    async with session.post(
                        f"{self.urls['alpaca_sim']}/admin/restore-state",
                        json=self._alpaca_state_snapshot,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as r:
                        if r.status == 200:
                            result = await r.json()
                            log.info("[intervention] alpaca-sim state restored: cash=%.2f positions=%d",
                                     self._alpaca_state_snapshot.get("cash", 0),
                                     result.get("positions", 0))
                        else:
                            log.warning("[intervention] restore-state returned %d", r.status)
                except Exception as exc:
                    log.warning("[intervention] could not restore alpaca-sim state: %s", exc)
                self._alpaca_state_snapshot = None
            # av-sim also loses all in-memory state on restart (prices, tickers,
            # as_of_date). Reload the scenario so the ingestor can fetch fresh data.
            # Without this, spy_max stays at pre-outage date and every pipeline run
            # returns already_ran_today, timing out the harness for every post-outage day.
            if self._current_scenario is not None:
                log.info("[intervention] reloading av-sim scenario after internet outage")
                await load_scenario_to_av_sim(
                    self._current_scenario, self.urls["av_sim"], session,
                )
                # Set as_of_date to the current simulation day so the ingestor
                # can fetch prices through today.
                if self._current_trading_day is not None:
                    await _post(session, f"{self.urls['av_sim']}/admin/set-as-of-date",
                                {"as_of_date": self._current_trading_day.isoformat()})

    async def _wait_for_health(
        self, session: aiohttp.ClientSession, kind: str,
    ) -> None:
        """Poll service health endpoints up to ~60s after an outage ends."""
        if kind == "stack":
            urls_to_check = [
                self.urls["pipeline"], self.urls["portfolio_builder"],
                self.urls["alpaca_sync"], self.urls["trade_executor"],
                self.urls["api"], self.urls["risk_service"],
            ]
        else:
            urls_to_check = [
                self.urls["av_sim"], self.urls["alpaca_sim"],
            ]
        deadline = time.monotonic() + 60.0
        for url in urls_to_check:
            while time.monotonic() < deadline:
                try:
                    async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
                        if r.status == 200:
                            break
                except Exception:
                    pass
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Mid-step restart helper (crash-recovery testing)
    # ------------------------------------------------------------------

    async def _do_restart_mid_step(
        self,
        session: aiohttp.ClientSession,
        step_name: str,
        runs_url: str,
        prev_run_id: str,
        trigger_url: Optional[str] = None,
        new_run_id: Optional[str] = None,
    ) -> str:
        """Restart the service for `step_name` mid-execution and wait for recovery.

        Steps:
          1. Obtain the run_id for the in-flight run (from POST response or polling)
          2. Issue docker compose restart -t 3 <service>
          3. Confirm the interrupted run reaches a terminal state
          4. Re-trigger via trigger_url (harness plays the scheduler role)
          5. Wait for the recovery run to reach a terminal status

        new_run_id — run_id returned by the trigger POST.  When provided the
        harness uses it directly (the DB row was committed before the response was
        sent), eliminating the polling detection window entirely.

        Returns a label string: "step:recovered" or "step:missed_window".
        """
        service = _STEP_SERVICE_MAP.get(step_name, step_name)
        t_start = time.monotonic()

        # 1. Obtain the in-flight run_id.
        #    Prefer the run_id from the trigger POST response — it is guaranteed
        #    to exist in the DB when the response is returned (INSERT committed
        #    synchronously before response).  Fall back to polling only when the
        #    endpoint did not return a run_id (legacy or error path).
        if new_run_id:
            detected_id = new_run_id
            log.info("[restart] %s (run_id=%s) detected via POST response — restarting %s",
                     step_name, detected_id[:8], service)
        else:
            detected_id = await poll_until_running(
                session, runs_url, prev_run_id=prev_run_id, max_wait=8.0,
            )
            if not detected_id:
                log.warning("[restart] %s: step never started within 8s — skipping", step_name)
                return f"{step_name}:missed_window"
            log.info("[restart] %s (run_id=%s) detected — restarting %s",
                     step_name, detected_id[:8], service)

        # 2. Restart in thread pool (subprocess blocks)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _restart_service_sync, service)

        # 3. Wait for the detected run to reach a terminal state (success = completed before
        #    the kill; failed+RESTART_ABORTED = killed mid-run; both are valid).
        reached_terminal = await poll_until_aborted(session, runs_url, detected_id, max_wait=90.0)
        if not reached_terminal:
            log.warning("[restart] %s: run %s never reached terminal state after 90s",
                        step_name, detected_id[:8])

        # 4. Re-trigger the step (harness plays the scheduler: sees terminal → re-fire)
        if trigger_url:
            log.info("[restart] %s: re-triggering via %s", step_name, trigger_url)
            await asyncio.sleep(2.0)   # give the service time to finish startup
            await _post(session, trigger_url)

        # 5. Wait for the recovery/re-triggered run to complete.
        #    prev_run_id=detected_id skips the detected row and waits for the new run.
        try:
            recovery = await poll_until_new_run(
                session, runs_url,
                prev_run_id=detected_id,
                prev_status="failed",   # treat detected row as non-running → wait for new run_id
                max_wait=240.0,
            )
            elapsed = round(time.monotonic() - t_start, 1)
            status = recovery.get("status", "?")
            log.info("[restart] %s: recovery run status=%s in %.1fs total", step_name, status, elapsed)
            return f"{step_name}:recovered"
        except TimeoutError:
            elapsed = round(time.monotonic() - t_start, 1)
            log.warning("[restart] %s: recovery run timed out after %.1fs", step_name, elapsed)
            return f"{step_name}:recovery_timeout"

    # ------------------------------------------------------------------
    # Single-day execution
    # ------------------------------------------------------------------

    async def _run_day(
        self,
        session: aiohttp.ClientSession,
        scenario: Scenario,
        trading_day: date,
        day_index: int,
        force_pipeline: bool = False,
        restart_steps: Optional[List[str]] = None,
    ) -> DayObservation:
        errors: List[str] = []
        pipeline_status = ""
        intents_submitted = 0
        intents_accepted = 0
        _restart = set(restart_steps or [])
        _restart_labels: List[str] = []

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
            _prev_status = _prev.get("status", "")
        except Exception:
            _prev_run_id = ""
            _prev_status = ""
        start_r = await _post(session, f"{av_ing}/jobs/fetch-data")
        if "error" not in start_r:
            if "fetch_data" in _restart:
                lbl = await self._do_restart_mid_step(
                    session, "fetch_data", f"{av_ing}/runs/latest", prev_run_id=_prev_run_id,
                    trigger_url=f"{av_ing}/jobs/fetch-data",
                    new_run_id=start_r.get("run_id"),
                )
                _restart_labels.append(lbl)
            try:
                await poll_until_new_run(
                    session, f"{av_ing}/runs/latest",
                    prev_run_id=_prev_run_id,
                    prev_status=_prev_status,
                    max_wait=180, interval=0.5,
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
                _prev_sync_status = _prev_sync.get("status", "")
            except Exception:
                _prev_sync_id = ""
                _prev_sync_status = ""
            await _post(session, f"{a_sync}/jobs/sync")
            try:
                await poll_until_new_run(
                    session, f"{a_sync}/runs/latest",
                    prev_run_id=_prev_sync_id, prev_status=_prev_sync_status,
                    max_wait=30, interval=0.5,
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
            _prev_pipe_status = _prev_pipe.get("status", "") or ""
        except Exception:
            _prev_pipe_id = ""
            _prev_pipe_status = ""
        pipeline_run_url = f"{pipeline}/jobs/run{'?force=true' if force_pipeline else ''}"
        start_r = await _post(session, pipeline_run_url)
        if start_r.get("status") in ("already_running",) or "error" not in start_r:
            if "pipeline" in _restart:
                lbl = await self._do_restart_mid_step(
                    session, "pipeline", f"{pipeline}/runs/latest", prev_run_id=_prev_pipe_id,
                    trigger_url=pipeline_run_url,
                    new_run_id=start_r.get("run_id"),
                )
                _restart_labels.append(lbl)
            try:
                final = await poll_until_new_run(
                    session, f"{pipeline}/runs/latest",
                    prev_run_id=_prev_pipe_id, prev_status=_prev_pipe_status,
                    max_wait=180, interval=0.5,
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
            try:
                _prev_vet = await _get(session, f"{vetter}/runs/latest")
                _prev_vet_id = _prev_vet.get("run_id", "") or ""
            except Exception:
                _prev_vet_id = ""
            start_r = await _post(session, f"{vetter}/jobs/vet")
            if start_r.get("status") not in ("already_running", "error") and "error" not in start_r:
                if "vetter" in _restart:
                    lbl = await self._do_restart_mid_step(
                        session, "vetter", f"{vetter}/runs/latest", prev_run_id=_prev_vet_id,
                        trigger_url=f"{vetter}/jobs/vet",
                        new_run_id=start_r.get("run_id"),
                    )
                    _restart_labels.append(lbl)
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
            _prev_pb_status = _prev_pb.get("status", "") or ""
        except Exception:
            _prev_pb_id = ""
            _prev_pb_status = ""
        start_r = await _post(session, f"{pb}/jobs/build")
        if "error" in start_r:
            errors.append(f"portfolio-builder start: {start_r.get('error')}")
        else:
            if "portfolio_builder" in _restart:
                lbl = await self._do_restart_mid_step(
                    session, "portfolio_builder", f"{pb}/runs/latest", prev_run_id=_prev_pb_id,
                    trigger_url=f"{pb}/jobs/build",
                    new_run_id=start_r.get("run_id"),
                )
                _restart_labels.append(lbl)
            try:
                await poll_until_new_run(
                    session, f"{pb}/runs/latest",
                    prev_run_id=_prev_pb_id, prev_status=_prev_pb_status,
                    max_wait=120, interval=0.5,
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
            _prev_dl_status = _prev_dl.get("status", "") or ""
        except Exception:
            _prev_dl_id = ""
            _prev_dl_status = ""
        start_r = await _post(session, f"{pipeline}/jobs/delta")
        if "error" in start_r:
            errors.append(f"delta start: {start_r.get('error')}")
        else:
            if "delta" in _restart:
                lbl = await self._do_restart_mid_step(
                    session, "delta", f"{pipeline}/runs/delta-latest", prev_run_id=_prev_dl_id,
                    trigger_url=f"{pipeline}/jobs/delta",
                    new_run_id=start_r.get("run_id"),
                )
                _restart_labels.append(lbl)
            try:
                final = await poll_until_new_run(
                    session, f"{pipeline}/runs/delta-latest",
                    prev_run_id=_prev_dl_id, prev_status=_prev_dl_status,
                    max_wait=120, interval=0.5,
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
            _prev_sync9_status = _prev_sync9.get("status", "")
        except Exception:
            _prev_sync9_id = ""
            _prev_sync9_status = ""
        sync_start_r = await _post(session, f"{a_sync}/jobs/sync")
        if "alpaca_sync" in _restart:
            lbl = await self._do_restart_mid_step(
                session, "alpaca_sync", f"{a_sync}/runs/latest", prev_run_id=_prev_sync9_id,
                trigger_url=f"{a_sync}/jobs/sync",
                new_run_id=sync_start_r.get("run_id"),
            )
            _restart_labels.append(lbl)
        try:
            await poll_until_new_run(
                session, f"{a_sync}/runs/latest",
                prev_run_id=_prev_sync9_id, prev_status=_prev_sync9_status,
                max_wait=60, interval=0.5,
            )
        except TimeoutError as exc:
            log.warning("alpaca-sync step 9 timed out: %s", exc)

        # ── Step 10: record observations ─────────────────────────────
        position_count, account_value, cash = await self._read_alpaca_state(session)
        regime = await self._read_regime(session, api_svc)

        parts = _restart_labels + (errors if errors else [])
        label = "; ".join(parts)

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
