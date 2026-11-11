"""The hot dated-run read returns closed proof metadata, never a diagnostic dump."""
import inspect
import json

import pytest
from psycopg.types.json import Jsonb

from sentinel.panel import sources
from tests.sentinel.test_panel_trading_run import historical_run_db, historical_run_dsn  # noqa: F401


def _diagnostic():
    return {'clean': True, 'runtime_state': 'RUNNING', 'cash_plan_superseded': True,
            'observation_id': 396, 'unresolved': [], 'foreign_orders': [],
            'foreign_positions': [], 'restricted_securities': {}, 'terminal_reason': None}


def _selected(fixture, diagnostic, *, reader=None):
    conn, calls = fixture
    conn.execute("""UPDATE sentinel_automation_cycles SET control_generation=86,
        certificate_sha256='new-cert',config_sha256='new-config',state='SUPERSEDED',
        failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED',diagnostic=%s""", (Jsonb(diagnostic),))
    conn.execute('UPDATE sentinel_execution_plans SET superseded_by=NULL')
    (reader or sources._current_trading_run)(conn)
    return calls[-1][0][-1]


def _assert_bounded(value):
    assert set(value) == set(_diagnostic())
    assert len(json.dumps(value)) < 1000


def test_current_run_query_projects_closed_metadata_from_large_diagnostic(historical_run_db):
    diagnostic = dict(_diagnostic(), unrelated_execution_trace='x' * 70000)
    selected = _selected(historical_run_db, diagnostic)
    _assert_bounded(selected)
    assert selected == _diagnostic()


@pytest.mark.parametrize('field,wrong,expected', [
    ('clean', 'true', False), ('clean', 1, False),
    ('cash_plan_superseded', 'true', False),
    ('runtime_state', 'UNKNOWN' * 20000, None),
    ('observation_id', '396', None), ('observation_id', -1, None),
    ('observation_id', 10 ** 30, None), ('observation_id', 396.5, None),
    ('unresolved', {}, None), ('unresolved', [None], None),
    ('foreign_orders', '[]', None), ('foreign_positions', [1], None),
    ('restricted_securities', {'unknown': True}, None),
    ('terminal_reason', 'unknown' * 20000, 'PRESENT'),
])
def test_current_run_query_cannot_normalize_malformed_history_to_positive(historical_run_db, field, wrong, expected):
    diagnostic = _diagnostic()
    diagnostic[field] = wrong
    selected = _selected(historical_run_db, diagnostic)
    _assert_bounded(selected)
    assert selected[field] == expected
    assert selected != _diagnostic()


@pytest.mark.parametrize('field', list(_diagnostic()))
def test_current_run_query_retains_missing_field_refusal(historical_run_db, field):
    diagnostic = _diagnostic()
    diagnostic.pop(field)
    selected = _selected(historical_run_db, diagnostic)
    _assert_bounded(selected)
    if field != 'terminal_reason':
        assert selected[field] is None


def test_whole_diagnostic_query_omission_is_detected_with_real_sql(historical_run_db):
    text = inspect.getsource(sources._current_trading_run)
    begin = text.index('jsonb_build_object(')
    end = text.index('\n            FROM', begin)
    namespace = dict(sources.__dict__)
    exec(text[:begin] + 'c.diagnostic' + text[end:], namespace)
    diagnostic = dict(_diagnostic(), unrelated_execution_trace='x' * 70000)
    _assert_bounded(_selected(historical_run_db, diagnostic))
    with pytest.raises(AssertionError):
        _assert_bounded(_selected(historical_run_db, diagnostic, reader=namespace['_current_trading_run']))
