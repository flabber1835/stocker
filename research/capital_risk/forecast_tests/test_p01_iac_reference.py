"""Source-bound metadata and scalar stubs; never execute Core or serializers."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import subprocess
import json
import sys
from types import SimpleNamespace
import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_reference_evidence as e
import p01_iac_reference_source as source
import p01_iac_reference_run as run
import p01_iac_reference_review as review


def runtime(day,*,value=1):
    state=dict(last_processed_session=day,synthetic_only=True,value=value)
    obj=dict(state=state,state_sha256=e.digest(state),input_sha256='SYNTHETIC_INPUT12')
    return dict(obj,checkpoint_sha256=e.digest(obj))


def outer(day,count,*,value=1):
    obj=dict(run=runtime(day,value=value),source_cursor=day,completed=count)
    return dict(obj,sha256=e.digest(obj))


def recorded(monkeypatch):
    epoch=outer('2020-06-30',628);monkeypatch.setattr(e,'OUTER',epoch['sha256'])
    zero=dict(epoch_checkpoint=epoch,input_checkpoint=deepcopy(epoch),successor_input_sha256='SYNTHETIC_INPUT12')
    previous=epoch['run'];paths=[]
    for day in ('2020-07-01','2020-07-02'):
        following=runtime(day);paths.append(dict(session=day,prior_checkpoint=previous,
            publication=dict(session=day,synthetic_only=True),checkpoint=following));previous=following
    final=outer('2020-07-02',630)
    boundary=dict(schema='research.p01-iac-unit-unadmitted-reference-boundary/1',actual_components=paths,
        qualifier_checkpoint=final,input_zero_checkpoint=zero['input_checkpoint'],
        actual_reference_records_preserved_before_fixtures=True,financial_authority=False,qualification_state_adopted=False)
    return dict(schema='research.p01-iac-unit-synthetic-canonical-component/2',actual_reference_boundary=boundary),zero


def test_actual_metadata_functions_compile_under_financial_import_fence():
    # Real published helper/source bytes, no module alias replacement or strategy import.
    script=r'''
import sys,importlib.abc
class FinancialFence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='sentinel' or fullname.startswith(('sentinel.','stock_strategy_shared','research.pooled_','research.bounded_')):
            raise AssertionError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
sys.meta_path.insert(0,FinancialFence())
import p01_iac_reference_run as runtime
import p01_iac_reference_review as review
names=('prepare','exact_prefixes','boundaries','report','refusal_rows','last_attempt','branch','economic','main')
for name in names:
    fn=runtime._body(name)
    assert fn.__name__==name
    while hasattr(fn,'__wrapped__'):fn=fn.__wrapped__
    assert fn.__globals__['historical_epoch'] is runtime.historical_epoch
for name in ('review','review_loaded'):assert review._body(name).__name__==name
print('FENCED_METADATA_COMPILE_11_PASS')
'''
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=HERE,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='FENCED_METADATA_COMPILE_11_PASS'


def test_whole_recorded_reference_hashes_and_types(monkeypatch):
    component,zero=recorded(monkeypatch)
    actual=e.validate_reference(component,zero)
    assert len(actual['components'])==2 and actual['final']['completed']==630
    wrong=deepcopy(component)
    wrong['actual_reference_boundary']['actual_components'][1]['prior_checkpoint']=runtime('2020-07-01',value=1.0)
    with pytest.raises(ValueError,match='ADJACENCY'):e.validate_reference(wrong,zero)


@pytest.mark.parametrize('where',['zero','final','runtime'])
def test_outer_and_inner_hash_mutations_refuse(monkeypatch,where):
    component,zero=recorded(monkeypatch)
    if where=='zero':zero['input_checkpoint']['sha256']='0'*64
    if where=='final':component['actual_reference_boundary']['qualifier_checkpoint']['sha256']='0'*64
    if where=='runtime':component['actual_reference_boundary']['actual_components'][0]['checkpoint']['state_sha256']='0'*64
    with pytest.raises(ValueError):e.validate_reference(component,zero)


def test_actual_preparation_source_shape_and_changed_source_refusal():
    path=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p01-sequential-001/final-delivery-preparation-001/source-contracts/backtest.py.txt')
    raw=path.read_bytes();proof=source.preparation_shape(raw,source.BACKTEST_SHA)
    assert proof['overlays_before_append'] is True and proof['original_axis_offset']==425
    with pytest.raises(ValueError,match='EXACT516'):source.preparation_shape(raw+b'\n',source.BACKTEST_SHA)


def test_exact_publication_and_prior_type_guard_falsifier():
    publication=dict(session='2020-07-01',synthetic_value=1)
    prior=dict(synthetic_only=True,value=1)
    window=dict(session=publication['session'],full_window_before_feature_bound=True)
    app=dict(session=publication['session'],derivation_before_buffer_append=True)
    assert source.check_prepared(publication,deepcopy(publication),prior,deepcopy(prior),window,app)['complete_typed_publication_equal']
    wrong=deepcopy(publication);wrong['synthetic_value']=1.0
    with pytest.raises(ValueError,match='WHOLE_RECORDED'):source.check_prepared(publication,wrong,prior,prior,window,app)
    # Remove this exact new guard and the invalid typed object is demonstrably accepted.
    tree=ast.parse(Path(source.__file__).read_bytes());node,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='check_prepared']
    node.body.pop(0);scope=dict(vars(source));exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-full-publication-guard>','exec'),scope)
    assert scope['check_prepared'](publication,wrong,prior,prior,window,app)['complete_typed_publication_equal']
    with pytest.raises(ValueError,match='ENTIRE_PRIOR'):source.check_prepared(publication,publication,prior,dict(prior,value=1.0),window,app)


def test_no_advance_blocker_restores_all_aliases_and_refuses():
    fn=lambda:None;first=SimpleNamespace(advance=fn);second=SimpleNamespace(advance=fn)
    targets=[('synthetic-runtime',first,'advance'),('synthetic-kernel',second,'advance')]
    with source.NoAdvance(targets) as blocker:
        with pytest.raises(ValueError,match='FINANCIAL_ADVANCE'):second.advance()
        with pytest.raises(ValueError,match='ZERO_RUNTIME'):blocker.proof()
    assert first.advance is second.advance is fn


def test_no_advance_setup_failure_restores_preceding_hook():
    fn=lambda:None;first=SimpleNamespace(advance=fn);bad=SimpleNamespace()
    with pytest.raises(AttributeError):
        with source.NoAdvance([('first',first,'advance'),('missing',bad,'advance')]):pass
    assert first.advance is fn


def test_unchanged_source_check_and_new_financial_domain_only():
    proof=dict(schema=source.SCHEMA,recorded_reference={'synthetic_only':True},source_compiler_check={'synthetic_only':True},
        fresh_execution=dict(origin='NEW_HOSTED_FAST_EXECUTION',applications=[],refusals=[]),source_members={})
    before=deepcopy(proof);codec=SimpleNamespace(applied=[{'synthetic_only':True}],refusals={})
    run.update_financial_source(proof,{'synthetic_member':True},codec)
    assert proof['recorded_reference']==before['recorded_reference'] and proof['source_compiler_check']==before['source_compiler_check']
    assert proof['fresh_execution']['origin']=='NEW_FRESH_OWN628_FINANCE' and 'reference_applications' not in proof
    with pytest.raises(ValueError):run.update_financial_source(proof,{},codec)


def test_review_actual_import_sites_and_explicit_domain_rewrites():
    code=ast.unparse(review._node('review'))
    assert 'from p01_iac_quote_epoch import historical_epoch' in code
    loaded=ast.unparse(review._node('review_loaded'))
    assert 'from p01_iac_reference_review import save_review as save' in loaded
    assert 'from p01_iac_reference_export import qualification' in loaded
    assert "qsource['source_compiler_check']['applications']" in loaded
    assert "fsource['fresh_execution']['applications']" in loaded
    assert 'reference_applications' not in loaded and 'fast_applications' not in loaded


def test_old_forward_reference_branch_cannot_be_selected():
    with pytest.raises(ValueError,match='NO_OLD_REFERENCE'):run.branch(None,None,None,'REFERENCE',proof_dir=Path('synthetic'))
    with pytest.raises(ValueError,match='NO_OLD_REFERENCE'):run.branch(None,None,None,'REFERENCE')
    with pytest.raises(ValueError,match='NO_OLD_QUALIFY'):run._body('qualify')


def test_evidence_static_spec_metadata_only():
    spec=e.reference_spec()
    assert spec['root_reuse_admission_sha256']==e.ADMISSION and spec['approved_members']==e.APPROVED
    assert set(spec)=={'schema','origin','approved_members','root_reuse_admission_sha256','partial_review_sha256',
        'metadata_review_sha256','final_review_sha256','financial_authority','financial_predecessor_admitted'}


def proof_stub():
    contract={'synthetic_only':True};origin={'synthetic_basis':True}
    basis=dict(source_series=origin,source_series_sha256=e.digest(origin),original_outer_sha256=review.OUTER)
    recorded=dict(origin='OLD_RECORDED_REFERENCE',source_origin=deepcopy(e.ORIGIN),root_reuse_admission_sha256=e.ADMISSION,
        approved_members=deepcopy(e.APPROVED),original_compiler_and_ring_logs_available=False,publications=[])
    restores=dict(origin='NEW_HOSTED_CANONICAL_RESTORE_OF_OLD_RECORDED_DATA',synthetic_wires=18,
        financial_transitions=0,source_gate_adoption=False,financial_authority=False,checked=[{} for _ in range(25)])
    check=dict(origin=source.COMPILER_ORIGIN,financial_transitions=0,refusals=[],source_contract=contract,origin_basis=basis,
        advance_blocker=dict(installed_entrypoints=['runtime.advance','runtime.advance_session','kernel.advance_session',
            'kernel.plan_session','live.plan_session','core_adapter.step_session'],attempted_calls=[],financial_transitions=0),
        prepared_publications=[dict(session=d) for d in ('2020-07-01','2020-07-02')],
        unit_window_anchor_checks=[{},{}],canonical_restores=restores)
    value=dict(schema=source.SCHEMA,source_contract=contract,origin_basis=basis,source_members={},
        recorded_reference=recorded,source_compiler_check=check,
        fresh_execution=dict(origin='NEW_HOSTED_FAST_EXECUTION',applications=[],refusals=[]),
        reference_report_check=dict(origin=source.REPORT_ORIGIN,financial_transitions=0,full_runtime_unchanged=True,
            complete_typed_report_equal=True),financial_authority=False)
    return value,contract,origin


@pytest.mark.parametrize('mutation',['oldlogs','reference_keys','advance','restores','fresh_origin','prepare_count','old_report'])
def test_new_source_proof_never_silently_relabels_old_or_missing_proofs(mutation):
    value,contract,origin=proof_stub();review.source_proof(value,contract,origin,{})
    if mutation=='oldlogs':value['recorded_reference']['original_compiler_and_ring_logs_available']=True
    if mutation=='reference_keys':value['reference_applications']=[]
    if mutation=='advance':value['source_compiler_check']['advance_blocker']['attempted_calls']=['runtime.advance']
    if mutation=='restores':value['source_compiler_check']['canonical_restores']['synthetic_wires']=17
    if mutation=='fresh_origin':value['fresh_execution']['origin']='OLD_RECORDED_REFERENCE'
    if mutation=='prepare_count':value['source_compiler_check']['prepared_publications'].pop()
    if mutation=='old_report':value['reference_report_check']['origin']='OLD_RECORDED_REFERENCE'
    with pytest.raises(ValueError):review.source_proof(value,contract,origin,{})


def test_actual_new_save_wrapper_uses_original_single_exclusive_create(tmp_path,monkeypatch):
    # Deliberately synthetic report metadata, no strategy state or accounting execution.
    monkeypatch.setattr(review,'validate_reuse',lambda evidence:{'synthetic_only':True})
    result=dict(schema='research.p01-iac-unit-suffix-review/1',status='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
        financial_predecessor_admitted=False,qualification_state_adopted=False)
    path=tmp_path/'iac-unit-financial-review.json'
    review.save_review(path,result)
    assert path.is_file() and result['reference_reuse_review']=={'synthetic_only':True}
    assert result['review_recovery']['correction']=='METADATA_BEFORE_ORIGINAL_SINGLE_EXCLUSIVE_CREATE'
    with pytest.raises(ValueError):review.save_review(path,result)


def test_actual_readonly_report_full_source_and_callsite_contract():
    raw=(HERE/'p01_iac_unit_run.py').read_bytes()
    old=json.loads((HERE/'p01_iac_unit_fixture_request.json').read_bytes())['sources']
    pins=json.loads((HERE/'p01_celg_bridge_source_map.json').read_bytes())['successor_all_sources']
    accounting=(HERE/'p01_factual_batch_accounting.py').read_bytes()
    proof=source.report_shape(raw,pins,accounting,old['p01_factual_batch_accounting.py'])
    assert proof['financial_transitions']==0 and proof['report_origin']==source.REPORT_ORIGIN
    assert len(proof['canonical_source_files'])==5
    with pytest.raises(ValueError):source.report_shape(raw+b'\n',pins,accounting,old['p01_factual_batch_accounting.py'])


def test_actual_producer_summary_expression_passes_actual_consumer_gate():
    import p01_iac_reference_export as consumer
    tree=ast.parse(Path(run.__file__).read_bytes())
    function,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
    call,=[n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
        and n.func.id=='save' and ast.unparse(n.args[0])=="proof / 'qualification-summary.json'"]
    aggregate=dict(complete=True,all_passed=True,expected_case_ids=list(consumer.FIXTURE_CASE_IDS))
    zero=dict(input_checkpoint={'sha256':'a'*64},input_document_sha256='b'*64,successor_input_sha256='c'*64)
    reference=dict(component_raw=b'SYNTHETIC_COMPONENT',provenance_raw=b'SYNTHETIC_PROVENANCE')
    def synthetic_hash(raw):
        assert raw in reference.values()
        return e.APPROVED[e.COMPONENT]['sha256'] if raw==reference['component_raw'] else 'd'*64
    values=dict(vars(run),aggregate=aggregate,zero=zero,reference=reference,
        fast=dict(roles=[{'synthetic_only':1},{'synthetic_only':2}],reused={'synthetic_only':True}),sha=synthetic_hash)
    summary=eval(compile(ast.Expression(body=call.args[1]),'<actual-producer-summary-only>','eval'),values)
    consumer.qualification(summary)
    summary.pop('reference_report_rechecked')
    with pytest.raises(ValueError):consumer.qualification(summary)


@pytest.mark.parametrize('mutation',[None,'advance','publication'])
def test_actual_source_check_order_with_source_shaped_metadata_stubs(tmp_path,mutation):
    """Execute only our outside-driver orchestration; all financial APIs are stubs."""
    calls=[];reference=dict(components=[],zero={'successor_input_sha256':'SYNTHETIC12'})
    for day in ('2020-07-01','2020-07-02'):
        before=dict(input_sha256='SYNTHETIC12',state={'data_version':4,'synthetic_only':True})
        reference['components'].append(dict(session=day,prior_checkpoint=before,checkpoint=deepcopy(before),
            publication=dict(session=day,synthetic_only=True)))
    raw=tmp_path/'module.txt';raw.write_bytes(b'SYNTHETIC_MODULE_ONLY')
    modules={n:SimpleNamespace(__file__=str(raw)) for n in ('runtime','kernel','live','core_adapter')}
    rt,kernel,live,core=(modules[n] for n in ('runtime','kernel','live','core_adapter'))
    original=lambda *args,**kwargs:None
    rt.advance=original;rt.advance_session=kernel.advance_session=original
    kernel.plan_session=live.plan_session=original;core.step_session=original
    def restore(cp,**kwargs):
        calls.append(('restore',cp['input_sha256']))
        return SimpleNamespace(snapshot=deepcopy(cp),state=SimpleNamespace(data_version=4),policy='SYNTHETIC',input_sha256='SYNTHETIC12')
    rt.restore=restore;rt.checkpoint=lambda run:deepcopy(run.snapshot)
    class Codec:
        def __init__(self,rows,parent):self.applied=[];self.refusals={};self.origin={'synthetic_only':True}
        def __enter__(self):return self
        def __exit__(self,*args):pass
    codec_holder=[]
    def codec(rows,parent):value=Codec(rows,parent);codec_holder.append(value);return value
    parent=dict(source_cursor='2020-06-30',sha256='SYNTHETIC_OUTER',run={'checkpoint_sha256':'SYNTHETIC_INNER'},base={'policy':'SYNTHETIC'})
    paths={'runtime':'research/pooled_vacancy_funding/runtime.py','kernel':'sentinel/core/kernel.py',
        'live':'shared/stock_strategy_shared/wealth_core/live.py','core_adapter':'shared/stock_strategy_shared/wealth_core/adapter.py'}
    mapping={p:source.sha(raw.read_bytes()) for p in paths.values()};mapping[source.BACKTEST]='SYNTHETIC_BACKTEST'
    binding=SimpleNamespace(parent=parent,source_map={'successor_all_sources':mapping},objects=tuple(range(11)))
    @contextmanager
    def epoch(*a,**k):yield binding
    class Buffer:
        def append(self,packet):
            calls.append(('append',packet.day));self.current=packet
            assert packet.applied==list(range(12))
        def prepare(self,prior,version,**kwargs):
            calls.append(('prepare',self.current.day))
            if mutation=='advance':rt.advance(None,None)
            value=dict(session=self.current.day,synthetic_only=True)
            if mutation=='publication':value['unexpected']=True
            return value
    backtest=SimpleNamespace(__file__=str(raw),START='SYNTHETIC_START',END='SYNTHETIC_END')
    backtest.load_repair=lambda *a,**k:11
    def apply(packet,obj):
        packet.applied.append(obj)
        if obj==11 and packet.day in ('2020-07-01','2020-07-02'):
            codec_holder[-1].applied.append(dict(session=packet.day,derivation_before_buffer_append=True))
        return packet
    backtest.apply_repair=apply
    dates=['SYNTHETIC_WARMUP_'+str(i) for i in range(425)]+['SYNTHETIC_START','2020-06-29','2020-06-30','2020-07-01','2020-07-02','2020-07-06','SYNTHETIC_END']
    packets=[SimpleNamespace(day=d,applied=[]) for d in ('2020-06-29','2020-06-30','2020-07-01','2020-07-02','2020-07-06')]
    tree=ast.parse(Path(source.__file__).read_bytes());node,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='source_check']
    node.body=[n for n in node.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    values=dict(vars(source),hosted=lambda:None,historical_epoch=epoch,InputCodec=codec,backtest=backtest,runtime=rt,
        adapter=SimpleNamespace(),bundle=SimpleNamespace(axis=lambda:dates),inputs=SimpleNamespace(packets=lambda *a,**k:iter(packets)),
        kernel=kernel,live=live,core_adapter=core,source_contract=lambda binding:{'window_length':85},
        resolve_buffer=lambda *a:(Buffer,{'synthetic_only':True}),preparation_shape=lambda *a:{'synthetic_only':True},
        restore_reference=lambda *a:{'synthetic_only':True},unit_scope=lambda *a:[],specification=lambda:{'synthetic_only':True},
        material=lambda value:deepcopy(value),anchor_record=lambda state,record:deepcopy(record),
        window_record=lambda buffer,pub,codec,length:dict(session=pub['session'],full_window_before_feature_bound=True))
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-new-source-check-metadata-stubs>','exec'),values)
    if mutation:
        with pytest.raises(ValueError,match='FINANCIAL_ADVANCE' if mutation=='advance' else 'WHOLE_RECORDED'):
            values['source_check'](tmp_path,tmp_path/'out',[],reference)
    else:
        result=values['source_check'](tmp_path,tmp_path/'out',[],reference)
        assert result['advance_blocker']['attempted_calls']==[]
        assert [row for row in calls if row[0]=='prepare']==[('prepare','2020-07-01'),('prepare','2020-07-02')]
        assert ('append','2020-07-06') not in calls
    assert rt.advance is original and kernel.plan_session is original
