from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest
from pydantic import ValidationError

from sentinel.execution import live_funding as funding
from sentinel.execution.native_readonly import ExecutionSubject


NOW = datetime(2026, 10, 16, 14, 30, tzinfo=timezone.utc)


def subject(**changes):
    return ExecutionSubject(**{
        'deployment_id': 'qualification', 'account_id': '00000000-0000-0000-0000-000000000001',
        'takeover_epoch': 1, 'environment': 'ALPACA_LIVE',
        'base_url': 'https://api.alpaca.markets', **changes})


def evidence(**changes):
    return funding.FundingEvidence(**{
        'subject': subject(), 'observed_at': NOW, 'cash': '100',
        'buying_power': '100', 'multiplier': '1', 'status': 'ACTIVE',
        'trading_blocked': False, 'account_blocked': False,
        'trade_suspended_by_user': False, 'settled_cash': '80',
        'reserved_cash': '20', 'settlement_source': 'simulation/settled-v1',
        'reservations_source': 'simulation/reservations-v1',
        'provenance': 'SIMULATION_ONLY', **changes})


def assess(**changes):
    return funding.assess_live_funding(evidence(**changes), expected_subject=subject(), now=NOW)


@pytest.mark.parametrize('cash,buying_power,settled,reserved,expected', [
    ('100', '100', '80', '20', '60'),
    ('35', '100', '80', '20', '35'),
    ('100', '25', '80', '20', '25'),
    ('100', '100', '10', '20', '0'),
    ('0', '0', '0', '0', '0'),
    ('1.000000009', '2', '1.000000009', '0.000000001', '1.000000008'),
])
def test_settled_budget_is_decimal_and_subtracts_reservations(cash, buying_power, settled, reserved, expected):
    decision = assess(cash=cash, buying_power=buying_power, settled_cash=settled, reserved_cash=reserved)
    assert decision.candidate_budget == Decimal(expected)
    assert decision.spendable_budget == 0 and decision.order_authority == 'NONE'
    assert decision.native_settlement == 'NOT_PROVEN'


@pytest.mark.parametrize('changes', [
    {'subject': subject(account_id='00000000-0000-0000-0000-000000000002')},
    {'subject': subject(takeover_epoch=2)},
    {'subject': subject(deployment_id='other')},
    {'subject': subject(environment='ALPACA_PAPER', base_url='https://paper-api.alpaca.markets')},
    {'observed_at': NOW - timedelta(seconds=31)},
    {'observed_at': NOW + timedelta(microseconds=1)},
    {'multiplier': '2'}, {'status': 'ACCOUNT_CLOSED'},
    {'trading_blocked': True}, {'account_blocked': True}, {'trade_suspended_by_user': True},
    {'cash': '-1'}, {'buying_power': '-1'}, {'settled_cash': '-1'}, {'reserved_cash': '-1'},
    {'settled_cash': None}, {'reserved_cash': None},
    {'settlement_source': None}, {'reservations_source': None},
])
def test_unproven_or_unavailable_funding_defers(changes):
    decision = assess(**changes)
    assert decision.status == 'DEFERRED' and decision.candidate_budget == 0
    assert decision.spendable_budget == 0


@pytest.mark.parametrize('source', [None, 'cash', 'buying_power', 'native/settled-v1', 'simulation/settled-v1'])
def test_native_fields_cannot_self_qualify_settlement(source):
    decision = assess(provenance='NATIVE', settlement_source=source)
    assert decision.status == 'DEFERRED' and decision.candidate_budget == 0
    assert 'NATIVE_SETTLEMENT_AND_RESERVATIONS_NOT_QUALIFIED' in decision.reasons


@pytest.mark.parametrize('changes', [
    {'cash': 1.1}, {'cash': True}, {'cash': 'NaN'}, {'cash': 'Infinity'}, {'cash': 'bad'},
    {'reserved_cash': float('nan')}, {'trading_blocked': 'false'},
    {'observed_at': NOW.replace(tzinfo=None)}, {'extra_authority': True},
    {'settled_cash': '1E+1000000000'}, {'reserved_cash': '1E-1000000000'},
    {'cash': '1' * 257},
])
def test_lossy_or_malformed_evidence_refuses(changes):
    with pytest.raises((ValidationError, ValueError)):
        evidence(**changes)


def test_funding_proof_guard_has_a_falsifier(monkeypatch):
    source = inspect.getsource(funding.assess_live_funding)
    needle = "if evidence.provenance != 'SIMULATION_ONLY':"
    assert source.count(needle) == 1
    changed = source.replace(needle, 'if False:')
    namespace = {}
    exec(compile(changed, 'settlement-falsifier', 'exec'), funding.__dict__, namespace)
    monkeypatch.setattr(funding, 'assess_live_funding', namespace['assess_live_funding'])
    with pytest.raises(AssertionError):
        test_native_fields_cannot_self_qualify_settlement('simulation/settled-v1')


def test_budget_does_not_depend_on_decimal_context():
    from decimal import localcontext
    with localcontext() as context:
        context.prec = 3
        decision = assess(cash='100', buying_power='100', settled_cash='80.000000009', reserved_cash='20.000000001')
    assert decision.candidate_budget == Decimal('60.000000008')
