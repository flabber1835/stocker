"""Pure new-input lineage/accounting fixtures; no canonical strategy execution."""
import ast
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
from contextlib import contextmanager

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_accounting as accounting
import p01_iac_unit_review as review
import p01_factual_batch_accounting as qualified
import core_window_review as ordinary


def parent():
    return dict(sha256=review.OUTER,completed=628,source_cursor='2020-06-30',chain='c'*64,
        base={'policy':'SYNTHETIC','sources':{'fixed':'fixed'}},repairs=[{'id':i} for i in range(11)],
        run=dict(input_sha256=review.ORIGINAL_INPUT,checkpoint_sha256=review.INNER,state_sha256=review.STATE,
            state=dict(last_processed_session='2020-06-30',ledger={'events':[]})))


def zero(p):
    adopted=deepcopy(p);adopted['repairs'].append(dict(sha256='b'*64))
    adopted['run']['input_sha256']=review.digest(dict(base=adopted['base'],repairs=adopted['repairs']))
    event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=p['run']['checkpoint_sha256'],
        predecessor_input_sha256=p['run']['input_sha256'],successor_input_sha256=adopted['run']['input_sha256'],
        unchanged_through=p['source_cursor'],earliest_affected_session='2020-07-01')
    adopted['chain']=review.digest(dict(previous=p['chain'],event=event))
    return dict(input_event=event,input_checkpoint=adopted)


_DEFAULT_CHAIN=object()


def daily(p,z,day='2020-07-01',*,chain=_DEFAULT_CHAIN):
    row=dict(session=day,phase='MEASURED',input_sha256=z['input_checkpoint']['run']['input_sha256'],
        state_sha256='s'*64,economics={'whole':'snapshot'})
    row['chain_sha256']=review.digest(dict(previous=z['input_checkpoint']['chain'] if chain is _DEFAULT_CHAIN else chain,
        session=day,state_sha256=row['state_sha256'],economics=row['economics']))
    return row


def test_exact_current_source_and_old11_new12_identity():
    p=parent();z=zero(p);adopted=z['input_checkpoint'];current=deepcopy(adopted)
    current.update(completed=629,source_cursor='2020-07-01');review.same_resume_identity(p,adopted,current)
    for kind in ('source','old_input','new_input','input_hash','old_parent'):
        before=deepcopy(p);bad=deepcopy(current)
        if kind=='source':bad['base']['sources']['fixed']='mutated'
        if kind=='old_input':bad['repairs'][0]={'relabelled':True}
        if kind=='new_input':bad['repairs'][-1]={'different':True}
        if kind=='input_hash':bad['run']['input_sha256']='0'*64
        if kind=='old_parent':before['sha256']='0'*64
        with pytest.raises(ValueError):review.same_resume_identity(before,adopted,bad)


def test_parent_chain_then_actual_input_event_is_only_financial_origin():
    p=parent();z=zero(p);row=daily(p,z);current={'chain':row['chain_sha256']}
    assert review.financial_chain(p,z,[row],current)==current['chain']
    for origin in (None,p['chain']):
        wrong=daily(p,z,chain=origin)
        with pytest.raises(ValueError):review.financial_chain(p,z,[wrong],{'chain':wrong['chain_sha256']})
    wrong=deepcopy(z);wrong['input_event']=None
    with pytest.raises(ValueError):review.financial_chain(p,wrong,[row],current)


