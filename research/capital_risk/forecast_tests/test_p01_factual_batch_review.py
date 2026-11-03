"""Pure saved-record arithmetic/scope tests; never execute canonical finance."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import math

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import p01_factual_batch_accounting as accounting
import p01_factual_batch_review as review


def action(kind='CASH_MERGER'):
    return dict(action_id='SYNTHETIC',source_security_id='SOURCE',source_ticker='SOURCE',economic_session='2021-02-05',
        clock_scope='KNOWN_COMPLETION_BEFORE_OPEN',held_representation_scope='CANONICAL_EXACT_INTEGRAL_ONLY',
        kind=kind,cash_per_share='19.25' if kind=='CASH_MERGER' else None,
        exchange_ratio=None if kind=='CASH_MERGER' else '0.55',delivered_security_id=None if kind=='CASH_MERGER' else 'TARGET',
        delivered_ticker=None if kind=='CASH_MERGER' else 'TARGET',
        delivered_issuer_id=None if kind=='CASH_MERGER' else 'SYNTHETIC_TARGET_ISSUER',primary_reference='https://example.test/legal')


def cash_event():
    return dict(security_id='SOURCE',ticker='SOURCE',session='2021-02-05',event_type='CASH_MERGER',
        reason='CASH_MERGER',detail=dict(shares=5,reference='https://example.test/legal'),fees=0,
        shares_delta=-5,price=19.25,cash_delta=96.25,cash_before=1000,cash_after=1096.25)


def conversion_event():
    return dict(security_id='SOURCE',ticker='SOURCE',session='2021-02-05',event_type='CONVERSION',reason='CONVERSION',
        detail=dict(shares_in=10,shares_delivered=5.5,reference='https://example.test/legal',
            delivered_security_id='TARGET',delivered_ticker='TARGET',exchange_ratio_exact='0.55',
            exact_fractional_entitlement='0',cash_in_lieu=0,cash_consideration=0),fees=0,
        shares_delta=-4.5,price=None,cash_delta=0,cash_before=1000,cash_after=1000)


def state():
    return dict(wealth_core={'episodes':{'1':dict(security_id='SOURCE',current_shares=10,initial_shares=20),
                                       '2':dict(security_id='SOURCE',current_shares=10,initial_shares=20)}},
                pending=[],median5={'selected':['SOURCE']})


def test_exact_cash_terms_and_no_state_mutation():
    event=cash_event();before=deepcopy(event)
    proof=accounting.action_flows([event],[action()])[0]
    assert proof['legal_cash_exact']=='385/4' and proof['source_shares_exact']=='5'
    assert event==before and proof['market_quote_invented'] is False


@pytest.mark.parametrize('field,value',[('price',19.0),('cash_delta',95.0),('fees',1),('session','2021-02-04'),
    ('event_type','TERMINAL_LIQUIDATION')])
def test_wrong_cash_or_clock_or_proxy_refuses(field,value):
    event=cash_event();event[field]=value
    with pytest.raises(ValueError):accounting.action_flows([event],[action()])


def test_unheld_only_clock_never_creates_legal_cash_entitlement():
    a=action();a['clock_scope']='DAILY_MARKET_UNHELD_SOURCE';a['held_representation_scope']='SOURCE_UNHELD'
    with pytest.raises(ValueError):accounting.action_flows([cash_event()],[a])


def test_holder_integral_exact_fractional_episode_allocations_supported():
    events=[conversion_event(),conversion_event()]
    proof=accounting.action_flows(events,[action('CONVERSION')])[0]
    assert proof['delivered_shares_exact']=='11' and proof['source_shares_exact']=='20'
    with pytest.raises(ValueError):accounting.action_flows(events[:1],[action('CONVERSION')])
    wrong=deepcopy(events);wrong[1]['detail']['shares_delivered']=5.4
    with pytest.raises(ValueError):accounting.action_flows(wrong,[action('CONVERSION')])


def test_conversion_cannot_add_cash_outside_the_legal_component():
    events=[conversion_event(),conversion_event()]
    events[0].update(cash_delta=1,cash_after=1001)
    with pytest.raises(ValueError):accounting.action_flows(events,[action('CONVERSION')])


def test_conversion_cash_matches_frozen_cumulative_binary64_subtraction():
    a=action('CASH_PLUS_STOCK');a.update(exchange_ratio='1',cash_per_share='2.5')
    event=conversion_event();before=math.nextafter(16380.0,math.inf);after=before+12.5
    event.update(reason='CASH_PLUS_STOCK',price=2.5,shares_delta=0,
        cash_before=before,cash_after=after,cash_delta=after-before)
    event['detail'].update(shares_in=5,shares_delivered=5,exchange_ratio_exact='1',cash_consideration=12.5)
    assert event['cash_delta']!=12.5
    proof=accounting.action_flows([event],[a])[0]
    assert proof['legal_cash_exact']=='25/2' and proof['cash_floating_residual_exact']!='0'
    assert proof['recorded_cash_delta_binary64_hexes']==[(after-before).hex()]
    event.update(cash_delta=12.5,cash_after=before+12.5)
    with pytest.raises(ValueError):accounting.action_flows([event],[a])


def test_historical_rights_and_ordinary_equations_delegated_without_core(monkeypatch):
    import p01_celg_bridge_accounting as historical
    seen=[];monkeypatch.setattr(historical,'right_flow',lambda events,q:seen.append(('old_rights',events,q)) or None)
    snapshot={'ledger':{'events':[]}}
    result=accounting.reconcile(snapshot,{'authenticated':'historical'},[],ordinary=lambda s:seen.append(('raw_equations',s)))
    assert result==dict(historical_celg_right_flow=None,grouped_action_flows=[])
    assert [r[0] for r in seen]==['old_rights','raw_equations']


def test_actual_scope_holder_and_reference_representation():
    value=state();before=deepcopy(value)
    result=review.action_scope(value,action('CONVERSION'),True)
    assert result['source_held'] and value==before
    value['wealth_core']['episodes']['2']['initial_shares']=10
    with pytest.raises(ValueError):review.action_scope(value,action('CONVERSION'),True)


@pytest.mark.parametrize('operation',['OPEN_SLOT_POSITION','CLOSE_POSITION'])
def test_every_source_pending_intent_refuses(operation):
    value=state();value['pending']=[dict(security_id='SOURCE',operation=operation)]
    with pytest.raises(ValueError):review.action_scope(value,action('CONVERSION'),True)


def test_target_roles_allowed_only_with_actual_independence_qualification():
    value=state();value['wealth_core']['episodes']={'3':dict(security_id='TARGET',current_shares=5,initial_shares=5)}
    value['pending']=[dict(security_id='TARGET',operation='OPEN_SLOT_POSITION')]
    assert review.action_scope(value,action('CONVERSION'),True)['target_existing_role'] is True
    with pytest.raises(ValueError):review.action_scope(value,action('CONVERSION'),False)


def test_held_source_target_holding_needs_its_own_component_and_no_target_pending():
    value=state();value['wealth_core']['episodes']['3']=dict(security_id='TARGET',current_shares=5,initial_shares=5)
    with pytest.raises(ValueError):review.action_scope(value,action('CONVERSION'),True)
    assert review.action_scope(value,action('CONVERSION'),True,True)['target_existing_role'] is True
    value['pending']=[dict(security_id='TARGET',operation='CLOSE_POSITION')]
    with pytest.raises(ValueError):review.action_scope(value,action('CONVERSION'),True,True)


def test_unheld_clock_guard_removal_falsifier():
    value=state();a=action('CONVERSION');a['clock_scope']='DAILY_MARKET_UNHELD_SOURCE'
    with pytest.raises(ValueError):review.action_scope(value,a,True)
    tree=ast.parse(Path(review.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='action_scope')
    conditional=next(n for n in fn.body if isinstance(n,ast.If) and ast.unparse(n.test)=="action['clock_scope'] == 'DAILY_MARKET_UNHELD_SOURCE'")
    conditional.test=ast.Constant(False)
    namespace=dict(vars(review));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unheld-clock-guard-removal-falsifier>','exec'),namespace)
    assert namespace['action_scope'](value,a,True)['source_held'] is True


def test_pre_event_receipt_binds_actual_prior_and_saved_current():
    cp=dict(sha256='outer',source_cursor='2020-02-05',run=dict(checkpoint_sha256='inner',state_sha256='state'))
    row=dict(path='2020-02-06-outer.json.gz',outer_sha256='outer',inner_sha256='inner',state_sha256='state',
        prior_session='2020-02-05',current_saved_identical_before_guard=True,current_file=dict(bytes=1,sha256='a'*64))
    files={'book/pre-event/'+row['path']:dict(bytes=1,sha256='a'*64)}
    review.pre_event_receipts([row],{'book/pre-event/'+row['path']:cp},files)
    wrong=deepcopy(row);wrong['current_file']['sha256']='b'*64
    with pytest.raises(ValueError):review.pre_event_receipts([wrong],{'book/pre-event/'+row['path']:cp},files)
    row['current_saved_identical_before_guard']=False
    with pytest.raises(ValueError):review.pre_event_receipts([row],{'book/pre-event/'+row['path']:cp},files)


def test_retry_memory_reconstructs_only_new_rows():
    keys={'opening_attempts':0,'longest_zero_failure_streak':0}
    memory=dict(month='2020-02',month_counts=dict(keys),totals={'MEASURED':dict(keys),'FORMATION':dict(keys)},
        failed_slots={},last_skip_ids=['old'],last_session='2020-02-28',transitions=526)
    row=dict(session='2020-03-02',retry_diagnostics=dict(counts={'opening_attempts':1,'longest_zero_failure_streak':2},
        events=[dict(outcome='ZERO_SHARES',slot_id=1,security_id='S',consecutive_failed_attempts=2)]))
    result=review.advance_retry(memory,row)
    assert result['monthly']['opening_attempts']==1 and memory['failed_slots']['1']['streak']==2
    assert memory['last_skip_ids']==[] and memory['transitions']==527


def test_committed_rows_are_exact_filter_of_all_attempted_rows():
    rows=[dict(session='2020-02-05',full_state='committed'),dict(session='2020-02-06',full_state='failed_attempt')]
    before=deepcopy(rows)
    assert review.committed_attempts(rows[:1],rows,'2020-02-05','2020-02-06')==rows[1:]
    assert rows==before
    with pytest.raises(ValueError):review.committed_attempts([],rows,'2020-02-05','2020-02-06')
    with pytest.raises(ValueError):review.committed_attempts(rows,rows,'2020-02-05','2020-02-06')
    with pytest.raises(ValueError):review.committed_attempts(rows[:1],rows,'2020-02-05','2020-02-07')
    with pytest.raises(ValueError):review.committed_attempts(rows[:1],rows,'2020-02-05',None)


def test_committed_filter_guard_removal_falsifier():
    rows=[dict(session='2020-02-05',full_state='must_not_drop')]
    with pytest.raises(ValueError):review.committed_attempts([],rows,'2020-02-05','2020-02-06')
    tree=ast.parse(Path(review.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='committed_attempts')
    guard=fn.body[3]
    assert isinstance(guard,ast.Expr) and isinstance(guard.value,ast.Call) and guard.value.func.id=='need'
    guard.value.args[0]=ast.Constant(True)
    namespace=dict(vars(review));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<committed-filter-guard-removal-falsifier>','exec'),namespace)
    assert namespace['committed_attempts']([],rows,'2020-02-05','2020-02-06')==[]


def test_quote_context_refusal_precedes_any_canonical_import(tmp_path,monkeypatch):
    @contextmanager
    def refused(*args,**kwargs):
        raise ValueError('AUTHENTICATION_REQUIRED_BEFORE_RESTORE')
        yield
    monkeypatch.setattr(review,'historical_epoch',refused)
    with pytest.raises(ValueError,match='AUTHENTICATION_REQUIRED'):
        review.review({},tmp_path,tmp_path)
    assert not any(n.startswith(('sentinel','stock_strategy_shared','research.pooled_')) for n in sys.modules)


def component_fixture():
    mapping={'successor_financial_sources':{'synthetic.py':'source'},'successor_all_sources':{'synthetic.py':'source'}}
    cfg=dict(policy='EXACT_PARENT_POLICY',fields=dict(n_slots=30),config_hash='configuration')
    body=dict(schema='research.p01-grouped-synthetic-canonical-components/1',
        status='SYNTHETIC_CANONICAL_COMPONENTS_PASSED_NOT_FINANCIAL_ADMISSION',configuration=cfg,
        source_map_identity_sha256=review.digest(mapping),source_files={'synthetic.py':'source'},
        target_independence_qualified=True,ordinary_representation_qualified=True,held_target_holding_qualified=True,
        canonical_module_global_hooks_unchanged=True,actual_allocation_guard_removal_accepts_bad_fixture=True,
        held_source_with_target_pending_qualified=False,financial_authority=False,qualification_state_adopted=False,
        actual_future_own_roles_claimed=False,target_cases={},stock_cases={},negative_cases=[])
    target_state=dict(wealth_core=dict(episodes={},slots={}),pending=[],median5={'selected':[]},ledger={'events':[]})
    for role in ('TARGET_HELD','TARGET_CLOSE_PENDING','TARGET_DOLLAR_BUY_PENDING'):
        body['target_cases'][role]=dict(before=deepcopy(target_state),canonical_without_term_state=deepcopy(target_state),
            canonical_with_term_state=deepcopy(target_state),source_unheld=True,all_source_pending_absent=True,
            full_state_roundtrip=True,source_vs_target_mutation_detected=None if role=='TARGET_HELD' else True,
            actual_mutated_state={'retained_mutation':role})
    records=[]
    for ticker in ('WLH','VSLR','BMCH','WPX'):
        a=action('CONVERSION');a.update(source_ticker=ticker,exchange_ratio='1');records.append(a)
        before=deepcopy(target_state);before['wealth_core']['episodes']={
            '0':dict(security_id='SOURCE',current_shares=10,initial_shares=10),
            '1':dict(security_id='TARGET',current_shares=7,initial_shares=7)}
        after=deepcopy(before);after['wealth_core']['episodes']['0']['security_id']='TARGET'
        event=conversion_event();event.update(ticker=ticker,shares_delta=0)
        event['detail'].update(exchange_ratio_exact='1',shares_delivered=10)
        after['ledger']['events']=[event]
        body['stock_cases'][ticker]=dict(terms=review.term(a),before=before,after=after,
            preexisting_target_quantity=7,preexisting_target_episode_unchanged=True,no_CIL_rate_supplied=True,
            synthetic_quantities={'current':[10]},canonical_report={'aggregate_by_security':{'TARGET':{'shares':17}}})
    for name in ('HOLDER_FRACTION_WITHOUT_CIL','INITIAL_REFERENCE_ROUNDING','INEXACT_EPISODE_BINARY64',
                 'SOURCE_EPISODE_EXIT_FLAG_WITHOUT_PENDING','SOURCE_PENDING_DOLLAR_BUY'):
        body['negative_cases'].append(dict(case=name,error='retained_exact_refusal',caller_full_state_and_ledger_unchanged=True))
    return body,cfg,records,mapping


def test_actual_component_wires_and_exact_parent_policy_are_inspected():
    args=component_fixture();before=deepcopy(args)
    assert len(review.component_proof(*args))==11 and args==before
    args[1]['fields']['n_slots']=20
    # The actual supplied configuration is independently obtained from parent policy.
    wrong_cfg=deepcopy(args[1]);wrong_cfg['fields']['n_slots']=30
    with pytest.raises(ValueError):review.component_proof(args[0],wrong_cfg,args[2],args[3])


@pytest.mark.parametrize('mutation',['target_state','source','stock_posting','negative'])
def test_component_whole_state_source_posting_and_refusal_falsifiers(mutation):
    body,cfg,records,mapping=component_fixture()
    if mutation=='target_state':body['target_cases']['TARGET_CLOSE_PENDING']['canonical_with_term_state']['pending']=[{'changed':True}]
    elif mutation=='source':body['source_files']['synthetic.py']='wrong'
    elif mutation=='stock_posting':body['stock_cases']['WPX']['after']['ledger']['events'][0].update(cash_delta=1,cash_after=1001)
    else:body['negative_cases'].pop()
    with pytest.raises(ValueError):review.component_proof(body,cfg,records,mapping)
