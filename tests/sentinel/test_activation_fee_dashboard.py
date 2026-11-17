"""Presentation follows the current owned fee wait, not raw stopped-worker rows."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel import activation_fee_wait
from sentinel.panel import model, operational_snapshot, presentation, projection_service, render
from sentinel.panel.review_model import OperatorReview
from sentinel.panel.serialization import public_payload
from tests.sentinel.test_panel_opening_cutoff import ENDED, proof, terminal  # noqa: F401


DECISION = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 4, 5, tzinfo=timezone.utc)
END = NOW + timedelta(minutes=2)


def _row(key, status, *, kind=None, state=None, as_of=NOW, **extra):
    fields = dict(session=DECISION, exposure=Decimal('1')) if key == 'exposure' else {}
    fact = model.OperationalFact(kind=kind, state=state, **fields) if kind else None
    return model.Row(key, key, 'recorded reason', status, as_of=as_of,
                     operational_fact=fact, **extra)


@pytest.fixture
def panel(terminal):
    _, _, prior_run, _, _ = terminal
    unsent, opening_fact = proof(terminal)
    prior_run = model.TradingRun.model_validate(dict(prior_run.model_dump(), unsent_at_cutoff=unsent))
    completed = model.Row('completed_trading_run', 'Recorded run', 'OPENING CUTOFF', model.FAIL,
        as_of=ENDED, valid_until=opening_fact.opening.deadline,
        trading_run=prior_run, operational_fact=opening_fact)
    rows = [_row('automation', model.WARN, kind='AUTOMATION_POLICY', state='INERT'),
            _row('shadow_worker', model.FAIL, kind='SHADOW_WORKER', state='STOPPED'),
            _row('paper_reconciliation', model.FAIL, kind='PAPER_VERIFICATION',
                 state='HISTORICAL_READINESS_WITHDRAWN'),
            _row('exposure', model.UNKNOWN, kind='CONTROLLER_DECISION', state='ROLLOUT_RENEWAL_PENDING'),
            _row('authority', model.UNKNOWN, kind='AUTHORITY', state='ACTIVATION_VERDICT_WITHDRAWN'),
            _row('alpaca_account', model.OK, kind='ALPACA_ACCOUNT', state='READY_SNAPSHOT',
                 as_of=NOW-timedelta(minutes=11), freshness=timedelta(minutes=10), required_current=True),
            _row('backup_restore', model.OK), _row('runtime_identity', model.OK),
            _row('shadow_verification', model.OK), completed]
    review = OperatorReview(scope='a'*64, head=1, reviewed_head=1, status='CLEAN',
                            observed_at=NOW, reviewed_at=NOW)
    return model.Panel(rows=rows, now=NOW, local_paper_mode=True, operator_review=review)


def _attach(panel, monkeypatch, wait=True):
    current = activation_fee_wait.ActivationFeeWait(DECISION, NOW, END, END, 'b'*64, 200)
    monkeypatch.setattr(activation_fee_wait, 'read_owned', lambda *_, **__: current if wait else None)
    return projection_service._with_activation_fee_wait(None, panel, now=panel.now)


def test_live_fee_wait_displays_amber_with_pending_rows_and_unchanged_machine_verdict(panel, monkeypatch):
    active = _attach(panel, monkeypatch)
    health = presentation.dashboard_health(active)
    assert (health['color'], health['label'], health['plan_readiness']) == (
        'amber', 'Installed · Waiting for the Alpaca fee to post', 'pending')
    assert health['valid_until'] == END.isoformat()
    assert presentation.health_facts(active) == {'active': [], 'warnings': []}
    assert active.operational == panel.operational == model.FAIL
    assert active.rows == panel.rows
    payload = public_payload(active)
    assert payload['dashboard_health'] == health
    assert payload['operational'] == model.FAIL
    worker = next(row for row in payload['rows'] if row['key'] == 'shadow_worker')
    assert worker['status'] == 'pending' and worker['original_status'] == 'fail'
    history = next(row for row in payload['rows'] if row['key'] == 'completed_trading_run')
    assert history['status'] == 'fail' and history['trading_run']['state'] == 'SUPERSEDED'
    html = render.render(active)
    assert 'SYSTEM HEALTH AMBER — WAITING FOR ALPACA' in html
    assert 'Awaiting PAPER activation' in html


@pytest.mark.parametrize('fault,active_key', [
    ('backup', 'backup_restore'), ('worker_without_proof', 'shadow_worker'),
    ('account_denial', 'alpaca_account'), ('changed_session', 'exposure'),
    ('unknown_history', 'completed_trading_run'), ('same_cycle_history', 'completed_trading_run'),
    ('source_failure', 'backend_sources'),
])
def test_unrelated_or_unproved_failures_stay_red(panel, monkeypatch, fault, active_key):
    active = _attach(panel, monkeypatch)
    if fault == 'source_failure':
        active = replace(active, source_errors=['financial observation is unavailable'])
    elif fault == 'same_cycle_history':
        active = replace(active, rows=[
            replace(row, trading_run=row.trading_run.model_copy(update=dict(intent=
                row.trading_run.intent.model_copy(update=dict(effective_session=date(2026, 11, 17))))))
            if row.key == active_key else row for row in active.rows])
    elif fault == 'changed_session':
        active = replace(active, rows=[
            replace(row, operational_fact=row.operational_fact.model_copy(update=dict(session=date(2026, 11, 13))))
            if row.key == active_key else row for row in active.rows])
    else:
        active = replace(active, rows=[replace(row, status=model.FAIL, operational_fact=None)
            if row.key == active_key else row for row in active.rows])
    health = presentation.dashboard_health(active)
    assert health['color'] == 'red' and active_key in health['active_conditions']


def test_cutoff_terminal_outcome_and_fresh_healthy_owner_follow_normal_health(panel, monkeypatch):
    active = _attach(panel, monkeypatch)
    assert presentation.dashboard_health(replace(active, now=END))['color'] == 'red'
    assert presentation.dashboard_health(_attach(active, monkeypatch, wait=False))['color'] == 'red'
    healthy = replace(active, rows=[_row('runtime_identity', model.OK)])
    assert presentation.dashboard_health(_attach(healthy, monkeypatch, wait=False))['color'] == 'green'


def test_projection_does_not_serialize_or_replay_the_live_consumer_witness(panel, monkeypatch):
    active = _attach(panel, monkeypatch)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-qualification-'+'q'*40)
    subject = 'c'*64
    value, signature = operational_snapshot.encode(active, context_sha256=subject,
        subjects={'SHADOW': subject, 'PAPER': subject})
    assert 'activation_fee_wait' not in value['panel']
    decoded = operational_snapshot.decode(value, signature, context_sha256=subject, now=NOW)
    assert decoded.panel.activation_fee_wait is None
    assert presentation.dashboard_health(decoded.panel)['color'] == 'red'
    with pytest.raises(operational_snapshot.SnapshotUnavailable, match='CONSUMER_STATE_REFUSED'):
        operational_snapshot._validate_panel(dict(value['panel'], activation_fee_wait={}))
