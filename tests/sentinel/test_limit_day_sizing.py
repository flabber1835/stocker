"""Protected BUY allocation, RAW provenance, and historical-policy separation."""
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction
import inspect
import json
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.core import decision
from sentinel.execution import opening_sizing, protected_limits as limits
from sentinel.execution import target_reprojection as projections
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.v5.test_opening import case, base
from tests.sentinel.test_production_decision import (
    _account, _binding, _episode, _observation, _publication)


@pytest.fixture(autouse=True)
def legacy_environment(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)


def references(plan, projection, *, prices=None):
    symbols = {sid: sid.replace("SEC-", "") for sid in limits._wanted(plan, projection)}
    symbols["SENTINEL:BIL"] = "BIL"
    return limits.PriorCloseReferences(plan.fingerprint(), plan.decision_session, plan.effective_session,
        plan.publication_fingerprint, "candidate", "a" * 64, "b" * 64, "ALPACA_OPENFIGI",
        {sid: D("100") for sid in symbols} if prices is None else prices, symbols,
        {sid: str(limits._factor(projection, sid)) for sid in symbols}, limits._action_identity(projection),
        {sid: "asset-" + sid for sid in symbols if sid != "SENTINEL:BIL"})


def protected_case(*, entries=2, exposure="0.55"):
    state, plan = case(entries=entries, exposure=exposure)
    projection = base(state, plan)
    refs = references(plan, projection)
    return state, plan, projection, refs


def select(monkeypatch, cap="100"):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", cap)


def with_held(*, quantity=990):
    state, old = case(entries=2, exposure="0.55")
    portfolio = PortfolioState.from_dict(state.wealth_core)
    portfolio.cash = 1000.
    portfolio.episodes[19] = _episode(19, "HELD", "HLD", quantity)
    portfolio.slots[19].occupied_by = "HELD"
    state.wealth_core = portfolio.to_dict()
    state.feed["series"]["HELD"] = {"security_id": "HELD", "ticker": "HLD", "issuer_id": "held-issuer",
        "split_factor": 1., "sessions": [], "session_indices": [], "signal_closes": [], "raw_closes": [], "volumes": []}
    marks = {"SEC-AAA": D(100), "SEC-BBB": D(100), "HELD": D(100)}
    plan = decision.build_execution_plan(state, _binding(), _publication(), _account(equity="100000"),
        _observation(), marks, {"SEC-AAA": "AAA", "SEC-BBB": "BBB", "HELD": "HLD"},
        old.decision_session, old.effective_session, defensive_security=None,
        rollout_state=SimpleNamespace(mode=SimpleNamespace(value="CONTROLLER"), version=1, certificate_sha256="a"*64)).plan
    projection = base(state, plan)
    return state, plan, projection, references(plan, projection)


def test_explicit_policy_has_no_implicit_cap_and_binds_every_term(monkeypatch):
    assert limits.ProtectedLimitPolicy.from_env() is None
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", limits.PROTECTED_MODE)
    with pytest.raises(projections.TargetProjectionRefused, match="explicit integer"):
        limits.ProtectedLimitPolicy.from_env()
    select(monkeypatch)
    policy = limits.ProtectedLimitPolicy.from_env()
    assert limits.ProtectedLimitPolicy.from_dict(policy.to_dict()) == policy
    assert len(policy.fingerprint()) == 64
    assert policy.fingerprint() != limits.ProtectedLimitPolicy(101).fingerprint()
    raw = policy.to_dict(); raw["buy_cash_headroom"] = "0"
    with pytest.raises(projections.TargetProjectionRefused, match="unsupported"):
        limits.ProtectedLimitPolicy.from_dict(raw)


@pytest.mark.parametrize("raw", ["-1", "1.1", "+1", "01", "True", ""])
def test_invalid_cap_refuses_without_default(monkeypatch, raw):
    select(monkeypatch, raw)
    with pytest.raises(projections.TargetProjectionRefused):
        limits.ProtectedLimitPolicy.from_env()


