from dataclasses import replace
import pytest
from research.data_available.snapshot import from_window
from research.data_available.test_policy import bars,day,meta,filled_feed
from research.data_available.policy import snapshot_bars


def test_repaired_snapshot_readmits_without_replaying_book():
    axis=[day(i) for i in range(300)]
    complete=[bars(i)[0] for i in range(300)]
    missing=[b for b in complete if b.session!=day(280)]
    invalid,_=from_window(axis,missing,meta())
    repaired,_=from_window(axis,complete,meta())
    assert not invalid[0].eligible
    assert repaired[0].eligible


def test_latest_snapshot_revision_changes_future_feature_only():
    axis=[day(i) for i in range(300)]
    original=[bars(i)[0] for i in range(300)]
    revised=[replace(b,signal_close=b.signal_close*1.1) if b.session==day(260) else b for b in original]
    a,_=from_window(axis,original,meta())
    b,_=from_window(axis,revised,meta())
    assert a[0].certified_signals!=b[0].certified_signals


def test_streamed_window_has_same_features_as_fresh_snapshot():
    feed,norm=filled_feed(400)
    streamed=snapshot_bars(feed,norm.security_bars)
    rebuilt,_=from_window([day(i) for i in range(100,400)],
                         [bars(i)[0] for i in range(100,400)],meta())
    assert streamed==rebuilt


@pytest.mark.parametrize('split_at',[50,350])
def test_fresh_window_matches_stream_after_old_or_recent_split(split_at):
    from stock_strategy_shared.wealth_core.feed import Feed
    from stock_strategy_shared.wealth_core.median5 import fresh
    feed=Feed(meta()); feed.median5_state=fresh()
    source=[]
    for i in range(400):
        row=bars(i)[0]
        if i>=split_at:
            row=replace(row,raw_close=row.raw_close/2,raw_open=row.raw_open/2,
                        volume=row.volume*2,split_ratio=2. if i==split_at else 1.)
        source.append(row)
        norm=feed.advance(day(i),[row])
    streamed=snapshot_bars(feed,norm.security_bars)
    rebuilt,_=from_window([day(i) for i in range(100,400)],source[100:],meta())
    assert rebuilt==streamed


@pytest.mark.parametrize('fault',['future','duplicate','short','unordered'])
def test_rejects_invalid_snapshot_before_calculation(fault):
    axis=[day(i) for i in range(300)]
    source=[bars(i)[0] for i in range(300)]
    if fault=='future': source.append(bars(300)[0])
    if fault=='duplicate': source.append(source[-1])
    if fault=='short': axis=axis[1:]
    if fault=='unordered': axis=axis[::-1]
    with pytest.raises(ValueError):
        from_window(axis,source,meta())
