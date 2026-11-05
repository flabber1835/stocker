"""Hosted canonical quote/cash/pending/admission cases; disposable fixtures only."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import json
import math
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest


def require_veto(result,sid):
    need(not any(v.operation.value=='OPEN_SLOT_POSITION' and v.security_id==sid
                 for v in result.decision.operations)
         and any(v['security_id']==sid and v['reason']=='REJECT_TERMINAL_THIS_SESSION'
                 for v in result.decision.admission_rejections),
         'MORF_CANONICAL_ACTUAL_TERMINAL_DAY_ADMISSION_VETO')


def qualify_quote(out,cp,facts,loaded,old_objects,request):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import runtime,backtest
    from sentinel.controller import terminal_returns
    from stock_strategy_shared.wealth_core import adapter,median5,v5
    from stock_strategy_shared.wealth_core.adapter import PendingOrder
    from stock_strategy_shared.wealth_core.engine import Operation,SecurityBar
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.prices import DailyBar
    from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
    from stock_strategy_shared.wealth_core.terminal import apply_terminal
    catalog=facts.catalog;term,=catalog['terms'];sid=term['security_id'];day=term['added']['session']
    payload=json.loads((out/catalog['commitment_group']['private_file']).read_bytes())
    quote,=payload['recognition_quote_qualification']['actual_recognition_quotes']
    witness,=catalog['same_day_quote_claims'];quote_hash=digest(quote)
    need(quote_hash==witness['source_observation_sha256'],'MORF_GATE_ACTUAL_COMPLETE_QUOTE_PREIMAGE')
    vendor=inputs.vendor(dict(quote));vendor_before=asdict(vendor)
    native,=[v for v in inputs.load_actions('/frozen/bundle').terminal[day] if v.security_id==sid]
    packet=Packet(day,(vendor,),{}, {},1.,{},(native,),())
    original_before=digest(asdict(packet));repaired=packet
    for obj in [*old_objects,loaded]:repaired=backtest.apply_repair(repaired,obj)
    need(digest(asdict(packet))==original_before and repaired.bars==packet.bars
         and asdict(repaired.bars[0])==vendor_before and digest(quote)==quote_hash,
         'MORF_GATE_REPAIR_PRESERVES_QUOTE_VOLUME_METADATA_AND_ORIGINAL_PACKET')
    complete,=[v for v in repaired.terminal if v.security_id==sid]
    need(asdict(complete)==term['added'] and complete.completeness(10)[0],
         'MORF_GATE_COMPLETE_EXACT_CASH_TERM_WITH_QUOTE_PRESENT')
    previous,=[v for v in payload['source_witnesses'] if v['security_id']==sid and v['session']=='2024-08-15']
    anchor=float(previous['raw_close']);prior_signal=float(previous['signal_close']);signal=float(quote['signal_close'])
    prior=SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{
        'signal_basis_anchor':('2024-08-15',anchor,prior_signal)}}},last_processed_session='2024-08-15')
    try:terminal_returns.values(prior=prior,published=SimpleNamespace(session=day,bars=packet.bars,terminal_events=packet.terminal))
    except ValueError as error:need('incomplete leadership cash terminal' in str(error),'MORF_GATE_ORIGINAL_INCOMPLETE_REFUSAL_REASON')
    else:raise ValueError('MORF_GATE_ORIGINAL_INCOMPLETE_GUARD_MISSING')
    actual=terminal_returns.values(prior=prior,published=SimpleNamespace(session=day,bars=repaired.bars,terminal_events=repaired.terminal))
    expected=float(Fraction('57')*Fraction(str(prior_signal))/Fraction(str(anchor)))
    need(actual[sid]==expected,'MORF_GATE_CASH_NOTIONAL_OVERRIDES_QUOTE_IN_SIGNAL_DOMAIN')
    restored=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored)==cp['run'],'MORF_GATE_ACTUAL_PARENT_CANONICAL_ROUNDTRIP')
    cfg=runtime.config(cp['base']['policy']);sizing=v5.entry_sizing_profile(cfg.economic_profile)

    def fixture(*,held=False,pending_entry=False):
        state=PortfolioState.fresh(9000,n_slots=cfg.n_slots,entry_sizing_profile=sizing)
        state.median5=median5.fresh();state.median5['formation_started']=True;state.initialized=True
        orders=[]
        if held:
            ep=HoldingEpisode(sid,'MORF','SEC_CIK:1679363',0,'2024-08-14','2024-08-15',
                anchor,signal,10,10,episode_peak_split_adjusted_close=signal,market_sessions_held=17,
                review_completed=True,source_lots=[dict(kind='EXPLICIT_DISPOSABLE_MORF_COMPONENT_FIXTURE')])
            state.episodes[0]=ep;state.slots[0].occupied_by=sid
        if pending_entry:
            state.reserve_slot(0,sid,'MORF','SEC_CIK:1679363')
            orders=[PendingOrder(Operation.OPEN_SLOT_POSITION,sid,'MORF',0,0,'2024-08-15',
                'ENTRY_DURABLE_RANK',intended_dollars=400.)]
        return state,orders,Ledger(),{sid:anchor}

    def step(parts,events):
        state,orders,ledger,last=parts
        daily=DailyBar(sid,'MORF','SEC_CIK:1679363',day,signal,float(quote['raw_open']),
            float(quote['raw_close']),tradeable=quote['tradeable']=='1',split_ratio=float(quote['split_ratio']),
            dividend_per_share=float(quote['dividend_per_share']))
        # Explicit disposable numerical-feature input exercises the actual
        # post-ranking veto. It is never a forecast or a financial predecessor.
        candidate=SecurityBar(sid,'MORF','SEC_CIK:1679363',[signal]*127,
            raw_close=float(quote['raw_close']),eligible=True,certified_signals=(.5,.02,.1,5.))
        return adapter.step_session(session=day,state=state,pending=orders,ledger=ledger,last_known=last,
            cfg=cfg,strategy_id='RESEARCH_MORF_CANONICAL_COMPONENT_ONLY',strategy_version=1,
            bars=[daily],security_bars=[candidate],terminal_terms=events)

    held=fixture(held=True);held_result=step(held,[complete])
    need(not held[0].episodes and not held[1] and math.isclose(held[0].cash,9570.,abs_tol=1e-8,rel_tol=0),
         'MORF_GATE_CANONICAL_HELD_CASH_57_REMOVAL_WITH_POSITIVE_QUOTE')
    paid=[v for v in held[2].events if v.security_id==sid and v.event_type.value=='CASH_MERGER']
    need(len(paid)==1 and paid[0].price==57. and paid[0].cash_delta==570.,'MORF_GATE_EXACT_CASH_NOT_EXECUTABLE_QUOTE')
    once=deepcopy((held[0].to_dict(),held[2].to_dict()))
    repeat=apply_terminal(held[0],complete,ledger=held[2],session=day,cfg=cfg)
    need(repeat==dict(applied=False,reason='NOT_HELD',security_id=sid)
         and (held[0].to_dict(),held[2].to_dict())==once,'MORF_GATE_REPEAT_PAYMENT_REFUSES_UNCHANGED')
    pending=fixture(pending_entry=True);pending_result=step(pending,[complete])
    need(not pending[0].episodes and not pending[1] and not pending_result.fills and pending[0].cash==9000.
         and any(v['reason']=='TERMINATED_BEFORE_FILL' for v in pending_result.cancelled),
         'MORF_GATE_PENDING_BUY_CANCELLED_BEFORE_POSITIVE_RAW_OPEN')
    control=fixture();control_result=step(control,[])
    need(any(v.operation is Operation.OPEN_SLOT_POSITION and v.security_id==sid for v in control_result.decision.operations),
         'MORF_GATE_CONTROL_FIXTURE_MUST_ACTUALLY_ADMIT_WITHOUT_TERMINAL')
    veto=fixture();veto_result=step(veto,[complete]);require_veto(veto_result,sid)
    need(control_result.decision.to_dict()['candidates']==veto_result.decision.to_dict()['candidates']
         and not veto[0].episodes and not veto[1] and not veto_result.fills,
         'MORF_GATE_VETO_PRESERVES_ELIGIBLE_SCORING_CROSS_SECTION')
    original_decide=adapter.decide
    def without_veto(**kwargs):
        kwargs['admission_veto_security_ids']=set();return original_decide(**kwargs)
    adapter.decide=without_veto
    try:
        altered=step(fixture(),[complete])
        try:require_veto(altered,sid)
        except ValueError as error:need(str(error)=='REFUSED_FULL_SYSTEM_MORF_CANONICAL_ACTUAL_TERMINAL_DAY_ADMISSION_VETO',
                                      'MORF_GATE_REMOVED_VETO_ACTUAL_FALSIFIER_REASON')
        else:raise ValueError('MORF_GATE_ACTUAL_VETO_REMOVAL_DID_NOT_BREAK_CASE')
    finally:adapter.decide=original_decide
    need(adapter.decide is original_decide and runtime.checkpoint(restored)==cp['run']
         and digest(asdict(packet))==original_before and digest(quote)==quote_hash,
         'MORF_GATE_FIXTURES_AND_FALSIFIER_LEAVE_PARENT_SOURCE_AND_CANONICAL_FUNCTION_UNCHANGED')
    save(out/'morf-quote-coexistence-canonical-qualification.json',dict(
        status='MORF_ACTUAL_CANONICAL_QUOTE_CASH_PENDING_AND_ADMISSION_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'],quote_observation_sha256=quote_hash,
        original_packet_sha256=original_before,original_incomplete_guard_refused=True,
        actual_leadership_cash_notional=expected,held_fixture_shares=10,held_fixture_cash_paid=570.,
        actual_cash_wins_over_executable_print=True,actual_once_only_payment=True,
        actual_pending_entry_cancelled_before_fill=True,actual_terminal_day_admission_veto=True,
        actual_without_terminal_control_admitted=True,scoring_candidates_unchanged=True,
        actual_veto_removal_falsifier_passed=True,canonical_function_restored=True,
        original_quote_volume_and_flags_unchanged=True,actual_parent_roundtrip=True,
        actual_parent_unchanged=True,disposable_fixture_sessions=5,
        qualification_copy_only=True,financial_sessions_advanced=0,production_contacted=False))
