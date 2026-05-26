from datetime import date

from tests.harness.harness.scenario import RegimeChange, Scenario

QUICK_SMOKE = Scenario(
    name="quick_smoke",
    seed=42,
    universe_size=60,
    start_date=date(2024, 1, 2),
    end_date=date(2024, 2, 15),  # ~30 trading days
    regimes=[
        RegimeChange(start_date=date(2024, 1, 2), regime_type="bull_calm"),
    ],
    run_vetter=False,
    description="30-day smoke test with 60 tickers",
)