@pytest.mark.parametrize('origin',[None,'PARENT_WITHOUT_INPUT_EVENT'])
def test_input_event_chain_guard_removal_falsifier(origin):
    p=parent();z=zero(p);seed=None if origin is None else p['chain'];wrong=daily(p,z,chain=seed)
    with pytest.raises(ValueError):review.financial_chain(p,z,[wrong],{'chain':wrong['chain_sha256']})
    tree=ast.parse((HERE/'p01_iac_unit_review.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='financial_chain')
    target=next(n for n in fn.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='chain' for t in n.targets))
    target.value=ast.Constant(None) if origin is None else ast.parse("parent['chain']",mode='eval').body
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='REVIEW_CANONICAL_INPUT_ZERO_CHAIN' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-input-event-origin>','exec'),ns)
    assert ns['financial_chain'](p,z,[wrong],{'chain':wrong['chain_sha256']})==wrong['chain_sha256']


def commitment(raw):
    return dict(bytes=len(raw),prefix_sha256=review.sha(raw),
        last_record_sha256=review.sha(raw.splitlines(keepends=True)[-1]) if raw else None)


def test_all_four_prefixes_and_partial_tails_preserved():
    old=b'{"old":1}\n';new=b'{"new":2}\n';tail=b'{"partial":'
    p={'journals':{n:commitment(old) for n in ('daily','formation','monthly','watch')}}
    c={'journals':{n:commitment(old+new) for n in p['journals']}}
    rows,tails,proof=review.journal_suffixes(p,c,dict.fromkeys(p['journals'],old),
        dict.fromkeys(p['journals'],old+new+tail))
    assert all(r==[{'new':2}] for r in rows.values())
    assert all(t==dict(bytes=len(tail),sha256=review.sha(tail)) for t in tails.values())
    bad=dict.fromkeys(p['journals'],b'changed'+old+new+tail)
    with pytest.raises(ValueError):review.journal_suffixes(p,c,dict.fromkeys(p['journals'],old),bad)


def test_actual_source_count_unchanged_and_exactly_one_input_watch_event():
    p=parent();event=zero(p)['input_event'];old=[{'schema':'pooled-source-boundary/1'}]
    value=review.boundary_counts(old,[event],event)
    assert value==dict(source_before=1,source_after=1,inputs_before=0,inputs_after=1)
    for suffix in ([],[event,event],[event,{'schema':'pooled-source-boundary/1'}]):
        with pytest.raises(ValueError):review.boundary_counts(old,suffix,event)


def paths(adopted):
    previous=adopted['run'];rows=[]
    for day in review.FIRST:
        cp=deepcopy(previous);cp['state']['last_processed_session']=day
        rows.append(dict(session=day,prior_checkpoint=deepcopy(previous),
            publication={'session':day,'whole':{'kept':True}},checkpoint=cp));previous=cp
    outer=deepcopy(adopted);outer.update(completed=630,source_cursor=review.FIRST[-1],run=rows[-1]['checkpoint'])
    q=dict(schema='research.p01-iac-unit-actual-two-session-component/1',reference_components=deepcopy(rows),
        actual_components=rows,reference_qualifier_checkpoint=deepcopy(outer),qualifier_checkpoint=outer,
        action_checks=[],inherited_native_scope_checks=[],source_unit_scope_checks=[],unit_window_anchor_checks=[],
        pre_event_checkpoints=[],financial_authority=False,qualification_state_adopted=False)
    return rows,q


def test_full_reference_fast_and_separate_fresh_first_two_including_partial_attempt():
    p=parent();adopted=zero(p)['input_checkpoint'];rows,q=paths(adopted)
    finance=dict(actual_components=[],attempted_components=rows[:1],financial_authority=False,qualification_state_adopted=False)
    assert review.first_two(adopted,q,finance,dict(completed=628,source_cursor='2020-06-30'),'2020-07-01')==rows[:1]
    finance.update(actual_components=rows,attempted_components=rows)
    assert review.first_two(adopted,q,finance,dict(completed=630,source_cursor='2020-07-02'),'2020-07-06')==[]
    bad=deepcopy(q);bad['reference_components'][0]['publication']['whole']['kept']=False
    with pytest.raises(ValueError):review.first_two(adopted,bad,finance,dict(completed=630,source_cursor='2020-07-02'),'2020-07-06')
    bad=deepcopy(finance);bad['attempted_components'][0]['checkpoint']['state']['extra']='excluded?'
    with pytest.raises(ValueError):review.first_two(adopted,q,bad,dict(completed=630,source_cursor='2020-07-02'),'2020-07-06')


def test_committed_attempt_filters_cannot_adopt_future_tail_or_skip_committed():
    rows=[{'session':'2020-07-01'},{'session':'2020-07-02'}]
    assert review.committed_attempts(rows[:1],rows,'2020-07-01','2020-07-02')==rows[1:]
    for actual,attempted in [(rows,rows),(rows[:1],rows[1:]),([],rows)]:
        with pytest.raises(ValueError):review.committed_attempts(actual,attempted,'2020-07-01','2020-07-02')


def event(kind,quantity,price,before,delta,detail=None):
    return dict(event_type=kind,security_id='S',session='2020-07-01',shares_delta=quantity,price=price,
        fees=abs(quantity)*price*.001 if kind in ('BUY','SELL') else 0,cash_before=before,cash_delta=delta,
        cash_after=before+delta,detail=detail or {})


def accounting_fixture():
    p=parent();buy=event('BUY',2,10.,50000.,-20.02);cash=buy['cash_after']
    p['run']['state']=dict(ledger={'events':[buy]},wealth_core={'cash':cash,'episodes':{'1':{'security_id':'S','current_shares':2}}})
    accrued=event('DIVIDEND_ACCRUED',0,1.,cash,0,{'amount':2.,'shares':2})
    snapshot=dict(wealth_core=deepcopy(p['run']['state']['wealth_core']),prices={'S':{'raw_price':11.,'status':'CURRENT'}},
        ledger={'events':[buy,accrued],'receivables':[{'security_id':'S','accrued_session':'2020-07-01','amount':2.}]},
        resolved_equity=cash+22+2)
    return p,snapshot


def test_accounting_uses_exact_old_whole_ledger_evaluator_only_new_snapshots():
    p,snapshot=accounting_fixture();before=deepcopy(snapshot)
    ordinary.reconcile(snapshot);expected=qualified.reconcile(snapshot,{},[])
    cursor=accounting.AccountingCursor(p,{},[])
    assert cursor.reconcile(snapshot)==expected and snapshot==before
    result=cursor.result()
    assert result['new_accounting_snapshots']==1 and result['old_snapshot_replays']==0
    assert result['accounting_origin_reset'] is False and result['numerical_tolerances_changed'] is False
    assert result['input_zero_resets_numerical_origin'] is False
    bad=deepcopy(snapshot);bad['resolved_equity']+=.001
    with pytest.raises(ValueError):accounting.AccountingCursor(p,{},[]).reconcile(bad)


def test_accounting_old_ledger_prefix_mutation_and_evaluator_mutation_refuse():
    p,snapshot=accounting_fixture();bad=deepcopy(snapshot);bad['ledger']['events'][0]['extra']='mutation'
    with pytest.raises(ValueError):accounting.AccountingCursor(p,{},[],evaluator=lambda *args:None).reconcile(bad)
    def mutate(value,*args):value['ledger']['events'][0]['extra']='mutation'
    with pytest.raises(ValueError):accounting.AccountingCursor(p,{},[],evaluator=mutate).reconcile(snapshot)


def test_accounting_source_pin_guard_removal_falsifier(monkeypatch):
    p,snapshot=accounting_fixture();monkeypatch.setattr(accounting,'CURSOR_SOURCE','0'*64)
    with pytest.raises(ValueError):accounting.AccountingCursor(p,{},[])
    tree=ast.parse((HERE/'p01_iac_unit_accounting.py').read_bytes())
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='CURSOR_SOURCE' for t in n.targets))
    assignment.value=ast.Constant('0'*64)
    guard=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='EXACT_QUALIFIED_WHOLE_LEDGER_CURSOR_SOURCE' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns={}
    exec(compile(ast.fix_missing_locations(tree),'<accounting-source-pin-removal>','exec'),ns)
    ns['AccountingCursor'](p,{},[])


def test_no_top_level_canonical_runtime_imports():
    for name in ('p01_iac_unit_accounting.py','p01_iac_unit_review.py'):
        for node in ast.parse((HERE/name).read_bytes()).body:
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith(('sentinel','stock_strategy_shared','research.pooled'))


