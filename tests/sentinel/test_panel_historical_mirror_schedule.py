"""Current future scheduling never erases an authenticated historical warning."""
from dataclasses import replace
import inspect

import pytest

from sentinel.panel import model, observer_codec, presentation, sources
from tests.sentinel.test_local_paper_panel_schedule import (
    NOW, OPEN, panel,
    test_future_unstamped_plan_requires_bound_local_scheduled_proof as scheduled_source_case,
)


def history_row():
    return model.paper_reconciliation_row(state='SCHEDULED_WITH_HISTORY',
        cycle_state='WAITING_OPEN', scheduled_until=OPEN,
        detail='Current future plan is scheduled; one earlier-plan mismatch remains historical.')


def test_historical_warning_remains_amber_and_cannot_be_the_normal_green_schedule_exception():
    row = history_row()
    assert row.status == row.effective_status(NOW) == model.WARN
    assert row.paper_alignment == 'SCHEDULED_WITH_HISTORY'
    assert row.effective_status(OPEN) == model.FAIL
    page = panel(scheduled=False)
    page.rows.append(row)
    assert page.operational == model.WARN
    assert presentation.dashboard_health(page)['color'] != 'green'
    assert 'NOT VERIFIED' in row.value and 'HISTORICAL' in row.value


def test_history_alignment_roundtrips_the_existing_observer_codec_without_claiming_success():
    row = history_row()
    encoded = observer_codec.pack([row], [], observed_at=NOW)['rows'][0]
    decoded = observer_codec.row_from_observation(encoded)
    assert decoded == row
    assert decoded.effective_status(NOW) == model.WARN
    assert decoded.recovery is None and decoded.required_current


def test_json_preserves_the_typed_historical_warning_and_native_expiry(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app
    page = panel(scheduled=False)
    page.rows.append(history_row())
    monkeypatch.setattr(app, '_read_panel', lambda: page)
    with TestClient(app.app) as client:
        body = client.get('/panel.json').json()
    row = next(item for item in body['rows'] if item['key'] == 'paper_reconciliation')
    assert row['paper_alignment'] == 'SCHEDULED_WITH_HISTORY'
    assert row['status'] == 'warn' and row['color'] == 'amber'
    assert row['valid_until'] == history_row().valid_until.isoformat()
    assert body['dashboard_health']['color'] != 'green'


@pytest.mark.parametrize('changes', [
    {'paper_alignment':'UNRECOGNIZED_HISTORY'}, {'valid_until':None},
    {'valid_until':OPEN.replace(tzinfo=None)}, {'required_current':False},
    {'status':model.OK}, {'key':'other'},
    {'recovery':{'phase':'AUTOMATION_OPEN','automatic':True,'deadline':OPEN}},
])
def test_malformed_history_flag_or_missing_native_bound_is_refused(changes):
    encoded = observer_codec.pack([history_row()], [], observed_at=NOW)['rows'][0]
    encoded.update(changes)
    with pytest.raises(ValueError):
        observer_codec.row_from_observation(encoded)


@pytest.mark.parametrize('changes', [
    {'required_current':False}, {'status':model.OK}, {'valid_until':None},
    {'recovery':model.RecoveryEvidence(phase='AUTOMATION_OPEN',automatic=True,deadline=OPEN)},
])
def test_internal_malformed_history_warning_cannot_hide_current_failure(changes):
    assert replace(history_row(), **changes).effective_status(NOW) == model.FAIL


@pytest.mark.parametrize('case', ['global_history', 'stamped_history'])
def test_historical_warning_has_an_executed_false_green_falsifier(monkeypatch, case):
    source = inspect.getsource(sources._scheduled_paper_mirror)
    guard = "state='SCHEDULED_WITH_HISTORY'"
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, "state='SCHEDULED'"),
        '<historical-warning-erased>', 'exec'), namespace)
    monkeypatch.setattr(sources, '_scheduled_paper_mirror', namespace['_scheduled_paper_mirror'])
    with pytest.raises(AssertionError):
        scheduled_source_case(
            monkeypatch, True, True, case, model.WARN)
