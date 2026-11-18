"""A close publication can precede its SHADOW health renewal within one live attempt."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import subprocess
import sys
import time

import psycopg
import pytest

from sentinel import shadow_health_projection as projection, shadow_service_status as status
from sentinel import shadow_supervisor as supervisor, shadow_worker_liveness as live, supervisor_io
from sentinel.shadow_service_config import ShadowServiceConfig
from sentinel.feed import operational_snapshot, publication
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


@pytest.fixture
def handoff(pg, tmp_path, monkeypatch):
    """Private native rows and signed files at the same two-phase boundary as the close."""
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    import uuid

    name = 'health_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    db = make_conninfo(pg.sync_dsn, dbname=name)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', db)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'synthetic-health-signing-value-' * 2)
    monkeypatch.setattr(supervisor, 'LATCH_FILE', tmp_path/status.CRITICAL_NAME)
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', tmp_path/'heartbeat')
    monkeypatch.setattr(live, 'ACTIVE_FILE', tmp_path/'worker')
    supervisor.HEARTBEAT_FILE.touch()
    config = ShadowServiceConfig(db, 'primary', Decimal(50000), 'private', 300, True)
    now = datetime.now(timezone.utc)
    close = now-timedelta(minutes=10)
    begin = close-timedelta(days=1)
    end = close+timedelta(days=1)
    target = tmp_path/'shadow-health-projection.json'
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE sentinel_processed_sessions(cursor_name text PRIMARY KEY, session date, state jsonb);
            CREATE TABLE sentinel_corpus_publications(version bigint PRIMARY KEY, previous_version bigint, window_end date,
                published_at timestamptz, evidence jsonb, window_start date, run_id uuid);
            CREATE TABLE sentinel_publication_validation_receipts(publication_version bigint PRIMARY KEY,
                receipt_sha256 text, receipt_hmac_sha256 text, previous_receipt_sha256 text,
                previous_version bigint,run_id uuid,origin_run_status text,published_at timestamptz,
                window_start date,window_end date,evidence jsonb);
            CREATE TABLE sentinel_price_candidates(candidate_id int PRIMARY KEY, snapshot_id text,
                reference_sha256 text,window_start date,window_end date);
            CREATE TABLE sentinel_operational_snapshots(publication_version bigint PRIMARY KEY, job_id int, candidate_id int, validation_sha256 text);
            CREATE TABLE sentinel_snapshot_jobs(job_id int PRIMARY KEY, candidate_id int, publication_version bigint, state text,
                created_at timestamptz, updated_at timestamptz, deadline timestamptz);
            CREATE TABLE sentinel_operational_snapshot_validations(candidate_id int PRIMARY KEY, validation_sha256 text)
            """)
        conn.execute("INSERT INTO sentinel_processed_sessions VALUES ('rolling-cold-start:v1',%s,'{}')", (begin.date(),))
        prior_receipt = 'd'*64
        conn.execute("INSERT INTO sentinel_corpus_publications VALUES(23,22,%s,%s,%s::jsonb,%s,NULL)",
                     (begin.date(), begin, json.dumps({publication.RECEIPT_EVIDENCE_KEY: {'receipt_sha256': prior_receipt}}),
                      begin.date()))
        digest, origin = projection._inventory(conn)
        assert origin
        signed = projection.Projection(schema_id=projection.SCHEMA, config_sha256=projection._config(config),
            inventory_sha256=digest, session=str(begin.date()), record_sha256='a'*64, runtime_authority_sha256='b'*64,
            waiting_session=str(close.date()), calendar_identity='XNYS/exchange_calendars private',
            valid_from=begin.isoformat(), current_until=close.isoformat(), valid_until=end.isoformat()).model_dump()
        projection._write({'projection': signed, 'hmac_sha256': projection._signature(signed)}, target)
        evidence = {'rolling_snapshot': {'schema': operational_snapshot.SCHEMA, 'candidate_id': '3',
            'job_id': '2', 'validation_sha256': 'c'*64, 'snapshot_id': '1'*64, 'reference_sha256': '2'*64}}
        attempt = supervisor._arm_worker()
        published_at = datetime.now(timezone.utc)
        signed_evidence = publication._add_validation_receipt(conn, version=24, previous_version=23,
            run_id=None, published_at=published_at, window_start=begin.date(), window_end=close.date(),
            evidence=evidence, previous_receipt_sha256=prior_receipt)
        receipt = signed_evidence[publication.RECEIPT_EVIDENCE_KEY]
        conn.execute("INSERT INTO sentinel_corpus_publications VALUES (24,23,%s,%s,%s::jsonb,%s,NULL)",
                     (close.date(), published_at, json.dumps(signed_evidence), begin.date()))
        conn.execute("INSERT INTO sentinel_publication_validation_receipts VALUES (24,%s,%s,%s,23,NULL,NULL,%s,%s,%s,%s::jsonb)",
                     (receipt['receipt_sha256'], receipt['receipt_hmac_sha256'], prior_receipt, published_at,
                      begin.date(), close.date(), json.dumps(evidence)))
        conn.execute("INSERT INTO sentinel_price_candidates VALUES (3,%s,%s,%s,%s)",
                     ('1'*64, '2'*64, begin.date(), close.date()))
        conn.execute("INSERT INTO sentinel_operational_snapshots VALUES (24,2,3,%s)", ('c'*64,))
        conn.execute("INSERT INTO sentinel_operational_snapshot_validations VALUES (3,%s)", ('c'*64,))
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES (2,3,24,'PUBLISHED',%s,%s,%s)",
                     (published_at, published_at, end))
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
        try:
            live.record(attempt, os.getpid(), child.pid, time.monotonic()+60)
            status.publish(supervisor.LATCH_FILE, 'f'*32)
            yield config, conn, target
        finally:
            child.terminate()
            child.wait(timeout=5)


