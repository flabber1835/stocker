"""Tests for the shared investability floor + a guard that the delta and the
portfolio-builder SOURCE it from the shared module (not their own avg-dollar-volume
definition) — the anti-divergence guard for the split-brain 'investable means
different things in different steps' bug.
"""
import math
from pathlib import Path

from stock_strategy_shared.investability import (
    avg_dollar_volume,
    below_investability_floor,
    DOLLAR_VOLUME_WINDOW,
)

ROOT = Path(__file__).resolve().parents[2]


# ── avg_dollar_volume (close × volume, last window) ─────────────────────────────

def test_avg_dollar_volume_basic():
    # 3 sessions: 10×100, 20×100, 30×100 → mean(1000,2000,3000) = 2000
    assert avg_dollar_volume([10, 20, 30], [100, 100, 100]) == 2000.0


def test_avg_dollar_volume_windowed():
    closes = [1] * 30
    vols = [100] * 29 + [999999]   # only the last 20 count; last one dominates
    out = avg_dollar_volume(closes, vols, window=20)
    expected = (100 * 19 + 999999) / 20
    assert out == expected


def test_avg_dollar_volume_skips_none_and_nan():
    out = avg_dollar_volume([10, None, float("nan"), 20], [100, 100, 100, 100])
    assert out == ((10 * 100) + (20 * 100)) / 2


def test_avg_dollar_volume_empty_is_none():
    assert avg_dollar_volume([], []) is None
    assert avg_dollar_volume([None, float("nan")], [1, 2]) is None


# ── below_investability_floor ───────────────────────────────────────────────────

def test_below_floor_price():
    assert below_investability_floor(4.0, 50e6, min_price=5.0, min_avg_dollar_volume=20e6) is True


def test_below_floor_liquidity():
    assert below_investability_floor(50.0, 10e6, min_price=5.0, min_avg_dollar_volume=20e6) is True


def test_meets_floor():
    assert below_investability_floor(50.0, 50e6, min_price=5.0, min_avg_dollar_volume=20e6) is False


def test_none_metrics_not_below():
    # missing measures are 'unknown', NOT below — never drop a name on a missing metric
    assert below_investability_floor(None, None, min_price=5.0, min_avg_dollar_volume=20e6) is False
    assert below_investability_floor(50.0, None, min_price=5.0, min_avg_dollar_volume=20e6) is False


# ── anti-divergence guard ───────────────────────────────────────────────────────

def test_delta_uses_shared_floor():
    src = (ROOT / "services" / "pipeline" / "app" / "engine.py").read_text()
    assert "from stock_strategy_shared.investability import below_investability_floor" in src
    assert "below_investability_floor(last_px, avg_dv" in src


def test_builder_uses_shared_floor_not_fundamentals_avg_volume():
    src = (ROOT / "services" / "portfolio-builder" / "app" / "main.py").read_text()
    assert "from stock_strategy_shared.investability import" in src
    assert "below_investability_floor(" in src
    assert "avg_dollar_volume(" in src
    # the divergent source (fundamentals.avg_volume) must be gone from the floor filter
    assert "SELECT DISTINCT ON (ticker) ticker, avg_volume" not in src