def test_cap_above_reviewed_ceiling_refuses():
    with pytest.raises(projections.TargetProjectionRefused, match="500"):
        limits.ProtectedLimitPolicy(501)


def test_orphan_cap_refuses_without_selecting_policy(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    with pytest.raises(projections.TargetProjectionRefused, match="explicit policy"):
        limits.ProtectedLimitPolicy.from_env()


def test_empty_compose_policy_and_cap_preserve_legacy_mode(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", "")
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "")
    assert limits.ProtectedLimitPolicy.from_env() is None


@pytest.mark.parametrize("price,cap,expected", [
    ("100.009", 0, "100.00"), ("0.99999", 0, "0.9999"),
    ("0.99999", 1, "1.00"), ("100", 100, "101.00"),
])
def test_limit_rounds_down_at_the_resulting_price_tick(price, cap, expected):
    _state, plan, projection, refs = protected_case()
    refs = replace(refs, prices={"SEC-AAA": D(price)})
    assert limits.limit_for(refs, "SEC-AAA", limits.ProtectedLimitPolicy(cap)) == D(expected)


def test_subtick_nonpositive_limit_refuses():
    _state, plan, projection, refs = protected_case()
    refs = replace(refs, prices={"SEC-AAA": D("0.00001")})
    with pytest.raises(projections.TargetProjectionRefused, match="positive"):
        limits.limit_for(refs, "SEC-AAA", limits.ProtectedLimitPolicy(0))


def test_exact_action_fraction_inverts_raw_price_and_is_bound():
    state, plan, _projection, _refs = protected_case()
    evidence = ({"security_id": "SEC-AAA", "session": str(plan.effective_session),
        "source_row_id": "split", "value": 30., "canonical_multiplier": str(D(1)/D(30)),
        "canonical_numerator": 1, "canonical_denominator": 30},)
    projection = base(state, plan, multipliers={"SEC-AAA": D(str(1/30))}, evidence=evidence)
    refs = references(plan, projection)
    assert refs.unit_factors["SEC-AAA"] == "1/30"
    assert limits.limit_for(refs, "SEC-AAA", limits.ProtectedLimitPolicy(100)) == D("3030")
    changed = replace(projection, action_evidence=())
    with pytest.raises(projections.TargetProjectionRefused, match="authority"):
        limits.resolve_protected(state, plan, changed, refs, limits.ProtectedLimitPolicy(100))


def test_nonunit_share_factor_requires_durable_event_evidence():
    with pytest.raises(projections.TargetProjectionRefused, match="durable action"):
        limits._factor(SimpleNamespace(action_multipliers={"HELD": D(2)}, action_evidence=()), "HELD")


def test_openfigi_stock_ids_cannot_silently_fall_back_to_symbol_only():
    _state, _plan, _projection, refs = protected_case()
    with pytest.raises(projections.TargetProjectionRefused, match="source-native"):
        replace(refs, provider_asset_ids={})
    assert replace(refs, source_provider="SHARADAR", provider_asset_ids={}).provider_asset_ids == {}


def test_quantities_use_scaled_budget_limit_and_headroom_without_mutating_state():
    state, plan, projection, refs = protected_case()
    before = state.state_hash
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.target_basket == {"SEC-AAA": D(27), "SEC-BBB": D(27)}
    assert [Fraction(row["budget"]) for row in result.opening_sizing["entries"]] == [Fraction(2750)] * 2
    assert "SENTINEL:BIL" not in result.opening_sizing["limits"]
    assert result.opening_sizing["mode"] == limits.PROTECTED_MODE
    assert state.state_hash == before
    assert limits.validate_projection(result)[1] == refs
    assert limits.PriorCloseReferences.from_dict(json.loads(json.dumps(refs.to_dict()))) == refs
    with pytest.raises(TypeError):
        refs.prices["SEC-AAA"] = D(1)


def test_core_remaining_allocation_is_shared_in_slot_order():
    state, plan, projection, refs = with_held()
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.target_basket["HELD"] == projection.target_basket["HELD"] == D(544)
    # H=54,400; the first intent owns all remaining600, despite both intents naming5,000.
    assert [Fraction(row["budget"]) for row in result.opening_sizing["entries"]] == [Fraction(600), Fraction(0)]
    assert result.target_basket["SEC-AAA"] == D(5)
    assert result.target_basket["SEC-BBB"] == 0
    assert result.opening_sizing["unallocated_core_budget"] == "0"


def test_unavailable_first_entry_reserves_full_priority_budget():
    state, plan, projection, refs = with_held()
    refs = replace(refs, prices={sid: value for sid, value in refs.prices.items() if sid != "SEC-AAA"})
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.target_basket["SEC-AAA"] == result.target_basket["SEC-BBB"] == 0
    assert result.opening_sizing["entries"][0]["status"] == "REFERENCE_UNAVAILABLE"
    assert Fraction(result.opening_sizing["entries"][0]["budget"]) == 600


def test_missing_core_reference_keeps_nonopening_target_and_blocks_all_buys(monkeypatch):
    state, plan, projection, refs = with_held()
    refs = replace(refs, prices={sid: value for sid, value in refs.prices.items() if sid != "HELD"})
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.target_basket["HELD"] == projection.target_basket["HELD"]
    assert result.target_basket["SEC-AAA"] == result.target_basket["SEC-BBB"] == 0
    assert result.opening_sizing["allocation_status"] == "CORE_REFERENCE_UNAVAILABLE"
    assert result.opening_sizing["nonopening_core_reference_value"] is None
    assert result.opening_sizing["unallocated_core_budget"] is None
    assert all(item["budget"] is None for item in result.opening_sizing["entries"])
    assert limits.unavailable_opening_intents(result) == {
        "SEC-AAA": "CORE_REFERENCE_UNAVAILABLE", "SEC-BBB": "CORE_REFERENCE_UNAVAILABLE"}
    select(monkeypatch)
    for sid in result.opening_sizing["references"]["symbols"]:
        with pytest.raises(limits.ProtectedReferenceUnavailable):
            limits.order_terms_for(result, sid)


def test_missing_bil_reference_only_blocks_bil_buy(monkeypatch):
    state, plan, projection, refs = protected_case()
    refs = replace(refs, prices={sid: value for sid, value in refs.prices.items() if sid != "SENTINEL:BIL"})
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.opening_sizing["allocation_status"] == "READY"
    assert result.target_basket == {"SEC-AAA": D(27), "SEC-BBB": D(27)}
    select(monkeypatch)
    assert limits.order_terms_for(result, "SEC-AAA").limit_price == D(101)
    with pytest.raises(limits.ProtectedReferenceUnavailable):
        limits.order_terms_for(result, "SENTINEL:BIL")


def test_canonical_equity_scalar_rejects_self_consistent_scale_tamper(monkeypatch):
    state, plan, projection, refs = protected_case()
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    select(monkeypatch)
    limits.validate_allocation(result, plan=plan, canonical_shadow_equity=D(100000))
    with pytest.raises(projections.TargetProjectionRefused, match="canonical shadow equity"):
        limits.validate_allocation(result, plan=plan, canonical_shadow_equity=D(100001))


@pytest.mark.parametrize("missing", ["HELD", "SENTINEL:BIL"])
def test_missing_buy_reference_does_not_block_observed_exact_sell_instrument(monkeypatch, missing):
    import asyncio
    from sentinel.paper import targets
    from sentinel.execution import feed_inputs
    from sentinel.execution.contract import BrokerInstrument, BrokerObservation, BrokerPosition, Completeness
    from datetime import datetime, timezone
    state, plan, _projection, _refs = with_held()
    plan = replace(plan, target_basket={**plan.target_basket, "SENTINEL:BIL": D(10)})
    projection = base(state, plan)
    refs = references(plan, projection)
    refs = replace(refs, prices={sid: value for sid, value in refs.prices.items() if sid != missing})
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    instrument = BrokerInstrument("HELD", "HLD", "asset-HELD")
    observation = BrokerObservation(observed_at=datetime.now(timezone.utc), orders=(),
        positions=(BrokerPosition(instrument, D(600)),), completeness=Completeness.COMPLETE)
    select(monkeypatch)
    monkeypatch.setattr(projections, "load_projection", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(feed_inputs, "metadata", lambda *_: {})
    looked_up = []
    async def resolve(*, security_id, symbol):
        looked_up.append(security_id)
        assert security_id not in {"HELD", "SENTINEL:BIL"}
        return BrokerInstrument(security_id, symbol, "asset-" + security_id)
    broker = SimpleNamespace(resolve_instrument=resolve)
    mapped = asyncio.run(targets._instrument_map(None, broker, state, plan, observation,
                                                target_basket=result.target_basket))
    assert mapped["HELD"] == instrument
    assert "SENTINEL:BIL" not in mapped
    assert (looked_up == []) == (missing == "HELD")


def test_nonopening_overallocation_refuses():
    state, plan, projection, refs = with_held()
    refs = replace(refs, prices={**refs.prices, "HELD": D(102)})
    with pytest.raises(projections.TargetProjectionRefused, match="exceeds"):
        limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))


