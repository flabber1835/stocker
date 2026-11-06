"""Actual authenticated JSON/CSV/AST and explicitly noncanonical scope DTO tests."""
import ast,gzip,importlib,json,stat,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest

C=Path(__file__).resolve().parents[2]
D=C
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
sys.path[:0]=[str(D),str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P06_BBIG_DATA_ONLY_FENCE:'+fullname)
FENCE=Fence();sys.meta_path.insert(0,FENCE)
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models
import system_campaign_p06_BBIG_api as api
import system_campaign_p06_BBIG_seed as seeds
import system_campaign_p06_BBIG_observer as observer
import system_campaign_p06_BBIG_runtime as runtime

def read(p):return Path('\\\\?\\'+str(Path(p).resolve())).read_bytes()
def ext(p):return Path('\\\\?\\'+str(Path(p).resolve()))
def function(raw,name):return next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
def dump(tree):return ast.dump(tree,include_attributes=False)
def removed(fn,label,namespace):
    tree=deepcopy(fn);sites=[]
    for node in ast.walk(tree):
        for field,value in ast.iter_fields(node):
            if isinstance(value,list):
                for i,item in enumerate(value):
                    if isinstance(item,ast.Expr) and isinstance(item.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value==label for a in item.value.args):
                        value[i]=ast.Pass();sites.append(item)
    assert len(sites)==1
    namespace=dict(namespace);exec(compile(ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[])),'<meaningful-guard-removal>','exec'),namespace)
    return namespace[tree.name]
@pytest.fixture(scope='module')
def actual():
    source=R/'source335-P06-source-snapshot/capture-P06-13516337974-001'
    manifest=json.loads(read(source/'authenticated-manifest.json'))['members'];raw=read(source/'verified-output/spec.json')
    assert dict(bytes=len(raw),sha256=data.sha(raw))==manifest['spec.json'];spec=json.loads(raw)
    capture=R/'financial330-source-snapshot/capture-P06-13482378564-001'
    mf=json.loads(read(capture/'authenticated-manifest.json'))['members'];root=capture/'verified-output'
    def member(n):
        raw=read(root/n);assert dict(bytes=len(raw),sha256=data.sha(raw))==mf[n];return raw
    cp=json.loads(gzip.decompress(member(spec['selected_checkpoint'])));rows=[json.loads(v) for v in member('uncertainty-certificate.jsonl').splitlines()][:130]
    return spec,cp,rows,ext(root),member
@pytest.fixture(scope='module')
def catalog():return data.catalog()
def test_actual_parent130_and_all_prior_gzip_bytes(actual):
    spec,cp,rows,root,member=actual
    assert data.parent_contract(cp,spec) and seeds.whole_prefix(root,cp,rows)
    assert len(cp['run']['state']['ledger']['events'])==1220
    assert not data.original.mentions_source(cp['run']['state']['ledger']['events'],(data.SID,'BBIG'))
    originals=seeds.initial.seed_reader(inherited_root=C)(root,cp)
    assert originals==rows and len(originals)==130
def test_actual_full10_original_history_and_new_visitor(actual):
    spec,cp,rows,root,member=actual;old=models.original;initial=models.initial.catalog()
    metadata=importlib.import_module('system_campaign_financial_partial').root_spec('P06',initial['parent_root_admission_sha256'])
    origin=old.DIRECTORY+'/'
    kwargs=dict(root_metadata=metadata,input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),
        initial_parent=json.loads(gzip.decompress(member(origin+old.PARENT))),
        ordinary_neutral=json.loads(gzip.decompress(member(origin+old.ORDINARY))),
        typed_neutral=json.loads(gzip.decompress(member(origin+old.TYPED))),member=member)
    assert models.bound_history()(root,cp,initial,**kwargs)==old.history(root,cp,initial,**kwargs)
    bad=deepcopy(cp);bad['repairs'].append(deepcopy(bad['repairs'][-1]))
    with pytest.raises(ValueError):models.bound_history()(root,bad,initial,**kwargs)
