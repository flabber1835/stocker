"""Actual immutable transport/accounting and readonly-hook metadata only."""
import ast,gzip,json,sys,zipfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p06-fin339-readonly-recovery-20261106');C=Path(__file__).resolve().parents[2]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P06_REVIEW339_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(C)]
import system_campaign_p06_fin339_readonly_recovery as r
import system_campaign_p06_BBIG_accounting_review as a
import system_campaign_financial_partial as partial
import system_campaign_financial_resume as m
import system_campaign_financial_review_repair as repair
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P06-source-snapshot/capture-P06-13525611349-001')
def ext(p):return Path(p) if str(p).startswith('\\\\?\\') else Path('\\\\?\\'+str(Path(p).resolve()))
@pytest.fixture(scope='module')
def actual():
    root=ext(R/'verified-output');mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
    def member(n):
        raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=r.sha(raw))==mf[n];return raw
    cp=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
    raw=member('book/daily.jsonl');pin=cp['journals']['daily'];rows=[json.loads(v) for v in raw[:pin['bytes']].splitlines()]
    i,=[i for i,v in enumerate(rows) if v['session']=='2023-07-27']
    before=rows[i-1]['evidence']['research_entry_audit']['closing_accounting'];opened=rows[i]['evidence']['research_entry_audit']['opening_accounting']
    folder=a.original.DIRECTORY
    record=json.loads(member(folder+'/actual-future-event-2023-07-27.json'))
    scope=json.loads(member(folder+'/observer-origin.json'))['one_actual_BBIG_scope']
    return root,cp,before,opened,record,scope,mf,member
@pytest.fixture
def target():return deepcopy(r.fact()['target'])
def request(t):return dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=r.MODE,arms=['P06'],financial_resume_authorized=False,
    readonly_partial_review=True,readonly_source_witnesses=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,
    **{r.FIELD:{'P06':r.declaration(t)}})
def test_actual_failure_then_original_source_record_positive_with_authentic_DTO_only(actual):
    root,cp,before,opened,record,scope,mf,member=actual;events=cp['run']['state']['ledger']['events'];term=r.data.catalog()['terms'][-1]
    saved=deepcopy((before,opened,events))
    with pytest.raises(KeyError,match='events'):a.original.source_record(record,term,scope,before,opened,events,source_was_selected=True)
    result=a.original.source_record(record,term,scope,a.expand_accounting(before,events),a.expand_accounting(opened,events),events,source_was_selected=True)
    assert result==dict(ticker='BBIG',session='2023-07-27',actual_noop=True,original_kernel_source_delegated=True,portfolio_completion_authorized=False,actual_settlement_claimed=False)
    assert (before,opened,events)==saved and len(a.expand_accounting(opened,events)['ledger']['events'])==1228
@pytest.mark.parametrize('change',['snapshot','phase','date','count','extra','events','reorder','truncate','same_length_source'])
def test_compact_DTO_or_committed_ledger_changes_refuse(actual,change):
    snap=deepcopy(actual[2]);events=deepcopy(actual[1]['run']['state']['ledger']['events'])
    if change=='snapshot':snap['schema']='foreign'
    elif change=='phase':snap['phase']='OPEN_BEFORE_FILLS'
    elif change=='date':snap['session']='2023-07-27'
    elif change=='count':snap['ledger']['event_count']=True
    elif change=='extra':snap['ledger']['events']=[]
    elif change=='events':events[0]['security_id']=r.data.SID
    elif change=='reorder':events.reverse()
    elif change=='truncate':events.pop()
    else:events[0]['session']='2010-01-01'
    with pytest.raises(ValueError):a.expand_accounting(snap,events)
