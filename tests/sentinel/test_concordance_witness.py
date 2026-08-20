from types import SimpleNamespace
import json
import math
import pytest

from sentinel.controller.concordance import (
    RecentLeadershipState,
    advance_recent_leadership,
    state_from_dict,
    state_to_dict,
)


def rows(n=30, *, recent_shift=0.0):
    return [SimpleNamespace(
        security_id=f"S{i:03d}",
        momentum=float(i),
        recent=float(n - i) + recent_shift,
    ) for i in range(n)]


def closes(n=30, value=100.0):
    return {f"S{i:03d}": value for i in range(n)}


def test_prior_membership_earns_next_close_return_only():
    state = RecentLeadershipState()
    state, first = advance_recent_leadership(
        session="S001", candidate_rows=rows(), eligible_universe_count=30,
        signal_closes=closes(), state=state)
    assert first.one_session_return == 0.0
    assert first.nav == 1.0
    selected = state.selected_recent
    current = closes()
    current[selected[0]] = 110.0
    state, second = advance_recent_leadership(
        session="S002", candidate_rows=rows(), eligible_universe_count=30,
        signal_closes=current, state=state)
    # 25-name floor: one +10% name and 24 flat names -> +0.4%.
    assert second.one_session_return == pytest.approx(0.004)
    assert second.nav == pytest.approx(1.004)


def test_missing_next_print_is_zero_weight_not_reweighted():
    state = RecentLeadershipState()
    state, _ = advance_recent_leadership(
        session="S001", candidate_rows=rows(), eligible_universe_count=30,
        signal_closes=closes(), state=state)
    current = closes()
    missing = state.selected_recent[0]
    del current[missing]
    changed = state.selected_recent[1]
    current[changed] = 110.0
    current_rows = [row for row in rows() if row.security_id != missing]
    _, decision = advance_recent_leadership(
        session="S002", candidate_rows=current_rows, eligible_universe_count=29,
        signal_closes=current, state=state)
    assert decision.one_session_return == pytest.approx(0.004)


def test_exact_20_40_session_returns_and_bounded_history():
    state = RecentLeadershipState()
    decisions = []
    for i in range(1, 45):
        px = 100.0 * (1.001 ** (i - 1))
        state, decision = advance_recent_leadership(
            session=f"S{i:03d}", candidate_rows=rows(),
            eligible_universe_count=30, signal_closes=closes(value=px),
            state=state)
        decisions.append(decision)
    assert decisions[20].recent_r20 == pytest.approx(1.001 ** 20 - 1)
    assert decisions[40].recent_r40 == pytest.approx(1.001 ** 40 - 1)
    assert len(state.nav_history) == 41
    assert len(state.session_history) == 41


def test_eligible_count_mismatch_refuses():
    with pytest.raises(ValueError, match="eligible population disagrees"):
        advance_recent_leadership(
            session="S001", candidate_rows=rows(), eligible_universe_count=31,
            signal_closes=closes(), state=RecentLeadershipState())


def test_duplicate_or_out_of_order_session_refuses():
    state, _ = advance_recent_leadership(
        session="S001", candidate_rows=rows(), eligible_universe_count=30,
        signal_closes=closes(), state=RecentLeadershipState())
    with pytest.raises(ValueError, match="strictly once"):
        advance_recent_leadership(
            session="S001", candidate_rows=rows(), eligible_universe_count=30,
            signal_closes=closes(), state=state)


def test_state_json_round_trip_is_strict():
    state, _ = advance_recent_leadership(
        session="S001", candidate_rows=rows(), eligible_universe_count=30,
        signal_closes=closes(), state=RecentLeadershipState())
    payload = json.loads(json.dumps(state_to_dict(state)))
    assert state_from_dict(payload) == state
    payload["junk"] = 1
    with pytest.raises(ValueError):
        state_from_dict(payload)
