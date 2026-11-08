"""Host staging then unchanged source hydration; synthetic transport or exact retained asset."""
import ast,builtins,csv,hashlib,io,json,os,sys,zipfile
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace
import urllib.request
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import C,DEP,data,runtime,env,fixture,fence,sha

PROVIDER_FIXTURE_SHA='179778da390f6f612e2e7d7df3a7865ddd15929be93ae2fe7c0292ca352df254'
@pytest.fixture
def provider(monkeypatch):
    import system_campaign_sprint_facts as sprint
    raw_fixture=(Path(__file__).parent/'fixtures/original-provider-selected-rows.json').read_bytes()
    assert sha(raw_fixture)==PROVIDER_FIXTURE_SHA
    value=json.loads(raw_fixture)
    assert (sprint.ALIAS_BYTES,sprint.ALIAS_SHA)==(9855560,'db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02')
    actual=os.environ.get('ADDITIONAL_SENSOR_REAL_ALIAS')
    if actual:
        raw=Path('\\\\?\\'+str(Path(actual).resolve())).read_bytes()
        assert len(raw)==sprint.ALIAS_BYTES and sha(raw)==sprint.ALIAS_SHA
    else:
        text=io.StringIO();writer=csv.DictWriter(text,fieldnames=list(value['rows'][0]));writer.writeheader();writer.writerows(value['rows'])
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('synthetic-transport-original-rows.csv',text.getvalue())
        raw=output.getvalue()
        # Explicit synthetic transport binding only. Original source + constants asserted above.
        monkeypatch.setattr(sprint,'ALIAS_BYTES',len(raw));monkeypatch.setattr(sprint,'ALIAS_SHA',sha(raw))
    for key,val in [('GITHUB_ACTIONS','true'),('RUNNER_ENVIRONMENT','github-hosted'),('GITHUB_RUN_ATTEMPT','1')]:monkeypatch.setenv(key,val)
    return SimpleNamespace(raw=raw,actual=bool(actual),sprint=sprint,rows=value['rows'])

class Response:
    status=200;headers={'Content-Encoding':'identity'}
    def __init__(self,raw):self.raw=raw;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):self.calls.append(n);return self.raw[:n]

def stage_function(p):
    import system_campaign_financial_future as f
    fn=data.function((C/'system_campaign_financial_future.py').read_bytes(),'stage_selected_sources')
    scope=dict(vars(f));scope['ROOT_BOUND_ALIAS_SOURCE_PHASES']=dict(f.ROOT_BOUND_ALIAS_SOURCE_PHASES)
    scope['ROOT_BOUND_ALIAS_SOURCE_PHASES'][p['arm'],p['origin_cursor']]=(p['origin_root_admission_sha256'],p['origin_outer_sha256'],p['origin_completed'])
    scope['ADDITIONAL_SENSOR_ALIAS_PHASES']=frozenset({(p['arm'],p['origin_cursor'])})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-host-staging-function>','exec'),scope)
    return scope['stage_selected_sources']

