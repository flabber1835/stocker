"""Offline LIVE policy/transport composition, including task and term races."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.authority.live import require_live_adapter_admission
from sentinel.execution import live_transport
from sentinel.execution.contract import BrokerCapabilities, ExecutionBroker, Side
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, LiveExecutionGrant,
    ManualExecutionGrant, PreTransportAuthorityRefused,
)
from tests.sentinel.live_order_fixtures import DAY, NOW, REFERENCE_SESSION, funding, order_fixture
from tests.sentinel.live_authority_fixtures import signed_live


class OfflineNative(ExecutionBroker):
    base_url = "https://api.alpaca.markets"
    capabilities = BrokerCapabilities(protected_limit_day=True)

    def __init__(self, fixture, clock):
        self.live_admission = fixture.admission
        self._now = lambda: clock[0]
        self.calls = []

    async def identify_account(self):
        raise AssertionError("transport-only fixture must not read an account")

    async def observe(self):
        raise AssertionError("transport-only fixture must not collect observations")

    async def find_by_client_key(self, client_key):
        raise AssertionError("transport-only fixture must not recover orders")

    async def recent_fills(self, since):
        raise AssertionError("transport-only fixture must not collect fills")

    async def market_clock(self):
        return SimpleNamespace(timestamp=self._now(), is_open=True)

    async def submit(self, *, client_key, instrument, side, quantity, order_terms):
        verified = require_live_adapter_admission(self.live_admission, base_url=self.base_url,
            now=self._now(), required_operation="SUBMIT")
        live_transport.require_live_mutation_permit(self, operation="SUBMIT",
            command_key=client_key, instrument=instrument, side=side,
            quantity=quantity, terms=order_terms, certificate_sha256=verified.sha256)
        self.calls.append(("SUBMIT", client_key, quantity))
        return "transported"

    async def cancel(self, broker_order_id):
        verified = require_live_adapter_admission(self.live_admission, base_url=self.base_url,
            now=self._now(), required_operation="CANCEL")
        live_transport.require_live_mutation_permit(self, operation="CANCEL",
            broker_order_id=broker_order_id, certificate_sha256=verified.sha256)
        self.calls.append(("CANCEL", broker_order_id))
        return "cancelled"


def composition(*, funding_expiry=None, before_mutation=None):
    fixture = order_fixture()
    clock = [NOW]
    inner = OfflineNative(fixture, clock)
    receipt = funding(fixture, **({"expires_at": funding_expiry.isoformat()} if funding_expiry else {}))
    context = live_transport.LiveOrderContext(DAY, fixture.request, fixture.account, NOW,
        fixture.positions, fixture.commitments, Decimal(10), REFERENCE_SESSION,
        funding=receipt.admission)
    policy = live_transport.LiveExecutionPolicy(admission=fixture.admission,
        load_submit=lambda _key: context, load_cancel=lambda _id: fixture.request,
        final_check=lambda _operation: None,
        now=lambda: clock[0])

    async def before(_grant, _operation):
        return None

    async def after(_grant, _operation, _result):
        return None

    guard = ExecutionBrokerGuard(before, after, before_mutation or before)
    grant = LiveExecutionGrant(fixture.subject, "EXECUTE", "plan", DAY, True)
    wrapped = GuardedExecutionBroker(inner=inner, grant=grant, guard=guard, live_policy=policy,
        issuer_admission_check=lambda **_kwargs: SimpleNamespace(allowed=True))
    return SimpleNamespace(fixture=fixture, clock=clock, inner=inner, context=context,
        policy=policy, wrapped=wrapped, grant=grant, guard=guard)


def arguments(case):
    command = case.fixture.request
    return dict(client_key=command.client_key, instrument=command.instrument,
        side=command.side, quantity=command.quantity, order_terms=command.order_terms)


def test_signed_limits_and_funding_reach_only_the_existing_guarded_membrane():
    case = composition()
    assert asyncio.run(case.wrapped.submit(**arguments(case))) == "transported"
    assert case.inner.calls == [("SUBMIT", case.fixture.request.client_key, Decimal(10))]


def test_signed_authority_alone_does_not_allow_naked_transport():
    case = composition()
    with pytest.raises(live_transport.LiveTransportRefused, match="exact guarded"):
        asyncio.run(case.inner.submit(**arguments(case)))
    assert case.inner.calls == []


def test_paper_confirmation_cannot_be_reused_for_live():
    case = composition()
    with pytest.raises(TypeError, match="PAPER grants"):
        GuardedExecutionBroker(inner=case.inner,
            grant=ManualExecutionGrant(case.fixture.subject.account_id, "plan", DAY, True),
            guard=case.guard, live_policy=case.policy)


@pytest.mark.parametrize("field", ["client_key", "instrument", "side", "quantity", "order_terms"])
def test_permit_binds_every_original_order_field(field):
    case = composition()

    async def scenario():
        kwargs = arguments(case)
        permit = await case.policy.authorize_submit(case.inner, **kwargs)
        changed = dict(kwargs)
        changed[field] = {
            "client_key": "another-key",
            "instrument": replace(kwargs["instrument"], broker_id="another-asset"),
            "side": Side.SELL,
            "quantity": Decimal(11),
            "order_terms": replace(kwargs["order_terms"], limit_price=Decimal("10.09")),
        }[field]
        with live_transport._mutation_scope(permit):
            with pytest.raises(live_transport.LiveTransportRefused):
                await case.inner.submit(**changed)

    asyncio.run(scenario())
    assert case.inner.calls == []


def test_permit_cannot_be_replayed_or_inherited_by_another_async_task():
    case = composition()

    async def scenario():
        kwargs = arguments(case)
        permit = await case.policy.authorize_submit(case.inner, **kwargs)
        with live_transport._mutation_scope(permit):
            with pytest.raises(live_transport.LiveTransportRefused):
                await asyncio.create_task(case.inner.submit(**kwargs))
            assert await case.inner.submit(**kwargs) == "transported"
            with pytest.raises(live_transport.LiveTransportRefused):
                await case.inner.submit(**kwargs)
        with pytest.raises(live_transport.LiveTransportRefused):
            await case.inner.submit(**kwargs)

    asyncio.run(scenario())
    assert len(case.inner.calls) == 1


def test_evidence_expiry_during_final_authority_io_prevents_transport():
    case = composition(funding_expiry=NOW + timedelta(seconds=1))

    async def delayed(_grant, _operation):
        case.clock[0] = NOW + timedelta(seconds=2)

    case.wrapped._guard = replace(case.guard, before_mutation=delayed)
    with pytest.raises(live_transport.LiveTransportRefused, match="expired|current"):
        asyncio.run(case.wrapped.submit(**arguments(case)))
    assert case.inner.calls == []


def test_pre_transport_policy_refusal_retains_single_use_unsent_proof():
    case = composition()
    case.policy._load_submit = lambda _key: replace(case.context, funding=None)
    with pytest.raises(PreTransportAuthorityRefused) as refused:
        asyncio.run(case.wrapped.submit(**arguments(case)))
    case.wrapped.consume_not_transported(refused.value, case.fixture.request)
    with pytest.raises(ValueError, match="unused"):
        case.wrapped.consume_not_transported(refused.value, case.fixture.request)
    assert case.inner.calls == []


def test_authority_rotation_after_policy_cannot_borrow_the_old_limits():
    case = composition()
    fixture = case.fixture
    current = [fixture.admission.certificate]
    admission = replace(fixture.admission, certificate_provider=lambda: current[0])
    case.inner.live_admission = admission
    case.policy._admission = admission

    async def rotate(_grant, _operation):
        claims = {**fixture.claims,
                  "limits": {**fixture.claims["limits"], "max_order_principal": "100"}}
        current[0] = signed_live(claims, fixture.private_key, fixture.key_id)

    case.wrapped._guard = replace(case.guard, before_mutation=rotate)
    with pytest.raises(live_transport.LiveTransportRefused):
        asyncio.run(case.wrapped.submit(**arguments(case)))
    assert case.inner.calls == []


def test_transport_guard_has_a_behavioral_falsifier(monkeypatch):
    def assert_refusal():
        case = composition()
        with pytest.raises(live_transport.LiveTransportRefused):
            asyncio.run(case.inner.submit(**arguments(case)))
        assert case.inner.calls == []

    assert_refusal()
    monkeypatch.setattr(live_transport, "require_live_mutation_permit", lambda *_args, **_kwargs: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        assert_refusal()


def test_control_withdrawal_at_actual_transport_prevents_submission():
    case = composition()
    def withdrawn(operation):
        assert operation == 'SUBMIT'
        raise RuntimeError('fresh kill switch is engaged')
    case.policy._final_check = withdrawn
    with pytest.raises(live_transport.LiveTransportRefused, match='final authority') as refused:
        asyncio.run(case.wrapped.submit(**arguments(case)))
    case.wrapped.consume_not_transported(refused.value, case.fixture.request)
    with pytest.raises(ValueError, match='unused'):
        case.wrapped.consume_not_transported(refused.value, case.fixture.request)
    assert case.inner.calls == []


def test_final_check_must_complete_without_yielding():
    case = composition()
    async def asynchronous(_operation):
        return None
    with pytest.raises(TypeError, match='synchronous'):
        live_transport.LiveExecutionPolicy(admission=case.fixture.admission,
            load_submit=lambda _key: case.context, load_cancel=lambda _id: case.fixture.request,
            final_check=asynchronous)
    case.policy._final_check = lambda operation: asynchronous(operation)
    with pytest.raises(live_transport.LiveTransportRefused, match='must not yield'):
        asyncio.run(case.wrapped.submit(**arguments(case)))
    assert case.inner.calls == []


def test_cancel_permit_is_exact_and_requires_original_owned_inflight_command():
    from sentinel.execution.states import CommandState
    case = composition()
    original = replace(case.fixture.request, state=CommandState.ACKNOWLEDGED,
                       broker_order_id='owned-order')
    case.policy._load_cancel = lambda _id: original
    assert asyncio.run(case.wrapped.cancel('owned-order')) == 'cancelled'
    with pytest.raises(live_transport.LiveTransportRefused, match='exact owned'):
        asyncio.run(case.wrapped.cancel('another-order'))
    assert case.inner.calls == [('CANCEL', 'owned-order')]


def test_inner_transport_lookalike_cannot_issue_unsent_proof():
    case = composition()
    async def lookalike(**_kwargs):
        raise live_transport.LiveTransportRefused('untrusted inner exception')
    case.inner.submit = lookalike
    with pytest.raises(live_transport.LiveTransportRefused) as refused:
        asyncio.run(case.wrapped.submit(**arguments(case)))
    with pytest.raises(ValueError, match='unused'):
        case.wrapped.consume_not_transported(refused.value, case.fixture.request)


def test_issuer_admission_is_checked_again_at_actual_transport():
    case = composition()
    allowed = [True]
    case.wrapped._issuer_admission_check = lambda **_kwargs: SimpleNamespace(allowed=allowed[0])
    async def withdraw(_grant, _operation):
        allowed[0] = False
    case.wrapped._guard = replace(case.guard, before_mutation=withdraw)
    with pytest.raises(live_transport.LiveTransportRefused, match='final authority') as refused:
        asyncio.run(case.wrapped.submit(**arguments(case)))
    case.wrapped.consume_not_transported(refused.value, case.fixture.request)
    assert case.inner.calls == []
