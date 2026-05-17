"""
Comprehensive tests for the pure-Python delta engine.
"""
from datetime import date, timedelta

import pytest

from app.engine import (
    RankObservation,
    DeltaDecision,
    evaluate_ticker,
    evaluate_all,
    _consecutive_in_zone,
)
from stock_strategy_shared.schemas.strategy import DeltaEngineConfig

BASE_DATE = date(2026, 5, 17)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _obs(rank: int, score: float = 1.0, days_ago: int = 0) -> RankObservation:
    return RankObservation(
        run_date=BASE_DATE - timedelta(days=days_ago),
        rank=rank,
        composite_score=score,
    )


def _history(*ranks) -> list[RankObservation]:
    """Build observation list with most-recent rank first."""
    return [_obs(r, days_ago=i) for i, r in enumerate(ranks)]


# ── _consecutive_in_zone tests ────────────────────────────────────────────────

def test_consecutive_all_satisfy():
    obs = _history(5, 5, 5)
    result = _consecutive_in_zone(obs, lambda o: o.rank <= 10, required=3)
    assert result == 3


def test_consecutive_breaks_on_second():
    obs = _history(5, 15, 5)
    result = _consecutive_in_zone(obs, lambda o: o.rank <= 10, required=3)
    assert result == 1


def test_consecutive_fewer_than_required():
    obs = _history(5)
    result = _consecutive_in_zone(obs, lambda o: o.rank <= 10, required=3)
    assert result == 1


def test_consecutive_empty():
    result = _consecutive_in_zone([], lambda o: o.rank <= 10, required=3)
    assert result == 0


# ── evaluate_ticker tests ─────────────────────────────────────────────────────

def test_entry_confirmed():
    obs = _history(10, 10, 10)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "entry"


def test_entry_not_enough_days():
    obs = _history(10, 10)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "watch"


def test_entry_blocked_when_held():
    obs = _history(10, 10, 10)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=0.05,  # already held
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "hold"


def test_exit_confirmed():
    obs = _history(50, 50, 50)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=0.05,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "exit"


def test_exit_not_enough_days():
    obs = _history(50, 50)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=0.05,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "hold"


def test_exit_blocked_when_not_held():
    obs = _history(50, 50, 50)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,  # not held
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "watch"


def test_buffer_zone_held_stays_hold():
    # rank=30 is between entry_rank=25 and exit_rank=40
    obs = _history(30, 30, 30)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=0.05,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "hold"


def test_buffer_zone_new_ticker_is_watch():
    obs = _history(30, 30, 30)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "watch"


def test_no_observations_held():
    d = evaluate_ticker(
        "AAPL", [],
        current_weight=0.05,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "hold"


def test_no_observations_not_held():
    d = evaluate_ticker(
        "AAPL", [],
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "watch"


def test_capacity_blocks_confirmed_entry():
    obs = _history(10, 10, 10)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=True,
    )
    assert d.action == "watch"
    assert "capacity" in d.reason


def test_entry_rank_boundary_inclusive():
    # rank == entry_rank should count as entry zone (≤)
    obs = _history(25, 25, 25)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=None,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "entry"


def test_exit_rank_boundary_exclusive():
    # rank == exit_rank should NOT trigger exit (must be strictly >)
    obs = _history(40, 40, 40)
    d = evaluate_ticker(
        "AAPL", obs,
        current_weight=0.05,
        entry_rank=25, exit_rank=40, confirmation_days=3,
        portfolio_at_capacity=False,
    )
    assert d.action == "hold"


def test_reason_string_is_non_empty():
    """All code paths produce a non-empty reason string."""
    configs = [
        # (obs_ranks, held, at_capacity) → expected_action
        ([10, 10, 10], False, False),  # entry
        ([10, 10, 10], False, True),   # watch (capacity)
        ([10, 10, 10], True,  False),  # hold (held, entry zone)
        ([50, 50, 50], True,  False),  # exit
        ([30, 30, 30], True,  False),  # hold (buffer)
        ([30, 30, 30], False, False),  # watch (not held, buffer)
        ([],           False, False),  # watch (no obs)
        ([],           True,  False),  # hold (no obs, held)
    ]
    for ranks, held, at_cap in configs:
        obs = _history(*ranks) if ranks else []
        weight = 0.05 if held else None
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=weight,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=at_cap,
        )
        assert d.reason, f"Empty reason for action={d.action}, held={held}, at_cap={at_cap}"


# ── evaluate_all tests ────────────────────────────────────────────────────────

