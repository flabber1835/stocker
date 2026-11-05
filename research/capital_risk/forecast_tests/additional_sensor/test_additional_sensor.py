"""Pure input/AST and synthetic callback qualification. Canonical finance is fenced."""
import ast,builtins,copy,hashlib,importlib,importlib.abc,json,os,sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[2]
DEP=Path(os.environ.get('ADDITIONAL_SENSOR_DEPENDENCY_DIR',str(C)))
for path in (DEP,C):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
import system_campaign_financial_additional_sensor as data
import system_campaign_financial_additional_sensor_runtime as runtime
sha=lambda v:hashlib.sha256(v).hexdigest()
F=Path(__file__).parent/'fixtures/source279-original-input-data.json'
FIXTURE_SHA='1e920debd1032d85e8c01ede83479fd2c1b46a56dccbcb73d1d8bed3d1bc3184'
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise AssertionError('NO_CANONICAL_FINANCIAL_IMPORT:'+name)
@pytest.fixture(autouse=True)
def fence():
    guard=Fence();sys.meta_path.insert(0,guard)
    try:yield
    finally:sys.meta_path.remove(guard)

@pytest.fixture
def fixture():
    raw=F.read_bytes();assert sha(raw)==FIXTURE_SHA
    value=json.loads(raw);assert value['not_a_canonical_checkpoint'] is True and value['financial_authority'] is False
    return value