def normalization_fixture():
    normalizer=dict(initial_native_factor_hex=(1.).hex(),initial_combined_factor_hex=(1.).hex(),
        original_signal_multiplier_hex=(1.).hex())
    rows=[dict(security_id='984687283821901795',session=day,split_ratio='1',raw_close=close,
        signal_close=close,raw_compatible_volume='13') for day,close in
        [('2020-06-30','9'),('2020-07-01','4'),('2020-07-02','5')]]
    bars={r['session']:dict(security_id=r['security_id'],raw_close=float(r['raw_close']),raw_open=4.,
        signal_close=float(r['raw_close']),split_ratio=1.,volume=13.,other='preserved') for r in rows}
    records=[]
    for r in rows[1:]:
        day=r['session'];logical=float(r['raw_close'])*float('2.1584')
        entry=dict(session=day,native_factor_hex=(1.).hex(),combined_factor_hex=float('2.1584').hex(),
            logical_signal_close=logical,effective_split_ratio=float('2.1584') if day==review.EVENT else 1.,
            raw_row_sha256=review.digest(r),native_basis_exact=True,canonical_factor_then_raw_order=True,
            legal_factor_insertions=1)
        records.append(dict(entry,native_bar=bars[day],logical_bar=dict(bars[day],
            signal_close=logical,split_ratio=entry['effective_split_ratio']),native_source_metadata={'identity':'kept'},
            child_or_cash_value_added=False,all_raw_price_volume_and_other_fields_unchanged=True,
            source_preimage_authenticated=True,derivation_before_buffer_append=True))
    return rows,normalizer,bars,records


def test_independent_actual_normalization_full_record_native_order_and_scalar_basis():
    rows,n,bars,records=normalization_fixture()
    assert review.normalization_records(records,rows,n,bars)['records']==2
    for key in ('raw_open','volume','other'):
        bad=deepcopy(records);bad[0]['logical_bar'][key]='changed'
        with pytest.raises(ValueError):review.normalization_records(bad,rows,n,bars)
    bad=deepcopy(records);bad[0]['logical_signal_close']+=.0001
    with pytest.raises(ValueError):review.normalization_records(bad,rows,n,bars)
    with pytest.raises(ValueError):review.normalization_records(records,list(reversed(rows)),n,bars)
    bad=deepcopy(rows);bad[1]['signal_close']='4.0001'
    with pytest.raises(ValueError):review.normalization_records(records,bad,n,bars)


def source_state():
    return dict(wealth_core=dict(episodes={},slots={},unresolved_terminals={},terminal_pending_terms={},
        terminal_pending_sessions={},terminal_carry_audit={}),pending=[],ledger=dict(events=[],receivables=[]),
        feed={'series':{'984687283821901795':{'ticker':'IAC'}}},median5={'selected':['984687283821901795']})


def test_source_scope_is_pre_event_only_and_independent_target_roles_are_retained():
    state=source_state();sid='517224929580411308'
    state['wealth_core']['episodes']['1']={'security_id':sid,'exit_pending':True}
    state['pending']=[{'security_id':sid,'intent':'BUY'}]
    proof=review.source_scope(state,review.EVENT)
    assert proof[0]['independent_target_roles'][sid]['episodes']==state['wealth_core']['episodes']
    for field in ('holding','pending','reservation','orphan','receivable','claim'):
        bad=deepcopy(state);source='984687283821901795'
        if field=='holding':bad['wealth_core']['episodes']['2']={'security_id':source,'exit_pending':True}
        if field=='pending':bad['pending'].append({'security_id':source,'intent':'BUY'})
        if field=='reservation':bad['wealth_core']['slots']['2']={'reserved_for':source}
        if field=='orphan':bad['wealth_core']['slots']['2']={'reserved_for':None,'reserved_ticker':'IAC'}
        if field=='receivable':bad['ledger']['receivables'].append({'security_id':source})
        if field=='claim':bad['wealth_core']['terminal_carry_audit'][source]={}
        with pytest.raises(ValueError):review.source_scope(bad,review.EVENT)
        assert review.source_scope(bad,'2020-07-02')==[]


def test_event_ledger_excludes_source_package_without_filtering_independent_target_flows():
    target={'security_id':'517224929580411308','event_type':'SELL','detail':{}}
    row=dict(session=review.EVENT,prior_checkpoint={'state':{'ledger':{'events':[]}}},
        checkpoint={'state':{'ledger':{'events':[target]}}})
    assert review.no_source_entitlement_posting([row])['ordinary_target_events_filtered'] is False
    for event in (dict(security_id='984687283821901795',event_type='DIVIDEND_ACCRUED'),
        dict(security_id='517224929580411308',event_type='SPINOFF_RECEIPT',
            detail={'parent_security_id':'984687283821901795'})):
        bad=deepcopy(row);bad['checkpoint']['state']['ledger']['events'].append(event)
        with pytest.raises(ValueError):review.no_source_entitlement_posting([bad])


def window_fixture():
    rows,n,bars,records=normalization_fixture();r=rows[-1];logical=records[-1]['logical_signal_close']
    signal=dict(security_id=r['security_id'],closes=[logical],raw_close=5.,certified_momentum=3.)
    basis=dict(split_factor=logical/5.,signal_basis_multiplier=1.,vendor_basis_multiplier=1.,
        signal_basis_anchor=[r['session'],5.,logical])
    record=dict(session=r['session'],source_present=True,source_series_retained=True,window_length=3,
        indices=[400,401,402],sessions=[row['session'] for row in rows],
        logical_signal_closes=[9.,records[0]['logical_signal_close'],logical],raw_closes=[9.,4.,5.],
        raw_compatible_volumes=[13.,13.,13.],native_row_sha256=[review.digest(row) for row in rows],
        actual_publication_signal=signal,full_window_before_feature_bound=True,raw_liquidity_domain_unchanged=True,
        actual_retained_basis=basis)
    return rows,n,record


def test_full_window_exact_raw_logical_calendar_and_published_quotient_not_ideal_ratio():
    rows,n,record=window_fixture();publication={'window_features':{'signals':[record['actual_publication_signal']]}}
    review.unit_window(record,rows,n,3,publication=publication,axis=record['sessions'])
    for key in ('raw_closes','logical_signal_closes','raw_compatible_volumes','native_row_sha256','indices'):
        bad=deepcopy(record);bad[key][0]='changed'
        with pytest.raises((ValueError,TypeError)):review.unit_window(bad,rows,n,3,publication=publication,axis=record['sessions'])
    bad=deepcopy(record);bad['actual_retained_basis']['split_factor']+=.0001
    with pytest.raises(ValueError):review.unit_window(bad,rows,n,3)
    absent=dict(session=review.EVENT,source_present=False,source_series_retained=False,unit_factor_not_applied_to_other_ids=True)
    review.unit_window(absent,rows,n,3,publication={'window_features':{'signals':[]}})


