import ast,inspect,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p05-ctxs-own1175-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('RUNTIME18_CONFORMANCE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p05_remaining_runtime as runtime
from system_campaign_financial_partial import root_spec
@pytest.fixture(scope='module')
def spec():return root_spec('P05',runtime.origin.data.own.ROOT)
def request(spec):
    return dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        **{runtime.FIELD:{'P05':runtime.declaration(spec)}})
def module():
    return SimpleNamespace(EXECUTION_MODE=runtime.MODE,financial_inputs=lambda *a:None,qualified_overlay=lambda *a:None,review_adoption=lambda *a:None)
def test_one_actual_initial1175_full19_declaration_and_closed_prerequisites(spec):
    runtime.prerequisites();d=runtime.declaration(spec)
    assert runtime.initial(spec) and runtime.family(spec) and runtime.selected(spec,request(spec))
    assert d['current_full_inputs']==19 and d['selected_terms']==18 and d['initial_adoption_required'] is True and d['actual20_origin_required'] is False
    assert d['all94_original_observation_terms_retained'] is d['original128_evidence_limit_unchanged'] is True
@pytest.mark.parametrize('key,value',[('execution_mode','READONLY_FROZEN_SOURCE_WITNESSES'),('financial_resume_authorized',False),('readonly_partial_review',True),('readonly_source_witnesses',True)])
def test_no_other_mode_or_authority_can_enter_financial_generation(spec,key,value):
    r=request(spec);r[key]=value
    with pytest.raises(ValueError):runtime.selected(spec,r)
@pytest.mark.parametrize('key,value',[('current_full_inputs',18),('selected_terms',17),('current_root_admission_sha256','0'*64),('initial_adoption_required',False),('all94_original_observation_terms_retained',False)])
def test_modified_finite_financial_declaration_refuses(spec,key,value):
    r=request(spec);r[runtime.FIELD]['P05'][key]=value
    with pytest.raises(ValueError):runtime.selected(spec,r)
def test_old_financial_context_still_refuses_new_parent_without_explicit_new_binding(spec):
    with pytest.raises(ValueError,match='INITIAL_OWN1152_ONLY'):
        with runtime.origin.old_batch.entry_context(module(),spec):pass
def test_whole_old_context_binding_accepts_only_new_exact_metadata_declaration_and_restores(spec):
    m=module();before=dict(vars(m));inventory=runtime.origin.old_materials.inventory;pending=runtime.pending.for_parent
    with runtime.old_entry(m,spec,request(spec)):
        assert m.financial_inputs is not before['financial_inputs']
        assert runtime.origin.old_materials.inventory is not inventory
    assert vars(m)==before and runtime.origin.old_materials.inventory is inventory and runtime.pending.for_parent is pending
def test_unselected_old_context_never_gets_new_financial_exception(spec):
    m=module();before=dict(vars(m))
    with pytest.raises(ValueError):
        with runtime.old_entry(m,spec,{}):pass
    assert vars(m)==before
def test_new_explicit_financial_scope_guard_has_meaningful_removal_falsifier(spec,monkeypatch):
    r=request(spec);r['financial_resume_authorized']=False
    with pytest.raises(ValueError):runtime.selected(spec,r)
    old=runtime.need;monkeypatch.setattr(runtime,'need',lambda v,label:None if label=='P05_RUNTIME18_ONLY_SEPARATELY_DECLARED_EXACT_FINANCIAL_PHASE' else old(v,label))
    assert runtime.selected(spec,r)
def test_local_financial_entry_refuses_before_any_canonical_import(spec,tmp_path):
    with pytest.raises(ValueError):
        with runtime.entry_context(module(),spec,request=request(spec),mode='economic',out=tmp_path):pass
    assert list(tmp_path.iterdir())==[]
