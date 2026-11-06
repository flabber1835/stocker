"""Readonly bridge metadata and extension-seam DTO tests; no financial runtime."""
import ast,gzip,json,sys
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_REPORTING_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
C=Path(__file__).resolve().parents[2];P=Path(__file__).parent;D=P
sys.path[:0]=[str(P),str(D),str(C)]
import system_campaign_p06_retained_reporting as data
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')

@pytest.fixture
def raw_target():
    A=R/'financial330-source-snapshot/capture-P06-13482378564-001';O=A/'verified-output'
    raw=Path('\\\\?\\'+str((O/'book/checkpoint.json.gz').resolve())).read_bytes()
    m=json.loads((A/'authenticated-manifest.json').read_bytes())['members']
    assert dict(bytes=len(raw),sha256=data.sha(raw))==m['book/checkpoint.json.gz']
    cp=json.loads(gzip.decompress(raw));fact=data.fact()
    result={k:deepcopy(v) for k,v in fact['target'].items() if k!='base_sha256'}
    result.update(base=cp['base'],monthly_seed_root_admission_sha256=data.ROOT,archive_format='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1',
        financial_authority=False,financial_predecessor_admitted=False)
    return result

def request(target):
    return dict(execution_mode=data.MODE,financial_resume_authorized=False,readonly_partial_review=True,
        readonly_source_witnesses=False,maximum_parallel_financial_workers=0,**{data.FIELD:{'P06':data.declaration(target)}})

def test_only_exact_actual_full10_raw_metadata_gets_readonly_compatibility_tag(raw_target):
    before=data.encoded(raw_target);qualified=data.qualify_target(raw_target)
    assert data.encoded(raw_target)==before and 'retained_uncertainty_model' not in raw_target
    assert qualified['retained_uncertainty_model']==data.TAG and qualified[data.MARKER]['actual_input_schema']=='research.bounded-contingent-sensor-input/1'
    assert qualified[data.MARKER]['old_B19_codec_installed'] is False and qualified[data.MARKER]['prior_seed_rows']==6
    assert data.qualify_target(qualified)==qualified
    assert 'root_admission' not in qualified and qualified[data.MARKER]['financial_resume_authorized'] is False
    assert data.request_declaration(qualified,request(qualified))==qualified[data.MARKER]

@pytest.mark.parametrize('change',['outer','root','monthly_seed','count','descriptors','input','selected_file','source_epoch','admitted',
    'financial','predecessor','artifact','cursor','tag','marker'])
def test_foreign_or_admitted_financial_targets_refused(raw_target,change):
    t=deepcopy(raw_target)
    if change=='outer':t['outer_sha256']='0'*64
    elif change=='root':t['root_admission_sha256']='0'*64
    elif change=='monthly_seed':t['monthly_seed_root_admission_sha256']='0'*64
    elif change=='count':t['measured_closes']=1260
    elif change=='descriptors':t['repairs']=t['repairs'][:-1]
    elif change=='input':t['input_sha256']='0'*64
    elif change=='selected_file':t['selected_file']['sha256']='0'*64
    elif change=='source_epoch':t['base']['policy']='FOREIGN'
    elif change=='admitted':t['root_admission']={}
    elif change=='financial':t['financial_authority']=True
    elif change=='predecessor':t['financial_predecessor_admitted']=True
    elif change=='artifact':t['artifact_id']=1
    elif change=='cursor':t['selected_session']='2023-01-19'
    elif change=='tag':t['retained_uncertainty_model']='FOREIGN_SCHEMA'
    else:t[data.MARKER]=dict(financial_resume_authorized=True)
    with pytest.raises(ValueError):data.qualify_target(t)

@pytest.mark.parametrize('change',['not_qualified','financial_mode','financial_flag','readonly_flag','parallel','declaration'])
def test_readonly_request_is_explicit_and_cannot_authorize_advance(raw_target,change):
    t=data.qualify_target(raw_target);r=request(t)
    if change=='not_qualified':t=raw_target
    elif change=='financial_mode':r['execution_mode']='OWN_ADMITTED_FINANCIAL_CONTINUATION'
    elif change=='financial_flag':r['financial_resume_authorized']=True
    elif change=='readonly_flag':r['readonly_partial_review']=False
    elif change=='parallel':r['maximum_parallel_financial_workers']=1
    else:r[data.FIELD]['P06']['prior_seed_rows']=1
    with pytest.raises(ValueError):data.request_declaration(t,r)