def test_actual_two_field_guard_removal_accepts_changed_raw_fixture():
    rows,n,bars,records=normalization_fixture();records[0]['logical_bar']['raw_open']=99.
    with pytest.raises(ValueError):review.normalization_records(records,rows,n,bars)
    tree=ast.parse((HERE/'p01_iac_unit_review.py').read_bytes())
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='normalization_records')
    guard=next(node for node in ast.walk(fn) if isinstance(node,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='REVIEW_ENTIRE_ACTUAL_NATIVE_LOGICAL_RECORD_ONLY_TWO_FIELDS_AND_NO_CHILD_VALUE' for v in ast.walk(node)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-two-field-guard>','exec'),ns)
    assert ns['normalization_records'](records,rows,n,bars)['records']==2


def test_whole_source_proof_refuses_any_member_origin_or_contract_change():
    origin={'series':'synthetic'};contract={'window_length':85};members={'2020':{'sha256':'a'*64}}
    value=dict(schema='research.p01-iac-unit-normalization-source-proof/1',source_contract=contract,
        origin_basis=dict(source_series=origin,source_series_sha256=review.digest(origin),original_outer_sha256=review.OUTER),
        source_members=members,reference_applications=[],fast_applications=[],reference_refusals=[],fast_refusals=[],financial_authority=False)
    review.source_proof(value,contract,origin,members)
    for key in ('source_contract','origin_basis','source_members'):
        bad=deepcopy(value);bad[key]['extra']='not ignored'
        with pytest.raises(ValueError):review.source_proof(bad,contract,origin,members)


def zero_proof_fixture():
    p=parent();p['journals']={'watch':commitment(b'')};z=zero(p);adopted=z['input_checkpoint']
    adopted['sha256']='e'*64;adopted['journals']={'watch':commitment(b'event\n')};event=z['input_event']
    proof=dict(schema='research.p01-iac-unit-zero-boundaries/1',epoch_checkpoint=p,input_checkpoint=adopted,input_event=event,
        prefixes={n:dict(before=c,after=adopted['journals'][n]) for n,c in p['journals'].items()},input_document_sha256='b'*64,
        successor_input_sha256=adopted['run']['input_sha256'],financial_authority=False,financial_predecessor_authorized=False,
        source_epoch_boundary_reemitted=False,input_adoptions=1,old_eleven_input_bytes_unchanged=True,
        source=dict(status='OWN628_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',
            inherited_generic_status='OWN526_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',generic_pause_source_sha256='f'*64,
            outer_sha256=review.OUTER,inner_sha256=review.INNER,state_sha256=review.STATE,input_sha256=review.ORIGINAL_INPUT,
            checkpoint_writes=3,financial_sessions_advanced=0,attempted_financial_transitions=0,
            full_checkpoint_and_journals_unchanged=True,source_boundary_reemitted=False,financial_predecessor_authorized=False),
        input=dict(status='CANONICAL_INPUT_STARTUP_PAUSED_WITH_ZERO_FINANCIAL_SESSIONS',canonical_backtest_startup_invoked=True,
            financial_sessions_advanced=0,attempted_financial_transitions=0,input_adoptions=1,canonical_adoption_checkpoint_writes=2,
            original_checkpoint_sha256=review.OUTER,qualification_checkpoint_sha256=adopted['sha256'],checkpoint_session='2020-06-30',
            completed=628,exact_canonical_boundary_event=event,all_financial_and_controller_state_unchanged=True,
            financial_resume_from_this_copy_authorized=False,production_contacted=False))
    return p,proof


def test_complete_zero_envelope_and_true_own628_generic_provenance():
    p,z=zero_proof_fixture();review.zero_proof(z,p,z['input_event'],'b'*64,'f'*64)
    for kind in ('parent','input_event','advanced','source_label','prefix','extra'):
        bad=deepcopy(z)
        if kind=='parent':bad['epoch_checkpoint']['sha256']='wrong'
        if kind=='input_event':bad['input_event']=None
        if kind=='advanced':bad['input']['financial_sessions_advanced']=1
        if kind=='source_label':bad['source']['status']='OWN627_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS'
        if kind=='prefix':bad['prefixes']['watch']['before']['bytes']=99
        if kind=='extra':bad['input']['ignored_future']='not allowed'
        with pytest.raises(ValueError):review.zero_proof(bad,p,z['input_event'],'b'*64,'f'*64)


def test_complete_status_cannot_promote_partial_or_current_tails():
    partial=dict(source_cursor='2020-07-02',completed=630)
    outcome=dict(status='IAC_UNIT_PARTIAL_OR_REFUSAL_PRESERVED',canonical_return_code=1)
    assert review.complete_status(outcome,partial,2,{'watch':{'bytes':20}},[{'session':'2020-07-06'}]) is False
    wrong=dict(outcome,status='COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW')
    with pytest.raises(ValueError):review.complete_status(wrong,partial,2,{'watch':{'bytes':0}},[])
    current=dict(source_cursor=review.END,completed=879);complete=dict(status='COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW',canonical_return_code=0)
    assert review.complete_status(complete,current,251,{'watch':{'bytes':0}},[]) is True
    for tails,corr in [({'watch':{'bytes':1}},[]),({'watch':{'bytes':0}},[{'uncommitted':True}])]:
        with pytest.raises(ValueError):review.complete_status(complete,current,251,tails,corr)


def test_review_refuses_before_evidence_io_when_not_hosted(monkeypatch):
    import full_system_core
    class NotHosted(Exception):pass
    def refused():raise NotHosted()
    monkeypatch.setattr(full_system_core,'hosted',refused)
    monkeypatch.setattr(review,'Path',lambda *args:pytest.fail('private I/O before hosted gate'))
    with pytest.raises(NotHosted):review.review({},'unused','unused')


def test_actual_review_entry_hydrates_quote_old11_and_authenticates12_before_restore(tmp_path,monkeypatch):
    import full_system_core,p01_iac_unit_contract as contract,p01_iac_unit_epoch as epoch,p01_iac_unit_codec as codec
    log=[];old=tmp_path/'old';evidence=tmp_path/'evidence';out=tmp_path/'out'
    for directory in (old/'book/repairs',evidence/'book/repairs',out):directory.mkdir(parents=True)
    descriptors=[]
    for index in range(12):
        raw=(b'{"synthetic":true}' if index==11 else json.dumps({'synthetic_old':index}).encode())
        h=review.sha(raw);d=dict(filename=h+'.json',sha256=h,resume_session='2020-06-30',predecessor_checkpoint_sha256='p'*64)
        descriptors.append(d);(evidence/'book/repairs'/d['filename']).write_bytes(raw)
        if index<11:(old/'book/repairs'/d['filename']).write_bytes(raw)
    raw=b'{"synthetic":true}';(tmp_path/'input.json').write_bytes(raw);(evidence/'iac-unit-input.json').write_bytes(raw)
    (evidence/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps({'repairs':descriptors}).encode()))
    p={'repairs':descriptors[:11]}
    @contextmanager
    def hydrate(*args,**kwargs):
        log.extend(('historical_quote_authenticated','all_original11_authenticated'))
        yield SimpleNamespace(parent=p,source_gate=SimpleNamespace(allow_input=lambda *args:pytest.fail('review must not register input')))
    class Codec:
        def __init__(self,rows,parent):log.append('new_codec_installed_after_history')
        def __enter__(self):return self
        def __exit__(self,*args):return None
    def load(path,**kwargs):
        log.append('load:'+Path(path).name);return SimpleNamespace(sha256=review.sha(Path(path).read_bytes()))
    fake=ModuleType('research.pooled_vacancy_funding');fake.backtest=SimpleNamespace(load_repair=load,
        main=lambda *args:pytest.fail('review must not startup'))
    package=ModuleType('research');package.__path__=[]
    monkeypatch.setitem(sys.modules,'research',package);monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',fake)
    monkeypatch.setattr(full_system_core,'hosted',lambda:log.append('hosted'))
    monkeypatch.setattr(epoch,'historical_epoch',hydrate);monkeypatch.setattr(codec,'InputCodec',Codec)
    monkeypatch.setattr(codec,'source_rows',lambda **kwargs:([],{}))
    monkeypatch.setattr(contract,'specification',lambda:{'bound':True});monkeypatch.setattr(contract,'document',lambda:{'synthetic':True})
    monkeypatch.setattr(contract,'HERE',tmp_path);monkeypatch.setattr(contract,'INPUT','input.json')
    path=Path;monkeypatch.setattr(review,'Path',lambda value:old if str(value)=='/old' else path(value))
    def finish(*args):
        assert sum(item.startswith('load:') for item in log)==12
        log.append('first_possible_restore');return {'stub':'only'}
    monkeypatch.setattr(review,'review_loaded',finish)
    assert review.review({'bound':True},out,evidence)=={'stub':'only'}
    assert log.index('historical_quote_authenticated')<log.index('all_original11_authenticated')<log.index('new_codec_installed_after_history')
    assert log[-1]=='first_possible_restore'


def test_hosted_review_has_no_startup_adoption_or_advance_callsite():
    tree=ast.parse((HERE/'p01_iac_unit_review.py').read_bytes())
    for fn in [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('review','review_loaded','current_report')]:
        calls=[ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)]
        assert not any(c.endswith(('.advance','.allow_input','.main','.run_backtest')) for c in calls
                       if c not in ('stats.advance',))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review_loaded')
    assert any(isinstance(n,ast.Call) and ast.unparse(n.func)=='adoption' for n in ast.walk(fn))


