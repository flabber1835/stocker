"""Reconstruct the November 27 bell crossing from its independent row and signed clocks."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import importlib
import json

import pytest

from sentinel.panel import model, operational_snapshot as snapshots, presentation, projection_service
from sentinel.panel import review, review_store, serialization
from sentinel.panel.sources import _shadow_worker_row, trading_environment_row
from tests.sentinel.test_operational_projection_service import conn, operational, pg, save_financial
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel
from tests.support.current_workflow_clock import BusinessClock
from tests.support.dashboard_review import reviewed_panel


BELL = datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc)
GENERATED = BELL - timedelta(seconds=5, microseconds=706531)
READ_AT = BELL + timedelta(microseconds=94377)
DUE = BELL + timedelta(minutes=1)


def waiting_page(state_dir, dsn):
    page = healthy_history_panel(now=GENERATED, execute_at=DUE)
    saved = page.row('paper_plan')
    plan = saved.paper_plan.model_copy(update={'decision_session': date(2026, 11, 25),
        'effective_session': BELL.date(), 'execution_open_at': None})
    rows = {
        'paper_plan': replace(saved, paper_plan=plan),
        'shadow_worker': _shadow_worker_row(state_dir, dsn),
        'paper_reconciliation': replace(model.paper_reconciliation_row(state='PENDING', cycle_state='WAITING_OPEN'),
            as_of=GENERATED-timedelta(seconds=43), freshness=timedelta(minutes=10)),
    }
    for key in ('feed', 'shadow_verification'):
        row = page.row(key)
        rows[key] = replace(row, operational_fact=row.operational_fact.model_copy(update={'session':plan.decision_session}))
    run = model.TradingRun(intent=plan, state='WAITING_OPEN', updated_at=GENERATED-timedelta(minutes=4))
    return replace(page, operator_review=None, rows=[rows.get(r.key,r) for r in page.rows] + [
        model.Row('trading_run', 'Trading run', 'WAITING_OPEN', model.OK, as_of=run.updated_at, trading_run=run),
        trading_environment_row('https://paper-api.alpaca.markets')])


def published(operational, monkeypatch, state_dir):
    database, owner, _ = operational
    dsn = database.info.dsn
    clock = [GENERATED]
    monkeypatch.setattr(review_store, 'database_now', lambda _: clock[0])
    original = waiting_page(state_dir, dsn)
    prior = review.Recorder(component='verifier', instance='bell-test').observe_owned(database, original, dsn)
    assert prior.status == 'REVIEW' and 'shadow_worker' in prior.warnings and not prior.active
    original = replace(original, operator_review=prior)
    context, subjects = snapshots.context(database, dsn), snapshots.subjects(database, dsn)
    value, signature = snapshots.encode(original, context_sha256=context, subjects=subjects)
    assert value['valid_until'] == BELL.isoformat()
    snapshots.publish_owned(database, owner_id=owner, value=value, signature=signature,
                            context_sha256=context, subjects=subjects, now=clock[0])
    database.commit()
    return database, clock


def test_signed_waiting_warning_survives_bell_as_partial_status(operational, monkeypatch, tmp_path):
    database, clock = published(operational, monkeypatch, tmp_path)
    dsn = database.info.dsn
    assert presentation.dashboard_health(projection_service.read(dsn))['color'] == 'amber'
    clock[0] = READ_AT
    view = projection_service.read(dsn, display=True)
    app = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app, '_config', lambda: (str(tmp_path), dsn))
    response = app.panel_json()
    assert response.status_code == 200 and response.headers['X-Sentinel-Panel-Status'] == 'PARTIAL'
    payload = json.loads(response.body)
    health = payload['dashboard_health']
    assert health['color'] == 'blue' and health['opening_refresh']
    assert 'shadow_worker' in health['review_conditions'] and health['active_conditions'] == []
    assert not payload['observation']['current'] and not payload['observation']['strict_current']
    assert payload['operator_review'] is None and app.operational_health().status_code == 503
    assert 'id="operational-state" class="state checking"' in app.panel().body.decode()
    assert datetime.fromisoformat(health['valid_until']) <= view.row('automation_leader').valid_until
    with pytest.raises(review_store.ReviewRefused):
        projection_service.guard_acknowledgement(database, view, dsn)

    # The same pre-bell page may cross a PAPER receipt change during collection.
    # A new financial refusal wins even while the unchanged reporting warning is retained.
    from tests.sentinel import test_operational_projection_service as fixtures
    monkeypatch.setattr(fixtures, 'datetime', BusinessClock(READ_AT).datetime)
    save_financial(database, 'PAPER', [model.paper_reconciliation_row(state='MISMATCH')])
    changed = projection_service.read(dsn, display=True)
    assert changed.observation_changed_scopes == ('PAPER',)
    assert changed.row('paper_reconciliation').status == model.FAIL
    health = serialization.public_payload(changed)['dashboard_health']
    assert health['color'] == 'red' and 'paper_reconciliation' in health['active_conditions']


def test_partial_view_withdraws_an_outdated_review_head(operational, monkeypatch, tmp_path):
    database, clock = published(operational, monkeypatch, tmp_path)
    clock[0] = READ_AT
    key = review_store.scope(database)
    state = review_store.load_locked(database, key, clock[0])
    review_store.append(database, key, state, kind='REVIEW', event_key='new-condition', details={}, now=clock[0])
    review_store.save(database, key, state, clock[0])
    database.commit()
    result = projection_service.read(database.info.dsn, display=True)
    assert result.operator_review is None and presentation._opening_reporting_deadline(result) is None


def test_waiting_warning_is_bound_to_the_saved_run_and_original_evidence(tmp_path):
    original = waiting_page(tmp_path, 'private')
    signed = reviewed_panel(now=GENERATED).operator_review.model_copy(update={
        'status':'REVIEW', 'warnings':['shadow_worker'], 'active':[], 'token':None})
    page = replace(original, operator_review=signed, now=READ_AT, observation_current=False,
        observation_retained=True, observation_generated_at=GENERATED,
        observation_valid_until=GENERATED+timedelta(seconds=snapshots.MAX_SECONDS))
    assert presentation._opening_reporting_deadline(page) == page.row('automation_leader').valid_until
    changed = replace(page, observation_changed_scopes=('PAPER',))
    assert presentation.dashboard_health(changed)['color'] == 'blue'
    run = page.row('trading_run')
    unknown = trading_environment_row('https://api.alpaca.markets')
    for row in (unknown, replace(page.row('authority'), status=model.FAIL),
                replace(run, trading_run=run.trading_run.model_copy(update={
                    'intent': run.trading_run.intent.model_copy(update={'cycle_id':'other'})}))):
        adverse = replace(page, rows=[row if r.key == row.key else r for r in page.rows])
        assert presentation._opening_reporting_deadline(adverse) is None
        assert presentation.dashboard_health(adverse)['color'] == 'red'
    for changed in (replace(page, now=DUE), replace(page, now=page.row('automation_leader').valid_until),
                    replace(page, observation_changed_scopes=('SHADOW',)),
                    replace(page, operator_review=signed.model_copy(update={'warnings':[]}))):
        assert presentation._opening_reporting_deadline(changed) is None
    from sentinel import shadow_service_status
    (tmp_path / shadow_service_status.CRITICAL_NAME).write_text('halt')
    halt = _shadow_worker_row(tmp_path, 'private')
    assert halt.status == model.FAIL
    failed = replace(page, rows=[halt if r.key == halt.key else r for r in page.rows])
    assert presentation.dashboard_health(failed)['color'] == 'red'
