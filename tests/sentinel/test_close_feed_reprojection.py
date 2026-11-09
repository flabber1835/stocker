"""Dependent feed waits are recomputed from the current authenticated inputs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import inspect
import textwrap

import pytest

from sentinel.feed import calendar
from sentinel.panel import model, postclose_feed_wait as waiting, projection_service as producer
from tests.sentinel.test_close_projection_coherence import NOW, page
from tests.sentinel.test_operational_projection_service import (
    conn, financial_rows, operational, pg, publish, save_financial, state,  # noqa: F401
)


def withdrawn(phase, fault):
    original = waiting.reproject(page(typed=True), now=NOW)
    feed = original.row('feed')
    feed = replace(feed, recovery=replace(feed.recovery, phase=phase))
    rows = [feed if row.key == 'feed' else row for row in original.rows]
    if fault == 'missing':
        rows = [row for row in rows if row.key != 'shadow_verification']
    else:
        key = 'shadow_worker' if fault == 'dead_worker' else 'shadow_verification'
        changes = ({'status': model.FAIL} if fault in {'negative', 'dead_worker'}
                   else {'source_publication_version': 18} if fault == 'foreign'
                   else {'recovery': replace(original.row(key).recovery,
                                              phase='FINANCIAL_VERIFICATION')})
        rows = [replace(row, **changes) if row.key == key else row for row in rows]
    return feed, waiting.reproject(replace(original, rows=rows), now=NOW).row('feed')


@pytest.mark.parametrize('phase', ['SHADOW_ATTESTATION', 'READINESS_HANDOFF'])
@pytest.mark.parametrize('fault', ['missing', 'negative', 'generic', 'foreign', 'dead_worker'])
def test_removed_or_refused_enabling_proof_withdraws_only_its_derived_wait(phase, fault):
    before, after = withdrawn(phase, fault)
    assert after.recovery is None, 'a derived wait survived loss of its enabling proof'
    assert after.effective_status(NOW) == model.FAIL
    assert replace(after, recovery=before.recovery, detail=before.detail) == before
    assert 'no current matching bounded readiness handoff' in after.detail


@pytest.mark.parametrize('status,phase', [
    (model.FAIL, 'SHADOW_ATTESTATION'), (model.UNKNOWN, 'READINESS_HANDOFF'),
    (model.WARN, 'FEED_INGEST')])
def test_native_negatives_and_unrelated_recovery_are_untouched(status, phase):
    original = page()
    feed = replace(original.row('feed'), status=status,
        recovery=model.RecoveryEvidence(phase=phase, automatic=True,
                                        deadline=NOW+timedelta(seconds=30)))
    original = replace(original, rows=[feed if row.key == 'feed' else row for row in original.rows])
    assert waiting.reproject(original, now=NOW).row('feed') is feed


def test_disabled_withdrawal_is_detected_by_an_executed_falsifier(monkeypatch):
    source = textwrap.dedent(inspect.getsource(waiting.reproject))
    guard = "and row.recovery.phase in {'READINESS_HANDOFF', 'SHADOW_ATTESTATION'}"
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'and False'), '<disabled-derived-withdrawal>', 'exec'),
         vars(waiting), namespace)
    monkeypatch.setattr(waiting, 'reproject', namespace['reproject'])
    with pytest.raises(AssertionError, match='derived wait survived'):
        test_removed_or_refused_enabling_proof_withdraws_only_its_derived_wait(
            'SHADOW_ATTESTATION', 'negative')


def receipt_handoff(operational, monkeypatch):
    """Publish the old feed and then replace only the real signed receipt."""
    from sentinel.panel import sources
    conn, _, condition = operational
    condition['financial'] = True
    collect = sources.build_panel
    captured = {}

    def with_pending_feed(**kwargs):
        panel = collect(**kwargs)
        feed = model.feed_row(frontier=calendar.latest_closed_session(panel.now),
            sessions_behind=0, ready=None, checks_passed=0, checks_total=0,
            as_of=panel.now, publication_version=17)
        worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK,
            as_of=panel.now, required_current=True, valid_until=panel.now+timedelta(seconds=45))
        captured['feed'], captured['worker'] = feed, worker
        return replace(panel, rows=[*[row for row in panel.rows if row.key != 'feed'], feed, worker])

    monkeypatch.setattr(sources, 'build_panel', with_pending_feed)
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    assert baseline.row('feed').effective_status(baseline.now) == model.FAIL
    now = datetime.now(timezone.utc)
    deadline = now+timedelta(minutes=4)
    typed = model.Row('shadow_verification', 'Shadow', 'AWAITING ATTESTATION', model.WARN,
        as_of=now, required_current=True, valid_until=deadline,
        source_publication_version=17, source_session=captured['feed'].source_session,
        recovery=model.RecoveryEvidence(phase='SHADOW_ATTESTATION', automatic=True, deadline=deadline))
    save_financial(conn, 'SHADOW', [replace(typed, key=row.key, label=row.label)
                                   for row in financial_rows('SHADOW', now)])
    return conn, baseline, captured


def assert_http_handoff(conn, baseline, captured, monkeypatch):
    from fastapi.testclient import TestClient
    app = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app, '_read_panel', lambda: producer.read(conn.info.dsn, display=True))
    before = state(conn)
    client = TestClient(app.app)
    try:
        response = client.get('/panel.json')
        assert response.status_code == 200
        body = response.json()
        feed = next(row for row in body['rows'] if row['key'] == 'feed')
        assert feed['original_status'] == model.WARN, 'fresh receipt was not reprojected'
        assert feed['current'] and feed['status'] == model.WARN and feed['color'] == 'amber'
        assert feed['recovery']['phase'] == 'SHADOW_ATTESTATION'
        assert datetime.fromisoformat(feed['as_of']) == captured['feed'].as_of
        assert datetime.fromisoformat(feed['valid_until']) == captured['worker'].valid_until
        assert body['observation']['strict_current'] is False
        assert body['operational'] == model.UNKNOWN and body['operator_review'] is None
        assert body['dashboard_health']['active_conditions'] == []
        # GET explains the current handoff; only background observation can
        # record recovery of the previously durable feed refusal.
        assert baseline.operator_review.status == 'FAILED'
        assert body['dashboard_health']['color'] == 'red'
        assert not body['source_errors']
        machine = client.get('/operational-health')
        assert machine.status_code == 503 and machine.json()['current'] is False
        assert machine.json()['status'] == model.UNKNOWN
    finally:
        client.close()
    assert state(conn) == before
    assert baseline.row('feed').recovery is None


def test_http_changed_signed_receipt_reprojects_feed_without_collection_or_authority(
        operational, monkeypatch):
    conn, baseline, captured = receipt_handoff(operational, monkeypatch)
    assert_http_handoff(conn, baseline, captured, monkeypatch)


def test_omitted_http_reprojection_is_detected_with_real_signed_receipts(operational, monkeypatch):
    conn, baseline, captured = receipt_handoff(operational, monkeypatch)
    source = textwrap.dedent(inspect.getsource(producer.read))
    guard = ("        panel = postclose_feed_wait.reproject(panel, now=now,\n"
             "            subject=current_basis['native']['SHADOW'] if current_basis else None)\n")
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), '<omitted-http-reprojection>', 'exec'),
         vars(producer), namespace)
    monkeypatch.setattr(producer, 'read', namespace['read'])
    with pytest.raises(AssertionError, match='fresh receipt was not reprojected'):
        assert_http_handoff(conn, baseline, captured, monkeypatch)