def remove(module,name,label):
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Mutation(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    mutation=Mutation();fn=ast.fix_missing_locations(mutation.visit(fn));assert mutation.hits==1
    ns=dict(vars(module));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<explicit-guard-removal-DATA>','exec'),ns);return ns[name]
def test_event_source_guard_meaningful_removal(actual):
    snap=actual[2];events=deepcopy(actual[1]['run']['state']['ledger']['events']);events[0]['event_id']='FOREIGN_ACTUAL_SOURCE'
    with pytest.raises(ValueError,match='FULL_ACTUAL'):a.expand_accounting(snap,events)
    result=remove(a,'expand_accounting','P06_REVIEW339_FULL_ACTUAL_COMMITTED_LEDGER_EVENT_SOURCE')(snap,events)
    assert result['ledger']['events'][0]['event_id']=='FOREIGN_ACTUAL_SOURCE'
def test_whole_original_review_AST_undo_and_source_record_identity():
    raw=Path(a.original.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review');new=a.review_tree(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id=='expand_accounting':self.hits+=1;assert len(node.args)==2 and ast.unparse(node.args[1])=='events';return node.args[0]
            return self.generic_visit(node)
    undo=Undo();restored=undo.visit(new);assert undo.hits==2 and ast.dump(old)==ast.dump(restored)
    fn=a.review_function();assert fn.__globals__['source_record'] is a.original.source_record
    assert fn.__globals__['cash_terms'] is a.original.cash_terms
def test_actual_failed_transport_and_original_public_crypto_guards(actual,target):
    r.validate_target(target);r.request_only_readonly(request(target),target)
    r.prove_refusal(target,actual[6],actual[0])
    with zipfile.ZipFile(R/'artifact.zip') as z:assert len(r.public_names(target,z))==5
    assert target['receipt_status']==r.STATUS and target['review_sha256'] is None and 'root_admission' not in target
    assert [target['prior_stops'][k]['exit_code'] for k in ('preflight','worker','reviewer')]==[0,1,1]
@pytest.mark.parametrize('key,value',[('outer_sha256','0'*64),('measured_closes',1432),('selected_session','2023-09-11'),('financial_authority',True),('review_sha256','0'*64),('root_admission_sha256','0'*64),('receipt_status','PASSED')])
def test_foreign_tail_or_promoted_target_refuses(target,key,value):
    target[key]=value
    with pytest.raises(ValueError):r.validate_target(target)
@pytest.mark.parametrize('key,value',[('execution_mode','OWN_ADMITTED_FINANCIAL_CONTINUATION'),('financial_resume_authorized',True),('readonly_partial_review',False),('readonly_source_witnesses',True),('maximum_parallel_financial_workers',1),('maximum_parallel_readonly_workers',2),('arms',['P07'])])
def test_other_modes_and_authority_refuse(target,key,value):
    bad=request(target);bad[key]=value
    with pytest.raises(ValueError):r.request_only_readonly(bad,target)
def test_original_code_objects_and_defaults_unchanged():
    before=repair.ORIGIN,repair.admit,repair.public_names,repair.require_requalified_review
    for name in ('public_names','admit'):
        fn=r.legacy(name);old=getattr(repair,name);assert fn.__code__ is old.__code__ and fn.__globals__ is not old.__globals__ and fn.__globals__['ORIGIN']==r.ORIGIN
    assert (repair.ORIGIN,repair.admit,repair.public_names,repair.require_requalified_review)==before
    r.source_contract(m,partial)
def test_source_closure_exact_and_overlay_false(tmp_path,monkeypatch,target):
    for name in r.source_names():
        path=D/name if (D/name).is_file() else C/name;(tmp_path/name).write_bytes(path.read_bytes())
    monkeypatch.setattr(r,'HERE',tmp_path)
    value=r.expected_request(lambda:dict(sources={},arm_inputs={'P06':dict(new_factual_overlay=True)}),execution_mode=r.MODE,selected_arms=['P06'],target_lookup=lambda arm:target)
    assert value[r.FIELD]=={'P06':r.declaration(target)} and value['arm_inputs']['P06']['new_factual_overlay'] is False
    assert set(r.source_names())<=set(value['sources'])
def test_preflight_readonly_patches_restore_and_actualfull11_visitor(actual,target,tmp_path,monkeypatch):
    root,current,*_=actual;member=actual[-1];models=r.models;old=models.original;catalog=models.initial.catalog()
    def data_visitor(where,cp):
        assert where==root and cp==current
        return models.bound_history()(root,cp,catalog,
            root_metadata=partial.root_spec('P06',catalog['parent_root_admission_sha256']),
            input_hash=lambda base,repairs:r.data.digest(dict(base=base,repairs=repairs)),
            initial_parent=json.loads(gzip.decompress(member(old.DIRECTORY+'/'+old.PARENT))),
            ordinary_neutral=json.loads(gzip.decompress(member(old.DIRECTORY+'/'+old.ORDINARY))),
            typed_neutral=json.loads(gzip.decompress(member(old.DIRECTORY+'/'+old.TYPED))),
            financial_parent=json.loads(gzip.decompress(member(models.PARENT))),
            neutral11=json.loads(gzip.decompress(member(models.DIRECTORY+'/checkpoint.json.gz'))),member=member)
    monkeypatch.setattr(models,'full',data_visitor)
    before=partial.retained_models,partial.model_context
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with r.preflight_context(m,target,out=tmp_path):
            assert partial.retained_models(actual[0],actual[1],target) is True
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert (partial.retained_models,partial.model_context)==before and list(tmp_path.iterdir())==[]
def test_date_count_guard_meaningful_removal(actual,monkeypatch):
    snap=deepcopy(actual[2]);events=actual[1]['run']['state']['ledger']['events'];snap['ledger']['event_count']=1228
    value=a.fact();match=next(v for v in value['BBIG_compact_accounting'] if v['phase']==snap['phase']);match.update(event_count=1228,sha256=r.data.digest(snap))
    monkeypatch.setattr(a,'fact',lambda:value)
    with pytest.raises(ValueError,match='COUNT_BOUNDS'):a.expand_accounting(snap,events)
    result=remove(a,'expand_accounting','P06_REVIEW339_EXACT_COUNT_BOUNDS_AND_ACCOUNTING_EVENT_CHRONOLOGY')(snap,events)
    assert len(result['ledger']['events'])==1228
def test_launch_quarantine_hooks_restore_on_abort(target,monkeypatch):
    import probe
    monkeypatch.setattr(probe,'check_context',lambda env:None);monkeypatch.setattr(r,'target',lambda:target)
    before=repair.applies,repair.admit,repair.ORIGIN,repair.require_requalified_review
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with r.context(request(target),mode='launch'):
            assert repair.applies(target) is True and repair.ORIGIN==r.ORIGIN
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert (repair.applies,repair.admit,repair.ORIGIN,repair.require_requalified_review)==before
def test_whole_readonly_runtime_context_restore_without_entering_engine(actual,target,tmp_path,monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(r,'target',lambda:target)
    parent=partial.root_spec('P06',r.ORIGIN);saved=a.original.review
    calls=[]
    @contextmanager
    def fake_inputs(root,current,out,spec):
        calls.append((root,current['sha256'],spec));yield
    monkeypatch.setattr(partial,'financial_inputs',fake_inputs)
    oldhooks=partial.retained_models,partial.model_context,r.runtime.legacy.review,r.runtime.legacy.run,m.factual_overlay_needed
    with pytest.raises(RuntimeError,match='EXPLICIT_METADATA_ABORT'):
        with r.review_context(m,parent,request(target),old=actual[0],out=tmp_path,evidence=actual[0]):
            assert a.original.review is not saved and r.runtime.legacy.review is not oldhooks[2]
            raise RuntimeError('EXPLICIT_METADATA_ABORT')
    assert a.original.review is saved and (partial.retained_models,partial.model_context,r.runtime.legacy.review,r.runtime.legacy.run,m.factual_overlay_needed)==oldhooks
    assert len(calls)==1 and calls[0][1]==r.OUTER and calls[0][2]==parent
def test_economic_mode_forbidden_before_patches(target,monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    old=repair.admit,repair.applies,repair.ORIGIN
    with pytest.raises(ValueError,match='ECONOMIC_MODE_FORBIDDEN'):
        with r.context(request(target),mode='economic'):pass
    assert (repair.admit,repair.applies,repair.ORIGIN)==old
def output_report_DTOs(actual):
    branch=json.loads(actual[-1]('stopped-review/uncertainty-certificate-review.json'))
    core=dict(EXPLICIT_NONCANONICAL_REVIEW_DTO=True,checkpoint_sha256=r.OUTER,schema='research.full-system-core-review/1',
        status='PARTIAL_CORE_PREFIX_REVIEWED',counts=dict(formation=126,daily=1426),all_prefixes_verified=True,all_daily_factors_and_chains_verified=True,complete=False)
    source=dict(passed=True,cash_events=[],source_events=[dict(ticker='BBIG',session='2023-07-27',actual_noop=True,
        original_kernel_source_delegated=True,portfolio_completion_authorized=False,actual_settlement_claimed=False)],
        all_committed_dates_and_calls_accounted=True,original_TRQ_MYOV_preserved=True,original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)
    return {'core-review.json':core,'uncertainty-certificate-review.json':branch,'p06-BBIG-combined-observation-review.json':source}
def test_fresh_output_validator_returns_original_failed_link_not_financial_permission(actual,target,tmp_path):
    for name,value in output_report_DTOs(actual).items():(tmp_path/name).write_bytes(r.encoded(value))
    result=r.require_requalified_review(tmp_path,target)
    assert result['passed'] is True and result['financial_authority'] is False and result['financial_sessions_advanced']==0
    assert result['original_failed_receipt_sha256']==target['receipt_sha256'] and result['original_failed_stops_preserved'] is True
    assert result['original_financial_artifact_id']==13525611349 and target['review_sha256'] is None
@pytest.mark.parametrize('name,field,value',[
    ('core-review.json','checkpoint_sha256','0'*64),('core-review.json','complete',True),
    ('uncertainty-certificate-review.json','retained_rows',129),('uncertainty-certificate-review.json','rows',44),
    ('uncertainty-certificate-review.json','parent_sha256','0'*64),('uncertainty-certificate-review.json','prior_qualification_reexecuted',True),
    ('uncertainty-certificate-review.json','prior_proof_rows_reexecuted',False),('uncertainty-certificate-review.json','exhaustive_leaves',42),
    ('p06-BBIG-combined-observation-review.json','original_TRQ_MYOV_preserved',False),('p06-BBIG-combined-observation-review.json','financial_sessions_reexecuted',1)])
def test_missing_incomplete_or_weakened_new_review_refuses(actual,target,tmp_path,name,field,value):
    reports=output_report_DTOs(actual);reports[name][field]=value
    for n,v in reports.items():(tmp_path/n).write_bytes(r.encoded(v))
    with pytest.raises(ValueError):r.require_requalified_review(tmp_path,target)
@pytest.mark.parametrize('name',['research.pooled_vacancy_funding.journal','research.pooled_vacancy_funding.monthly','stock_strategy_shared.x','sentinel.x','numpy'])
def test_engine_import_fences(name):
    with pytest.raises(ImportError,match='DATA_ONLY'):__import__(name)
