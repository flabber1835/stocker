"""Portable input/dispatch falsifiers; never import a financial engine or state."""
import ast
from contextlib import nullcontext
from copy import deepcopy
import gzip,hashlib,importlib,json,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest

REPO=Path(__file__).resolve().parents[1]
HERE=REPO
if not (HERE/'system_campaign_financial_uncertainty.py').exists():HERE=Path(__file__).resolve().parents[2]/'candidate'
SOURCES=Path(os.environ.get('QUALIFIED_OWN_TEST_SOURCE_DIR',str(HERE)))
class SourceDirectory:
    def __truediv__(self,name):
        candidate=HERE/name
        return candidate if candidate.exists()else SOURCES/name
FILES=SourceDirectory()
U=HERE/'system_campaign_financial_uncertainty.py'
F=HERE/'system_campaign_financial_future.py'
ROOT='bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
encoded=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
digest=lambda v:sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(v,code):
    if not v:raise ValueError(code)
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('INPUT_ONLY_FENCE:'+name)
@pytest.fixture(autouse=True)
def fence():
    guard=Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)
class RemoveImports(ast.NodeTransformer):
    def visit_Import(self,n):return None
    def visit_ImportFrom(self,n):return None
class RemoveGuard(RemoveImports):
    def __init__(self,label):self.label=label
    def visit_Expr(self,n):
        if isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Name)and n.value.func.id=='need'and any(isinstance(v,ast.Constant)and v.value==self.label for v in n.value.args):return ast.Pass()
        return self.generic_visit(n)
def namespace(*,remove=None):
    tree=ast.parse(U.read_bytes())
    body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.Assign))
          and not(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='HERE'for t in n.targets))]
    tree=RemoveGuard(remove).visit(ast.Module(body=body,type_ignores=[]))
    ns=dict(__file__=str(U),HERE=FILES,Path=Path,json=json,gzip=gzip,sha=sha,digest=digest,deepcopy=deepcopy,
        nullcontext=nullcontext,ast=ast,need=need,hosted=lambda:None,save=lambda p,v:p.write_bytes(encoded(v)))
    exec(compile(ast.fix_missing_locations(tree),'<qualified-own-input-only>','exec'),ns)
    return ns
@pytest.fixture
def own():
    n=namespace();phase=deepcopy(n['own_policy_catalog']()['phases'][ROOT])
    source=json.loads((HERE/n['OWN_SOURCE_CATALOG']).read_bytes())['sources'][phase['source_payload_sha256']]
    payload,review=source['payload'],source['review']
    n['registered_scope']=lambda h:deepcopy(payload['scope'])
    # Tiny synthetic cp, used only to exercise the input predicate, never restore.
    integration=json.loads((FILES/n['INTEGRATION']).read_bytes())
    cp=dict(sha256=phase['outer_sha256'],completed=439,source_cursor='2019-09-30',repairs=[],
        base=dict(archive_sha256=payload['archive_sha256'],bundle_sha256=payload['bundle_sha256'],sources=integration['canonical_controller_sources']),
        run=dict(input_sha256='a'*64,state=dict(wealth_core=dict(episodes={}),pending=[],median5=dict(selected=[sid for sid,selected in review['parent_selected'].items()if selected]))))
    spec=dict(arm='P03',root_admission_sha256=ROOT,outer_sha256=cp['sha256'],measured_closes=439,selected_session='2019-09-30')
    return n,phase,cp,spec
def test_actual_pinned_source_input_contract(own):
    n,p,cp,spec=own;payload,hashes=n['own_source_binding'](cp,p)
    assert len(payload['terms'])==13 and len(payload['additional_rows'])==3 and len(hashes)==6
    assert p['event']['parent_selected']is True and p['event']['parent_positions']==[]
@pytest.mark.parametrize('field,value',[('arm','P05'),('outer_sha256','0'*64),('measured_closes',440),('selected_session','2019-10-18')])
def test_exact_registered_root(own,field,value):
    n,p,cp,spec=own;spec[field]=value
    with pytest.raises(ValueError):n['own_policy_phase'](spec)
