"""Complete synthetic fixture feeds; real source normalization stays unchanged."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import traceback

from p01_iac_unit_contract import SOURCE, CHILD, OLD_MATCH, EVENT, FIRST, encoded, need, sha, digest
from p01_iac_unit_guard import unit_scope
from p01_factual_batch_component import configuration
from system_campaign_discovery_context import material
from p01_iac_unit_component import fill_prefix, scope_falsifiers, write_progress, ROLES, NEGATIVE_ROLES

SCHEMA='research.p01-iac-unit-synthetic-canonical-component/2'
ORIGINAL_COMPONENT_SHA='59cf4449434232ae2d4d6bc15c206731359fadc117883259134062930dbfe087'
CASE_IDS=tuple(sid+'/'+role for sid in (CHILD,OLD_MATCH) for role in ROLES)+('POST_EVENT_SOURCE_BUY',)
SYNTHETIC_SOURCE_TICKER='SYNTHETIC_UNIT_SOURCE'
SYNTHETIC_SOURCE_ISSUER='SYNTHETIC_UNIT_SOURCE_ISSUER'
PHASE='ACTIONS_FILLS_CLOSE_PRE_DECISION_NOT_A_COMPLETE_SESSION'


def fixture_plan(base,target,role,*,signal_session):
    """Pure metadata plan. Every price here is explicitly synthetic."""
    owned=base['last_processed_session'];raw=base['feed'];clock=sorted(raw['seen_sessions'].items(),key=lambda pair:pair[1])
    need(raw['history_sessions']==260 and len(clock)>=3 and clock[-1]==(owned,raw['session_index'])
         and all(clock[i][0]<clock[i+1][0] and clock[i][1]+1==clock[i+1][1] for i in range(len(clock)-1)),
         'FIXTURE_EXACT_OWNED_CALENDAR_AND_GLOBAL_INDEX')
    need(role in ROLES and target in (SOURCE,CHILD,OLD_MATCH) and signal_session==owned,
         'FIXTURE_ROLE_AND_SIGNAL_AT_OWNED_CLOSE')
    post=target==SOURCE
    need((owned==EVENT and post and role=='DOLLAR_BUY_PENDING') or (owned=='2020-06-30' and not post),
         'FIXTURE_PRE_EVENT_TARGET_OR_POST_EVENT_NEW_SOURCE_CLOCK')
    instruments={SOURCE:dict(ticker=SYNTHETIC_SOURCE_TICKER,issuer_id=SYNTHETIC_SOURCE_ISSUER,
        raw_price=10. if post else 60.,volume=100000000.,unit_event=EVENT)}
    if not post:instruments[target]=dict(ticker='SYNTHETIC_TARGET',issuer_id='SYNTHETIC_TARGET_'+target,
        raw_price=10.,volume=100000000.,unit_event=None)
    return dict(schema='research.p01-iac-unit-synthetic-fixture-plan/1',base_state_sha256=digest(base),
        target_security_id=target,target_role=role,owned_session=owned,phase_session=FIRST[1] if post else EVENT,
        phase=PHASE,signal_session=signal_session,history_sessions=260,calendar=[[day,index] for day,index in clock],
        instruments=instruments,setup_session=clock[-2][0],setup_signal_session=clock[-3][0],
        replaced_fields=['wealth_core','ledger','pending','last_known','feed'],all_prices_and_histories_synthetic=True,
        market_observations_or_preIPO_evidence=False,complete_financial_transition=False)


def planned_feed(plan):
    """Independent scalar specification for every saved synthetic feed field."""
    days=[p[0] for p in plan['calendar']];indices=[p[1] for p in plan['calendar']];series={}
    for sid,domain in plan['instruments'].items():
        factor=1.;signals=[]
        for day in days:
            if day==domain['unit_event']:factor*=float('2.1584')
            signals.append(domain['raw_price']*factor)
            factor=signals[-1]/domain['raw_price']
        series[sid]=dict(security_id=sid,ticker=domain['ticker'],issuer_id=domain['issuer_id'],split_factor=factor,
            sessions=list(days),session_indices=list(indices),signal_closes=signals,
            raw_closes=[domain['raw_price']]*len(days),volumes=[domain['volume']]*len(days),
            signal_basis_anchor=[days[-1],domain['raw_price'],signals[-1]])
    return dict(history_sessions=260,session_index=indices[-1],seen_sessions=dict(plan['calendar']),series=series)


def build_feed(plan,feed,from_feed,to_feed,protected,elig):
    """HOSTED caller supplies the actual pinned canonical APIs; tests use stubs."""
    context=from_feed(dict(history_sessions=260,session_index=plan['calendar'][0][1]-1,seen_sessions={},series={}),{},elig)
    for sid,domain in plan['instruments'].items():
        context.series[sid]=feed.SecuritySeries(sid,domain['ticker'],domain['issuer_id'])
    for day,index in plan['calendar']:
        need(context._advance_session(day)==index,'FIXTURE_CANONICAL_GLOBAL_INDEX_EXACT')
        for sid,domain in plan['instruments'].items():
            ratio=float('2.1584') if day==domain['unit_event'] else 1.
            factor=context.series[sid].split_factor*ratio
            bar=feed.VendorBar(day,sid,domain['ticker'],domain['raw_price'],domain['raw_price'],domain['volume'],
                split_ratio=ratio,signal_close=domain['raw_price']*factor)
            context.series[sid].append(bar,index,published_signal=True)
    result=to_feed(context,protected)
    need(encoded(result)==encoded(planned_feed(plan)) and set(protected)<=set(result['series']),
         'ENTIRE_SYNTHETIC_FEED_CANONICAL_APIS_MATCH_DECLARED_PLAN')
    return result


def make_fixture(base,target,role,cfg,state,ledger,engine,adapter,feed,SessionState,from_feed,to_feed,protected_ids,elig,*,signal_session,capture=None):
    plan=fixture_plan(base,target,role,signal_session=signal_session);domain=plan['instruments'][target]
    book=state.PortfolioState.fresh(50000.,n_slots=cfg.n_slots)
    book.entry_sizing_profile=base['wealth_core']['entry_sizing_profile'];book.median5=deepcopy(base['wealth_core']['median5'])
    journal=ledger.Ledger();pending=[];ticker=domain['ticker'];issuer=domain['issuer_id']
    if role!='DOLLAR_BUY_PENDING':
        cost=engine.entry_cost(7,10.,cfg)
        journal.post(session=plan['setup_session'],event_type=ledger.EventType.BUY,cash_before=book.cash,cash_delta=-cost,
            security_id=target,ticker=ticker,shares_delta=7,price=10.,fees=cost-70.,reason='SYNTHETIC_COMPONENT_SETUP')
        engine.apply_entry(book,op=engine.Op(engine.Operation.OPEN_SLOT_POSITION,'SYNTHETIC_COMPONENT_SETUP',
            slot_id=0,security_id=target,ticker=ticker,shares=7),session=plan['setup_session'],signal_session=plan['setup_signal_session'],
            raw_open=10.,split_adjusted_price=10.,issuer_id=issuer,cfg=cfg)
        if role in ('CLOSE_PENDING','EXIT_FLAG_ONLY'):
            book.episodes[0].exit_pending=True;book.episodes[0].exit_reason='SYNTHETIC_EXIT'
        if role=='CLOSE_PENDING':pending.append(adapter.PendingOrder(engine.Operation.CLOSE_POSITION,target,ticker,0,7,signal_session,'SYNTHETIC_CLOSE'))
    else:
        book.slots[0].reserve(target,ticker,issuer)
        pending.append(adapter.PendingOrder(engine.Operation.OPEN_SLOT_POSITION,target,ticker,0,0,signal_session,
            'SYNTHETIC_BUY',intended_dollars=500.))
    wealth=book.to_dict();orders=[p.to_dict() for p in pending];protected=protected_ids(wealth,orders)
    wire=deepcopy(base);wire.update(wealth_core=wealth,ledger=journal.to_dict(),pending=orders,
        last_known={sid:plan['instruments'][sid]['raw_price'] for sid in protected},
        feed=build_feed(plan,feed,from_feed,to_feed,protected,elig))
    if capture is not None:capture('RAW_FIXTURE_BEFORE_CANONICAL_RESTORE',deepcopy(wire))
    value=SessionState.from_dict(wire).to_dict()
    need(encoded(SessionState.from_dict(deepcopy(value)).to_dict())==encoded(value),'VALID_COMPLETE_SYNTHETIC_FULL_STATE')
    need(encoded(value['feed'])==encoded(planned_feed(plan)) and encoded(value['last_known'])==encoded(wire['last_known']),
         'CANONICAL_RESTORE_RETAINS_COMPLETE_DECLARED_FEED_AND_MARKS')
    for key in set(base)|set(value):
        if key not in plan['replaced_fields']:need(encoded(value[key])==encoded(base[key]),'FIXTURE_ALL_UNDECLARED_ENVELOPE_FIELDS_EXACT:'+key)
    contract=dict(plan=plan,protected_security_ids=sorted(protected),before_state_sha256=digest(value),
        before_feed_sha256=digest(value['feed']),canonical_roundtrip=True,financial_authority=False)
    return value,ticker,issuer,contract


def reference_boundary(components,final,zero,contract):
    for outer in (zero,final):
        need(outer['sha256']==digest({k:v for k,v in outer.items() if k!='sha256'}),
             'DURABLE_REFERENCE_ACTUAL_OUTER_HASH')
        run=outer['run']
        need(run['state_sha256']==digest(run['state'])
             and run['checkpoint_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'}),
             'DURABLE_REFERENCE_ENTIRE_OUTER_RUNTIME_HASH')
    need([r['session'] for r in components]==list(FIRST),'DURABLE_ACTUAL_TWO_REFERENCE_DAYS')
    previous=zero['run']
    for row in components:
        need(encoded(row['prior_checkpoint'])==encoded(previous) and row['publication']['session']==row['session'],
             'DURABLE_REFERENCE_FULL_ADJACENCY_AND_PUBLICATION')
        current=row['checkpoint'];need(current['state_sha256']==digest(current['state'])
            and current['checkpoint_sha256']==digest({k:v for k,v in current.items() if k!='checkpoint_sha256'})
            and current['state']['last_processed_session']==row['session']
            and current['input_sha256']==zero['run']['input_sha256'],'DURABLE_REFERENCE_ENTIRE_RUNTIME_HASHES_AND_INPUT')
        previous=current
    need(encoded(final['run'])==encoded(previous) and final['source_cursor']==FIRST[-1]
         and type(final['completed']) is int and final['completed']==630,
         'DURABLE_REFERENCE_ACTUAL_FINAL_OUTER_CHECKPOINT')
    return dict(schema='research.p01-iac-unit-unadmitted-reference-boundary/1',actual_components=deepcopy(components),
        qualifier_checkpoint=deepcopy(final),input_zero_checkpoint=deepcopy(zero),source_contract_sha256=digest(contract),
        actual_reference_records_preserved_before_fixtures=True,financial_authority=False,qualification_state_adopted=False)


def aggregate():
    return dict(schema='research.p01-iac-unit-fixture-aggregate/1',expected_case_ids=list(CASE_IDS),
        attempted_case_ids=[],passed_case_ids=[],failed_cases=[],complete=False,all_passed=False)


def finish_case(proof,case,*,stage,error=None):
    record=proof['fixture_aggregate'];need(case not in record['attempted_case_ids'] and case in CASE_IDS,'ONE_ACTUAL_FIXTURE_ATTEMPT_PER_CASE')
    record['attempted_case_ids'].append(case)
    if error is None:record['passed_case_ids'].append(case)
    else:record['failed_cases'].append(dict(case_id=case,stage=stage,error_type=type(error).__name__,
        message=str(error),traceback=traceback.format_exc(),financial_authority=False))
    record['complete']=record['attempted_case_ids']==list(CASE_IDS)
    record['all_passed']=record['complete'] and record['passed_case_ids']==list(CASE_IDS) and not record['failed_cases']


def fixture_sources(binding):
    names=('sentinel/core/session.py','shared/stock_strategy_shared/wealth_core/feed.py',
        'shared/stock_strategy_shared/wealth_core/adapter.py','shared/stock_strategy_shared/wealth_core/state.py',
        'shared/stock_strategy_shared/wealth_core/state_restore_validation.py','shared/stock_strategy_shared/wealth_core/shares.py')
    pins={n:sha((Path('/variant')/n).read_bytes()) for n in names}
    need(all(binding.source_map['successor_all_sources'][n]==h for n,h in pins.items()),'COMPLETE_FIXTURE_ACTUAL516_SOURCE_APIS')
    return pins


def qualify_components(binding,template_state,codec,contract,output,*,post_event_state,reference_components,qualifier_checkpoint,input_zero_checkpoint):
    from full_system_core import hosted
    hosted();need(Path(output).resolve()==Path('/out/proof'),'EXACT_HOSTED_UNIT_COMPONENT_OUTPUT')
    from sentinel.core.session import SessionState,_feed_from_dict,_feed_to_dict,_path_dependent_security_ids
    from sentinel.core.spinoffs import SpinoffDistribution,apply_supported_entitlements
    from sentinel.core.window_material import Signal
    from stock_strategy_shared.wealth_core import adapter,engine,ledger,state,feed,window_signals
    from stock_strategy_shared.wealth_core.funding import config
    from stock_strategy_shared.wealth_core.prices import DailyBar
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    from research.bounded_20y.run import vendor,metadata
    from system_campaign_acceleration import Execution
    need(sha(Path(__file__).with_name('p01_iac_unit_component.py').read_bytes())==ORIGINAL_COMPONENT_SHA,'FROZEN_490_COMPONENT_NORMALIZER_SOURCE')
    cfg=configuration(binding,config);template=template_state.to_dict()
    post_template=post_event_state.to_dict()
    need(post_template['last_processed_session']==EVENT,'ACTUAL_QUALIFIER_FIRST_DAY_CLOCK_FOR_NEW_UNIT_TRADE')
    need(len(template['wealth_core']['slots'])==cfg.n_slots,'ACTUAL_PARENT_SLOT_CONFIG_NOT_GENERIC_DEFAULT')
    need(encoded(SessionState.from_dict(deepcopy(template)).to_dict())==encoded(template),'ACTUAL_TEMPLATE_FULL_CANONICAL_ROUNDTRIP')
    required=('shared/stock_strategy_shared/wealth_core/engine.py','shared/stock_strategy_shared/wealth_core/ledger.py',
        'shared/stock_strategy_shared/wealth_core/funding.py','shared/stock_strategy_shared/wealth_core/prices.py',
        'shared/stock_strategy_shared/wealth_core/marks.py','shared/stock_strategy_shared/wealth_core/v5.py')
    pins={n:sha((Path('/variant')/n).read_bytes()) for n in required}
    need(all(h==binding.source_map['successor_all_sources'][n] for n,h in pins.items()),'ACTUAL_CANONICAL_FIXTURE_SOURCE_PINS')
    proof=dict(schema=SCHEMA,status='UNIT_COMPONENTS_STARTED',source_contract=contract,source_files=pins,
        origin_basis_sha256=digest(codec.origin),configuration=dict(policy=binding.parent['base']['policy'],
        fields=asdict(cfg),config_hash=cfg.config_hash()),normalizer_cases={},target_cases={},negative_cases=[],
        source_scope_falsifiers=[],post_event_new_unit_case=None,normalizer_qualified=False,unit_target_independence_qualified=False,
        source_scope_falsifiers_qualified=False,positions_and_orders_synthetic=True,
        normalization_observations_from_authenticated_frozen_input=True,actual_future_roles_claimed=False,
        financial_authority=False,qualification_state_adopted=False)
    proof.update(actual_reference_boundary=reference_boundary(reference_components,qualifier_checkpoint,input_zero_checkpoint,contract),
        fixture_source_files=fixture_sources(binding),fixture_contracts={},fixture_contexts={},fixture_aggregate=aggregate())
    need(encoded(post_template)==encoded(reference_components[0]['checkpoint']['state']),'ACTUAL_REFERENCE_FIRST_DAY_POST_CLOCK_STATE_EXACT')
    write_progress(output,proof)
    rows=[r for day,r in codec.domain.rows.items() if EVENT<=day<=FIRST[-1]]
    need([r['session'] for r in rows]==list(FIRST) and not any(d<=FIRST[-1] for d in codec.domain.failures),
         'COMPONENT_FIRST_TWO_NATIVE_BASIS_CLOSED_NO_FUTURE_STATE_ASSUMPTION')
    bars=[replace(vendor(r),split_ratio=codec.domain.days[r['session']]['effective_split_ratio']) for r in rows]
    reference=feed.build_signal_series(bars,prior_split_factor=float(codec.origin['split_factor']))
    expected=[codec.domain.days[r['session']]['logical_signal_close'] for r in rows]
    need(reference==expected,'EXACT_FROZEN_CANONICAL_RAW_FORWARD_REFERENCE')
    restored=_feed_from_dict(binding.parent['run']['state']['feed'],{},EligibilityConfig()).series[SOURCE]
    prior_row=codec.domain.rows[binding.parent['source_cursor']]
    restored.reconcile_signal_basis(vendor(prior_row))
    split_only=_feed_from_dict(binding.parent['run']['state']['feed'],{},EligibilityConfig()).series[SOURCE]
    start=int(binding.parent['run']['state']['feed']['session_index'])+1
    for i,(bar,value) in enumerate(zip(bars,reference),start):
        normalized=replace(bar,signal_close=value)
        restored.append(normalized,i,published_signal=True);split_only.append(bar,i,published_signal=True)
        need(restored.signal_closes[-1]==value and (bar.raw_close is None or bar.raw_close<=0
             or restored.split_factor==value/bar.raw_close),'EXACT_ACTIVE_PUBLISHED_SIGNAL_PATH_REFERENCE')
    need(split_only.signal_closes[-len(reference):]!=reference,'SPLIT_ONLY_FALSIFIER_MUST_DIFFER')
    proof['normalizer_cases']['observed_forward']=dict(observations=len(rows),source_sessions=[r['session'] for r in rows],
        source_raw_row_sha256=[digest(r) for r in rows],reference_signal_hex=[None if v is None else v.hex() for v in reference],
        published_path_exact=True,split_only_falsifier_rejected=True)
    from p01_iac_unit_codec import NativeDomain
    raw,split=next((a,b) for a in (1.3,7.1,13.7,23.2,101.3) for b in (1.1,1.3,1.7,3.3)
        if (a*b)*float('2.1584')!=a*(float('2.1584')*b))
    toy=[dict(session=FIRST[0],security_id=SOURCE,raw_close='10',raw_open='9',
              signal_close='10',split_ratio='1',raw_compatible_volume='99'),
         dict(session=FIRST[1],security_id=SOURCE,raw_close=str(raw),raw_open=str(raw),
              signal_close=str(raw*split),split_ratio=str(split),raw_compatible_volume='99')]
    domain=NativeDomain(toy,codec.records['normalizer'])
    toy_bars=[feed.VendorBar(r['session'],SOURCE,'SYNTHETIC_UNIT_SOURCE',float(r['raw_close']),
        float(r['raw_open']),99.,split_ratio=domain.days[r['session']]['effective_split_ratio']) for r in toy]
    canonical=feed.build_signal_series(toy_bars,prior_split_factor=1.)
    need(canonical==[domain.days[r['session']]['logical_signal_close'] for r in toy]
         and canonical[-1]!=(raw*split)*float('2.1584'),'ACTUAL_CANONICAL_COMPOSITION_ASSOCIATIVITY_FALSIFIER')
    proof['normalizer_cases']['native_composition']=dict(synthetic_rows=toy,
        canonical_signal_hex=[v.hex() for v in canonical],published_times_ratio_wrong_hex=((raw*split)*float('2.1584')).hex(),
        associativity_falsifier_rejected=True,raw_factor_chronology_exact=True)
    # The cached feature metrics are computed BEFORE Signal.bar(multiplier).
    # A late uniform multiplier cannot supply the event step in that window.
    length=contract['window_length'];indices=list(range(length));raw=[10.0+i*.01 for i in indices]
    raw[-2:]=[8.,8.1];correct=raw[:-2]+[v*float('2.1584') for v in raw[-2:]]
    meta=metadata(prior_row)
    def feature(closes):
        series=feed.SecuritySeries(SOURCE,'SYNTHETIC_UNIT_SOURCE','SYNTHETIC_ISSUER',
            session_indices=indices,signal_closes=closes,raw_closes=raw,volumes=[100000000.]*length)
        return window_signals.feature(series,meta,index=length-1,session=EVENT)
    good,bad=feature(correct),feature(raw)
    need(good.certified_signals is not None and bad.certified_signals is not None
         and good.certified_signals!=bad.certified_signals,'LATE_MULTIPLIER_FEATURE_FALSIFIER')
    with Execution('REFERENCE',signal_closes=1):reference_signal=Signal.from_feature(good).model_dump(mode='json')
    with Execution('FAST',signal_closes=1):fast_signal=Signal.from_feature(good).model_dump(mode='json')
    need(reference_signal==fast_signal,'WHOLE_FAST_REFERENCE_FEATURE_WIRE_EXACT')
    proof['normalizer_cases']['feature_order']=dict(reference_signal=reference_signal,fast_signal=fast_signal,
        late_unadjusted_certified_signals=list(bad.certified_signals),late_multiplier_falsifier_rejected=True,
        full_synthetic_signal_window=correct,synthetic_raw_closes=raw)
    proof['normalizer_qualified']=True;write_progress(output,proof)
    prefix=fill_prefix(Path(adapter.__file__).read_bytes(),adapter.__dict__)
    source_ticker=SYNTHETIC_SOURCE_TICKER
    distribution=SpinoffDistribution(session=EVENT,parent_ticker=source_ticker,parent_security_id=SOURCE,
        child_ticker=None,child_security_id=None,source_row_id='SYNTHETIC_UNRESOLVED_IN_KIND_SOURCE',value_evidence=None)
    template_original=deepcopy(template);post_original=deepcopy(post_template)
    def phase(wire,target,ticker,issuer,unit):
        result=SessionState.from_dict(deepcopy(wire));book=state.PortfolioState.from_dict(result.wealth_core)
        journal=ledger.Ledger.from_dict(result.ledger);pending=[adapter.PendingOrder.from_dict(p) for p in result.pending]
        source=DailyBar(SOURCE,source_ticker,SYNTHETIC_SOURCE_ISSUER,EVENT,60.*float('2.1584') if unit else 60.,50.,60.,
            split_ratio=float('2.1584') if unit else 1.,dividend_per_share=7.)
        delivered=DailyBar(target,ticker,issuer,EVENT,10.,10.,10.)
        audit=apply_supported_entitlements(book,[distribution],bars=[source,delivered],ledger=journal,config=cfg)
        marks=dict(result.last_known)
        value=prefix(session=EVENT,state=book,bars=[source,delivered],pending=pending,ledger=journal,
            last_known=marks,cfg=cfg,strategy_id='SYNTHETIC_UNIT_COMPONENT',strategy_version=1,
            security_bars=[],terminal_terms=[])
        result.wealth_core,result.ledger,result.pending=book.to_dict(),journal.to_dict(),[p.to_dict() for p in pending]
        result.last_known=marks
        after=result.to_dict();need(encoded(SessionState.from_dict(deepcopy(after)).to_dict())==encoded(after),'FULL_FILLED_COMPONENT_ROUNDTRIP')
        return after,dict(prefix=value,spinoff_audit=material(audit))
    for case in CASE_IDS:
        post=case=='POST_EVENT_SOURCE_BUY';target=SOURCE if post else case.split('/')[0]
        role='DOLLAR_BUY_PENDING' if post else case.split('/')[1]
        base=post_template if post else template;signal_session=EVENT if post else '2020-06-30'
        stage='PLAN_COMPLETE_SYNTHETIC_CONTEXT'
        proof['fixture_contracts'][case]=dict(status='PLANNING',target_security_id=target,target_role=role)
        proof['fixture_contexts'][case]=dict(status='STARTED',phase=PHASE,financial_authority=False)
        write_progress(output,proof)
        def capture(label,raw,case=case):
            proof['fixture_contexts'][case].update(stage=label,raw_before=raw,raw_before_sha256=digest(raw),
                raw_fixture_financial_authority=False)
            write_progress(output,proof)
        try:
            proof['fixture_contracts'][case]=dict(plan=fixture_plan(base,target,role,signal_session=signal_session),status='PLANNED')
            stage='CONSTRUCT_AND_CANONICAL_RESTORE_COMPLETE_CONTEXT'
            before,ticker,issuer,record=make_fixture(base,target,role,cfg,state,ledger,engine,adapter,feed,
                SessionState,_feed_from_dict,_feed_to_dict,_path_dependent_security_ids,EligibilityConfig(),
                signal_session=signal_session,capture=capture)
            proof['fixture_contracts'][case]=record
            if not post:
                unit_scope(before,EVENT);stage='BASELINE_CANONICAL_ACTION_FILL_CLOSE_PREFIX'
                baseline,base_audit=phase(before,target,ticker,issuer,False)
                stage='UNIT_CANONICAL_ACTION_FILL_CLOSE_PREFIX';actual,audit=phase(before,target,ticker,issuer,True)
                stage='ENTIRE_BASELINE_UNIT_STATE_AND_AUDIT_COMPARE'
                need(encoded(actual)==encoded(baseline) and encoded(audit)==encoded(base_audit),
                    'WHOLE_TARGET_STATE_FILLS_LEDGER_MARKS_AND_CASH_UNCHANGED')
                added=actual['ledger']['events'][len(before['ledger']['events']):]
                need(not any(e.get('security_id')==SOURCE for e in added),'NO_SYNTHETIC_SOURCE_PROXY_OR_SPLIT_FLOW')
                proof['target_cases'][case]=dict(before=before,baseline=baseline,actual=actual,audit=audit,
                    target_role=role,entire_full_state_and_fill_result_equal=True)
            else:
                stage='POST_EVENT_NEW_UNIT_CLOCK_AND_RAW_FILL'
                need(before['last_processed_session']==EVENT and before['pending'][0]['signal_session']==EVENT,
                    'EXPLICIT_POST_EVENT_NEW_UNIT_INTENT_CLOCK')
                need(unit_scope(before,FIRST[1])==[],'NO_ONGOING_OLD_UNIT_ABSENCE_GUARD')
                full=SessionState.from_dict(deepcopy(before));book=state.PortfolioState.from_dict(full.wealth_core)
                journal=ledger.Ledger.from_dict(full.ledger);pending=[adapter.PendingOrder.from_dict(p) for p in full.pending]
                raw=10.;logical=raw*float('2.1584')
                bar=DailyBar(SOURCE,ticker,issuer,FIRST[1],logical,raw,raw,split_ratio=1.,dividend_per_share=0.)
                marks=dict(full.last_known)
                filled=prefix(session=FIRST[1],state=book,bars=[bar],pending=pending,ledger=journal,last_known=marks,
                    cfg=cfg,strategy_id='SYNTHETIC_POST_EVENT_NEW_UNIT',strategy_version=1,security_bars=[],terminal_terms=[])
                full.wealth_core,full.ledger,full.pending=book.to_dict(),journal.to_dict(),[p.to_dict() for p in pending]
                full.last_known=marks
                actual=full.to_dict();need(encoded(SessionState.from_dict(deepcopy(actual)).to_dict())==encoded(actual),'NEW_UNIT_FILL_FULL_CANONICAL_ROUNDTRIP')
                episodes=[e for e in actual['wealth_core']['episodes'].values() if e['security_id']==SOURCE]
                events=actual['ledger']['events'][len(before['ledger']['events']):]
                need(len(episodes)==1 and not actual['pending'] and episodes[0]['current_shares']>0
                    and episodes[0]['initial_shares']==episodes[0]['current_shares']
                    and episodes[0]['episode_peak_split_adjusted_close']==logical
                    and len(events)==1 and events[0]['event_type']=='BUY' and events[0]['security_id']==SOURCE
                    and events[0]['price']==raw,'ORDINARY_NEW_UNIT_RAW_EXECUTION_QUANTITY_FEE_AND_LOGICAL_PEAK')
                proof['post_event_new_unit_case']=dict(before=before,after=actual,prefix=filled,raw_price=raw,logical_price=logical,
                    actual_qualifier_clock_state_sha256=digest(post_template),raw_execution_and_whole_quantity_canonical=True,
                    logical_reference_peak_canonical=True,no_old_package_or_double_split_posted=True,full_canonical_roundtrip=True)
            proof['fixture_contracts'][case].update(after_state_sha256=digest(actual),after_feed_sha256=digest(actual['feed']),
                after_protected_security_ids=sorted(_path_dependent_security_ids(actual['wealth_core'],actual['pending'])),
                retained_current_marks=deepcopy(actual['last_known']),canonical_after_roundtrip=True)
            need(encoded(actual['feed'])==encoded(before['feed']),'ISOLATED_PREFIX_DOES_NOT_INVENT_A_NEW_OWNED_FEED_SESSION')
            proof['fixture_contexts'][case]=dict(status='PASSED',phase=PHASE,before_state_sha256=digest(before),
                after_state_sha256=digest(actual),financial_authority=False)
            finish_case(proof,case,stage=stage)
        except Exception as error:
            proof['fixture_contexts'][case].update(status='REFUSED',stage=stage,financial_authority=False)
            finish_case(proof,case,stage=stage,error=error)
        write_progress(output,proof)
    need(encoded(template)==encoded(template_original) and encoded(post_template)==encoded(post_original),'ALL_FIXTURES_LEAVE_BOTH_ACTUAL_CONTEXTS_UNCHANGED')
    proof['unit_target_independence_qualified']=proof['fixture_aggregate']['all_passed']
    proof['source_scope_falsifiers']=scope_falsifiers(template)
    proof['source_scope_falsifiers_qualified']=True
    proof['negative_cases']=[dict(case='SPLIT_ONLY',rejected=True),dict(case='LATE_MULTIPLIER',rejected=True)]
    proof['status']='UNIT_NORMALIZATION_AND_TARGET_SCOPE_QUALIFIED' if proof['fixture_aggregate']['all_passed'] else 'UNIT_FIXTURE_AGGREGATE_REFUSAL_PRESERVED'
    path=write_progress(output,proof)
    need(proof['fixture_aggregate']['complete'] and proof['fixture_aggregate']['all_passed'],
        'ALL_NINE_COMPLETE_SYNTHETIC_CONTEXTS_REQUIRED_BEFORE_QUALIFICATION')
    return dict(normalizer_qualified=True,unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True,
        proof_sha256=sha(path.read_bytes()),target_cases=len(proof['target_cases']),source_scope_falsifiers=len(NEGATIVE_ROLES),
        fixture_aggregate=deepcopy(proof['fixture_aggregate']))
