"""Hosted action fixtures and read-only historical raw-domain admission."""
import argparse,gzip,hashlib,inspect,json,os,sys,time
from decimal import Decimal as D
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace,ModuleType
from holding_account import Account,Position,RawOpen,Intent,trade,mark,accrue,pay,split,cash_merger,snapshot,restore,state,digest,need
from holding_actions import Terms,convert,receive_spinoff,liquidate_children
from holding_prices import qualify_prices

SOURCE='a'*64;INPUT='b'*64;DAY='2026-01-05';NEXT='2026-01-06';LATER='2026-01-07'


def seed(quantities=('7','14'),sid='S'):
    return Account(source_sha256=SOURCE,cash='1000',positions={str(i):Position(episode=str(i),security_id=sid,
        ticker=sid,shares=q) for i,q in enumerate(quantities)},last_session='2026-01-02')


def terms(a,identifier,**kw):
    value=dict(event_id=identifier,session=DAY,security_id='S',delivered_security_id='T',delivered_ticker='T',
        ratio='.5',reference='SYNTHETIC_QUALIFICATION_ONLY',input_sha256=INPUT,
        predecessor_sha256=snapshot(a)['state_sha256'])
    value.update(kw);return Terms(**value)


def action_cases(output,terminal,spinoffs,core_state,ledger,config,shares):
    started=time.perf_counter();cases=[];refusals=[]
    def save(name,before,after,events,**extra):
        value=dict(name=name,before=snapshot(before),after=snapshot(after),events=events,**extra);cases.append(value)
        (output/'case-prefix.json').write_text(json.dumps(dict(cases=cases,refusals=refusals),indent=2)+'\n')
    def refuse(name,call,account):
        before=snapshot(account)
        try:call()
        except (ValueError,TypeError) as exc:
            need(snapshot(account)==before,'REFUSAL_MUTATED_PREDECESSOR');refusals.append(dict(name=name,error=str(exc)));return
        raise AssertionError('FORBIDDEN_ACCEPTED_'+name)
    def cil(fraction,t):
        cls=terminal.RoundedTerminalTerms if t.rounding!='EXACT' else terminal.TerminalTerms
        canonical=cls(t.session,t.security_id,terminal.TerminalKind.CONVERSION,
            exchange_ratio=t.ratio,cash_in_lieu_price_per_delivered_share=None if t.cil_price is None else float(t.cil_price))
        return terminal._cash_in_lieu(fraction,canonical)
    def conversion(a,t):return convert(a,t,canonical_entitlement=terminal._split_entitlement,canonical_cil=cil)

    initial=seed();t=terms(initial,'conversion',cil_price='20')
    converted,e=conversion(initial,t)
    need(converted.positions['0'].shares==Q(10,3) and converted.positions['1'].shares==Q(20,3)
        and converted.cash==1010 and all(p.security_id=='T' for p in converted.positions.values()),'EXACT_PRO_RATA_HOLDER_CONVERSION')
    need(snapshot(initial)['state_sha256']==t.predecessor_sha256,'UNCHANGED_ORIGINAL_ACTION_PREDECESSOR')
    save('holder_conversion_exact_recurring_lots',initial,converted,[e],canonical_entitlement=['10','1/2'])
    mixed,e=conversion(initial,terms(initial,'mixed',cash_per_share='3.25',cil_price='20'))
    need(mixed.cash==Q('1078.25'),'MIXED_CASH_ENTITLEMENT');save('mixed_cash_stock',initial,mixed,[e])
    rounded_seed=seed(('3',));rounded,e=conversion(rounded_seed,terms(rounded_seed,'halfup',ratio='1.325',cil_price='20',rounding='NEAREST_HUNDREDTH_HALF_UP'))
    need(rounded.cash==Q('1019.6') and e['event']['exact_fraction']=='39/40'
        and e['event']['settlement_fraction']=='49/50','DECLARED_HALF_UP_NOT_EXACT')
    save('explicit_half_up_cil',rounded_seed,rounded,[e])
    tiny=seed(('1',));zero,e=conversion(tiny,terms(tiny,'zero',ratio='.25',cil_price='20'))
    need(not zero.positions and zero.cash==1005 and zero.retired==('0',),'ZERO_WHOLE_CONVERSION')
    save('zero_whole_delivered_cash_only',tiny,zero,[e])
    # Conversion must leave a pre-existing delivered-security episode separate.
    existing=seed().model_copy(update=dict(positions={**initial.positions,'oldT':Position(episode='oldT',security_id='T',ticker='T',shares='5')}))
    combined,e=conversion(existing,terms(existing,'existing-target',cil_price='20'))
    need(combined.positions['oldT']==existing.positions['oldT'] and len(combined.positions)==3,'DELIVERED_SECURITY_EPISODES_COLLAPSED')
    save('existing_delivered_episode_preserved',existing,combined,[e])
    # Actual funded dividend entitlement persists after source identity changes.
    entitled,e0=accrue(initial,event_id='div',session=DAY,claim_id='D1',security_id='S',cash_per_share='2',pay_session=LATER)
    ent_converted,e1=conversion(entitled,terms(entitled,'convert-after-ex',session=NEXT,cil_price='20'))
    paid,e2=pay(ent_converted,event_id='pay',session=LATER,claim_id='D1')
    need(paid.cash==1052 and not paid.claims,'DIVIDEND_THROUGH_CONVERSION')
    save('claim_survives_conversion',initial,paid,[e0,e1,e2])
    spun,e0=receive_spinoff(initial,terms(initial,'spin',delivered_security_id='C',delivered_ticker='C',cil_price='20'))
    need(all(spun.positions[k]==p for k,p in initial.positions.items()),'SPINOFF_CHANGED_PARENT')
    child_keys=[k for k,p in spun.positions.items() if p.kind=='ACTION_CHILD']
    need([spun.positions[k].shares for k in child_keys]==[Q(10,3),Q(20,3)],'SPINOFF_HOLDER_ALLOCATION')
    liquidated,e1=liquidate_children(spun,event_id='spin-sell',session=DAY,security_id='C',quote=RawOpen(session=DAY,security_id='C',price='20'))
    need(liquidated.cash==Q('1209.8') and liquidated.positions==initial.positions,'SPINOFF_SINGLE_FEE')
    # Actual frozen first-open spinoff operation, not merely a helper formula.
    canonical=core_state.PortfolioState.fresh(1000,n_slots=20,entry_sizing_profile='wealth-core-v5-zero-share-fixed-2008-v1')
    for index,q in enumerate((7,14)):
        ep=core_state.HoldingEpisode('S','S','SID:S',index,'2025-12-01','2025-12-02',10,10,q,q,
            episode_peak_split_adjusted_close=10,market_sessions_held=17,review_completed=True,source_lots=[])
        canonical.episodes[index]=ep;canonical.slots[index].occupied_by='S'
    distribution=spinoffs.SpinoffDistribution(DAY,'S','S','C','C','SYNTHETIC',None,child_shares_per_parent='.5',
        child_price='20',cash_in_lieu_price='20',policy=spinoffs.LIQUIDATE_CHILD_AT_OPEN)
    bars=[SimpleNamespace(security_id=s,ticker=s,session=DAY,raw_open=20,tradeable=True) for s in ('S','C')]
    oracle_ledger=ledger.Ledger();audits=spinoffs.apply_supported_entitlements(canonical,[distribution],bars=bars,ledger=oracle_ledger,config=config)
    need(abs(Q(str(canonical.cash))-liquidated.cash)<=Q('1e-10') and len(audits)==1,'FROZEN_SPINOFF_ORACLE')
    save('spinoff_receipt_and_first_open_liquidation',initial,liquidated,[e0,e1],
        intermediate=snapshot(spun),canonical_cash=str(canonical.cash),canonical_audit=audits)
    # Restore at recurring fractions; then sell part of one converted lot exactly.
    boundary=snapshot(converted);recovered=restore(json.loads(json.dumps(boundary)),SOURCE)
    intent=Intent(event_id='fraction-sell',signal_session=DAY,execution_session=NEXT,episode='0',security_id='T',ticker='T',side='SELL',shares='1/3')
    quote=RawOpen(session=NEXT,security_id='T',price='10')
    uninterrupted,e0=trade(converted,intent,quote);continued,e1=trade(recovered,intent,quote)
    need(snapshot(uninterrupted)==snapshot(continued) and e0==e1 and continued.positions['0'].shares==3,'RECURRING_RESTART_SUFFIX')
    child_restart=restore(json.loads(json.dumps(snapshot(spun))),SOURCE)
    resumed,e2=liquidate_children(child_restart,event_id='spin-sell',session=DAY,security_id='C',quote=RawOpen(session=DAY,security_id='C',price='20'))
    need(snapshot(resumed)==snapshot(liquidated),'CHILD_RESTART_SUFFIX')
    save('restart_after_conversion_and_spinoff',converted,continued,[e0],boundary=boundary,child_boundary=snapshot(spun),child_final=snapshot(resumed))
    # Regression of the /1 covered economic equations under the versioned /2 basis.
    a=Account(source_sha256=SOURCE,cash='1000');i=Intent(event_id='buy',signal_session=DAY,execution_session=NEXT,episode='E',security_id='S',ticker='S',side='BUY',shares='20')
    bought,e0=trade(a,i,RawOpen(session=NEXT,security_id='S',price='10'))
    need(bought.cash==Q('799.8') and mark(bought,{'S':'11'})==Q('1019.8'),'VERSION1_COVERED_ECONOMICS')
    split_value,e1=split(bought,event_id='split',session=LATER,security_id='S',ratio='1.5',canonical_split=shares.split_shares,raw_price='6')
    need(split_value.positions['E'].shares==30,'VERSIONED_SPLIT')
    merged,e2=cash_merger(split_value,event_id='cash',session=LATER,security_id='S',cash_per_share='27')
    need(merged.cash==Q('1609.8'),'VERSIONED_CASH_MERGER')
    save('versioned_account_existing_economics',a,merged,[e0,e1,e2])

    refuse('missing_cil',lambda:conversion(initial,terms(initial,'bad')),initial)
    refuse('wrong_predecessor',lambda:conversion(initial,terms(initial,'bad',predecessor_sha256='0'*64,cil_price='20')),initial)
    refuse('duplicate_conversion',lambda:conversion(converted,t),converted)
    refuse('wrong_source_sid',lambda:conversion(initial,terms(initial,'bad',security_id='WRONG',cil_price='20')),initial)
    refuse('same_source_delivered',lambda:terms(initial,'bad',delivered_security_id='S'),initial)
    refuse('unsupported_rounding',lambda:terms(initial,'bad',rounding='ROUND_DOWN'),initial)
    refuse('nonfinite_ratio',lambda:terms(initial,'bad',ratio='NaN'),initial)
    refuse('missing_reference',lambda:terms(initial,'bad',reference=''),initial)
    refuse('forged_checkpoint',lambda:restore({**boundary,'state_sha256':'0'*64},SOURCE),converted)
    refuse('wrong_checkpoint_source',lambda:restore(boundary,'c'*64),converted)
    refuse('wrong_child_quote',lambda:liquidate_children(spun,event_id='bad',session=DAY,security_id='C',quote=RawOpen(session=DAY,security_id='S',price='20')),spun)
    refuse('double_child_sale',lambda:liquidate_children(liquidated,event_id='bad',session=DAY,security_id='C',quote=RawOpen(session=DAY,security_id='C',price='20')),liquidated)
    refuse('child_increase',lambda:trade(spun,Intent(event_id='bad',signal_session=DAY,execution_session=NEXT,
        episode=child_keys[0],security_id='C',ticker='C',kind='ACTION_CHILD',side='BUY',shares='1'),RawOpen(session=NEXT,security_id='C',price='20')),spun)
    # Actual guard removal must accept the forged predecessor the original rejects.
    import holding_actions as module
    text=Path(module.__file__).read_text();broken=text.replace("need(snapshot(account)['state_sha256']==terms.predecessor_sha256,'REFUSED_ACTION_PREDECESSOR')","need(True,'REFUSED_ACTION_PREDECESSOR')")
    need(text!=broken,'PREDECESSOR_FALSIFIER_MATCH');mutant=ModuleType('holding_action_removed_guard');sys.modules[mutant.__name__]=mutant
    exec(compile(broken,'removed-action-predecessor','exec'),mutant.__dict__)
    forged=terms(initial,'guard-falsifier',cil_price='20',predecessor_sha256='0'*64)
    mutant.convert(initial,forged,canonical_entitlement=terminal._split_entitlement,canonical_cil=cil)
    result=dict(status='FUNDED_ACTION_COMPONENTS_PASSED',cases=len(cases),refusals=len(refusals),
        predecessor_guard_removal_accepted=True,canonical_spinoff_called=True,canonical_entitlement_and_cil_called=True,
        serialization_schema='research.persistent-funded-account-prototype/2',processing_seconds=time.perf_counter()-started)
    (output/'cases.json').write_text(json.dumps(dict(summary=result,cases=cases,refusals=refusals),indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_ACTION_QUALIFICATION')
    from stock_strategy_shared.wealth_core import terminal,state as core_state,ledger,v5,engine,shares
    from sentinel.core import spinoffs
    cp=json.loads(gzip.decompress((a.root/'checkpoint.json.gz').read_bytes()));bindings={}
    for module in (terminal,core_state,ledger,v5,spinoffs,engine,shares):
        path=Path(module.__file__);need(str(path).startswith('/fixed/'),'FROZEN_ACTION_MODULE_LOCATION')
        rel=str(path).removeprefix('/fixed/');actual=hashlib.sha256(path.read_bytes()).hexdigest()
        need(cp['base']['sources'][rel]==actual,'FROZEN_ACTION_MODULE_HASH');bindings[rel]=actual
    review=json.loads((a.root/'fixed-review.json').read_bytes())
    need(review['final_file_sha256']==hashlib.sha256((a.root/'checkpoint.json.gz').read_bytes()).hexdigest()
        and review['journal_commitments']==cp['journals'] and review['canonical_roundtrip'] and review['full_chain_verified'],'ORIGINAL_REVIEW_BINDING')
    rows=[]
    for name,n in (('formation',126),('daily',4639)):
        raw=(a.root/(name+'.jsonl')).read_bytes()
        need(len(raw)==cp['journals'][name]['bytes'] and hashlib.sha256(raw).hexdigest()==cp['journals'][name]['prefix_sha256'],'ORIGINAL_PREFIX_HASH')
        values=[json.loads(r) for r in raw.splitlines()];need(len(values)==n,'ORIGINAL_ROW_COUNT');rows.extend(values)
    events=cp['run']['state']['ledger']['events'];archive_sha=hashlib.file_digest(a.archive.open('rb'),'sha256').hexdigest()
    need(archive_sha==cp['base']['archive_sha256'],'ORIGINAL_ARCHIVE_HASH')
    del cp
    output=a.output;output.mkdir(exist_ok=False);started=time.perf_counter()
    cases=action_cases(output,terminal,spinoffs,core_state,ledger,v5.research_config('wealth-core-v5-zero-share-fixed-2008-v1'),shares)
    prices=qualify_prices(rows,events,a.archive,a.bundle,output/'prices')
    ready=prices['equity_raw_domain_covered'] and prices['defensive_raw_bil_complete']
    result=dict(schema='research.holding-action-price-result/1',status='ACTION_PRICE_QUALIFICATION_COMPLETE',
        components=cases,prices=prices,canonical_source_bindings=bindings,archive_sha256=archive_sha,
        matched_H0_raw_instrument_ready=ready,full_P2_ready=False,P2_policy_executed=False,
        historical_funded_accounts_executed=0,canonical_strategy_transitions_executed=0,production_contacted=False,
        total_processing_seconds=time.perf_counter()-started)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print('ACTION_PRICE_QUALIFICATION_FINISHED')


if __name__=='__main__':main()
