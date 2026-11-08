"""Whole-source adapters and metadata guards; no local canonical execution."""
import ast,sys,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_RUNTIME_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_bounded_sensor_runtime_v2 as data

@pytest.mark.parametrize('name',['run_retained','review_retained'])
def test_whole_original_reuse_with_exact_import_binding_AST_undo(name):
    raw=Path(data.legacy.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
    after=data.body_tree(name)
    if name=='run_retained':
        for index,node in enumerate(before.body):
            if isinstance(node,ast.ImportFrom) and node.module in ('system_campaign_financial_branches','system_campaign_uncertainty_archive'):
                after.body.insert(index,deepcopy(node))
    else:
        statement=next(n for n in after.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches')
        statement.names.insert(1,ast.alias(name='validate_input',asname=None))
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

def test_exact_selected_initial_and_real_declared_typed_family_metadata_only():
    c=data.catalog();initial=dict(arm='P03',root_admission_sha256=data.INITIAL)
    assert data.initial(initial) and data.selected(initial)
    assert data.declaration(initial)['owned_or_ordered_right_valuation_authorized'] is False
    descriptor=dict(filename=data.models.TYPED_SHA+'.json',sha256=data.models.TYPED_SHA,
        resume_session=c['parent_cursor'],predecessor_checkpoint_sha256=c['parent_inner_sha256'])
    # This transport-shaped DTO has no financial state/journals/schema.
    retained=dict(noncannonical_metadata=True,arm='P03',repairs=c['parent_descriptors']+[descriptor])
    assert data.selected(retained) and not data.initial(retained)
    retained['repairs'][15]['sha256']='0'*64;assert not data.selected(retained)
    assert not data.selected(dict(initial,arm='P07'))

@pytest.mark.parametrize('name',['run_retained','review_retained'])
def test_binding_sets_cannot_override_guards_or_omit_required_bindings(name):
    with pytest.raises(ValueError,match='ONLY_COMPLETE_EXPLICIT_BINDING_SET'):data.bound_body(name,{'need':lambda *a:None})

def test_worker_entry_restores_every_binding_on_exception_and_delegates_unselected():
    import system_campaign_financial_partial as partial
    spec=dict(arm='P03',root_admission_sha256=data.INITIAL)
    module=SimpleNamespace(financial_inputs=lambda *a:None,review=lambda *a:None,factual_overlay_needed=lambda *a:True)
    saved=(data.legacy.run,data.legacy.review,data.legacy.uncertainty_phase,partial.retained_models,partial.model_context,
        module.financial_inputs,module.review,module.factual_overlay_needed)
    with pytest.raises(RuntimeError):
        with data.entry_context(module,spec):
            assert data.legacy.uncertainty_phase(spec)
            assert module.financial_inputs is not saved[-3]
            raise RuntimeError('SYNTHETIC_ABORT')
    assert saved==(data.legacy.run,data.legacy.review,data.legacy.uncertainty_phase,partial.retained_models,partial.model_context,
        module.financial_inputs,module.review,module.factual_overlay_needed)
    with data.entry_context(module,dict(arm='P05')):assert module.financial_inputs is saved[-3]

@pytest.mark.parametrize('target',['run','review','seed','review_codecs'])
def test_hosted_guard_precedes_all_financial_imports(monkeypatch,target):
    import full_system_core
    def refuse():raise ValueError('LOCAL_NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='LOCAL_NOT_HOSTED'):
        if target=='run':data.run(None,None,None,None,None,None,spec={},old=None)
        elif target=='review':data.review(None,None,None,spec={},old=None)
        elif target=='seed':data.seed(None,None,{})
        else:
            with data.review_codecs(None,{}):pass

def test_guarded_interpretation_sources_remain_exact():
    c=data.catalog();root=Path(data.__file__).parent
    assert len(c['input_semantics_sources'])==9
    assert all(data.sha((root/n).read_bytes())==pin for n,pin in c['input_semantics_sources'].items())

def test_four_shared_worker_function_ASTs_unchanged():
    source=Path(data.legacy.__file__).with_name('system_campaign_financial_resume.py').read_bytes()
    expected=dict(preflight='fa2f6f19d53137596c3cc96575f19e610c32bd93bdade3dc55a48c764e1ce2b2',
        economic='cb10dbe24ce57173da398097a359f5b3418c30c68618375db6e22a269e8250f9',
        review='1306cc4b8378c3c48332fbfd625fc6d36306f1211f4032bc394f609eddc5a734',
        launch='9e6c1f8b7841c58f7e4972299bc928d170c906e0b2a44d98ceb5b9872d387b94')
    actual={n.name:data.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(source).body
            if isinstance(n,ast.FunctionDef) and n.name in expected}
    assert actual==expected

def test_removing_source_guard_accepts_a_broken_original_archive_guard(tmp_path,monkeypatch):
    raw=Path(data.legacy.__file__).read_bytes()
    source=b'actual.name == original.name and actual.read_bytes() == original.read_bytes()'
    assert raw.count(source)==1
    bad=tmp_path/'foreign-source-metadata.txt';bad.write_bytes(raw.replace(source,b'True',1))
    monkeypatch.setattr(data.legacy,'__file__',str(bad))
    with pytest.raises(ValueError,match='ENTIRE_ORIGINAL_RETAINED_SOURCE'):data.body_tree('review_retained')
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='body_tree')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='BOUNDED_RUNTIME_ENTIRE_ORIGINAL_RETAINED_SOURCE' for v in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-source-guard-AST-only>','exec'),scope)
    changed=scope['body_tree']('review_retained')
    call=next(n for n in ast.walk(changed) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='FINANCIAL_RETAINED_PROOF_EVENT_GZIP_NAME_AND_BYTES_PRESERVED' for v in n.args))
    assert isinstance(call.args[0],ast.Constant) and call.args[0].value is True

def test_reporting_only_exposes_actual_captured_financial_declaration():
    seed=data.metadata();declared=data.declaration(seed)
    request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,financial_source_changed=False,
        selected_bounded_models={'P03':declared},admitted_checkpoints={'P03':seed['outer_sha256']},
        sources={'system_campaign_bounded_sensor_runtime_v2.py':data.sha(Path(data.__file__).read_bytes())})
    assert data.report_declaration(request,'P03')==dict(retained_uncertainty_model='research.leadership-branch-uncertainty-input/1')
    assert data.report_declaration(request,'P05') is None
    wrong=deepcopy(request);wrong['admitted_checkpoints']['P03']='0'*64
    with pytest.raises(ValueError):data.report_declaration(wrong,'P03')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