def test_cold_start_empty_portfolio():
    """No current holdings — confirmed entries up to max_positions are approved."""
    universe = {
        f"TICK{i}": _history(5, 5, 5)
        for i in range(5)
    }
    decisions = evaluate_all(
        universe=universe,
        current_portfolio={},
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=5,
    )
    entries = [d for d in decisions.values() if d.action == "entry"]
    assert len(entries) == 5


def test_stable_portfolio_no_changes():
    """All held stocks in buffer zone → all hold, no entries or exits."""
    tickers = ["AAPL", "MSFT", "GOOG"]
    universe = {t: _history(30, 30, 30) for t in tickers}
    portfolio = {t: 0.1 for t in tickers}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio=portfolio,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert all(d.action == "hold" for d in decisions.values())


def test_confirmed_exit_removes_held_ticker():
    universe = {"AAPL": _history(50, 50, 50)}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio={"AAPL": 0.1},
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert decisions["AAPL"].action == "exit"


def test_confirmed_entry_adds_new_ticker():
    universe = {"NVDA": _history(10, 10, 10)}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio={},
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert decisions["NVDA"].action == "entry"


def test_simultaneous_entry_and_exit():
    universe = {
        "NVDA": _history(10, 10, 10),  # confirmed entry
        "AAPL": _history(50, 50, 50),  # confirmed exit
    }
    portfolio = {"AAPL": 0.1}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio=portfolio,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert decisions["NVDA"].action == "entry"
    assert decisions["AAPL"].action == "exit"


def test_capacity_prevents_entry_when_full():
    """30 stocks held at capacity, 2 confirmed entries → both blocked."""
    held = {f"HELD{i:02d}": 0.033 for i in range(30)}
    universe = {t: _history(30) for t in held}  # all in buffer, no exits
    universe["NEW1"] = _history(10, 10, 10)
    universe["NEW2"] = _history(10, 10, 10)

    decisions = evaluate_all(
        universe=universe,
        current_portfolio=held,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert decisions["NEW1"].action == "watch"
    assert decisions["NEW2"].action == "watch"


def test_capacity_allows_entry_when_exit_creates_room():
    """30 held, 1 exits → 1 confirmed entry is approved (net stays 30)."""
    held = {f"HELD{i:02d}": 0.033 for i in range(29)}
    held["EXIT01"] = 0.033  # 30 total

    universe = {t: _history(30) for t in held}
    universe["EXIT01"] = _history(50, 50, 50)  # override: exits
    universe["NEW1"] = _history(10, 10, 10)    # confirmed entry

    decisions = evaluate_all(
        universe=universe,
        current_portfolio=held,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert decisions["EXIT01"].action == "exit"
    assert decisions["NEW1"].action == "entry"


def test_missing_ticker_force_exit():
    """Held ticker absent from universe → force-exit with delisted reason."""
    decisions = evaluate_all(
        universe={},  # universe is empty — AAPL is missing
        current_portfolio={"AAPL": 0.05},
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert "AAPL" in decisions
    assert decisions["AAPL"].action == "exit"
    assert "delisted" in decisions["AAPL"].reason.lower() or "missing" in decisions["AAPL"].reason.lower()


def test_decisions_cover_all_universe_tickers():
    universe = {"AAPL": _history(20), "MSFT": _history(35), "GOOG": _history(50)}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio={},
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert set(decisions.keys()) >= set(universe.keys())


def test_decisions_cover_held_tickers_not_in_universe():
    """Held tickers missing from universe must appear in result (force-exit)."""
    universe = {"AAPL": _history(20)}
    portfolio = {"AAPL": 0.05, "DELIST": 0.05}
    decisions = evaluate_all(
        universe=universe,
        current_portfolio=portfolio,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert "DELIST" in decisions
    assert decisions["DELIST"].action == "exit"


# ── DeltaEngineConfig schema tests ────────────────────────────────────────────

def test_delta_engine_config_defaults():
    cfg = DeltaEngineConfig()
    assert cfg.entry_rank == 25
    assert cfg.exit_rank == 40
    assert cfg.confirmation_days == 3
    assert cfg.max_positions == 30


def test_exit_rank_must_exceed_entry_rank():
    with pytest.raises(ValueError, match="exit_rank"):
        DeltaEngineConfig(entry_rank=40, exit_rank=40)


def test_exit_rank_equal_to_entry_rank_raises():
    with pytest.raises(ValueError):
        DeltaEngineConfig(entry_rank=30, exit_rank=25)


def test_exit_rank_greater_than_entry_rank_ok():
    cfg = DeltaEngineConfig(entry_rank=20, exit_rank=35)
    assert cfg.entry_rank == 20
    assert cfg.exit_rank == 35