def test_original_partial_retention_function_ASTs_remain_whole():
    import system_campaign_financial_partial as partial
    data.retained_source_contract(partial)
    expected=data.fact()['original_partial_retention_AST']
    actual={n.name:data.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(partial.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name in expected}
    assert actual==expected and set(actual)=={'financial_inputs','retention_tree','retained_models','model_context'}

def test_entry_patches_only_exact_model_seams_and_installs_only_ABMD_codec(monkeypatch,tmp_path,raw_target):
    import full_system_core
    import system_campaign_financial_partial as partial
    import system_campaign_p06_abmd_models as models
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    calls=[]
    def old_models(*a):calls.append('OLD_MODELS');return True
    @contextmanager
    def old_context(*a):calls.append('OLD_CONTEXT_ENTER');yield;calls.append('OLD_CONTEXT_EXIT')
    monkeypatch.setattr(partial,'retained_models',old_models);monkeypatch.setattr(partial,'model_context',old_context)
    monkeypatch.setattr(models,'validate_full',lambda root,parent,catalog:calls.append('FULL10') or dict(full_inputs=10))
    monkeypatch.setattr(data,'load',lambda path:dict(event='SYNTHETIC_EVENT'))
    monkeypatch.setattr(data,'evidence',lambda catalog:[])
    monkeypatch.setattr(data,'hydrate',lambda catalog,path:calls.append('READONLY_NATIVE_HYDRATION') or ('SYNTHETIC_NATIVE',{}))
    class SyntheticABMDCodec:
        def __init__(self,*a):calls.append('ABMD_CODEC_ONLY')
        def __enter__(self):calls.append('ABMD_ENTER')
        def __exit__(self,*a):calls.append('ABMD_EXIT')
    monkeypatch.setattr(data,'InputCodec',SyntheticABMDCodec)
    t=data.qualify_target(raw_target);parent=dict(not_canonical_checkpoint=True,sha256=t['outer_sha256'],repairs=t['repairs'])
    with data.entry_context(t,old=tmp_path,out=tmp_path,request=request(t)):
        assert partial.retained_models(tmp_path,parent,t) is True
        with partial.model_context(tmp_path,parent,t):calls.append('LEGACY_BODY')
        assert partial.retained_models(tmp_path,parent,dict(arm='P03')) is True
        with partial.model_context(tmp_path,parent,dict(arm='P03')):pass
    assert partial.retained_models is old_models and partial.model_context is old_context
    assert calls==['FULL10','READONLY_NATIVE_HYDRATION','ABMD_CODEC_ONLY','ABMD_ENTER','LEGACY_BODY','ABMD_EXIT',
        'OLD_MODELS','OLD_CONTEXT_ENTER','OLD_CONTEXT_EXIT']

def test_expected_request_adds_only_explicit_readonly_bridge_and_exact_source_pins(monkeypatch,raw_target):
    t=data.qualify_target(raw_target)
    monkeypatch.setattr(data,'source_names',lambda:(data.FACT,data.REQUEST))
    result=data.expected_request(lambda:dict(sources={}),execution_mode=data.MODE,selected_arms=['P06'],target_lookup=lambda arm:t)
    assert result[data.FIELD]=={'P06':data.declaration(t)}
    assert result['sources']=={data.FACT:data.FACT_SHA,data.REQUEST:data.REQUEST_SHA}
    result=data.expected_request(lambda:dict(sources={}),execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',selected_arms=['P06'],target_lookup=lambda arm:t)
    assert result[data.FIELD]=={}
    with pytest.raises(ValueError):data.expected_request(lambda:dict(sources={}),execution_mode=data.MODE,selected_arms=['P06'],target_lookup=lambda arm:raw_target)

def test_hosted_entry_fence_precedes_model_or_canonical_import(monkeypatch,raw_target):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        with data.entry_context(data.qualify_target(raw_target),old=None,out=None,request={}):pass

@pytest.mark.parametrize('guard',['target_scope','request_scope'])
def test_meaningful_reporting_authority_guard_removal_is_detected(raw_target,guard):
    tree=ast.parse(Path(data.__file__).read_bytes())
    name='validate_target' if guard=='target_scope' else 'request_declaration'
    label='P06_REPORT_READONLY_UNADMITTED_FULL10_TRANSPORT_SCOPE' if guard=='target_scope' else 'P06_REPORT_EXPLICIT_READONLY_REQUEST_DECLARATION'
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-reporting-authority-guard>','exec'),scope)
    if guard=='target_scope':
        raw_target['financial_authority']=True
        with pytest.raises(ValueError):data.validate_target(raw_target)
        assert scope[name](raw_target)['target']['outer_sha256']==data.OUTER
    else:
        target=data.qualify_target(raw_target);r=request(target);r['financial_resume_authorized']=True
        with pytest.raises(ValueError):data.request_declaration(target,r)
        assert scope[name](target,r)==target[data.MARKER]

@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)

def test_whole_original_bridge_AST_undo_changes_only_exact_case_literals_and_declaration_keys():
    source=Path(data.__file__).read_text();plan=json.loads((P/'REPORT333-whole-bridge-AST-undo-plan.json').read_bytes())
    for before,after in reversed(plan['replacements']):
        assert source.count(after)==1,(before,after)
        source=source.replace(after,before,1)
    original=(C/'system_campaign_p06_abmd_reporting.py').read_bytes()
    assert data.sha(original)==plan['original_sha256']
    assert ast.dump(ast.parse(source))==ast.dump(ast.parse(original))
