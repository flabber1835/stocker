"""The falling-knife veto's beta uses the configurable MARKET_BENCHMARK, not a
hardcoded 'SPY'. This is the consumer that must match the pipeline's card so the
screener's excess_dd == the real veto trigger (card==veto parity) when the benchmark
is changed. Default SPY = unchanged behavior.
"""
import os

import app.main as m

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_default_benchmark_is_spy():
    assert m.MARKET_BENCHMARK == "SPY"


def test_vetter_has_no_hardcoded_spy_benchmark_query():
    src = open(os.path.join(ROOT, "services", "llm-vetter", "app", "main.py")).read()
    assert "ticker = :bench" in src, "vetter benchmark query must bind :bench"
    assert "WHERE ticker = 'SPY'" not in src, "vetter still hardcodes the SPY benchmark"