def test_no_opening_intents_still_have_protected_held_and_bil_limits(monkeypatch):
    state, plan = case(entries=0, exposure="0")
    plan = replace(plan, target_basket={"SENTINEL:BIL": D(1000)})
    projection = base(state, plan)
    refs = references(plan, projection)
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    select(monkeypatch)
    monkeypatch.setattr(projections, "load_projection", lambda *_args, **_kwargs: result)
    projections.assert_projection(None, plan=plan, projection=result, through_session=plan.effective_session)
    assert result.target_basket == projection.target_basket
    assert result.opening_sizing["limits"]["SENTINEL:BIL"] == "99.99"


@pytest.mark.parametrize("cap", [0, 100, 500])
def test_fixed_bil_target_fits_its_complete_cash_budget(monkeypatch, cap):
    state, plan = case(entries=0, exposure="0")
    plan = replace(plan, target_basket={"SENTINEL:BIL": D(1000)})
    projection = base(state, plan)
    refs = references(plan, projection)
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(cap))
    select(monkeypatch, str(cap))
    term = limits.order_terms_for(result, "SENTINEL:BIL")
    assert result.target_basket == projection.target_basket
    assert D(1000) * term.limit_price + limits.HEADROOM <= plan.account_nav
    assert result.opening_sizing["fixed_legs"] == [{
        "security_id": "SENTINEL:BIL", "kind": "BIL", "target_quantity": "1000",
        "budget": "100000", "raw_cap": str(D(100) * (D(10000) + D(cap)) / D(10000)),
        "limit": "99.99", "status": "READY"}]
    limits.validate_allocation(result, plan=plan, canonical_shadow_equity=D(100000))


