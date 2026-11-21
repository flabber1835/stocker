"""Canonical rolling state remains exact across verifier-only material reuse."""
import pytest

from sentinel import backup_runtime_authority, operational_schema, rolling_runtime, rolling_checkpoint
from sentinel.shadow_status_material import StatusMaterialMemo, current_memo
from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs, store
from tests.sentinel.test_rolling_paper_inputs import (
    conn, pg, source, issuer_source, ready, operational_source, published, approve,
)
from tests.sentinel.test_rolling_initialization import OBS, NOW


@pytest.fixture(autouse=True)
def private_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path/'absent-policy')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-canonical-status-fixture-key-'*2)


def test_actual_canonical_status_reuses_material_and_keeps_current_failures(conn, published, monkeypatch):
    approve(conn)
    conn.rollback()
    operational_schema.install_quiescent(conn)
    calls = []
    original = rolling_runtime._status_closure
    def canonical(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(rolling_runtime, '_status_closure', canonical)
    def read(at=NOW):
        with store.connect(conn.info.dsn) as reader:
            return rolling_runtime.classify(reader, observation_id=OBS, starting_cash=100000,
                                            clock=lambda: at)
    independent = read()
    memo = StatusMaterialMemo()
    token = current_memo.set(memo)
    try:
        first, second = read(), read()
        assert len(calls) == 2
        assert first['status'] == second['status'] == independent['status'] == 'VERIFIED'
        assert first['result'].state.to_dict() == second['result'].state.to_dict() == independent['result'].state.to_dict()
        assert first['result'].record_sha256 == independent['result'].record_sha256
        with monkeypatch.context() as next_close:
            target = calendar.next_session(independent['result'].session)
            next_close.setattr(operational_snapshot, 'source_final_session', lambda instant=None: target)
            with pytest.raises(rolling_go_inputs.RollingSourceFrontierPending):
                read()
        assert len(calls) == 2, 'fresh readiness required decoding the unchanged checkpoint again'
        conn.execute("SET LOCAL session_replication_role='replica'")
        conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name=%s",
                     (rolling_checkpoint.CURSOR,))
        conn.commit()
        with pytest.raises((ValueError, RuntimeError)):
            read()
        assert len(calls) == 3
    finally:
        current_memo.reset(token)