def test_full_reference_outer_guard_removal_falsifier():
    p=parent();adopted=zero(p)['input_checkpoint'];rows,q=paths(adopted)
    financial=dict(actual_components=rows,attempted_components=rows,financial_authority=False,qualification_state_adopted=False)
    q['reference_qualifier_checkpoint']['extra']='must not exclude'
    current=dict(completed=630,source_cursor='2020-07-02')
    with pytest.raises(ValueError):review.first_two(adopted,q,financial,current,'2020-07-06')
    tree=ast.parse((HERE/'p01_iac_unit_review.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='first_two')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='REVIEW_REFERENCE_FAST_FULL_OUTER_QUALIFIER_CHECKPOINTS' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-full-outer>','exec'),ns)
    assert ns['first_two'](adopted,q,financial,current,'2020-07-06')==[]


def test_full_reports_keep_hosted_values_and_zero_rows_reuse_old_admission():
    expected=dict(canonical_report={'cash':'source_value'},independent_accounting={'whole_ledger':'unchanged'},
        actual_ledger={'events':['all original and new']},full_state_unchanged_by_report=True)
    q=dict(schema='research.p01-iac-unit-actual-accounting-and-report/1',reference=deepcopy(expected),fast=deepcopy(expected),
        reference_equals_fast=True,financial_authority=False,qualification_state_adopted=False)
    review.qualification_report(q,expected)
    wrong=deepcopy(q);wrong['fast']['canonical_report']['cash']='excluded?'
    with pytest.raises(ValueError):review.qualification_report(wrong,expected)
    current=dict(schema='research.p01-iac-unit-current-accounting-and-report/1',
        status='ACTUAL_CURRENT_UNIT_ACCOUNTING_AND_REPORT_VERIFIED',new_committed_transitions=1,current=expected,
        financial_authority=False,qualification_state_adopted=False)
    review.financial_report(current,expected,1)
    empty=dict(current,status='NO_NEW_COMMITTED_ACCOUNTING_REPORT_OLD_ADMISSION_REUSED',new_committed_transitions=0,current=None)
    review.financial_report(empty,None,0)
    with pytest.raises(ValueError):review.financial_report(dict(empty,current=expected),expected,0)


