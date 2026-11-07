"""Trading API envelope acceptance remains account-bound and quarantined."""
import ast
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel.execution import alpaca
from tests.sentinel.test_alpaca_boundary_overlay import (
    ACCOUNT_UUID, Response, account_payload, activity_event, adapter, sse)

AFTER = datetime(2026, 8, 19, tzinfo=timezone.utc)
THROUGH = datetime(2026, 8, 20, tzinfo=timezone.utc)
PATH = '/v2beta1/events/activities'


def native_shaped_event():
    value = activity_event(activity_type='DIV', activity_subtype='CDIV',
        net_amount='75.89', qty='0', details={'symbol': 'BIL', 'rate': '0.308493', 'entitled_qty': '246'})
    value.pop('account_id')
    return value


def test_owned_stream_without_partner_account_field_is_bracketed():
    broker, http = adapter(routes={PATH: Response(text=sse(native_shaped_event()))})
    result = asyncio.run(broker.account_cash_activities(after=AFTER, through=THROUGH))
    assert len(result.activities) == 1 and result.activities[0].net_amount == Decimal('75.89')
    assert [path for _, path, _ in http.calls] == ['/v2/account', PATH, '/v2/account']
    assert not broker.financial_activity_sse
    assert not broker.capabilities.account_cash_activity_evidence
    assert not broker.capabilities.account_fill_interval_evidence


@pytest.mark.parametrize('value', ['', None, 'another-account'])
def test_present_event_account_field_must_match(value):
    event = dict(native_shaped_event(), account_id=value)
    broker, _ = adapter(routes={PATH: Response(text=sse(event))})
    with pytest.raises(alpaca.MalformedBrokerPayload, match='another account'):
        asyncio.run(broker.account_cash_activities(after=AFTER, through=THROUGH))


@pytest.mark.parametrize('field,value', [('id', 'another-native-uuid'), ('id', ''),
    ('account_number', 'PA-OTHER')])
@pytest.mark.parametrize('empty', [False, True])
def test_completed_stream_refuses_changed_account(field, value, empty):
    count = 0
    def accounts(_):
        nonlocal count
        count += 1
        return account_payload() if count == 1 else dict(account_payload(), **{field: value})
    broker, _ = adapter(routes={'/v2/account': accounts,
        PATH: Response(text='' if empty else sse(native_shaped_event()))})
    with pytest.raises(alpaca.MalformedBrokerPayload, match='identity changed'):
        asyncio.run(broker.account_cash_activities(after=AFTER, through=THROUGH))


def test_closing_account_unavailability_yields_no_batch():
    count = 0
    def accounts(_):
        nonlocal count
        count += 1
        if count > 1: raise RuntimeError('account read unavailable')
        return account_payload()
    broker, _ = adapter(routes={'/v2/account': accounts, PATH: Response(text=sse(native_shaped_event()))})
    with pytest.raises(RuntimeError, match='unavailable'):
        asyncio.run(broker.account_cash_activities(after=AFTER, through=THROUGH))


def test_optional_matching_account_and_repeated_snapshot_keep_original_cursor():
    event = dict(native_shaped_event(), account_id=ACCOUNT_UUID)
    broker, http = adapter(routes={PATH: Response(text=sse(event))})
    result = asyncio.run(broker._bounded_activity_events(after=AFTER, through=THROUGH, verify_snapshot_replay=True))
    assert result == (event,)
    assert [path for _, path, _ in http.calls] == ['/v2/account', PATH, '/v2/account', PATH, '/v2/account']


@pytest.mark.parametrize('guard', ['closing_account', 'explicit_event_account'])
def test_removed_account_scope_guard_is_detected(monkeypatch, guard):
    tree = ast.parse(textwrap.dedent(inspect.getsource(alpaca.AlpacaExecutionBroker._bounded_activity_events)))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.If) and (
        any(isinstance(item, ast.Name) and item.id == 'account_after' for item in ast.walk(node.test))
        if guard == 'closing_account' else 'event_account != account_uuid' in ast.unparse(node.test))]
    assert len(matches) == 1
    matches[0].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-trading-activity-account-guard>', 'exec'), vars(alpaca), namespace)
    monkeypatch.setattr(alpaca.AlpacaExecutionBroker, '_bounded_activity_events', namespace['_bounded_activity_events'])
    with pytest.raises(pytest.fail.Exception):
        if guard == 'closing_account': test_completed_stream_refuses_changed_account('id', 'foreign', False)
        else: test_present_event_account_field_must_match('foreign')
