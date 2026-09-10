"""Local checks of real plan assembly and the external Alpaca service seam."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import multiprocessing
import signal

import pytest

from sentinel.authority import RolloutMode, RolloutState
from sentinel.binding import AccountBinding
from sentinel.core.decision import build_execution_plan
from sentinel.execution.contract import Side
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
from sentinel.feed.publication import Publication

from tests.internal_state import broker, market, oracles
from tests.internal_state.test_market import formed_state


@pytest.mark.parametrize("profile", ["paper", "live_cash"])
def test_selected_strategy_plan_broker_fills_and_cash_keep_shadow_history(profile):
    _, state = formed_state(7)
    before = deepcopy(state.to_dict())
    service = broker.BrokerService(profile)
    day = state.last_processed_session
    service.move(day + "T22:00:00+00:00")
    index = len(market.sessions(day)) - 1
    prices = {symbol: str(market.raw_price(symbol, index, 7)) for symbol in market.SYMBOLS}
    prices["BIL"] = str(100 + index / 100)
    service.prices(prices)
    adapter = broker.adapter(service)
    result = build_execution_plan(state,
        AccountBinding("lab", "alpaca", "SIM-ALPACA-1", 1),
        Publication(version=2, previous_version=1, run_id="synthetic", window_start=market.START,
                    window_end=day, evidence={"fixture": "test-only"}),
        asyncio.run(adapter.account_snapshot()), asyncio.run(adapter.observe()),
        {market.SECURITIES[s]: Decimal(price) for s, price in prices.items()},
        {sid: symbol for symbol, sid in market.SECURITIES.items()},
        date.fromisoformat(day), date.fromisoformat(calendar.next_session(day)),
        rollout_state=RolloutState(RolloutMode.CONTROLLER, 1, "synthetic-test-only"))
    plan = result.plan
    oracles.plan_commitment(state.to_dict(), plan.to_dict(), state.last_processed_session)
    plan_before = plan.fingerprint()
    assert any(quantity > 0 for quantity in plan.target_basket.values())
    cost = sum((quantity * Decimal(prices[next(s for s, value in market.SECURITIES.items() if value == sid)])
                for sid, quantity in plan.target_basket.items()), Decimal(0))
    assert 0 < cost <= plan.account_nav
    opened, _ = calendar.session_window(plan.effective_session)
    service.move((opened + timedelta(minutes=1)).isoformat())
    for sid, quantity in plan.target_basket.items():
        if quantity <= 0:
            continue
        symbol = next(s for s, value in market.SECURITIES.items() if value == sid)
        instrument = asyncio.run(adapter.resolve_instrument(security_id=sid, symbol=symbol))
        outcome = asyncio.run(adapter.submit(client_key="synthetic-" + symbol,
            instrument=instrument, side=Side.BUY, quantity=quantity))
        assert outcome.state == CommandState.ACKNOWLEDGED
    assert service.fill(partial=True) > 0
    assert service.fill() > 0
    service.cash(100)
    oracles.broker_accounting(service.snapshot())
    assert state.to_dict() == before
    assert plan.fingerprint() == plan_before


def test_external_broker_process_survives_adapter_replacement_and_response_loss():
    manager, service = broker.manager("paper")
    try:
        opened, _ = calendar.session_window(market.FIRST)
        service.move((opened + timedelta(minutes=1)).isoformat())
        adapter = broker.adapter(service)
        instrument = asyncio.run(adapter.resolve_instrument(security_id="STATE-S000", symbol="S000"))
        service.timeout()
        lost = asyncio.run(adapter.submit(client_key="synthetic-replay-key", instrument=instrument,
                                          side=Side.BUY, quantity=Decimal(2)))
        assert lost.state == CommandState.UNKNOWN
        assert service.fill() == 1
        found = asyncio.run(broker.adapter(service).find_by_client_key("synthetic-replay-key"))
        assert found.order.filled_quantity == Decimal(2)
        assert len(service.snapshot()["orders"]) == 1
        oracles.broker_accounting(service.snapshot())
    finally:
        manager.shutdown()


def test_real_process_death_leaves_broker_acceptance_observable():
    manager, service = broker.manager("paper")
    process = multiprocessing.get_context("spawn").Process(target=broker.killed_submitter, args=(service,))
    try:
        opened, _ = calendar.session_window(market.FIRST)
        service.move((opened + timedelta(minutes=1)).isoformat())
        process.start()
        process.join(10)
        assert process.exitcode == -signal.SIGKILL
        assert len(service.snapshot()["orders"]) == 1
        assert service.fill() == 1
        found = asyncio.run(broker.adapter(service).find_by_client_key("synthetic-kill-key"))
        assert found.order.state == CommandState.FILLED
        assert found.order.filled_quantity == Decimal(3)
        oracles.broker_accounting(service.snapshot())
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        manager.shutdown()