def test_actual130_metadata_and_historical_full10_event(actual):
    spec,cp,rows,root,member=actual
    allowed,resolutions=seeds.prior_event(root,cp,rows,cp)
    hashes=json.loads((C/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    result=seeds.qualify_metadata(cp,spec,rows,rows,resolutions,allowed,member(resolutions[0]['actual']),hashes,hashes)
    assert result['committed_rows']==130 and result['second_event_authorized'] is False
    bad=deepcopy(rows);bad[-1]['chain_sha256']='0'*64
    with pytest.raises(ValueError):seeds.qualify_metadata(cp,spec,bad,rows,resolutions,allowed,member(resolutions[0]['actual']),hashes,hashes)
def test_whole_original_retained_seed_on_actual130_DATA(actual):
    spec,cp,rows,root,member=actual
    hashes=json.loads((C/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    def contract(current,target):
        assert current==cp and target==spec and data.parent_contract(current,target)
        # DATA contract checks authenticated committed source identities. Fresh
        # generated /variant physical bytes remain a mandatory hosted gate.
        assert len(hashes)==6 and all(current['base']['sources'][n]==h for n,h in hashes.items())
        assert json.loads(member('branch-controller-qualification.json'))['exact_controller_sources']==hashes
        return hashes
    def visitor(where,current):
        assert where==root and current==cp
        test_actual_full10_original_history_and_new_visitor(actual)
    result=seeds.bind_seed(contract=contract,visitor=visitor)(root,cp,spec)
    assert result==(hashes,rows,member('branch-controller-qualification.json'))
def test_literal34_catalog_prefix_selector_and_original_code(catalog):
    chosen=data.selected('P06',cursor='2023-06-30')
    assert chosen[2]==[catalog['terms'][-1]] and chosen[0].catalog==catalog
    assert data.selector().__code__ is data.original.own_cash_selection.__code__
    assert (data.original.OWN_CASH_PHASES.get(('P06','2023-06-30')),len(json.loads((C/data.original.OWN_CASH_CATALOG).read_bytes())['terms']))==(None,34)
@pytest.mark.parametrize('fault',range(15))
def test_full_source_native_quote_and_scope_corruption(catalog,fault):
    term=deepcopy(catalog['terms'][-1])
    if fault==0:term['identity_witness']['security_type_eligible']='0'
    elif fault==1:term['identity_witness']['issuer_id']='SEC_UNKNOWN:'+data.SID
    elif fault==2:term['source_capture']['artifact_id']+=1
    elif fault==3:term['native']['reference']='actions/acquisition'
    elif fault==4:term['added']['cash_per_share']=0.
    elif fault==5:term['research_assumption']['retained_raw_close']='3.8799999999999999'
    elif fault==6:term['portfolio_completion_authorized']=True
    elif fault==7:term['require_unowned_and_unordered']=False
    elif fault==8:term['research_assumption']['held_settlement_supported']=True
    elif fault==9:term['retained_quote']['raw_close']=3.89
    elif fault==10:term['preopen_completion_confirmed']=True
    elif fault==11:term['parent_positions']=[dict(slot_id=1,ticker='BBIG',quantity=1,entry_date='2023-06-30')]
    elif fault==12:term['native_session']='2023-07-28'
    elif fault==13:term['research_assumption']['actual_settlement_claimed']=True
    elif fault==14:term['source_capture']['independent_qualification_sha256']='0'*64
    with pytest.raises((ValueError,KeyError)):data.qualify_member(term)
def test_whole_source_binding_undo():
    raw=Path(data.cash.__file__).read_bytes();tree=data.source_tree(raw)
    tree.body.insert(0,ast.ImportFrom(module='system_campaign_financial_future',names=[ast.alias(name='registered_scope')],level=0))
    for n in ast.walk(tree):
        if isinstance(n,ast.Constant) and n.value=='research.independent-forward-source-DATA-validation/2':n.value='research.independent-frozen-source-data-validation/1'
    assert dump(tree)==dump(function(raw,'source_binding'))
    member=data.source_member_tree(raw).body[-1]
    original=next(n for n in ast.walk(function(raw,'validate')) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='CASH_BATCH_EXACT_SOURCE_NATIVE_ROLE_AND_CLOCK' for a in n.value.args))
    assert dump(member)==dump(original)
def test_whole_models_history_undo():
    raw=Path(models.original.__file__).read_bytes();tree=models.history_tree(raw)
    choices=next(n for n in ast.walk(tree) if isinstance(n,ast.Tuple) and ast.unparse(n)=='(8, 9, 10, 11)');choices.elts.pop()
    equality=next(n for n in ast.walk(tree) if isinstance(n,ast.Compare) and ast.unparse(n)=="typed_neutral['repairs'] == cp['repairs'][:10]")
    equality.comparators[0]=ast.parse("cp['repairs']",mode='eval').body
    h=next(n for n in ast.walk(tree) if isinstance(n,ast.Compare) and ast.unparse(n)=="typed_neutral['run']['input_sha256'] == input_hash(typed_neutral['base'], typed_neutral['repairs'])")
    h.comparators[0]=ast.parse("cp['run']['input_sha256']",mode='eval').body
    tree.args.kwonlyargs=tree.args.kwonlyargs[:-2];tree.args.kw_defaults=tree.args.kw_defaults[:-2];tree.body.pop(-2)
    next(k for k in tree.body[-1].value.keywords if k.arg=='full_inputs').value=ast.Constant(10)
    assert dump(tree)==dump(function(raw,'history'))
def test_whole_seed_and_remaining_and_adoption_undo():
    raw=Path(seeds.legacy.__file__).read_bytes();tree=seeds.seed_tree(raw)
    imp=next(n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches')
    imp.names=[ast.alias(name='validate_input'),ast.alias(name='seed'),*imp.names]
    assert dump(tree)==dump(function(raw,'retained_seed'))
    raw=Path(data.original.__file__).read_bytes();tree=api.remaining_tree(raw)
    block=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'")
    imp,added,tail=block.body;imp.names.append(ast.alias(name='validate_input'));block.body=[imp,added.orelse[0],tail]
    assert dump(tree)==dump(function(raw,'remaining_ordinary_terms'))
    raw=Path(runtime.legacy.__file__).read_bytes();tree=runtime.adoption_tree(raw)
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    node.value.keys.pop();node.value.values.pop()
    assert dump(tree)==dump(function(raw,'paused_own_adoption'))
@pytest.mark.parametrize('name',['preserve','run','review'])
def test_whole_retained_body_undo(name):
    raw=Path(runtime.retained.__file__).read_bytes();tree=runtime.retained_tree(raw,name)
    if name=='preserve':
        for n in ast.walk(tree):
            if isinstance(n,ast.Constant) and type(n.value)is int and n.value==147:n.value=18
    else:
        imp=next(n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_p06_BBIG_seed')
        imp.module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
        if name=='review':imp.names[0].name='review'
        for n in ast.walk(tree):
            if isinstance(n,ast.Constant) and type(n.value)is int and n.value==130:n.value=6
    assert dump(tree)==dump(function(raw,name))
def test_whole_point_metadata_undo():
    raw=Path(seeds.point.__file__).read_bytes();tree=seeds.metadata_tree(raw)
    for n in ast.walk(tree):
        if isinstance(n,ast.Constant):
            if type(n.value)is int and n.value==13482378564:n.value=13478656632
            elif type(n.value)is int and n.value==1383:n.value=1259
            elif n.value=='2023-06-30':n.value='2022-12-30'
    replacements={"proof['rows'] == 124":6,"proof.get('retained_rows', 0) == 6":0,'len(rows) == len(committed) == 130':6}
    for n in ast.walk(tree):
        if isinstance(n,ast.Compare) and ast.unparse(n) in replacements:n.comparators[-1]=ast.Constant(replacements[ast.unparse(n)])
    tree.args.kw_defaults[-1]=ast.Name(id='SIX_PREFIX',ctx=ast.Load())
    assert dump(tree)==dump(function(raw,'qualify_seed_metadata'))
def test_whole_original_factory_undo_and_all_API_code_objects(actual):
    spec,cp,rows,root,member=actual
    raw=Path(seeds.initial.__file__).read_bytes();tree=seeds.point.factory_tree(raw)
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='material')
    assignment.value.keywords=[k for k in assignment.value.keywords if k.arg!='growth']
    guard=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='P06_ABMD_INITIAL_HAS_NO_PRIOR_B19_SEED' for a in n.value.args))
    guard.args[0]=ast.parse('self.seed == [] and self.math is self.pending is None',mode='eval').body
    assert dump(tree)==dump(function(raw,'certificate_class'))
    bound=api.api(cp,spec)
    for name in api.FUNCTIONS:assert getattr(bound,name).__code__ is getattr(data.original,name).__code__
def noncanonical_scope_dto(catalog):
    """Explicitly noncanonical minimal absence DTO, never a checkpoint or seed."""
    term=deepcopy(catalog['terms'][-1]);scope=dict(schema='research.never-held-source-exit-scope/1',arm='P06',
        parent_outer_sha256=data.OUTER,parent_root_admission_sha256=data.ROOT,hydrated_sha256='a'*64,overlay_sha256='b'*64,
        terminal_sha256=data.digest(term['added']),session='2023-07-27',security_id=data.SID,source_valuation_phase='CLOSE',
        portfolio_completion_authorized=False,require_unowned_and_unordered=True,source_ticker='BBIG',require_never_held=True)
    wealth=dict(episodes={},slots={},terminal_pending_terms={},terminal_pending_sessions={},unresolved_terminals={},terminal_carry_audit={})
    ledger=dict(events=[],receivables=[]);state=dict(wealth_core=wealth,pending=[],ledger=ledger)
    record=dict(session='2023-07-27',passed=True,financial_source_changed=False,stock=[],risk=[],engine_calls=0,order=['CASH:'+data.SID],
        source_prior_absent=True,cash=[dict(session='2023-07-27',security_id=data.SID,actual_context_call=True,
        postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.),source_only_noop=True)],
        source=[dict(security_id=data.SID,actual_context_call=True,original_function_delegated=True,source_value_returned=False,
            portfolio_completion_authorized=False,scope_sha256=data.digest(scope))])
    return term,scope,state,record
@pytest.mark.parametrize('fault',range(10))
def test_original_neverheld_whole_scope_refuses_owned_ordered_or_historical(catalog,fault):
    term,scope,state,record=noncanonical_scope_dto(catalog);sid=data.SID
    if fault==0:state['wealth_core']['episodes']['1']=dict(security_id=sid)
    elif fault==1:state['wealth_core']['slots']['1']=dict(occupied_by=sid,reserved_for=None)
    elif fault==2:state['wealth_core']['slots']['1']=dict(occupied_by=None,reserved_for=sid)
    elif fault==3:state['pending']=[dict(security_id=sid)]
    elif fault in (4,5,6,7):state['wealth_core'][('terminal_pending_terms','terminal_pending_sessions','unresolved_terminals','terminal_carry_audit')[fault-4]][sid]={}
    elif fault==8:state['ledger']['receivables']=[dict(security_id=sid)]
    elif fault==9:state['ledger']['events']=[dict(detail=dict(previous_ticker='BBIG'))]
    with pytest.raises(ValueError):data.original.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],scope)