def hydrate_function(e,provider,*,rows=None,native=None,contract_change=None):
    import system_campaign_zogenix_facts as z
    actual=data.source('system-campaign-zogenix-sensor-contract.json');assert sha(actual)=='699149d418a932ca10f7c1f0848a5e9bb5f14083be431f7fde3a741c1d4313de'
    contract=json.loads(actual)
    if not provider.actual:contract['provider_archive_sha256']=sha(provider.raw)
    if contract_change:contract_change(contract)
    Native=make_dataclass('SyntheticSourceNative',[(k,object) for k in contract['native']])
    Native.completeness=lambda self,n:(False,('synthetic source-native completeness stub',))
    term=Native(**(native if native is not None else contract['native']))
    selected_rows=deepcopy(e.fixture['original_zogenix_rows'] if rows is None else rows)
    inputs=SimpleNamespace(load_actions=lambda path:SimpleNamespace(terminal={z.NATIVE:(term,)}),
                           _archive_rows=lambda archive,name:iter(selected_rows))
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='research.pooled_input_support':return SimpleNamespace(inputs=inputs)
        if name=='research.pooled_input_support.bundle':return SimpleNamespace(axis=lambda:['2022-03-03','2022-03-04','2022-03-07'])
        return builtins.__import__(name,globals,locals,fromlist,level)
    class Files:
        def __truediv__(self,name):
            assert name==z.CONTRACT
            return SimpleNamespace(read_bytes=lambda:data.encoded(contract))
    real_zip=zipfile.ZipFile
    class Zip:
        @staticmethod
        def ZipFile(path,*a,**k):
            if str(path)=='/frozen/archive/corpus.zip':return nullcontext(SimpleNamespace(synthetic_source_reader=True))
            return real_zip(path,*a,**k)
    scope=dict(vars(z),HERE=Files(),zipfile=Zip,hosted=lambda:None,
        __builtins__=dict(vars(builtins),__import__=imports))
    fn=data.function(data.source('system_campaign_zogenix_facts.py'),'hydrate')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<unchanged-original-source-hydrate>','exec'),scope)
    return scope['hydrate']

def folders(tmp_path):
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir();return old,out

def test_original_host_stage_then_original_hydrate_uses_staged_out_not_old(env,provider,monkeypatch,tmp_path):
    old,out=folders(tmp_path);response=Response(provider.raw);calls=[]
    def open(url,timeout):
        calls.append((url,timeout));assert url==provider.sprint.ALIAS_URL;return response
    monkeypatch.setattr(urllib.request,'urlopen',open)
    stage_function(env.p)(env.spec,old,out)
    assert calls==[(provider.sprint.ALIAS_URL,60)] and response.calls==[len(provider.raw)+1]
    assert (out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes()==provider.raw
    hydrate=hydrate_function(env,provider);native=hydrate(out,out)
    private=json.loads((out/'hydrated-zogenix-sensor-event.json').read_bytes())
    assert private['actual_native']==env.p['event']['native_term'] and private['source_quote_present'] is False
    assert [data.digest(r) for r in private['provider_rows']]==private['contract']['provider_row_sha256']
    assert len(private['provider_rows'])==3 and private['right_market_price_observed'] is False
    with pytest.raises(FileNotFoundError):hydrate(old,old)

@pytest.mark.parametrize('wrong',['root','outer','closes'])
def test_original_host_alias_binding_rejects_foreign_root_before_fetch(env,provider,monkeypatch,tmp_path,wrong):
    old,out=folders(tmp_path);spec=dict(env.spec)
    spec[{'root':'root_admission_sha256','outer':'outer_sha256','closes':'measured_closes'}[wrong]]=1048 if wrong=='closes' else '0'*64
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('foreign root attempted fetch'))
    with pytest.raises(ValueError,match='QUALIFIED_OWN_ROOT'):stage_function(env.p)(spec,old,out)

@pytest.mark.parametrize('wrong',['quote','row','native','provider_rows'])
def test_original_hydrate_full_source_native_and_provider_guards(env,provider,tmp_path,wrong):
    old,out=folders(tmp_path);(out/'provider-source').mkdir();(out/'provider-source/SHARADAR_ACTIONS.zip').write_bytes(provider.raw)
    rows=deepcopy(env.fixture['original_zogenix_rows']);native=None;change=None
    if wrong=='quote':rows.append(dict(rows[0],session='2022-03-07'))
    elif wrong=='row':rows[0]['raw_open']='999'
    elif wrong=='native':native=dict(env.p['event']['native_term'],cash_per_share=28.)
    else:change=lambda c:c.update(provider_row_sha256=['0'*64]*3)
    with pytest.raises(ValueError):hydrate_function(env,provider,rows=rows,native=native,contract_change=change)(out,out)
    assert not(out/'hydrated-zogenix-sensor-event.json').exists()
