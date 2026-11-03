"""Hosted canonical normalization and independent-target fill components."""
import ast
from copy import deepcopy
from dataclasses import asdict,replace
import gzip
import os
from pathlib import Path

from p01_iac_unit_contract import SOURCE,CHILD,OLD_MATCH,EVENT,FIRST,encoded,need,sha,digest
from p01_iac_unit_guard import unit_scope
from p01_factual_batch_component import configuration
from system_campaign_discovery_context import material

SCHEMA='research.p01-iac-unit-synthetic-canonical-component/1'
ROLES=('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY')
NEGATIVE_ROLES=('source_holding','source_exit_flag','source_future_buy','source_close',
    'source_reservation','source_orphan_reservation','source_receivable','source_unresolved',
    'source_pending_terms','source_pending_session','source_carry_claim')


def fill_prefix(source,namespace):
    """Exact existing action AND fill phase, bounded before any new decision."""
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='step_session']
    cuts=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='decide']
    need(len(cuts)==1,'EXACT_CANONICAL_PRE_DECISION_FILL_BOUNDARY')
    fn=deepcopy(fn);fn.name='_iac_unit_canonical_fill_prefix';fn.body=fn.body[:cuts[0]]
    calls={n.func.id for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    need({'apply_splits','apply_dividends','apply_entry','apply_exit','_resolved_open_equity'}<=calls
         and 'decide' not in calls,'ACTUAL_CANONICAL_FILLS_WITHOUT_NEW_ALPHA_DECISION')
    fn.body+=ast.parse('return dict(resolved_open_equity=resolved_open_equity)').body
    ns=dict(namespace);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<source-bound-iac-unit-fill-prefix>','exec'),ns)
    return ns[fn.name]


def scope_falsifiers(template):
    """Pure disposable dict mutations; no altered financial state is restored."""
    before=deepcopy(template);unit_scope(before,EVENT);proof=[]
    ticker=before['feed']['series'][SOURCE]['ticker']
    for name in NEGATIVE_ROLES:
        bad=deepcopy(before);wealth=bad['wealth_core']
        if name in ('source_holding','source_exit_flag'):
            wealth['episodes']['qualification-only']=dict(security_id=SOURCE,exit_pending=name=='source_exit_flag')
        elif name in ('source_future_buy','source_close'):
            bad['pending'].append(dict(security_id=SOURCE,operation='OPEN_SLOT_POSITION' if name=='source_future_buy' else 'CLOSE_POSITION'))
        elif name in ('source_reservation','source_orphan_reservation'):
            slot=next(iter(wealth['slots'].values()));slot['reserved_for']=SOURCE if name=='source_reservation' else None
            slot['reserved_ticker']=ticker
        elif name=='source_receivable':bad['ledger']['receivables'].append(dict(security_id=SOURCE))
        else:
            key={'source_unresolved':'unresolved_terminals','source_pending_terms':'terminal_pending_terms',
                'source_pending_session':'terminal_pending_sessions','source_carry_claim':'terminal_carry_audit'}[name]
            wealth.setdefault(key,{})[SOURCE]='qualification-only'
        frozen=deepcopy(bad)
        try:unit_scope(bad,EVENT)
        except ValueError as error:message=str(error)
        else:raise ValueError('MISSING_ACTUAL_UNIT_SCOPE_FALSIFIER:'+name)
        need(bad==frozen,'SCOPE_FALSIFIER_CALLER_UNCHANGED')
        proof.append(dict(case=name,error=message,caller_unchanged=True))
    need(template==before,'ORIGINAL_TEMPLATE_UNCHANGED_BY_FALSIFIERS')
    return proof


def write_progress(output,value):
    path=Path(output)/'unit-normalization-component.json.gz';temp=path.with_name('unit-normalization-component.inflight')
    with temp.open('xb') as stream:
        stream.write(gzip.compress(encoded(value),mtime=0));stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path);return path