@pytest.fixture
def env(tmp_path,monkeypatch,fixture):
    import system_campaign_financial_uncertainty as u
    overlay=tmp_path/'driver';overlay.mkdir()
    catalog=json.loads((C/'system-campaign-qualified-own-uncertainty-input-facts.json').read_bytes())
    p=next(v for v in catalog['phases'].values() if v['mode']==data.MODE)
    for name in set(p['policy_source_files'])|set(data.EXPECTED)|{u.OWN_POLICY_CATALOG,u.OWN_SOURCE_CATALOG}:
        path=C/name if (C/name).exists() else DEP/name
        (overlay/name).write_bytes(path.read_bytes())
    monkeypatch.setattr(data,'HERE',overlay);monkeypatch.setattr(runtime,'HERE',overlay)
    monkeypatch.setattr(u,'HERE',overlay)
    monkeypatch.setattr(u,'OWN_POLICY_SHA',sha((overlay/u.OWN_POLICY_CATALOG).read_bytes()))
    monkeypatch.setattr(u,'OWN_SOURCE_SHA',sha((overlay/u.OWN_SOURCE_CATALOG).read_bytes()))
    closed=next(n.value for n in ast.parse((C/'system_campaign_financial_uncertainty.py').read_bytes()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OWN_POLICY_CLOSED_GENERATIONS' for t in n.targets))
    monkeypatch.setattr(u,'OWN_POLICY_CLOSED_GENERATIONS',ast.literal_eval(closed))
    root=tmp_path/'synthetic-inputs';(root/'book/repairs').mkdir(parents=True)
    for name,raw in fixture['original_descriptors_and_input_bytes'].items():(root/'book/repairs'/name).write_text(raw,encoding='utf8',newline='')
    cp=copy.deepcopy(fixture['query_shaped_parent'])
    spec=dict(arm=p['arm'],root_admission_sha256=p['root_admission_sha256'],outer_sha256=p['outer_sha256'],
        measured_closes=p['completed'],selected_session=p['source_cursor'])
    return SimpleNamespace(p=p,u=u,overlay=overlay,root=root,cp=cp,spec=spec,fixture=fixture)

def full_input(e,monkeypatch):
    import system_campaign_financial_branches as b
    import system_campaign_zogenix_facts as z
    monkeypatch.setattr(b,'evidence',lambda root:copy.deepcopy(e.fixture['original_branch_document']['source_evidence']))
    ordinary=json.loads(next(raw for raw in e.fixture['original_descriptors_and_input_bytes'].values() if json.loads(raw)['schema']=='terminal-repair/1'))
    ordinary['predecessor_checkpoint_sha256']=e.cp['run']['checkpoint_sha256']
    ordinary['source_evidence'].append(dict(reference='synthetic-input-only/ordinary',sha256='1'*64,description='Synthetic neutral descriptor; no financial state.'))
    raw=data.encoded(ordinary);h=sha(raw)
    od=dict(filename=h+'.json',sha256=h,resume_session=e.cp['source_cursor'],predecessor_checkpoint_sha256=ordinary['predecessor_checkpoint_sha256'])
    (e.root/'book/repairs'/od['filename']).write_bytes(raw)
    cp1=copy.deepcopy(e.cp);cp1['repairs'].append(od);cp1['run']['checkpoint_sha256']='2'*64
    (e.root/z.PRIVATE).write_bytes(data.encoded(dict(synthetic_event_hash_only=True)))
    path=z.overlay(cp1,e.root);raw=path.read_bytes();h=sha(raw)
    zd=dict(filename=h+'.json',sha256=h,resume_session=cp1['source_cursor'],predecessor_checkpoint_sha256='2'*64)
    (e.root/'book/repairs'/zd['filename']).write_bytes(raw)
    cp2=copy.deepcopy(cp1);cp2['repairs'].append(zd);cp2['run']['input_sha256']='3'*64
    origin=dict(schema='research.retained-additional-sensor-origin/1',origin_root_admission_sha256=e.p['origin_root_admission_sha256'],
        ordinary_origin_outer_sha256=e.p['origin_outer_sha256'],ordinary_descriptor=od,sensor_descriptor=zd,cp1_inner_sha256='2'*64)
    return cp2,origin

def test_closed_generation_source_and_exact_nonpoint593_facts(env):
    assert data.phase(env.spec)==env.p
    assert env.p['original_branch_descriptor']['resume_session']=='2019-09-30'
    assert env.p['original_branch_descriptor']['predecessor_checkpoint_sha256']=='b3a6483dd1846596c461bad03140ac68e2ee69ee47d32fed27b7883d4f6b6dd9'
    last=env.fixture['original593_last_proof']
    assert len(last['possible_after'])==1 and last['math']['absolute']==[0.9604626761136053,0.9617624797108225]
    assert len(env.cp['repairs'])==20
    old=copy.deepcopy(env.u.own_policy_catalog());old['phases']={k:v for k,v in old['phases'].items() if k=='bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f'}
    assert sha(data.encoded(old))=='75639e35fe4ed78b15eacdc808347c1932aa6e2cdbc4d7733cd836d1e532defc'
    assert data.common_source_binding(env.cp,env.p)['scope_sha256']==env.p['source_scope_sha256']

@pytest.mark.parametrize('field,value',[('outer_sha256','0'*64),('measured_closes',1048),('selected_session','2022-03-01'),('arm','P03')])
def test_phase_wrong_registered_identity_refuses(env,field,value):
    bad=dict(env.spec);bad[field]=value
    with pytest.raises(ValueError,match='EXACT_REGISTERED_ROOT_PHASE'):data.phase(bad)

def test_phase_guard_removal_actually_admits_wrong_outer(env):
    bad=dict(env.spec,outer_sha256='0'*64)
    with pytest.raises(ValueError):data.phase(bad)
    fn=data.function(Path(data.__file__).read_bytes(),'phase')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need']
    call.args[0]=ast.Constant(True);scope=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<guard-removal-synthetic>','exec'),scope)
    assert scope['phase'](bad)==env.p

@pytest.mark.parametrize('bad',['native','source','range','ownership','role'])
def test_source_binding_wrong_original_fact_refuses(env,bad):
    cp=copy.deepcopy(env.cp);p=copy.deepcopy(env.p)
    if bad=='native':p['event']['native_term_sha256']='0'*64
    elif bad=='source':p['source_scope_sha256']='0'*64
    elif bad=='range':p['event']['native_term']['cash_per_share']=28.
    elif bad=='ownership':cp['run']['state']['wealth_core']['episodes']['x']=dict(security_id=p['event']['security_id'],slot_id=1,ticker='ZGNX',current_shares=1,entry_date='2022-01-01')
    else:cp['run']['state']['median5']['selected']=[]
    with pytest.raises(ValueError):data.common_source_binding(cp,p)

def test_real_original_b19_and_new_typed_parser_keep_both_origins(env,monkeypatch):
    cp,origin=full_input(env,monkeypatch)
    assert data.validate_models(env.root,cp,env.p,origin=origin,input_hash=lambda base,repairs:'3'*64)==[origin['sensor_descriptor']]
    assert origin['sensor_descriptor']['predecessor_checkpoint_sha256']!=env.p['original_branch_descriptor']['predecessor_checkpoint_sha256']
    assert cp['repairs'][:20]==env.cp['repairs']

@pytest.mark.parametrize('bad',['unknown','duplicate','missing','oldorigin','neworigin','descriptor','inputhash','native','range'])
def test_full_input_semantic_visitor_refuses_bad_models(env,monkeypatch,bad):
    cp,origin=full_input(env,monkeypatch);p=copy.deepcopy(env.p)
    if bad=='unknown':
        raw=data.encoded(dict(schema='arbitrary-unknown/1',predecessor_checkpoint_sha256='2'*64));h=sha(raw)
        d=dict(filename=h+'.json',sha256=h,resume_session='2022-02-28',predecessor_checkpoint_sha256='2'*64)
        (env.root/'book/repairs'/d['filename']).write_bytes(raw);cp['repairs'].append(d)
    elif bad=='duplicate':cp['repairs'].append(copy.deepcopy(cp['repairs'][-1]))
    elif bad=='missing':cp['repairs'].pop()
    elif bad=='oldorigin':p['original_branch_descriptor']=dict(p['original_branch_descriptor'],resume_session='2022-02-28')
    elif bad=='neworigin':origin['cp1_inner_sha256']='0'*64
    elif bad=='descriptor':cp['repairs'][-1]['filename']='../bad.json'
    elif bad=='inputhash':cp['run']['input_sha256']='0'*64
    else:
        d=cp['repairs'][-1];doc=json.loads((env.root/'book/repairs'/d['filename']).read_bytes())
        doc['native_term_sha256' if bad=='native' else 'consideration_range']='0'*64 if bad=='native' else '28<=cash<=28'
        raw=data.encoded(doc);h=sha(raw);d.update(filename=h+'.json',sha256=h);origin['sensor_descriptor']=copy.deepcopy(d)
        (env.root/'book/repairs'/d['filename']).write_bytes(raw)
    with pytest.raises(ValueError):data.validate_models(env.root,cp,p,origin=origin,input_hash=lambda base,repairs:'3'*64)

def test_new_schema_count_guard_removal_detects_missing_model(env,monkeypatch):
    cp,origin=full_input(env,monkeypatch);cp['repairs'].pop()
    with pytest.raises(ValueError,match='EXACT_DECLARED_MODEL_SCHEMAS'):data.validate_models(env.root,cp,env.p,origin=origin)
    fn=data.function(Path(data.__file__).read_bytes(),'validate_models')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need' and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='ADDITIONAL_EXACT_DECLARED_MODEL_SCHEMAS']
    call.args[0]=ast.Constant(True);scope=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<meaningful-schema-count-removal>','exec'),scope)
    assert scope['validate_models'](env.root,cp,env.p,origin=origin)==[]

def test_immutable_b19_semantic_visitor_has_exactly_one_inserted_branch(env,monkeypatch):
    cp,origin=full_input(env,monkeypatch);original=data.function;seen=[]
    def capture(raw,name):
        node=original(raw,name)
        if name=='validate_input':seen.append(node)
        return node
    monkeypatch.setattr(data,'function',capture)
    data.validate_models(env.root,cp,env.p,origin=origin)
    actual=seen[-1];loop,=[n for n in actual.body if isinstance(n,ast.For)]
    inserted=[n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=='schema == ADDITIONAL_SCHEMA']
    assert len(inserted)==1;loop.body.remove(inserted[0])
    old=original(data.source('system_campaign_financial_branches.py'),'validate_input')
    assert ast.dump(actual,include_attributes=False)==ast.dump(old,include_attributes=False)

def test_exact_suffix_visitor_preserves_every_other_branch_guard(env):
    tree=data.suffix_tree();loop=tree.body[0]
    old=data.function(data.source('system_campaign_financial_branches.py'),'review')
    expected_loop,=[n for n in old.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)']
    assert ast.unparse(loop.iter)=='enumerate(rows, start=retained_count)'
    call,=[n for n in ast.walk(loop) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need' and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='BRANCH_ONLY_DECLARED_EVENT_MAY_VARY']
    assert isinstance(call.args[0],ast.BoolOp) and len(call.args[0].values)==2
    assert ast.unparse(call.args[0].values[1])=='additional_event_allows(row, item)'
    call.args[0]=call.args[0].values[0];loop.iter=expected_loop.iter
    assert ast.dump(loop,include_attributes=False)==ast.dump(expected_loop,include_attributes=False)

@pytest.mark.parametrize('pairs,expected',[([],1.),([(1.,1.)],2.),([(1.,1.),(.5,.5)],1.75)])
def test_point_dispatch_uses_unchanged_cpython_order(pairs,expected):
    from system_campaign_uncertainty_math import Interval,growth
    from system_campaign_point_growth import point_growth
    values=[Interval(*v) for v in pairs]
    actual=data.mixed_growth(values,point=point_growth,interval=growth)
    assert actual.pair()==[expected,expected]

def test_genuine_interval_dispatch_preserves_width_and_original_operation():
    from system_campaign_uncertainty_math import Interval,growth
    from system_campaign_point_growth import point_growth
    values=[Interval(-.01,.02),Interval.point(.004)]
    assert data.mixed_growth(values,point=point_growth,interval=growth)==growth(values)
    assert growth(values).lo<growth(values).hi
    with pytest.raises(ValueError):point_growth(values)

def test_original_z_mro_delegates_exhaustive_cloud_and_adds_only_basis(env,monkeypatch,tmp_path):
    import system_campaign_financial_branches as b
    from system_campaign_uncertainty_math import Interval
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    Joint=runtime.joint_certificate(lambda values:Interval.point(1.))
    assert Joint.__mro__[1].__module__=='system_campaign_zogenix_sensor'
    state=dict(version=1,episode=False,latched=False,full_streak=0,recent_positive_streak=0,
        previous_native=1.,previous_desired=1.,effective_native=1.,champion_audit={},last_session='2022-03-07')
    def synthetic_recovery(**kwargs):
        after=copy.deepcopy(kwargs['state']);after['full_streak']=1 if kwargs['recent_r20']>0 else 0
        return after,dict(native=1.,desired=1.)
    probe=Joint.__new__(Joint);probe.out=tmp_path;probe.math=SimpleNamespace(snapshot=lambda:dict(synthetic_old_nonpoint=True))
    probe.original_recover=synthetic_recovery;probe.possible=[b.discrete(state)]
    probe.bounds={'recent_r20':Interval(-.02,.02),'recent_r40':Interval.point(.01)}
    probe.material=dict(synthetic_only=True);probe.zbasis=dict(session='2022-03-07',selected=True)
    kwargs=dict(state=state,native=1.,wc_drawdown=0.,spy_r20=.01,wc_r20=.01,recent_r20=.01,recent_r40=.01)
    actual=probe.recover(**kwargs)
    assert len(probe.possible)==2 and len(probe.pending['branches'])==2
    assert probe.pending['additional_event_basis']==probe.zbasis
    assert probe.pending['math']==dict(synthetic_old_nonpoint=True)
    assert actual[1]==dict(native=1.,desired=1.)

def test_explicit_both_model_report_declaration_and_default_refusal(env):
    d=data.declaration(env.p,env.u.OWN_POLICY_SHA)
    request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,financial_source_changed=False,
        selected_research_models={'P07':d},sources={env.u.OWN_POLICY_CATALOG:env.u.OWN_POLICY_SHA},admitted_checkpoints={'P07':env.p['outer_sha256']})
    result=data.report_declaration(request,'P07')
    assert result['retained_uncertainty_model']==data.BRANCH_INPUT and result['retained_additional_sensor']==d
    request['selected_research_models']['P07']['input_schemas']=[data.BRANCH_INPUT]
    with pytest.raises(ValueError):data.report_declaration(request,'P07')
    assert data.report_declaration({'selected_research_models':{'P07':dict(input_schema=data.BRANCH_INPUT)}},'P07') is None

@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_canonical_import_fence(name):
    with pytest.raises(AssertionError):__import__(name)
