"""
3-day crash-recovery simulation.

Tests that each pipeline service recovers automatically after a mid-step
docker-compose restart (simulating a crash or OOM kill mid-execution).

Day 0 — cold boot (first ever run, empty DB):
  Each of the 6 pipeline services is restarted while its step is running.
  Verifies the RESTART_ABORTED: orphan-cleanup path fires and the chain
  re-runs to completion.

Day 1 — second scheduled run (warm DB with prior-day data):
  Same per-step restarts on a warm system.  Tests that orphan cleanup
  doesn't collide with prior-day success rows.

Day 2 — force=True (manual run, same data as day 1 but fresh pipeline):
  Uses force_pipeline_days=[2] so the pipeline is triggered with force=True
  (bypassing already_ran_today guard).  Same per-step restarts.  Tests that
  forced re-runs survive crash-recovery correctly.
"""

from datetime import date

from tests.harness.harness.scenario import RegimeChange, RestartRecoveryDay, Scenario

_ALL_STEPS = [
    "fetch_data",
    "pipeline",
    "vetter",
    "portfolio_builder",
    "delta",
    "alpaca_sync",
]

RESTART_RECOVERY = Scenario(
    name="restart_recovery",
    seed=20240101,
    universe_size=100,          # ≥100 required to pass av-ingestor LISTING_STATUS validation
    start_date=date(2024, 1, 2),
    end_date=date(2024, 1, 4),  # 3 trading days: Jan 2, 3, 4
    regimes=[RegimeChange(date(2024, 1, 2), "bull_calm")],
    run_vetter=True,
    vetter_every_n_days=1,      # run vetter every day so it's always exercised
    restart_recovery_days=[
        RestartRecoveryDay(day_index=0, steps=_ALL_STEPS),  # cold boot
        RestartRecoveryDay(day_index=1, steps=_ALL_STEPS),  # warm run
        RestartRecoveryDay(day_index=2, steps=_ALL_STEPS),  # forced re-run
    ],
    force_pipeline_days=[1, 2],  # harness runs all days on same wall-clock date; force bypasses already_ran_today
    description=(
        "3-day crash/restart recovery: each pipeline step is interrupted "
        "mid-execution by a docker compose restart and verified to recover "
        "via RESTART_ABORTED orphan cleanup."
    ),
)
