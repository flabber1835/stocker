"""Hosted actual-packet and joint-controller gate; no market sessions advanced."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
from types import SimpleNamespace
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest
from system_campaign_zogenix_input import SID,NATIVE,DAY,parse,require_no_position
from system_campaign_zogenix_facts import PRIVATE,evidence
from system_campaign_zogenix_sensor import SensorCertificate,check_inherited
from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
from system_campaign_uncertainty_gate import certified_recovery


def qualify(out,cp,objects,loaded,codec,request):
    hosted();check_inherited()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from sentinel.core.session import PublishedSession
    from sentinel.controller import terminal_returns,median5,champion_config
    from research.pooled_vacancy_funding import backtest
    from research.bounded_20y.run import vendor
    from system_campaign_sprint_facts import qualify_packet_schema
    qualify_packet_schema(Packet,request['qualified_packet_source_sha256'])
    source=json.loads((out/PRIVATE).read_bytes());actions=inputs.load_actions(Path('/frozen/bundle'))
    last,=[v for v in source['source_witnesses'] if v['session']==NATIVE]
    bar=vendor(last);native=codec.native;fixed={}
    for day in (NATIVE,DAY):
        packet=Packet(day,(bar,) if day==NATIVE else (),{},{},1.,{},tuple(actions.terminal.get(day,())),())
        before=digest(asdict(packet));value=packet
        for obj in [*objects,loaded]:value=backtest.apply_repair(value,obj)
        need(digest(asdict(packet))==before and value.bars==packet.bars,'ZOGENIX_ORIGINAL_PACKET_AND_QUOTES_PRESERVED')
        matches=[t for t in value.terminal if t.security_id==SID]
        need(matches==([] if day==NATIVE else [replace(native,session=DAY)]),'ZOGENIX_ACTUAL_CANONICAL_RECALENDAR')
        fixed[day]=value
    prior=SimpleNamespace(wealth_core={'episodes':{}},pending=[],median5={'selected':[SID]},last_processed_session=NATIVE,
        feed={'series':{SID:{'signal_basis_anchor':[NATIVE,float(last['raw_close']),float(last['signal_close'])]}}})
    published=PublishedSession(session=DAY,data_version=1,bars=(),meta={},sectors={},spy_closeadj=[1.],terminal_events=fixed[DAY].terminal)
    try:terminal_returns.values(prior=prior,published=published)
    except ValueError as e:need(str(e)=='incomplete leadership cash terminal: '+SID,'ZOGENIX_ORIGINAL_CANONICAL_REFUSAL')
    else:raise ValueError('REFUSED_ZOGENIX_ORDINARY_GUARD_MISSING')
    probe=SensorCertificate.__new__(SensorCertificate);probe.zcodec=codec;probe.znative=native;probe.zsource=source;probe.original_values=terminal_returns.values
    values=probe.values(prior=prior,published=published)
    need(values[SID]==probe.event_bounds.lo and probe.zbasis['selected'],'ZOGENIX_ACTUAL_SENSOR_GATE')
    for changed in (SimpleNamespace(**{**vars(prior),'wealth_core':{'episodes':{'x':{'security_id':SID}}}}),
                    SimpleNamespace(**{**vars(prior),'pending':[{'security_id':SID}]})):
        try:probe.values(prior=changed,published=published)
        except ValueError:pass
        else:raise ValueError('REFUSED_ZOGENIX_OWNED_OR_ORDERED_GATE_MISSING')
    for cursor,pred in ((cp['source_cursor'],'0'*64),(NATIVE,cp['run']['checkpoint_sha256'])):
        try:parse(out/'zogenix-sensor-input.json',resume_session=cursor,predecessor_checkpoint_sha256=pred,
                  expected_evidence=evidence(out),native_sha256=codec.native_sha256)
        except ValueError:pass
        else:raise ValueError('REFUSED_ZOGENIX_PREDECESSOR_OR_CONSUMED_GUARD_MISSING')
    # Two distinct uncertain factors reach the same unchanged rolling proof
    # and actual canonical recovery function. This is synthetic, not P02 P/L.
    state=median5.fresh(champion=True);prefix=[1.02**n for n in range(41)]
    state.update(last_session='joint-000',witness_nav=prefix,selected=['OLD-CVR',SID,'OTHER'],
                 selected_closes={'OLD-CVR':20.,SID:28.,'OTHER':100.})
    math=RollingWitnessBounds(prefix);calls=checks_count=0
    for day in range(1,71):
        terminals={'OLD-CVR'} if day==1 else {SID} if day==12 else set()
        prices={s:state['selected_closes'][s]*1.02 for s in state['selected'] if s not in terminals}
        terminal_values={'OLD-CVR':18.} if day==1 else {SID:26.} if day==12 else {}
        returns=[]
        for sid in state['selected']:
            current=Interval(18.,20.) if sid=='OLD-CVR' and day==1 else Interval(26.,28.) if sid==SID and day==12 else Interval.point(prices[sid])
            returns.append(current.div(Interval.point(state['selected_closes'][sid])).sub(Interval.point(1.)))
        members=([SID] if day<12 else [])+['OTHER']
        state,observed=median5.witness(state,session=f'joint-{day:03d}',
            candidates=[SimpleNamespace(security_id=s,recent=1.) for s in members],closes=prices,
            terminals=terminals,terminal_values=terminal_values)
        math.advance(growth(returns),state['witness_nav'][-1]);bounds={f'recent_r{k}':math.period(k) for k in (20,40)}
        kwargs=dict(state=state,native=1.,wc_drawdown=-.05,spy_r20=.02,wc_r20=.01,**observed)
        (state,_),checks=certified_recovery(champion_config.recover,kwargs,bounds);calls+=1;checks_count+=len(checks)
        if day in (2,13,43):math=RollingWitnessBounds.restore(math.snapshot())
    ambiguous=dict(kwargs,recent_r20=-.01,recent_r40=.1)
    try:certified_recovery(champion_config.recover,ambiguous,{'recent_r20':Interval(-.02,.02),'recent_r40':Interval.point(.1)})
    except ValueError as e:need('AMBIGUOUS_CONTROLLER_COMPARISON' in str(e),'ZOGENIX_ACTUAL_CROSSING_REFUSAL')
    else:raise ValueError('REFUSED_ZOGENIX_COMPARISON_GUARD_MISSING')
    save(out/'zogenix-canonical-qualification.json',dict(status='ACTUAL_PACKETS_AND_JOINT_CANONICAL_GATE_PASSED',
        actual_packets=2,retained_inputs=len(objects),original_incomplete_term_refused=True,original_packets_preserved=True,
        actual_owned_and_pending_refusals=True,wrong_predecessor_and_consumed_refused=True,
        actual_canonical_recovery_calls=calls,invariant_comparisons=checks_count,actual_crossing_refused=True,
        serialized_joint_continuations=3,financial_sessions_advanced=0,production_contacted=False))