def test_complete_original_gate_methods_preserved_and_original_write_precedes_archive(spec):
    tree=ast.parse((C/'system_campaign_financial_resume.py').read_bytes())
    cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate']
    namespace=dict(deepcopy=deepcopy,Path=Path)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<whole-original-gate-class-for-method-identity-only>','exec'),namespace)
    old=namespace['AdoptionGate'];new=runtime.gate_class(old,Path('/out'),None,spec,module_path=C/'system_campaign_financial_resume.py')
    assert new.advance is old.advance and new.__enter__ is old.__enter__ and new.__exit__ is old.__exit__ and new.__init__ is old.__init__
    source=ast.parse(inspect.getsource(runtime.gate_class))
    fn,=[n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='write']
    calls=[ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)]
    assert 'super().write' in calls and 'record_origin' in calls
    assert fn.body[1].value.func.attr=='write' and fn.body[2].body[0].value.func.id=='record_origin'
def test_changed_live_original_gate_writer_refuses_before_subclassing(spec,monkeypatch):
    tree=ast.parse((C/'system_campaign_financial_resume.py').read_bytes());cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate']
    namespace={};exec(compile(ast.Module(body=[cls],type_ignores=[]),'<whole-original-gate-for-source-falsifier>','exec'),namespace)
    old=namespace['AdoptionGate'];old.write=lambda *a:None
    with pytest.raises(ValueError,match='FIVE_REAL_ORIGINAL_GATE_METHOD'):runtime.gate_class(old,Path('/out'),None,spec,module_path=C/'system_campaign_financial_resume.py')
    need=runtime.need;monkeypatch.setattr(runtime,'need',lambda v,label:None if label=='P05_RUNTIME18_ALL_FIVE_REAL_ORIGINAL_GATE_METHOD_CODE_SHAPES' else need(v,label))
    assert runtime.gate_class(old,Path('/out'),None,spec,module_path=C/'system_campaign_financial_resume.py').advance is old.advance
def test_no_temporary_book_copy_or_custom_canonical_state_writer_in_new_runtime():
    tree=ast.parse(Path(runtime.__file__).read_bytes());calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not any(n.endswith(('.restore','.write_checkpoint','.copytree','.main')) for n in calls)
    assert 'origin.origin' in calls and 'contextmanager' in calls
    assert not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and ast.unparse(t).startswith(("current[","parent[","neutral[")) for t in n.targets) for n in ast.walk(tree))
def test_original_legacy_function_bodies_unchanged_from_closed_source_preparation_qualification():
    q=json.loads((D/'P05-retained18-source-preparation-qualification.json').read_bytes())
    tree=ast.parse((C/'system_campaign_financial_resume.py').read_bytes())
    current={n.name:runtime.sha(ast.dump(n,include_attributes=False).encode()) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('launch','preflight','economic','review')}
    assert current==q['whole_legacy_host_launch_and_worker_functions_preserved']
def test_prior_same_generation_root_without_twentieth_input_never_counts_as_retained(spec):
    wrong=deepcopy(spec);wrong['root_admission_sha256']='0'*64
    assert not runtime.initial(wrong) and not runtime.family(wrong)
def test_generated_request_adds_complete_sources_and_true_initial_input_flag_without_replacing_others(spec,tmp_path,monkeypatch):
    for name in runtime.source_names():
        path=D/name
        if not path.is_file():path=C/name
        assert path.is_file(),name
        (tmp_path/name).write_bytes(path.read_bytes())
    monkeypatch.setattr(runtime,'HERE',tmp_path)
    old=request(spec);old.pop(runtime.FIELD)
    old['sources']={'untouched-frozen.py':'a'*64}
    old['arm_inputs']={'P05':dict(new_factual_overlay=False,restored_correlation=False),'P03':dict(new_factual_overlay=True,restored_correlation=False)}
    result=runtime.expected_request(lambda:deepcopy(old),execution_mode=runtime.MODE,selected_arms=('P05','P03'),root_lookup=lambda arm:spec)
    assert result['arm_inputs']['P05']==dict(new_factual_overlay=True,restored_correlation=False)
    assert result['arm_inputs']['P03']==old['arm_inputs']['P03'] and result['sources']['untouched-frozen.py']=='a'*64
    assert runtime.selected(spec,result)
    bad=deepcopy(old);bad['sources'][next(iter(runtime.Q_PINS))]='0'*64
    with pytest.raises(ValueError):runtime.expected_request(lambda:bad,execution_mode=runtime.MODE,selected_arms=('P05',),root_lookup=lambda arm:spec)
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
