"""
Scenario and RegimeChange dataclasses, plus trading-day utilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class RegimeChange:
    """Marks the start of a new market regime."""
    start_date: date
    regime_type: str  # "bull_calm" | "bull_stress" | "bear_stress" | "bear_calm"


@dataclass
class InitialPosition:
    """One holding to seed into the Alpaca simulator at simulation start."""
    ticker: str
    value_usd: float  # approximate dollar value; qty is computed from start-date DB price


@dataclass
class Intervention:
    """A manual event applied between trading days.

    Supported actions:
      - "liquidate_and_withdraw": pick the largest current position, sell it at
        the most-recent price (proceeds → cash), then withdraw all cash so the
        sim ends the day with $0 cash and one fewer position. `ticker` lets the
        scenario pin a specific position; otherwise the largest is chosen.

      - "stack_off": stop the core stocker services (pipeline, scheduler,
        portfolio-builder, llm-vetter, alpaca-sync, trade-executor, api,
        dashboard, risk-service) for `duration_days` trading days, then start
        them back up. Simulates "the operator's computer is off for a few days"
        — postgres and redis stay up so state persists.

      - "internet_off": stop the simulator containers (av-sim, alpaca-sim,
        anthropic-sim, tavily-sim) for `duration_days` trading days, then
        start them back up. Simulates "the internet is down" — core stocker
        services remain running but every external data fetch / order
        submission fails.

      - "manual_run": after the day's normal pipeline cycle completes,
        re-run the cycle on the same sim trading day with force=True (same
        as the dashboard "Run" button). Bypasses the already_ran_today
        guard so a second full pipeline run is created, producing fresh
        rankings and a new trading proposal. Tests intent-purge correctness
        and that risk-service / trade-executor handle back-to-back runs.
    """
    on_day_index: int                     # zero-based trading-day index when the intervention fires
    action: str                           # "liquidate_and_withdraw" | "stack_off" | "internet_off"
    ticker: Optional[str] = None          # liquidate_and_withdraw: pin a position; None = largest
    duration_days: int = 0                # stack_off / internet_off: number of trading days
    note: str = ""


@dataclass
class Scenario:
    """Full description of a multi-day simulation run."""
    name: str
    seed: int
    universe_size: int
    start_date: date
    end_date: date
    regimes: List[RegimeChange]
    run_vetter: bool = False
    vetter_every_n_days: int = 5  # run vetter every N trading days
    description: str = ""
    # Starting cash and positions seeded into alpaca-sim (after day-0 fetch-data)
    initial_cash: float = 100_000.0
    initial_positions: Optional[List[InitialPosition]] = None
    # Extra (pinned) tickers to include in the av-sim universe.
    # Each entry is a dict with keys: ticker, name, sector, exchange.
    # Sibling pairs should share the same `name` value so analysis can identify them.
    extra_tickers: Optional[List[Dict[str, Any]]] = None
    # Manual interventions applied between trading days.
    interventions: List[Intervention] = field(default_factory=list)
    # Per-day restart specs: restart the named service mid-step to test recovery.
    restart_recovery_days: List["RestartRecoveryDay"] = field(default_factory=list)
    # Day indices on which the pipeline POST should use force=True (manual run).
    force_pipeline_days: List[int] = field(default_factory=list)
    # When True, skip manual POST /jobs/run and POST /jobs/delta — let the Redis
    # event chain self-trigger them (fetch_data.complete → pipeline;
    # portfolio_builder.complete → delta). Tests the production orchestration path.
    rely_on_redis_triggers: bool = False
    # When True, skip Step 8 (manual intent submission). Use with auto_approve_wait_secs
    # to test dashboard auto-approve, or with post_delta_hook to handle submission there.
    skip_manual_approve: bool = False
    # Seconds to wait after delta for dashboard auto-approve to fire.
    # Only used when skip_manual_approve=True. Checks all tradeable intents
    # are submitted/deferred/pending after the wait; adds errors for any that aren't.
    auto_approve_wait_secs: int = 0
    # Async callable: (driver, session, errors) -> None.
    # Called after Step 6 (delta) completes, before Step 7 (read intents).
    # Receives the SimulationDriver instance, the aiohttp ClientSession, and the
    # mutable errors list. May read driver._current_delta_run_id for the delta run id.
    post_delta_hook: Optional[Any] = None


@dataclass
class RestartRecoveryDay:
    """Specifies which pipeline steps to crash-restart mid-execution on a given day.

    For each step name in `steps`, the driver: triggers the step, waits until
    status='running', issues `docker compose restart` on the relevant service,
    then waits for the RESTART_ABORTED recovery run to complete.

    Step names → service:
      fetch_data        → av-ingestor
      pipeline          → pipeline
      vetter            → llm-vetter
      portfolio_builder → portfolio-builder
      delta             → pipeline  (same service, /jobs/delta endpoint)
      alpaca_sync       → alpaca-sync
    """
    day_index: int       # zero-based trading-day index
    steps: List[str]     # ordered list of step names to restart mid-execution


@dataclass
class DayObservation:
    """Recorded state at the end of one simulated trading day."""
    date: date
    position_count: int
    account_value: float
    cash: float
    regime: str
    label: str = ""
    pipeline_status: str = ""
    intents_submitted: int = 0
    intents_accepted: int = 0


def list_trading_days(start: date, end: date) -> List[date]:
    """Return all weekdays (Mon–Fri) from start to end inclusive."""
    days: List[date] = []
    current = start
    while current <= end:
        # weekday(): 0=Mon … 4=Fri, 5=Sat, 6=Sun
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days
