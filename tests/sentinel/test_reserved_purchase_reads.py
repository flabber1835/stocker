"""Checks shared around native reads never share a financial book between purchases."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sentinel.execution import submission_group
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.authority_gate import _result_accounts
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerInstrument, Side
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, BrokerOperation, ExecutionBrokerGuard, GuardedExecutionBroker,
    ManualExecutionGrant, OrderEvidenceNotReady, PaperPreparationGrant,
)
from tests.sentinel.test_limit_day_transport import broker_for
from tests.sentinel.test_order_terms_schema import _compiled
from tests.sentinel.test_market_reservations import NOW, book


def setup_reads(monkeypatch, *, grant=None, revoke=None):
    commands = [SimpleNamespace(client_key=name, side=Side.BUY, notional=Decimal(10),
                                instrument=BrokerInstrument("SEC-" + name, name, "asset-" + name))
                for name in "ABCD"]
    routes = {"/v2/assets/" + c.instrument.broker_id: dict(id=c.instrument.broker_id,
              symbol=c.instrument.symbol, tradable=True, status="active", fractionable=True)
              for c in commands}
    routes["/v2/clock"] = dict(timestamp=NOW.isoformat(), is_open=True,
                               next_close=(NOW + timedelta(hours=3)).isoformat(),
                               next_open=(NOW + timedelta(days=1)).isoformat())
    inner, http = broker_for(AssetIdAlpacaExecutionBroker, routes=routes)
    timestamp = [NOW]
    monkeypatch.setattr(inner, "_now", lambda: timestamp[0])
    checks = []

    async def check(_grant, operation, result=None):
        phase = "before" if result is None else "after"
        checks.append((phase, operation))
        if revoke == phase:
            raise BrokerAuthorityRefused("revoked")

    guarded = GuardedExecutionBroker(inner=inner,
        grant=grant or ManualExecutionGrant("TEST", "plan", NOW.date(), True),
        guard=ExecutionBrokerGuard(check, check, check))
    return guarded, inner, http, timestamp, checks, commands


def test_four_reserved_orders_share_clock_and_rule_brackets(monkeypatch):
    guarded, _, http, now, checks, commands = setup_reads(monkeypatch)
    with submission_group.independent_dispatch_scope(commands):
        asyncio.run(guarded._prefetch_reserved_market_inputs(commands))
        assert [call[1] for call in http.calls] == ["/v2/clock", *["/v2/assets/asset-" + c.client_key for c in commands]]
        assert checks == [(phase, operation) for operation in (BrokerOperation.MARKET_CLOCK, BrokerOperation.ASSET_RULES)
                          for phase in ("before", "after")]
        for cmd in commands:
            clock, rules = guarded._take_market_inputs(cmd.client_key, cmd.instrument)
            assert clock.timestamp == now[0] and rules.instrument == cmd.instrument and rules.fractionable
            assert guarded._take_market_inputs(cmd.client_key, cmd.instrument) is None
        for cmd in commands:
            asyncio.run(guarded.market_clock())
            asyncio.run(guarded.asset_rules(instrument=cmd.instrument))
        assert len(checks[4:]) == 16


@pytest.mark.parametrize("change", ["expired", "clock-backwards", "instrument", "group", "closed", "stopped"])
def test_clock_and_rule_receipts_refuse_changed_context(monkeypatch, change):
    guarded, _, _, now, _, commands = setup_reads(monkeypatch)
    cmd = commands[0]
    with submission_group.independent_dispatch_scope(commands):
        asyncio.run(guarded._prefetch_reserved_market_inputs(commands))
        if change == "group":
            with submission_group.independent_dispatch_scope(commands):
                assert guarded._take_market_inputs(cmd.client_key, cmd.instrument) is None
            return
        if change == "stopped":
            submission_group.stop(cmd.client_key)
        now[0] += timedelta(seconds={"expired": 31, "clock-backwards": -1, "closed": 10800}.get(change, 0))
        instrument = commands[1].instrument if change == "instrument" else cmd.instrument
        assert guarded._take_market_inputs(cmd.client_key, instrument) is None


@pytest.mark.parametrize("fault", ["", "cash-account", "book-account", "uuid", "before", "after", "sent", "prepare"])
def test_funding_reads_both_endpoints_with_current_identity_per_unsent_key(monkeypatch, fault):
    grant = PaperPreparationGrant("TEST", NOW.date()) if fault == "prepare" else None
    guarded, inner, _, _, checks, commands = setup_reads(monkeypatch, grant=grant, revoke=fault)
    identity = BrokerAccountIdentity("alpaca", "TEST", {"id": "one"})
    account = BrokerAccountSnapshot(identity, Decimal(100), Decimal(100), Decimal(100), Decimal(1), "ACTIVE")
    observation = replace(book(), account_identity=identity)
    if fault == "cash-account":
        account = replace(account, identity=replace(identity, account_id="another"))
    if fault == "book-account":
        observation = replace(observation, account_identity=replace(identity, account_id="another"))
    if fault == "uuid":
        observation = replace(observation, account_identity=replace(identity, raw={"id": "two"}))
    snapshot = AsyncMock(return_value=account)
    observe = AsyncMock(return_value=observation)
    monkeypatch.setattr(inner, "account_snapshot", snapshot)
    monkeypatch.setattr(inner, "observe", observe)
    async def run():
        with submission_group.independent_dispatch_scope(commands):
            key = commands[0].client_key
            submission_group.checkpointed(key)
            if fault == "sent":
                submission_group.entering_transport(key)
            guarded._active_submit_keys.add(key)
            async with guarded.submission_lock:
                if fault:
                    with pytest.raises((BrokerAuthorityRefused, OrderEvidenceNotReady)):
                        await guarded._current_reserved_account(key)
                    assert guarded._take_reserved_observation(key, account) is None
                    assert snapshot.await_count == int(fault not in ("sent", "prepare", "before"))
                    assert observe.await_count == int(fault in ("book-account", "uuid", "after"))
                    return
                assert _result_accounts((account, observation)) == (account.identity, observation.account_identity)
                assert await guarded._current_reserved_account(key) is account
                assert guarded._take_reserved_observation(commands[1].client_key, account) is None
                assert guarded._take_reserved_observation(key, replace(account)) is None
                async def other_task():
                    return guarded._take_reserved_observation(key, account)
                assert await asyncio.create_task(other_task()) is None
                assert guarded._take_reserved_observation(key, account) is observation
                assert guarded._take_reserved_observation(key, account) is None
                sibling = commands[1].client_key
                guarded._active_submit_keys.add(sibling)
                submission_group.checkpointed(sibling)
                new_account = replace(account, cash=Decimal(82))
                new_book = replace(observation, observed_at=NOW + timedelta(seconds=1))
                snapshot.return_value = new_account
                observe.return_value = new_book
                assert await guarded._current_reserved_account(sibling) is new_account
                assert guarded._take_reserved_observation(sibling, new_account) is new_book
                assert (snapshot.await_count, observe.await_count) == (2, 2)
                assert checks == [("before", BrokerOperation.OBSERVE), ("after", BrokerOperation.OBSERVE)] * 2
    asyncio.run(run())


def test_native_renewal_after_group_prefetch_sees_withdrawn_eligibility(monkeypatch):
    from sentinel.execution.market_buy_policy import FRACTIONAL_MODE
    from tests.sentinel.test_market_buy_policy import MARKET_ENV
    for key, value in {**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE}.items():
        monkeypatch.setenv(key, value)
    guarded, inner, http, now, _, commands = setup_reads(monkeypatch)
    cmd = commands[0]
    identity = BrokerAccountIdentity("alpaca", "TEST")
    account = BrokerAccountSnapshot(identity, Decimal(100), Decimal(100), Decimal(100), Decimal(1), "ACTIVE")
    monkeypatch.setattr(inner, "account_snapshot", AsyncMock(return_value=account))
    monkeypatch.setattr(inner, "observe", AsyncMock(return_value=replace(book(), account_identity=identity)))
    route = "/v2/assets/" + cmd.instrument.broker_id
    async def fund(**_):
        now[0] += timedelta(seconds=31)
        http.routes[route]["fractionable"] = False
    guarded._market_buy_funding = fund
    guarded._issuer_admission_check = lambda **_: SimpleNamespace(allowed=True)
    async def run():
        with submission_group.independent_dispatch_scope(commands):
            await guarded._prefetch_reserved_market_inputs(commands)
            submission_group.checkpointed(cmd.client_key)
            with pytest.raises(OrderEvidenceNotReady, match="fractional"):
                await guarded.submit(client_key=cmd.client_key, instrument=cmd.instrument,
                                     side=cmd.side, quantity=None, notional=cmd.notional)
    asyncio.run(run())
    assert [step[1] for step in http.calls].count(route) == 2
    assert all(step[0] == "GET" for step in http.calls)


def test_native_account_uuid_and_group_owner_falsifiers(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, "_current_reserved_account", _compiled(
        GuardedExecutionBroker._current_reserved_account,
        'or observation.account_identity.raw.get("id") != account.identity.raw.get("id")', 'or False'))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_funding_reads_both_endpoints_with_current_identity_per_unsent_key(monkeypatch, "uuid")
    monkeypatch.setattr(GuardedExecutionBroker, "_take_market_inputs", _compiled(
        GuardedExecutionBroker._take_market_inputs, "owner is not submission_group.owner(key)", "False"))
    with pytest.raises(AssertionError):
        test_clock_and_rule_receipts_refuse_changed_context(monkeypatch, "group")
