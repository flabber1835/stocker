import ast,inspect,json,os,sys
from copy import deepcopy
from pathlib import Path
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p05-ctxs-own1175-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('RUNTIME18_V2_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p05_remaining_runtime_v2 as runtime
from system_campaign_financial_partial import root_spec
from forecast_tests.p05_remaining18.test_remaining18_origin_inventory_DATA import actual as actual19
@pytest.fixture(scope='module')
def packet_DTO():
    # Explicitly noncanonical input DTO conformance, not a hosted packet pass.
    # Parent is genuine FIN326; strict/accounting proofs are actual SOURCE331.
    parent,_,_=actual19.__wrapped__();spec=root_spec('P05',runtime.original.origin.data.own.ROOT)
    r=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/source331-source-snapshot/capture-P05-13482516435-001')
    manifest=json.loads((r/'authenticated-manifest.json').read_bytes())['members'];root=r/'verified-output'
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root.resolve()))
    def source(name):
        n='parent-preflight/'+name;raw=(root/n).read_bytes()
        assert dict(bytes=len(raw),sha256=runtime.sha(raw))==manifest[n]
        return raw
    origin=runtime.original.origin;api=origin.api_module.api(parent);material=origin.material(parent);hydrated=origin.api_module.original.hydration_name(parent)
    values={origin.data.CATALOG:runtime.encoded(origin.data.catalog(parent)),hydrated:runtime.encoded(material)}
    doc=api.document(parent,material,runtime.sha(values[hydrated]));values[origin.api_module.original.OVERLAY]=runtime.encoded(doc)
    values[origin.api_module.original.SOURCE_SCOPES]=runtime.encoded(api.source_scopes(parent,material,runtime.sha(runtime.encoded(doc)),runtime.sha(values[hydrated])))
    values[origin.api_module.QUALIFICATION]=runtime.encoded(dict(passed=True,packet_checks=36,only_terminal_field_changed=True,
        complete_terms_and_canonical_notional_verified=True,original_incomplete_guard_retained=True,
        wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,financial_sessions_advanced=0))
    values['strict-parent-preflight.json']=source('strict-parent-preflight.json');values['old-prefix-canonical-review.json']=source('old-prefix-canonical-review.json')
    provider=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p02-sequential-001/wwe-tko-suffix-002/evidence-001/verified/provider-source/SHARADAR_ACTIONS.zip')
    values['provider-source/SHARADAR_ACTIONS.zip']=provider.read_bytes()
    values['P05-retained18-provider-stage.json']=runtime.encoded(dict(passed=True,provider_sha256=runtime.sha(values['provider-source/SHARADAR_ACTIONS.zip']),
        original_provider_rows_verified=9,financial_sessions_advanced=0,original_stage_code_unchanged=True,metadata_authority_upgraded=False))
    proof=dict(schema='research.P05-own1175-retained18-source-preparation/1',passed=True,root_admission_sha256=origin.data.own.ROOT,
        parent_outer_sha256=parent['sha256'],parent_completed=1175,full_parent_inputs=19,declaration=runtime.original.preparation.declaration(spec),
        packet_checks=36,terms=18,financial_sessions_advanced=0,canonical_checkpoint_or_root_written=False,
        canonical_parent_unchanged=True,financial_request_authorized=False,original_future_prepare_and_qualify_code_unchanged=True,
        resources={n:dict(bytes=len(raw),sha256=runtime.sha(raw)) for n,raw in values.items()})
    return parent,spec,proof,values
def test_metadata_DTO_validator_requires_entire18_input_and36_flags(packet_DTO):
    parent,spec,proof,values=packet_DTO
    result=runtime.validate_preflight_packet(parent,spec,proof,values.__getitem__)
    assert result['passed'] and result['packet_checks']==36 and result['financial_sessions_advanced']==0
@pytest.mark.parametrize('key,value',[('packet_checks',35),('terms',17),('financial_sessions_advanced',1),('canonical_checkpoint_or_root_written',True),('canonical_parent_unchanged',False),('parent_outer_sha256','0'*64)])
def test_incomplete_or_different_preflight_header_refuses(packet_DTO,key,value):
    parent,spec,proof,values=packet_DTO;p=deepcopy(proof);p[key]=value
    with pytest.raises(ValueError):runtime.validate_preflight_packet(parent,spec,p,values.__getitem__)
