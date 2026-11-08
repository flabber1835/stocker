"""Network-free transfer tests using the exact immutable acquire function."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

HERE = Path(__file__).parent
MODULE = HERE / 'system_campaign_stage_transport.py'
if not MODULE.exists():
    MODULE = HERE.parents[1] / MODULE.name
spec = importlib.util.spec_from_file_location('qualified_stage_transport', MODULE)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
FIXTURE = HERE / 'immutable-stage-acquire-fixture.json'
FIXTURE_SHA = '9df4561a0a91f898b43463e9d63b57d322499ebc888f56839b0d155f4092c6d3'
ACQUIRE_AST = 'd1b10c686d5f202dfa29072f0b6ca7279cbf4061a81568f060c7f48c7a6e0dc9'
VALIDATE_AST = '1c209a9534f1754864be885b8e84f27d3ade22be2e2e132965810d0e7fc29e04'
TOKEN = 'synthetic-read-token'


class Response(io.BytesIO):
    def __init__(self, body, url='', *, headers=None, status=200):
        super().__init__(body)
        self.headers = {} if headers is None else headers
        self.status, self.url = status, url

    def geturl(self):
        return self.url


class QueueAPI:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        assert self.values, 'unexpected additional HTTP call'
        result = self.values.pop(0)
        if callable(result):
            result = result(request)
        if isinstance(result, Exception):
            raise result
        return result


def fail(code=504, headers=None):
    return urllib.error.HTTPError(adapter.PUBLIC_ROOT + 'part', code, 'synthetic', headers or {}, None)


def ordinary_failure(*args, **kwargs):
    raise fail()


def request_for(values=(b'a' * 48, b'b' * 48)):
    assets = {}
    names = ('data.tar.crseal', 'runtime.tar.crseal')
    for name, value in zip(names, values, strict=True):
        assets[name] = dict(bytes=len(value), sha256=hashlib.sha256(value).hexdigest(),
                           parts=[dict(name=name + '.part-0000', bytes=len(value), sha256=hashlib.sha256(value).hexdigest())])
    return dict(schema='research.capital-risk-stage-request/1', request_id='stage-002', stage='stage',
        protocol_sha256='a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52',
        expected_image='sha256:97b69cf2f8487785e55a4ecafe2497829d021a9d58b5e4af001e8dcc6a981309',
        release=adapter.RELEASE, manifest_sha256='a' * 64, assets=assets)


def stage_functions():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    fixture = json.loads(raw)
    assert fixture['source_sha256'] == adapter.STAGE_SHA
    assert fixture['financial_runtime_code'] is False
    ns = dict(urllib=SimpleNamespace(request=urllib.request), hashlib=hashlib, re=__import__('re'),
              PROTOCOL=request_for()['protocol_sha256'], IMAGE=request_for()['expected_image'],
              RELEASE=adapter.RELEASE, MAX_ASSET=3 * 1024 ** 3)
    for name, expected in [('acquire', ACQUIRE_AST), ('validate_request', VALIDATE_AST)]:
        item = fixture['functions'][name]
        node, = ast.parse(item['source']).body
        assert hashlib.sha256(item['source'].encode()).hexdigest() == item['source_sha256']
        assert hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() == item['ast_sha256'] == expected
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(FIXTURE), 'exec'), ns)
    return SimpleNamespace(**ns)


def metadata(request):
    assets = []
    for index, (url, part) in enumerate(adapter.declared_parts(request).items(), 101):
        assets.append(dict(id=index, name=part['name'], size=part['bytes'], state='uploaded',
            browser_download_url=url, url=adapter.API_ROOT + '/releases/assets/' + str(index),
            digest='sha256:' + part['sha256']))
    return dict(id=55, tag_name=adapter.RELEASE, draft=False, assets=assets,
        url=adapter.API_ROOT + '/releases/55', assets_url=adapter.API_ROOT + '/releases/55/assets',
        html_url='https://github.com/' + adapter.REPOSITORY + '/releases/tag/' + adapter.RELEASE)


def json_response(value):
    return Response(json.dumps(value).encode(), adapter.API_ROOT + '/releases/tags/' + adapter.RELEASE)


def binary(body):
    return lambda req: Response(body, req.full_url, headers={'Content-Length': str(len(body))})


def headers(request):
    return {k.lower(): v for k, v in request.header_items()}


def test_original_acquire_public_success_never_calls_api(tmp_path, monkeypatch):
    stage = stage_functions()
    request = request_for()
    stage.validate_request(request)
    calls = []
    def original(url, timeout):
        calls.append(url)
        return Response(b'a' * 48, headers={'Content-Length': '48'})
    api = QueueAPI([])
    monkeypatch.setattr(urllib.request, 'urlopen', original)
    with adapter.installed(request, TOKEN, api_opener=api):
        result = stage.acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)
    assert result.read_bytes() == b'a' * 48 and len(calls) == 1 and api.calls == []
    assert urllib.request.urlopen is original


def test_original_acquire_api_direct_two_parts_metadata_once(tmp_path, monkeypatch):
    stage = stage_functions()
    request = request_for()
    api = QueueAPI([json_response(metadata(request)), binary(b'a' * 48), binary(b'b' * 48)])
    monkeypatch.setattr(urllib.request, 'urlopen', ordinary_failure)
    with adapter.installed(request, TOKEN, api_opener=api) as transfer:
        for name, declared in request['assets'].items():
            stage.acquire(name, declared, tmp_path)
        assert transfer.calls == 3 and len(transfer.assets) == 2
    assert urllib.request.urlopen is ordinary_failure
    assert all(headers(req)['authorization'] == 'Bearer ' + TOKEN for req, _ in api.calls)
    assert all(timeout == 60 for _, timeout in api.calls)
    assert transfer.token is None


def test_actual_acquire_multi_part_mode_transition_uses_public_once(tmp_path,monkeypatch):
    request=request_for();a=b'a'*48;b=b'b'*48
    request['assets']['data.tar.crseal']=dict(bytes=96,sha256=hashlib.sha256(a+b).hexdigest(),parts=[
        dict(name='data.tar.crseal.part-0000',bytes=48,sha256=hashlib.sha256(a).hexdigest()),
        dict(name='data.tar.crseal.part-0001',bytes=48,sha256=hashlib.sha256(b).hexdigest())])
    public=[]
    def original(url,**kwargs):public.append(url);raise fail()
    api=QueueAPI([json_response(metadata(request)),binary(a),binary(b),binary(b)])
    monkeypatch.setattr(urllib.request,'urlopen',original)
    stage=stage_functions();stage.validate_request(request)
    with adapter.installed(request,TOKEN,api_opener=api)as transfer:
        for name,declared in request['assets'].items():stage.acquire(name,declared,tmp_path)
        assert transfer.calls==4 and len(transfer.seen)==3
    assert len(public)==1 and(tmp_path/'data.tar.crseal').read_bytes()==a+b
    assert(tmp_path/'runtime.tar.crseal').read_bytes()==b and urllib.request.urlopen is original


def test_first_success_then_failure_only_switches_after_metadata_closes(tmp_path,monkeypatch):
    request=request_for();a=b'a'*48;b=b'b'*48
    request['assets']['data.tar.crseal']=dict(bytes=96,sha256=hashlib.sha256(a+b).hexdigest(),parts=[
        dict(name='data.tar.crseal.part-0000',bytes=48,sha256=hashlib.sha256(a).hexdigest()),
        dict(name='data.tar.crseal.part-0001',bytes=48,sha256=hashlib.sha256(b).hexdigest())])
    public=[]
    def original(url,**kwargs):
        public.append(url)
        if len(public)==1:return Response(a,headers={'Content-Length':'48'})
        raise fail()
    api=QueueAPI([json_response(metadata(request)),binary(b),binary(b)])
    monkeypatch.setattr(urllib.request,'urlopen',original)
    with adapter.installed(request,TOKEN,api_opener=api)as transfer:
        for name,declared in request['assets'].items():stage_functions().acquire(name,declared,tmp_path)
    assert len(public)==2 and len(api.calls)==3 and len(transfer.seen)==3


def test_incomplete_metadata_never_activates_release_wide_mode():
    request=request_for();data=metadata(request);data['assets'][1]['size']=1
    public=[]
    def original(url,**kwargs):public.append(url);raise fail()
    api=QueueAPI([json_response(data)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,original,api_opener=api)
    with pytest.raises(ValueError,match='ASSET_IDENTITY'):transfer.open(next(iter(transfer.parts)),timeout=60)
    assert transfer.assets is None and len(public)==1 and len(api.calls)==1


def test_later_api_part_corruption_refuses_without_public_retry(tmp_path,monkeypatch):
    request=request_for();public=[]
    def original(url,**kwargs):public.append(url);raise fail()
    api=QueueAPI([json_response(metadata(request)),binary(b'a'*48),binary(b'x'*48)])
    monkeypatch.setattr(urllib.request,'urlopen',original)
    with adapter.installed(request,TOKEN,api_opener=api):
        stage_functions().acquire('data.tar.crseal',request['assets']['data.tar.crseal'],tmp_path)
        with pytest.raises(ValueError,match='PART_OR_LENGTH'):
            stage_functions().acquire('runtime.tar.crseal',request['assets']['runtime.tar.crseal'],tmp_path)
    assert len(public)==1 and len(api.calls)==3


def test_qualified_mode_remains_exact_scope_and_duplicate_guard():
    request=request_for();public=[]
    def original(url,**kwargs):public.append(url);raise fail()
    api=QueueAPI([json_response(metadata(request)),binary(b'a'*48)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,original,api_opener=api)
    url=next(iter(transfer.parts));transfer.open(url,timeout=60).close()
    with pytest.raises(ValueError,match='OPEN_ONCE'):transfer.open(url,timeout=60)
    with pytest.raises(urllib.error.HTTPError):transfer.open(adapter.PUBLIC_ROOT+'unrequested',timeout=60)
    assert len(public)==2 and len(api.calls)==2


def test_original_acquire_manual_redirect_has_no_credential(tmp_path, monkeypatch):
    request = request_for()
    location = 'https://release-assets.githubusercontent.com/github-production-release-asset/test?sig=synthetic-secret'
    redirect = urllib.error.HTTPError(adapter.API_ROOT + '/releases/assets/101', 302, '', {'Location': location}, None)
    api = QueueAPI([json_response(metadata(request)), redirect, binary(b'a' * 48)])
    monkeypatch.setattr(urllib.request, 'urlopen', ordinary_failure)
    with adapter.installed(request, TOKEN, api_opener=api):
        stage_functions().acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)
    assert headers(api.calls[1][0])['authorization'] == 'Bearer ' + TOKEN
    assert 'authorization' not in headers(api.calls[2][0])
    assert api.calls[2][0].full_url == location


@pytest.mark.parametrize('bad,reason', [(b'x' * 48, 'PART_OR_LENGTH'), (b'a' * 47, 'PART_OR_LENGTH'), (b'a' * 49, 'SIZE')])
def test_actual_immutable_acquire_refuses_wrong_bytes(tmp_path, monkeypatch, bad, reason):
    request = request_for()
    api = QueueAPI([json_response(metadata(request)), lambda req: Response(bad, req.full_url)])
    monkeypatch.setattr(urllib.request, 'urlopen', ordinary_failure)
    with adapter.installed(request, TOKEN, api_opener=api), pytest.raises(ValueError, match=reason):
        stage_functions().acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)
    assert len(api.calls) == 2


def test_actual_immutable_acquire_content_length_guard(tmp_path, monkeypatch):
    request = request_for()
    api = QueueAPI([json_response(metadata(request)), lambda req: Response(b'a' * 48, req.full_url, headers={'Content-Length': '49'})])
    monkeypatch.setattr(urllib.request, 'urlopen', ordinary_failure)
    with adapter.installed(request, TOKEN, api_opener=api), pytest.raises(ValueError, match='REFUSED_DOWNLOAD_LENGTH'):
        stage_functions().acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)


def test_original_destination_xb_guard_precedes_network(tmp_path, monkeypatch):
    request = request_for()
    (tmp_path / 'data.tar.crseal').write_bytes(b'preserved')
    api = QueueAPI([])
    monkeypatch.setattr(urllib.request, 'urlopen', ordinary_failure)
    with adapter.installed(request, TOKEN, api_opener=api), pytest.raises(FileExistsError):
        stage_functions().acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)
    assert api.calls == [] and (tmp_path / 'data.tar.crseal').read_bytes() == b'preserved'


@pytest.mark.parametrize('change', ['asset_name','part_name','part_total','release'])
def test_actual_immutable_request_refuses_destination_and_commitment_escape(change):
    request=request_for()
    if change=='asset_name':request['assets']['../escape']=request['assets'].pop('data.tar.crseal')
    elif change=='part_name':request['assets']['data.tar.crseal']['parts'][0]['name']='../escape'
    elif change=='part_total':request['assets']['data.tar.crseal']['parts'][0]['bytes']=47
    else:request['release']='foreign-release'
    with pytest.raises(ValueError,match='REFUSED_'):stage_functions().validate_request(request)


def test_no_fallback_or_retry_after_first_stream_bytes(tmp_path, monkeypatch):
    class Broken(Response):
        def read(self, size=-1):
            if self.tell():
                raise ConnectionResetError('synthetic stream interruption')
            return super().read(24)
    request = request_for()
    api = QueueAPI([])
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: Broken(b'a' * 48))
    with adapter.installed(request, TOKEN, api_opener=api), pytest.raises(ValueError,match='STREAM_INTERRUPTED'):
        stage_functions().acquire('data.tar.crseal', request['assets']['data.tar.crseal'], tmp_path)
    assert api.calls == [] and (tmp_path / 'data.tar.crseal').stat().st_size == 24


@pytest.mark.parametrize('mutate', [lambda x: x.update(tag_name='foreign'), lambda x: x.update(url='https://api.github.com/repos/other/repo/releases/55'),
    lambda x: x['assets'][0].update(size=49), lambda x: x['assets'][0].update(id=True),
    lambda x: x['assets'][0].update(browser_download_url='https://evil.invalid/file'),
    lambda x: x['assets'][0].update(url=adapter.API_ROOT + '/releases/assets/999'),
    lambda x: x['assets'][0].update(digest='sha256:' + '0' * 64),
    lambda x: x['assets'].append(deepcopy(x['assets'][0])),
    lambda x: x['assets'][1].update(id=x['assets'][0]['id'], url=x['assets'][0]['url'])])
def test_complete_release_asset_identity_failures(mutate):
    request = request_for(); data = metadata(request); mutate(data)
    api = QueueAPI([json_response(data)])
    transfer = adapter.ReleaseTransfer(request, TOKEN, ordinary_failure, api_opener=api)
    with pytest.raises(ValueError, match='REFUSED_STAGE_TRANSPORT_'):
        transfer.open(next(iter(transfer.parts)), timeout=60)
    assert len(api.calls) == 1


@pytest.mark.parametrize('location', ['https://evil.invalid/?signed=secret', 'http://release-assets.githubusercontent.com/file',
    'https://api.github.com@evil.invalid/file', 'https://release-assets.githubusercontent.com.evil.invalid/file',
    'https://user:password@release-assets.githubusercontent.com/file', 'https://release-assets.githubusercontent.com/file#secret'])
def test_redirect_origin_refusal_never_sends_credential(location):
    request = request_for()
    redirect = urllib.error.HTTPError('api', 302, '', {'Location': location}, None)
    api = QueueAPI([json_response(metadata(request)), redirect])
    transfer = adapter.ReleaseTransfer(request, TOKEN, ordinary_failure, api_opener=api)
    with pytest.raises(ValueError, match='REFUSED_STAGE_TRANSPORT_') as caught:
        transfer.open(next(iter(transfer.parts)), timeout=60)
    assert len(api.calls) == 2 and location not in str(caught.value) and TOKEN not in str(caught.value)


@pytest.mark.parametrize('code,remaining', [(403, None), (429, None), (503, '0')])
def test_rate_limit_refusal_no_fallback(code, remaining):
    h = {} if remaining is None else {'X-RateLimit-Remaining': remaining}
    def original(*args, **kwargs): raise fail(code, h)
    api = QueueAPI([])
    transfer = adapter.ReleaseTransfer(request_for(), TOKEN, original, api_opener=api)
    with pytest.raises(ValueError, match='RATE_LIMIT'):
        transfer.open(next(iter(transfer.parts)), timeout=60)
    assert api.calls == []


@pytest.mark.parametrize('code', [403, 429])
def test_api_rate_limit_explicit_stops(code):
    request = request_for()
    api = QueueAPI([urllib.error.HTTPError('api', code, '', {'Retry-After': '60'}, None)])
    transfer = adapter.ReleaseTransfer(request, TOKEN, ordinary_failure, api_opener=api)
    with pytest.raises(ValueError, match='RATE_LIMIT_HTTP_' + str(code)):
        transfer.open(next(iter(transfer.parts)), timeout=60)
    assert len(api.calls) == 1


def test_retry_after_bounded_seconds_and_http_date():
    waited = []
    transfer = adapter.ReleaseTransfer(request_for(), TOKEN, ordinary_failure, sleep=waited.append,
        now=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc))
    transfer.delay({'Retry-After': '2'})
    transfer.delay({'Retry-After': 'Thu, 05 Nov 2026 00:00:03 GMT'})
    assert waited == [2, 3] and transfer.waited == 5
    for value in ('6', '-1', 'NaN', 'bad'):
        with pytest.raises(ValueError, match='RETRY_AFTER'):
            transfer.delay({'Retry-After': value})
    transfer.waited = 14
    with pytest.raises(ValueError, match='BUDGET'): transfer.delay({'Retry-After': '2'})


def test_initial_retry_after_precedes_single_metadata_call():
    order=[]; request=request_for()
    def original(*a, **k): raise fail(504, {'Retry-After':'2'})
    api=QueueAPI([lambda req: (order.append('metadata') or json_response(metadata(request))), binary(b'a'*48)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,original,api_opener=api,sleep=lambda seconds:order.append(('wait',seconds)))
    transfer.open(next(iter(transfer.parts)),timeout=60).close()
    assert order==[('wait',2),'metadata']


def test_budget_origin_and_duplicate_public_open_fail_before_request():
    api = QueueAPI([])
    transfer = adapter.ReleaseTransfer(request_for(), TOKEN, ordinary_failure, api_opener=api)
    with pytest.raises(ValueError, match='CREDENTIAL_ORIGIN'):
        transfer.request('https://evil.invalid/path', authenticated=True, accept='x')
    transfer.calls = transfer.max_calls
    with pytest.raises(ValueError, match='CALL_BUDGET'):
        transfer.request(adapter.API_ROOT + '/releases/assets/101', authenticated=True, accept='x')
    url = next(iter(transfer.parts)); transfer.seen.add(url)
    with pytest.raises(ValueError, match='OPEN_ONCE'): transfer.open(url, timeout=60)
    assert api.calls == []


def test_unrelated_url_delegates_exactly_without_fallback():
    calls=[]
    def original(*args,**kwargs): calls.append((args,kwargs)); raise fail()
    transfer=adapter.ReleaseTransfer(request_for(),TOKEN,original,api_opener=QueueAPI([]))
    with pytest.raises(urllib.error.HTTPError):transfer.open('https://github.com/unrelated',timeout=9)
    assert calls==[(('https://github.com/unrelated',),{'timeout':9})] and not transfer.seen


@pytest.mark.parametrize('error', [urllib.error.HTTPError('x',404,'',{},None),urllib.error.URLError('dns unavailable')])
def test_nontransient_original_open_refuses_without_api(error):
    def original(*a,**k):raise error
    api=QueueAPI([]);transfer=adapter.ReleaseTransfer(request_for(),TOKEN,original,api_opener=api)
    with pytest.raises(ValueError,match='NONTRANSIENT'):transfer.open(next(iter(transfer.parts)),timeout=60)
    assert api.calls==[]


def test_opener_restored_on_exception_and_nested_scope(monkeypatch):
    original=lambda *a,**k:None
    monkeypatch.setattr(urllib.request,'urlopen',original)
    with pytest.raises(RuntimeError):
        with adapter.installed(request_for(),TOKEN,api_opener=QueueAPI([])) as outer:
            installed=urllib.request.urlopen
            with adapter.installed(request_for(),TOKEN,api_opener=QueueAPI([])):
                pass
            assert urllib.request.urlopen==installed
            raise RuntimeError('synthetic')
    assert urllib.request.urlopen is original and outer.token is None


def test_no_redirect_handler_never_forwards_request():
    req=urllib.request.Request(adapter.API_ROOT+'/x',headers={'Authorization':'Bearer '+TOKEN})
    assert adapter.NoRedirect().redirect_request(req,None,302,'',{},'https://evil.invalid') is None


def test_metadata_byte_bound_and_no_retry():
    request=request_for()
    api=QueueAPI([Response(b' '* (adapter.METADATA_LIMIT+1),adapter.API_ROOT+'/releases/tags/'+adapter.RELEASE)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,ordinary_failure,api_opener=api)
    with pytest.raises(ValueError,match='METADATA_SIZE'):transfer.open(next(iter(transfer.parts)),timeout=60)
    assert len(api.calls)==1


def test_api_transient_failure_stops_without_retry_or_url_leak():
    request=request_for();signed='https://release-assets.githubusercontent.com/file?sig=synthetic-secret'
    api=QueueAPI([json_response(metadata(request)),urllib.error.HTTPError(signed,504,'bad '+signed,{},None)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,ordinary_failure,api_opener=api)
    with pytest.raises(ValueError,match='API_OPEN_HTTP_504')as caught:transfer.open(next(iter(transfer.parts)),timeout=60)
    assert signed not in str(caught.value)and TOKEN not in str(caught.value)and len(api.calls)==2


def test_no_retry_when_api_response_stream_fails(tmp_path,monkeypatch):
    class Broken(Response):
        def read(self,size=-1):raise ConnectionResetError('synthetic API stream failure')
    request=request_for()
    api=QueueAPI([json_response(metadata(request)),lambda req:Broken(b'',req.full_url)])
    monkeypatch.setattr(urllib.request,'urlopen',ordinary_failure)
    with adapter.installed(request,TOKEN,api_opener=api),pytest.raises(ValueError,match='STREAM_INTERRUPTED'):
        stage_functions().acquire('data.tar.crseal',request['assets']['data.tar.crseal'],tmp_path)
    assert len(api.calls)==2


def test_signed_url_stream_error_is_opaque_and_never_retried():
    secret='https://release-assets.githubusercontent.com/file?sig=synthetic-secret'
    class Broken(Response):
        def read(self,size=-1):raise urllib.error.URLError(secret)
    response=adapter.OpaqueResponse(Broken(b''))
    with pytest.raises(ValueError,match='STREAM_INTERRUPTED')as caught:response.read(10)
    assert secret not in str(caught.value)and caught.value.__suppress_context__ is True


@pytest.mark.parametrize('error',[TimeoutError('timeout'),urllib.error.URLError(TimeoutError('timeout')),ConnectionResetError('reset')])
def test_eligible_open_transport_exceptions(error):
    request=request_for()
    def original(*a,**k):raise error
    api=QueueAPI([json_response(metadata(request)),binary(b'a'*48)])
    transfer=adapter.ReleaseTransfer(request,TOKEN,original,api_opener=api)
    transfer.open(next(iter(transfer.parts)),timeout=60).close()
    assert len(api.calls)==2


def test_binding_exact_immutable_hashes_and_adapter_pin(tmp_path,monkeypatch):
    stagefile=tmp_path/'stage.py';stagefile.write_bytes(b'synthetic-host-staging-source')
    request=tmp_path/'stage-request.json';request.write_bytes(b'synthetic-request')
    assert adapter.STAGE_SHA=='2ab2596762e059c6178361b45295739a14973992701ca95ee0e77d34b534f163'
    assert json.loads(FIXTURE.read_bytes())['source_sha256']==adapter.STAGE_SHA
    stagehash=hashlib.sha256(stagefile.read_bytes()).hexdigest();requesthash=hashlib.sha256(request.read_bytes()).hexdigest()
    monkeypatch.setattr(adapter,'STAGE_SHA',stagehash);monkeypatch.setattr(adapter,'STAGE_REQUEST_SHA',requesthash)
    factual={'sources':{MODULE.name:hashlib.sha256(MODULE.read_bytes()).hexdigest(),'stage.py':stagehash,'stage-request.json':requesthash}}
    adapter.validate_binding(tmp_path,factual,request)
    for name in factual['sources']:
        bad=deepcopy(factual);bad['sources'][name]='0'*64
        with pytest.raises(ValueError,match='SOURCE_BINDING'):adapter.validate_binding(tmp_path,bad,request)
    stagefile.write_bytes(b'changed')
    with pytest.raises(ValueError,match='IMMUTABLE_STAGE'):adapter.validate_binding(tmp_path,factual,request)


def test_cli_original_stage_called_with_token_absent_and_argv_restored(tmp_path,monkeypatch):
    request=tmp_path/'stage-request.json';request.write_text(json.dumps(request_for()))
    factual=tmp_path/'request.json';factual.write_text('{}')
    original_argv=['adapter','--request',str(request),'--factual-request',str(factual),'--output',str(tmp_path/'out.json')]
    monkeypatch.setattr(sys,'argv',original_argv)
    monkeypatch.setenv('GH_TOKEN',TOKEN)
    monkeypatch.setattr(adapter,'validate_binding',lambda *args:None)
    observed=[]
    stage=SimpleNamespace(__file__=str(MODULE.parent/'stage.py'))
    def check(env):assert env['GH_TOKEN']==TOKEN;observed.append('hosted')
    stage.check_context=check;stage.validate_request=stage_functions().validate_request
    def original_main():
        import os
        assert 'GH_TOKEN'not in os.environ
        assert sys.argv==[str(MODULE.parent/'stage.py'),'--request',str(request),'--output',str(tmp_path/'out.json')]
        assert getattr(urllib.request.urlopen,'__self__',None).token==TOKEN
        observed.append('original-stage-main')
        raise RuntimeError('synthetic stage stop')
    stage.main=original_main
    monkeypatch.setitem(sys.modules,'stage',stage)
    original=urllib.request.urlopen
    with pytest.raises(RuntimeError,match='synthetic stage stop'):adapter.main()
    assert observed==['hosted','original-stage-main']and sys.argv is original_argv and urllib.request.urlopen is original


def test_cli_wrong_stage_origin_refuses_before_token_or_context(tmp_path,monkeypatch):
    request=tmp_path/'stage-request.json';request.write_text('{}')
    factual=tmp_path/'request.json';factual.write_text('{}')
    monkeypatch.setattr(sys,'argv',['adapter','--request',str(request),'--factual-request',str(factual),'--output',str(tmp_path/'out')])
    monkeypatch.setattr(adapter,'validate_binding',lambda *args:None)
    monkeypatch.setenv('GH_TOKEN',TOKEN)
    monkeypatch.setitem(sys.modules,'stage',SimpleNamespace(__file__='/foreign/stage.py'))
    with pytest.raises(ValueError,match='IMPORTED_STAGE_ORIGIN'):adapter.main()
    assert __import__('os').environ['GH_TOKEN']==TOKEN


@pytest.mark.parametrize('guard', ['credential','budget','asset_size'])
def test_critical_guard_removal_admits_forbidden_synthetic_case(guard):
    text=MODULE.read_text();ns={'__name__':'guard_removed'}
    if guard=='credential':
        old="parsed.netloc == 'api.github.com' and url.startswith(API_ROOT + '/')"
        text=text.replace(old,'True',1)
    elif guard=='budget':
        text=text.replace("need(self.calls < self.max_calls, 'REFUSED_STAGE_TRANSPORT_CALL_BUDGET')",'pass',1)
    else:
        text=text.replace("type(asset.get('size')) is int and asset['size'] == part['bytes']",'True',1)
    assert text!=MODULE.read_text()
    exec(compile(text,str(MODULE),'exec'),ns)
    request=request_for(); data=metadata(request)
    if guard=='asset_size':
        data['assets'][0]['size']=49
        api=QueueAPI([json_response(data)])
    else:api=QueueAPI([lambda req:Response(b'',req.full_url)])
    transfer=ns['ReleaseTransfer'](request,TOKEN,ordinary_failure,api_opener=api)
    if guard=='credential':transfer.request('https://evil.invalid/file',authenticated=True,accept='x').close()
    elif guard=='budget':
        transfer.calls=transfer.max_calls
        transfer.request(adapter.API_ROOT+'/x',authenticated=True,accept='x').close()
    else:transfer.metadata();assert transfer.assets
    assert len(api.calls)==1


@pytest.mark.parametrize('forbidden',['stock_strategy_shared','sentinel','research.pooled_','numpy','pandas'])
def test_no_financial_imports(forbidden):
    tree=ast.parse(MODULE.read_text())
    imports=[n.module or '' for n in ast.walk(tree)if isinstance(n,ast.ImportFrom)]
    imports += [alias.name for n in ast.walk(tree)if isinstance(n,ast.Import)for alias in n.names]
    assert not any(name.startswith(forbidden)for name in imports)