def test_fixed_core_limit_retains_quantity_and_opening_priority(monkeypatch):
    state, plan, projection, refs = with_held()
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    select(monkeypatch)
    term = limits.order_terms_for(result, "HELD")
    assert result.target_basket == {"HELD": D(544), "SEC-AAA": D(5), "SEC-BBB": D(0)}
    assert term.limit_price == D("99.99")
    assert result.target_basket["HELD"] * term.limit_price + limits.HEADROOM <= D(54400)
    assert [Fraction(item["budget"]) for item in result.opening_sizing["entries"]] == [600, 0]
    assert result.opening_sizing["fixed_legs"][0]["budget"] == "54400"


@pytest.mark.parametrize("nav,quantity", [("1", "1"), ("1.00001", "1000000")])
def test_fixed_unaffordable_limit_preserves_quantity_and_defers_only_buy(monkeypatch, nav, quantity):
    state, plan = case(entries=0, exposure="0")
    plan = replace(plan, account_nav=D(nav), target_basket={"SENTINEL:BIL": D(quantity)})
    projection = base(state, plan)
    refs = references(plan, projection)
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.target_basket == projection.target_basket
    assert result.opening_sizing["fixed_legs"][0]["status"] == "BUDGET_UNAVAILABLE"
    assert "SENTINEL:BIL" not in result.opening_sizing["limits"]
    select(monkeypatch)
    with pytest.raises(limits.ProtectedReferenceUnavailable):
        limits.order_terms_for(result, "SENTINEL:BIL")


