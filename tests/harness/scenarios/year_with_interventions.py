"""
1-year simulation with regime changes + four real-world operational events:

  1. day 29  (~Feb 12 2024): manual_run #1 — user presses Run mid-month
  2. day 59  (~Mar 25 2024) for 3 days: stack_off — "computer is off for the weekend"
  3. day 130 (~Jul 2 2024): liquidate_and_withdraw — user pulls cash from one position
  4. day 175 (~Sep 3 2024): manual_run #2
  5. day 199 (~Oct 7 2024) for 2 days: internet_off — "ISP is down"
  6. day 230 (~Nov 19 2024): manual_run #3
  7. day 245 (~Dec 10 2024): manual_run #4 — final routine manual trigger

Regime schedule (same as year_initial_positions):
  bull_calm   2024-01-02 → 2024-05-31
  bear_stress 2024-06-01 → 2024-09-30
  bull_calm   2024-10-01 → 2025-01-02

The liquidation on day 130 lands right after the bear→bull-no-actually-bear
transition (regime flipped to bear_stress on Jun 1, day ~105). This is the
worst possible moment to lose a position + all cash — the system is mid-flux,
positions are getting reshuffled, and we then drop cash to zero.
"""

from datetime import date

from tests.harness.harness.scenario import (
    InitialPosition,
    Intervention,
    RegimeChange,
    Scenario,
)

# Reuse the universe builder from year_initial_positions to keep the two
# scenarios directly comparable (same tickers, same regime schedule, same
# initial positions, only interventions added).
from tests.harness.scenarios.year_initial_positions import _build_extra_tickers


YEAR_WITH_INTERVENTIONS = Scenario(
    name="year_with_interventions",
    seed=20240101,
    universe_size=110,
    start_date=date(2024, 1, 2),
    end_date=date(2025, 1, 2),
    regimes=[
        RegimeChange(date(2024, 1, 2),  "bull_calm"),
        RegimeChange(date(2024, 6, 1),  "bear_stress"),
        RegimeChange(date(2024, 10, 1), "bull_calm"),
    ],
    run_vetter=True,
    vetter_every_n_days=5,
    initial_cash=10_000.0,
    initial_positions=[
        InitialPosition(ticker="AAPL", value_usd=15_000.0),
        InitialPosition(ticker="SNDK", value_usd=10_000.0),
        InitialPosition(ticker="MU",   value_usd=20_000.0),
        InitialPosition(ticker="KEYS", value_usd=15_000.0),
        InitialPosition(ticker="V",    value_usd=30_000.0),
    ],
    extra_tickers=_build_extra_tickers(),
    interventions=[
        Intervention(
            on_day_index=29,
            action="manual_run",
            note="Routine manual chain trigger — verifies same-day re-run is safe",
        ),
        Intervention(
            on_day_index=59,
            action="stack_off",
            duration_days=3,
            note="Operator's computer is off for 3 days (~long weekend)",
        ),
        Intervention(
            on_day_index=130,
            action="liquidate_and_withdraw",
            note="Cash crunch: user liquidates the largest position and pulls everything out",
        ),
        Intervention(
            on_day_index=175,
            action="manual_run",
            note="Second routine manual run, ~Sep 3",
        ),
        Intervention(
            on_day_index=199,
            action="internet_off",
            duration_days=2,
            note="ISP outage: core services running but av-sim/alpaca-sim unreachable",
        ),
        Intervention(
            on_day_index=230,
            action="manual_run",
            note="Manual run during post-outage normal operation",
        ),
        Intervention(
            on_day_index=245,
            action="manual_run",
            note="Last manual run, near year-end",
        ),
    ],
    description=(
        "1-year bull→bear→bull with real-world operational events: "
        "manual runs, 3-day computer outage, mid-year liquidation + cash withdrawal, "
        "2-day internet outage."
    ),
)
