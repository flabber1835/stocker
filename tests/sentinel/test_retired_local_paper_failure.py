"""A retired failure stays visible without impersonating the active generation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import inspect

import pytest

from sentinel import informational_paper_mirror as mirror, local_paper
from sentinel.automation import health, store
from sentinel.execution import account_status
from sentinel.feed import readers as publication
from sentinel.panel import model, sources


@pytest.fixture
def case(monkeypatch):
    now = datetime.now(timezone.utc)
    control = SimpleNamespace(enabled=True, kill_switch_engaged=False, generation=46)
    live = SimpleNamespace(healthy=True, operational_ready=True, control_generation=46,
        leader_active=True, service_heartbeat_fresh=True, authority_verdict="PASS",
        authority_lifecycle_current=True, broker_outcome_unresolved=1)
    account = dict(broker="alpaca", account_id="PAfixture", status="ACTIVE", flags={},
        equity="50000", cash="10000", buying_power="8959.27", multiplier="1", observed_at=now)
    old = dict(cycle_id="old-blocked", state="BLOCKED", decision_session="2026-10-21",
        failure_code="NonRetryableCallbackRefused", failure_detail="old source fingerprint")
    current = []
    monkeypatch.setattr(local_paper, "require_bound_account", lambda c: True)
    monkeypatch.setattr(store, "load_control", lambda c: control)
    monkeypatch.setattr(health, "read_health", lambda c: live)
    monkeypatch.setattr(sources, "_informational_mirror_count", lambda c: 1)
    monkeypatch.setattr(sources, "_latest_automation_cycle",
        lambda c, *, generation=None: old if generation is None else next(iter(current), None))
    monkeypatch.setattr(sources, "_latest_account_evidence", lambda c: account)
    monkeypatch.setattr(sources, "_bound_account_id", lambda c: "PAfixture")
    monkeypatch.setattr(account_status, "recorded_reservation", lambda *a, **k: {"reserved_cash": "1040.73", "order_count": 1})
    monkeypatch.setattr(publication, "current", lambda c: SimpleNamespace(version=4))
    monkeypatch.setattr(publication, "frontier", lambda *a: "2026-10-21")
    monkeypatch.setattr(mirror, "require_transport_permitted", lambda *a, **k: {"status": mirror.NO_UNIT_CHANGE})
    def row():
        return sources._dual_paper_row(None, informational_paper_mirror=mirror,
            publication=publication, feed_store=None)
    return SimpleNamespace(control=control, health=live, account=account,
        current=current, row=row, now=now)


def test_retired_error_is_visible_amber_without_claiming_completion(case):
    row = case.row()
    assert row.status == model.WARN and row.effective_status(case.now) == model.WARN
    assert "PRIOR CYCLE FAILED" in row.value and "NOT VERIFIED" in row.value
    assert "old-blocked" in row.detail and "old source fingerprint" in row.detail
    assert "no completed reconciliation or qualification is claimed" in row.detail
    assert "CLEAN" not in row.value and "SCHEDULED" not in row.value


def test_any_current_or_adopted_cycle_keeps_terminal_failure_red(case):
    case.current.append(dict(cycle_id="adopted-or-current"))
    assert case.row().status == model.FAIL


@pytest.mark.parametrize("field,value", [("enabled", False), ("kill_switch_engaged", True)])
def test_disabled_or_killed_policy_cannot_turn_red_into_history(case, field, value):
    setattr(case.control, field, value)
    assert case.row().status == model.FAIL


@pytest.mark.parametrize("field,value", [("healthy", False), ("operational_ready", False),
    ("control_generation", 45), ("leader_active", False), ("service_heartbeat_fresh", False),
    ("authority_verdict", "FAIL"), ("authority_lifecycle_current", False), ("broker_outcome_unresolved", 2)])
def test_live_authority_health_and_outcome_guards_remain(case, field, value):
    setattr(case.health, field, value)
    assert case.row().status == model.FAIL


@pytest.mark.parametrize("field,value", [("account_id", "foreign"), ("multiplier", "2"),
    ("cash", "-1"), ("buying_power", "100"), ("flags", {"trading_blocked": True}),
    ("observed_at", datetime(2026, 1, 1, tzinfo=timezone.utc))])
def test_fresh_native_account_guards_remain(case, field, value):
    case.account[field] = value
    assert case.row().status == model.FAIL


def test_normal_release_keeps_prior_failure_red(case, monkeypatch):
    monkeypatch.setattr(local_paper, "require_bound_account", lambda c: False)
    assert case.row().status == model.FAIL


def test_native_hold_and_global_mirror_integrity_are_required(case, monkeypatch):
    monkeypatch.setattr(account_status, "recorded_reservation", lambda *a, **k: None)
    assert case.row().status == model.FAIL
    monkeypatch.setattr(account_status, "recorded_reservation", lambda *a, **k: {"reserved_cash": "1040.73", "order_count": 1})
    monkeypatch.setattr(mirror, "require_transport_permitted", lambda *a, **k: {"status": mirror.MISMATCH})
    assert case.row().status == model.FAIL and "MISMATCH" in case.row().value
    def pending(*a, **k):
        raise mirror.InformationalPaperMirrorPending("due unit evidence missing")
    monkeypatch.setattr(mirror, "require_transport_permitted", pending)
    assert case.row().status == model.FAIL
    monkeypatch.setattr(publication, "current", lambda c: None)
    assert case.row().status == model.UNKNOWN


def test_current_generation_guard_falsifier_is_detected(case, monkeypatch):
    source = inspect.getsource(sources._retired_local_paper_failure)
    needle = "_latest_automation_cycle(conn, generation=control.generation) is not None"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "False"), "<removed-current-cycle-guard>", "exec"),
        sources._retired_local_paper_failure.__globals__, namespace)
    monkeypatch.setattr(sources, "_retired_local_paper_failure", namespace["_retired_local_paper_failure"])
    with pytest.raises(AssertionError):
        test_any_current_or_adopted_cycle_keeps_terminal_failure_red(case)