def test_fixed_bil_budget_requires_immutable_plan_nav(monkeypatch):
    state, plan = case(entries=0, exposure="0")
    plan = replace(plan, target_basket={"SENTINEL:BIL": D(1000)})
    projection = base(state, plan)
    refs = references(plan, projection)
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    derived, fixed = limits._projection_limits(result, refs, limits.ProtectedLimitPolicy(100),
        account_nav=D(200000), target_exposure=D(0), opening=set())
    changed = replace(result, opening_sizing={**result.opening_sizing, "account_nav": "200000",
        "fixed_legs": fixed, "limits": {sid: str(value) for sid, value in derived.items()}})
    assert limits.validate_projection(changed)[1] == refs  # Internal arithmetic alone is not plan authority.
    select(monkeypatch)
    with pytest.raises(projections.TargetProjectionRefused, match="allocation"):
        limits.validate_allocation(changed, plan=plan, canonical_shadow_equity=D(100000))


@pytest.mark.parametrize("mode", [None, opening_sizing.FINAL_MODE, opening_sizing.UNAVAILABLE_MODE,
                                 opening_sizing.ZERO_MODE])
def test_pending_dispatch_preserves_absent_and_legacy_modes(mode):
    projection = SimpleNamespace(opening_sizing=None if mode is None else {"mode": mode})
    assert limits.unavailable_opening_intents(projection) == {}
    assert limits.unavailable_opening_intents(None) == {}


def test_pending_dispatch_does_not_accept_unknown_or_malformed_protected_mode():
    for mode in ["UNKNOWN", limits.PROTECTED_MODE]:
        with pytest.raises(projections.TargetProjectionRefused):
            limits.unavailable_opening_intents(SimpleNamespace(opening_sizing={"mode": mode}))


def test_terms_require_exact_current_policy_and_derived_limit(monkeypatch):
    state, plan, projection, refs = protected_case()
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    select(monkeypatch)
    terms = limits.order_terms_for(result, "SEC-AAA")
    assert terms.order_type == "limit" and terms.time_in_force == "day" and terms.limit_price == D(101)
    changed = replace(result, opening_sizing={**result.opening_sizing, "limits": {"SEC-AAA": "102"}})
    with pytest.raises(projections.TargetProjectionRefused, match="allocation"):
        limits.order_terms_for(changed, "SEC-AAA")
    select(monkeypatch, "101")
    with pytest.raises(projections.TargetProjectionRefused, match="configuration"):
        limits.order_terms_for(result, "SEC-AAA")


def test_explicit_dispatch_keeps_historical_reference_out_of_quote_port(monkeypatch):
    import asyncio
    state, plan, projection, refs = protected_case()
    select(monkeypatch)
    broker = SimpleNamespace(opening_prices=lambda **_: pytest.fail("quote GET"))
    assert asyncio.run(opening_sizing.prices_for_plan(None, state=state, plan=plan, broker=broker)) is None
    assert opening_sizing.resolve(state, plan, projection, refs).opening_sizing["mode"] == limits.PROTECTED_MODE
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY")
    with pytest.raises(projections.TargetProjectionRefused, match="require"):
        opening_sizing.resolve(state, plan, projection, refs)


class ReferenceConnection:
    def __init__(self, stock_rows, bil_rows=None):
        self.stock_rows = stock_rows
        self.bil_rows = [(100,)] if bil_rows is None else bil_rows
        self.calls = []
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def execute(self, sql, params):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT ")
        assert "close_unadjusted" in sql
        self.rows = self.bil_rows if "benchmark" in sql else list(self.stock_rows)
    def fetchall(self):
        return self.rows


