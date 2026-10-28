"""Issuer admission defers BUYs before settlement and command construction."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from sentinel.execution import executor as execution
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerCapabilities, BrokerInstrument,
    BrokerObservation, BrokerPosition, Side,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan, OpeningIntent
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.execution.target_reprojection import TargetProjection

TODAY = date(2026, 10, 27)
DEPLOYMENT = DeploymentIdentity('issuer-test', 'sim', 'SIM-ACCOUNT', 1)


@pytest.fixture
def harness(monkeypatch):
    for name in ('SENTINEL_LOCAL_PAPER_MODE', 'SENTINEL_LOCAL_PAPER_BACKUP_POLICY',
                 'SENTINEL_PAPER_BUY_POLICY', 'SENTINEL_PAPER_BUY_CAP_BPS'):
        monkeypatch.delenv(name, raising=False)
    h = SimpleNamespace(locked=False, events=[], commands=[], positions=(), reconciliations=0)

    @contextmanager
    def writer(_conn):
        assert not h.locked
        h.locked = True
        try:
            yield
        finally:
            h.locked = False

    async def reconcile(**_kwargs):
        assert h.locked
        h.reconciliations += 1
        observation = BrokerObservation(datetime(2026, 10, 27, tzinfo=timezone.utc),
            positions=h.positions)
        h.rec = SimpleNamespace(runtime_state=RuntimeState.RUNNING, observation=observation,
            restricted_securities={}, transport_ready=True)
        return h.rec

    async def identify():
        return BrokerAccountIdentity('sim', 'SIM-ACCOUNT')

    def build(**kwargs):
        assert h.locked
        h.events.append(('command', kwargs['delta'].security_id))
        return original_build(**kwargs)

    async def persist(_conn, _broker, command, **_kwargs):
        assert h.locked
        h.commands.append(command)
        return replace(command, state=CommandState.ACKNOWLEDGED)

    monkeypatch.setattr(execution.journal, 'writer_lock', writer)
    monkeypatch.setattr(execution, '_assert_current_plan', lambda *_args: None)
    monkeypatch.setattr(execution, 'assert_projection', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(execution.journal, 'in_flight_commands', lambda *_args: ())
    monkeypatch.setattr(execution.journal, 'load_commands', lambda *_args, **_kwargs: ())
    monkeypatch.setattr(execution.R, 'reconcile', reconcile)
    monkeypatch.setattr(execution, '_binding', lambda _conn: object())
    monkeypatch.setattr(execution.C, 'authorize', lambda **_kwargs: None)
    original_build = execution.C.build
    monkeypatch.setattr(execution.C, 'build', build)
    monkeypatch.setattr(execution, '_persist_and_send', persist)
    h.broker = SimpleNamespace(capabilities=BrokerCapabilities(), identify_account=identify)

    def run(basket, *, admission=None, opening_intents=(), projection=None, instruments=None):
        plan = ExecutionPlan('issuer-plan', TODAY, TODAY, Decimal(1),
            target_basket={sid: Decimal(qty) for sid, qty in basket.items()},
            opening_intents=opening_intents)
        h.plan = plan
        selected = instruments or {sid: BrokerInstrument(sid, sid, 'asset-'+sid) for sid in basket}
        return asyncio.run(execution.execute_session(broker=h.broker, conn=object(),
            deployment=DEPLOYMENT, plan=plan, instruments=selected, today=TODAY,
            buy_admission=admission, target_projection=projection))

    h.run = run
    return h


def test_denied_buy_preserves_positive_target_without_command_or_settlement(harness, monkeypatch):
    sell = BrokerInstrument('OLD', 'OLD', 'asset-old')
    harness.positions = (BrokerPosition(sell, Decimal(1)),)

    async def no_settlement(**_kwargs):
        pytest.fail('issuer-denied BUY spent a settlement read')

    monkeypatch.setattr(execution, '_settle_reductions', no_settlement)
    calls = []

    def admission(**kwargs):
        assert harness.locked and kwargs['reconciliation'] is harness.rec
        calls.append(kwargs)
        return SimpleNamespace(allowed=False, reason='ISSUER_UNRESOLVED')

    result = harness.run({'OLD': 0, 'NEW': 4}, admission=admission)
    assert [(command.security_id, command.side) for command in harness.commands] == [('OLD', Side.SELL)]
    assert [item['security_id'] for item in calls] == ['NEW']
    assert all(item['reserve'] is False for item in calls)
    assert result.deferred == ('NEW',)
    assert result.deferral_reasons == {'NEW': 'ISSUER_UNRESOLVED'}
    assert harness.plan.target_basket['NEW'] == Decimal(4)
    assert harness.reconciliations == 1 and not result.refused


def test_same_plan_reservations_are_serial_before_command_creation(harness):
    claimed = set()

    def admission(**kwargs):
        assert harness.locked and kwargs['reconciliation'] is harness.rec
        sid = kwargs['security_id']
        if not kwargs['reserve']:
            return SimpleNamespace(allowed=True, reason='')
        harness.events.append(('reserve', sid))
        if claimed:
            return SimpleNamespace(allowed=False, reason='ISSUER_ALREADY_RESERVED')
        claimed.add('shared-issuer')
        return SimpleNamespace(allowed=True, reason='')

    intents = (OpeningIntent('ZZZ', 1, Decimal(20)), OpeningIntent('AAA', 2, Decimal(20)))
    provisional = ExecutionPlan('issuer-plan', TODAY, TODAY, Decimal(1),
        target_basket={'AAA': Decimal(0), 'ZZZ': Decimal(0)}, opening_intents=intents)
    projection = TargetProjection(provisional.plan_id, provisional.fingerprint(), TODAY,
        {}, (), {}, {'AAA': Decimal(2), 'ZZZ': Decimal(2)})
    result = harness.run({'AAA': 0, 'ZZZ': 0}, admission=admission,
        opening_intents=intents, projection=projection)
    assert [command.security_id for command in harness.commands] == ['ZZZ']
    assert harness.events == [('reserve', 'ZZZ'), ('command', 'ZZZ'), ('reserve', 'AAA')]
    assert result.deferred == ('AAA',)
    assert result.deferral_reasons['AAA'] == 'ISSUER_ALREADY_RESERVED'
    assert projection.target_basket['AAA'] == Decimal(2)


def test_reservation_guard_has_a_falsifier(harness, monkeypatch):
    source = inspect.getsource(execution._execute_session_locked)
    needle = 'if not issuer_admitted(delta, reserve=True):'
    assert source.count(needle) == 1
    namespace = dict(vars(execution))
    exec(compile(source.replace(needle, 'if False:'), 'missing-issuer-reservation', 'exec'), namespace)
    monkeypatch.setattr(execution, '_execute_session_locked', namespace['_execute_session_locked'])
    with pytest.raises(AssertionError):
        test_same_plan_reservations_are_serial_before_command_creation(harness)


def test_pre_settlement_admission_has_a_falsifier(harness, monkeypatch):
    def preflight_proof():
        calls = []

        def admission(**kwargs):
            calls.append((kwargs['security_id'], kwargs['reserve']))
            return SimpleNamespace(allowed=False, reason='ISSUER_UNRESOLVED')

        harness.run({'NEW': 4}, admission=admission)
        assert calls == [('NEW', False)], 'read-only issuer admission must precede BUY reservation'
        assert not harness.commands

    preflight_proof()
    source = inspect.getsource(execution._execute_session_locked)
    needle = 'if not issuer_admitted(delta):'
    assert source.count(needle) == 1
    namespace = dict(vars(execution))
    exec(compile(source.replace(needle, 'if False:'), 'missing-issuer-preflight', 'exec'), namespace)
    monkeypatch.setattr(execution, '_execute_session_locked', namespace['_execute_session_locked'])
    with pytest.raises(AssertionError, match='read-only issuer admission must precede BUY reservation'):
        preflight_proof()


def test_sell_never_depends_on_issuer_evidence(harness):
    instrument = BrokerInstrument('SELL', 'SELL', 'asset-sell')
    harness.positions = (BrokerPosition(instrument, Decimal(3)),)

    def unavailable(**_kwargs):
        pytest.fail('SELL consulted issuer evidence')

    result = harness.run({'SELL': 1}, admission=unavailable)
    assert len(result.submitted) == 1 and result.submitted[0].side is Side.SELL
    assert not result.deferred


@pytest.mark.parametrize('sid,symbol,blocked', [
    ('EQUITY', 'BIL', True), ('SENTINEL:BIL', 'BIL', False)])
def test_owner_paper_requires_callback_except_exact_defensive_identity(harness, monkeypatch, sid, symbol, blocked):
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_MODE', 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1')
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', 'PAFIXTURE')
    result = harness.run({sid: 1}, instruments={sid: BrokerInstrument(sid, symbol, 'asset')})
    assert bool(result.deferred) is blocked
    assert bool(harness.commands) is not blocked
    if blocked:
        assert result.deferral_reasons[sid] == 'issuer admission authority is absent'


def test_generic_simulation_without_local_mode_keeps_ordinary_buy_path(harness):
    result = harness.run({'EQUITY': 2})
    assert len(result.submitted) == 1 and not result.deferred


def test_async_or_malformed_admission_cannot_authorize_buy(harness):
    async def invalid(**_kwargs):
        return SimpleNamespace(allowed=True, reason='')

    result = harness.run({'EQUITY': 2}, admission=invalid)
    assert not harness.commands and result.deferred == ('EQUITY',)
    assert 'synchronous' in result.deferral_reasons['EQUITY']
