"""The private timing fixture cannot manufacture a protected-policy PASS."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.automation.model import CycleState, ExecuteDisposition, ExecuteResult
from sentinel.execution import journal, protected_limits
from tools import opening_gateway_qualification as gateway


POST = "https://paper-api.alpaca.markets/v2/orders"


@pytest.fixture(autouse=True)
def clean_policy(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)


def provider(*, worst=False, cash="1000"):
    now = datetime.now(timezone.utc)
    http = gateway.LocalAlpaca(account="local-only", cash=cash,
        assets={"AAA": {"id": "asset-AAA", "symbol": "AAA", "security_id": "SEC-AAA", "price": D(100)}},
        window=lambda: (now-timedelta(minutes=1), now+timedelta(hours=1)),
        forbid_quotes=True, marketable_limit_fills=worst)
    http.started = gateway.time.monotonic()
    return http


def body(**changes):
    return {"symbol": "asset-AAA", "qty": "2", "side": "buy", "type": "limit",
        "time_in_force": "day", "order_class": "simple", "extended_hours": False,
        "client_order_id": "key-1", "limit_price": "90", **changes}


def result(disposition, **changes):
    return ExecuteResult(disposition=ExecuteDisposition(disposition),
        last_clean_reconciliation_id="private-clean", **changes)


def test_nonmarketable_day_order_remains_working_with_real_cash_reservation():
    http = provider()
    row = http.post(POST, body()).json()
    assert row["status"] == "new" and row["filled_qty"] == "0" and row["filled_avg_price"] is None
    assert http.cash == 1000 and http.positions == {} and http.events == []
    account = http.get("https://paper-api.alpaca.markets/v2/account", {}).json()
    assert D(account["cash"]) == 1000 and D(account["buying_power"]) == 820
    assert http.get(POST, {"status": "open"}).json() == [row]
    assert http.get(POST, {"status": "closed"}).json() == []
    assert http.get(POST, {"status": "all"}).json() == [row]
    with pytest.raises(gateway.QualificationRefused, match="UNRESERVED_CASH"):
        http.post(POST, body(client_order_id="next", qty="10"))
    assert http.cash == 1000 and len(http.orders) == 1


@pytest.mark.parametrize("worst,limit,fill", [(False, "110", "100"), (True, "110", "110"),
                                            (True, "90", "90")])
def test_marketable_scenario_uses_explicit_native_or_worst_limit_economics(worst, limit, fill):
    http = provider(worst=worst)
    row = http.post(POST, body(limit_price=limit)).json()
    assert row["status"] == "filled" and row["filled_qty"] == "2"
    assert D(row["filled_avg_price"]) == D(fill)
    assert http.cash == D(1000) - 2*D(fill) and http.positions == {"asset-AAA": D(2)}
    assert len(http.events) == 1 and D(http.events[0]["price"]) == D(fill)
    assert D(http.events[0]["net_amount"]) == -2*D(fill)
    assert http.get("https://paper-api.alpaca.markets/v2/account", {}).json()["buying_power"] == str(http.cash)


@pytest.mark.parametrize("changes", [
    {"qty": "NaN"}, {"qty": "Infinity"}, {"qty": "-1"}, {"qty": "0"}, {"qty": "1.5"}, {"qty": 2},
    {"side": "hold"}, {"side": "sell"}, {"type": "stop"}, {"type": "market"},
    {"time_in_force": "ioc"}, {"order_class": "bracket"}, {"extended_hours": True}, {"extended_hours": "false"},
    {"limit_price": "NaN"}, {"limit_price": "Infinity"}, {"limit_price": "0"}, {"limit_price": "-1"},
    {"limit_price": "1.001"}, {"limit_price": D(90)}, {"symbol": "unbound"}, {"notional": "100"},
])
def test_invalid_native_payload_cannot_change_simulated_finances(changes):
    http = provider()
    with pytest.raises(gateway.QualificationRefused):
        http.post(POST, body(**changes))
    assert http.cash == 1000 and http.orders == {} and http.positions == {} and http.events == []


@pytest.mark.parametrize("cash", ["-1", "NaN", "Infinity", True, 1000.0])
def test_invalid_initial_cash_refuses(cash):
    with pytest.raises(gateway.QualificationRefused, match="INVALID_CASH"):
        provider(cash=cash)


def test_protected_fixture_forbids_quote_requests_and_cross_host_routes():
    http = provider()
    with pytest.raises(gateway.QualificationRefused, match="QUOTE_GET_FORBIDDEN"):
        http.get("https://data.alpaca.markets/v2/stocks/quotes/latest", {"feed": "iex", "symbols": "AAA"})
    with pytest.raises(gateway.QualificationRefused, match="USED_QUOTE_GET"):
        gateway.require_no_quotes(http)
    with pytest.raises(gateway.QualificationRefused, match="WRONG_ENDPOINT_HOST"):
        http.get("https://data.alpaca.markets/v2/account", {})
    with pytest.raises(gateway.QualificationRefused, match="UNEXPECTED_MUTATION"):
        http.post("https://data.alpaca.markets/v2/orders", body())


def test_provider_roundtrip_cannot_reset_original_timing_budget():
    http = provider()
    state = http.state()
    state["started"] += 1
    with pytest.raises(gateway.QualificationRefused, match="RESET_QUALIFICATION_CLOCK"):
        http.restore(state)
    http.post(POST, body())
    state = http.state()
    state["first_order_seconds"] = 0
    with pytest.raises(gateway.QualificationRefused, match="RESET_QUALIFICATION_CLOCK"):
        http.restore(state)


@pytest.mark.parametrize("policy,cap", [(None, None), ("", ""), (None, "100"),
                                      (protected_limits.PROTECTED_MODE, None),
                                      (protected_limits.PROTECTED_MODE, ""),
                                      (protected_limits.PROTECTED_MODE, "501")])
def test_gateway_requires_explicit_selected_policy_and_usable_cap(monkeypatch, policy, cap):
    if policy is not None:
        monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", policy)
    if cap is not None:
        monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", cap)
    with pytest.raises((gateway.QualificationRefused, protected_limits.TargetProjectionRefused)):
        gateway.require_protected_policy()


def test_gateway_uses_exact_explicit_protected_policy(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    assert gateway.require_protected_policy() == protected_limits.ProtectedLimitPolicy(100)


@pytest.mark.parametrize("phase", ["EXECUTE", "RECOVER", "PREFLIGHT"])
@pytest.mark.parametrize("disposition", ["BLOCKED", "RETRY", "SUPERSEDED"])
def test_returned_refusal_never_becomes_later_success(phase, disposition):
    with pytest.raises(gateway.QualificationRefused, match="CALLBACK_REFUSED"):
        gateway.require_callback_progress(result(disposition), phase=phase)


@pytest.mark.parametrize("changes", [
    {"diagnostic": {"execution": {"refused": {"SEC-AAA": "refused"}}}},
    {"failure_code": "TERMINAL_COMMAND_REFUSAL"},
])
def test_apparent_reconcile_cannot_hide_financial_refusal(changes):
    with pytest.raises(gateway.QualificationRefused, match="FINANCIAL_REFUSAL"):
        gateway.require_callback_progress(result("RECONCILE", **changes), phase="EXECUTE")


@pytest.mark.parametrize("state", ["SEND_PENDING", "UNKNOWN", "REJECTED", "CANCELLED", "CANCEL_PENDING"])
def test_canonical_journal_uncertainty_stops_the_campaign(monkeypatch, state):
    seen = []
    def commands(conn, deployment, *, plan_id):
        seen.append((conn, deployment, plan_id))
        return [SimpleNamespace(state=SimpleNamespace(value=state))]
    monkeypatch.setattr(journal, "load_commands", commands)
    with pytest.raises(gateway.QualificationRefused, match="UNRESOLVED_OR_REFUSED_COMMAND"):
        gateway.require_command_progress("private-connection", deployment="deployment", plan_id="plan")
    assert seen == [("private-connection", "deployment", "plan")]


def campaign(monkeypatch, *, recoveries=("READY_TO_EXECUTE", "SUCCEEDED"), asset_count=2,
             times=(10, 50, 70, 100), send=True, execute_result=None, command_state="FILLED"):
    clock = [0.0]
    monkeypatch.setattr(gateway.time, "monotonic", lambda: clock[0])
    http = provider(worst=True)
    rows, calls, transitions, moments = iter(recoveries), [], [], iter(times)
    monkeypatch.setattr(journal, "load_commands", lambda *_a, **_k:
        [SimpleNamespace(state=SimpleNamespace(value=command_state))] if http.orders else [])
    def transition(_conn, **values):
        transitions.append(values)
        return SimpleNamespace(cycle_id="cycle", state=values["to_state"])
    monkeypatch.setattr(gateway, "transition_for_callback", transition)
    def callback(phase, _stage, _body, *, current_cycle):
        calls.append((phase, current_cycle.state))
        clock[0] = next(moments)
        if phase == "EXECUTE":
            if send:
                http.post(POST, body(qty="1", client_order_id=f"key-{len(http.orders)}", limit_price="100"))
            return result(execute_result or "RECONCILE")
        return result(next(rows))
    def run():
        return gateway.execute_to_completion(conn="private", permit="permit",
            cycle=SimpleNamespace(cycle_id="cycle", state=CycleState.EXECUTING),
            deployment="deployment", plan_id="plan", asset_count=asset_count,
            callback=callback, execute="execute", recover="recover", http=http, maximum_lateness=540)
    return run, http, calls, transitions


def test_scheduler_retry_uses_legal_states_and_one_original_clock(monkeypatch):
    run, http, calls, transitions = campaign(monkeypatch)
    cycle, recovered, passes = run()
    assert passes == 2 and recovered.disposition.value == "SUCCEEDED" and http.started == 0
    assert http.first_order_seconds == 10 and len(http.orders) == 2
    assert cycle.state is CycleState.RECONCILING
    assert calls == [("EXECUTE", CycleState.EXECUTING), ("RECOVER", CycleState.RECONCILING)] * 2
    assert [row["to_state"] for row in transitions] == [CycleState.RECONCILING, CycleState.RETRY_WAIT,
                                                        CycleState.EXECUTING, CycleState.RECONCILING]
    assert transitions[1]["diagnostic"]["retry_phase"] == "EXECUTE"


@pytest.mark.parametrize("times", [(121, 125, 130, 140), (10, 50, 270, 301)])
def test_retry_cannot_hide_first_post_or_total_deadline_failure(monkeypatch, times):
    run, http, _calls, _transitions = campaign(monkeypatch, times=times)
    with pytest.raises(gateway.QualificationRefused, match="LATENCY_MARGIN"):
        run()
    assert http.started == 0


def test_no_forward_progress_cannot_loop_to_a_later_pass(monkeypatch):
    run, http, calls, _transitions = campaign(monkeypatch, send=False)
    with pytest.raises(gateway.QualificationRefused, match="NO_FORWARD_PROGRESS"):
        run()
    assert len(calls) == 2 and http.orders == {}


def test_retry_count_is_bounded_even_when_orders_keep_appearing(monkeypatch):
    run, http, calls, _transitions = campaign(monkeypatch,
        recoveries=("READY_TO_EXECUTE", "READY_TO_EXECUTE"))
    with pytest.raises(gateway.QualificationRefused, match="NO_COMPLETE_BASKET"):
        run()
    assert len(calls) == 4 and len(http.orders) == 2


@pytest.mark.parametrize("execute_result,command_state", [("BLOCKED", "FILLED"), (None, "UNKNOWN")])
def test_refusal_or_uncertainty_stops_before_recovery_or_retry(monkeypatch, execute_result, command_state):
    run, _http, calls, _transitions = campaign(monkeypatch, execute_result=execute_result, command_state=command_state)
    with pytest.raises(gateway.QualificationRefused):
        run()
    assert len(calls) == 1


def broken(function, before, after):
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = {}
    exec(compile(source.replace(before, after), '<removed-qualification-guard>', 'exec'), function.__globals__, namespace)
    return namespace[function.__name__]


def test_callback_disposition_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "require_callback_progress", broken(gateway.require_callback_progress,
        'if result.disposition.value not in allowed:', 'if False:'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_returned_refusal_never_becomes_later_success("EXECUTE", "BLOCKED")


def test_explicit_protected_policy_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "require_protected_policy", broken(gateway.require_protected_policy,
        'if policy is None:', 'if False:'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_gateway_requires_explicit_selected_policy_and_usable_cap(monkeypatch, None, None)


def test_canonical_unknown_command_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "require_command_progress", broken(gateway.require_command_progress,
        'if any(command.state.value in', 'if False and any(command.state.value in'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_canonical_journal_uncertainty_stops_the_campaign(monkeypatch, "UNKNOWN")


def test_quote_get_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "require_no_quotes", broken(gateway.require_no_quotes,
        'if any(count for key, count in http.requests.items() if "quotes" in key):', 'if False:'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_protected_fixture_forbids_quote_requests_and_cross_host_routes()


def test_original_timing_clock_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "require_latency_progress", lambda *_a, **_k: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_retry_cannot_hide_first_post_or_total_deadline_failure(monkeypatch, (10, 50, 270, 301))


def test_no_progress_falsifier(monkeypatch):
    monkeypatch.setattr(gateway, "execute_to_completion", broken(gateway.execute_to_completion,
        'if len(http.orders) <= prior_orders:', 'if False:'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_no_forward_progress_cannot_loop_to_a_later_pass(monkeypatch)