def source_fixture(monkeypatch, plan):
    from sentinel.execution import feed_inputs
    pub = SimpleNamespace(version=plan.data_version, window_end=str(plan.decision_session))
    @contextmanager
    def pinned(*_args, **_kwargs):
        yield pub
    resolver = SimpleNamespace(ticker_for_security=lambda sid, _day: sid.replace("SEC-", ""),
        resolve=lambda symbol, _day: "SEC-" + symbol)
    manifest = SimpleNamespace(snapshot_id="a"*64, provider="ALPACA_OPENFIGI", model_dump=lambda **_: {"source": "bound"})
    monkeypatch.setattr(feed_inputs, "pinned", pinned)
    monkeypatch.setattr(feed_inputs, "is_rolling", lambda _: True)
    pub.authority_reads = []
    def authorities(connection, current, *, session):
        assert current is pub and session == str(plan.effective_session)
        pub.authority_reads.append((connection, session))
        return SimpleNamespace(candidate_id="candidate", manifest=manifest, resolver=resolver), session, str(plan.decision_session), resolver
    monkeypatch.setattr(feed_inputs, "_snapshot_identity_authorities", authorities)
    monkeypatch.setattr(feed_inputs, "resolver", lambda *_args, **_kwargs: SimpleNamespace(provider_asset_ids={"SEC-AAA": "asset-a", "SEC-BBB": "asset-b"}))
    monkeypatch.setattr(decision, "publication_fingerprint", lambda _: plan.publication_fingerprint)
    return pub


def test_source_factory_re_reads_raw_rows_and_revalidation_detects_price_edit(monkeypatch):
    state, plan, projection, _refs = protected_case()
    pub = source_fixture(monkeypatch, plan)
    conn = ReferenceConnection([("SEC-AAA", "AAA", 100), ("SEC-BBB", "BBB", 100)])
    refs = limits.build_references(conn, plan=plan, projection=projection)
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    select(monkeypatch)
    assert limits.revalidate_references(conn, plan=plan, projection=result) == refs
    assert len(conn.calls) == 4
    assert len(pub.authority_reads) == 2  # Fresh canonical context on each invocation.
    conn.stock_rows[0] = ("SEC-AAA", "AAA", 101)
    with pytest.raises(projections.TargetProjectionRefused, match="changed"):
        limits.revalidate_references(conn, plan=plan, projection=result)


def test_source_factory_refuses_publication_drift_before_raw_read(monkeypatch):
    _state, plan, projection, _refs = protected_case()
    pub = source_fixture(monkeypatch, plan)
    pub.version += 1
    conn = ReferenceConnection([])
    with pytest.raises(projections.TargetProjectionRefused, match="publication"):
        limits.build_references(conn, plan=plan, projection=projection)
    assert conn.calls == []


def test_source_factory_refuses_duplicate_or_rebound_identity(monkeypatch):
    _state, plan, projection, _refs = protected_case()
    source_fixture(monkeypatch, plan)
    for rows in [[("SEC-AAA", "AAA", 100)] * 2, [("SEC-AAA", "AAA", None)] * 2, [("SEC-AAA", "BBB", 100)]]:
        with pytest.raises(projections.TargetProjectionRefused, match="ambiguous"):
            limits.build_references(ReferenceConnection(rows), plan=plan, projection=projection)


def test_missing_source_rows_remain_explicit_buy_unavailability(monkeypatch):
    state, plan, projection, _refs = protected_case()
    source_fixture(monkeypatch, plan)
    refs = limits.build_references(ReferenceConnection([], bil_rows=[]), plan=plan, projection=projection)
    assert refs.prices == {}
    result = limits.resolve_protected(state, plan, projection, refs, limits.ProtectedLimitPolicy(100))
    assert result.opening_sizing["limits"] == {}
    assert limits.unavailable_opening_intents(result) == {
        "SEC-AAA": "REFERENCE_UNAVAILABLE", "SEC-BBB": "REFERENCE_UNAVAILABLE"}


