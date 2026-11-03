"""Hosted cumulative canonical qualification before the exact financial suffix."""
from dataclasses import asdict
from copy import deepcopy
from pathlib import Path
import json
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest
from system_campaign_future_amendment import (
    TARGET,CORRECT,SID,CUTOVER,INNER,RETIRED_ADD,PRESERVED_ADD,validate_conflict,projection)
from system_campaign_sprint_facts import published_packet,qualify_packet_schema


def expect_refusal(fn,code):
    try:fn()
    except ValueError:return
    raise ValueError('REFUSED_AMENDMENT_FALSIFIER_'+code)


def qualify(cp,root,cash,amendment,packet_source_sha256):
    hosted()
    from research.pooled_vacancy_funding import backtest,repair
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from types import SimpleNamespace
    qualify_packet_schema(Packet,packet_source_sha256)
    old=[backtest.load_repair(root/'book/repairs'/d['filename'],resume_session=d['resume_session'],
         predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp['repairs']]
    loaded=backtest.load_repair(amendment.overlay,resume_session=CUTOVER,predecessor_checkpoint_sha256=INNER)
    need(amendment.active,'AMENDMENT_ACTUAL_ORDINARY_ACTIVATION')
    docs=amendment.original_docs;actions=inputs.load_actions(Path('/frozen/bundle'))
    tlry=next(r for r in amendment.payload['cash_witnesses']['witnesses']
              if r['session']=='2021-05-03' and r['security_id']=='653423826172679659')
    bar=vendor(tlry);checks=0;unamended_refusals=0
    def apply(packet,objects,fn):
        for obj in objects:packet=fn(packet,obj)
        return packet
    for day in ('2021-04-30','2021-05-03'):
        original=Packet(day,(bar,) if day=='2021-05-03' else (),{},{},1.,{},tuple(actions.terminal.get(day,())),())
        before=digest(asdict(original))
        # Original cumulative composition MUST fail under the original adapter.
        expect_refusal(lambda:apply(original,old,amendment.original_apply),'ORIGINAL_DUPLICATE_COMPOSITION');unamended_refusals+=1
        fixed=apply(original,[*old,loaded],backtest.apply_repair);matches=[r for r in fixed.terminal if r.security_id==SID]
        need(digest(asdict(original))==before,'AMENDMENT_ORIGINAL_RAW_PACKET_UNCHANGED')
        if day=='2021-04-30':need(not matches,'AMENDMENT_PRIOR_APHA_LAST_TRADING_DAY_PRESERVED')
        else:
            need(len(matches)==1 and digest(asdict(matches[0]))==PRESERVED_ADD
                 and matches[0].cash_in_lieu_price_per_delivered_share==0.,'AMENDMENT_EXACT_PRIOR_ZERO_CIL_TERM_ONCE')
            prior=SimpleNamespace(median5={'selected':[SID]},feed={'series':{SID:{'signal_basis_anchor':('2021-04-30',1.,1.)}}},last_processed_session='2021-04-30')
            value=terminal_returns.values(prior=prior,published=published_packet(fixed))
            from fractions import Fraction
            need(value[SID]==float(Fraction('.8381')*Fraction(str(bar.raw_close))),
                 'AMENDMENT_ACTUAL_CANONICAL_APHA_STOCK_NOTIONAL')
        checks+=1
    target=next(v for v in old if v.sha256==TARGET)
    days=sorted({r['session'] for field in ('suppress','add') for r in docs[TARGET][field] if r['security_id']!=SID})
    for day in days:
        original=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
        before=digest(asdict(original));original_target=amendment.original_apply(original,target)
        projected=backtest.apply_repair(original,target)
        need(asdict(original_target)==asdict(projected) and digest(asdict(original))==before,
             'AMENDMENT_ALL_OTHER_TARGET_PACKET_OPERATIONS_UNCHANGED');checks+=1
    # Direct binding/consumption/term/activation falsifiers, never a skipped case.
    expect_refusal(lambda:backtest.load_repair(amendment.overlay,resume_session=CUTOVER,predecessor_checkpoint_sha256='0'*64),'WRONG_PREDECESSOR')
    expect_refusal(lambda:backtest.load_repair(amendment.overlay,resume_session='2021-04-15',predecessor_checkpoint_sha256=INNER),'CONSUMED_NEW_FACT')
    wrong=deepcopy(cp);wrong['source_cursor']='2021-04-30'
    expect_refusal(lambda:validate_conflict(wrong,docs),'CONSUMED_PROJECTION_BOUNDARY')
    for h in (TARGET,CORRECT):
        wrong=deepcopy(docs);wrong[h]['add'][0]['reference']+=' changed'
        if h==TARGET:
            wrong=deepcopy(docs);next(v for v in wrong[h]['add'] if v['security_id']==SID)['exchange_ratio']=.8
        else:next(v for v in wrong[h]['add'] if v['security_id']==SID)['cash_in_lieu_price_per_delivered_share']=1.
        expect_refusal(lambda:validate_conflict(cp,wrong,),'CHANGED_TARGET_OR_CORRECT_TERM')
    amendment.active=False
    try:expect_refusal(lambda:backtest.apply_repair(original,target),'WRONG_ACTIVATION')
    finally:amendment.active=True
    cash.qualify(loaded,old,root/'cash-batch-input-qualification.json',packet_source_sha256=packet_source_sha256)
    save(root/'future-input-amendment-qualification.json',dict(schema='research.future-input-amendment-qualification/1',
        status='CUMULATIVE_CANONICAL_INPUTS_QUALIFIED',actual_APHA_packet_checks=2,
        other_target_packet_checks=checks-2,unamended_composition_refusals=unamended_refusals,
        exact_prior_zero_fractional_payment_preserved=True,original_descriptor_and_packets_unchanged=True,
        wrong_predecessor_consumed_wrong_term_and_activation_falsifiers=True,
        new_overlay_sha256=loaded.sha256,financial_sessions_advanced=0,production_contacted=False))
    return loaded
