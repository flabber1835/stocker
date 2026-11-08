"""DATA routing, whole-body AST, and explicitly noncanonical transport DTOs."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ABMD_LIFECYCLE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
sys.path.insert(2,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
import system_campaign_p07_abmd_lifecycle as data
import system_campaign_financial_partial as partial

D=Path(__file__).resolve().parents[2]
C=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
S=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
def source_bytes(name):
    paths=[where/name for where in (D,C,S) if (where/name).is_file()]
    assert paths,name
    return paths[0].read_bytes()

def test_actual_frozen_v2_catalog_all_common_and_both_runtime_bindings():
    value=data.catalog(source_bytes=source_bytes)
    assert value['arm']=='P07' and len(value['parent_descriptors'])==23
    for name in ('system_campaign_p07_abmd_certificate.py','system_campaign_p07_abmd_models.py'):
        assert value['input_semantics_sources'][name]==data.sha(source_bytes(name))

def test_explicit_selected_request_exact_current_root_and_financial_mode():
    spec=data.initial_spec();request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',
        selected_abmd_bounded_inputs={'P07':data.declaration(spec)})
    assert data.selected(spec,request)
    for change in ('mode','declaration','root','arm'):
        s=deepcopy(spec);r=deepcopy(request)
        if change=='mode':r['execution_mode']='READ_ONLY'
        elif change=='declaration':r['selected_abmd_bounded_inputs']['P07']['actual_owned_or_ordered_right_valuation_authorized']=True
        elif change=='root':s['root_admission_sha256']='0'*64
        else:s['arm']='P06'
        assert not data.selected(s,r)

def test_financial_mode_guard_falsifier():
    spec=data.initial_spec();r=dict(execution_mode='READ_ONLY',selected_abmd_bounded_inputs={'P07':data.declaration(spec)})
    fn=data.models.legacy.original.function(Path(data.__file__).read_bytes(),'selected')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Compare(self,n):
            if ast.unparse(n)=="request.get('execution_mode') == 'OWN_ADMITTED_FINANCIAL_CONTINUATION'":
                self.hits+=1;return ast.copy_location(ast.Constant(True),n)
            return self.generic_visit(n)
    change=Remove();fn=change.visit(fn);assert change.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-financial-mode-DATA-guard>','exec'),scope)
    assert not data.selected(spec,r) and scope['selected'](spec,r)

@pytest.fixture
def transport():
    # This is metadata only: no checkpoint schema, financial state or journals.
    d=dict(filename='NONCANONICAL-DESCRIPTOR.json',sha256='a'*64,resume_session='2022-11-30',predecessor_checkpoint_sha256='b'*64)
    value=dict(schema=data.origin.SCHEMA,passed=True,initial_root_admission_sha256=data.INITIAL_ROOT,
        catalog_sha256=data.CATALOG_SHA,descriptor=d,noncanonical_transport_DTO=True)
    retained=data.retained_declaration(value)
    return dict(arm='P07',root_admission_sha256='f'*64,noncanonical_transport_DTO=True,
        retained_abmd=retained,repairs=deepcopy(data.models.plan()['parent_descriptors'])+[d])

def test_retained_declaration_carries_exact_origin_and_full24(transport):
    assert data.valid_retained(transport) and data.selected(transport,{})
    assert transport['retained_abmd']['prior_proof_rows_reexecuted']==0
    assert len(transport['repairs'])==24

@pytest.mark.parametrize('change',['catalog','authority','bool_count','count','origin','origin_hex','extra','descriptor','prefix','length'])
def test_retained_declaration_falsifiers(transport,change):
    s=deepcopy(transport);d=s['retained_abmd']
    if change=='catalog':d['catalog_sha256']='0'*64
    elif change=='authority':d['old_models_and_sources_preserved']=False
    elif change=='bool_count':d['prior_proof_rows_reexecuted']=False
    elif change=='count':d['prior_proof_rows_reexecuted']=1
    elif change=='origin':d['origin_sha256']='wrong'
    elif change=='origin_hex':d['origin_sha256']='z'*64
    elif change=='extra':d['financial_authority']=True
    elif change=='descriptor':s['repairs'][23]=dict(s['repairs'][23],sha256='0'*64)
    elif change=='prefix':s['repairs'][0]=dict(s['repairs'][0],sha256='0'*64)
    else:s['repairs'].pop()
    with pytest.raises(ValueError):data.valid_retained(s)

def test_whole_original_packet_qualifier_AST_undo():
    raw=(S/'system_campaign_abmd_bounded_preparation.py').read_bytes()
    before=data.models.legacy.original.function(raw,'qualify_packets');after=data.packet_tree(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,n):
            if ast.unparse(n)=='apply_cumulative(original, loaded)':
                self.hits+=1;return ast.copy_location(ast.parse('backtest.apply_repair(original,loaded)',mode='eval').body,n)
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after)
    assert undo.hits==1 and ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    with pytest.raises(ValueError):data.packet_tree(raw+b'\n')

@pytest.mark.parametrize('raises',[False,True])
def test_entry_restores_both_exact_hooks(monkeypatch,raises):
    import full_system_core
    import system_campaign_financial_additional_sensor as additional
    import system_campaign_ordinary_augmentation_router as router
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    monkeypatch.setattr(data,'selected',lambda spec:spec.get('noncanonical_transport_DTO') is True)
    spec={'noncanonical_transport_DTO':True};old=(additional.phase,router.implementation)
    marker=SimpleNamespace(noncanonical_routing_DTO=True)
    monkeypatch.setattr(data,'api',lambda root,cp,spec:marker)
    try:
        with data.entry(spec):
            assert additional.phase is data.phase
            assert router.implementation(None,None,spec) is marker
            if raises:raise LookupError('SYNTHETIC_BODY_FAILURE')
    except LookupError:
        assert raises
    assert (additional.phase,router.implementation)==old

def test_actual_initial_phase_preserves_original_full_source_record():
    spec=data.initial_spec();p=data.phase(spec)
    assert p==data.LEGACY_PHASE(spec) and p['proof_rows']==784
    assert p['origin_root_admission_sha256']!=data.INITIAL_ROOT

def test_later_phase_counts_come_only_from_admission_metadata(monkeypatch,transport):
    old=data.LEGACY_PHASE(data.initial_spec());seen=[]
    monkeypatch.setattr(partial,'validate_root_spec',lambda spec:seen.append(spec['noncanonical_transport_DTO']))
    monkeypatch.setattr(data.models.legacy.original,'retained_origin',lambda p:seen.append(p['proof_rows']))
    transport.update(outer_sha256='e'*64,measured_closes=1259,selected_session='2022-12-30',
        root_admission=dict(branch_uncertainty_proof=dict(passed=True,all_comparisons_and_state_sets_verified=True,
        all_math_watch_financial_chains_verified=True,rows=21,retained_rows=784)))
    p=data.phase(transport)
    assert p['proof_rows']==805 and p['proof_new_rows']==21 and p['proof_retained_rows']==784
    mutable={'root_admission_sha256','outer_sha256','completed','source_cursor','proof_rows','proof_new_rows','proof_retained_rows'}
    assert all(p[k]==v for k,v in old.items() if k not in mutable) and seen==[True,784,805]
    transport['root_admission']['branch_uncertainty_proof']['rows']=True
    with pytest.raises(ValueError):data.phase(transport)

@pytest.mark.parametrize('name',['api','runtime_api','run_initial','entry'])
def test_hosted_refusal_precedes_every_financial_import(monkeypatch,name):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if name=='api':data.api(None,None,None)
        elif name=='runtime_api':data.runtime_api(None,None,None,None)
        elif name=='run_initial':data.run_initial(*([None]*8))
        else:
            with data.entry(None):pass

def test_initial_review_routes_actual_current24_without_changing_parent():
    fn=data.models.legacy.original.function(Path(data.__file__).read_bytes(),'api')
    branch=next(n for n in fn.body if isinstance(n,ast.If) and 'origin.ORIGIN' in ast.unparse(n.test))
    assert "current['repairs'][:23] == cp['repairs']" in ast.unparse(branch)
    assert 'runtime_api(root, current, spec, value)' in ast.unparse(branch)
    assert not any(isinstance(n,ast.Assign) and any(ast.unparse(t)=='cp' for t in n.targets) for n in ast.walk(branch))

def test_initial_review_actual24_routing_metadata_DTO(tmp_path):
    # Compile the same entire routing function with imports bound to explicit
    # metadata fakes. There is no checkpoint file or financial object.
    (tmp_path/data.origin.ORIGIN).write_bytes(b'NONCANONICAL-ROUTING-MARKER')
    parent={'noncanonical_metadata_DTO':True,'repairs':list(range(23))}
    current={'noncanonical_metadata_DTO':True,'repairs':list(range(24))}
    calls=[]
    fn=data.models.legacy.original.function(Path(data.__file__).read_bytes(),'api')
    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self,node):return None
    fn=Imports().visit(fn)
    scope=dict(vars(data),hosted=lambda:None,catalog=lambda:{'noncanonical_catalog_DTO':True},
        journal=SimpleNamespace(read_checkpoint=lambda path:current),
        old_api=lambda *a:pytest.fail('original23 API incorrectly selected for24-input evidence'),
        runtime_api=lambda root,cp,spec,value:calls.append(cp))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-API-routing-metadata-fakes>','exec'),scope)
    scope['api'](tmp_path,parent,{})
    assert calls==[current] and len(parent['repairs'])==23
    current['repairs'][0]=-1
    with pytest.raises(ValueError):scope['api'](tmp_path,parent,{})

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
