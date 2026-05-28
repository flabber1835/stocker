"""
auto_approve — verifies the dashboard auto-approve background task.

In production, the dashboard's _auto_approve_bg() task polls /delta/latest
every 30 seconds and submits pending intents automatically after
TRADE_AUTO_APPROVE_MINUTES minutes without human action.

The standard harness manually submits every intent in Step 8, so this
path is never exercised. This scenario skips Step 8 entirely and waits
95 seconds, expecting auto-approve to have submitted all tradeable intents.

Requirement: the harness docker-compose must set
  TRADE_AUTO_APPROVE_MINUTES: "1"
on the dashboard service. The base harness docker-compose.yml already does
this; do not change it to a higher value or this scenario will time out.
"""
from datetime import date

from tests.harness.harness.scenario import RegimeChange, Scenario

AUTO_APPROVE = Scenario(
    name="auto_approve",
    description=(
        "5-day simulation. Step 8 (manual intent submission) is skipped every day. "
        "The scenario waits 95 seconds for the dashboard auto-approve task to fire "
        "(TRADE_AUTO_APPROVE_MINUTES=1 in harness docker-compose). "
        "Expects all tradeable intents to have order_status in "
        "(submitted, deferred, pending) after the wait."
    ),
    seed=13,
    universe_size=60,
    start_date=date(2024, 1, 2),
    end_date=date(2024, 1, 8),  # 5 trading days
    regimes=[
        RegimeChange(start_date=date(2024, 1, 2), regime_type="bull_calm"),
    ],
    run_vetter=False,
    skip_manual_approve=True,
    auto_approve_wait_secs=95,
)
