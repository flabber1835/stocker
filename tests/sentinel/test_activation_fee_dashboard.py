"""Presentation follows the current owned fee wait, not raw stopped-worker rows."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import activation_fee_wait
from sentinel.panel import model, operational_snapshot, presentation, projection_service, read_projection, render
from sentinel.panel import authority_reader, observer_codec, verification_service
from sentinel.panel.review_model import OperatorReview
from sentinel.panel.serialization import public_payload
from tests.sentinel.test_panel_opening_cutoff import ENDED, proof, terminal  # noqa: F401


DECISION = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 4, 5, tzinfo=timezone.utc)
END = NOW + timedelta(minutes=2)


def _row(key, status, *, kind=None, state=None, as_of=NOW, **extra):
    fields = dict(session=DECISION, exposure=Decimal('1')) if key == 'exposure' else {}
    if state == 'HISTORICAL_READINESS_WITHDRAWN':
        fields['session'] = DECISION
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
            _row('paper_reconciliation', model.PENDING, kind='PAPER_VERIFICATION',
                 state='HISTORICAL_READINESS_WITHDRAWN', required_current=True, valid_until=END),
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


def test_paper_projection_cannot_use_withdrawn_or_older_wait(panel, monkeypatch):
    rows = [panel.row('paper_reconciliation')]
    _attach(panel, monkeypatch)
    assert read_projection._activation_paper_rows(None, rows, now=NOW) == rows
    for now, live in ((END, True), (NOW, False)):
        _attach(panel, monkeypatch, wait=live)
        restored, = read_projection._activation_paper_rows(None, rows, now=now)
        assert restored.status == model.FAIL and restored.operational_fact is None
        assert (restored.as_of, restored.valid_until) == (rows[0].as_of, rows[0].valid_until)


@pytest.mark.parametrize('renewal_offset', [-1, 1])
def test_paper_projection_uses_earlier_original_expiry_of_both_witnesses(panel, monkeypatch, renewal_offset):
    signed = panel.row('paper_reconciliation')
    renewed_expiry = END + timedelta(microseconds=renewal_offset)
    later = activation_fee_wait.ActivationFeeWait(DECISION, NOW+timedelta(seconds=1),
        renewed_expiry, renewed_expiry, 'b'*64, 200)
    monkeypatch.setattr(activation_fee_wait, 'read_owned', lambda *_, **__: later)
    returned, = read_projection._activation_paper_rows(None, [signed], now=later.observed_at)
    assert returned.status == model.PENDING and returned.as_of == signed.as_of
    assert returned.valid_until == min(signed.valid_until, renewed_expiry)
    assert signed.valid_until == END


def test_owned_paper_observer_schedules_refresh_before_pending_expires(panel, monkeypatch):
    elapsed = [0]
    started = []
    key = 'c'*64
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-qualification-'+'q'*40)
    monkeypatch.setattr(authority_reader, 'Thread',
        lambda **_: SimpleNamespace(start=lambda: started.append(elapsed[0])))
    reader = authority_reader.Reader(clock=lambda: elapsed[0],
        wall_clock=lambda: NOW+timedelta(seconds=elapsed[0]),
        evidence_reader=lambda *_: key, expected_keys=frozenset({'paper_reconciliation'}))
    pending = replace(panel.row('paper_reconciliation'),
                      valid_until=NOW+activation_fee_wait.FRESHNESS)
    observed = NOW + timedelta(seconds=1)
    elapsed[0] = 1
    reader.answer = (key, observer_codec.pack([pending], [], observed_at=observed), None, observed)
    result = reader.read('private', allow_start=False)
    assert reader.attempt_outcome == 'VERIFIED' and reader.failure_diagnostic is None
    assert result[0][0].as_of == NOW and result[0][0].valid_until == pending.valid_until
    signed = verification_service.snapshot(reader, result, scope='PAPER', now=observed)
    assert signed[0]['valid_until'] == pending.valid_until.isoformat()
    elapsed[0] = 209
    reader.read('private')
    assert not started
    elapsed[0] = 210
    reader.read('private')
    assert started == [210] and elapsed[0] < authority_reader.REFRESH_SECONDS

    # A queued PAPER observation may spend 83 seconds behind the shared slot.
    # It must be admitted early enough to complete with the renewed witness
    # while the original signed pending proof is still current.
    elapsed[0] = 301
    renewed = replace(pending, as_of=NOW+timedelta(seconds=204),
        valid_until=NOW+timedelta(seconds=564))
    reader.answer = (key, observer_codec.pack([renewed], [],
        observed_at=NOW+timedelta(seconds=301)), None, NOW+timedelta(seconds=301))
    renewed_result = reader.read('private', allow_start=False)
    assert renewed_result[0][0].as_of == renewed.as_of
    renewed_signed = verification_service.snapshot(reader, renewed_result,
        scope='PAPER', now=NOW+timedelta(seconds=301))
    assert renewed_signed[0]['valid_until'] == renewed.valid_until.isoformat()
    assert verification_service.snapshot(reader, result, scope='PAPER',
        now=renewed.valid_until+timedelta(microseconds=1)) is None


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
