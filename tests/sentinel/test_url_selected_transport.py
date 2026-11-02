"""URL selection is distinct from signed admission and a guarded send permit."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from live_authority_fixtures import live_fixture
from sentinel.config import LiveEndpointRefused, SentinelConfig, build_execution_broker
from sentinel.execution.alpaca import (
    FinancialGradeAlpacaExecutionBroker, HardenedAlpacaExecutionBroker,
    MalformedBrokerPayload, OriginalAlpaca,
)
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.certification import (
    AdapterNotCertified, certify_adapter, require_certified,
    require_certified_adapter,
)
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.trading_environment import TradingEnvironment
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response


PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
INSTRUMENT = BrokerInstrument("SEC-AAPL", "AAPL", "asset-aapl")


def adapter(fixture, *, adapter_type=AssetIdAlpacaExecutionBroker, http=None):
    return adapter_type(
        api_key="offline-test-key", secret_key="offline-test-secret",
        base_url=LIVE, live_admission=fixture.admission,
        resolve_security_id=lambda symbol, _as_of=None: "SEC-" + symbol,
        http_provider=(lambda: http) if http is not None else None)


@pytest.mark.parametrize("url,environment,namespace", [
    (PAPER, TradingEnvironment.PAPER, "alpaca"),
    ("https://API.ALPACA.MARKETS:443/", TradingEnvironment.LIVE, "alpaca-live"),
])
def test_url_is_the_only_environment_selector(url, environment, namespace):
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": url,
                                     "LIVE_TRADING_ENABLED": "false",
                                     "PAPER_ONLY": "true"})
    assert config.environment is environment
    assert config.broker_namespace == namespace
    assert config.base_url == config.trading_endpoint.base_url
    assert config.redacted()["environment"] == environment.value


def test_live_selection_without_admission_cannot_construct_execution_transport():
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE,
                                     "ALPACA_API_KEY": "offline-key",
                                     "ALPACA_SECRET_KEY": "offline-secret"})
    with pytest.raises(LiveEndpointRefused, match="separately validated"):
        build_execution_broker(config, resolve_security_id=lambda value: value)


def test_unknown_origin_refuses_before_credentials_are_read():
    class NoCredentialReads(dict):
        def get(self, key, default=None):
            if key in {"ALPACA_API_KEY", "ALPACA_SECRET_KEY"}:
                raise AssertionError("credential read before origin validation")
            return super().get(key, default)

    with pytest.raises(LiveEndpointRefused):
        SentinelConfig.from_env(NoCredentialReads(ALPACA_BASE_URL=LIVE + ".evil.test"))


def test_signed_live_factory_uses_a_distinct_instance_qualification():
    fixture = live_fixture()
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE,
                                     "ALPACA_API_KEY": "offline-key",
                                     "ALPACA_SECRET_KEY": "offline-secret"})
    broker = build_execution_broker(config, resolve_security_id=lambda value: value,
                                    live_admission=fixture.admission)
    identity = require_certified_adapter(broker, expected="alpaca-live")
    assert identity.mode == "ALPACA_LIVE"
    assert identity.conformance_suite == "sentinel.alpaca-live-software-conformance/1"
    assert broker.broker_namespace == "alpaca-live"
    with pytest.raises(AdapterNotCertified):
        require_certified("alpaca-live")
    with pytest.raises(AdapterNotCertified):
        certify_adapter(broker, name="alpaca", mode="ALPACA_PAPER")


def test_live_account_identity_uses_native_uuid_and_distinct_namespace():
    fixture = live_fixture()
    http = Httpx(routes={"/v2/account": {"id": fixture.subject.account_id,
                                        "account_number": "PAPER-NUMBER"}})
    broker = adapter(fixture, http=http)
    identity = asyncio.run(broker.identify_account())
    assert (identity.broker, identity.account_id) == ("alpaca-live", fixture.subject.account_id)
    retained = OriginalAlpaca._account_identity({"id": fixture.subject.account_id,
                                                "account_number": "PAPER-NUMBER"})
    assert (retained.broker, retained.account_id) == ("alpaca", "PAPER-NUMBER")


@pytest.mark.parametrize("account", ["", "account-number", "00000000-0000-0000-0000-000000000000"])
def test_live_identity_cannot_fall_back_to_display_account_number(account):
    with pytest.raises(MalformedBrokerPayload):
        OriginalAlpaca._account_identity({"id": account, "account_number": "PAPER-NUMBER"},
                                         broker="alpaca-live")


def assert_revoked_read_refused(broker, http):
    with pytest.raises(BrokerAuthorityRefused):
        asyncio.run(broker.identify_account())
    assert http.calls == []


def test_revocation_after_construction_prevents_a_read_request():
    fixture = live_fixture()
    http = Httpx(routes={"/v2/account": {"id": fixture.subject.account_id}})
    broker = adapter(fixture, http=http)
    fixture.roots[fixture.key_id] = replace(fixture.roots[fixture.key_id], status="REVOKED")
    assert_revoked_read_refused(broker, http)


def test_revocation_is_rechecked_after_async_client_entry_before_http():
    fixture = live_fixture()
    http = Httpx(routes={"/v2/account": {"id": fixture.subject.account_id}})
    original_client = http.AsyncClient

    class RevokeAtEntry(original_client):
        async def __aenter__(self):
            fixture.roots[fixture.key_id] = replace(fixture.roots[fixture.key_id], status="REVOKED")
            return await super().__aenter__()

    http.AsyncClient = RevokeAtEntry
    broker = adapter(fixture, http=http)
    assert_revoked_read_refused(broker, http)


@pytest.mark.parametrize("adapter_type", [OriginalAlpaca, HardenedAlpacaExecutionBroker,
                                          FinancialGradeAlpacaExecutionBroker,
                                          AssetIdAlpacaExecutionBroker])
@pytest.mark.parametrize("operation", ["SUBMIT", "CANCEL"])
def test_live_certificate_alone_cannot_send_a_mutation(adapter_type, operation):
    fixture = live_fixture()
    http = Httpx(post=Response({}, 201))
    broker = adapter(fixture, adapter_type=adapter_type, http=http)
    with pytest.raises(BrokerAuthorityRefused):
        if operation == "SUBMIT":
            asyncio.run(broker.submit(client_key="key-1", instrument=INSTRUMENT,
                                      side=Side.BUY, quantity=Decimal(2)))
        else:
            asyncio.run(broker.cancel("exact-order-1"))
    assert http.calls == []


def test_admission_cannot_be_a_caller_supplied_approved_boolean():
    with pytest.raises(BrokerAuthorityRefused):
        AssetIdAlpacaExecutionBroker(api_key="test", secret_key="test", base_url=LIVE,
                                     live_admission={"approved": True})


def test_live_admission_cannot_be_replayed_at_paper_origin():
    fixture = live_fixture()
    with pytest.raises(BrokerAuthorityRefused):
        AssetIdAlpacaExecutionBroker(api_key="test", secret_key="test", base_url=PAPER,
                                     live_admission=fixture.admission)


def test_certification_rechecks_revocation_and_origin_after_issuance():
    fixture = live_fixture()
    broker = adapter(fixture)
    certify_adapter(broker, name="alpaca-live", mode="ALPACA_LIVE",
                    live_admission=fixture.admission)
    fixture.roots[fixture.key_id] = replace(fixture.roots[fixture.key_id], status="REVOKED")
    with pytest.raises(AdapterNotCertified, match="fresh LIVE"):
        require_certified_adapter(broker)


def test_changed_live_origin_refuses_before_a_read_or_certification():
    fixture = live_fixture()
    http = Httpx(routes={"/v2/account": {"id": fixture.subject.account_id}})
    broker = adapter(fixture, http=http)
    certify_adapter(broker, name="alpaca-live", mode="ALPACA_LIVE",
                    live_admission=fixture.admission)
    broker.base_url = PAPER
    with pytest.raises(BrokerAuthorityRefused, match="origin changed"):
        asyncio.run(broker.identify_account())
    with pytest.raises(AdapterNotCertified, match="origin or admission changed"):
        require_certified_adapter(broker)
    assert http.calls == []


def test_revoked_read_falsifier_detects_removal_of_request_guard(monkeypatch):
    fixture = live_fixture()
    http = Httpx(routes={"/v2/account": {"id": fixture.subject.account_id}})
    broker = adapter(fixture, http=http)
    fixture.roots[fixture.key_id] = replace(fixture.roots[fixture.key_id], status="REVOKED")
    monkeypatch.setattr(broker, "_require_transport_authority", lambda **_kwargs: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        assert_revoked_read_refused(broker, http)


@pytest.mark.parametrize('operation', ['SUBMIT', 'CANCEL'])
@pytest.mark.parametrize('withdrawal', ['expiry', 'kill'])
def test_actual_adapter_propagates_late_permit_refusal_without_http(monkeypatch, operation, withdrawal):
    from datetime import timedelta
    from sentinel.authority import AuthorityRefused, live
    from sentinel.execution import live_transport
    from sentinel.execution.states import CommandState
    from tests.sentinel.live_order_fixtures import (
        DAY, NOW, REFERENCE_SESSION, funding, order_fixture,
    )
    fixture = order_fixture()
    clock = [NOW]
    withdrawn = [False]
    # The unit scenario explicitly owns its historical aware clock; production
    # uses the validator's real clock and has no such override.
    original = live.require_live_adapter_admission
    monkeypatch.setattr(live, 'require_live_adapter_admission', lambda admission, **kwargs:
        original(admission, **{**kwargs, 'now': clock[0]}))
    http = Httpx()
    original_client = http.AsyncClient
    class WithdrawAtEntry(original_client):
        async def __aenter__(self):
            if withdrawal == 'expiry':
                clock[0] += timedelta(seconds=31)
            else:
                withdrawn[0] = True
            return await super().__aenter__()
    http.AsyncClient = WithdrawAtEntry
    broker = adapter(fixture, http=http)
    broker._clock_provider = lambda: clock[0]
    context = live_transport.LiveOrderContext(DAY, fixture.request, fixture.account, NOW,
        fixture.positions, fixture.commitments, Decimal(10), REFERENCE_SESSION,
        funding=funding(fixture).admission)
    owned = replace(fixture.request, state=CommandState.ACKNOWLEDGED, broker_order_id='owned-order')
    def final_check(_operation):
        if withdrawn[0]:
            raise AuthorityRefused('fresh kill engaged at actual client entry')
    policy = live_transport.LiveExecutionPolicy(admission=fixture.admission,
        load_submit=lambda _key: context, load_cancel=lambda _id: owned,
        final_check=final_check, now=lambda: clock[0])
    command = fixture.request
    kwargs = dict(client_key=command.client_key, instrument=command.instrument,
        side=command.side, quantity=command.quantity, order_terms=command.order_terms)
    if operation == 'SUBMIT':
        from types import SimpleNamespace
        from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker, LiveExecutionGrant
        async def clock_read():
            return SimpleNamespace(timestamp=clock[0], is_open=True)
        async def instrument_read(**_kwargs):
            return command.instrument
        async def check(*_args):
            return None
        broker.market_clock = clock_read
        broker.resolve_instrument = instrument_read
        wrapped = GuardedExecutionBroker(inner=broker,
            grant=LiveExecutionGrant(fixture.subject, 'EXECUTE', 'plan', DAY, True),
            guard=ExecutionBrokerGuard(check, check, check), live_policy=policy,
            issuer_admission_check=lambda **_kwargs: SimpleNamespace(allowed=True))
    async def scenario():
        if operation == 'SUBMIT':
            with pytest.raises(live_transport.LiveTransportRefused) as refused:
                await wrapped.submit(**kwargs)
            wrapped.consume_not_transported(refused.value, command)
            with pytest.raises(ValueError, match='no matching unused'):
                wrapped.consume_not_transported(refused.value, command)
        else:
            permit = await policy.authorize_cancel(broker, 'owned-order')
            with live_transport._mutation_scope(permit):
                with pytest.raises(live_transport.LiveTransportRefused):
                    await broker.cancel('owned-order')
    asyncio.run(scenario())
    assert http.calls == []
