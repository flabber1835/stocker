import math
import pytest
from sentinel.controller.recent_leadership import (
    LeadershipCandidate,
    advance_shadow_nav,
    equal_weight_next_close_return,
    leadership_population_size,
    select_leadership,
    session_return,
)


def test_population_size_is_10_percent_with_25_floor():
    assert leadership_population_size(250) == 25
    assert leadership_population_size(251) == 26
    assert leadership_population_size(1001) == 101


def test_recent_and_established_use_same_population_and_identity_tiebreak():
    rows = [LeadershipCandidate(f"{i:03d}", float(i // 2), float((99-i)//2)) for i in range(100)]
    sel = select_leadership(rows)
    assert len(sel.established) == len(sel.recent) == 25
    assert sel.established[0] > sel.established[-1]


def test_missing_print_keeps_weight_and_earns_zero_not_reweight():
    ids = ("A", "B")
    r = equal_weight_next_close_return(ids, {"A": 100.0, "B": 100.0}, {"A": 110.0})
    assert r == pytest.approx(0.05)  # +10% and 0%, arithmetic 50/50


def test_prior_close_membership_price_return_and_nav_compound():
    r = equal_weight_next_close_return(("A", "B"), {"A": 100.0, "B": 200.0}, {"A": 102.0, "B": 198.0})
    assert r == pytest.approx(0.005)
    assert advance_shadow_nav(1.0, r) == pytest.approx(1.005)


def test_session_return_uses_exact_session_gap():
    nav = [1.0]
    for _ in range(40):
        nav.append(nav[-1] * 1.001)
    assert session_return(nav, 20) == pytest.approx(nav[-1] / nav[-21] - 1)
    assert session_return(nav, 40) == pytest.approx(nav[-1] / nav[-41] - 1)
