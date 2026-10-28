"""Shared history must yield before decoding later dates, without hiding damage."""
import pytest

from sentinel.feed import normalized_layout as layout, rolling_store as storage
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_normalized_layout import candidate


@pytest.mark.parametrize('shared', [False, True])
def test_full_order_domains_and_inclusive_bounds_match_original_view(conn, shared):
    identity, manifest, _ = candidate(conn, shared=shared)
    table = layout.read_table(conn, 'BARS')
    raw = conn.execute(f'SELECT {",".join(storage.BAR_COLUMNS)} FROM {table} '
        'WHERE candidate_id=%s ORDER BY session,security_id COLLATE "C"', (identity,)).fetchall()
    expected = [dict(zip(storage.BAR_COLUMNS, row)) for row in raw]
    assert [b.model_dump() for b in storage.read_bars(conn, identity)] == expected
    lo, hi = manifest.window.sessions[3], manifest.window.sessions[8]
    assert [b.model_dump() for b in storage.read_bars(conn, identity, start=lo, end=hi)] == [
        row for row in expected if lo <= row['session'] <= hi]
    assert storage.verify_content(conn, identity) == manifest


def assert_incremental_first_fetch(conn, monkeypatch):
    identity, manifest, _ = candidate(conn)
    original = storage._stream_rows
    seen = []
    def bounded(*args, **kwargs):
        assert kwargs['start'] == kwargs['end']
        assert kwargs['start'] is not None
        seen.append(kwargs['start'])
        yield from original(*args, **kwargs)
    monkeypatch.setattr(storage, '_stream_rows', bounded)
    stream = storage.read_bars(conn, identity)
    first = next(stream)
    assert first.session == manifest.window.sessions[0]
    assert seen == [manifest.window.sessions[0]]
    assert len([first, *stream]) == manifest.bar_count
    assert seen == list(manifest.window.sessions)


def test_first_row_does_not_decode_the_entire_shared_window(conn, monkeypatch):
    assert_incremental_first_fetch(conn, monkeypatch)


def test_removed_partitioning_falsifier_recreates_blocking_first_fetch(conn, monkeypatch):
    def whole_window(connection, identity, *, table, columns, order, start=None, end=None):
        yield from storage._stream_rows(connection, identity,
            table=layout.read_table(connection, 'BARS' if table.endswith('_bars') else 'BENCHMARKS'),
            columns=columns, order=order, start=start, end=end)
    # Seal the sound fixture first; replace only the reading path under test.
    original_candidate = candidate
    def prepared(*args, **kwargs):
        result = original_candidate(*args, **kwargs)
        monkeypatch.setattr(storage, '_rows', whole_window)
        return result
    monkeypatch.setattr(__import__(__name__, fromlist=['candidate']), 'candidate', prepared)
    with pytest.raises(AssertionError):
        assert_incremental_first_fetch(conn, monkeypatch)


def test_stored_sessions_do_not_hide_rows_outside_the_declared_axis(conn):
    from datetime import timedelta
    identity, manifest, _ = candidate(conn, shared=False)
    extra = manifest.window.sessions[-1]+timedelta(days=1)
    conn.execute('SET LOCAL session_replication_role=replica')
    row = storage.CanonicalBar(security_id='outside', session=extra, ticker='OUT',
        close_signal=12, close_unadjusted=24, open_unadjusted=23, volume=1000,
        split_ratio=1, dividend_per_share=0)
    conn.execute('INSERT INTO sentinel_snapshot_bars(candidate_id,'+','.join(storage.BAR_COLUMNS)+') '
        'VALUES('+','.join(['%s']*(len(storage.BAR_COLUMNS)+1))+')',
        [identity, *[getattr(row, key) for key in storage.BAR_COLUMNS]])
    assert extra in layout.stored_sessions(conn, identity, 'BARS')
    assert list(storage.read_bars(conn, identity))[-1] == row
    with pytest.raises(storage.SnapshotStorageRefused, match='content differs'):
        storage.verify_content(conn, identity)
