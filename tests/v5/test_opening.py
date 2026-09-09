"""Opening prices, immutable dollar plans and recoverable execution sizing."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from sentinel.authority import RolloutMode, RolloutState
from sentinel.core import decision
from sentinel.execution import opening_sizing, target_reprojection as projections
from sentinel.execution.opening_prices import OpeningPrices, OpeningPriceUnavailable, parse_bars, ENDPOINT
from sentinel.execution.plan import OpeningIntent
from sentinel.execution.contract import BrokerInstrument
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.v5.test_v5 import canonical
from tests.sentinel.test_production_decision import (
    DECISION_SESSION, EFFECTIVE_SESSION, _account, _binding, _episode,
    _observation, _publication)


def case(*, cash=100000., entries=1, sale=False, exposure="1"):
    env = canonical()
    state = PortfolioState.from_dict(env.wealth_core)
    state.cash = cash
    pending, ids = [], []
    for slot in range(entries):
        ticker = ("AAA", "BBB")[slot]; sid = "SEC-"+ticker
        state.reserve_slot(slot, sid, ticker, "issuer-"+sid)
        ids.append((sid, ticker))
        pending.append(PendingOrder(Operation.OPEN_SLOT_POSITION, sid, ticker,
            slot, 0., DECISION_SESSION.isoformat(), "ENTRY_DURABLE_RANK", intended_dollars=5000.))
    if sale:
        state.episodes[19] = _episode(19, "SEC-X", "X", 10.)
        state.slots[19].occupied_by = "SEC-X"
        pending.append(PendingOrder(Operation.CLOSE_POSITION, "SEC-X", "X", 19, 10.,
            DECISION_SESSION.isoformat(), "STOP"))
        ids.append(("SEC-X", "X"))
    for sid, ticker in ids:
        env.feed["series"][sid] = {"security_id": sid, "ticker": ticker,
            "issuer_id": "issuer-"+sid, "split_factor": 1., "sessions": [],
            "session_indices": [], "signal_closes": [], "raw_closes": [], "volumes": []}
    env.pending = [p.to_dict() for p in pending]
    env.wealth_core = state.to_dict()
    env.last_processed_session = DECISION_SESSION.isoformat(); env.data_version = 7
    env.last_decision = {"session": DECISION_SESSION.isoformat(), "target_core_exposure": float(exposure)}
    env.last_evidence = {"wealth_core": {"estimated_equity": 100000.}}
    plan = decision.build_execution_plan(env, _binding(), _publication(),
        _account(equity="100000"), _observation(),
        {sid: D(100) for sid, _ in ids}, dict(ids), DECISION_SESSION, EFFECTIVE_SESSION,
        defensive_security=None,
        rollout_state=RolloutState(mode=RolloutMode.CONTROLLER, version=1,
                                  certificate_sha256="a"*64)).plan
    return env, plan


def prices(env, plan, *, price="100", sale_price="100"):
    opened, _ = calendar.session_window(plan.effective_session)
    target = decision.shadow_target(env)
    required = opening_sizing.required_prices(env, plan)
    return OpeningPrices(plan.effective_session, opened, opened+timedelta(minutes=1),
        {sid: D(sale_price if sid == "SEC-X" else price) for sid in required},
        {sid: target.tickers[sid] for sid in required})


def base(env, plan, *, multipliers=None, evidence=()):
    target = decision.shadow_target(env)
    return projections.project_target(plan, through_session=plan.effective_session,
        action_multipliers=multipliers or {}, action_evidence=evidence,
        canonical_target_shares=target.shares, pending_open_shares=target.pending_open_shares,
        held_shares=target.held_shares, pending_close_shares=target.pending_close_shares)


def test_close_plan_preserves_dollars_and_identity_binds_them():
    env, plan = case(entries=2)
    assert [i.intended_dollars for i in plan.opening_intents] == [D(5000), D(5000)]
    assert plan.target_basket == {"SEC-AAA": D(0), "SEC-BBB": D(0)}
    assert plan.to_dict()["opening_intents"] == [i.to_dict() for i in plan.opening_intents]
    changed = replace(plan, opening_intents=(OpeningIntent("SEC-AAA", 0, D(5001)), plan.opening_intents[1]))
    assert changed.fingerprint() != plan.fingerprint()
    with pytest.raises(ValueError, match="zero provisional"):
        replace(plan, target_basket={"SEC-AAA": D(49), "SEC-BBB": D(0)})
    with pytest.raises(ValueError, match="slot order"):
        replace(plan, opening_intents=tuple(reversed(plan.opening_intents)))


@pytest.mark.parametrize("price,expected", [("50", 99), ("100", 49), ("200", 24), ("6000", 0)])
def test_opening_gaps_resolve_whole_shares_and_preserve_canonical_state(price, expected):
    env, plan = case()
    before = env.to_dict()
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price=price))
    assert result.target_basket["SEC-AAA"] == expected
    assert result.opening_sizing["entries"][0]["core_shares"] == str(expected)
    assert env.to_dict() == before


def test_sale_proceeds_and_slot_order_fund_the_opening_once():
    env, plan = case(cash=100., entries=2, sale=True)
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan))
    assert result.target_basket == {"SEC-AAA": D(10), "SEC-BBB": D(0), "SEC-X": D(0)}
    assert D(result.opening_sizing["cash_after_entries"]) == D(98)
    assert D(result.opening_sizing["sales"][0]["proceeds"]) == D(999)
    assert D(result.opening_sizing["entries"][0]["cash_before"]) == 1099


def test_cash_cushion_is_released_at_open():
    env, plan = case(cash=232.45)
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price="166.92"))
    assert result.target_basket["SEC-AAA"] == 1


def test_opening_receivable_funding_uses_only_due_claims():
    from stock_strategy_shared.wealth_core.ledger import Ledger
    env, plan = case(cash=0.)
    ledger = Ledger()
    for sid, amount, due in (("OLD", 200., 0), ("LATER", 1000., 1)):
        ledger.receivables.append({"security_id": sid, "ticker": sid,
            "amount": amount, "accrued_session": "2026-08-10", "due_in": due})
    env.ledger = ledger.to_dict()
    plan = replace(plan, shadow_snapshot_hash=env.state_hash)
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan))
    assert result.target_basket["SEC-AAA"] == 1
    assert D(result.opening_sizing["due_dividends"]) == 200


def test_split_units_leave_pending_dollars_invariant():
    env, plan = case()
    scalar = {"security_id": "SEC-AAA", "session": EFFECTIVE_SESSION.isoformat(),
        "source_row_id": "split", "action": "split", "value": "0.1", "canonical_multiplier": "0.1"}
    b = base(env, plan, multipliers={"SEC-AAA": D("0.1")}, evidence=(scalar,))
    result = opening_sizing.resolve(env, plan, b, prices(env, plan, price="1000"))
    assert result.target_basket["SEC-AAA"] == 4
    assert result.cancelled_pending_opens == {}
    assert result.opening_sizing["intents"][0]["intended_dollars"] == "5000.0"


def test_controller_exposure_scales_resolved_opening_shares():
    env, plan = case(exposure="0.55")
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price="50"))
    assert result.target_basket["SEC-AAA"] == 54
    assert result.opening_sizing["entries"][0]["core_shares"] == "99"


def test_zero_exposure_has_durable_zero_sizing():
    env, plan = case(exposure="0")
    result = opening_sizing.resolve(env, plan, base(env, plan), None)
    assert result.target_basket["SEC-AAA"] == 0
    assert result.opening_sizing["mode"] == "ZERO_EXPOSURE"


def test_missing_opening_evidence_and_different_canonical_intent_refuse():
    env, plan = case()
    with pytest.raises(OpeningPriceUnavailable):
        opening_sizing.resolve(env, plan, base(env, plan), None)
    env.wealth_core["cash"] = 1.
    with pytest.raises(projections.TargetProjectionRefused, match="canonical plan"):
        opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan))


def bar_payload():
    opened, _ = calendar.session_window(EFFECTIVE_SESSION)
    return {"bars": {"AAA": [{"t": opened.isoformat(), "o": "50", "v": 100}]},
            "next_page_token": None}


def parse(payload):
    opened, _ = calendar.session_window(EFFECTIVE_SESSION)
    return parse_bars(payload, session=EFFECTIVE_SESSION,
        instruments={"SEC-AAA": BrokerInstrument("SEC-AAA", "AAA", "asset")},
        observed_at=opened+timedelta(minutes=1))


def test_opening_evidence_round_trips_with_exact_prices():
    result = parse(bar_payload())
    assert result.prices == {"SEC-AAA": D(50)}
    assert OpeningPrices.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    with pytest.raises(TypeError):
        result.prices["SEC-AAA"] = D(10)


@pytest.mark.parametrize("fault", ["wrong_minute", "zero_open", "zero_volume", "nan",
                                  "partial", "missing_page_proof", "missing", "duplicate", "extra"])
def test_invalid_opening_market_evidence_refuses(fault):
    payload = bar_payload(); row = payload["bars"]["AAA"][0]
    if fault == "wrong_minute": row["t"] = "2026-08-12T13:29:00+00:00"
    elif fault == "zero_open": row["o"] = 0
    elif fault == "zero_volume": row["v"] = 0
    elif fault == "nan": row["o"] = "NaN"
    elif fault == "partial": payload["next_page_token"] = "next"
    elif fault == "missing_page_proof": del payload["next_page_token"]
    elif fault == "missing": payload["bars"] = {}
    elif fault == "duplicate": payload["bars"]["AAA"].append(dict(row))
    elif fault == "extra": payload["bars"]["BBB"] = [dict(row)]
    with pytest.raises(OpeningPriceUnavailable): parse(payload)


def test_projection_json_round_trip_and_tamper_refusal():
    env, plan = case()
    result = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price="50"))
    raw = json.loads(json.dumps(result.payload()))
    assert projections._decode(raw, plan_id=plan.plan_id, session=plan.effective_session) == result
    raw["opening_sizing"]["entries"][0]["account_shares"] = "10000"
    with pytest.raises(projections.TargetProjectionRefused, match="fingerprint"):
        projections._decode(raw, plan_id=plan.plan_id, session=plan.effective_session)


@pytest.mark.asyncio
async def test_alpaca_reads_raw_sip_opening_minute_after_it_completes():
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    opened, _ = calendar.session_window(EFFECTIVE_SESSION)
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, *, headers, params):
            calls.append((url, params))
            return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                   json=lambda **kwargs: bar_payload())
    broker = AlpacaExecutionBroker(api_key="test", secret_key="test",
        base_url="https://paper-api.alpaca.markets", http_provider=lambda: SimpleNamespace(AsyncClient=Client),
        clock_provider=lambda: opened+timedelta(minutes=1))
    result = await broker.opening_prices(session=EFFECTIVE_SESSION,
        instruments={"SEC-AAA": BrokerInstrument("SEC-AAA", "AAA", "asset")})
    assert result.prices["SEC-AAA"] == 50
    assert calls[0][0] == ENDPOINT
    assert calls[0][1] == {"symbols": "AAA", "feed": "sip", "adjustment": "raw",
        "timeframe": "1Min", "start": opened.isoformat(),
        "end": (opened+timedelta(minutes=1, microseconds=-1)).isoformat(),
        "asof": EFFECTIVE_SESSION.isoformat(), "sort": "asc", "limit": 10000, "currency": "USD"}
    broker._clock_provider = lambda: opened
    with pytest.raises(OpeningPriceUnavailable):
        await broker.opening_prices(session=EFFECTIVE_SESSION,
            instruments={"SEC-AAA": BrokerInstrument("SEC-AAA", "AAA", "asset")})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_reuses_durable_opening_evidence(monkeypatch):
    env, plan = case()
    evidence = prices(env, plan, price="50")
    result = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    monkeypatch.setattr(opening_sizing, "load_projection", lambda *a, **kw: result)
    read = await opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=object())
    assert read == evidence
    assert opening_sizing.resolve(env, plan, base(env, plan), read) == result


def test_dollar_intents_cannot_use_empty_book_authority_bypass():
    from sentinel.paper.targets import _plan_deltas, _provably_clean_empty_noop
    env, plan = case()
    observation = _observation()
    deltas = _plan_deltas(target_basket=plan.target_basket, observation=observation,
                         minimum_quantity_increment=D(1))
    assert not _provably_clean_empty_noop(deltas=deltas, commands=(),
        observation=observation, opening_intents=plan.opening_intents)


def test_opening_prices_use_fresh_execute_read_authority():
    from sentinel.execution.authority_gate import _authority_operation
    from sentinel.execution.guarded import BrokerOperation
    from tests.sentinel.test_guarded_execution_broker import manual_grant, automation_grant
    for grant in (manual_grant(), automation_grant()):
        assert _authority_operation(grant, BrokerOperation.OPENING_PRICES) == "EXECUTE_READ"


def test_entry_submit_order_preserves_slots_after_reductions():
    from sentinel.execution import commands, executor
    deltas = [commands.Delta(sid, D(0), D(0), D(0), D(remaining),
                            commands.DeltaClass.ACTIONABLE)
              for sid, remaining in (("SEC-A", 1), ("SEC-Z", 1), ("SEC-X", -1))]
    ordered = executor.order_of_operations(deltas, opening_intents=(
        OpeningIntent("SEC-Z", 0, D(5000)), OpeningIntent("SEC-A", 1, D(5000))))
    assert [item.security_id for item in ordered] == ["SEC-X", "SEC-Z", "SEC-A"]


def test_executor_requires_opening_projection_before_execution():
    from contextlib import nullcontext
    from unittest.mock import AsyncMock, patch
    from sentinel.execution import executor
    from tests.sentinel.test_journal_and_reconcile import DEPLOY
    env, plan = case()
    with (patch.object(executor.journal, "writer_lock", return_value=nullcontext()),
          patch.object(executor, "_assert_current_plan"),
          patch.object(executor, "_execute_session_locked", new=AsyncMock())):
        with pytest.raises(ValueError, match="opening-time projection"):
            asyncio.run(executor.execute_session(conn=None, broker=object(),
                deployment=DEPLOY, plan=plan, instruments={}, today=EFFECTIVE_SESSION))


def test_persisted_unit_only_projection_is_insufficient_for_dollar_intent():
    from unittest.mock import patch
    env, plan = case()
    unit_only = base(env, plan)
    with patch.object(projections, "load_projection", return_value=unit_only):
        with pytest.raises(projections.TargetProjectionRefused, match="sizing evidence"):
            projections.assert_projection(None, plan=plan, projection=unit_only,
                                          through_session=EFFECTIVE_SESSION)


def test_paper_target_path_consumes_opening_evidence(monkeypatch):
    from sentinel.paper import targets
    from sentinel.execution import journal
    monkeypatch.setattr(journal, "load_commands", lambda *args: [])
    env, plan = case()
    b = SimpleNamespace(capabilities=SimpleNamespace(minimum_quantity_increment=D(1)))
    result = targets._target_projection_or_refuse(None, state=env, plan=plan,
        binding=_binding(), broker=b, through=EFFECTIVE_SESSION, actions=lambda sid: D(1),
        target_actions=lambda sid: D(1), persist_projection=False,
        opening_prices=prices(env, plan, price="50"))
    assert result.target_basket["SEC-AAA"] == 99
    assert result.opening_sizing["prices"]["source"] == "ALPACA_SIP_RAW_OPENING_MINUTE_V1"


@pytest.mark.asyncio
async def test_missing_opening_price_is_a_retryable_paper_refusal(monkeypatch):
    from sentinel.paper.execution import _opening_prices_or_retry
    from sentinel.paper.model import PaperRetryableRefused
    async def unavailable(*args, **kwargs):
        raise OpeningPriceUnavailable("opening minute incomplete")
    monkeypatch.setattr(opening_sizing, "prices_for_plan", unavailable)
    env, plan = case()
    with pytest.raises(PaperRetryableRefused, match="incomplete"):
        await _opening_prices_or_retry(None, state=env, plan=plan, broker=object())


@pytest.mark.parametrize("fault", ["timeout", "unavailable", "rate_limit", "malformed"])
@pytest.mark.asyncio
async def test_opening_transport_failure_defers_execution(fault):
    import httpx
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    opened, _ = calendar.session_window(EFFECTIVE_SESSION)
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            if fault == "timeout": raise httpx.ReadTimeout("test")
            return httpx.Response({"unavailable": 503, "rate_limit": 429,
                                   "malformed": 200}[fault], content=b"invalid json",
                                  request=httpx.Request("GET", url))
    broker = AlpacaExecutionBroker(api_key="test", secret_key="test",
        base_url="https://paper-api.alpaca.markets",
        http_provider=lambda: SimpleNamespace(AsyncClient=Client),
        clock_provider=lambda: opened+timedelta(minutes=1))
    with pytest.raises(OpeningPriceUnavailable):
        await broker.opening_prices(session=EFFECTIVE_SESSION,
            instruments={"SEC-AAA": BrokerInstrument("SEC-AAA", "AAA", "asset")})
