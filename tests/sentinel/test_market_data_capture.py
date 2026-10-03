"""Offline provider pagination, resumability and price-domain witnesses."""
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from tools.provider_capture import Capture, CaptureError, DATA, NASDAQ, acquire, encoded
from tools.provider_preprocess import sharadar_row


def test_split_adjusted_sharadar_volume_is_converted_to_raw():
    row = dict(ticker='ABC', date='2026-09-14', open='10', close='12', closeunadj='24', volume='1000')
    assert sharadar_row(row) == ('ABC','2026-09-14','20','24','12','500','1000')


def test_paginated_capture_resumes_without_network_or_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('ALPACA_API_KEY','secret-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY','secret-value')
    monkeypatch.setattr('tools.provider_capture.time.sleep',lambda _:None)
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        token = kwargs['params'].get('page_token')
        data = {'bars':{'ABC':[{'c':12}]}, 'next_page_token':'next' if not token else None}
        return nullcontext(SimpleNamespace(status_code=200, iter_content=lambda _:iter([encoded(data)])))
    capture = Capture(tmp_path,transport=SimpleNamespace(get=get))
    paths = capture.pages('alpaca',DATA+'/v2/stocks/bars',{'symbols':'ABC'},kind='bars')
    assert len(paths)==2 and calls==[{'symbols':'ABC'},{'symbols':'ABC','page_token':'next'}]
    monkeypatch.delenv('ALPACA_API_KEY')
    monkeypatch.delenv('ALPACA_SECRET_KEY')
    capture.transport.get=lambda *a, **k: pytest.fail('download repeated')
    assert capture.pages('alpaca',DATA+'/v2/stocks/bars',{'symbols':'ABC'},kind='bars')==paths
    assert all('secret' not in (tmp_path/path).read_text() for path in paths)
    retained=json.loads((tmp_path/paths[0]).read_bytes())
    retained['response']['bars']={}
    (tmp_path/paths[0]).write_bytes(encoded(retained))
    with pytest.raises(CaptureError,match='integrity'):
        capture.pages('alpaca',DATA+'/v2/stocks/bars',{'symbols':'ABC'},kind='bars')


def test_repeated_cursor_refuses_instead_of_looping(tmp_path,monkeypatch):
    capture=Capture(tmp_path)
    monkeypatch.setattr(capture,'page',lambda *a:({'datatable':{'data':[]},'meta':{'next_cursor_id':'same'}},'page'))
    with pytest.raises(CaptureError,match='pagination repeated'):
        capture.pages('sharadar',NASDAQ+'SEP.json',{},kind='SEP')


def test_provider_retry_is_bounded_and_errors_exclude_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('SHARADAR_API_KEY','secret-key')
    monkeypatch.setattr('tools.provider_capture.time.sleep',lambda _:None)
    calls=[]
    def get(url, **kwargs):
        calls.append(kwargs)
        return nullcontext(SimpleNamespace(status_code=503))
    capture=Capture(tmp_path,transport=SimpleNamespace(get=get))
    with pytest.raises(CaptureError,match='retry budget exhausted'):
        capture.page('sharadar',NASDAQ+'SEP.json',{})
    assert len(calls)==5
    assert not list(tmp_path.rglob('*.json'))
    capture.transport.get=lambda *a, **k:nullcontext(SimpleNamespace(status_code=401))
    with pytest.raises(CaptureError) as caught:
        capture.page('sharadar',NASDAQ+'SEP.json',{})
    assert str(caught.value)=='sharadar HTTP 401; response body withheld'


def test_incomplete_capture_cannot_be_preprocessed(tmp_path):
    from tools.provider_preprocess import preprocess
    (tmp_path/'manifest.json').write_text('{"status":"INCOMPLETE"}')
    with pytest.raises(CaptureError,match='incomplete'):
        preprocess(tmp_path)


def test_sharadar_only_names_remain_in_coverage_but_never_reach_alpaca_bars(tmp_path, monkeypatch):
    from tools import provider_capture
    requested = []
    monkeypatch.setattr(Capture, 'page', lambda *args: (
        [dict(symbol='ABC'), dict(symbol='SPY')], 'assets.json'))
    monkeypatch.setattr(provider_capture, 'datatable', lambda *args: iter([
        dict(ticker='ABC', isdelisted='N'),
        dict(ticker='ABR-PD', isdelisted='N')]))

    def pages(self, provider, url, params, *, kind):
        if url == DATA+'/v2/stocks/bars':
            names = params['symbols'].split(',')
            requested.append(names)
            if 'ABR-PD' in names:
                raise CaptureError('alpaca HTTP 400; response body withheld')
        return []

    monkeypatch.setattr(Capture, 'pages', pages)
    manifest = acquire(tmp_path, end='2026-09-30')
    universe = json.loads((tmp_path/'universe.json').read_text())
    assert manifest['status'] == 'COMPLETE'
    assert universe['symbols'] == ['ABC', 'ABR-PD', 'BIL', 'SPY']
    assert universe['alpaca_query_symbols'] == ['ABC', 'SPY']
    assert requested == [['ABC', 'SPY'], ['ABC', 'SPY']]


def test_offline_preprocessing_keeps_domains_and_zero_coverage(tmp_path, monkeypatch):
    import csv
    import gzip
    import hashlib
    import sqlite3
    from tools.provider_capture import save
    from tools.provider_preprocess import preprocess
    closed = []
    original_connect = sqlite3.connect
    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: original_connect(*a, **k, factory=TrackedConnection))
    def page(name, value):
        save(tmp_path/name, dict(response=value,sha256=hashlib.sha256(encoded(value)).hexdigest()))
        return [name]
    columns=['ticker','date','open','close','closeunadj','volume']
    sep=page('sep.json',dict(datatable=dict(columns=[{'name':c} for c in columns],
        data=[['ABC','2026-09-14','10','12','24','1000']])))
    sfp=page('sfp.json',dict(datatable=dict(columns=[{'name':c} for c in columns],data=[])))
    raw=page('raw.json',dict(bars={'ABC':[dict(t='2026-09-14T04:00:00Z',o=20,c=24,v=500)]}))
    split=page('split.json',dict(bars={'ABC':[dict(t='2026-09-14T04:00:00Z',o=10,c=12,v=1000)]}))
    save(tmp_path/'universe.json',dict(symbols=['ABC','MISSING']))
    save(tmp_path/'manifest.json',dict(status='COMPLETE', request=dict(sessions=['2026-09-14']),
        files=dict(sharadar_sep=sep,sharadar_sfp=sfp,alpaca_raw=raw,alpaca_split=split)))
    preprocess(tmp_path)
    assert closed == [True]  # Windows cannot unlink an open SQLite database.
    assert not (tmp_path/'preprocessing.partial.sqlite').exists()
    with gzip.open(tmp_path/'alpaca.csv.gz','rt') as file:
        alpaca=list(csv.DictReader(file))
    with gzip.open(tmp_path/'sharadar.csv.gz','rt') as file:
        assert list(csv.DictReader(file))==alpaca
    assert alpaca[0]['raw_volume']=='500' and alpaca[0]['signal_close']=='12'
    with (tmp_path/'coverage.csv').open() as file:
        absent=[r for r in csv.DictReader(file) if r['ticker']=='MISSING']
    assert len(absent)==2 and all(r['sessions']=='0' for r in absent)
    assert json.loads((tmp_path/'preprocessing.json').read_text())['production_authority'] is False