def synthetic_fixture():
    rows,n,bars,records=normalization_fixture();contract={'window_length':3};origin={'ticker':'IAC'}
    names={'shared/stock_strategy_shared/wealth_core/'+v+'.py':'a'*64 for v in ('engine','ledger','funding','prices','marks','v5')}
    configuration={'policy':'SYNTHETIC','fields':{'n_slots':30},'config_hash':'cfg'}
    raw=[10.,8.,8.1];correct=raw[:-2]+[v*float('2.1584') for v in raw[-2:]]
    signal=dict(closes=[correct[-1]],certified_signals=[1.,2.,3.,4.])
    comp_raw,comp_split=next((a,b) for a in (1.3,7.1,13.7,23.2,101.3) for b in (1.1,1.3,1.7,3.3)
        if (a*b)*float('2.1584')!=a*(float('2.1584')*b))
    toy=[dict(session=review.FIRST[0],security_id='984687283821901795',raw_close='10',raw_open='9',
        signal_close='10',split_ratio='1',raw_compatible_volume='99'),
        dict(session=review.FIRST[1],security_id='984687283821901795',raw_close=str(comp_raw),raw_open=str(comp_raw),
        signal_close=str(comp_raw*comp_split),split_ratio=str(comp_split),raw_compatible_volume='99')]
    value=dict(schema='research.p01-iac-unit-synthetic-canonical-component/1',status='UNIT_NORMALIZATION_AND_TARGET_SCOPE_QUALIFIED',
        source_contract=contract,source_files=names,origin_basis_sha256=review.digest(origin),configuration=configuration,
        normalizer_cases=dict(observed_forward=dict(observations=2,source_sessions=list(review.FIRST),
            source_raw_row_sha256=[review.digest(r) for r in rows[1:]],
            reference_signal_hex=[r['logical_signal_close'].hex() for r in records],published_path_exact=True,split_only_falsifier_rejected=True),
            native_composition=dict(synthetic_rows=toy,canonical_signal_hex=[(10.*float('2.1584')).hex(),
                (comp_raw*(float('2.1584')*comp_split)).hex()],published_times_ratio_wrong_hex=((comp_raw*comp_split)*float('2.1584')).hex(),
                associativity_falsifier_rejected=True,raw_factor_chronology_exact=True),
            feature_order=dict(reference_signal=deepcopy(signal),fast_signal=deepcopy(signal),late_unadjusted_certified_signals=[0.,0.,0.,0.],
                late_multiplier_falsifier_rejected=True,full_synthetic_signal_window=correct,synthetic_raw_closes=raw)),
        target_cases={},negative_cases=[dict(case='SPLIT_ONLY',rejected=True),dict(case='LATE_MULTIPLIER',rejected=True)],
        source_scope_falsifiers=[],normalizer_qualified=True,unit_target_independence_qualified=True,
        source_scope_falsifiers_qualified=True,positions_and_orders_synthetic=True,
        normalization_observations_from_authenticated_frozen_input=True,actual_future_roles_claimed=False,
        financial_authority=False,qualification_state_adopted=False)
    for sid in ('517224929580411308','369995575874917058'):
        for role in ('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY'):
            before=source_state();before['wealth_core']['cash']=50000.
            if role!='DOLLAR_BUY_PENDING':
                buy=event('BUY',7,10.,50000.,-70.07);buy['security_id']=sid
                before['ledger']['events']=[buy];before['wealth_core']['cash']=buy['cash_after']
                before['wealth_core']['episodes']['0']=dict(security_id=sid,current_shares=7,
                    exit_pending=role in ('CLOSE_PENDING','EXIT_FLAG_ONLY'))
            if role in ('DOLLAR_BUY_PENDING','CLOSE_PENDING'):
                before['pending']=[dict(security_id=sid,intended_dollars=500.)]
            after=deepcopy(before)
            if role=='DOLLAR_BUY_PENDING':
                buy=event('BUY',49,10.,50000.,-490.49);buy['security_id']=sid
                after['ledger']['events']=[buy];after['wealth_core']['cash']=buy['cash_after']
                after['wealth_core']['episodes']['0']=dict(security_id=sid,current_shares=49,exit_pending=False);after['pending']=[]
            if role=='CLOSE_PENDING':
                sell=event('SELL',-7,10.,before['wealth_core']['cash'],69.93);sell['security_id']=sid
                after['ledger']['events'].append(sell);after['wealth_core']['cash']=sell['cash_after']
                after['wealth_core']['episodes']={};after['pending']=[]
            equity=after['wealth_core']['cash']+sum(e['current_shares']*10. for e in after['wealth_core']['episodes'].values())
            value['target_cases'][sid+'/'+role]=dict(before=before,baseline=deepcopy(after),actual=after,
                audit=dict(prefix=dict(resolved_open_equity=equity),spinoff_audit=[]),target_role=role,entire_full_state_and_fill_result_equal=True)
    reasons={'source_holding':'HOLDING_UNSUPPORTED','source_exit_flag':'HOLDING_UNSUPPORTED',
        'source_future_buy':'ANY_PENDING_UNSUPPORTED','source_close':'ANY_PENDING_UNSUPPORTED',
        'source_reservation':'RESERVATION_OR_ORPHAN_RESERVATION_UNSUPPORTED','source_orphan_reservation':'RESERVATION_OR_ORPHAN_RESERVATION_UNSUPPORTED',
        'source_receivable':'RECEIVABLE_UNSUPPORTED','source_unresolved':'UNRESOLVED_OR_CARRY_CLAIM',
        'source_pending_terms':'UNRESOLVED_OR_CARRY_CLAIM','source_pending_session':'UNRESOLVED_OR_CARRY_CLAIM','source_carry_claim':'UNRESOLVED_OR_CARRY_CLAIM'}
    value['source_scope_falsifiers']=[dict(case=name,error='REFUSED_'+reason,caller_unchanged=True) for name,reason in reasons.items()]
    post_template=source_state();post_template['last_processed_session']=review.EVENT;post_template['last_known']={}
    before=deepcopy(post_template);before['wealth_core']['cash']=50000.
    before['pending']=[dict(security_id='984687283821901795',signal_session=review.EVENT)]
    after=deepcopy(before);after['pending']=[];buy=event('BUY',49,10.,50000.,-490.49)
    buy.update(security_id='984687283821901795',session=review.FIRST[1]);after['ledger']['events']=[buy]
    after['wealth_core']['cash']=buy['cash_after'];after['wealth_core']['episodes']['0']=dict(
        security_id='984687283821901795',current_shares=49,initial_shares=49,episode_peak_split_adjusted_close=10.*float('2.1584'))
    value['post_event_new_unit_case']=dict(before=before,after=after,
        prefix=dict(resolved_open_equity=buy['cash_after']+490.),raw_price=10.,logical_price=10.*float('2.1584'),
        actual_qualifier_clock_state_sha256=review.digest(post_template),raw_execution_and_whole_quantity_canonical=True,
        logical_reference_peak_canonical=True,no_old_package_or_double_split_posted=True,full_canonical_roundtrip=True)
    return value,contract,origin,rows,configuration,{'successor_all_sources':names},post_template,lambda wire:wire


