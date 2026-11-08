import sys,json
from pathlib import Path
from copy import deepcopy
import pytest
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p07-fin343-full25-reporting-20261107');C=Path(__file__).resolve().parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REPORT25_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_full25_reporting as r
def request(t):return dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=r.MODE,arms=['P07'],financial_resume_authorized=False,readonly_partial_review=True,readonly_source_witnesses=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,**{r.FIELD:{'P07':r.declaration(t)}})
def test_real_target():
    t=r.fact()['target'];r.validate(t)
    assert (t['measured_closes'],t['selected_session'],len(t['repairs']))==(1383,'2023-06-30',25)
    assert t['monthly_seed_root_admission_sha256']==r.ROOT
    assert 'root_admission' not in t and 'root_requalified_fin326_failed_review_parent' not in t
    r.require_request(request(t),t)

def test_original_crypto_refusal_guard_distinguishes_current_and_historical_labels():
    import system_campaign_factual_admit as crypto
    t=r.fact()['target'];assert 'review_refusal' not in t
    import ast
    source=ast.parse(Path(crypto.__file__).read_bytes())
    guards=[n for n in ast.walk(source) if isinstance(n,ast.If) and ast.unparse(n.test)=="spec.get('review_refusal')"]
    assert len(guards)==1 and not t.get('review_refusal')
    wrong=deepcopy(t);wrong['review_refusal']=t['inherited_reporting_seed_diagnostic_metadata']['review_refusal']
    with pytest.raises(ValueError,match='FACTUAL_DECLARED_REVIEW_ONLY_REFUSAL'):crypto.prove_review_refusal(wrong,{},Path('EXPLICIT_NONCANONICAL_UNUSED'))
@pytest.mark.parametrize('key,value',[('measured_closes',1384),('selected_session','2023-07-03'),('outer_sha256','f'*64),('financial_authority',True)])
def test_nonexact_target_refuses(key,value):
    t=deepcopy(r.fact()['target']);t[key]=value
    with pytest.raises(ValueError):r.validate(t)
@pytest.mark.parametrize('key,value',[('financial_resume_authorized',True),('maximum_parallel_financial_workers',1),('execution_mode','OWN_ADMITTED_FINANCIAL_CONTINUATION')])
def test_financial_request_refuses(key,value):
    t=r.fact()['target'];q=request(t);q[key]=value
    with pytest.raises(ValueError):r.require_request(q,t)
def test_economic_entry_is_closed(monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);t=r.fact()['target']
    with pytest.raises(ValueError,match='ONLY_READONLY_PREFLIGHT'):
        with r.entry_context(None,t,mode='economic',request=request(t)):pytest.fail('entered financial scope')
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_no_financial_import(name):
    assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
    with pytest.raises(ImportError):Fence().find_spec(name)

@pytest.mark.parametrize('scope',['target','request'])
def test_guard_removal_is_meaningful(monkeypatch,scope):
    t=deepcopy(r.fact()['target']);q=request(t)
    if scope=='target':t['measured_closes']=1384;label='REPORT25_ONLY_AUTHENTIC_UNADMITTED1383_FULL25';call=lambda:r.validate(t)
    else:q['financial_resume_authorized']=True;label='REPORT25_EXPLICIT_ZERO_FINANCIAL_REQUEST';call=lambda:r.require_request(q,t)
    with pytest.raises(ValueError):call()
    old=r.need
    monkeypatch.setattr(r,'need',lambda value,name:None if name==label else old(value,name))
    call()

@pytest.mark.parametrize('fail',[False,True])
def test_noncanonical_copy_expansion_and_rollback(tmp_path,monkeypatch,fail):
    root=tmp_path/'NONCANONICAL';root.mkdir();(root/'original').write_bytes(b'NONCANONICAL RESOURCE')
    manifest=r.loss.inventory(root)[0];expected=dict(manifest,**{'copy/a':manifest['original'],'copy/b':manifest['original']})
    def reader(physical,declared):
        assert declared==manifest
        def logical(n):
            if fail and n=='copy/b':raise ValueError('NONCANONICAL COPY READ FAULT')
            return physical('original')
        logical.representation=dict(copies=[dict(name=n) for n in ('copy/a','copy/b')],before_inventory=expected)
        return logical
    monkeypatch.setattr(r,'host_guard',lambda:None);monkeypatch.setattr(r.loss,'logical_members',reader);monkeypatch.setattr(r.loss,'RECEIPT','original')
    if fail:
        with pytest.raises(ValueError,match='NONCANONICAL COPY'):r.reconstruct(root,manifest)
        assert r.loss.inventory(root)[0]==manifest
    else:assert r.reconstruct(root,manifest)['copies']==2 and r.loss.inventory(root)[0]==expected

@pytest.mark.parametrize('error',[ValueError('NONCANONICAL_STATIC_GUARD'),ValueError('NONCANONICAL private value'),KeyError('missing_code_field')])
def test_admission_diagnostics_preserve_error_and_restore_hooks(tmp_path,monkeypatch,capsys,error):
    from types import SimpleNamespace
    import system_campaign_p07_fin326_requalified_parent as composite
    t=r.fact()['target'];path=tmp_path/'NONCANONICAL-request.json';path.write_text(json.dumps(request(t)))
    def original_admit(*a,**k):raise error
    module=SimpleNamespace(admit_partial=original_admit)
    def launch(args):return module.admit_partial(t)
    old=composite.applies;monkeypatch.setattr(r,'host_guard',lambda:None)
    with pytest.raises(type(error)) as caught:r.bind_launch(launch,module)(SimpleNamespace(arm='P07',request=path))
    assert caught.value is error and module.admit_partial is original_admit and composite.applies is old
    value=json.loads(capsys.readouterr().out);assert value['p07_readonly_stage']=='CRYPTO_ADMISSION'
    assert value['error_type']==type(error).__name__ and 'private value' not in json.dumps(value)
