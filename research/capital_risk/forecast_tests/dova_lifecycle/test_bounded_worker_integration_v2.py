"""Whole worker orchestration on explicit noncanonical metadata and fake scopes."""
import ast,gzip,json,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_bounded_runtime_v2 import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_runtime_v2 as data

WORKER=Path(data.legacy.__file__).with_name('system_campaign_financial_resume.py')


def test_full_original_review_stays_inside_codec_scope_through_readonly_review(tmp_path,monkeypatch):
    raw=WORKER.read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review')
    fn=deepcopy(before);imports=[(i,n) for i,n in enumerate(fn.body) if isinstance(n,ast.ImportFrom)]
    assert [(n.module,[a.name for a in n.names]) for _,n in imports]==[
        ('system_campaign_financial_additional_sensor',['phase']),('system_campaign_financial_uncertainty',['uncertainty_phase'])]
    nested=[n for n in ast.walk(fn) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_uncertainty' and n.names[0].name=='review']
    assert len(nested)==1
    class BindImports(ast.NodeTransformer):
        removed=0
        def visit_ImportFrom(self,node):self.removed+=1;return None
    binding=BindImports();fn=binding.visit(fn);assert binding.removed==4
    # No canonical module is imported; this whole body receives fake scope taps.
    calls=[];active=[]
    @contextmanager
    def scopes(root,spec):
        active.extend(['ORIGINAL_B19_CODEC','TYPED_CODEC']);calls.append('ENTER')
        try:yield {'NONCANONICAL_REVIEW_DTO':True}
        finally:active.clear();calls.append('EXIT')
    def tap(name):
        def call(*a,**k):assert active==['ORIGINAL_B19_CODEC','TYPED_CODEC'];calls.append(name)
        return call
    marker=dict(NONCANONICAL_REVIEW_PARENT_DTO=True)
    name='NONCANONICAL-review-parent-metadata.json.gz';(tmp_path/name).write_bytes(gzip.compress(json.dumps(marker).encode()))
    spec=dict(arm='P03',root_admission_sha256=data.INITIAL,root_admission={'NONCANONICAL_TRANSPORT':True},
        selected_checkpoint=name,outer_sha256='SYNTHETIC_OUTER',selected_file={'sha256':'SYNTHETIC_RAW_PIN'})
    evidence=tmp_path/'NONCANONICAL_EVIDENCE';out=tmp_path/'NONCANONICAL_REVIEW_OUTPUT'
    def strict(value,target):assert value==marker and target is spec;return value
    scope=dict(hosted=lambda:None,additional_phase=lambda target:None,Path=lambda path:tmp_path if path=='/old' else Path(path),
        strict_parent=strict,json=json,gzip=gzip,uncertainty_phase=lambda target:data.legacy.uncertainty_phase(target),
        review_uncertainty=lambda *a,**k:data.legacy.review(*a,**k),readonly_review=tap('READONLY_CANONICAL_REVIEW'),
        verify_correlation=lambda *a:None,preserve_tails=lambda *a:None,verify_originals=lambda *a:None,
        sha256_file=lambda *a:'SYNTHETIC_RAW_PIN',need=data.need)
    # The unchanged worker also reads its tail metadata; this is a separate DTO.
    evidence.mkdir();(evidence/'resume-tail-preflight.json').write_text('{}')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-original-review-fake-scope-DATA-only>','exec'),scope)
    monkeypatch.setattr(data,'review_codecs',scopes);monkeypatch.setattr(data,'review',tap('BOUNDED_SUFFIX_REVIEW'))
    module=SimpleNamespace(financial_inputs=lambda *a:None,review=scope['review'],factual_overlay_needed=lambda *a:True)
    with data.entry_context(module,spec):module.review(evidence,out,spec)
    assert calls==['ENTER','BOUNDED_SUFFIX_REVIEW','READONLY_CANONICAL_REVIEW','EXIT'] and active==[]
    # Removing the external lifetime wrapper makes this same original body fail.
    scope['uncertainty_phase']=lambda target:True;scope['review_uncertainty']=tap('UNSCOPED_SUFFIX')
    with pytest.raises(AssertionError):scope['review'](evidence,out,spec)


def test_review_scope_validates_actual_evidence_inside_existing_model_context(monkeypatch):
    import full_system_core,system_campaign_financial_partial as partial
    marker={'NONCANONICAL_REVIEW_EVIDENCE_DTO':True,'repairs':['METADATA_ONLY']*16};calls=[];active=[]
    class FakePath:
        def __truediv__(self,name):return self
        def read_bytes(self):return b'NONCANONICAL_READONLY_METADATA_BYTES'
    root=FakePath()
    @contextmanager
    def context(where,current,target):
        assert where is root and current is marker and data.initial(target);active.append(True);calls.append('MODEL_CONTEXT')
        try:yield
        finally:active.clear()
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(data,'Path',lambda value:value)
    monkeypatch.setattr(data.origins,'strict_json',lambda raw:marker)
    monkeypatch.setattr(partial,'model_context',context)
    monkeypatch.setattr(data,'full_models',lambda *a:calls.append('FULL_INPUTS') if active else pytest.fail('CODEC_ALREADY_CLOSED'))
    monkeypatch.setattr(data,'typed',lambda *a:'NONCANONICAL_TYPED_METADATA')
    monkeypatch.setattr(data,'metadata',lambda:{'NONCANONICAL_ROOT_METADATA':True})
    monkeypatch.setattr(data.origins,'load',lambda *a:calls.append('AUTHENTIC_ORIGIN') if active else pytest.fail('CODEC_ALREADY_CLOSED'))
    with data.review_codecs(root,dict(arm='P03',root_admission_sha256=data.INITIAL)) as current:
        assert current is marker and active;calls.append('WHOLE_WORKER_REVIEW')
    assert calls==['MODEL_CONTEXT','FULL_INPUTS','AUTHENTIC_ORIGIN','WHOLE_WORKER_REVIEW'] and active==[]


def test_request_context_adds_exact_sources_and_preserves_original_initial_registry(monkeypatch):
    import system_campaign_financial_partial as partial
    seed=data.metadata();monkeypatch.setattr(partial,'root_spec',lambda arm,*pins:seed)
    old=data.legacy.own_policy_phase;calls=[]
    def original():
        calls.append('WHOLE_ORIGINAL_REQUEST');assert data.legacy.own_policy_phase(seed)==old(seed)
        assert data.legacy.own_unchanged_input_phase(seed) is False
        return dict(financial_resume_authorized=True,financial_source_changed=False,
            admitted_checkpoints={'P03':seed['outer_sha256']},sources={})
    module=SimpleNamespace(expected_request=original,EXECUTION_MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION',SELECTED_ARMS=('P03',))
    with data.request_context(module):
        value=module.expected_request()
        assert value['selected_bounded_models']=={'P03':data.declaration(seed)}
        assert value['sources']=={n:data.sha((data.HERE/n).read_bytes()) for n in data.source_names()}
    assert module.expected_request is original and data.legacy.own_policy_phase is old and calls==['WHOLE_ORIGINAL_REQUEST']


def test_request_bindings_restore_on_original_failure(monkeypatch):
    import system_campaign_financial_partial as partial
    seed=data.metadata();monkeypatch.setattr(partial,'root_spec',lambda arm,*pins:seed)
    def original():raise RuntimeError('NONCANONICAL_ABORT')
    module=SimpleNamespace(expected_request=original,EXECUTION_MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION',SELECTED_ARMS=('P03',))
    saved=data.legacy.own_policy_phase,data.legacy.own_unchanged_input_phase
    with pytest.raises(RuntimeError):
        with data.request_context(module):module.expected_request()
    assert saved==(data.legacy.own_policy_phase,data.legacy.own_unchanged_input_phase) and module.expected_request is original


def test_new_family_request_routes_metadata_without_inventing_old_registry_record(monkeypatch):
    import system_campaign_financial_partial as partial
    c=data.catalog();d=dict(filename=data.models.TYPED_SHA+'.json',sha256=data.models.TYPED_SHA,
        resume_session=c['parent_cursor'],predecessor_checkpoint_sha256=c['parent_inner_sha256'])
    dto=dict(NONCANONICAL_REQUEST_ROUTING_DTO=True,arm='P03',repairs=c['parent_descriptors']+[d],
        outer_sha256='SYNTHETIC_TRANSPORT_OUTER')
    monkeypatch.setattr(partial,'root_spec',lambda *a:dto)
    monkeypatch.setattr(data,'validate_request_spec',lambda value:data.declaration(value)
        if value.get('NONCANONICAL_REQUEST_ROUTING_DTO') is True else pytest.fail('FOREIGN_DTO'))
    def refuse(*a):raise AssertionError('NO_OLD_REGISTRY_PHASE_FOR_NEW_FAMILY')
    monkeypatch.setattr(data.legacy,'own_policy_phase',refuse)
    def original():
        assert data.legacy.own_policy_phase(dto) is None and data.legacy.own_unchanged_input_phase(dto) is True
        return dict(financial_resume_authorized=True,financial_source_changed=False,
            admitted_checkpoints={'P03':'SYNTHETIC_TRANSPORT_OUTER'},sources={})
    module=SimpleNamespace(expected_request=original,EXECUTION_MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION',SELECTED_ARMS=('P03',))
    with data.request_context(module):assert module.expected_request()['selected_bounded_models']=={'P03':data.declaration(dto)}


def test_readonly_target_requires_exact_captured_request_and_monthly_seed(tmp_path):
    seed=data.metadata();request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,
        financial_source_changed=False,selected_bounded_models={'P03':data.declaration(seed)},admitted_checkpoints={'P03':seed['outer_sha256']},
        sources={'system_campaign_bounded_sensor_runtime_v2.py':data.sha(Path(data.__file__).read_bytes())})
    raw=json.dumps(request,sort_keys=True).encode();(tmp_path/'request.json').write_bytes(raw)
    cp=dict(NONCANONICAL_TARGET_METADATA_DTO=True,sha256='TARGET',completed=480,source_cursor='2099-01-03',repairs=['METADATA_ONLY'],run={'input_sha256':'INPUT'})
    spec=dict(arm='P03',request_sha256=data.sha(raw),retained_uncertainty_model='research.leadership-branch-uncertainty-input/1',
        monthly_seed_root_admission_sha256=data.INITIAL,outer_sha256='TARGET',measured_closes=480,selected_session='2099-01-03',repairs=['METADATA_ONLY'],input_sha256='INPUT')
    assert data.reporting_contract(tmp_path,cp,spec)=={'retained_uncertainty_model':'research.leadership-branch-uncertainty-input/1'}
    wrong=deepcopy(spec);wrong['monthly_seed_root_admission_sha256']='FOREIGN'
    with pytest.raises(ValueError,match='CAPTURED_PREFIX_SEED'):data.reporting_contract(tmp_path,cp,wrong)
    (tmp_path/'request.json').write_bytes(raw+b' ')
    with pytest.raises(ValueError,match='ORIGINAL_REQUEST_BYTES'):data.reporting_contract(tmp_path,cp,spec)


def test_retained_family_does_not_enter_old_registry_for_outcome_flags():
    value=data.catalog();d=dict(filename=data.models.TYPED_SHA+'.json',sha256=data.models.TYPED_SHA,
        resume_session=value['parent_cursor'],predecessor_checkpoint_sha256=value['parent_inner_sha256'])
    spec=dict(NONCANONICAL_INPUT_FAMILY_DTO=True,arm='P03',repairs=value['parent_descriptors']+[d])
    def refuse(*a):raise AssertionError('OLD_REGISTRY_MUST_NOT_RECEIVE_NEW_FAMILY')
    module=SimpleNamespace(financial_inputs=refuse,review=refuse,factual_overlay_needed=refuse)
    with data.entry_context(module,spec):assert module.factual_overlay_needed(spec) is False