def test_all_eight_saved_target_wires_real_ordinary_fills_and_source_refusals():
    args=synthetic_fixture();assert len(review.synthetic_component(*args))==18
    for kind in ('missing_target','full_wire','source_role','raw_hex','late_feature','missing_falsifier','skipped_buy','old_source_pending_clock','double_split','native_composition'):
        bad=deepcopy(args);value=bad[0];key='517224929580411308/DOLLAR_BUY_PENDING'
        if kind=='missing_target':value['target_cases'].pop(key)
        if kind=='full_wire':value['target_cases'][key]['actual']['pending']=[{'changed':True}]
        if kind=='source_role':value['target_cases'][key]['before']['pending'].append({'security_id':'984687283821901795'})
        if kind=='raw_hex':value['normalizer_cases']['observed_forward']['reference_signal_hex'][0]=(99.).hex()
        if kind=='late_feature':value['normalizer_cases']['feature_order']['late_unadjusted_certified_signals']=[1.,2.,3.,4.]
        if kind=='missing_falsifier':value['source_scope_falsifiers'].pop()
        if kind=='skipped_buy':
            row=value['target_cases'][key];row['actual']=deepcopy(row['before']);row['baseline']=deepcopy(row['before'])
        if kind=='old_source_pending_clock':value['post_event_new_unit_case']['before']['pending'][0]['signal_session']='2020-06-30'
        if kind=='double_split':value['post_event_new_unit_case']['after']['wealth_core']['episodes']['0']['current_shares']*=float('2.1584')
        if kind=='native_composition':value['normalizer_cases']['native_composition']['canonical_signal_hex'][-1]=value['normalizer_cases']['native_composition']['published_times_ratio_wrong_hex']
        with pytest.raises(ValueError):review.synthetic_component(*bad)


def test_component_future_basis_not_prequalified_and_post_spectator_is_canonically_normalized():
    args=list(synthetic_fixture());args[3].append(dict(session='2020-07-06',security_id='984687283821901795',
        split_ratio='unsupported future basis',raw_close='not prequalified'))
    template=args[6];before=args[0]['post_event_new_unit_case']['before'];before['feed']['bounded_by_canonical_restore']=True
    def normalize(wire):
        result=deepcopy(wire);result['feed']['bounded_by_canonical_restore']=True;return result
    args[7]=normalize
    assert len(review.synthetic_component(*args))==18
    before['feed']['unqualified_injection']='must refuse'
    with pytest.raises(ValueError):review.synthetic_component(*args)


def test_native_metadata_is_bound_to_entire_actual_published_metadata_not_rawrow_shortcut():
    rows,n,bars,records=normalization_fixture();path=[dict(session=r['session'],publication={'meta':{
        '984687283821901795':deepcopy(r['native_source_metadata'])}}) for r in records]
    assert review.publication_metadata(records,path)['rawrow_classifier_shortcut_used'] is False
    wrong=deepcopy(records);wrong[0]['native_source_metadata']['extra']='cannot ignore'
    with pytest.raises(ValueError):review.publication_metadata(wrong,path)
    with pytest.raises(ValueError):review.publication_metadata(records[:1],path)


def test_exact_input_zero_receipt_uses_canonical_full_preimage_and_deterministic_encoder():
    p=parent();adopted=zero(p)['input_checkpoint'];encoder=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    buffer=io.BytesIO()
    with gzip.GzipFile(filename='',fileobj=buffer,mode='wb',compresslevel=1,mtime=0) as stream:stream.write(encoder(adopted))
    raw=buffer.getvalue();assert json.loads(gzip.decompress(raw))==adopted
    row=dict(session=review.EVENT,path=review.EVENT+'-'+adopted['sha256']+'.json.gz',outer_sha256=adopted['sha256'],
        inner_sha256=adopted['run']['checkpoint_sha256'],state_sha256=adopted['run']['state_sha256'],prior_session='2020-06-30',
        current_saved_identical_before_guard=True,current_file=dict(bytes=len(raw),sha256=review.sha(raw)))
    review.input_zero_receipt([row],adopted,encoder)
    wrong=deepcopy(row);wrong['current_file']['sha256']='0'*64
    with pytest.raises(ValueError):review.input_zero_receipt([wrong],adopted,encoder)
    with pytest.raises(ValueError):review.input_zero_receipt([row],adopted,lambda v:encoder(v)+b'\n')


def test_actual_preparation_window_is_not_falsely_claimed_as_retained_state():
    rows,n,record=window_fixture();prepared={k:v for k,v in record.items() if k not in ('source_series_retained','actual_retained_basis')}
    review.unit_window(prepared,rows,n,3,prepared=True)
    with pytest.raises(ValueError):review.unit_window(prepared,rows,n,3)
    with pytest.raises(ValueError):review.unit_window(prepared,rows,n,3,prepared=True,checkpoint={'state':{}})


def test_actual_producer_role_count_and_full_records_have_distinct_callsite_contracts():
    tree=ast.parse((HERE/'p01_iac_unit_run.py').read_bytes())
    qualify=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify')
    values={k.arg:ast.unparse(k.value) for n in ast.walk(qualify) if isinstance(n,ast.Call) for k in n.keywords}
    assert values['actual_role_and_full_state_checks']=="len(fast['roles'])"
    assert values['actual_role_and_full_state_records']=="fast['roles']"
    economic=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='economic')
    guard=next(n for n in ast.walk(economic) if isinstance(n,ast.Call) and ast.unparse(n.func)=='UnitGuard')
    assert next(ast.unparse(k.value) for k in guard.keywords if k.arg=='qualified')=="qualified['actual_role_and_full_state_records']"


