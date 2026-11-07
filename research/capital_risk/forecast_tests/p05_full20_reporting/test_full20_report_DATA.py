"""Actual origin/transport DATA and context metadata; no MonthlyStats engine."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p05-fin340-full20-readonly-report-20261106');C=Path(__file__).resolve().parents[2]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P05_FULL20_REPORT_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(C)]
import system_campaign_p05_full20_reporting as r
import system_campaign_financial_partial as partial
import system_campaign_financial_resume as m
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
def read(p):return Path(p).read_bytes() if str(p).startswith('\\\\?\\') else Path('\\\\?\\'+str(Path(p).resolve())).read_bytes()
@pytest.fixture(scope='module')
def actual():
    capture=R/'financial340-P05-source-snapshot/capture-P05-13524003871-001';mf=json.loads(read(capture/'authenticated-manifest.json'))['members']
    root=Path('\\\\?\\'+str((capture/'verified-output').resolve()))
    def member(n):
        raw=read(root/n);assert dict(bytes=len(raw),sha256=r.sha(raw))==mf[n];return raw
    current=r.origin.actual_json(member('book/checkpoint.json.gz'))
    rawtarget=json.loads((D/'P05-FIN340-full20-reporting-target.json').read_bytes())
    return root,current,r.qualify_target(rawtarget),member
def request(target):return dict(execution_mode=r.MODE,financial_resume_authorized=False,readonly_partial_review=True,readonly_source_witnesses=False,
    maximum_parallel_financial_workers=0,**{r.FIELD:{'P05':r.declaration(target)}})
def test_exact_saved1196_target_has_no_financial_or_fake_model_tag(actual):
    root,current,target,member=actual;r.validate_target(target);r.request_declaration(target,request(target))
    assert len(target['repairs'])==20 and target['selected_session']=='2022-09-30' and target['measured_closes']==1196
    assert 'root_admission' not in target and 'retained_uncertainty_model' not in target
    assert target['monthly_seed_root_admission_sha256']==r.origin.data.own.ROOT
def test_actual_whole_current20_origin_and112_observer_before_cash_extraction(actual):
    root,current,target,member=actual;checked=r.full20(root,current,target)
    assert len(checked['material']['terms'])==18 and len(checked['cash_terms'])==14 and len(checked['scopes'])==1
    assert checked['neutral']['repairs']==current['repairs'] and checked['parent']['completed']==1175
def test_whole_original_input_monthly_and_four_m_AST_sources(actual):
    r.source_contract(partial,m)
    assert 'reproduce_reports' in r.fact()['original_partial_AST'] and 'monthly_reproduction' in r.fact()['original_partial_AST']
@pytest.mark.parametrize('key,value',[
    ('execution_mode','OWN_ADMITTED_FINANCIAL_CONTINUATION'),('financial_resume_authorized',True),
    ('readonly_partial_review',False),('readonly_source_witnesses',True),('maximum_parallel_financial_workers',1)])
def test_other_modes_authorities_or_financial_workers_refuse(actual,key,value):
    target=actual[2];bad=request(target);bad[key]=value
    with pytest.raises(ValueError):r.request_declaration(target,bad)
@pytest.mark.parametrize('key,value',[
    ('financial_authority',True),('financial_predecessor_admitted',True),('measured_closes',1199),
    ('selected_session','2022-10-05'),('outer_sha256','0'*64),('retained_uncertainty_model','research.leadership-branch-uncertainty-input/1')])
def test_changed_transport_or_tail_checkpoint_refuses(actual,key,value):
    bad=deepcopy(actual[2]);bad[key]=value
    with pytest.raises(ValueError):r.validate_target(bad)
def test_missing_qualified_marker_or_changed_declaration_refuses(actual):
    bad=deepcopy(actual[2]);bad.pop(r.MARKER)
    with pytest.raises(ValueError):r.request_declaration(bad,request(bad))
    bad=deepcopy(actual[2]);bad[r.MARKER]['full_inputs']=19
    with pytest.raises(ValueError):r.qualify_target(bad)
def test_wrong_actual_current_count_refuses_before_origin_or_financial_import(actual):
    root,current,target,member=actual;bad=deepcopy(current);bad['completed']=1199
    with pytest.raises(ValueError,match='NO_PROJECTION_OR_TAIL_SEED'):r.full20(root,bad,target)
def test_request_source_closure_and_false_new_overlay_flag(actual,tmp_path,monkeypatch):
    target=actual[2]
    for name in r.source_names():
        p=D/name if (D/name).is_file() else C/name;(tmp_path/name).write_bytes(p.read_bytes())
    monkeypatch.setattr(r,'HERE',tmp_path)
    original=dict(sources={'untouched.py':'a'*64},arm_inputs={'P05':dict(new_factual_overlay=True)})
    value=r.expected_request(lambda:deepcopy(original),execution_mode=r.MODE,selected_arms=['P05'],target_lookup=lambda arm:target)
    assert value[r.FIELD]=={'P05':r.declaration(target)} and value['arm_inputs']['P05']['new_factual_overlay'] is False
    assert value['sources']['untouched.py']=='a'*64 and set(r.source_names())<=set(value['sources'])
def test_report_context_aliases_and_inventory_restore_on_abort_without_calling_engine(actual,monkeypatch,tmp_path):
    root,current,target,member=actual
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    saved=partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with r.entry_context(m,target,mode='preflight',old=root,out=tmp_path,request=request(target)):
            assert partial.financial_inputs is m.financial_inputs and partial.financial_inputs is not saved[0]
            assert r.origin.old_materials.inventory is not saved[2]
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert (partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory)==saved and list(tmp_path.iterdir())==[]
def test_nonpreflight_context_refuses_before_any_patch(actual,monkeypatch,tmp_path):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    saved=partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory
    with pytest.raises(ValueError,match='ONLY_HOSTED_READONLY_PREFLIGHT'):
        with r.entry_context(m,actual[2],mode='economic',old=actual[0],out=tmp_path,request=request(actual[2])):pass
    assert (partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory)==saved
def test_different_live_input_context_alias_refuses_before_patch(actual,monkeypatch,tmp_path):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    def noncanonical_other_context(*a,**k):raise AssertionError('MUST_NOT_CALL_OTHER_CONTEXT')
    monkeypatch.setattr(m,'financial_inputs',noncanonical_other_context)
    before=partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory
    with pytest.raises(ValueError,match='UNWRAPPED_ORIGINAL_INPUT_CONTEXT_ALIAS'):
        with r.entry_context(m,actual[2],mode='preflight',old=actual[0],out=tmp_path,request=request(actual[2])):pass
    assert (partial.financial_inputs,m.financial_inputs,r.origin.old_materials.inventory)==before
def test_complete_origin_visitor_precedes_original_cash_context_in_wrapper_AST():
    tree=ast.parse(Path(r.__file__).read_bytes());entry=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='entry_context')
    wrapper=next(n for n in entry.body if isinstance(n,ast.FunctionDef) and n.name=='financial_inputs')
    calls=[ast.unparse(n) for n in wrapper.body]
    assert next(i for i,v in enumerate(calls) if v.startswith('full20('))<next(i for i,v in enumerate(calls) if v.startswith('with prior_partial('))
    assert not any(isinstance(n,ast.ImportFrom) and n.module and 'runtime_v3' in n.module for n in ast.walk(tree))
    assert not any(isinstance(n,ast.Call) and ast.unparse(n.func).endswith(('.main','.restore','.write_checkpoint')) for n in ast.walk(tree))
def test_readonly_request_guard_removal_is_meaningful(actual):
    target=actual[2];bad=request(target);bad['financial_resume_authorized']=True
    with pytest.raises(ValueError):r.request_declaration(target,bad)
    tree=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='request_declaration')
    stmt=next(n for n in tree.body if isinstance(n,ast.Expr) and 'P05_REPORT20_EXPLICIT_REPORT_ONLY_ZERO_FINANCIAL_WORKER_REQUEST' in ast.unparse(n))
    tree.body[tree.body.index(stmt)]=ast.Pass();ns=dict(vars(r));exec(compile(ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[])),'<removed-report-only-request-guard>','exec'),ns)
    assert ns['request_declaration'](target,bad)==r.declaration(target)
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
    assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
    with pytest.raises(ImportError):Fence().find_spec(name)
