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
    # Scan the whole service, not just main.py: the regime step's benchmark query
    # now lives in factor_inputs.py, and a main.py-only scan would pass vacuously
    # for any query that moves out of it.
    import glob
    app_dir = os.path.join(ROOT, "services", "pipeline", "app")
    src = "".join(open(f).read() for f in sorted(glob.glob(os.path.join(app_dir, "*.py"))))
    # the analytical market-proxy queries must bind :bench, not a 'SPY' string literal
    assert "ticker = :bench" in src
    assert "ticker = 'SPY'" not in src, "pipeline still hardcodes ticker = 'SPY'"
