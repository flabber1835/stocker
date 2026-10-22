"""Account quantities change for intent, not daily NAV/rounding noise."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import dual_plan_authority as authority, schema
from sentinel.core import decision
from sentinel.execution import held_targets, journal, protected_limits as limits
from sentinel.execution import target_reprojection as projections
from sentinel.execution.commands import compute_delta, DeltaClass
from sentinel.execution.contract import Side
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.sentinel.test_order_terms_schema import pg  # noqa: F401
from tests.sentinel.test_production_decision import (
    _account, _binding, _controller_rollout, _episode, _observation,
    _position, _publication, _state, _working_order)
from tests.sentinel.test_limit_day_sizing import references
from tests.support.postgres import drop_public_tables
from tests.sentinel.test_retained_binding_reuse import proof_scope
from tests.v5.test_opening import base, case

SID = "PBR-A"


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg.sync_dsn) as connection:
        drop_public_tables(connection)
        schema.ensure_schema(connection)
        yield connection


def state(*, equity="50337.32063980001", session="2026-08-11", exposure="0.55", shares=132):
    value = _state(episodes=[_episode(7, SID, "PBR.A", shares)], equity=equity, exposure=exposure)
    value.last_processed_session = session
    value.last_decision["session"] = session
    return value


def build(value, *, cash="49972.37", observation=None, targets=None, price="22.96", defensive=None):
    return decision.build_execution_plan(value, _binding(),
        replace(_publication(), window_end=value.last_processed_session),
        _account(equity=cash, cash=cash), observation or _observation(),
        {SID: D(price), "SENTINEL:BIL": D("91.61")}, {SID: "PBR.A", "SENTINEL:BIL": "BIL"},
        date.fromisoformat(value.last_processed_session),
        date.fromisoformat(calendar.next_session(value.last_processed_session)),
        defensive_security=defensive, rollout_state=_controller_rollout(), retained_targets=targets)


def carry(previous, before, after, projection=None, *, actions=None):
    return held_targets.carry_quantities(previous=previous, previous_state=before,
        projection=projection or base(before, previous), state=after,
        exposure=D(str(after.last_decision["target_core_exposure"])), actions=actions)


def test_actual_pbra_rounding_sale_is_removed_without_a_topup():
    before = state()
    initial = build(before).plan
    after = state(equity="50605.570639800004", session="2026-08-12")
    observation = _observation(positions=[_position(SID, "PBR.A", "72")])
    old = build(after, cash="48392.83", observation=observation, price="23.10").plan
    assert initial.target_basket[SID] == 72 and old.target_basket[SID] == 71
    snapshot = after.to_dict()
    targets = carry(initial, before, after)
    fixed = build(after, cash="48392.83", observation=observation, targets=targets, price="23.10").plan
    assert fixed.target_basket[SID] == 72 and after.to_dict() == snapshot
    delta = compute_delta(security_id=SID, desired=fixed.target_basket[SID],
        observation=observation, min_increment=D(1))
    assert delta.classification is DeltaClass.NONE


@pytest.mark.parametrize("equity", ["48000", "50337.32063980001", "60000"])
def test_no_daily_sell_or_topup_when_scale_moves(equity):
    before, after = state(), state(equity=equity, session="2026-08-12")
    previous = build(before).plan
    assert build(after, targets=carry(previous, before, after)).plan.target_basket[SID] == 72


def test_winner_gains_value_without_a_share_trim():
    before, after = state(), state(equity="56000", session="2026-08-12")
    previous = build(before).plan
    result = build(after, targets=carry(previous, before, after), price="45.92")
    assert result.plan.target_basket[SID] == 72
    assert result.projection.notional[SID] == D(72) * D("45.92")


@pytest.mark.parametrize("exposure", ["0", "0.35", "0.65", "1"])
def test_controller_allocation_change_still_resizes(exposure):
    before, after = state(), state(session="2026-08-12", exposure=exposure)
    previous = build(before).plan
    assert carry(previous, before, after) == {}
    assert build(after, targets={}).plan.target_basket.get(SID, D(0)) != 72


def test_exit_and_reentry_are_not_protected_as_continuing_holdings():
    before, after = state(), state(session="2026-08-12")
    previous = build(before).plan
    after.pending = [PendingOrder(Operation.CLOSE_POSITION, SID, "PBR.A", 7, 132,
        after.last_processed_session, "STOP").to_dict()]
    assert carry(previous, before, after) == {}
    assert build(after, targets={}).plan.target_basket.get(SID, D(0)) == 0
    after.pending = []
    after.wealth_core["episodes"]["7"]["signal_date"] = "2026-08-12"
    assert carry(previous, before, after) == {}


def test_split_ages_frozen_quantity_without_rebalancing():
    before, after = state(), state(session="2026-08-13", shares=264)
    previous = build(before).plan
    event = {"security_id": SID, "session": "2026-08-13", "source_row_id": "split-2",
             "canonical_multiplier": "2", "value": "2", "canonical_numerator": "2", "canonical_denominator": "1"}
    class Actions:
        def __call__(self, sid): return D(2) if sid == SID else D(1)
        def material_events_for(self, **kwargs): return ()
        def scalar_evidence_for(self, ids): return ()
    with pytest.raises(projections.TargetProjectionRefused, match="durable action"):
        carry(previous, before, after, actions=Actions())
    class Evidenced(Actions):
        def scalar_evidence_for(self, ids):
            return (SimpleNamespace(to_dict=lambda: dict(event)),)
    assert carry(previous, before, after, actions=Evidenced())[SID] == 144
    class Unsupported(Evidenced):
        def material_events_for(self, **kwargs): return ("MERGER",)
    with pytest.raises(projections.TargetProjectionRefused, match="unsupported action"):
        carry(previous, before, after, actions=Unsupported())


def test_partial_fill_retains_intended_target_not_observed_quantity():
    before, after = state(), state(session="2026-08-12")
    previous = build(before).plan
    obs = _observation(positions=[_position(SID, "PBR.A", "50")])
    fixed = build(after, observation=obs, targets=carry(previous, before, after)).plan
    assert fixed.target_basket[SID] == 72
    delta = compute_delta(security_id=SID, desired=fixed.target_basket[SID], observation=obs, min_increment=D(1))
    assert delta.quantity == 22
    working = _observation(positions=obs.positions, orders=[_working_order(
        SID, "PBR.A", side=Side.BUY, quantity="72", filled="50")])
    assert compute_delta(security_id=SID, desired=fixed.target_basket[SID],
        observation=working, min_increment=D(1)).classification is DeltaClass.NONE


def test_installation_does_not_buy_back_the_previously_sold_share():
    before, after = state(), state(session="2026-08-12")
    previous = build(before).plan
    projection = replace(base(before, previous), target_basket={SID: D(71)})
    fixed = build(after, targets=carry(previous, before, after, projection)).plan
    assert fixed.target_basket[SID] == 71


def test_pending_entry_to_held_episode_keeps_protected_account_quantity():
    before, previous = case(entries=1, exposure="0.55")
    projected = base(before, previous)
    projected = limits.resolve_protected(before, previous, projected,
        references(previous, projected), limits.ProtectedLimitPolicy(100))
    after = deepcopy(before)
    after.last_processed_session = previous.effective_session.isoformat()
    after.last_decision["session"] = after.last_processed_session
    portfolio = PortfolioState.from_dict(after.wealth_core)
    episode = _episode(0, "SEC-AAA", "AAA", 50)
    episode.signal_date = previous.decision_session.isoformat()
    portfolio.episodes[0] = episode
    after.wealth_core = portfolio.to_dict()
    after.pending = []
    assert carry(previous, before, after, projected)["SEC-AAA"] == projected.target_basket["SEC-AAA"] == 27


def save(conn, value, plan, *, basis=None):
    journal.adopt_current_plan(conn, plan)
    shadow = SimpleNamespace(state=value, record_sha256="b"*64, runtime_authority_sha256="c"*64)
    proof = authority.build_authority(plan=plan, shadow_result=shadow,
        publication=replace(_publication(), window_end=value.last_processed_session),
        account_snapshot=_account(equity="49972.37"), observation=_observation(),
        marks={SID: D("22.96"), "SENTINEL:BIL": D("91.61")},
        tickers={SID: "PBR.A", "SENTINEL:BIL": "BIL"}, held_share_targets=basis)
    authority.record_authority(conn, proof)
    projections.record_projection(conn, base(value, plan))
    return shadow, proof


def test_durable_predecessor_rederives_and_survives_reconnect(conn):
    before = state()
    previous = build(before, defensive="SENTINEL:BIL").plan
    save(conn, before, previous)
    after = state(equity="50605.570639800004", session="2026-08-12")
    basis = held_targets.build_basis(conn, previous=previous, state=after,
        binding=_binding(), rollout=_controller_rollout())
    assert basis["targets"][SID] == "72"
    targets = {sid: D(qty) for sid, qty in basis["targets"].items()}
    current = build(after, targets=targets, defensive="SENTINEL:BIL").plan
    shadow, proof = save(conn, after, current, basis=basis)
    assert proof["schema"] == authority.HELD_SCHEMA
    with psycopg.connect(conn.info.dsn) as reopened:
        retained = authority.rederive_plan(reopened, plan=current, binding=_binding(),
            rollout_state=_controller_rollout(), expected_shadow_result=shadow)
        assert retained["retained_targets"] == basis["targets"]
        assert held_targets.plan_targets(reopened, plan=current, state=after) == targets
        assert journal.latest_plan(reopened).target_basket[SID] == 72


@pytest.mark.parametrize("field,value", [
    ("targets", {SID: "71"}), ("previous_projection_fingerprint", "a"*64),
    ("previous_authority_sha256", "a"*64), ("previous_plan_fingerprint", "a"*64),
])
def test_tampered_basis_refuses(conn, field, value):
    before, after = state(), state(session="2026-08-12")
    previous = build(before).plan
    save(conn, before, previous)
    basis = held_targets.build_basis(conn, previous=previous, state=after,
        binding=_binding(), rollout=_controller_rollout())
    basis[field] = value
    with pytest.raises(projections.TargetProjectionRefused, match="do not re-derive"):
        held_targets.verify_basis(conn, basis=basis, state=after, binding=_binding(), rollout=_controller_rollout())


def test_another_account_cannot_seed_targets(conn):
    before, after = state(), state(session="2026-08-12")
    previous = build(before).plan
    save(conn, before, previous)
    with pytest.raises(projections.TargetProjectionRefused, match="another account"):
        held_targets.build_basis(conn, previous=previous, state=after,
            binding=_binding(account_id="another"), rollout=_controller_rollout())


def test_absent_and_changed_parent_projection_change_reuse_token(conn):
    before, after = state(), state(session="2026-08-12")
    previous = build(before, defensive="SENTINEL:BIL").plan
    save(conn, before, previous)
    basis = held_targets.build_basis(conn, previous=previous, state=after,
        binding=_binding(), rollout=_controller_rollout())
    current = build(after, targets={sid: D(q) for sid, q in basis["targets"].items()},
        defensive="SENTINEL:BIL").plan
    save(conn, after, current, basis=basis)
    token = held_targets.predecessor_version(conn, current.plan_id)
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
        (projections.CURSOR_PREFIX + previous.plan_id,))
    conn.commit()
    assert held_targets.predecessor_version(conn, current.plan_id) != token
    with pytest.raises(projections.TargetProjectionRefused, match="do not re-derive"):
        held_targets.verify_basis(conn, basis=basis, state=after, binding=_binding(), rollout=_controller_rollout())


def test_rehashed_forged_basis_still_refuses_parent_mismatch(conn):
    before, after = state(), state(session="2026-08-12")
    previous = build(before, defensive="SENTINEL:BIL").plan
    save(conn, before, previous)
    basis = held_targets.build_basis(conn, previous=previous, state=after,
        binding=_binding(), rollout=_controller_rollout())
    current = build(after, targets={sid: D(q) for sid, q in basis["targets"].items()},
        defensive="SENTINEL:BIL").plan
    shadow, proof = save(conn, after, current, basis=basis)
    proof["held_share_targets"]["targets"][SID] = "71"
    proof.pop("authority_sha256")
    proof["authority_sha256"] = authority._sha256(proof)
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
        (authority._canonical(proof), authority.CURSOR_PREFIX + current.plan_id))
    conn.commit()
    with pytest.raises(authority.DualPlanAuthorityRefused, match="do not re-derive"):
        authority.rederive_plan(conn, plan=current, binding=_binding(),
            rollout_state=_controller_rollout(), expected_shadow_result=shadow)


def test_scope_reuses_small_basis_but_rechecks_changed_parent_projection(conn, monkeypatch):
    before, after = state(), state(session="2026-08-12")
    previous = build(before, defensive="SENTINEL:BIL").plan
    save(conn, before, previous)
    basis = held_targets.build_basis(conn, previous=previous, state=after,
        binding=_binding(), rollout=_controller_rollout())
    current = build(after, targets={sid: D(q) for sid, q in basis["targets"].items()},
        defensive="SENTINEL:BIL").plan
    shadow, _ = save(conn, after, current, basis=basis)
    calls = []
    real = authority._rederive_plan
    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(authority, "_rederive_plan", counted)
    with proof_scope(conn) as scope:
        def read():
            return authority.rederive_plan(conn, plan=current, binding=_binding(),
                rollout_state=_controller_rollout(), expected_shadow_result=shadow)
        assert read()["retained_targets"][SID] == "72"
        cached = scope.values["held-share-basis"]
        assert len(cached[2]) < 8192
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,'{}')",
            ("broker-observation:v4:retained-target-test", after.last_processed_session))
        conn.commit()
        assert read()["retained_targets"][SID] == "72" and len(calls) == 1
        assert scope.values["held-share-basis"] is cached
        conn.execute("UPDATE sentinel_processed_sessions SET state=state WHERE cursor_name=%s",
            (projections.CURSOR_PREFIX + previous.plan_id,))
        conn.commit()
        assert read()["retained_targets"][SID] == "72" and len(calls) == 2


def test_unsized_missing_reference_does_not_freeze_an_unbound_zero():
    before, previous = case(entries=1, exposure="0.55")
    projected = base(before, previous)
    projected = limits.resolve_protected(before, previous, projected,
        references(previous, projected, prices={"SENTINEL:BIL": D(100)}), limits.ProtectedLimitPolicy(100))
    assert projected.target_basket["SEC-AAA"] == 0
    after = deepcopy(before)
    after.last_processed_session = previous.effective_session.isoformat()
    after.last_decision["session"] = after.last_processed_session
    assert "SEC-AAA" not in carry(previous, before, after, projected)


def test_presubmit_guard_binds_retention_to_verified_sizing(monkeypatch):
    from sentinel.paper import validation
    value, plan = case(entries=1, exposure="0.55")
    projected = base(value, plan)
    fixed = limits.resolve_protected(value, plan, projected,
        references(plan, projected), limits.ProtectedLimitPolicy(100), retained_targets={})
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    monkeypatch.setattr(validation.binding_mod, "require", lambda c: _binding())
    monkeypatch.setattr(validation.journal, "load_commands", lambda *a, **k: [SimpleNamespace(side=Side.BUY)])
    monkeypatch.setattr(projections, "load_projection", lambda *a, **k: fixed)
    validation._protected_allocation_or_refuse(None, plan=plan, state=value, retained_targets={})
    with pytest.raises(validation.PaperActivationRefused, match="retained share authority"):
        validation._protected_allocation_or_refuse(None, plan=plan, state=value, retained_targets=None)


def test_existing_appreciation_is_held_without_funding_new_entry():
    value, plan = case(entries=1, exposure="0.55")
    portfolio = PortfolioState.from_dict(value.wealth_core)
    portfolio.episodes[7] = _episode(7, SID, "PBR.A", 132)
    portfolio.slots[7].occupied_by = SID
    value.wealth_core = portfolio.to_dict()
    value.feed["series"][SID] = {"security_id": SID, "ticker": "PBR.A", "issuer_id": "issuer-"+SID,
        "split_factor": 1., "sessions": [], "session_indices": [], "signal_closes": [], "raw_closes": [], "volumes": []}
    plan = decision.build_execution_plan(value, _binding(), _publication(), _account(equity="10000"),
        _observation(), {SID: D(100), "SEC-AAA": D(100)}, {SID: "PBR.A", "SEC-AAA": "AAA"},
        plan.decision_session, plan.effective_session, defensive_security=None,
        rollout_state=_controller_rollout(), retained_targets={SID: D(72)}).plan
    projected = base(value, plan)
    refs = references(plan, projected)
    with pytest.raises(projections.TargetProjectionRefused, match="exceeds"):
        limits.resolve_protected(value, plan, projected, refs, limits.ProtectedLimitPolicy(100))
    fixed = limits.resolve_protected(value, plan, projected, refs,
        limits.ProtectedLimitPolicy(100), retained_targets={SID: D(72)})
    assert fixed.target_basket[SID] == 72 and fixed.target_basket["SEC-AAA"] == 0
    assert fixed.opening_sizing["unallocated_core_budget"] == "0"
    limits.validate_projection(fixed)


def test_removing_retention_falsifier_recreates_the_observed_sale(monkeypatch):
    source = Path(held_targets.__file__).read_text()
    needle = "    if targets is None:\n        return projection\n"
    assert source.count(needle) == 1
    namespace = {"__name__": held_targets.__name__}
    exec(compile(source.replace(needle, "    return projection\n"), "<retention-disabled>", "exec"), namespace)
    monkeypatch.setattr(held_targets, "apply", namespace["apply"])
    with pytest.raises(AssertionError):
        test_actual_pbra_rounding_sale_is_removed_without_a_topup()


def test_removing_exposure_change_guard_is_detected(monkeypatch):
    source = Path(held_targets.__file__).read_text()
    needle = "if previous.target_exposure != exposure:"
    assert source.count(needle) == 1
    namespace = {"__name__": held_targets.__name__}
    exec(compile(source.replace(needle, "if False:"), "<allocation-guard-disabled>", "exec"), namespace)
    monkeypatch.setattr(held_targets, "carry_quantities", namespace["carry_quantities"])
    with pytest.raises(AssertionError):
        test_controller_allocation_change_still_resizes("0.35")


def test_removing_presubmit_basis_guard_is_detected(monkeypatch):
    from sentinel.paper import validation
    import inspect
    source = inspect.getsource(validation._protected_allocation_or_refuse)
    needle = 'if projection.opening_sizing.get("retained_targets") != retained_targets:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "<basis-guard-disabled>", "exec"),
        validation._protected_allocation_or_refuse.__globals__, namespace)
    monkeypatch.setattr(validation, "_protected_allocation_or_refuse", namespace["_protected_allocation_or_refuse"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_presubmit_guard_binds_retention_to_verified_sizing(monkeypatch)
