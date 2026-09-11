"""Falsifiers for replay identity, independent accounting and state contracts."""
from copy import deepcopy
import json

import pytest

from tests.internal_state.contract import Action, InvalidTrace, InvariantFailure, Trace, reduce_trace
from tests.internal_state.oracles import broker_accounting, canonical_state, journal_contract
from tests.internal_state.scenarios import catalogue, generated
from tests.internal_state.ci_gate import acceptance


@pytest.mark.parametrize("mutation", ["empty", "skip", "failure", "missing", "exit"])
def test_full_suite_gate_cannot_pass_incomplete_results(mutation):
    report = dict(collected=["a", "b"], passed={"a": 1, "b": 2}, failures={}, skipped={},
                  expected_failures={}, exitstatus=0)
    assert acceptance(**report)
    if mutation == "empty":
        report["collected"], report["passed"] = [], {}
    elif mutation == "skip":
        report["passed"].pop("b")
        report["skipped"]["b"] = "missing prerequisite"
    elif mutation == "failure":
        report["failures"]["a"] = "failure"
    elif mutation == "missing":
        report["passed"].pop("b")
    else:
        report["exitstatus"] = 2
    assert not acceptance(**report)


def test_trace_has_exact_replay_identity_and_rejects_changed_events():
    trace = generated(2026)
    assert Trace.decode(json.loads(json.dumps(trace.envelope()))) == trace
    changed = trace.envelope()
    changed["trace"]["actions"][0]["kind"] = "restart"
    with pytest.raises(InvalidTrace, match="digest"):
        Trace.decode(changed)


def test_reducer_replays_same_failure_and_rejects_invalid_causal_candidates():
    trace = Trace(name="reducer", actions=tuple(Action(kind=k) for k in
        ("restart", "daily", "restart", "execute", "restart", "fill", "restart")))
    def run(candidate):
        kinds = [a.kind for a in candidate.actions]
        if "fill" in kinds and ("execute" not in kinds or "daily" not in kinds):
            raise InvalidTrace("missing preconditions")
        if "fill" in kinds:
            raise InvariantFailure("cash_conservation", 100, 90)
    reduced, evidence = reduce_trace(trace, run, "cash_conservation")
    assert [a.kind for a in reduced.actions] == ["daily", "execute", "fill"]
    assert evidence["evaluations"] <= evidence["budget"]
    with pytest.raises(InvariantFailure, match="cash_conservation"):
        run(reduced)


def test_generation_is_deterministic_bounded_and_varied():
    assert [generated(i).envelope() for i in range(16)] == [generated(i).envelope() for i in range(16)]
    assert len({tuple(a.kind for a in generated(i).actions) for i in range(16)}) == 16
    assert all(3 < len(generated(i).actions) <= 40 for i in range(16))
    names = [(t.name, t.profile) for t in catalogue()]
    assert len(names) == len(set(names))
    assert {t.profile for t in catalogue()} == {"paper", "live_cash"}


@pytest.fixture
def money():
    return {"initial_cash": "1000", "movements": ["50"], "cash": "1042", "positions": {"ABC": "1"},
        "fills": [{"sign": "1", "quantity": "2", "price": "10", "symbol": "ABC"},
                  {"sign": "-1", "quantity": "1", "price": "12", "symbol": "ABC"}],
        "orders": {"a": {"client_order_id": "a", "filled_qty": "2", "qty": "2"},
                   "b": {"client_order_id": "b", "filled_qty": "1", "qty": "1"}}}


@pytest.mark.parametrize("fault,expected", [
    ("cash", "broker_cash_conservation"), ("shares", "broker_share_conservation"),
    ("duplicate", "one_broker_order_per_key"), ("overfill", "broker_fill_bounds")])
def test_independent_accounting_kills_false_facts(money, fault, expected):
    broker_accounting(money)
    if fault == "cash":
        money["cash"] = "1043"
    elif fault == "shares":
        money["positions"]["ABC"] = "2"
    elif fault == "duplicate":
        money["orders"]["b"]["client_order_id"] = "a"
    else:
        money["orders"]["a"]["filled_qty"] = "3"
    with pytest.raises(InvariantFailure) as captured:
        broker_accounting(money)
    assert captured.value.invariant == expected


@pytest.fixture
def state():
    day = "2026-10-20"
    return {"strategy_identity": {"fixture": "frozen"}, "last_processed_session": day,
        "controller": {"last_session": day}, "last_decision": {"session": day, "target_core_exposure": .55},
        "recent_leadership": {"last_session": day}, "ldrc": {"last_session": day}, "shadow_peak_nav": 1000,
        "wealth_core": {"slots": {str(i): {"occupied_by": None} for i in range(25)}, "cash": 100000, "episodes": {}},
        "ledger": {"events": []}, "pending": [],
        "feed": {"series": {"ABC": {"sessions": [day], "session_indices": [1],
            "signal_closes": [10], "raw_closes": [10], "volumes": [100]}}}}