def last_attempt(arrays):
    all_days=[r['session'] for values in arrays for r in values]
    if not all_days:return None
    day=max(all_days);value=dict(schema='research.p01-iac-unit-last-observed-attempt/1',session=day,financial_authority=False)
    for key,values in zip(('codec_application_sha256','codec_refusal_sha256','prepared_window_sha256','guard_refusal_sha256'),arrays):
        matched=[r for r in values if r['session']==day];value[key]=review.digest(matched[0]) if matched else None
    return value


def tail_fixture():
    axis=['2020-06-30','2020-07-01','2020-07-02','2020-07-06','2020-07-07',review.END,'2021-06-30']
    current=dict(source_cursor='2020-06-30',chain='c'*64,run=dict(state_sha256=review.STATE,input_sha256='i'*64),
        journals={n:commitment(b'') for n in ('daily','formation','monthly','watch')})
    apps=[dict(session=d,actual_native_preimage=review.digest(d)) for d in axis[1:4]]
    prepared=[dict(session=d,actual_prepared_window=review.digest(d)) for d in axis[1:4]]
    outcome=dict(actual_codec_applications=apps,actual_codec_refusals=[],attempted_unit_preparations=prepared,unit_guard_refusals=[])
    outcome['last_observed_attempt']=last_attempt((apps,[],prepared,[]))
    chain=current['chain'];rows=[];previous=review.STATE;correlations=[];corrchain='d'*64
    for index,day in enumerate(axis[1:4],1):
        state=str(index)*64;row=dict(session=day,phase='MEASURED',state_sha256=state,input_sha256='i'*64,economics={'n':str(index)})
        chain=review.digest(dict(previous=chain,session=day,state_sha256=state,economics=row['economics']));row['chain_sha256']=chain
        if index<=2:rows.append(row)
        corr=dict(schema='research.system-campaign-correlation-input/1',session=day,publication_version=index,
            input_sha256='i'*64,prior_state_sha256=previous,next_state_sha256=state,material={'actual':'captured'})
        corrchain=review.digest(dict(previous=corrchain,record=corr));corr['chain_sha256']=corrchain;correlations.append(corr);previous=state
    encode=lambda values:b''.join(json.dumps(r,sort_keys=True,separators=(',',':')).encode()+b'\n' for r in values)
    books=dict(daily=encode(rows)+b'{"incomplete":',formation=b'',monthly=b'',
        watch=encode([dict(session=axis[2],terminal_state={},warnings=['captured warning'])])+b'{"partial')
    old=encode([dict(chain_sha256='d'*64,next_state_sha256=review.STATE)])
    new=old+encode(correlations)
    return current,books,old,new,[],outcome,axis


def test_multi_unsent_tail_is_bounded_contiguous_and_never_financially_admitted():
    args=tail_fixture();value=review.bounded_tail(*args)
    assert value['allowed_uncommitted_sessions']==['2020-07-01','2020-07-02','2020-07-06']
    assert len(value['complete_daily_tail_rows'])==2 and value['attempted_financial_authority']=='UNADMITTED'
    assert value['tail_rows_promoted_to_financial_predecessor'] is False
    assert value['stream_fragments']['daily']['incomplete_bytes']==len(b'{"incomplete":')
    assert value['stream_fragments']['daily']['incomplete_bytes_parsed'] is False
    assert value['uncommitted_full_states']==[dict(session='2020-07-06',status='UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED')]
    actual=[];attempts=[dict(session=d) for d in value['allowed_uncommitted_sessions']]
    assert review.committed_attempts(actual,attempts,'2020-06-30','2020-07-01',value['allowed_uncommitted_sessions'])==attempts


@pytest.mark.parametrize('kind',['wrong_date','gap','duplicate','reorder','forged_failed_day','future_compiler','wrong_daily_chain','wrong_correlation','generic_watch'])
def test_multi_unsent_tail_wrong_axis_order_hash_or_forged_failed_day_refuses(kind):
    args=list(deepcopy(tail_fixture()));current,books,old,new,committed,outcome,axis=args
    rows,proof=review.complete_lines(books['daily'],'fixture')
    if kind=='wrong_date':rows[1]['session']='2020-07-05'
    if kind=='gap':rows=rows[1:]
    if kind=='duplicate':rows.append(deepcopy(rows[-1]))
    if kind=='reorder':rows.reverse()
    if kind=='wrong_daily_chain':rows[1]['chain_sha256']='0'*64
    if kind in ('wrong_date','gap','duplicate','reorder','wrong_daily_chain'):
        books['daily']=b''.join(json.dumps(r).encode()+b'\n' for r in rows)
    if kind=='forged_failed_day':outcome['last_observed_attempt']['session']='2020-07-07'
    if kind=='future_compiler':
        outcome['actual_codec_applications'].append(dict(session='2020-07-07',actual_native_preimage='future'))
        outcome['attempted_unit_preparations'].append(dict(session='2020-07-07',actual_prepared_window='future'))
        outcome['last_observed_attempt']=last_attempt((outcome['actual_codec_applications'],[],outcome['attempted_unit_preparations'],[]))
    if kind=='wrong_correlation':args[3]=new.replace(b'"next_state_sha256":"222',b'"next_state_sha256":"999')
    if kind=='generic_watch':books['watch']=b'{"session":"2020-07-07","untyped":"not an attempt"}\n'
    with pytest.raises(ValueError):review.bounded_tail(*args)


def test_multi_unsent_bound_predicate_removal_falsifier():
    args=list(deepcopy(tail_fixture()));outcome=args[5]
    outcome['actual_codec_applications'].append(dict(session='2020-07-07',actual_native_preimage='future'))
    outcome['attempted_unit_preparations'].append(dict(session='2020-07-07',actual_prepared_window='future'))
    outcome['last_observed_attempt']=last_attempt((outcome['actual_codec_applications'],[],outcome['attempted_unit_preparations'],[]))
    with pytest.raises(ValueError):review.bounded_tail(*args)
    tree=ast.parse((HERE/'p01_iac_unit_review.py').read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='bounded_tail')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='REVIEW_LAST_OBSERVED_ATTEMPT_ONLY_CLOSED_TAIL_OR_ONE_NEXT_DAY' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-observed-tail-bound>','exec'),ns)
    assert ns['bounded_tail'](*args)['allowed_uncommitted_sessions'][-1]=='2020-07-07'
