"""The signed dashboard spans the publication-to-verifier admission gap."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from threading import Event
import uuid

from fastapi.testclient import TestClient
import pytest

from sentinel.feed import calendar, operational_snapshot, publication, rolling_go_inputs
from sentinel.feed import rolling_jobs, rolling_store, store
from sentinel.feed.rolling_contract import RestartRequirement, digest
from sentinel.panel import attempt_store, model, projection_service, read_projection, sources
from tests.sentinel.test_operational_projection_service import (
    conn, operational, pg, publish, save_financial, state,  # noqa: F401
)


DECISION = '2026-09-14'
PREDECESSOR = '2026-09-11'


def _attempt(subject, outcome, observed_at):
    admitted = observed_at - timedelta(seconds=2) if outcome == 'VERIFIED' else observed_at
    value = dict(schema='sentinel.financial-observer-attempt/1', attempt_id=uuid.uuid4().hex,
        subject_sha256=subject, outcome=outcome, admitted_at=admitted.isoformat(),
        deadline=(admitted + timedelta(minutes=10)).isoformat())
    if outcome == 'VERIFIED':
        value.update(work_started_at=admitted.isoformat(), completed_at=observed_at.isoformat(),
                     work_deadline=(admitted + timedelta(minutes=5)).isoformat())
    return value


def _write_attempt(conn, owner, subject, outcome):
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0].astimezone(timezone.utc)
    assert attempt_store.publish_owned(conn, owner_id=owner, scope='SHADOW',
        attempt=_attempt(subject, outcome, now), now=now)
    conn.commit()


def _new_publication(conn, owner):
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0].astimezone(timezone.utc)
    publication._insert_receipted_publication(conn, previous=None, next_version=1, run_id=None,
        published_at=now - timedelta(minutes=2), window_start='2025-01-02',
        window_end=PREDECESSOR, publication_evidence={})
    conn.commit()
    old_subject = read_projection.subject(conn, conn.info.dsn, 'SHADOW')
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    _write_attempt(conn, owner, old_subject, 'VERIFIED')
    job = operational_snapshot.enqueue(conn, strategy_sha256=digest('close-panel-qualification'),
        dependencies_sha256=digest({'scope': rolling_go_inputs.SCHEMA}), budget_seconds=240)
    request = rolling_jobs.PreparationRequest.model_validate(rolling_jobs.status(conn, job)['request'])
    reference = rolling_store.put_evidence(conn, {'source': 'private closing reference'})
    source = rolling_store.put_evidence(conn, {'source': 'private closing data'})
    candidate = rolling_store.begin(conn, window=request.window, reference_sha256=reference,
        source_evidence_sha256=source, expected_publication_version=1,
        dependencies_sha256=request.dependencies_sha256)
    rolling_store.write_bars(conn, candidate, (dict(session=day, security_id='AAA', ticker='AAA',
        close_signal=50, close_unadjusted=50, open_unadjusted=50, volume=1000,
        split_ratio=1, dividend_per_share=0) for day in request.window.sessions))
    rolling_store.write_benchmarks(conn, candidate, (dict(session=day, spy_total_return=100,
        bil_open_signal=50, bil_close_signal=50, bil_close_adjusted=50, bil_close_unadjusted=50)
        for day in request.window.sessions))
    manifest = rolling_store.seal(conn, candidate,
        expected_keys=((str(day), 'AAA') for day in request.window.sessions),
        normalization_version='private-qualified', requirements=RestartRequirement(),
        provider='ALPACA_OPENFIGI')
    validated = rolling_store.put_evidence(conn, dict(schema=operational_snapshot.VALIDATION_SCHEMA,
        scope='DATA_ONLY', snapshot_id=manifest.snapshot_id, reference_sha256=reference,
        source_evidence_sha256=source, request_sha256=request.request_sha256))
    conn.execute('INSERT INTO sentinel_operational_snapshot_validations VALUES (%s,%s)', (candidate, validated))
    committed_at = conn.execute('SELECT clock_timestamp()').fetchone()[0].astimezone(timezone.utc)
    binding = dict(schema=operational_snapshot.SCHEMA, job_id=job, candidate_id=candidate,
        snapshot_id=manifest.snapshot_id, reference_sha256=reference, validation_sha256=validated)
    publication._insert_receipted_publication(conn, previous=publication._core.current(conn),
        next_version=2, run_id=None, published_at=committed_at, window_start=str(request.window.start),
        window_end=DECISION, publication_evidence={'rolling_snapshot': binding})
    conn.execute('INSERT INTO sentinel_operational_snapshots VALUES (2,%s,%s,%s)',
                 (job, candidate, validated))
    conn.execute("UPDATE sentinel_snapshot_jobs SET state='PUBLISHED', candidate_id=%s, "
                 "publication_version=2 WHERE job_id=%s", (candidate, job))
    conn.commit()
    assert operational_snapshot.published(conn, job)['data_version'] == 2
    new_subject = read_projection.subject(conn, conn.info.dsn, 'SHADOW')
    conn.rollback()
    assert new_subject != old_subject
    return old_subject, new_subject, committed_at


@pytest.mark.parametrize('measured_failure', [False, True])
def test_signed_panel_during_closing_publication_before_verifier_admission(
        operational, monkeypatch, measured_failure):
    conn, owner, condition = operational
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + '2' * 64)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: DECISION)
    old_subject, current_subject, committed_at = _new_publication(conn, owner)
    # Supply only the market schedule. All original job, verifier, worker and
    # signed dashboard receipt clocks remain the private PostgreSQL wall clock.
    session_window = calendar.session_window
    effective = calendar.next_session(DECISION)
    bounds = {DECISION: (committed_at - timedelta(hours=7), committed_at - timedelta(minutes=1)),
              effective: (committed_at + timedelta(hours=8), committed_at + timedelta(hours=14))}
    monkeypatch.setattr(calendar, 'session_window',
        lambda session: bounds[str(session)] if str(session) in bounds else session_window(session))
    collect = sources.build_panel
    condition['financial'] = True

    def collect_closing_facts(**kwargs):
        panel = collect(**kwargs)
        deadline = panel.now + timedelta(minutes=2)
        feed = model.feed_row(frontier=DECISION, sessions_behind=0,
            ready=False if measured_failure else None, checks_passed=1 if measured_failure else 0,
            checks_total=2 if measured_failure else 0, checked_at=panel.now if measured_failure else None,
            as_of=committed_at, publication_version=2)
        shadow = model.Row('shadow_verification', 'Shadow', 'CHECK IN PROGRESS', model.WARN,
            required_current=True, valid_until=deadline,
            recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION', automatic=True, deadline=deadline))
        worker = model.Row('shadow_worker', 'Strategy worker', 'RUNNING', model.OK,
            as_of=panel.now, required_current=True, valid_until=panel.now + timedelta(seconds=45),
            operational_fact=model.OperationalFact(kind='SHADOW_WORKER', state='ACTIVE_WORKER'))
        return replace(panel, rows=[row for row in panel.rows if row.key not in {feed.key, shadow.key}]
                       + [feed, shadow, worker])

    monkeypatch.setattr(sources, 'build_panel', collect_closing_facts)
    app = importlib.import_module('sentinel.panel.app')
    dsn = conn.info.dsn
    monkeypatch.setattr(app, '_read_panel', lambda: projection_service.read(dsn, display=True))
    permit_admission = Event()

    def admit_new_subject():
        assert permit_admission.wait(10), 'collector never sampled the admission gap'
        with store.connect(dsn, connect_timeout=2, statement_timeout_ms=3000) as verifier:
            _write_attempt(verifier, owner, current_subject, 'QUEUED')

    def read_close(client, expected_subject):
        publish(operational)
        response = client.get('/panel.json')
        assert response.status_code == 200
        body = response.json()
        assert body['verification_attempts']['SHADOW']['latest']['subject_sha256'] == expected_subject
        feed = next(row for row in body['rows'] if row['key'] == 'feed')
        assert feed['current']
        assert datetime.fromisoformat(feed['as_of']) == committed_at
        health = body['dashboard_health']
        assert health['plan_readiness'] != 'ready'
        if measured_failure:
            assert feed['status'] == model.FAIL and feed['recovery'] is None
            assert feed['operational_fact']['state'] == 'NOT_READY'
            assert health['color'] == 'red' and 'feed' in health['active_conditions']
            assert 'feed' in state(conn)['active']
        else:
            assert feed['status'] == model.WARN, 'unmeasured publication handoff appeared failed'
            assert feed['feed_readiness'] == 'AWAITING_VERDICT' and feed['source_publication_version'] == 2
            assert health['color'] == 'amber' and 'feed' not in health['active_conditions']
            assert 'feed' not in state(conn)['active']
        return feed

    with TestClient(app.app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        admission = executor.submit(admit_new_subject)
        try:
            before = read_close(client, old_subject)
        finally:
            permit_admission.set()
        admission.result(timeout=5)
        after = read_close(client, current_subject)
    if not measured_failure:
        assert datetime.fromisoformat(before['valid_until']) <= committed_at + timedelta(seconds=60)
        assert after['recovery']['phase'] == 'READINESS_HANDOFF'