def test_only_container_observes_owned_close_while_financial_renewal_remains_due(handoff):
    config, conn, target = handoff
    with pytest.raises(projection.ProjectionRenewalRequired):
        projection.health(config, target=target, fallback=pytest.fail)
    assert supervisor._health(30, config=config) == 0
    assert projection.health(config, target=target, fallback=pytest.fail,
                             observe_close_wait=True)['service_health'] == 'CLOSE_PUBLICATION_PENDING'
    conn.execute("UPDATE sentinel_processed_sessions SET state=state")
    assert supervisor._health(30, config=config) == 1


@pytest.mark.parametrize('damage', ['config', 'job', 'deadline', 'prior_day', 'extra', 'binding',
                                     'recovery', 'signature', 'bad_hmac', 'receipt_parent', 'wrong_schema', 'wrong_candidate',
                                     'latch', 'bad_owner', 'other_supervisor', 'missing_pending', 'successor', 'handoff'])
def test_other_mutations_and_unowned_waits_stay_unhealthy(handoff, damage, monkeypatch):
    config, conn, target = handoff
    if damage == 'config':
        config = replace(config, starting_cash=Decimal(99000))
    elif damage == 'job':
        conn.execute("UPDATE sentinel_snapshot_jobs SET state='READY'")
    elif damage == 'deadline':
        conn.execute("UPDATE sentinel_snapshot_jobs SET deadline=now()-interval '1 second'")
    elif damage == 'prior_day':
        conn.execute("UPDATE sentinel_corpus_publications SET window_end=window_end-1 WHERE version=24")
    elif damage == 'extra':
        conn.execute("INSERT INTO sentinel_corpus_publications SELECT 25,24,window_end,published_at,evidence FROM sentinel_corpus_publications WHERE version=24")
    elif damage == 'binding':
        conn.execute("UPDATE sentinel_operational_snapshot_validations SET validation_sha256='changed'")
    elif damage == 'recovery':
        conn.execute("UPDATE sentinel_corpus_publications SET evidence=evidence || '{\"operational_recovery\":true}'::jsonb WHERE version=24")
    elif damage == 'signature':
        conn.execute("UPDATE sentinel_corpus_publications SET evidence=evidence || '{\"changed\":true}'::jsonb WHERE version=24")
        conn.execute("UPDATE sentinel_publication_validation_receipts SET evidence=evidence || '{\"changed\":true}'::jsonb")
    elif damage == 'bad_hmac':
        conn.execute("UPDATE sentinel_corpus_publications SET evidence=jsonb_set(evidence,%s,to_jsonb(%s::text)) WHERE version=24",
                     ([publication.RECEIPT_EVIDENCE_KEY, 'receipt_hmac_sha256'], '0'*64))
        conn.execute("UPDATE sentinel_publication_validation_receipts SET receipt_hmac_sha256=%s", ('0'*64,))
    elif damage == 'receipt_parent':
        conn.execute("UPDATE sentinel_publication_validation_receipts SET previous_receipt_sha256=%s", ('e'*64,))
    elif damage == 'wrong_candidate':
        conn.execute("UPDATE sentinel_price_candidates SET reference_sha256=%s", ('e'*64,))
    elif damage == 'wrong_schema':
        row = conn.execute("SELECT published_at,window_start,window_end,evidence FROM sentinel_publication_validation_receipts").fetchone()
        published, start, end, evidence = row
        del evidence['rolling_snapshot']['schema']
        signed = publication._add_validation_receipt(conn, version=24, previous_version=23, run_id=None,
            published_at=published, window_start=start, window_end=end, evidence=evidence, previous_receipt_sha256='d'*64)
        receipt = signed[publication.RECEIPT_EVIDENCE_KEY]
        conn.execute("UPDATE sentinel_corpus_publications SET evidence=%s::jsonb WHERE version=24", (json.dumps(signed),))
        conn.execute("UPDATE sentinel_publication_validation_receipts SET evidence=%s::jsonb,receipt_sha256=%s,receipt_hmac_sha256=%s",
                     (json.dumps(evidence), receipt['receipt_sha256'], receipt['receipt_hmac_sha256']))
    elif damage == 'latch':
        supervisor.LATCH_FILE.write_text('failure')
    elif damage == 'bad_owner':
        value = target.with_name(status.NAME)
        envelope = json.loads(value.read_bytes())
        envelope['hmac_sha256'] = '0'*64
        value.write_text(json.dumps(envelope))
    elif damage == 'other_supervisor':
        value = json.loads(supervisor._pending_file().read_bytes())
        del value['hmac_sha256']
        value['supervisor_start_ticks'] += 1
        from sentinel import receipt_authentication
        sig = receipt_authentication.sign({'purpose': value['schema'], 'pending': value})
        supervisor._pending_file().write_text(json.dumps({**value, 'hmac_sha256': sig}))
        assert live.matches(supervisor._pending_file())
    elif damage == 'missing_pending':
        supervisor._pending_file().unlink()
    elif damage == 'successor':
        pid = json.loads(live.ACTIVE_FILE.read_bytes())['worker']['pid']
        supervisor._clear_worker()
        replacement = supervisor._arm_worker()
        live.record(replacement, os.getpid(), pid, time.monotonic()+60)
        status.publish(supervisor.LATCH_FILE, 'e'*32)
    else:
        original = projection.health
        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            assert result['service_health'] == 'CLOSE_PUBLICATION_PENDING'
            live.clear()
            return result
        monkeypatch.setattr(projection, 'health', observe)
    assert supervisor._health(30, config=config) == 1


