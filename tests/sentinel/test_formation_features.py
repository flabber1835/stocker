"""Differential falsifiers against the unchanged canonical window loader."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentinel.core import formation_features, window_features
from sentinel.feed import rolling_store, calendar
from sentinel.feed.rolling_contract import CanonicalBar, CurrentFormationWindow
from stock_strategy_shared.wealth_core.feed import SecurityMeta


@pytest.fixture
def fixture(monkeypatch):
    window = CurrentFormationWindow.through('2026-10-01')
    axis = list(map(str, window.sessions))
    rows = [CanonicalBar(security_id=sid, ticker=sid, session=day,
        close_signal=100+index*.003, close_unadjusted=100+index*.003,
        open_unadjusted=None if index % 7 == 0 else 100,
        volume=None if sid == 'GAP' and index % 11 == 0 else 1_000_000,
        split_ratio=1, dividend_per_share=.1 if index % 31 == 0 else 0)
        for index, day in enumerate(axis) for sid in ('AAA','BBB','GAP')
        if not (sid == 'GAP' and index % 17 == 0)]
    reads = []
    @contextmanager
    def cursor(conn, query, params):
        _, lo, hi = params
        values = [row for row in rows if lo <= str(row.session) <= hi]
        values.sort(key=(lambda row: (str(row.session), row.security_id))
                    if 'ORDER BY session,' in query else
                    (lambda row: (row.security_id, str(row.session))))
        reads.append((lo, hi, len(values)))
        yield iter(tuple(getattr(row, field) for field in rolling_store.BAR_COLUMNS) for row in values)
    monkeypatch.setattr(rolling_store.store if hasattr(rolling_store, 'store') else formation_features.store,
                        'streaming_cursor', cursor)
    monkeypatch.setattr(window_features.store, 'streaming_cursor', cursor)
    meta = {sid:SecurityMeta(sid, sid, category='Domestic Common Stock Primary Class',
                            first_session=axis[0]) for sid in ('AAA','BBB','GAP')}
    refs = SimpleNamespace(candidate_id='candidate', manifest=SimpleNamespace(
        window=window, snapshot_id='b'*64), resolver=SimpleNamespace(resolve=lambda ticker, day:ticker),
        current_metadata=lambda **kw:(meta, {}))
    pub = SimpleNamespace(version=1, window_end=axis[-1])
    prior = SimpleNamespace(state_hash='a'*64, wealth_core={}, pending=[], median5={'selected':['AAA']})
    return axis, rows, reads, refs, pub, prior


def test_every_formation_window_is_exact_and_each_row_is_read_once(fixture):
    axis, rows, reads, refs, pub, prior = fixture
    cached = formation_features.FormationFeatures(None, refs=refs, publication=pub)
    for day in axis[299:]:
        expected = window_features.load(None, prior=prior, refs=refs, publication=pub, session=day)
        actual = cached.load(prior=prior, session=day)
        assert actual.model_dump() == expected.model_dump()
        assert actual.sha256 == expected.sha256
        assert all(len(ring.indices) <= 300 for ring in cached.rings.values())
    assert cached.rows_read == len(rows)


def test_future_and_expired_rows_do_not_enter_features_and_backward_read_rebuilds(fixture):
    axis, rows, reads, refs, pub, prior = fixture
    cached = formation_features.FormationFeatures(None, refs=refs, publication=pub)
    first = cached.load(prior=prior, session=axis[299])
    for index, row in enumerate(rows):
        if str(row.session) > axis[300]:
            rows[index] = row.model_copy(update={'close_signal':999999.})
    assert cached.load(prior=prior, session=axis[299]).sha256 == first.sha256
    cached.load(prior=prior, session=axis[300])
    assert reads[-1][:2] == (axis[300],axis[300])
    assert cached.load(prior=prior, session=axis[299]).sha256 == first.sha256
    assert reads[-1][:2] == (axis[0],axis[299])


def test_cache_cannot_cross_snapshot_or_publication(fixture):
    axis, rows, reads, refs, pub, prior = fixture
    cached = formation_features.FormationFeatures(None, refs=refs, publication=pub)
    pub.version = 2
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        cached.load(prior=prior, session=axis[-1])
