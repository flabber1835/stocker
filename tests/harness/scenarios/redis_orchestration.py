"""
redis_orchestration — verifies the Redis event-driven pipeline triggers.

In production, two code paths connect services via Redis streams:

  fetch_data.complete (published by av-ingestor)
    → pipeline's _redis_consumer_loop wakes up and runs factors + rank

  portfolio_builder.complete (published by portfolio-builder)
    → pipeline's _redis_consumer_loop wakes up and runs delta

The standard harness scenarios bypass both: they call POST /jobs/run and
POST /jobs/delta directly. With rely_on_redis_triggers=True the harness
skips those POSTs and waits for self-trigger instead, exercising the same
code path production uses.
"""
from datetime import date

from tests.harness.harness.scenario import RegimeChange, Scenario

REDIS_ORCHESTRATION = Scenario(
    name="redis_orchestration",
    description=(
        "1-day simulation that omits the direct /jobs/run and /jobs/delta triggers. "
        "Pipeline must self-trigger from the fetch_data.complete Redis event; "
        "delta must self-trigger from portfolio_builder.complete. "
        "The single day must complete without timeout errors."
    ),
    seed=7,
    universe_size=60,
    start_date=date(2024, 1, 2),
    end_date=date(2024, 1, 2),  # 1 trading day — proves the Redis trigger mechanism works
    regimes=[
        RegimeChange(start_date=date(2024, 1, 2), regime_type="bull_calm"),
    ],
    run_vetter=False,
    rely_on_redis_triggers=True,
)