@pytest.mark.parametrize('mutation',['pending','held','selected','date','cash','producer'])
def test_source_and_current_role_fail_closed(own,mutation):
    n,p,cp,spec=own;sid=p['event']['security_id']
    if mutation=='pending':cp['run']['state']['pending']=[dict(security_id=sid)]
    if mutation=='held':cp['run']['state']['wealth_core']['episodes']['1']=dict(slot_id=1,ticker='ALDR',current_shares=1,entry_date='2019-09-30',security_id=sid)
    if mutation=='selected':cp['run']['state']['median5']['selected'].remove(sid)
    if mutation=='date':p['event']['effective_session']='2019-10-23'
    if mutation=='cash':p['event']['known_cash_leg']='20.00'
    if mutation=='producer':p['source_producer_sha256']='0'*64
    with pytest.raises(ValueError):n['own_source_binding'](cp,p)
def make_retained(own,mode):
    n,origin,cp,spec=own;record=deepcopy(origin)
    record.update(mode='RETAINED',root_admission_sha256='e'*64,outer_sha256='f'*64,completed=462,source_cursor='2019-10-31',
        origin_root_admission_sha256=ROOT,origin_record_sha256=sha(encoded(origin)),proof_growth='INTERVAL',ordinary_input_mode=mode)
    catalog=deepcopy(n['own_policy_catalog']());catalog['phases'][record['root_admission_sha256']]=record;n['own_policy_catalog']=lambda:catalog
    cp=deepcopy(cp);cp.update(sha256=record['outer_sha256'],completed=462,source_cursor='2019-10-31')
    spec=dict(arm='P03',root_admission_sha256=record['root_admission_sha256'],outer_sha256=cp['sha256'],measured_closes=462,selected_session=cp['source_cursor'],base=cp['base'],root_admission={})
    n['validate_root_spec']=lambda spec:None
    return n,record,cp,spec
@pytest.mark.parametrize('mode,expected',[('UNCHANGED',True),('NEW_QUALIFIED_ORDINARY',False)])
def test_explicit_retained_mode_below_old503_threshold(own,mode,expected):
    n,p,cp,spec=make_retained(own,mode)
    assert n['own_unchanged_input_phase'](spec)is expected
    assert len(n['own_retained_contract'](cp,spec))==6
    if expected:
        receipt=n['own_unchanged_input_receipt'](cp,spec)
        assert receipt['proof_growth']=='RETAINED_OUTWARD_ROUNDED_INTERVAL_STATE_SET'
        assert 'witness_sha256'not in receipt and 'POINT_RETURN'not in encoded(receipt).decode()
def test_no_automatic_later_root_authority(own):
    n,p,cp,spec=own;spec.update(root_admission_sha256='e'*64,retained_uncertainty_model='typed')
    with pytest.raises(ValueError,match='UNREGISTERED'):n['own_policy_phase'](spec)
def test_unknown_retained_mode_refuses(own):
    n,p,cp,spec=make_retained(own,'AUTOMATIC')
    with pytest.raises(ValueError):n['own_unchanged_input_phase'](spec)
def test_typed_reporting_is_from_the_exact_original_request(own):
    n,p,cp,spec=own
    request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,financial_source_changed=False,
        sources={n['OWN_POLICY_CATALOG']:n['OWN_POLICY_SHA']},selected_research_models={'P03':n['own_model_declaration'](p)},admitted_checkpoints={'P03':cp['sha256']})
    assert n['typed_reporting_declaration'](request,'P03')==dict(retained_uncertainty_model='research.leadership-branch-uncertainty-input/1')
    request['admitted_checkpoints']['P03']='0'*64
    with pytest.raises(ValueError):n['typed_reporting_declaration'](request,'P03')
@pytest.mark.parametrize('guard,mutation',[
 ('OWN_POLICY_EXACT_DECLARED_ARM_ROOT_AXIS_AND_MODE','axis'),
 ('OWN_POLICY_EXACT_FRESH_SOURCE_CLOCK_ROOT_HISTORY_AND_ZERO_AUTHORITY','producer'),
 ('OWN_POLICY_EXACT_ORIGINAL_UNRESOLVED_DATE_AND_CONSIDERATION_CONTRACT','date'),
 ('OWN_POLICY_EVERY_FROZEN_IDENTITY_AND_CURRENT_PARENT_ROLE','pending')])