def test_source_noop_record_and_original_method_identity(catalog):
    term,scope,state,record=noncanonical_scope_dto(catalog)
    assert observer.source_record(record,term,scope,state,state,[],source_was_selected=False)['actual_noop'] is True
    event=data.original.ActualEvents.__new__(data.original.ActualEvents);event.scopes=[scope];event.terms={(term['added']['session'],data.SID):term['added']}
    cash=[deepcopy(next(t for t in catalog['terms'] if t['ticker']=='TRQ'))]
    observer.merge_cash(event,cash)
    assert event.advance.__func__ is data.original.ActualEvents.advance and event.source_values.__func__ is data.original.ActualEvents.source_values
@pytest.mark.parametrize('fault',range(7))
def test_source_noop_complete_call_set_and_real_delegation_falsifiers(catalog,fault):
    term,scope,state,record=noncanonical_scope_dto(catalog)
    if fault==0:record['source']=[]
    elif fault==1:record['source'][0]['original_function_delegated']=False
    elif fault==2:record['cash'][0]['postcondition']['nominal_cash']=3.88
    elif fault==3:record['cash'][0]['actual_context_call']=False
    elif fault==4:record['order'].append('CASH:EXTRA')
    elif fault==5:record['source'][0]['scope_sha256']='0'*64
    elif fault==6:record['source'][0]['source_value_returned']=False
    with pytest.raises(ValueError):observer.source_record(record,term,scope,state,state,[],source_was_selected=fault==6)
