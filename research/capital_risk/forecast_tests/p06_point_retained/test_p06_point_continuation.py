"""Frozen source/actual numeric DATA and unregistered metadata DTOs only."""
import ast,gzip,json,sys
from copy import deepcopy
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_POINT_METADATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import system_campaign_p06_abmd_point_continuation as data

C=Path(__file__).resolve().parents[2]
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial324-source-snapshot/capture-P06-13478656632-001')
W=Path('C:/GitHub/stocker/.codex-tmp/matched-funding-20261025/action-research/ge-20240402/successor-001/source/sentinel/controller/median5.py')
def read(path):return Path('\\\\?\\'+str(path.resolve())).read_bytes()

@pytest.fixture(scope='module')
def actual():
    pins=json.loads(read(R/'authenticated-manifest.json'))['members']
    def member(name):
        raw=read(R/'verified-output'/name);assert dict(bytes=len(raw),sha256=data.sha(raw))==pins[name];return raw
    cp=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
    whole=member('uncertainty-certificate.jsonl')
    rows=[json.loads(line) for line in whole.splitlines() if json.loads(line)['session']<=cp['source_cursor']]
    assert len(rows)==6 and dict(bytes=len(data.proof_bytes(rows)),sha256=data.sha(data.proof_bytes(rows)))==data.SIX_PREFIX
    assert dict(bytes=len(whole),sha256=data.sha(whole))==data.ENTIRE_OLD_PROOF
    catalog=json.loads((C/'P06-own1238-ABMD-bounded-catalog-v2.json').read_bytes())
    from system_campaign_bounded_sensor_event_review import permissions
    allowed,resolutions=permissions(R/'verified-output',rows,catalog,through=cp['source_cursor'],input_descriptors=cp['repairs'])
    assert allowed=={} and len(resolutions)==1
    return dict(cp=cp,rows=rows,catalog=catalog,allowed=allowed,resolutions=resolutions,
        archive_raw=member(resolutions[0]['actual']),hashes=json.loads((C/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources'])

@pytest.fixture
def dto(actual):
    # Deliberately unregistered ID cannot resolve as a real root. This is only
    # metadata: no checkpoint schema, financial state or journals are present.
    cp=actual['cp'];current={k:deepcopy(cp[k]) for k in ('sha256','completed','source_cursor','base','repairs')}
    current['NONCANONICAL_METADATA_DTO']=True
    current['run']={k:cp['run'][k] for k in ('checkpoint_sha256','state_sha256','input_sha256')}
    spec=dict(NONCANONICAL_UNREGISTERED_ADMISSION_DTO=True,arm='P06',root_admission_sha256='NONCANONICAL-UNREGISTERED-TEST-ID',
        artifact_id=13478656632,outer_sha256=current['sha256'],selected_file=data.SAVED_GZIP,base=current['base'],repairs=current['repairs'],
        measured_closes=1259,selected_session='2022-12-30',inner_sha256=current['run']['checkpoint_sha256'],
        state_sha256=current['run']['state_sha256'],input_sha256=current['run']['input_sha256'],root_admission=dict(
            NONCANONICAL_UNREGISTERED_ADMISSION_DTO=True,branch_uncertainty_proof=dict(passed=True,rows=6,retained_rows=0,
            all_comparisons_and_state_sets_verified=True,all_math_watch_financial_chains_verified=True)))
    return dict(current=current,spec=spec,rows=actual['rows'],committed=actual['rows'],resolutions=actual['resolutions'],
        allowed=actual['allowed'],archive_raw=actual['archive_raw'],source_hashes=actual['hashes'],expected_hashes=actual['hashes'])

def test_exact_frozen_witness_and_whole_point_helper_operation_order():
    result=data.arithmetic_sources(read(W),(C/'system_campaign_point_growth.py').read_bytes(),
        (C/'system_campaign_financial_additional_sensor.py').read_bytes())
    assert result['whole_witness_AST_sha256']==data.WITNESS_AST

@pytest.mark.parametrize('index',[0,1,2])
def test_any_changed_frozen_source_is_refused(index):
    sources=[read(W),(C/'system_campaign_point_growth.py').read_bytes(),(C/'system_campaign_financial_additional_sensor.py').read_bytes()]
    sources[index]+=b'\n'
    with pytest.raises(ValueError):data.arithmetic_sources(*sources)

def test_removed_whole_file_guard_accepts_same_AST_with_foreign_source_bytes():
    fn=data.function(Path(data.__file__).read_bytes(),'arithmetic_sources')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='P06_POINT_WHOLE_FROZEN_WITNESS_POINT_AND_MIXED_SOURCES' for v in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-source-byte-guard-DATA-only>','exec'),scope)
    args=(read(W)+b'\n',(C/'system_campaign_point_growth.py').read_bytes(),(C/'system_campaign_financial_additional_sensor.py').read_bytes())
    with pytest.raises(ValueError):data.arithmetic_sources(*args)
    assert scope['arithmetic_sources'](*args)['witness_sha256']==data.WITNESS_SHA

def test_actual_Dec28_factor_difference_and_same_rounded_NAV(actual):
    from system_campaign_uncertainty_math import Interval,growth
    row,=[r for r in actual['rows'] if r['session']=='2022-12-28']
    returns=[Interval(*v['current']).div(Interval.point(v['prior'])).sub(Interval.point(1.)) for v in row['material']['rows']]
    point=data.mixed_growth(returns);sequential=growth(returns)
    assert point.pair()==[0.9814856408126033]*2 and sequential.pair()==row['material']['factor']==[0.9814856408126034]*2
    prior,=[r for r in actual['rows'] if r['session']=='2022-12-27']
    assert prior['material']['representative_nav']*point.lo==prior['material']['representative_nav']*sequential.lo==row['material']['representative_nav']

def test_varying_intervals_keep_original_growth():
    from system_campaign_uncertainty_math import Interval,growth
    returns=[Interval(.01,.02),Interval.point(-.005)]
    assert data.mixed_growth(returns).pair()==growth(returns).pair()

@pytest.mark.parametrize('kind',['implementation','version'])
def test_point_helper_refuses_foreign_interpreter(monkeypatch,kind):
    import system_campaign_point_growth as point
    if kind=='implementation':monkeypatch.setattr(point.platform,'python_implementation',lambda:'FOREIGN')
    else:monkeypatch.setattr(point,'sys',SimpleNamespace(version_info=(3,11)))
    with pytest.raises(ValueError,match='SAME_CPYTHON312'):data.mixed_growth([])

def test_literal_actual_six_rows_metadata_gate_does_not_register_admission(dto):
    assert dto['spec']['NONCANONICAL_UNREGISTERED_ADMISSION_DTO'] is True
    assert dto['spec']['root_admission_sha256']=='NONCANONICAL-UNREGISTERED-TEST-ID'
    result=data.qualify_seed_metadata(**dto)
    assert result['committed_rows']==6 and result['unadmitted_tail_rows_used']==0 and result['financial_authority'] is False

@pytest.mark.parametrize('change',['initial_root','current','input','history','rows','boolrows','seed_factor','tail',
    'state','source_hashes','basis','archive','alias','preimage'])
def test_admitted_seed_origin_and_source_falsifiers(dto,change):
    a=deepcopy(dto)
    if change=='initial_root':a['spec']['root_admission_sha256']=data.INITIAL_ROOT
    elif change=='current':a['current']['sha256']='0'*64
    elif change=='input':a['current']['run']['input_sha256']='0'*64
    elif change=='history':a['current']['repairs']=a['current']['repairs'][:-1]
    elif change=='rows':a['spec']['root_admission']['branch_uncertainty_proof']['rows']=5
    elif change=='boolrows':a['spec']['root_admission']['branch_uncertainty_proof']['rows']=True
    elif change=='seed_factor':a['rows'][2]['material']['factor'][0]+=1e-6
    elif change=='tail':a['rows'].append(dict(NONCANONICAL_TAIL_DTO=True,session='2023-01-03'))
    elif change=='state':a['current']['run']['state_sha256']='0'*64
    elif change=='source_hashes':a['source_hashes']={}
    elif change=='basis':a['allowed']={'FOREIGN':('2022-12-22','FOREIGN',[380.,415.])}
    elif change=='archive':a['archive_raw']+=b'FOREIGN'
    elif change=='alias':a['resolutions'][0]['actual']='book/pre-event/2022-12-22.json.gz'
    else:a['resolutions'][0]['state_sha256']='0'*64
    with pytest.raises(ValueError):data.qualify_seed_metadata(**a)

def test_entire_frozen_initial_factory_AST_undo_exactly_two_bindings():
    raw=Path(data.frozen.__file__).read_bytes();before=data.function(raw,'certificate_class');after=data.factory_tree(raw)
    material,=[n for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='material']
    keyword=material.value.keywords.pop();assert keyword.arg=='growth' and ast.unparse(keyword.value)=='mixed_growth'
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_BoolOp(self,node):
            if ast.unparse(node).startswith('qualified_retained_seed(self.seed, self.source_hashes, event, source, codec) and '):
                self.hits+=1;return ast.copy_location(ast.parse('self.seed == [] and self.math is self.pending is None',mode='eval').body,node)
            return self.generic_visit(node)
    undo=Undo();after=undo.visit(after)
    assert undo.hits==1 and ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

def test_removed_literal_seed_guard_accepts_altered_old_factor_falsifier(dto):
    a=deepcopy(dto);a['rows']=deepcopy(a['rows']);a['rows'][2]['material']['factor'][0]+=1e-6
    fn=data.function(Path(data.__file__).read_bytes(),'qualify_seed_metadata')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='P06_POINT_LITERAL_SIX_ADMITTED_PROOFS_NO_UNADMITTED_TAIL' for v in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-six-proof-byte-guard-DATA-only>','exec'),scope)
    with pytest.raises(ValueError):data.qualify_seed_metadata(**a)
    assert scope['qualify_seed_metadata'](**a)['financial_authority'] is False

def test_runtime_refuses_before_any_canonical_import(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        data.certificate_class(None,None,None,None,inherited_root=None,retained_root=None,current_checkpoint=None,admitted_spec=None)

def test_no_selection_writer_or_registration_surface():
    raw=Path(data.__file__).read_text()
    assert '.write_bytes(' not in raw and '.write_text(' not in raw
    assert not any(n in vars(data) for n in ('selected','entry','register','request_context'))
    fn=data.function(Path(data.__file__).read_bytes(),'certificate_class')
    assert 'validate_root_spec(spec)' in ast.unparse(fn)
    assert 'journal.read_checkpoint' in ast.unparse(fn)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