def test_probe_failure_is_retained_without_private_exception_values(monkeypatch):
    events = []
    monkeypatch.setenv('SENTINEL_FEED_SERVICE_MODE','SHADOW')
    monkeypatch.setattr(supervisor_io, 'report', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(supervisor_io, '_pipe_report',
                        lambda text, *, container_log: events.append((container_log,json.loads(text))) or False)
    assert supervisor._health_failure('FRONTIER', 'private-canary', ValueError('private-canary')) == 1
    [(container, event)] = events
    assert container and event['context'] == {'state':'FRONTIER'}
    assert event['error']['exception_type'] == 'ValueError' and 'private-canary' not in json.dumps(event)


def test_rotated_docker_probe_still_writes_to_main_log_and_refuses_full_or_regular_sink(tmp_path, monkeypatch):
    reader, writer = os.pipe()
    try:
        monkeypatch.setattr(supervisor_io, '_CONTAINER_STDERR', f'/proc/self/fd/{writer}')
        assert supervisor_io._pipe_report('FRONTIER', container_log=True)
        assert os.read(reader, 128) == b'FRONTIER\n'
        os.set_blocking(writer, False)
        with pytest.raises(BlockingIOError):
            while True:
                os.write(writer, b'x'*4096)
        os.set_blocking(writer, True)
        assert supervisor_io._pipe_report('FRONTIER', container_log=True) is False
        assert os.get_blocking(writer)
        target = tmp_path/'ordinary'
        target.write_bytes(b'original')
        monkeypatch.setattr(supervisor_io, '_CONTAINER_STDERR', str(target))
        assert supervisor_io._pipe_report('FRONTIER', container_log=True) is None
        assert target.read_bytes() == b'original'
    finally:
        os.close(writer)
        os.close(reader)
