"""Audit-only witness for an authoritative current-session ticker change."""
from dataclasses import asdict
import json
import pytest
from sentinel.core import rolling_continuity as continuity
from sentinel.core.rolling_inputs import SnapshotReferences
from sentinel.core.rolling_reader import RollingPriceReader
from sentinel import rolling_checkpoint as origin, rolling_daily_checkpoint as cp
from sentinel.feed import operational_snapshot as op
from tests.sentinel.test_rolling_daily import first, ready, conn, pg, source, operational_source, refresh, advance, resume


def test_dated_identity_preserving_rename_blocks_daily_book(conn, first, operational_source, monkeypatch):
    original=op.prepare
    data=operational_source
    def publish_rename(*args,**kwargs):
        today=max(r['date'] for r in data['SEP'])
        for row in data['SEP']:
            if row['ticker']=='BBB' and row['date']==today:
                row['ticker']='NEW'
        for row in data['TICKERS']:
            if row['ticker']=='BBB':row['ticker']='NEW'
        for kind,contra in [('tickerchangefrom','BBB'),('tickerchangeto','NEW')]:
            data['ACTIONS'].append(dict(ticker='NEW',date=today,action=kind,
                name='Same economic issuer',value=None,contraticker=contra,contraname=None))
        return original(*args,**kwargs)
    monkeypatch.setattr(op,'prepare',publish_rename)
    published=refresh(conn,data,monkeypatch)
    assert published['data_version']==2
    with op.pinned(conn) as (pub,binding):
        before=origin.read(conn).snapshot
        old=SnapshotReferences(conn,candidate_id=before['candidate_id'],snapshot_id=before['snapshot_id'])
        new=SnapshotReferences(conn,candidate_id=binding['candidate_id'],snapshot_id=binding['snapshot_id'])
        previous,today=first.session,pub.window_end
        assert old.resolver.resolve('BBB',previous)=='2'
        assert new.resolver.resolve('BBB',previous)=='2'
        assert new.resolver.resolve('NEW',today)=='2'
        a,b=map(lambda x:asdict(x.current_metadata()[0]['2']),(old,new))
        assert a.pop('ticker')=='BBB' and b.pop('ticker')=='NEW'
        assert a==b
        left=RollingPriceReader(conn,candidate_id=before['candidate_id'],snapshot_id=before['snapshot_id'])
        right=RollingPriceReader(conn,candidate_id=binding['candidate_id'],snapshot_id=binding['snapshot_id'])
        lo=max(str(left.manifest.window.start),str(right.manifest.window.start))
        assert list(left.bars(start=lo,end=previous))==list(right.bars(start=lo,end=previous))
        # Direct overlap/reference identity checks accept the exact historical tape.
        continuity._overlap(conn,left,right,new,previous)
    with pytest.raises(continuity.RollingContinuityRefused,match='HISTORICAL_REFERENCE_CHANGED: 2') as err:
        advance(conn)
    assert cp.read(conn) is None
    assert resume(conn).state.state_hash==first.state.state_hash
    print('AUDIT_WITNESS',json.dumps(dict(permanent_identity='2',before_symbol='BBB',
        after_symbol='NEW',historical_bars_equal=True,publication=published['data_version'],
        result=str(err.value))))
