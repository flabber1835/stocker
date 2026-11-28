"""Reconstruct the November 27 bell crossing from its independent row and signed clocks."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import importlib
import json

import pytest

from sentinel.panel import delivery, model, operational_snapshot as snapshots, presentation, projection_service
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


def waiting_page(state_dir, dsn, *, generated=GENERATED, leader_end=None):
    page = healthy_history_panel(now=generated, execute_at=DUE)
    saved = page.row('paper_plan')
    plan = saved.paper_plan.model_copy(update={'decision_session': date(2026, 11, 25),
        'effective_session': BELL.date(), 'execution_open_at': None})
    rows = {
        'paper_plan': replace(saved, paper_plan=plan),
        'shadow_worker': _shadow_worker_row(state_dir, dsn),
        'paper_reconciliation': replace(model.paper_reconciliation_row(state='PENDING', cycle_state='WAITING_OPEN'),
            as_of=generated-timedelta(seconds=43), freshness=timedelta(minutes=10)),
    }
    if leader_end is not None:
        rows['automation_leader'] = replace(page.row('automation_leader'), valid_until=leader_end)
    for key in ('feed', 'shadow_verification'):
        row = page.row(key)
        rows[key] = replace(row, operational_fact=row.operational_fact.model_copy(update={'session':plan.decision_session}))
    run = model.TradingRun(intent=plan, state='WAITING_OPEN', updated_at=generated-timedelta(minutes=4))
    return replace(page, operator_review=None, rows=[rows.get(r.key,r) for r in page.rows] + [
        model.Row('trading_run', 'Trading run', 'WAITING_OPEN', model.OK, as_of=run.updated_at, trading_run=run),
        trading_environment_row('https://paper-api.alpaca.markets')])


def published(operational, monkeypatch, state_dir, *, generated=GENERATED, leader_end=None):
    database, owner, _ = operational
    dsn = database.info.dsn
    clock = [generated]
    monkeypatch.setattr(review_store, 'database_now', lambda _: clock[0])
    original = waiting_page(state_dir, dsn, generated=generated, leader_end=leader_end)
    prior = review.Recorder(component='verifier', instance='bell-test').observe_owned(database, original, dsn)
    assert prior.status == 'REVIEW' and 'shadow_worker' in prior.warnings and not prior.active
    original = replace(original, operator_review=prior)
    context, subjects = snapshots.context(database, dsn), snapshots.subjects(database, dsn)
    value, signature = snapshots.encode(original, context_sha256=context, subjects=subjects)
    if generated < BELL:
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
    worker = next(row for row in payload['rows'] if row['key'] == 'shadow_worker')
    assert worker['original_status'] == model.UNKNOWN and not worker['current']
    assert health['active_conditions'] == []
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


@pytest.mark.parametrize('next_snapshot_published', [False, True])
def test_consecutive_partial_responses_use_their_own_signed_clocks(
        operational, monkeypatch, tmp_path, next_snapshot_published):
    # The sampled database gives us two possible snapshots for the 06:30:05
    # response. Collection time alone does not settle which transaction was visible.
    generated = BELL - timedelta(seconds=6, microseconds=322420)
    first_expiry = BELL + timedelta(seconds=3, microseconds=531658)
    database, clock = published(operational, monkeypatch, tmp_path, generated=generated, leader_end=first_expiry)
    dsn = database.info.dsn
    clock[0] = BELL + timedelta(microseconds=45370)
    first = projection_service.read(dsn, display=True)
    assert presentation.dashboard_health(first)['color'] == 'blue'
    lease_expiry = first_expiry
    if next_snapshot_published:
        generated = BELL + timedelta(seconds=1, microseconds=111956)
        lease_expiry = BELL + timedelta(seconds=12, microseconds=648823)
        database, clock = published(operational, monkeypatch, tmp_path,
                                    generated=generated, leader_end=lease_expiry)
        # An independently refreshed PAPER receipt invalidates a subject
        # without changing the waiting plan or the absent supervisor report.
        from tests.sentinel import test_operational_projection_service as fixtures
        monkeypatch.setattr(fixtures, 'datetime', BusinessClock(generated).datetime)
        save_financial(database, 'PAPER', [model.paper_reconciliation_row(state='PENDING', cycle_state='WAITING_OPEN')])
    display_expiry = generated + timedelta(seconds=snapshots.MAX_SECONDS)
    stamps = (first_expiry, BELL+timedelta(seconds=5, microseconds=186339),
              BELL+timedelta(seconds=10, microseconds=243704), BELL+timedelta(seconds=15, microseconds=676517),
              display_expiry-timedelta(microseconds=1))
    for clock[0] in stamps:
        page = projection_service.read(dsn, display=True)
        assert page.observation_generated_at == generated and page.row('automation_leader').valid_until == lease_expiry
        payload = serialization.public_payload(page)
        health = payload['dashboard_health']
        assert not payload['observation']['current'] and health['color'] == 'blue'
        assert 'shadow_worker' not in health['active_conditions']
        by_key = {r['key']:r for r in payload['rows']}
        assert not by_key['shadow_worker']['current'] and by_key['shadow_worker']['original_status'] == model.UNKNOWN
        if page.now >= lease_expiry:
            assert not by_key['automation_leader']['current']
        assert set(health['trading_continuity']['reason_codes']) == {'STATUS_UNKNOWN'}
        if page.now == BELL+timedelta(seconds=5, microseconds=186339):
            with monkeypatch.context() as removed:
                removed.setattr(delivery, 'row_current', delivery._source_current)
                old = presentation.dashboard_health(page)
                assert old['color'] == 'red' and old['active_conditions'] == ['shadow_worker']
    clock[0] = display_expiry
    with pytest.raises(snapshots.SnapshotUnavailable, match='DISPLAY_WINDOW_EXHAUSTED'):
        projection_service.read(dsn, display=True)

    database, clock = published(operational, monkeypatch, tmp_path, generated=display_expiry,
                                leader_end=display_expiry+timedelta(seconds=12))
    current = projection_service.read(dsn, display=True)
    assert current.observation_current and presentation.dashboard_health(current)['color'] == 'amber'


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
    wrong_run = replace(run, trading_run=run.trading_run.model_copy(update={
        'intent': run.trading_run.intent.model_copy(update={'cycle_id':'other'})}))
    for row, expected in ((unknown, 'red'), (replace(page.row('authority'), status=model.FAIL), 'red'),
                          (wrong_run, 'blue')):
        adverse = replace(page, rows=[row if r.key == row.key else r for r in page.rows])
        assert presentation._opening_reporting_deadline(adverse) is None
        assert presentation.dashboard_health(adverse)['color'] == expected
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