def test_meaningful_history_guard_removal(catalog):
    term,scope,state,record=noncanonical_scope_dto(catalog);state['ledger']['events']=[dict(ticker='BBIG')]
    with pytest.raises(ValueError):data.original.require_source_scope(state['wealth_core'],[],state['ledger'],scope)
    mutant=removed(function(Path(data.original.__file__).read_bytes(),'require_source_scope'),'FUTURE_SOURCE_EXIT_NO_HISTORICAL_OWNERSHIP',vars(data.original))
    mutant(state['wealth_core'],[],state['ledger'],scope)
@pytest.mark.parametrize('label,kind',[
    ('P06_BBIG_EXACT_ENTIRE_SOURCE_DAY_CALL_SET','extra-order'),
    ('P06_BBIG_ACTUAL_ZERO_VALUE_NOOP_AND_UNCHANGED_SOURCE_DELEGATION','false-delegation')])
def test_meaningful_observer_guard_removal(catalog,label,kind):
    term,scope,state,record=noncanonical_scope_dto(catalog)
    if kind=='extra-order':record['order'].append('EXTRA')
    else:record['source'][0]['original_function_delegated']=False
    with pytest.raises(ValueError):observer.source_record(record,term,scope,state,state,[],source_was_selected=False)
    mutant=removed(function(Path(observer.__file__).read_bytes(),'source_record'),label,vars(observer))
    mutant(record,term,scope,state,state,[],source_was_selected=False)
