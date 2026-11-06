"""Pure DATA/AST and opaque mock seams; no synthetic canonical checkpoint exists."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).parent;C=Path(__file__).resolve().parents[2]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('THOR17_PRIVATE_QUALIFICATION_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(P),str(C)]
import system_campaign_p03_thor_data as data
import system_campaign_p03_thor_api as api
import system_campaign_p03_thor_runtime as runtime
def ext(p):return Path(p) if str(p).startswith('\\\\?\\') else Path('\\\\?\\'+str(Path(p).resolve()))
def function(raw,name):return next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
def remove(module,name,label):
    fn=function(Path(module.__file__).read_bytes(),name)
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in n.value.args):
                self.hits+=1;return None
            return self.generic_visit(n)
    changed=Remove();fn=ast.fix_missing_locations(changed.visit(fn));assert changed.hits==1
    namespace=dict(vars(module));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<one-removed-private-DATA-guard>','exec'),namespace)
    return namespace[name]
@pytest.fixture(scope='module')
def actual():
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P03',data.ROOT)
    R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
    A=R/'financial324-source-snapshot/capture-P03-13476494369-001'
    if not (A/'authenticated-manifest.json').exists():pytest.skip('private authenticated actual financial DATA unavailable; no fixture replacement fabricated')
    members=json.loads(ext(A/'authenticated-manifest.json').read_bytes())['members']
    def member(name):
        raw=ext(A/'verified-output'/name).read_bytes();assert dict(bytes=len(raw),sha256=data.sha(raw))==members[name];return raw
    raw=member(spec['selected_checkpoint']);assert dict(bytes=len(raw),sha256=data.sha(raw))==spec['selected_file']
    return dict(root=ext(A/'verified-output'),parent=json.loads(gzip.decompress(raw)),spec=spec,member=member)
def test_actual_source_bound_single_THOR_common_cash_and_all128_members():
    value=data.catalog();term,=value['terms'];assert data.validate(value)
    assert value['selected_source_indices']==[5] and len(value['source_data']['payload']['terms'])==128
    assert term['identity_witness']['issuer_id']=='SEC_UNKNOWN:'+data.SID and term['identity_witness']['security_type_eligible']=='0'
    assert term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' and term['added']['cash_per_share']==68.
    assert term['last_trading_session']=='2020-01-22' and term['added']['session']==term['native_session']=='2020-01-23'
    assert data.primary_fact()['exact_legal_effective_timestamp'] is None
def test_original_source_binding_AST_undo_only_one_schema_and_lifted_scope_import():
    raw=Path(data.cash.__file__).read_bytes();old=function(raw,'source_binding');new=data.source_tree(raw)
    site,=[n for n in ast.walk(new) if isinstance(n,ast.Constant) and n.value=='research.independent-forward-source-DATA-validation/2']
    site.value='research.independent-frozen-source-data-validation/1';new.body.insert(0,deepcopy(old.body[0]))
    assert ast.dump(new)==ast.dump(old)
    with pytest.raises(ValueError):data.source_tree(raw+b'\n# changed\n')
@pytest.mark.parametrize('change',['cash','native_cash','native_date','source_hash','source_scope','qualification','selected_index','positions',
    'issuer','eligible','preopen','last_trade','currency','primary_pin','parent','adopted_flag'])
def test_whole_original_cash_guards_and_new_exact_fact_refuse_corrupt_metadata(change):
    v=deepcopy(data.catalog());t=v['terms'][0]
    if change=='cash':t['added']['cash_per_share']=67.
    elif change=='native_cash':t['native']['cash_per_share']=68.
    elif change=='native_date':t['native_session']='2020-01-22'
    elif change=='source_hash':t['source_capture']['payload_sha256']='0'*64
    elif change=='source_scope':v['source_data']['payload']['scope']['terms'].pop()
    elif change=='qualification':v['source_data']['qualification']['passed']=False
    elif change=='selected_index':v['selected_source_indices']=[6]
    elif change=='positions':t['parent_positions']=[{'explicitly_noncanonical_metadata_DTO':True}]
    elif change=='issuer':t['identity_witness']['issuer_id']='SEC:1609727'
    elif change=='eligible':t['identity_witness']['security_type_eligible']='1'
    elif change=='preopen':t['preopen_completion_confirmed']=False
    elif change=='last_trade':t['last_trading_session']='2020-01-23'
    elif change=='currency':t['primary_extraction']['cash_currency']='EUR'
    elif change=='primary_pin':t['primary_extraction']['qualified_preopen_fact_sha256']='0'*64
    elif change=='parent':v['parent_outer_sha256']='0'*64
    elif change=='adopted_flag':v['canonical_financial_source_changed']=True
    with pytest.raises(ValueError):data.validate(v)
def test_exact_qualified_source_generation_guard_has_meaningful_removal():
    v=deepcopy(data.catalog());v['source_data']['qualification']['tests']['meaningful_guard_removals']=0
    with pytest.raises(ValueError,match='EXACT_INDEPENDENT_SOURCE327_QUALIFICATION'):data.source_binding(v)
    fn=remove(data,'source_binding','THOR_EXACT_INDEPENDENT_SOURCE327_QUALIFICATION_BYTES')
    assert fn(v)[2]['tests']['meaningful_guard_removals']==0
def test_primary_semantic_guard_has_meaningful_removal(tmp_path,monkeypatch):
    value=deepcopy(data.primary_fact());value['preopen_completion_confirmed']=False
    raw=data.encoded(value);(tmp_path/data.PRIMARY).write_bytes(raw)
    monkeypatch.setattr(data,'HERE',tmp_path);monkeypatch.setattr(data,'PRIMARY_SHA',data.sha(raw))
    with pytest.raises(ValueError,match='COMMON_CASH_AND_PAST_TENSE'):data.primary_fact()
    assert remove(data,'primary_fact','THOR_COMMON_CASH_AND_PAST_TENSE_ISSUER_PUBLICATION_BEFORE_OPEN_ONLY')()['preopen_completion_confirmed'] is False
def test_actual_parent_full16_and_committed49_seed_axis_without_restoration(actual):
    assert data.parent_contract(actual['parent'],actual['spec'])
    import system_campaign_financial_branches as branch
    rows=branch.seed(actual['root'],actual['parent']);raw=actual['member']('uncertainty-certificate.jsonl')
    assert len(rows)==49 and len(raw.splitlines())==63
    assert all(json.loads(v)['session']>actual['parent']['source_cursor'] for v in raw.splitlines()[49:])
    assert rows[-1]['next_state_sha256']==actual['parent']['run']['state_sha256']
def test_parent_commitment_guard_has_meaningful_removal(actual):
    malformed=deepcopy(actual['parent']);malformed['run']['input_sha256']='0'*64
    with pytest.raises(ValueError,match='ONLY_ACTUAL_OWN503'):data.parent_contract(malformed,actual['spec'])
    assert remove(data,'parent_contract','THOR_ONLY_ACTUAL_OWN503_FULL16_PARENT_ALL_COMMITMENTS')(malformed,actual['spec'])
def test_full_remaining_ordinary_AST_undo_keeps_all_original_B19_and_ordinary_guards():
    raw=Path(api.original.__file__).read_bytes();old=function(raw,'remaining_ordinary_terms');new=api.remaining_tree(raw)
    a,=[n for n in ast.walk(old) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'"]
    b,=[n for n in ast.walk(new) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'"]
    assert ast.unparse(b.body[1].test)=="doc['schema'] == DOVA_SCHEMA" and ast.dump(b.body[1].orelse[0])==ast.dump(a.body[1])
    b.body=deepcopy(a.body);assert ast.dump(old)==ast.dump(new)
    with pytest.raises(ValueError):api.remaining_tree(raw+b'\n')
def test_api_complete_original_code_objects_only_concrete_clock_and_selected_term(actual):
    value=api.api(actual['parent'],actual['spec'])
    for name in api.FUNCTIONS:
        actual=getattr(value,name);whole=actual.__wrapped__ if name=='hydrate' else actual
        assert whole.__code__ is getattr(api.original,name).__code__
    codec,catalog,terms=value.selected('P03',cursor='2019-12-31');assert terms==data.catalog()['terms']
    assert codec.catalog_sha==data.sha(data.encoded(data.catalog())) and catalog==data.CATALOG
    with pytest.raises(ValueError):value.selected('P03',cursor='2020-01-31')
    with pytest.raises(ValueError):value.selected('P05',cursor='2019-12-31')
def test_calendar_retains_original_policy_and_exact_next_frozen_session():
    t=data.catalog()['terms'][0];api.completion_session(t,['2020-01-21','2020-01-22','2020-01-23','2020-01-24'])
    with pytest.raises(ValueError,match='EXISTING_CALENDAR_EXACT_NEXT'):api.completion_session(t,['2020-01-21','2020-01-22','2020-01-24'])
    with pytest.raises(ValueError):api.completion_session(t,['2020-01-21','2020-01-22','2020-01-22','2020-01-23'])
def test_calendar_guard_removal_has_meaningful_failure():
    t=data.catalog()['terms'][0];axis=['2020-01-21','2020-01-22','2020-01-24']
    with pytest.raises(ValueError):api.completion_session(t,axis)
    assert remove(api,'completion_session','THOR_API_EXISTING_CALENDAR_EXACT_NEXT_FROZEN_SESSION_AFTER_LAST_TRADE')(t,axis) is None
def test_exclusive_original_qualifier_save_has_one_distinct_stage_name(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(api.original,'save',lambda path,value:calls.append((path,value)))
    q=dict(passed=True,financial_sessions_advanced=0)
    api.qualifier_save(tmp_path/'future-input-qualification.json',q)
    assert calls==[(tmp_path/api.QUALIFICATION,q)]
    api.qualifier_save(tmp_path/'other.json',q);assert calls[-1][0]==tmp_path/'other.json'
    with pytest.raises(ValueError):api.qualifier_save(tmp_path/'future-input-qualification.json',dict(passed=True,financial_sessions_advanced=1))
def test_whole_original_adoption_AST_undo_only_one_filename_entry():
    raw=Path(runtime.uncertainty.__file__).read_bytes();before=function(raw,'paused_own_adoption');after=runtime.adoption_tree(raw)
    mapping=next(n.value for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    assert mapping.keys[-1].value==api.DIRECTORY and mapping.values[-1].value==api.OVERLAY
    mapping.keys.pop();mapping.values.pop();assert ast.dump(before)==ast.dump(after)
    with pytest.raises(ValueError):runtime.adoption_tree(raw+b'\n')
@pytest.mark.parametrize('name',['run','review'])
def test_complete_existing_typed_runtime_code_objects_only_seed_binding(name):
    opaque_seed=lambda *args:None
    before=getattr(runtime.typed,name);after=runtime.bound_runtime(name,opaque_seed)
    assert before.__code__ is after.__code__ and before.__defaults__==after.__defaults__
    assert {key for key in before.__globals__ if after.__globals__[key] is not before.__globals__[key]}=={'seed'}
def test_request_declaration_names_real16_and_unknown_future_neutral_only(actual):
    declared=runtime.declaration(actual['spec'])
    assert declared['original_inputs']==16 and declared['required_actual_neutral_inputs']==17
    assert declared['actual_future_neutral_checkpoint_known'] is declared['future17_root_restart_selected'] is False
    request=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        **{runtime.FIELD:{'P03':declared}})
    assert runtime.entry_authority(actual['spec'],request)
    with pytest.raises(ValueError):runtime.entry_authority(actual['spec'],dict(request,**{runtime.FIELD:{}}))
def test_future17_root_financial_restart_refuses_without_forming_checkpoint(actual):
    # This is explicitly a metadata-only malformed Spec DTO, never a checkpoint.
    dto=dict(NONCANONICAL_METADATA_DTO=True,arm='P03',root_admission_sha256='0'*64,
        repairs=[*actual['spec']['repairs'],{'NONCANONICAL_TAIL_DESCRIPTOR_DTO':True}])
    request=dict(execution_mode=runtime.MODE,financial_resume_authorized=True)
    with pytest.raises(ValueError,match='FUTURE17_ROOT_RESTART'):runtime.entry_authority(dto,request)
    assert runtime.entry_authority(dto,dict(execution_mode='READONLY_FROZEN_SOURCE_WITNESSES',financial_resume_authorized=False)) is False
def test_future_root_guard_removal_has_meaningful_falsifier(actual):
    dto=dict(NONCANONICAL_METADATA_DTO=True,arm='P03',root_admission_sha256='0'*64,
        repairs=[*actual['spec']['repairs'],{'NONCANONICAL_TAIL_DESCRIPTOR_DTO':True}])
    req=dict(execution_mode=runtime.MODE,financial_resume_authorized=True)
    with pytest.raises(ValueError):runtime.entry_authority(dto,req)
    assert remove(runtime,'entry_authority','THOR_RUNTIME_FUTURE17_ROOT_RESTART_REQUIRES_SEPARATE_QUALIFICATION')(dto,req) is False
def test_entry_hooks_restore_on_abort_after_existing_typed_context(actual,monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    old_run,old_review=runtime.uncertainty.run,runtime.uncertainty.review
    original_overlay=lambda _:False;module=SimpleNamespace(factual_overlay_needed=original_overlay)
    request=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        **{runtime.FIELD:{'P03':runtime.declaration(actual['spec'])}})
    with pytest.raises(RuntimeError):
        with runtime.entry_context(module,actual['spec'],request):
            assert module.factual_overlay_needed(actual['spec']) is True
            assert runtime.uncertainty.run is not old_run and runtime.uncertainty.review is not old_review
            raise RuntimeError('explicit opaque hook-abort seam, no financial body invoked')
    assert runtime.uncertainty.run is old_run and runtime.uncertainty.review is old_review and module.factual_overlay_needed is original_overlay
def test_temporary_view_cleanup_guard_does_not_claim_completion_before_observation(tmp_path):
    owned=tmp_path/'explicitly_noncanonical_metadata_only_temporary_directory';owned.mkdir()
    with pytest.raises(ValueError):runtime.cleanup_observed(owned)
    assert remove(runtime,'cleanup_observed','THOR_RUNTIME_TEMPORARY_OWNED_SEED_VIEW_CLEANUP_OBSERVED')(owned)
    owned.rmdir();assert runtime.cleanup_observed(owned)
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
