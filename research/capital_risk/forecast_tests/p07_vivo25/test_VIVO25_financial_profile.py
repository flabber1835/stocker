"""Private request DTOs and source namespaces only; no launch or engine execution."""
import ast,json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from forecast_tests.p07_vivo25.test_VIVO25_data_models_api import actual,read,P,C,R
import system_campaign_p07_vivo_profile as profile
import system_campaign_p07_vivo_runtime as runtime
import system_campaign_p07_vivo_data as data

@pytest.fixture
def metadata_qualification(monkeypatch):
    """Explicitly noncanonical profile DTO; never written as a qualification."""
    raw=b'PRIVATE-REQUEST-METADATA-DTO-NOT-ACTUAL-QUALIFICATION'
    monkeypatch.setattr(runtime,'qualification',lambda:(raw,dict(private_metadata_dto=True)))
    return raw

def base_request():
    raw=read(R/'source335-source-snapshot/system-campaign-factual-request.json');value=json.loads(raw)
    value.update(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,
        readonly_source_witnesses=False,maximum_parallel_financial_workers=1,maximum_parallel_readonly_workers=0)
    value['arms']=['P07'];value['admitted_checkpoints']={'P07':data.OUTER}
    value['arm_inputs']={'P07':dict(new_factual_overlay=False,restored_correlation=False)}
    return value

def source_reader(name):
    if name==runtime.QUALIFICATION:return b'PRIVATE-REQUEST-METADATA-DTO-NOT-ACTUAL-QUALIFICATION'
    return (P/name if (P/name).exists() else C/name).read_bytes()

def generate(spec):
    return profile.expected_request(base_request,execution_mode=runtime.MODE,selected_arms=['P07'],
        root_lookup=lambda arm:spec,source_bytes=source_reader)

def test_financial_request_truthful_and_source_only_defaults_unchanged(actual,metadata_qualification):
    _,_,spec=actual;request=generate(spec)
    assert runtime.require_request(spec,request)
    assert request['execution_mode']==runtime.MODE and request['financial_resume_authorized'] is True
    assert request[profile.composite.SOURCE_FIELD]=={} and request[runtime.FIELD]['P07']==runtime.declaration(spec)
    assert request['arm_inputs']['P07']['new_factual_overlay'] is True
    with pytest.raises(ValueError,match='SOURCE_ONLY_REQUEST_NO_FINANCIAL_ENABLE'):profile.composite.request_only_source(request,spec)
    with pytest.raises(ValueError,match='FINANCIAL805_CONTINUATION_NOT_YET_QUALIFIED'):
        profile.composite.expected_request(base_request,execution_mode=runtime.MODE,selected_arms=['P07'],root_lookup=lambda arm:spec)

@pytest.mark.parametrize('mutation',range(17))
def test_truthful_financial_request_semantic_refusals(actual,metadata_qualification,mutation):
    _,_,spec=actual;r=generate(spec)
    if mutation==0:r['execution_mode']=profile.composite.SOURCE_MODE
    elif mutation==1:r['financial_resume_authorized']=False
    elif mutation==2:r['readonly_partial_review']=True
    elif mutation==3:r['readonly_source_witnesses']=True
    elif mutation==4:r[runtime.FIELD]={}
    elif mutation==5:r[runtime.FIELD]['P07']['old_committed_proof_rows']=824
    elif mutation==6:r[runtime.FIELD]['P07']['required_actual_neutral_inputs']=24
    elif mutation==7:r[runtime.FIELD]['P07']['source335_qualification_sha256']='0'*64
    elif mutation==8:r['admitted_checkpoints']['P07']='0'*64
    elif mutation==9:r['arm_inputs']['P07']['new_factual_overlay']=False
    elif mutation==10:r['maximum_parallel_financial_workers']=0
    elif mutation==11:r['maximum_parallel_financial_workers']=True
    elif mutation==12:r['maximum_parallel_financial_workers']=5
    elif mutation==13:r['arms']=[]
    elif mutation==14:r['maximum_parallel_readonly_workers']=1
    elif mutation==15:r['selected_p07_composite_source_bridges']={'P07':{'financial_authority':False}}
    else:r['arm_inputs']['P07']['restored_correlation']=True
    with pytest.raises((ValueError,KeyError)):runtime.require_request(spec,r)

def test_meaningful_truthful_financial_declaration_guard_removal(actual,metadata_qualification,monkeypatch):
    _,_,spec=actual;r=generate(spec);r[runtime.FIELD]['P07']['old_committed_proof_rows']=824
    with pytest.raises(ValueError,match='EXPLICIT_TRUTHFUL_QUALIFIED_DECLARATION'):runtime.require_request(spec,r)
    old=data.need
    def without(value,label):
        if label!='VIVO_FINANCIAL_PROFILE_EXPLICIT_TRUTHFUL_QUALIFIED_DECLARATION_REQUIRED':old(value,label)
    monkeypatch.setattr(data,'need',without);assert runtime.require_request(spec,r)

def test_original_metadata_validator_whole_AST_undo_and_actual805(actual,metadata_qualification):
    _,_,spec=actual;raw=Path(profile.uncertainty.__file__).read_bytes()
    old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_retained_admission_metadata']
    new=profile.metadata_tree(raw);imp,=[n for n in old.body if isinstance(n,ast.ImportFrom)]
    new.body.insert(old.body.index(imp),deepcopy(imp));assert ast.dump(old)==ast.dump(new)
    assert profile.validate_retained_metadata(spec)==dict(completed=1259,source_cursor='2022-12-30',rows=805,new_rows=21,retained_rows=784)

def test_composite_context_whole_AST_undo():
    raw=profile.frozen_source();old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='context']
    new=profile.context_tree(raw)
    profile.retained.models.replace_count(new,"('launch', 'preflight', 'economic', 'review')","('launch', 'preflight')",1,'TEST_CONTEXT_MODE_UNDO')
    assert ast.dump(new)==ast.dump(old)

def test_original_composite_admit_entire_code_object_bound_only_financial_predicate():
    # Inspect the finite binding source directly; never call artifact admission.
    fn=profile.finance_admit
    tree=ast.parse(Path(profile.__file__).read_bytes())
    binding=next(n for n in ast.walk(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='finance_admit'))
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='FunctionType')
    assert ast.unparse(binding.args[0])=='original.__code__'
    assert ast.unparse(binding.args[1])=='dict(original.__globals__, request_only_source=request_only_financial)'

def test_launch_adapter_accepts_only_original_composite_wrapper_and_keeps_closure():
    original=profile.composite.bind_launch(lambda args:'unexecuted-inner')
    result=profile.bind_launch(original);assert result.__closure__ is not None
    with pytest.raises(ValueError,match='LATE_BIND_ONLY_COMPLETE_FROZEN_COMPOSITE'):profile.bind_launch(lambda args:None)

def test_financial_source_route_unchanged_for_nonselected_request(actual,monkeypatch):
    _,_,spec=actual;seen=[]
    def old(original,**kwargs):seen.append(kwargs);return dict(original())
    monkeypatch.setattr(profile.composite,'expected_request',old)
    r=profile.expected_request(lambda:dict(sources={}),execution_mode='SOME_OTHER_MODE',selected_arms=[],root_lookup=lambda arm:spec)
    assert seen and r[runtime.FIELD]=={}

def test_no_local_financial_profile_entry():
    with pytest.raises(ValueError,match='HOSTED'):
        with profile.entry_context(None,None,mode='economic',request={}):pass