def test_guard_removal_makes_bad_input_pass(own,guard,mutation):
    original,p,cp,spec=own;n=namespace(remove=guard);n['registered_scope']=original['registered_scope']
    if mutation=='axis':
        spec['measured_closes']=440
        with pytest.raises(ValueError):original['own_policy_phase'](spec)
        assert n['own_policy_phase'](spec)
    else:
        if mutation=='producer':p['source_producer_sha256']='0'*64
        if mutation=='date':p['event']['effective_session']='2019-10-23'
        if mutation=='pending':cp['run']['state']['pending']=[dict(security_id=p['event']['security_id'])]
        with pytest.raises(ValueError):original['own_source_binding'](cp,p)
        assert n['own_source_binding'](cp,p)
@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared','sentinel','numpy','pandas'])
def test_engine_import_fence(name):
    with pytest.raises(ImportError,match='FENCE'):importlib.import_module(name)


def synthetic_run(own,tmp_path,*,remove=None,corrupt_final=False):
    original,phase,cp,spec=own
    n=namespace(remove=remove);log=[]
    n.update(own_policy_phase=lambda spec:phase,own_source_binding=lambda cp,p:(None,{'controller':'pinned'}))
    sequence=[]
    for index in range(1,4):
        current=deepcopy(cp);current['sha256']=str(index)*64
        current['repairs']=cp['repairs']+[dict(stage=i)for i in range(index)]
        current['run']['input_sha256']=str(index)*64;current['run']['checkpoint_sha256']=str(index)*64
        sequence.append(current)
    def prepare(parent,out,arm):
        log.append(('ordinary',parent['sha256'],arm))
        (out/'material.json').write_bytes(encoded(dict(terms=[dict(ticker=t)for t in phase['ordinary_expected_tickers']])))
        path=out/'future-financial-overlay.json';path.write_text('ordinary')
        return path,SimpleNamespace(earliest_affected_session='2019-10-07')
    def pause(parent,out,args,rows,path,earliest,directory):
        i=len([x for x in log if x[0]=='pause']);log.append(('pause',directory,parent['sha256'],earliest,path.name))
        assert parent is (cp if i==0 else sequence[i-1])
        return sequence[i]
    def date_input(parent,out):
        log.append(('date',parent['sha256']))
        (out/n['DATE_OVERLAY']).write_text('date')
        return nullcontext(),None
    class Alder:
        native='native'
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def prepared_date(parent,out):
        date_input(parent,out);return Alder(),SimpleNamespace()
    def reconstruct(parent,evidence_root,out):
        log.append(('reconstruct-date',parent['sha256']));out.mkdir()
    def overlay(parent,out):
        log.append(('model',parent['sha256']));path=out/'branch-uncertainty-input.json'
        path.write_bytes(encoded(dict(predecessor=parent['run']['checkpoint_sha256'])))
        return path
    def parser(path,*,resume_session,predecessor_checkpoint_sha256):
        log.append(('parser',resume_session,predecessor_checkpoint_sha256))
        if resume_session>=phase['event']['effective_session'] or predecessor_checkpoint_sha256!=sequence[1]['run']['checkpoint_sha256']:raise ValueError('exact parser')
        return SimpleNamespace()
    class Context:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def events(out,arm,*,cp):log.append(('events',cp['sha256'],arm));return Context()
    def main(args):log.append(('finance',tuple(args)));return 0
    final=deepcopy(sequence[-1])
    if corrupt_final:final['run']['input_sha256']='0'*64
    n.update(prepare=prepare,review_input=lambda parent,out,arm:'2019-10-07',hydration_name=lambda parent:'material.json',
        paused_own_adoption=pause,ActualEvents=events,prepare_date=prepared_date,hydrate=lambda native,path:{'event':'closed'},
        idempotent_dispatch=lambda alder:Context(),qualify_dispatch=lambda *args:None,
        reconstruct_own_date=reconstruct,overlay=overlay,evidence=lambda out:[],Codec=Context,Certificate=Context,
        qualify=lambda out,hashes:log.append(('qualify',)),parse=lambda *args,**kwargs:log.append(('reparse',)),
        validate_input=lambda out,cp:log.append(('validate-model',cp['sha256'])),
        backtest=SimpleNamespace(main=main,load_repair=parser),journal=SimpleNamespace(read_checkpoint=lambda path:final))
    result=n['run_own_initial'](cp,tmp_path,['--resume'],[b'old\n'],Context(),Context(),spec,tmp_path/'old')
    return log,result

