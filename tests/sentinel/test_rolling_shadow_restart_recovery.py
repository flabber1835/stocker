"""Actual PostgreSQL proof of an unchanged canonical book after interruption."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from sentinel import shadow_restart_recovery as recovery, rolling_authority as authority
from sentinel import rolling_initialization as initial, rolling_checkpoint as origin, shadow_runtime
from sentinel.feed.rolling_contract import canonical_json
from tests.sentinel.test_rolling_runtime import advance, issuer_source, published, ready, operational_source, conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import NOW, OBS


class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return NOW if tz is None else NOW.astimezone(tz)


@pytest.fixture
def interrupted(conn, published, tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'datetime', Clock)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    monkeypatch.setattr(recovery.shadow_worker_liveness, 'ACTIVE_FILE', tmp_path/'active.json')
    marker = recovery.make_pending('a'*32, os.getpid())
    marker['boot_id'] = '00000000-0000-0000-0000-000000000000'
    payload = {k: v for k, v in marker.items() if k != 'hmac_sha256'}
    marker['hmac_sha256'] = recovery.receipt_authentication.sign({'purpose': recovery.SCHEMA, 'pending': payload})
    raw = json.dumps(marker).encode()
    (tmp_path/recovery.shadow_service_status.PENDING_NAME).write_bytes(raw)
    return tmp_path, raw, SimpleNamespace(operational_source_only=True,
        database_url=conn.info.dsn, observation_id=OBS, starting_cash=100_000)


def test_real_restart_proof_and_archive_do_not_replay_or_change_book(conn, interrupted, monkeypatch):
    state, raw, config = interrupted
    result = advance(conn)
    before = origin.read(conn).model_dump(by_alias=True)
    counts = [conn.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
              ('sentinel_processed_sessions', 'sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills')]
    conn.rollback()
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    monkeypatch.setattr(AlpacaExecutionBroker, '__init__', lambda *a, **k: pytest.fail('broker constructed'))
    monkeypatch.setattr(initial, 'initialize', lambda *a, **k: pytest.fail('book reconstructed'))
    with recovery.owner(state):
        verified = recovery.verify(config)
        accepted = recovery.archive(state, verified, hashlib.sha256(raw).hexdigest())
    assert verified['state_sha256'] == result.state.state_hash
    assert verified['runtime_authority_sha256'] == result.runtime_authority_sha256
    assert verified['authority_effect'] == 'NONE' and accepted['worker_outcome'] == 'UNKNOWN'
    assert origin.read(conn).model_dump(by_alias=True) == before
    assert counts == [conn.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
                      ('sentinel_processed_sessions', 'sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills')]
    assert (state/'shadow-restart-incidents'/('a'*32)/recovery.shadow_service_status.PENDING_NAME).read_bytes() == raw


@pytest.mark.parametrize('defect', ['candidate', 'signature', 'foreign-runtime'])
def test_real_unverified_restart_leaves_original_guard_and_book(conn, interrupted, monkeypatch, defect):
    state, raw, config = interrupted
    if defect == 'candidate': initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    else:
        advance(conn)
        if defect == 'signature':
            value = authority.latest(conn, OBS)[0].model_dump(by_alias=True)
            changed = conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
                         (canonical_json({'authority': value, 'hmac_sha256': '0'*64}), authority.name(OBS, value['session'])))
            assert changed.rowcount == 1
            conn.commit()
        else:
            original = shadow_runtime._validated_runtime_identity
            def foreign(**kwargs):
                value = deepcopy(original(**kwargs)); value['validated_data_publication_sha256'] = '0'*64
                return value
            monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', foreign)
    before = conn.execute('SELECT count(*) FROM sentinel_processed_sessions').fetchone()[0]
    conn.rollback()
    with recovery.owner(state):
        report = recovery.probe(config)
    assert report['status'] == 'REFUSED'
    assert (state/recovery.shadow_service_status.PENDING_NAME).read_bytes() == raw
    assert not (state/'shadow-restart-incidents').exists()
    assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions').fetchone()[0] == before