@pytest.mark.parametrize("fault,expected", [
    ("cursor", "state_cursor_atomicity"), ("witness", "witness_cursor"),
    ("ldrc", "ldrc_cursor"), ("exposure", "exposure_bounds"),
    ("slot", "one_slot_per_episode"), ("future", "no_future_observation"),
    ("nan", "finite_state"), ("identity", "strategy_identity")])
def test_independent_state_contract_kills_corruption(state, fault, expected):
    identity = deepcopy(state["strategy_identity"])
    canonical_state(state, identity=identity, cursor="2026-10-20")
    if fault == "cursor":
        state["last_processed_session"] = "2026-10-19"
    elif fault in {"witness", "ldrc"}:
        state["recent_leadership" if fault == "witness" else "ldrc"]["last_session"] = "2026-10-19"
    elif fault == "exposure":
        state["last_decision"]["target_core_exposure"] = 1.01
    elif fault == "slot":
        state["wealth_core"]["slots"]["0"]["occupied_by"] = "same"
        state["wealth_core"]["slots"]["1"]["occupied_by"] = "same"
    elif fault == "future":
        state["feed"]["series"]["ABC"]["sessions"] = ["2026-10-21"]
    elif fault == "nan":
        state["feed"]["series"]["ABC"]["signal_closes"] = [float("nan")]
    else:
        state["strategy_identity"]["fixture"] = "changed"
    with pytest.raises(InvariantFailure) as captured:
        canonical_state(state, identity=identity, cursor="2026-10-20")
    assert captured.value.invariant == expected


def test_journal_oracle_rejects_illegal_transition_and_changed_economics():
    c = {"client_key": "k", "identity": {"security_id": "ABC"}, "instrument": {"symbol": "ABC"},
         "side": "BUY", "quantity": "2", "filled_quantity": "0", "state": "SEND_PENDING"}
    events = {"k": [{"from": None, "to": "PLANNED", "filled": "0"},
                    {"from": "PLANNED", "to": "SEND_PENDING", "filled": "0"}]}
    remembered = {}
    journal_contract([c], events, {"orders": {}}, remembered)
    c["quantity"] = "3"
    with pytest.raises(InvariantFailure, match="immutable_command_economics"):
        journal_contract([c], events, {"orders": {}}, remembered)
    c["quantity"] = "2"
    events["k"][1]["to"] = "FILLED"
    with pytest.raises(InvariantFailure, match="legal_command_transition"):
        journal_contract([c], events, {"orders": {}}, remembered)


@pytest.mark.parametrize("fault", ["intact", "quantity", "side", "instrument", "deployment",
                                   "revision", "key", "broker", "no_restore"])
def test_recovered_attribution_keeps_pre_restore_economics_exact(fault):
    original = {"client_key": "k", "identity": {"security_id": "ABC", "plan_id": "sentinel-original",
        "revision": 0, "deployment": {"broker_account_id": "owned"}},
        "instrument": {"symbol": "ABC"}, "side": "BUY", "quantity": "2",
        "filled_quantity": "2", "state": "FILLED", "recovered_key": None}
    events = {"k": [{"from": None, "to": "FILLED", "filled": "2"}]}
    world = {"orders": {"order": {"client_order_id": "k", "qty": "2", "filled_qty": "2",
                                  "side": "buy", "symbol": "ABC"}}}
    remembered = {}
    journal_contract([original], events, world, remembered)
    recovered = deepcopy(original)
    recovered["identity"]["plan_id"] = "RECOVERED"
    recovered["recovered_key"] = "k"
    if fault == "quantity":
        recovered["quantity"] = "3"
    elif fault == "side":
        recovered["side"] = "SELL"
    elif fault == "instrument":
        recovered["instrument"]["symbol"] = "OTHER"
    elif fault == "deployment":
        recovered["identity"]["deployment"]["broker_account_id"] = "foreign"
    elif fault == "revision":
        recovered["identity"]["revision"] = 1
    elif fault == "key":
        recovered["recovered_key"] = None
    elif fault == "broker":
        world["orders"] = {}
    if fault == "intact":
        journal_contract([recovered], events, world, remembered, restored=True)
    else:
        with pytest.raises(InvariantFailure, match="immutable_command_economics"):
            journal_contract([recovered], events, world, remembered, restored=fault != "no_restore")