def test_three_paused_boundaries_original_events_then_no_overlay_finance(own,tmp_path):
    log,result=synthetic_run(own,tmp_path)
    assert result==0
    pauses=[row for row in log if row[0]=='pause']
    assert [(p[1],p[3])for p in pauses]==[('ordinary-input-adoption','2019-10-07'),('date-input-adoption','2019-10-21'),('input-adoption','2019-10-22')]
    assert [p[2]for p in pauses]==[own[2]['sha256'],'1'*64,'2'*64]
    assert [p[4]for p in pauses]==['future-financial-overlay.json','alder-date-financial-overlay.json','branch-uncertainty-input.json']
    assert ('events',own[2]['sha256'],'P03')in log
    assert ('date','1'*64)in log and ('model','2'*64)in log
    assert log[-1]==('finance',('--resume',))
    assert log.index(('validate-model','3'*64))<log.index(('finance',('--resume',)))
    assert log.index(('reparse',))<log.index(('finance',('--resume',)))

def test_financial_input_guard_removal_is_detected(own,tmp_path):
    first=tmp_path/'first';first.mkdir()
    with pytest.raises(ValueError,match='THREE_EXACT_INPUT'):synthetic_run(own,first,corrupt_final=True)
    second=tmp_path/'second';second.mkdir()
    log,result=synthetic_run(own,second,corrupt_final=True,remove='OWN_POLICY_FINANCE_ONLY_AFTER_THREE_EXACT_INPUT_BOUNDARIES')
    assert result==0

PROTECTED_P07_AST = {'point_return_phase': '6c45385c0e62bc2e8642e31fb8f4a8fbbdd14b8384564f0c7b4cdc125fd8b427', 'unchanged_input_phase': '87658dba7af73e1c183ef4d1da04c9f59956931684b93798a343a99a6ae1dab9', 'proof_scope': '5321b5bb31fead4f5aa08a7b780462d301b26f85d69ad50ee615317454b64d2a', 'unchanged_input_receipt': '38f79d8dbaeecc6366cbeb6b03864273baa00cf72b51a489c70a31394e9b11b6', 'review_unchanged_input': '467c593d1cd5f73e66bf4a914702f94e31b3da51d71398abcdfff15fdb6a885b', 'source_contract': '4c43f704d1d4443f94318123f0c4ee6cf4e85f0678e7735e3eb9472a8026538a', 'prepare_date': 'b06eab8c4fe683006ac98c40d4a891dce4a798dafbc26e29ff56b514b103663f', 'boundary': 'fd9227c984ea5e197a6972972f0a4fd3cd7606874bcaa4e19bde6e62d445be25', 'active_codec': '1a38c803aa4aa9b316c04997a971e498dfae7c72de29e9c51c941526ca04ed19', 'suffix_review_tree': '30ee68222a740aac9d26940345c34158307c55c77f5dc46a60ee744f15948fd1', 'review_new_rows': 'd5019a6168e80ead97f1ac44f96c026dd0ac02a7bbbdddd045a1542040572ccc'}

def test_original_p07_gate_and_math_ast_unchanged():
    actual={n.name:sha(ast.dump(n,include_attributes=False).encode())for n in ast.parse(U.read_bytes()).body if isinstance(n,ast.FunctionDef)}
    assert all(actual[name]==pin for name,pin in PROTECTED_P07_AST.items())
