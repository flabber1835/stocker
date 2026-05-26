from datetime import date

from tests.harness.harness.scenario import RegimeChange, Scenario

YEAR_BULL_BEAR = Scenario(
    name="year_bull_bear",
    seed=20240101,
    universe_size=100,
    start_date=date(2024, 1, 2),
    end_date=date(2025, 1, 2),
    regimes=[
        RegimeChange(start_date=date(2024, 1, 2),  regime_type="bull_calm"),
        RegimeChange(start_date=date(2024, 6, 1),  regime_type="bear_stress"),
        RegimeChange(start_date=date(2024, 10, 1), regime_type="bull_calm"),
    ],
    run_vetter=True,
    vetter_every_n_days=5,
    description="1-year bull→bear→bull cycle with 100 tickers",
)