@pytest.mark.parametrize('name',['P05-own1175-retained18-source-stock-cash-catalog.json','p05-retained18-input-qualification.json','strict-parent-preflight.json','provider-source/SHARADAR_ACTIONS.zip'])
def test_missing_mandatory_packet_resource_refuses(packet_DTO,name):
    parent,spec,proof,values=packet_DTO;p=deepcopy(proof);p['resources'].pop(name)
    with pytest.raises(ValueError):runtime.validate_preflight_packet(parent,spec,p,values.__getitem__)
def test_changed_actual_resource_hash_refuses_before_packet_validation(packet_DTO):
    parent,spec,proof,values=packet_DTO
    with pytest.raises(ValueError,match='ALL_ACTUAL_PREFLIGHT'):runtime.validate_preflight_packet(parent,spec,proof,lambda n:values[n]+b'corrupt DTO falsifier')
def test_packet_header_guard_removal_is_meaningful(packet_DTO,monkeypatch):
    parent,spec,proof,values=packet_DTO;p=deepcopy(proof);p['packet_checks']=35
    with pytest.raises(ValueError):runtime.validate_preflight_packet(parent,spec,p,values.__getitem__)
    need=runtime.need;monkeypatch.setattr(runtime,'need',lambda v,label:None if label=='P05_RUNTIME18_V2_EXACT_ACTUAL_PARENT_ZERO_ADVANCE_HOSTED36_PREPARATION_HEADER' else need(v,label))
    assert runtime.validate_preflight_packet(parent,spec,p,values.__getitem__)['passed']
def test_separate_explicit_request_gate_is_required(packet_DTO):
    _,spec,_,_=packet_DTO;d=runtime.declaration(spec)
    r=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,**{runtime.FIELD:{'P05':d}})
    assert runtime.selected(spec,r) and d['actual_hosted36_packet_checks_required_before_financial_entry'] is True
    del r[runtime.FIELD]['P05']['actual_hosted36_packet_checks_required_before_financial_entry']
    with pytest.raises(ValueError):runtime.selected(spec,r)
def test_closed_base_module_and_all_whole_bound_function_code_objects():
    runtime.qualified_base()
    for fn in (runtime.original.selected,runtime.original.expected_request,runtime.original.entry_context.__wrapped__,runtime.original.old_entry.__wrapped__,runtime.original.launch_context.__wrapped__,runtime.original.bind_launch):
        assert runtime.bind_function(fn).__code__ is fn.__code__
def test_origin_exception_recloses_original_advance_guard_without_financial_state(packet_DTO,monkeypatch):
    _,spec,_,_=packet_DTO;tree=ast.parse((C/'system_campaign_financial_resume.py').read_bytes());cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate']
    namespace={};exec(compile(ast.Module(body=[cls],type_ignores=[]),'<original-gate-method-identity-only>','exec'),namespace)
    Original=namespace['AdoptionGate'];Gate=runtime.gate_class(Original,Path('/out'),None,spec,module_path=C/'system_campaign_financial_resume.py')
    Base=Gate.__mro__[1]
    # Stub only the already-checked wrapper call; never run a writer or create CP.
    def failure(event,*a,**k):event.accepted=True;raise ValueError('explicit metadata-only origin failure stub')
    monkeypatch.setattr(Base,'write',failure);event=object.__new__(Gate);event.accepted=False
    with pytest.raises(ValueError):event.write()
    assert event.accepted is False and Gate.advance is Original.advance
    node,=[n for n in ast.walk(ast.parse(inspect.getsource(runtime.gate_class))) if isinstance(n,ast.ClassDef) and n.name=='Gate']
    fn,=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='write'];fn.body[0].handlers[0].body.pop(0)
    weakened={"Base":Base};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<one-acceptance-reset-removal-falsifier>','exec'),weakened)
    bad=object.__new__(weakened['Gate']);bad.accepted=False
    with pytest.raises(ValueError):bad.write()
    assert bad.accepted is True
def test_local_entry_still_refuses_before_financial_import_or_output(packet_DTO,tmp_path):
    _,spec,_,_=packet_DTO;r=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,**{runtime.FIELD:{'P05':runtime.declaration(spec)}})
    with pytest.raises(ValueError):
        with runtime.entry_context(None,spec,request=r,mode='economic',out=tmp_path):pass
    assert list(tmp_path.iterdir())==[]
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
