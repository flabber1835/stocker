"""Compact current-input assessment: independent counts and production callers."""
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from sentinel.core import rolling_inputs as adapter
from sentinel.feed import rolling_go_inputs as inputs, rolling_store, store, publication
from sentinel import rolling_runtime as runtime
from tests.sentinel.test_rolling_inputs import candidate, action
from tests.sentinel.test_rolling_runtime import advance, OBS
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

LATEST_CLOSED_SESSION = inputs.calendar.latest_closed_session
__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'published', 'ready']

def compact(conn, key):
    return adapter.readiness_inputs(conn, candidate_id=key[0], snapshot_id=key[1])


def test_compact_coverage_matches_independent_sql_counts(conn):
    def change(bars, window):
        return [bar.model_copy(update=(
            {'open_unadjusted': None} if bar.security_id == '1' and bar.session < window.end
            else {'volume': 0} if bar.security_id == '2' and bar.session == window.end else {}))
            for bar in bars]
    key = candidate(conn, bar_change=change,
                    reference_change=lambda value: value['tickers'][0].update(relatedtickers='S01 S02'))
    result = compact(conn, key)
    rows = conn.execute('SELECT session,count(*),count(*) FILTER (WHERE close_signal>0),'
        'count(*) FILTER (WHERE close_unadjusted>0),count(*) FILTER (WHERE open_unadjusted>0),'
        'count(*) FILTER (WHERE volume>0) FROM sentinel_snapshot_bars WHERE candidate_id=%s'
        ' AND session>=%s GROUP BY session ORDER BY session',
        (key[0], result.warmup_sessions[0])).fetchall()
    assert len(rows) == 253 and sum(row[1] for row in rows[:-1]) == 6300
    assert result.counts == {str(row[0]): row[1] for row in rows}
    for index, name in enumerate(('signal_close', 'raw_close', 'raw_open', 'volume'), 2):
        assert result.frontier_positive[name] == rows[-1][index]
        assert result.warmup_positive[name] == sum(row[index] for row in rows[:-1])
    assert result.frontier_positive['volume'] == 24
    assert result.warmup_positive['raw_open'] == 6048
    assert result.related_issuers
    assert len(result.benchmarks) == 254
    assert not hasattr(result, 'bars') and not hasattr(result, 'warmup')


def test_status_does_not_materialize_warmup_and_keeps_economic_state(conn, published, monkeypatch):
    before = advance(conn)
    tables = ('sentinel_processed_sessions', 'sentinel_commands', 'sentinel_fills')
    counts = [conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in tables]
    conn.rollback()
    def forbidden(*args, **kwargs):
        pytest.fail('status materialized the entire equity warmup')
    monkeypatch.setattr(inputs, 'cold_start_inputs', forbidden)
    monkeypatch.setattr(adapter, 'cold_start_inputs', forbidden)
    verify = rolling_store.verify_content
    def checked(c, cid):
        assert c.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        assert c.execute('SHOW transaction_isolation').fetchone()[0] == 'repeatable read'
        with store.connect(c.info.dsn) as other:
            assert not other.execute('SELECT pg_try_advisory_xact_lock(%s)',
                                     (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
        return verify(c, cid)
    monkeypatch.setattr(rolling_store, 'verify_content', checked)
    after = runtime.status(conn, observation_id=OBS, starting_cash=100_000)
    assert after.state.state_hash == before.state.state_hash
    assert after.strategy_nav == before.strategy_nav
    assert after.runtime_authority_sha256 == before.runtime_authority_sha256
    assert [conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in tables] == counts


def test_both_assessments_keep_identical_readiness_clauses(conn, published):
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    with inputs.pinned(conn) as pub:
        full_binding, _material, full = inputs.validate(conn, pub)
        compact_binding, small = inputs.validate_status(conn, pub)
    assert full_binding == compact_binding
    assert asdict(full) == asdict(small)
    assert small.ready


def test_compact_status_rejects_late_hash_corruption_despite_unchanged_counts(conn):
    key = candidate(conn)
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1'
                 ' WHERE candidate_id=%s AND session=%s AND security_id=%s',
                 (key[0], '2026-09-14', '25'))
    conn.commit()
    with pytest.raises(rolling_store.SnapshotStorageRefused, match='manifest'):
        compact(conn, key)


def test_compact_reader_checks_dated_identity_after_valid_hashes(conn):
    key = candidate(conn, bar_change=lambda bars, _window: [
        bar.model_copy(update={'ticker':'S02'}) if bar.security_id=='1' else bar for bar in bars])
    with pytest.raises(adapter.RollingInputsRefused, match='REFERENCE_MISMATCH'):
        compact(conn, key)


def test_compact_reader_keeps_terminal_reference_refusal(conn):
    key = candidate(conn, actions=[action(ticker='UNMAPPED')])
    with pytest.raises(adapter.RollingInputsRefused, match='UNRESOLVED_SNAPSHOT_TERMINALS'):
        compact(conn, key)


def test_compact_status_refuses_stale_source_final_frontier(conn, published, monkeypatch):
    # The shared provider fixture freezes calendar.latest_closed_session.
    # Restore the real calendar here to exercise the supplied future instant.
    monkeypatch.setattr(inputs.calendar, 'latest_closed_session', LATEST_CLOSED_SESSION)
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    with inputs.pinned(conn) as pub:
        with pytest.raises(inputs.RollingGoRefused, match='source-final'):
            inputs.validate_status(conn, pub, now=datetime(2026, 9, 17, 4, tzinfo=timezone.utc))
