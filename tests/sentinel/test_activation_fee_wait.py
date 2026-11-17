"""The fenced display observation uses real PostgreSQL identity and receipt clocks."""
from datetime import date, datetime, timedelta, timezone
import json

import psycopg
import pytest

from sentinel import activation_fee_wait as fee_wait, receipt_authentication
from tests.support.postgres import _EphemeralPostgres


SESSION = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 4, 3, 14, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 11, 17, 9, 37, 29, tzinfo=timezone.utc)
CERTIFICATE = 'c' * 64


@pytest.fixture(scope='module')
def postgres():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def connection(postgres, monkeypatch):
    monkeypatch.setenv(receipt_authentication.KEY_ENV, 'activation-fee-receipt-test-key-only')
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + '2' * 64)
    monkeypatch.setenv('SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256', '3' * 64)
    monkeypatch.setenv('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', '4' * 64)
    monkeypatch.setenv('SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', '5' * 64)
    monkeypatch.setenv('SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256', '6' * 64)
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_MODE', 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1')
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_BACKUP_POLICY', 'REQUIRED_V1')
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', 'PAFIXTURE')
    with psycopg.connect(postgres.sync_dsn) as conn:
        conn.execute('CREATE TEMP TABLE sentinel_automation_control '
                     '(id int, enabled boolean, kill_switch_engaged boolean, generation bigint)')
        conn.execute('CREATE TEMP TABLE sentinel_execution_authority_state '
                     '(id int, active_certificate_sha256 text)')
        conn.execute('CREATE TEMP TABLE sentinel_account_binding (id int, deployment_id text, '
                     'broker text, broker_account_id text, takeover_epoch bigint, ownership_state text)')
        conn.execute('CREATE TEMP TABLE sentinel_corpus_publications (version bigint, window_end date)')
        conn.execute('INSERT INTO sentinel_automation_control VALUES (1,false,true,9)')
        conn.execute('INSERT INTO sentinel_execution_authority_state VALUES (1,%s)', (CERTIFICATE,))
        conn.execute("INSERT INTO sentinel_account_binding VALUES (1,'fixture','alpaca','PAFIXTURE',4,'SENTINEL_OWNED')")
        conn.execute('INSERT INTO sentinel_corpus_publications VALUES (83,%s)', (SESSION,))
        yield conn


def publish(connection, tmp_path, **overrides):
    options = dict(decision_session=SESSION, deadline=DEADLINE, certificate_sha256=CERTIFICATE,
                   now=NOW, state_dir=tmp_path)
    return fee_wait.publish_owned(connection, **(options | overrides))


def test_fenced_fee_wait_round_trip_and_exact_expiry(connection, tmp_path):
    wait = publish(connection, tmp_path, deadline='2026-11-17T09:37:29Z')
    assert wait == fee_wait.ActivationFeeWait(SESSION, NOW, DEADLINE, NOW + timedelta(seconds=360), CERTIFICATE, 9)
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) == wait
    assert fee_wait.read_owned(connection, now=wait.valid_until, state_dir=tmp_path) is None
    assert fee_wait.read_owned(connection, now=NOW - timedelta(microseconds=1), state_dir=tmp_path) is None
    cutoff = NOW + timedelta(seconds=30)
    assert publish(connection, tmp_path, deadline=cutoff).valid_until == cutoff
    assert fee_wait.read_owned(connection, now=cutoff, state_dir=tmp_path) is None


@pytest.mark.parametrize('change', [
    'UPDATE sentinel_automation_control SET enabled=true',
    'UPDATE sentinel_automation_control SET kill_switch_engaged=false',
    'UPDATE sentinel_automation_control SET generation=generation+1',
    "UPDATE sentinel_execution_authority_state SET active_certificate_sha256=repeat('0',64)",
    'UPDATE sentinel_account_binding SET takeover_epoch=takeover_epoch+1',
    'UPDATE sentinel_corpus_publications SET window_end=window_end',
    'INSERT INTO sentinel_corpus_publications VALUES (84, DATE \'2026-11-16\')',
])
def test_durable_identity_changes_withdraw_receipt(connection, tmp_path, change):
    assert publish(connection, tmp_path) is not None
    connection.execute(change)
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) is None


@pytest.mark.parametrize('key,new_value', [
    ('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow'),
    ('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'paper'),
    ('SENTINEL_LOCAL_PAPER_MODE', ''),
    ('SENTINEL_LOCAL_PAPER_BACKUP_POLICY', ''),
    ('SENTINEL_GIT_COMMIT', '7' * 40),
    ('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + '7' * 64),
    ('SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256', '7' * 64),
    ('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', '7' * 64),
    ('SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', '7' * 64),
    ('ALPACA_BASE_URL', 'https://api.alpaca.markets'),
])
def test_reviewed_runtime_changes_withdraw_receipt(connection, tmp_path, monkeypatch, key, new_value):
    assert publish(connection, tmp_path) is not None
    monkeypatch.setenv(key, new_value)
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) is None


def test_tampered_and_unbounded_receipts_never_display(connection, tmp_path):
    assert publish(connection, tmp_path) is not None
    target = tmp_path / fee_wait.FILENAME
    envelope = json.loads(target.read_bytes())
    envelope['value']['deadline'] = '2026-11-17T09:35:00+00:00'
    target.write_text(json.dumps(envelope, sort_keys=True, separators=(',', ':')), encoding='ascii')
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) is None
    target.write_bytes(b' ' * (fee_wait.MAX_BYTES + 1))
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) is None


def test_invalid_publication_never_creates_or_replaces_marker(connection, tmp_path):
    target = tmp_path / fee_wait.FILENAME
    assert publish(connection, tmp_path, deadline='2026-11-17T14:30:01Z') is None
    assert publish(connection, tmp_path, deadline='2026-11-17T09:37:29') is None
    assert publish(connection, tmp_path, certificate_sha256='7' * 64) is None
    assert not target.exists()
    assert publish(connection, tmp_path) is not None
    before = target.read_bytes()
    assert publish(connection, tmp_path, decision_session='2026-11-13') is None
    assert target.read_bytes() == before


def test_only_current_owner_can_clear_receipt(connection, tmp_path):
    assert publish(connection, tmp_path) is not None
    fee_wait.clear_owned(connection, decision_session=SESSION, certificate_sha256='7' * 64, state_dir=tmp_path)
    assert fee_wait.read_owned(connection, now=NOW, state_dir=tmp_path) is not None
    fee_wait.clear_owned(connection, decision_session=SESSION, certificate_sha256=CERTIFICATE, state_dir=tmp_path)
    assert not (tmp_path / fee_wait.FILENAME).exists()
