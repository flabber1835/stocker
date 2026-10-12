"""Producer-to-operator acceptance and falsifiers for interrupted publishers."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import inspect
import json
import os
from pathlib import Path
import textwrap
import time
from types import SimpleNamespace

import pytest

from sentinel import shadow_service_status as status, shadow_supervisor as supervisor
from sentinel.panel import app, model, sources
from sentinel.panel.authority_reader import _unknown
from sentinel.panel.render import render
from tests.sentinel.test_supervisor_dependency_bounds import pg, conn

NOW = datetime(2026, 10, 11, 23, tzinfo=timezone.utc)
DSN = 'postgresql://qualification/sentinel'
A = 'a'*32
B = 'b'*32


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', DSN)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'qualification-receipt-key-00000000000000')
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    monkeypatch.setattr(supervisor, 'LATCH_FILE', tmp_path/status.CRITICAL_NAME)
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', tmp_path/'heartbeat')
    monkeypatch.setattr(supervisor.shadow_worker_liveness, 'ACTIVE_FILE', tmp_path/'active.json')
    return tmp_path


def arm(state, attempt=A):
    (state/status.PENDING_NAME).write_text(json.dumps(dict(
        schema='sentinel.shadow-supervisor-pending/2', attempt_id=attempt,
        started_at_unix=NOW.timestamp())))


def active(state, monkeypatch):
    arm(state)
    monkeypatch.setattr(supervisor.shadow_worker_liveness, 'matches', lambda _: True)
    monkeypatch.setattr(status.time, 'monotonic', lambda: 100)
    (state/'active.json').write_text(json.dumps({'deadline_monotonic': 400}))
    status.publish(state/status.CRITICAL_NAME, A, now=NOW)


def row(state, monkeypatch):
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **k: fn(*a))
    return sources._shadow_worker_row(state, DSN)


def test_idle_and_active_worker_are_current_on_json_and_html(state, monkeypatch):
    for running in (False, True):
        if running:
            active(state, monkeypatch)
        else:
            status.publish(state/status.CRITICAL_NAME, A, now=NOW)
        worker = row(state, monkeypatch)
        page = model.Panel(rows=[worker], now=NOW)
        monkeypatch.setattr(app, '_config', lambda: (state, DSN))
        monkeypatch.setattr(app, 'build_panel', lambda **k: page)
        monkeypatch.setattr(app, '_shadow_segment_disclosure', lambda p, d: p)
        actual = json.loads(app.panel_json().body)
        assert actual['operational'] == model.OK
        assert actual['rows'][0]['color'] == 'green'
        assert 'data-key="shadow_worker" data-status="ok"' in render(page)
        assert worker.as_of == NOW
        assert worker.valid_until == NOW+timedelta(seconds=60)


def test_real_spawned_reader_can_observe_current_worker(state):
    status.publish(state/status.CRITICAL_NAME, A)
    worker = sources._shadow_worker_row(state, DSN)
    assert worker.status == model.OK, worker.detail


def test_stalled_status_file_cannot_block_the_http_worker(state):
    os.mkfifo(state/status.NAME)
    started = time.monotonic()
    worker = sources._shadow_worker_row(state, DSN)
    assert worker.status == model.UNKNOWN and 'TimeoutError' in worker.detail
    assert time.monotonic()-started < 4.5


@pytest.mark.parametrize('damage', ['missing', 'signature', 'shape', 'future', 'expired', 'runtime', 'attempt', 'critical'])
def test_broken_worker_proof_cannot_establish_operational_green(state, monkeypatch, damage):
    active(state, monkeypatch)
    target = state/status.NAME
    if damage == 'missing': target.unlink()
    elif damage in {'signature', 'shape'}:
        wrapped = json.loads(target.read_text())
        if damage == 'signature': wrapped['hmac_sha256'] = '0'*64
        else: wrapped['status']['surprise'] = True; wrapped['hmac_sha256'] = status._signature(wrapped['status'])
        target.write_text(json.dumps(wrapped))
    elif damage == 'runtime': monkeypatch.setenv('SENTINEL_GIT_COMMIT', '3'*40)
    elif damage == 'attempt': arm(state, B)
    elif damage == 'critical': (state/status.CRITICAL_NAME).write_text('terminal refusal')
    check_at = NOW+timedelta(seconds=61) if damage == 'expired' else NOW-timedelta(seconds=6) if damage == 'future' else NOW
    worker = row(state, monkeypatch)
    page = model.Panel(rows=[worker], now=check_at)
    assert page.operational in {model.FAIL, model.UNKNOWN}
    assert 'OPERATIONAL RED' in render(page)


def test_missing_process_during_ack_handoff_cannot_renew_or_be_adopted(state, monkeypatch):
    active(state, monkeypatch)
    original = (state/status.NAME).read_bytes()
    monkeypatch.setattr(supervisor.shadow_worker_liveness, 'matches', lambda _: False)
    status.publish(state/status.CRITICAL_NAME, A, now=NOW+timedelta(seconds=1))
    assert (state/status.NAME).read_bytes() == original
    status.publish(state/status.CRITICAL_NAME, B, now=NOW+timedelta(seconds=2))
    assert status.read(state, DSN)['state'] == 'FENCED'


def test_acknowledgement_to_idle_handoff_keeps_only_original_proof(state, monkeypatch):
    active(state, monkeypatch)
    (state/status.PENDING_NAME).unlink()
    assert status.read(state, DSN)['observed_at'] == NOW
    assert row(state, monkeypatch).effective_status(NOW+timedelta(seconds=61)) == model.FAIL
    status.publish(state/status.CRITICAL_NAME, A, now=NOW+timedelta(seconds=2))
    assert status.read(state, DSN)['reason'] == 'IDLE'


def test_active_worker_deadline_never_moves_forward(state, monkeypatch):
    active(state, monkeypatch)
    initial = status.read(state, DSN)['worker_deadline']
    status.publish(state/status.CRITICAL_NAME, A, now=NOW+timedelta(seconds=10))
    assert status.read(state, DSN)['worker_deadline'] == initial


def test_worker_failure_does_not_relabel_verified_saved_portfolio(state, monkeypatch):
    arm(state)
    status.publish(state/status.CRITICAL_NAME, A, now=NOW)
    worker = row(state, monkeypatch)
    shadow = model.shadow_verification_row(verdict='SHADOW_GO', verification='VERIFIED', session='2026-10-09')
    page = model.Panel(rows=[shadow, worker], now=NOW)
    assert page.operational == model.FAIL and shadow.effective_status(NOW) == model.OK
    html = render(page)
    assert 'data-key="shadow_verification" data-status="ok"' in html
    assert 'href="#status-shadow_worker"' in html and 'HALTED' in html


@pytest.mark.parametrize('change', ['critical', 'attempt', 'ack'])
def test_changed_negative_marker_during_read_withdraws_positive_observation(state, monkeypatch, change):
    active(state, monkeypatch)
    from sentinel import shadow_service_probe as probe
    original = probe.raw
    def changed(path):
        value = original(path)
        if path.name == status.NAME:
            if change == 'critical': (state/status.CRITICAL_NAME).write_text('terminal refusal')
            elif change == 'attempt': arm(state, B)
            else: (state/status.PENDING_NAME).unlink()
        return value
    monkeypatch.setattr(probe, 'raw', changed)
    worker = row(state, monkeypatch)
    if change == 'ack':
        assert worker.effective_status(NOW) == model.OK and worker.as_of == NOW
    else: assert worker.effective_status(NOW) in {model.FAIL, model.UNKNOWN}


def test_malformed_retained_attempt_is_reported_without_exposing_raw_contents(state):
    raw = '{private malformed marker'
    (state/status.PENDING_NAME).write_text(raw)
    incident = supervisor._retained_interruption()
    assert incident['reason'] == 'UNREADABLE_PENDING_MARKER'
    assert raw not in json.dumps(incident) and len(incident['incident_sha256']) == 64


def test_browser_document_cannot_outlive_original_worker_proof(state, monkeypatch):
    status.publish(state/status.CRITICAL_NAME, A, now=NOW)
    worker = row(state, monkeypatch)
    healthy = render(model.Panel(rows=[worker], now=NOW))
    assert 'data-max-age-seconds="45"' in healthy and '}, 30000)' in healthy
    late = render(model.Panel(rows=[worker], now=NOW+timedelta(seconds=50)))
    assert 'data-max-age-seconds="10.0"' in late and '}, 1000)' in late
    assert worker.as_of == NOW and worker.valid_until == NOW+timedelta(seconds=60)


def test_removed_browser_worker_proof_cap_is_detected(state, monkeypatch):
    source = textwrap.dedent(inspect.getsource(render))
    line = 'document_age = min(document_age, max(0, (worker.valid_until-now).total_seconds()))'
    assert line in source
    namespace = {}; exec(compile(source.replace(line, 'document_age = PRESENTATION_MAX_AGE_SECONDS'),
        'worker-document-falsifier', 'exec'), render.__globals__, namespace)
    monkeypatch.setitem(globals(), 'render', namespace['render'])
    with pytest.raises(AssertionError):
        test_browser_document_cannot_outlive_original_worker_proof(state, monkeypatch)


class Visible(HTMLParser):
    def __init__(self): super().__init__(); self.closed_details=0; self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'details': self.closed_details += 1
    def handle_endtag(self, tag):
        if tag == 'details': self.closed_details -= 1
    def handle_data(self, value):
        if not self.closed_details: self.parts.append(value)


def test_last_known_numbers_and_failure_reasons_are_visible_without_expanding_details():
    previous = model.Row('shadow_nav', 'Certified shadow NAV', '$50,575.09', model.OK, as_of=NOW)
    rows, _, _, errors = _unknown(True, 'verification running', [previous], checking_until=NOW+timedelta(seconds=300))
    rows.append(model.Row('automation_alerts', 'Automation alerts', '2 unacked', model.FAIL))
    html = render(model.Panel(rows=rows, source_errors=errors, now=NOW+timedelta(seconds=1)))
    visible = Visible(); visible.feed(html.split('<script>', 1)[0])
    assert 'LAST KNOWN · $50,575.09' in ''.join(visible.parts)
    assert 'Needs attention' in ''.join(visible.parts)
    assert 'href="#status-automation_alerts"' in html


def test_startup_retained_attempt_alert_is_idempotent_and_never_launches_a_worker(state, monkeypatch, conn):
    from sentinel import schema
    schema.ensure_schema(conn)
    from sentinel.automation import outbox
    arm(state)
    original = (state/status.PENDING_NAME).read_bytes()
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **kw: fn(*a))
    monkeypatch.setattr(supervisor, '_enqueue_alert', lambda **kw: outbox.enqueue(conn, **kw))
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(poll_seconds=300))
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor, '_latched_wait', lambda *a: 91)
    monkeypatch.setattr(supervisor.subprocess, 'Popen', lambda *a, **k: pytest.fail('interrupted worker launched'))
    for _ in range(3): assert supervisor.run() == 91
    assert (state/status.PENDING_NAME).read_bytes() == original
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='SHADOW_SUPERVISOR_LATCHED'").fetchone()[0] == 1
    arm(state, B)
    assert supervisor.run() == 91
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='SHADOW_SUPERVISOR_LATCHED'").fetchone()[0] == 2


def test_notification_retry_remains_bounded_and_never_clears_the_fence(state, monkeypatch):
    arm(state); clock = [0]; calls=[]
    monkeypatch.setattr(supervisor.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(supervisor.time, 'sleep', lambda _: clock.__setitem__(0, clock[0]+10))
    monkeypatch.setattr(supervisor, '_touch', lambda: None)
    def notify(): calls.append(clock[0]); return len(calls)>1
    monkeypatch.setattr(supervisor, '_report_retained_interruption', notify)
    assert supervisor._latched_wait(lambda: clock[0] >= 40) == 0
    assert calls == [0,30] and (state/status.PENDING_NAME).exists()


@pytest.mark.parametrize('guard', ['signature', 'runtime', 'attempt', 'incarnation', 'expiry', 'critical'])
def test_removed_monitoring_guards_are_detected(state, monkeypatch, guard):
    if guard == 'signature':
        monkeypatch.setattr(status.hmac, 'compare_digest', lambda *a: True)
    elif guard == 'critical':
        from sentinel import shadow_service_probe as probe
        source = textwrap.dedent(inspect.getsource(probe.observe))
        assert source.count('if critical.exists():') == 2
        namespace = {}; exec(compile(source.replace('if critical.exists():', 'if False:'),
            'worker-critical-probe-falsifier', 'exec'), probe.__dict__, namespace)
        monkeypatch.setattr(probe, 'observe', namespace['observe'])
    elif guard in {'runtime', 'attempt'}:
        source = textwrap.dedent(inspect.getsource(status.decode_probe))
        line = {'runtime': 'if value.binding_sha256 != binding(database_url):',
                'attempt': "if value.state == 'RUNNING' and attempt is not None and value.attempt_id != attempt['attempt_id']:"}[guard]
        assert line in source
        namespace = {}; exec(compile(source.replace(line, 'if False:'), 'worker-monitoring-falsifier', 'exec'), status.__dict__, namespace)
        monkeypatch.setattr(status, 'decode_probe', namespace['decode_probe'])
    elif guard == 'incarnation':
        source = textwrap.dedent(inspect.getsource(status.publish))
        namespace = {}; exec(compile(source.replace('prior.incarnation == incarnation', 'True'), 'worker-incarnation-falsifier', 'exec'), status.__dict__, namespace)
        monkeypatch.setattr(status, 'publish', namespace['publish'])
        with pytest.raises(AssertionError): test_missing_process_during_ack_handoff_cannot_renew_or_be_adopted(state, monkeypatch)
        return
    else: monkeypatch.setattr(status, 'MAX_AGE_SECONDS', 1000)
    with pytest.raises(AssertionError):
        test_broken_worker_proof_cannot_establish_operational_green(state, monkeypatch,
            'expired' if guard == 'expiry' else guard)
