"""Production report-only consumers must not retain the strategy warmup."""
from datetime import datetime, timezone

import pytest

from sentinel import schema
from sentinel.core import rolling_inputs as adapter
from sentinel.execution import feed_inputs
from sentinel.feed import readers, rolling_go_inputs as inputs, rolling_store
from tests.sentinel.test_rolling_runtime import advance
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source

__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'published', 'ready']
REAL_CLOSED_SESSION = inputs.calendar.latest_closed_session
NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)


def forbid_materialization(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('report-only caller retained the complete strategy warmup')
    monkeypatch.setattr(inputs, 'cold_start_inputs', forbidden)
    monkeypatch.setattr(adapter, 'cold_start_inputs', forbidden)


def report(conn, consumer, instant=NOW):
    if consumer == 'assessment':
        return readers.readiness(conn, today=instant.isoformat())
    if consumer == 'readiness':
        return inputs.readiness(conn, now=instant)
    with feed_inputs.pinned(conn, commit=False):
        return feed_inputs.readiness(conn, today=instant.isoformat())


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution', 'prepare', 'runtime_retry'])
def test_report_only_entrypoints_never_materialize(conn, published, monkeypatch, consumer):
    before = advance(conn) if consumer == 'runtime_retry' else None
    conn.rollback()
    forbid_materialization(monkeypatch)
    if consumer == 'runtime_retry':
        after = advance(conn)
        assert after.state.state_hash == before.state.state_hash
        assert after.strategy_nav == before.strategy_nav
        assert after.runtime_authority_sha256 == before.runtime_authority_sha256
        assert not after.appended
        assert conn.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 0
    elif consumer == 'prepare':
        result = inputs.prepare(conn, target_session='2026-09-14')
        assert result['status'] == 'ALREADY_CURRENT'
        assert result['snapshot_id'] == published['snapshot_id']
    else:
        inputs.require_schemas(conn)
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        assert report(conn, consumer).ready
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'


def test_first_acquisition_verification_never_materializes(conn, issuer_source, monkeypatch):
    schema.ensure_schema(conn)
    forbid_materialization(monkeypatch)
    result = inputs.prepare(conn, target_session='2026-09-14')
    assert result['status'] == 'PUBLISHED'
    assert conn.execute('SELECT COUNT(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0] == 0


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution'])
def test_report_consumers_preserve_stale_frontier_semantics(conn, published, monkeypatch, consumer):
    monkeypatch.setattr(inputs.calendar, 'latest_closed_session', REAL_CLOSED_SESSION)
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    later = datetime(2026, 9, 17, 4, tzinfo=timezone.utc)
    if consumer == 'assessment':
        result = report(conn, consumer, later)
        assert not result.ready
        assert any(check.name == 'rolling source-final frontier' for check in result.failures)
    else:
        with pytest.raises(inputs.RollingGoRefused, match='source-final'):
            report(conn, consumer, later)


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution'])
def test_report_consumers_refuse_late_corruption(conn, published, consumer):
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1'
                 ' WHERE candidate_id=%s AND session=%s AND security_id=%s',
                 (published['candidate_id'], '2026-09-14', '25'))
    conn.commit()
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    with pytest.raises(rolling_store.SnapshotStorageRefused, match='manifest'):
        report(conn, consumer)