def test_meaningful_source_binding_guard_removal():
    value=data.pinned(data.SOURCE,data.SOURCE_SHA);value['parent_outer_sha256']='0'*64
    with pytest.raises(ValueError):data.source_binding(value)
    namespace=dict(vars(data.cash),registered_scope=data.registered_scope)
    mutant=removed(data.source_tree(Path(data.cash.__file__).read_bytes()),'CASH_BATCH_EXACT_ADMITTED_PARENT',namespace)
    assert len(mutant(value))==3
def test_meaningful_full_source_member_guard_removal(catalog):
    value=data.pinned(data.SOURCE,data.SOURCE_SHA);payload,review,q=data.source_binding(value);index=15
    term=deepcopy(catalog['terms'][-1]);term['identity_witness']['issuer_id']='WRONG'
    namespace=dict(vars(data.cash));tree=data.source_member_tree(Path(data.cash.__file__).read_bytes())
    exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-source-member-test>','exec'),namespace)
    args=(value,term,payload['terms'][index],payload['scope']['terms'][index],review['terms'][index],catalog['terms'][-1]['source_capture'])
    with pytest.raises(ValueError):namespace['check'](*args)
    removed(tree,'CASH_BATCH_EXACT_SOURCE_NATIVE_ROLE_AND_CLOCK',namespace)(*args)
