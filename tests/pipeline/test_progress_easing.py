"""The /runs/progress bar eases the coarse real milestones into a smooth 5-point
cadence (5, 10, 15, 20 …). Cosmetic only — _set_pct milestones and the
computation are unchanged; this just verifies the display interpolation.
"""
import time

from app.main import (
    _eased_pct, _current_progress, _STEP_MILESTONES,
    _CREEP_INTERVAL_SECS, _CREEP_STEP,
)


def _at(step, real, elapsed_steps):
    """Pretend we reached milestone `real` `elapsed_steps` creep-intervals ago."""
    _current_progress.clear()
    _current_progress.update({
        "step": step, "real": real, "pct": real,
        "ts": time.monotonic() - elapsed_steps * _CREEP_INTERVAL_SECS,
    })


def test_always_a_multiple_of_five():
    for real in (2, 18, 30, 58, 68, 84, 91, 100):
        for elapsed in (0, 1, 3, 50):
            _at("calc_factors", real, elapsed)
            assert _eased_pct() % _CREEP_STEP == 0


def test_creeps_toward_next_milestone_but_not_onto_it():
    # real=18 → anchor 20, next milestone 30 → display caps at 25, never 30.
    _at("calc_factors", 18, elapsed_steps=100)
    assert _eased_pct() == 25
    # Only when the work actually reaches 30 does the bar show 30.
    _at("calc_factors", 30, elapsed_steps=0)
    assert _eased_pct() == 30


def test_advances_with_time():
    _at("calc_factors", 2, elapsed_steps=0)
    first = _eased_pct()                 # anchor 0
    _at("calc_factors", 2, elapsed_steps=2)
    later = _eased_pct()                 # +2 steps → 10
    assert later > first
    assert later <= 15                   # ceiling for the 2→18 gap (next anchor 20)


def test_monotonic_non_decreasing_across_a_run():
    seq = [(2, 0), (2, 3), (18, 0), (18, 9), (30, 0), (58, 0),
           (68, 0), (84, 0), (91, 0), (91, 3), (100, 0)]
    prev = -1
    for real, elapsed in seq:
        _at("calc_factors", real, elapsed)
        cur = _eased_pct()
        assert cur >= prev, f"went backwards at real={real}: {cur} < {prev}"
        prev = cur
    assert prev == 100


def test_caps_at_100():
    _at("calc_factors", 100, elapsed_steps=100)
    assert _eased_pct() == 100


def test_unknown_step_returns_real():
    _at("something_else", 42, elapsed_steps=10)
    assert _eased_pct() == 42
    _current_progress.clear()
