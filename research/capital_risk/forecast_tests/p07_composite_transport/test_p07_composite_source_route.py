"""Portable finite source-transport regression; no canonical financial imports."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
T=Path(__file__).parent
C=T.parents[1]
if not (C/'system_campaign_financial_partial.py').exists():
    C=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
sys.path[:0]=[str(T),str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_COMPOSITE_PORTABLE_METADATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_fin326_requalified_parent as m
import system_campaign_financial_partial as partial
def remove_guard(name,label):
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value==label for x in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    change=Remove();fn=ast.fix_missing_locations(change.visit(fn));assert change.count==1
    scope=dict(vars(m));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-source-only-metadata-guard>','exec'),scope)
    return scope[name]
@pytest.fixture
def root():return partial.root_spec('P07',m.ROOT_SHA)
def request(root):
    return dict(execution_mode=m.SOURCE_MODE,readonly_source_witnesses=True,financial_resume_authorized=False,
        readonly_partial_review=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=2,
        arms=['P06','P07'],admitted_checkpoints={'P07':root['outer_sha256']},
        arm_inputs={'P07':dict(new_factual_overlay=False,restored_correlation=False)},
        **{m.SOURCE_FIELD:{'P07':m.source_declaration(root)}})
def source_bytes(name):
    p=Path(m.__file__).parent/name
    return p.read_bytes() if p.exists() else (C/name).read_bytes()
def test_complete_old_transport_module_AST_undo():
    plan=json.loads((T/'P07-composite-whole-source-AST-undo-plan.json').read_bytes())
    original=(C/plan['original_file']).read_bytes();assert m.sha(original)==plan['original_sha256']
    new=Path(m.__file__).read_text();assert new.endswith(plan['extra']);new=new[:-len(plan['extra'])]
    for item in reversed(plan['changes']):
        assert new.count(item['replacement'])==1
        new=new.replace(item['replacement'],item['original'],1)
    assert ast.dump(ast.parse(new))==ast.dump(ast.parse(original))
def test_actual_root_uses_failed_original_and_separate_positive_review(root):
    target,review=m.validated(root)
    assert target['receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED'
    assert target['prior_stops']['worker']['exit_code']==target['prior_stops']['reviewer']['exit_code']==1
    assert review['prior_stops']['repair_reviewer']['exit_code']==0
    assert m.sha(m.encoded(target))==m.QUARANTINE_SHA
    assert m.accounting_review(root)==('stopped-review/core-review.json',review['core_review_sha256'])
def test_full24_and805_source_declaration_never_installs_certificate_factory(root):
    d=m.source_declaration(root)
    assert (d['completed'],d['full_input_descriptors'],d['committed_proof_rows'])==(1259,24,805)
    assert d['certificate_factory_installed'] is d['financial_authority'] is d['new_input_adoption'] is False
    assert m.request_only_source(request(root),root)==d
def test_existing_full24_lifecycle_route_remains_selected_in_source_mode(root):
    import system_campaign_p07_abmd_lifecycle as lifecycle
    assert lifecycle.selected(root) and lifecycle.valid_retained(root)
    phase=lifecycle.phase(root)
    assert (phase['completed'],phase['proof_rows'],phase['proof_new_rows'],phase['proof_retained_rows'])==(1259,805,21,784)
@pytest.mark.parametrize('field,value',[('execution_mode','OWN_ADMITTED_FINANCIAL_CONTINUATION'),('financial_resume_authorized',True),
    ('maximum_parallel_financial_workers',1),('readonly_source_witnesses',False),('readonly_partial_review',True)])
def test_source_only_authority_refuses_financial_modes(root,field,value):
    malformed=request(root);malformed[field]=value
    with pytest.raises(ValueError,match='SOURCE_ONLY_REQUEST_NO_FINANCIAL_ENABLE'):m.request_only_source(malformed,root)
def test_source_only_guard_removal_has_meaningful_financial_flag_falsifier(root):
    malformed=request(root);malformed['financial_resume_authorized']=True
    with pytest.raises(ValueError):m.request_only_source(malformed,root)
    assert remove_guard('request_only_source','P07_COMPOSITE_EXPLICIT_EXACT_SOURCE_ONLY_REQUEST_NO_FINANCIAL_ENABLE')(malformed,root)['committed_proof_rows']==805
def test_expected_source_closure_and_financial_generation_refusal(root):
    original=lambda:dict(sources={})
    value=m.expected_request(original,execution_mode=m.SOURCE_MODE,selected_arms=('P06','P07'),root_lookup=lambda arm:root,source_bytes=source_bytes)
    assert value[m.SOURCE_FIELD]=={'P07':m.source_declaration(root)}
    assert value['sources'][Path(m.__file__).name]==m.sha(Path(m.__file__).read_bytes())
    with pytest.raises(ValueError,match='CONTINUATION_NOT_YET_QUALIFIED'):
        m.expected_request(original,execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',selected_arms=('P07',),root_lookup=lambda arm:root,source_bytes=source_bytes)
@pytest.mark.parametrize('mode',['launch','preflight'])
def test_hooks_restore_after_original_body_abort(root,monkeypatch,mode):
    import system_campaign_financial_requalified_parent as old
    import full_system_core
    monkeypatch.setattr(m.quarantine,'launcher_guard',lambda:None);monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    before={name:getattr(old,name) for name in ('applies','admit','accounting_review')}
    with pytest.raises(ValueError,match='EXPLICIT_ABORT'):
        with m.context(root,mode=mode):
            assert old.applies(root) and old.accounting_review(root)==m.accounting_review(root)
            raise ValueError('EXPLICIT_ABORT')
    assert all(getattr(old,name) is value for name,value in before.items())
def test_worker_source_context_refuses_economic_mode(root,monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    with pytest.raises(ValueError,match='PREFLIGHT_ONLY'):
        with m.source_context(None,root,mode='economic',request=request(root)):pytest.fail('unreachable')
def test_source_phase_guard_removal_exposes_wrong_runtime805_scope(root,monkeypatch):
    import full_system_core
    import system_campaign_p07_abmd_lifecycle as lifecycle
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    wrong=dict(lifecycle.phase(root),proof_rows=784);monkeypatch.setattr(lifecycle,'phase',lambda spec:wrong)
    value=request(root)
    with pytest.raises(ValueError,match='FULL24_AND805_LIFECYCLE_PHASE'):
        with m.source_context(None,root,mode='preflight',request=value):pytest.fail('unreachable')
    with remove_guard('source_context','P07_COMPOSITE_EXACT_SOURCE_ONLY_FULL24_AND805_LIFECYCLE_PHASE')(None,root,mode='preflight',request=value):assert True
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_canonical_import_fences(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
