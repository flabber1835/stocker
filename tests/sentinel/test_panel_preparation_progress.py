"""Producer progress is current information, never financial readiness."""
import ast
from datetime import date, datetime, timedelta, timezone
import inspect
import textwrap

import pytest
from pydantic import ValidationError

from sentinel.panel.model import PreparationWork, Row, WARN, FAIL


NOW = datetime(2026, 10, 30, 20, 30, tzinfo=timezone.utc)


def work(**changes):
    values = dict(job_id='current-closing-data', decision_session=date(2026, 10, 30),
        effective_session=date(2026, 11, 2), state='ACQUIRING', rows_done=1720712,
        components_done=31, created_at=NOW-timedelta(minutes=20), updated_at=NOW,
        last_progress_at=NOW-timedelta(minutes=2), observed_at=NOW,
        deadline=NOW+timedelta(hours=1), lease_until=NOW+timedelta(seconds=35),
        owner_registered=True, fence=4, next_retry=None)
    values.update(changes)
    return PreparationWork(**values)


def test_live_progress_expires_at_the_original_lease_and_observation_bounds():
    value = work()
    assert value.active_at(NOW)
    assert value.active_until == NOW+timedelta(seconds=35)
    assert not value.active_at(value.active_until)
    assert not value.visible_at(NOW+timedelta(seconds=46))
    assert work(lease_until=NOW+timedelta(minutes=5)).active_until == NOW+timedelta(seconds=45)
    assert value.rows_done == 1720712 and value.last_progress_at == NOW-timedelta(minutes=2)


@pytest.mark.parametrize('changes', [
    {'owner_registered': False}, {'fence': 0}, {'lease_until': None},
    {'lease_until': NOW}, {'state': 'WAIT_SOURCE'}, {'state': 'RETRY_WAIT'},
    {'state': 'PUBLISHED'},
])
def test_unowned_expired_and_parked_work_is_not_called_active(changes):
    assert not work(**changes).active_at(NOW)


@pytest.mark.parametrize('changes', [
    {'rows_done': True}, {'rows_done': -1}, {'components_done': -1},
    {'fence': True}, {'owner_registered': 1}, {'state': 'UNKNOWN'},
    {'observed_at': NOW.replace(tzinfo=None)},
    {'last_progress_at': NOW+timedelta(seconds=1)},
    {'deadline': NOW-timedelta(minutes=21)},
    {'effective_session': date(2026, 10, 29)},
])
def test_malformed_progress_cannot_be_a_display_fact(changes):
    with pytest.raises(ValidationError):
        work(**changes)


def test_progress_does_not_overrule_its_row_or_become_another_rows_authority():
    row = Row('ingest', 'Acquisition', 'ACQUIRING', WARN,
        as_of=NOW, freshness=timedelta(minutes=1), preparation=work())
    assert row.can_show_preparation(NOW)
    assert not Row('other', 'Other', 'ACQUIRING', WARN,
        preparation=work()).can_show_preparation(NOW)
    assert not Row('ingest', 'Acquisition', 'FAILED', FAIL,
        preparation=work()).can_show_preparation(NOW)
    assert not row.can_show_preparation(NOW+timedelta(seconds=46))


def test_registered_owner_guard_has_an_executed_removal_falsifier(monkeypatch):
    original = PreparationWork.active_until.fget
    tree = ast.parse(textwrap.dedent(inspect.getsource(original)))
    removed = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            kept = []
            for value in node.values:
                if (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
                        and isinstance(value.operand, ast.Attribute)
                        and value.operand.attr == 'owner_registered'):
                    removed.append(value)
                else:
                    kept.append(value)
            node.values = kept
    assert len(removed) == 1
    namespace = dict(original.__globals__)
    exec(compile(ast.fix_missing_locations(tree), '<missing-producer-owner-guard>', 'exec'), namespace)
    monkeypatch.setattr(PreparationWork, 'active_until', namespace['active_until'])
    with pytest.raises(AssertionError):
        test_unowned_expired_and_parked_work_is_not_called_active({'owner_registered': False})


def test_json_preserves_strict_readiness_and_exports_the_separate_health(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app, model
    from sentinel.panel.presentation import dashboard_health

    panel = model.Panel(now=NOW, rows=[Row('ingest', 'Acquisition', 'ACQUIRING', WARN,
        as_of=NOW, freshness=timedelta(minutes=1), preparation=work())])
    monkeypatch.setattr(app, '_read_panel', lambda: panel)
    with TestClient(app.app) as client:
        body = client.get('/panel.json').json()
    assert (body['overall'], body['operational'], body['color']) == ('warn', 'warn', 'amber')
    assert body['dashboard_health'] == dashboard_health(panel)
    assert body['rows'][0]['preparation']['rows_done'] == 1720712
    assert body['rows'][0]['preparation']['last_progress_at'] == '2026-10-30T20:28:00Z'
