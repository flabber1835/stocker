"""Market proxy is configurable (MARKET_BENCHMARK), default SPY = unchanged.

Guards that the pipeline no longer hardcodes 'SPY' in its regime / beta / session
queries (it binds :bench) and that the default resolves to SPY.
"""
import os
import re

import app.main as m

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_default_benchmark_is_spy():
    assert m.MARKET_BENCHMARK == "SPY"


def test_pipeline_has_no_hardcoded_spy_ticker_literals():
    src = open(os.path.join(ROOT, "services", "pipeline", "app", "main.py")).read()
    # the analytical market-proxy queries must bind :bench, not a 'SPY' string literal
    assert "ticker = :bench" in src
    assert "ticker = 'SPY'" not in src, "pipeline still hardcodes ticker = 'SPY'"
