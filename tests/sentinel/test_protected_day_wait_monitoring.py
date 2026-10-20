"""Asynchronous resting orders must stay observable without masking failures."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import alert_service
from sentinel.automation import service as module
from sentinel.automation.model import (
    AutomationConfig, ControlBinding, CycleState, ExecuteResult,
    ProtectedDayWait, protected_day_wait,
)
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.execution.contract import OrderTerms
from sentinel.operational_status import FAIL, OK, WARN
from sentinel.panel import model, sources
from tests.sentinel.test_automation_service_fault_paths import scheduled_record


NOW = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)


def wait_payload(now=NOW, *, plan_id="retained-plan"):
    from sentinel.feed import calendar
    _, closed = calendar.session_window("2026-10-20")
    return {"schema": "sentinel.protected-day-wait/1", "plan_id": plan_id,
        "effective_session": "2026-10-20", "observation_id": 12,
        "observed_at": now.isoformat(), "deadline": (closed + timedelta(minutes=10)).isoformat(),
        "deployment": ["fault-lab", "alpaca-paper", "synthetic-account", 1],
        "basis_sha256": "b" * 64, "projection_fingerprint": "c" * 64,
        "policy_sha256": "d" * 64, "reserved_cash": "200",
        "commands": [{"client_key": "sntl-existing", "broker_order_id": "native-existing",
            "security_id": "security-a", "side": "BUY", "state": "ACKNOWLEDGED",
            "remaining_quantity": "2", "limit_price": "100",
            "order_terms": OrderTerms("limit", "day", Decimal("100")).to_dict()}]}


@pytest.mark.parametrize("mutation", ["unknown", "market", "terms", "reservation", "duplicate", "deadline"])
def test_resting_wait_requires_positive_exact_terms_and_fixed_deadline(mutation):
    raw = wait_payload()
    if mutation == "unknown": raw["commands"][0]["state"] = "UNKNOWN"
    elif mutation == "market": raw["commands"][0]["order_terms"] = OrderTerms().to_dict()
    elif mutation == "terms": raw["commands"][0]["limit_price"] = "99"
    elif mutation == "reservation": raw["reserved_cash"] = "201"
    elif mutation == "duplicate": raw["commands"] *= 2
    else: raw["deadline"] = (NOW + timedelta(days=1)).isoformat()
    assert protected_day_wait(raw, now=NOW) is None


def test_resting_wait_never_earns_freshness_from_the_reader():
    raw = wait_payload()
    assert protected_day_wait(raw, now=NOW) is not None
    assert protected_day_wait(raw, now=NOW - timedelta(microseconds=1)) is None
    assert protected_day_wait(raw, now=NOW + timedelta(minutes=10, seconds=1)) is None
    assert protected_day_wait(raw, now=NOW, plan_id="another-plan") is None
    assert protected_day_wait(raw, now=NOW, effective_session="2026-10-21") is None


def runner(monkeypatch, *, known=False, failure=None, duration=95, ready=False):
    cfg = AutomationConfig(lease_seconds=12, heartbeat_seconds=3, control_poll_seconds=3,
        retry_base_seconds=20, retry_max_seconds=120, maximum_clock_skew_seconds=1000000)
    cycle, permit = scheduled_record(cfg, CycleState.RETRY_WAIT, decision_session=date(2026, 10, 19))
    clock = [cycle.execute_at]
    current = [cycle.model_copy(update={"plan_id": "retained-plan", "next_wake_at": clock[0],
        "diagnostic": {"retry_phase": "RECOVER", "phase_attempt_count": 0}})]
    binding = ControlBinding(**{name: getattr(cycle, name) for name in
        ("deployment_id", "broker", "broker_account_id", "takeover_epoch", "certificate_sha256",
         "rollout_mode", "rollout_version", "config_sha256")})
    control = SimpleNamespace(enabled=True, kill_switch_engaged=False, generation=1,
        config_sha256=cfg.fingerprint, binding=binding)
    calls, progress = [], []
    service = RecoveryAutomationService(config=cfg, holder_id=permit.holder_id,
        refresh=None, prepare=None, recover=None, execute=None)
    monkeypatch.setattr(module.store, "load_control", lambda *_a, **_k: control)
    monkeypatch.setattr(module.store, "acquire_lease", lambda *_a, **_k: permit)
    monkeypatch.setattr(module.store, "require_leader", lambda _c, p: p)
    monkeypatch.setattr(module.store, "heartbeat_lease", lambda _c, *, permit, **_k: permit)
    monkeypatch.setattr(module.store, "register_instance", lambda _c, **fields: progress.append(fields))
    monkeypatch.setattr(module.store, "oldest_nonterminal_other_generation_cycle", lambda *_a, **_k: None)
    monkeypatch.setattr(module.store, "blocked_cycle_for_generation", lambda *_a, **_k: None)
    monkeypatch.setattr(module.store, "oldest_unresolved_transport_cycle", lambda *_a, **_k: None)
    monkeypatch.setattr(module.store, "latest_cycle", lambda *_a, **_k: current[0])
    monkeypatch.setattr(module.store, "create_cycle", lambda *_a, **_k: current[0])
    monkeypatch.setattr(module.integrity, "validate_cycle_lineage", lambda *_a: None)
    monkeypatch.setattr(service, "_assert_clock_skew", lambda **fields: fields["now"])

    def transition(_conn, *, to_state, **fields):
        fields.pop("permit", None); fields.pop("cycle_id", None)
        current[0] = current[0].model_copy(update={"state": to_state, "updated_at": clock[0], **fields})
        return current[0]
    monkeypatch.setattr(module.store, "transition_cycle", transition)

    async def invoke(phase, context, **_fields):
        assert phase == "RECOVER"
        calls.append(clock[0])
        clock[0] += timedelta(seconds=duration)
        if failure is not None: raise failure
        if ready:
            return ExecuteResult(disposition="READY_TO_EXECUTE", last_clean_reconciliation_id="12",
                failure_code="PROTECTED_COHORT_READY", failure_detail="existing protected cohort is ready")
        return ExecuteResult(disposition="RECONCILE",
            failure_code="PROTECTED_DAY_ORDERS_WORKING" if known else "COMMANDS_IN_FLIGHT",
            failure_detail="working orders", diagnostic={"protected_day_wait": wait_payload(clock[0])} if known else {})
    monkeypatch.setattr(service, "_invoke_phase", invoke)
    return service, current, permit, clock, calls, progress


def test_persistent_loop_uses_completion_clock_after_long_recovery(monkeypatch):
    service, current, permit, clock, calls, progress = runner(monkeypatch)
    original = clock[0]
    async def sleep(seconds): clock[0] += timedelta(seconds=seconds)
    connection = lambda: SimpleNamespace(rollback=lambda: None, close=lambda: None)
    asyncio.run(service.run(connection, stop=SimpleNamespace(is_set=lambda: False),
        clock=lambda: clock[0], sleep=sleep, max_ticks=5))
    assert calls == [original]
    assert current[0].next_wake_at == original + timedelta(seconds=95 + 20)
    assert current[0].next_wake_at > clock[0]
    assert progress[-1]["next_wake_at"] > clock[0]


def test_known_day_wait_does_not_consume_failure_budget_or_publish_an_alert(monkeypatch):
    service, current, permit, clock, calls, _progress = runner(monkeypatch, known=True)
    current[0] = current[0].model_copy(update={"diagnostic": {
        "retry_phase": "RECOVER", "phase_attempt_count": 999}})
    conn = SimpleNamespace(rollback=lambda: None)
    for _ in range(10):
        result = asyncio.run(service._run_recover(conn, now=clock[0], cycle=current[0],
            permit=permit, clock=lambda: clock[0]))
        assert result.action is module.TickAction.WAITING
        assert result.cycle.state is CycleState.RETRY_WAIT
        assert result.cycle.next_wake_at == clock[0] + timedelta(seconds=3)
        assert result.cycle.failure_code is None and result.cycle.failure_detail is None
        assert "phase_attempt_count" not in result.cycle.diagnostic
        assert "notifier_action" not in result.cycle.diagnostic
        clock[0] = result.cycle.next_wake_at
    assert len(calls) == 10 and current[0].plan_id == "retained-plan"


def test_lock_failure_is_never_reclassified_as_a_known_order_wait(monkeypatch):
    failure = module.TransientInfrastructureFailure("local database lock unavailable")
    service, current, permit, clock, *_ = runner(monkeypatch, known=True, failure=failure)
    result = asyncio.run(service._run_recover(SimpleNamespace(rollback=lambda: None), now=clock[0],
        cycle=current[0], permit=permit, clock=lambda: clock[0]))
    assert result.action is module.TickAction.RETRY_SCHEDULED
    assert result.cycle.failure_code == "TransientInfrastructureFailure"
    assert "lock unavailable" in result.cycle.failure_detail
    assert "exception_fingerprint" in result.cycle.diagnostic
    assert "protected_day_wait" not in result.cycle.diagnostic


def test_recovery_completion_rechecks_original_submission_cutoff(monkeypatch):
    service, current, permit, clock, *_ = runner(monkeypatch, ready=True, duration=600)
    result = asyncio.run(service._run_recover(SimpleNamespace(rollback=lambda: None), now=clock[0],
        cycle=current[0], permit=permit, clock=lambda: clock[0]))
    assert result.cycle.state is CycleState.SUPERSEDED
    assert result.cycle.failure_code == "MAX_EXECUTION_LATENESS_EXCEEDED"
    assert result.cycle.execute_at == current[0].execute_at


def test_positive_cohort_continuation_is_bounded_pending_not_a_failure(monkeypatch):
    service, current, permit, clock, *_ = runner(monkeypatch, ready=True, duration=0)
    result = asyncio.run(service._run_recover(SimpleNamespace(rollback=lambda: None), now=clock[0],
        cycle=current[0], permit=permit, clock=lambda: clock[0]))
    assert result.cycle.failure_code is None and result.cycle.failure_detail is None
    assert result.cycle.diagnostic["continuation_reason"]["code"] == "PROTECTED_COHORT_READY"
    cycle = {**result.cycle.model_dump(), "state": result.cycle.state.value, "retry_phase": "EXECUTE",
             "original_execution_deadline_at": result.cycle.diagnostic["original_execution_deadline_at"]}
    row = model.automation_cycle_row(installed=True, enabled=True,
        **{key: value for key, value in cycle.items() if key in sources._AUTOMATION_CYCLE_ROW_FIELDS})
    assert row.effective_status(clock[0]) == WARN
    original_deadline = service._latest_new_execution_at(result.cycle)
    assert original_deadline < result.cycle.execution_close_at
    assert row.effective_status(original_deadline + timedelta(seconds=1)) == FAIL
    assert sources._cycle_recovery(cycle).deadline == original_deadline
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=cycle)
    assert steps[4].effective_status(clock[0]) == WARN
    assert steps[4].value == "READY TO CONTINUE"
    assert steps[4].effective_status(original_deadline + timedelta(seconds=1)) == FAIL
    for invalid in (None, result.cycle.execution_close_at, result.cycle.execution_open_at - timedelta(seconds=1)):
        bad = {**cycle, "original_execution_deadline_at": invalid}
        assert model.automation_cycle_row(installed=True, enabled=True,
            **{key: value for key, value in bad.items() if key in sources._AUTOMATION_CYCLE_ROW_FIELDS}).effective_status(clock[0]) == FAIL


def test_panel_known_day_wait_is_bounded_pending_and_never_completed():
    raw = wait_payload()
    cycle = {"cycle_id": "cycle-a", "state": "RETRY_WAIT", "effective_session": "2026-10-20",
        "plan_id": raw["plan_id"], "retry_phase": "RECOVER", "protected_day_wait": raw,
        "updated_at": NOW, "next_wake_at": NOW + timedelta(seconds=3)}
    row = model.automation_cycle_row(installed=True, enabled=True,
        **{key: value for key, value in cycle.items() if key in sources._AUTOMATION_CYCLE_ROW_FIELDS})
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=cycle)
    assert row.effective_status(NOW) == WARN
    assert steps[4].effective_status(NOW) == WARN
    assert steps[4].value == "DAY ORDERS WORKING"
    assert steps[5].effective_status(NOW) == WARN
    assert steps[6].value == "NOT REACHED"
    assert row.effective_status(NOW + timedelta(minutes=11)) == FAIL
    assert steps[5].effective_status(NOW + timedelta(minutes=11)) == FAIL
    missed = model.automation_step_rows(installed=True, enabled=True,
        cycle={**cycle, "new_submission_cutoff_expired": True,
               "unsent_actionable_deltas": [{"security_id": "missing-name", "remaining": "10"}]})
    assert missed[4].effective_status(NOW) == FAIL
    assert missed[4].value == "MISSED UNSENT BUYs"


def test_panel_only_accepts_positively_matched_reservations_and_keeps_margin_red():
    values = dict(available=True, broker="alpaca", account_id="synthetic-account",
        expected_account_id="synthetic-account", status="ACTIVE", flags={}, equity="10000",
        cash="1000", buying_power="800", multiplier="1", observed_at=NOW)
    assert model.alpaca_account_row(**values).effective_status(NOW) == FAIL
    assert model.alpaca_account_row(**values, matched_protected_reservation=wait_payload()).effective_status(NOW) == OK
    for changed in ({"multiplier": "2"}, {"buying_power": "700"}, {"buying_power": "1200"},
                    {"flags": {"trading_blocked": True}}, {"observed_at": NOW + timedelta(seconds=61)}):
        assert model.alpaca_account_row(**{**values, **changed},
            matched_protected_reservation=wait_payload()).effective_status(NOW) == FAIL
    assert model.alpaca_account_row(**values, matched_protected_reservation=wait_payload()).effective_status(
        NOW + timedelta(minutes=11)) == FAIL


def test_expired_working_order_observation_is_an_external_health_incident():
    assert alert_service._active_incident(SimpleNamespace(policy_state="PROTECTED_DAY_WAIT_EXPIRED",
        enabled=True, kill_switch_engaged=False))


@pytest.mark.parametrize("fault", [None, "unknown", "different_plan", "native_terms", "replacement", "binding", "incomplete"])
@pytest.mark.parametrize("ready", [False, True])
def test_reservation_reader_joins_actual_commands_and_canonical_observation(monkeypatch, fault, ready):
    from dataclasses import replace
    from sentinel.execution import journal
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
    from sentinel.execution.states import CommandState

    raw = wait_payload()
    cycle = {"plan_id": raw["plan_id"], "effective_session": "2026-10-20", "protected_day_wait": raw}
    dep = DeploymentIdentity(*raw["deployment"])
    identity = CommandIdentity(dep, raw["plan_id"], "security-a")
    command = Command(identity, BrokerInstrument("security-a", "AAA", "asset-a"), Side.BUY,
        Decimal("2"), state=CommandState.ACKNOWLEDGED, broker_order_id="native-existing",
        order_terms=OrderTerms("limit", "day", Decimal("100")))
    raw["commands"][0]["client_key"] = command.client_key
    if ready:
        cohort = {key: value for key, value in raw.items() if key != "deadline"}
        cohort["schema"] = "sentinel.protected-cohort-continuation/1"
        cycle = {"plan_id": raw["plan_id"], "effective_session": "2026-10-20", "protected_cohort": cohort,
            "retry_phase": "EXECUTE", "continuation_reason": {"code": "PROTECTED_COHORT_READY"},
            "execution_close_at": datetime.fromisoformat(raw["deadline"]) - timedelta(minutes=10)}
    order = {"client_key": command.client_key, "broker_order_id": command.broker_order_id,
        "security_id": command.security_id, "side": "BUY", "state": "ACKNOWLEDGED",
        "quantity": "2", "filled_quantity": "0", "order_terms": command.order_terms.to_dict()}
    payload = {"completeness": "COMPLETE", "account_id": dep.broker_account_id,
        "observed_at": NOW.isoformat(), "orders": [order]}
    binding = tuple(raw["deployment"])
    if fault == "unknown": command = replace(command, state=CommandState.UNKNOWN)
    elif fault == "different_plan": command = replace(command, identity=replace(identity, plan_id="other"))
    elif fault == "native_terms": order["order_terms"] = OrderTerms().to_dict()
    elif fault == "replacement": order["external_replacement"] = True
    elif fault == "binding": binding = (*binding[:2], "another-account", binding[3])
    elif fault == "incomplete": payload["completeness"] = "PARTIAL"

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_a): pass
        def execute(self, query): self.query = query
        def fetchone(self): return binding if "account_binding" in self.query else (12, "RUNNING")
    conn = SimpleNamespace(cursor=Cursor)
    monkeypatch.setattr(journal, "load_observation_payload", lambda *_a: payload)
    monkeypatch.setattr(journal, "load_commands", lambda *_a: [command])
    result = sources._matched_resting_reservation(conn,
        account={"account_id": dep.broker_account_id, "observed_at": NOW},
        cycle=cycle, now=NOW)
    assert bool(result) is (fault is None)


def test_removed_completion_clock_guard_is_detected(monkeypatch):
    monkeypatch.setattr(module.AutomationService, "_completed_at", staticmethod(lambda now, clock: now))
    with pytest.raises(AssertionError):
        test_persistent_loop_uses_completion_clock_after_long_recovery(monkeypatch)


def test_removed_exact_reservation_match_is_detected(monkeypatch):
    import inspect
    text = inspect.getsource(model.alpaca_account_row)
    guard = 'and abs((cash_value - buying_power_value) - reservation.reserved_cash) <= Decimal("1.00"))'
    assert guard in text
    namespace = {}
    exec(compile(text.replace(guard, 'and True)'), 'removed-reservation-guard', 'exec'), model.__dict__, namespace)
    monkeypatch.setattr(model, "alpaca_account_row", namespace["alpaca_account_row"])
    with pytest.raises(AssertionError):
        test_panel_only_accepts_positively_matched_reservations_and_keeps_margin_red()