def _broken(function, before, after):
    original = textwrap.dedent(inspect.getsource(function))
    assert original.count(before) == 1
    namespace = {}
    exec(compile(original.replace(before, after), '<broken-protection>', 'exec'), function.__globals__, namespace)
    return namespace[function.__name__]


def test_reviewed_cap_ceiling_falsifier(monkeypatch):
    monkeypatch.setattr(limits.ProtectedLimitPolicy, "__post_init__", _broken(
        limits.ProtectedLimitPolicy.__post_init__, "not 0 <= self.cap_bps <= 500", "self.cap_bps < 0"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_cap_above_reviewed_ceiling_refuses()


def test_fixed_budget_ceiling_falsifier(monkeypatch):
    monkeypatch.setattr(limits, "_projection_limits", _broken(limits._projection_limits,
        'min(Fraction(raw_cap), (budget - Fraction(HEADROOM)) / Fraction(quantity))', 'Fraction(raw_cap)'))
    with pytest.raises(AssertionError):
        test_fixed_bil_target_fits_its_complete_cash_budget(monkeypatch, 100)


def test_fixed_budget_plan_nav_falsifier(monkeypatch):
    monkeypatch.setattr(limits, "_validate_allocation", _broken(limits._validate_allocation,
        'or account_nav != Fraction(plan.account_nav)', 'or False'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_fixed_bil_budget_requires_immutable_plan_nav(monkeypatch)


def test_fixed_nonpositive_tick_availability_falsifier(monkeypatch):
    monkeypatch.setattr(limits, "_projection_limits", _broken(limits._projection_limits,
        'if rounded > 0:', 'if True:'))
    with pytest.raises(AssertionError):
        test_fixed_unaffordable_limit_preserves_quantity_and_defers_only_buy(monkeypatch, "1.00001", "1000000")


def test_action_evidence_falsifier(monkeypatch):
    monkeypatch.setattr(limits, "share_action_factor", _broken(
        projections.share_action_factor, "if multiplier != 1:", "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_nonunit_share_factor_requires_durable_event_evidence()


def test_native_source_id_falsifier(monkeypatch):
    monkeypatch.setattr(limits.PriorCloseReferences, "__post_init__", _broken(
        limits.PriorCloseReferences.__post_init__,
        'if self.source_provider == "ALPACA_OPENFIGI" and', 'if False and'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_openfigi_stock_ids_cannot_silently_fall_back_to_symbol_only()


def test_unavailable_core_buy_guard_falsifier(monkeypatch):
    monkeypatch.setattr(limits.ProtectedOrderTerms, "for_security", _broken(
        limits.ProtectedOrderTerms.for_security,
        'if self.allocation_status == "CORE_REFERENCE_UNAVAILABLE":', 'if False:'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_missing_core_reference_keeps_nonopening_target_and_blocks_all_buys(monkeypatch)


def test_core_envelope_falsifier_detects_removed_guard(monkeypatch):
    original = inspect.getsource(limits.resolve_protected)
    target = 'if not missing_core and held - retained_value > max(Fraction(0), core_budget - retained_value):'
    assert original.count(target) == 1
    namespace = {}
    exec(compile(original.replace(target, 'if False:'), '<removed-core-envelope>', 'exec'),
         limits.resolve_protected.__globals__, namespace)
    monkeypatch.setattr(limits, "resolve_protected", namespace["resolve_protected"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_nonopening_overallocation_refuses()


def test_priority_falsifier_detects_released_unavailable_budget(monkeypatch):
    original = inspect.getsource(limits.resolve_protected)
    target = 'available -= budget'
    assert original.count(target) == 1
    namespace = {}
    exec(compile(original.replace(target, 'available -= 0'), '<released-priority>', 'exec'),
         limits.resolve_protected.__globals__, namespace)
    monkeypatch.setattr(limits, "resolve_protected", namespace["resolve_protected"])
    with pytest.raises(AssertionError):
        test_unavailable_first_entry_reserves_full_priority_budget()