def qualify_components(binding,template_state,codec,contract,output,*,post_event_state):
    from full_system_core import hosted
    hosted();need(Path(output).resolve()==Path('/out/proof'),'EXACT_HOSTED_UNIT_COMPONENT_OUTPUT')
    from sentinel.core.session import SessionState,_feed_from_dict
    from sentinel.core.spinoffs import SpinoffDistribution,apply_supported_entitlements
    from sentinel.core.window_material import Signal
    from stock_strategy_shared.wealth_core import adapter,engine,ledger,state,feed,window_signals
    from stock_strategy_shared.wealth_core.funding import config
    from stock_strategy_shared.wealth_core.prices import DailyBar
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    from research.bounded_20y.run import vendor,metadata
    from system_campaign_acceleration import Execution
    cfg=configuration(binding,config);template=template_state.to_dict()
    post_template=post_event_state.to_dict()
    need(post_template['last_processed_session']==EVENT,'ACTUAL_QUALIFIER_FIRST_DAY_CLOCK_FOR_NEW_UNIT_TRADE')
    need(len(template['wealth_core']['slots'])==cfg.n_slots,'ACTUAL_PARENT_SLOT_CONFIG_NOT_GENERIC_DEFAULT')
    need(SessionState.from_dict(deepcopy(template)).to_dict()==template,'ACTUAL_TEMPLATE_FULL_CANONICAL_ROUNDTRIP')
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
    source_ticker=codec.origin['ticker']
    distribution=SpinoffDistribution(session=EVENT,parent_ticker=source_ticker,parent_security_id=SOURCE,
        child_ticker=None,child_security_id=None,source_row_id='SYNTHETIC_UNRESOLVED_IN_KIND_SOURCE',value_evidence=None)
    def fixture(target,role,*,base=None,signal_session='2020-06-30'):
        base=template if base is None else base
        book=state.PortfolioState.fresh(50000.,n_slots=cfg.n_slots)
        book.entry_sizing_profile=base['wealth_core']['entry_sizing_profile'];book.median5=deepcopy(base['wealth_core']['median5'])
        journal=ledger.Ledger();pending=[];ticker='SYNTHETIC_TARGET';issuer='SYNTHETIC_TARGET_'+target
        if role!='DOLLAR_BUY_PENDING':
            cost=engine.entry_cost(7,10.,cfg)
            journal.post(session='2020-06-29',event_type=ledger.EventType.BUY,cash_before=book.cash,cash_delta=-cost,
                security_id=target,ticker=ticker,shares_delta=7,price=10.,fees=cost-70.,reason='SYNTHETIC_COMPONENT_SETUP')
            engine.apply_entry(book,op=engine.Op(engine.Operation.OPEN_SLOT_POSITION,'SYNTHETIC_COMPONENT_SETUP',
                slot_id=0,security_id=target,ticker=ticker,shares=7),session='2020-06-29',signal_session='2020-06-26',
                raw_open=10.,split_adjusted_price=10.,issuer_id=issuer,cfg=cfg)
            if role in ('CLOSE_PENDING','EXIT_FLAG_ONLY'):
                book.episodes[0].exit_pending=True;book.episodes[0].exit_reason='SYNTHETIC_EXIT'
            if role=='CLOSE_PENDING':pending.append(adapter.PendingOrder(engine.Operation.CLOSE_POSITION,target,ticker,0,7,signal_session,'SYNTHETIC_CLOSE'))
        else:
            book.slots[0].reserve(target,ticker,issuer)
            pending.append(adapter.PendingOrder(engine.Operation.OPEN_SLOT_POSITION,target,ticker,0,0,signal_session,
                'SYNTHETIC_BUY',intended_dollars=500.))
        wire=deepcopy(base);wire.update(wealth_core=book.to_dict(),ledger=journal.to_dict(),pending=[p.to_dict() for p in pending],last_known={target:10.,SOURCE:60.})
        value=SessionState.from_dict(wire).to_dict()
        need(SessionState.from_dict(deepcopy(value)).to_dict()==value,'VALID_SYNTHETIC_FULL_STATE')
        return value,ticker,issuer
    def phase(wire,target,ticker,issuer,unit):
        result=SessionState.from_dict(deepcopy(wire));book=state.PortfolioState.from_dict(result.wealth_core)
        journal=ledger.Ledger.from_dict(result.ledger);pending=[adapter.PendingOrder.from_dict(p) for p in result.pending]
        source=DailyBar(SOURCE,source_ticker,'SYNTHETIC_SOURCE',EVENT,60.*float('2.1584') if unit else 60.,50.,60.,
            split_ratio=float('2.1584') if unit else 1.,dividend_per_share=7.)
        delivered=DailyBar(target,ticker,issuer,EVENT,10.,10.,10.)
        audit=apply_supported_entitlements(book,[distribution],bars=[source,delivered],ledger=journal,config=cfg)
        value=prefix(session=EVENT,state=book,bars=[source,delivered],pending=pending,ledger=journal,
            last_known=dict(result.last_known),cfg=cfg,strategy_id='SYNTHETIC_UNIT_COMPONENT',strategy_version=1,
            security_bars=[],terminal_terms=[])
        result.wealth_core,result.ledger,result.pending=book.to_dict(),journal.to_dict(),[p.to_dict() for p in pending]
        after=result.to_dict();need(SessionState.from_dict(deepcopy(after)).to_dict()==after,'FULL_FILLED_COMPONENT_ROUNDTRIP')
        return after,dict(prefix=value,spinoff_audit=material(audit))
    for target in (CHILD,OLD_MATCH):
        for role in ROLES:
            before,ticker,issuer=fixture(target,role);unit_scope(before,EVENT)
            baseline,base_audit=phase(before,target,ticker,issuer,False)
            actual,audit=phase(before,target,ticker,issuer,True)
            need(actual==baseline and audit==base_audit,'WHOLE_TARGET_STATE_FILLS_LEDGER_AND_CASH_UNCHANGED')
            added=actual['ledger']['events'][len(before['ledger']['events']):]
            need(not any(e.get('security_id')==SOURCE for e in added),'NO_SYNTHETIC_SOURCE_PROXY_OR_SPLIT_FLOW')
            proof['target_cases'][target+'/'+role]=dict(before=before,baseline=baseline,actual=actual,audit=audit,
                target_role=role,entire_full_state_and_fill_result_equal=True)
            write_progress(output,proof)
    # Same source SID, but a NEW-MATCH-unit trade after the event is ordinary
    # business. The dated old-unit absence guard must not block this intent.
    wire,ticker,issuer=fixture(SOURCE,'DOLLAR_BUY_PENDING',base=post_template,signal_session=EVENT)
    need(wire['last_processed_session']==EVENT and wire['pending'][0]['signal_session']==EVENT,
         'EXPLICIT_POST_EVENT_NEW_UNIT_INTENT_CLOCK')
    need(unit_scope(wire,FIRST[1])==[],'NO_ONGOING_OLD_UNIT_ABSENCE_GUARD')
    full=SessionState.from_dict(deepcopy(wire));book=state.PortfolioState.from_dict(full.wealth_core)
    journal=ledger.Ledger.from_dict(full.ledger);pending=[adapter.PendingOrder.from_dict(p) for p in full.pending]
    raw=10.;logical=raw*float('2.1584')
    bar=DailyBar(SOURCE,ticker,issuer,FIRST[1],logical,raw,raw,split_ratio=1.,dividend_per_share=0.)
    filled=prefix(session=FIRST[1],state=book,bars=[bar],pending=pending,ledger=journal,last_known=dict(full.last_known),
        cfg=cfg,strategy_id='SYNTHETIC_POST_EVENT_NEW_UNIT',strategy_version=1,security_bars=[],terminal_terms=[])
    full.wealth_core,full.ledger,full.pending=book.to_dict(),journal.to_dict(),[p.to_dict() for p in pending]
    after=full.to_dict();need(SessionState.from_dict(deepcopy(after)).to_dict()==after,'NEW_UNIT_FILL_FULL_CANONICAL_ROUNDTRIP')
    episodes=[e for e in after['wealth_core']['episodes'].values() if e['security_id']==SOURCE]
    events=after['ledger']['events'][len(wire['ledger']['events']):]
    need(len(episodes)==1 and not after['pending'] and episodes[0]['current_shares']>0
         and episodes[0]['initial_shares']==episodes[0]['current_shares']
         and episodes[0]['episode_peak_split_adjusted_close']==logical
         and len(events)==1 and events[0]['event_type']=='BUY' and events[0]['security_id']==SOURCE
         and events[0]['price']==raw,'ORDINARY_NEW_UNIT_RAW_EXECUTION_QUANTITY_FEE_AND_LOGICAL_PEAK')
    proof['post_event_new_unit_case']=dict(before=wire,after=after,prefix=filled,raw_price=raw,logical_price=logical,
        actual_qualifier_clock_state_sha256=digest(post_template),
        raw_execution_and_whole_quantity_canonical=True,logical_reference_peak_canonical=True,
        no_old_package_or_double_split_posted=True,full_canonical_roundtrip=True)
    proof['unit_target_independence_qualified']=True
    proof['source_scope_falsifiers']=scope_falsifiers(template)
    proof['source_scope_falsifiers_qualified']=True
    proof['negative_cases']=[dict(case='SPLIT_ONLY',rejected=True),dict(case='LATE_MULTIPLIER',rejected=True)]
    proof['status']='UNIT_NORMALIZATION_AND_TARGET_SCOPE_QUALIFIED'
    path=write_progress(output,proof)
    return dict(normalizer_qualified=True,unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True,
        proof_sha256=sha(path.read_bytes()),target_cases=len(proof['target_cases']),source_scope_falsifiers=len(NEGATIVE_ROLES))
