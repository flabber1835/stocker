"""Offline provider pagination, resumability and price-domain witnesses."""
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from tools.provider_capture import Capture, CaptureError, DATA, NASDAQ, encoded
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



def test_readonly_feed_diagnostic_selects_only_named_configuration(tmp_path):
    from tools.autonomy_feed_qualification import selected_config, backup_availability
    config = tmp_path / 'operator.env'
    original = 'ALPACA_API_KEY="data-key"\nALPACA_SECRET_KEY=data-secret\nOTHER_SECRET=private\n'
    config.write_text(original)
    selected = selected_config(config, {'ALPACA_API_KEY':'override', 'SENTINEL_PAPER_ACCOUNT_ID':'private-id'})
    assert selected == {'ALPACA_API_KEY':'override', 'ALPACA_SECRET_KEY':'data-secret'}
    assert config.read_text() == original
    missing = backup_availability({'SENTINEL_BACKUP_DIR':str(tmp_path/'missing'),
                                   'SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED':'1'})
    assert missing['status'] == 'NOT_PROVEN' and not missing['configured_target_present']
    present = backup_availability({'SENTINEL_BACKUP_DIR':str(tmp_path),
                                   'SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED':'1'})
    assert present['status'] == 'NOT_PROVEN'


def test_readonly_feed_diagnostic_container_has_no_account_or_database_authority():
    from tools.autonomy_feed_qualification import probe_command, PROBE_CODE
    command = probe_command('sha256:'+'a'*64)
    assert command[:4] == ['docker','run','--rm','-i']
    assert '--read-only' in command and '--cap-drop' in command
    assert '--volume' not in command and '--mount' not in command
    assert not any('DATABASE' in item or 'ACCOUNT_ID' in item or 'BACKUP_' in item for item in command)
    assert 'retained_go' not in PROBE_CODE and '/orders' not in PROBE_CODE
    assert PROBE_CODE.index('SENTINEL_IMAGE_SOURCE_REVISION') < PROBE_CODE.index('from sentinel.feed')
    assert '_bounds(day, day)' in PROBE_CODE
    compile(PROBE_CODE, '<provider-probe>', 'exec')


def test_readonly_feed_diagnostic_redacts_untrusted_provider_output():
    from tools.autonomy_feed_qualification import run_probe, MARKER
    import subprocess
    calls = []
    def runner(command, **kwargs):
        calls.append((command, kwargs))
        value = {'status':'FAIL', 'error_type':'credential-secret'}
        return subprocess.CompletedProcess(command,0,MARKER+json.dumps(value),'private-account-id')
    result = run_probe('sha256:'+'a'*64,'b'*40,
                       {'ALPACA_API_KEY':'credential-secret','ALPACA_SECRET_KEY':'other-secret'}, runner=runner)
    assert result['status'] == 'FAIL' and result['reason'] == 'PROVIDER_PROBE_OUTPUT_REFUSED'
    assert 'credential-secret' not in json.dumps(result) and 'private-account-id' not in json.dumps(result)
    assert 'credential-secret' not in ' '.join(calls[0][0])
    assert calls[0][1]['env']['ALPACA_API_KEY'] == 'credential-secret'


def test_readonly_feed_diagnostic_never_claims_complete_go(tmp_path, capsys):
    from tools.autonomy_feed_qualification import main
    output = tmp_path/'diagnostic'
    assert main(['--runtime-image','sha256:'+'a'*64,'--commit','b'*40,
                 '--output-dir',str(output),'--plan-only']) == 2
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == report['source']['status'] == 'NOT_PROVEN'
    assert not report['financial_publication_attempted'] and report['broker_mutation_attempts'] == 0
    assert 'formation_restart_parity' in report['unexecuted']
    with pytest.raises(SystemExit):
        main(['--runtime-image','sha256:'+'a'*64,'--commit','b'*40,
              '--output-dir',str(output),'--plan-only'])



def test_readonly_feed_diagnostic_cleans_only_its_named_container_after_timeout():
    import subprocess
    from tools.autonomy_feed_qualification import run_probe
    calls = []
    def runner(command, **kwargs):
        calls.append((command,kwargs))
        if command[:2] == ['docker','run']:
            raise subprocess.TimeoutExpired(command,600)
        return subprocess.CompletedProcess(command,0,'','')
    with pytest.raises(subprocess.TimeoutExpired):
        run_probe('sha256:'+'a'*64,'b'*40,
                  {'ALPACA_API_KEY':'secret','ALPACA_SECRET_KEY':'secret2'},runner=runner)
    name = calls[0][0][calls[0][0].index('--name')+1]
    assert calls[1][0] == ['docker','rm','--force',name]
    assert name.startswith('sentinel-source-diagnostic-')
    assert not any(key in calls[1][1]['env'] for key in ('ALPACA_API_KEY','ALPACA_SECRET_KEY'))