def test_meaningful_exact130_metadata_guard_removal(actual):
    spec,cp,rows,root,member=actual
    allowed,resolutions=seeds.prior_event(root,cp,rows,cp)
    hashes=json.loads((C/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    bad=deepcopy(rows);bad[-1]['chain_sha256']='0'*64
    with pytest.raises(ValueError):seeds.qualify_metadata(cp,spec,bad,rows,resolutions,allowed,member(resolutions[0]['actual']),hashes,hashes)
    namespace=dict(vars(seeds.point),SAVED_OUTER=data.OUTER,SAVED_GZIP=spec['selected_file'],LAST_CHAIN=seeds.LAST,PREFIX=seeds.PREFIX)
    mutant=removed(seeds.metadata_tree(Path(seeds.point.__file__).read_bytes()),'P06_POINT_LITERAL_SIX_ADMITTED_PROOFS_NO_UNADMITTED_TAIL',namespace)
    assert mutant(cp,spec,bad,rows,resolutions,allowed,member(resolutions[0]['actual']),hashes,hashes)['passed'] is True
def test_hook_restoration_on_preflight_abort(actual,monkeypatch,tmp_path):
    spec,cp,rows,root,member=actual
    core=importlib.import_module('full_system_core');monkeypatch.setattr(core,'hosted',lambda:None)
    partial=importlib.import_module('system_campaign_financial_partial')
    module=SimpleNamespace(factual_overlay_needed=lambda target:False)
    saved=(partial.retained_models,partial.model_context,runtime.legacy.uncertainty_phase,runtime.legacy.run,runtime.legacy.review,module.factual_overlay_needed)
    request=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        **{runtime.FIELD:{'P06':runtime.declaration(spec)}})
    with pytest.raises(RuntimeError,match='EXPLICIT_TEST_ABORT'):
        with runtime.entry_context(module,spec,mode='preflight',old=root,out=tmp_path,request=request):
            assert module.factual_overlay_needed(spec) is True
            raise RuntimeError('EXPLICIT_TEST_ABORT')
    assert (partial.retained_models,partial.model_context,runtime.legacy.uncertainty_phase,runtime.legacy.run,runtime.legacy.review,module.factual_overlay_needed)==saved
def filesystem_only_view(tmp_path,*,prefix='p06-BBIG-real-neutral-seed-view-test',watch=True):
    """No checkpoints: plain NONCANONICAL filesystem permission test material."""
    out=tmp_path/'out';owned=out/prefix;view=owned/'view';(view/'book').mkdir(parents=True)
    selected=view/'immutable-noncanonical-test.txt';selected.write_text('NONCANONICAL-IMMUTABLE-PERMISSION-FIXTURE')
    selected.chmod(stat.S_IREAD)
    if watch:
        p=view/'book/watch.jsonl';p.write_text('NONCANONICAL-WATCH-PERMISSION-FIXTURE');p.chmod(stat.S_IREAD)
    return out,owned,view,selected
def test_owned_filesystem_permission_conformance_only(tmp_path,monkeypatch):
    out,owned,view,selected=filesystem_only_view(tmp_path)
    origin=tmp_path/'NONCANONICAL-original.txt';origin.write_text('NONCANONICAL-ORIGINAL');origin.chmod(stat.S_IREAD)
    before=(selected.read_bytes(),selected.stat().st_mode,origin.read_bytes(),origin.stat().st_mode)
    old=Path.chmod;calls=[]
    def chmod(path,mode,*a,**k):
        assert path.resolve().is_relative_to(view.resolve());calls.append((path,mode));return old(path,mode,*a,**k)
    monkeypatch.setattr(Path,'chmod',chmod)
    receipt=runtime.owned_view_permissions(view,owned,out)
    assert receipt['owned_directories']==2 and receipt['original_source_permissions_changed'] is False
    assert {p for p,m in calls}=={view,view/'book',view/'book/watch.jsonl'}
    assert (selected.read_bytes(),selected.stat().st_mode,origin.read_bytes(),origin.stat().st_mode)==before
@pytest.mark.parametrize('fault',['wrong-prefix','wrong-output','wrong-view','missing-watch','symlink-member','escaped-member'])
def test_permission_full_target_set_validated_before_any_chmod(tmp_path,monkeypatch,fault):
    out,owned,view,selected=filesystem_only_view(tmp_path,prefix='wrong-name' if fault=='wrong-prefix' else 'p06-BBIG-real-neutral-seed-view-test',watch=fault!='missing-watch')
    if fault=='wrong-output':out=tmp_path/'other-output'
    elif fault=='wrong-view':view=owned/'book';view.mkdir()
    elif fault=='symlink-member':
        old=Path.is_symlink;monkeypatch.setattr(Path,'is_symlink',lambda p:p==selected or old(p))
    elif fault=='escaped-member':
        old=Path.resolve;monkeypatch.setattr(Path,'resolve',lambda p,*a,**k:tmp_path/'outside' if p==selected else old(p,*a,**k))
    calls=[];monkeypatch.setattr(Path,'chmod',lambda p,*a,**k:calls.append(p))
    with pytest.raises(ValueError):runtime.owned_view_permissions(view,owned,out)
    assert calls==[]
def test_meaningful_owned_permission_target_guard_removal(tmp_path,monkeypatch):
    out,owned,view,selected=filesystem_only_view(tmp_path,prefix='wrong-name')
    calls=[];monkeypatch.setattr(Path,'chmod',lambda p,*a,**k:calls.append(p))
    with pytest.raises(ValueError):runtime.owned_view_permissions(view,owned,out)
    assert calls==[]
    mutant=removed(function(Path(runtime.__file__).read_bytes(),'owned_view_permissions'),
        'P06_BBIG_PERMISSION_TARGET_ONLY_EXPLICIT_OWNED_OUTPUT_VIEW',vars(runtime))
    mutant(view,owned,out);assert calls
def test_original_real_kernel_and_terminal_frame_falsifiers():
    frame=sys._getframe();other=(lambda:None).__code__
    assert data.original.actual_source_call(frame,other,object(),object()) is False
    assert data.original.actual_terminal_call(frame,other,object(),object(),'2023-07-27') is False
@pytest.mark.parametrize('name',['research.pooled_vacancy_funding.backtest','stock_strategy_shared.wealth_core','sentinel.controller','numpy','pandas'])
def test_import_fence(name,monkeypatch):
    monkeypatch.setattr(sys,'meta_path',[FENCE,*[v for v in sys.meta_path if v is not FENCE]])
    assert not any(v==name or v.startswith(name+'.') for v in sys.modules)
    with pytest.raises(ImportError,match='P06_BBIG_DATA_ONLY_FENCE'):importlib.import_module(name)
def test_all_private_sources_syntax_and_exact_request(actual):
    spec,cp,rows,root,member=actual
    for name in runtime.source_names():
        if name.endswith('.py'):compile(read(D/name),name,'exec')
    def before():return dict(sources={},admitted_checkpoints={'P06':data.OUTER},arm_inputs={'P06':dict(new_factual_overlay=False)})
    request=runtime.expected_request(before,execution_mode=runtime.MODE,selected_arms=['P06'],root_lookup=lambda arm:spec)
    request.update(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False)
    assert runtime.selected(spec,request) and request['arm_inputs']['P06']['new_factual_overlay'] is True
    request[runtime.FIELD]['P06']['committed_seed_rows']=6
    assert not runtime.selected(spec,request)
