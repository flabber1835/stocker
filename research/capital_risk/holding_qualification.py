"""Hosted synthetic account qualification plus read-only committed identity audit."""
from __future__ import annotations
import argparse,hashlib,inspect,json,os,sys,time
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace,ModuleType

from holding_account import Account,Position,Intent,RawOpen,trade,mark,split,accrue,pay,cash_merger,snapshot,restore,state,need,FEE
from holding_identity import bind_book

SOURCE='a'*64
DAY='2026-01-05';NEXT='2026-01-06';THIRD='2026-01-07';FOURTH='2026-01-08'

def seed(cash='1000',shares='20',other=False):
    positions={'E':Position(episode='E',security_id='S',ticker='S',shares=shares)}
    if other:positions['U']=Position(episode='U',security_id='U',ticker='U',shares='7')
    return Account(source_sha256=SOURCE,cash=cash,positions=positions,last_session='2026-01-02')

def fill(account,identifier,side,quantity,price,*,episode='E',sid='S',kind='EQUITY',signal=DAY,execution=NEXT,live=True,core_exit=False):
    return trade(account,Intent(event_id=identifier,signal_session=signal,execution_session=execution,
        episode=episode,security_id=sid,ticker=sid,kind=kind,side=side,shares=quantity,source_episode_live=live,core_exit=core_exit),
        RawOpen(security_id=sid,session=execution,price=price))

def refuses(call,label):
    try:call()
    except (ValueError,TypeError) as exc:return dict(case=label,error=str(exc))
    raise AssertionError('FORBIDDEN_OPERATION_ACCEPTED_'+label)

def scalar_counterexample(CanonicalAccount):
    adapter=CanonicalAccount('100',formed=False)
    previous=dict(strategy_nav='100',last_session='2026-01-02',pending_allocation='.55',held_allocation='.55',parent_core_close_equity='100')
    actual=[]
    for day,opening,closing in [(DAY,'100','120'),(NEXT,'120','96')]:
        prices=dict(bil_open_signal='1',bil_close_signal='1',bil_open_adjusted='1',bil_close_adjusted='1',bil_close_unadjusted='1',
            bil_previous_close_adjusted='1',bil_previous_session=previous['last_session'])
        envelope=SimpleNamespace(last_processed_session=day,shadow_nav_history=[float(closing)],
            last_evidence=dict(wealth_core=dict(session=day,blocked=False,resolved_equity=float(closing),
                estimated_equity=float(closing),resolved_open_equity=float(opening),open_unresolved_security_ids=[]),
                observation=dict(shadow_nav=float(closing))),last_decision=dict(target_core_exposure=.55))
        previous=adapter.advance(previous=previous,state=envelope,strategy_prices=prices);actual.append(previous)
    holding=seed('45','55');values=[mark(holding,{'S':'1.2'}),mark(holding,{'S':'.96'})]
    need([D(x['strategy_nav']) for x in actual]==[D('111'),D('98.79')],'CANONICAL_SCALAR_COUNTEREXAMPLE')
    need(values==[D('111'),D('97.80')],'PERSISTENT_COUNTEREXAMPLE')
    return dict(status='MODEL_CHANGED_PROVEN',canonical_scalar=actual,persistent_holding_navs=list(map(str,values)),
        difference_at_second_close=str(D(actual[-1]['strategy_nav'])-values[-1]),
        allocation='.55',stock_prices=['1','1.2','.96'],fees_during_example='0',no_strategy_performance_inference=True)

def qualify(output,canonical):
    started=time.perf_counter();cases=[];negative=[];events=[]
    cfg=canonical['config']
    # Disabled local allocation: identical persistent-account states, not old scalar parity.
    left=Account(source_sha256=SOURCE,cash='1000');right=Account(source_sha256=SOURCE,cash='1000')
    for account_name in ('left','right'):
        a=left if account_name=='left' else right
        a,event=fill(a,'entry','BUY','20','10');events.append(event)
        if account_name=='left':left=a
        else:right=a
    need(snapshot(left)==snapshot(right),'DISABLED_LAYER_ALL_STATE_EQUALITY')
    before=snapshot(left);values=[mark(left,{'S':'11'}),mark(left,{'S':'9'})]
    need(values==[D('1019.8'),D('979.8')] and snapshot(left)==before,'NO_DAILY_REBALANCE')
    need(left.cash==D('799.8') and left.positions['E'].shares==20,'ENTRY_FEE')
    entry_oracle=str(canonical['entry_cost'](20,10,cfg))
    need(abs(D(entry_oracle)-D('200.2'))<=D('1e-10'),'CANONICAL_ENTRY_COST')
    cases.append(dict(name='unchanged_and_disabled_neutral_control',state=state(left),marks=list(map(str,values)),
        canonical_float_entry_cost=entry_oracle,oracle_monetary_tolerance='1e-10',disabled_state_hash=snapshot(left)['state_sha256']))

    initial=seed(other=True);saved=snapshot(initial)
    reduced,event=fill(initial,'trim','SELL','9','12');events.append(event)
    need(snapshot(initial)==saved and reduced.positions['E'].shares==11 and reduced.positions['U']==initial.positions['U'],'TRIM_QUANTITY_AND_UNFLAGGED')
    need(reduced.cash==D('1107.892') and abs(D(str(canonical['exit_proceeds'](9,12,cfg)))-D('107.892'))<=D('1e-10'),'CANONICAL_PARTIAL_SELL_COST')
    defended,event=fill(reduced,'defensive-buy','BUY','100','1',episode='BIL',sid='BIL',kind='DEFENSIVE');events.append(event)
    need(defended.cash==D('1007.792') and mark(defended,{'S':'12','U':'30','BIL':'1'})==D('1449.792'),'DEFENSIVE_ROUTE_SINGLE_FEES')
    cases.append(dict(name='partial_trim_and_defensive_route',before=state(initial),after=state(defended),stock_sale_fee='.108',defensive_buy_fee='.1'))

    restored,event=fill(defended,'defensive-sell','SELL','100','1',episode='BIL',sid='BIL',kind='DEFENSIVE',signal=NEXT,execution=THIRD);events.append(event)
    restored,event=fill(restored,'restore','BUY','9','13',signal=NEXT,execution=THIRD);events.append(event)
    need(restored.positions['E'].shares==20 and restored.cash==D('990.575') and restored.positions['U'].shares==7,'RESTORE_CASH_AND_QUANTITY')
    clipped,event=fill(seed('20','11'),'clip','BUY','9','13');events.append(event)
    need(clipped.cash==D('6.987') and clipped.positions['E'].shares==12 and event['event']['filled_shares']=='1','CASH_CLIPPED_POSITIVE_FILL')
    zero,event=fill(seed('1','11'),'zero','BUY','9','13');events.append(event)
    need(zero.positions['E'].shares==11 and event['event']['outcome']=='CASH_CLIPPED_ZERO','EXPLICIT_ZERO_FILL')
    cases.append(dict(name='restoration_and_cash_clipping',restored=state(restored),clipped=state(clipped),zero=state(zero)))

    entitled,ev=accrue(seed('1000','11'),event_id='ex',session=NEXT,claim_id='D1',security_id='S',cash_per_share='2',pay_session=FOURTH);events.append(ev)
    sold,ev=fill(entitled,'sell-after-ex','SELL','11','12',signal=NEXT,execution=THIRD,core_exit=True);events.append(ev)
    paid,ev=pay(sold,event_id='pay',session=FOURTH,claim_id='D1');events.append(ev)
    need(mark(sold,{})==mark(paid,{})==D('1153.868') and paid.cash==D('1153.868'),'DIVIDEND_NO_DOUBLE_PROFIT')
    ledger=canonical['ledger']();ledger.accrue_dividend(session=NEXT,security_id='S',ticker='S',shares=11,per_share=2,cash=1000,due_in=1)
    unchanged,_=ledger.settle_due(session=THIRD,cash=float(sold.cash));canonical_cash,paid_events=ledger.settle_due(session=FOURTH,cash=unchanged)
    need(D(str(canonical_cash))==paid.cash and len(paid_events)==1 and ledger.receivable_total==0,'CANONICAL_DIVIDEND_ENTITLEMENT')
    negative.append(refuses(lambda:pay(sold,event_id='early',session=THIRD,claim_id='D1'),'early_dividend'))
    negative.append(refuses(lambda:pay(paid,event_id='pay-again',session=FOURTH,claim_id='D1'),'double_dividend'))
    cases.append(dict(name='dividend_survives_sale_and_pays_once',ex=state(entitled),sold=state(sold),paid=state(paid)))

    pre=seed('1000','15');post,ev=split(pre,event_id='split',session=NEXT,security_id='S',ratio='1.5',canonical_split=canonical['split_shares'],raw_price='6');events.append(ev)
    need(post.positions['E'].shares==D('22.5') and mark(pre,{'S':'9'})==mark(post,{'S':'6'})==D('1135'),'CANONICAL_SPLIT_NO_VALUE_LOSS')
    negative.append(refuses(lambda:split(pre,event_id='bad-split',session=NEXT,security_id='S',ratio=str(D(1)/7),canonical_split=canonical['split_shares'],raw_price='63'),'unrepresentable_split'))
    cases.append(dict(name='split_preserves_value_and_identity',before=state(pre),after=state(post)))

    merged,ev=cash_merger(seed('1000','11'),event_id='merger',session=NEXT,security_id='S',cash_per_share='27');events.append(ev)
    need(merged.cash==1297 and not merged.positions and merged.retired==('E',),'FUNDED_MERGER_ENTITLEMENT')
    canonical_state=canonical['portfolio'].fresh(1000,n_slots=20,entry_sizing_profile='wealth-core-v5-zero-share-fixed-2008-v1')
    ep=canonical['episode']('S','S','SID:S',0,'2025-12-01','2025-12-02',10,10,11,11,
        episode_peak_split_adjusted_close=10,market_sessions_held=17,review_completed=True,source_lots=[dict(kind='SYNTHETIC')])
    canonical_state.episodes[0]=ep;canonical_state.slots[0].occupied_by='S';canonical_ledger=canonical['ledger']()
    terms=canonical['terms'](NEXT,'S',canonical['terminal_kind'].CASH_MERGER,cash_per_share=27,reference='SYNTHETIC')
    canonical['apply_terminal'](canonical_state,terms,ledger=canonical_ledger,session=NEXT,cfg=cfg)
    need(D(str(canonical_state.cash))==merged.cash and not canonical_state.episodes,'CANONICAL_MERGER_ENTITLEMENT')
    negative.append(refuses(lambda:cash_merger(merged,event_id='merger-again',session=NEXT,security_id='S',cash_per_share='27'),'double_merger'))
    negative.append(refuses(lambda:fill(merged,'restore-retired','BUY','1','10',signal=NEXT,execution=THIRD),'restore_after_core_exit'))
    cases.append(dict(name='cash_merger_actual_funded_quantity',state=state(merged)))

    boundary=snapshot(entitled);recovered=restore(json.loads(json.dumps(boundary)),SOURCE)
    suffix1,ev1=fill(entitled,'suffix-sell','SELL','2','12',signal=NEXT,execution=THIRD)
    suffix2,ev2=fill(recovered,'suffix-sell','SELL','2','12',signal=NEXT,execution=THIRD)
    suffix1,ev3=pay(suffix1,event_id='suffix-pay',session=FOURTH,claim_id='D1')
    suffix2,ev4=pay(suffix2,event_id='suffix-pay',session=FOURTH,claim_id='D1')
    need(snapshot(suffix1)==snapshot(suffix2) and ev1==ev2 and ev3==ev4,'SERIALIZED_SUFFIX')
    (output/'account-boundary.json').write_text(json.dumps(boundary,indent=2)+'\n')
    prefix=json.dumps(ev1,sort_keys=True).encode()+b'\n';journal=prefix+json.dumps(ev3,sort_keys=True).encode()+b'\n'
    (output/'restart-journal.jsonl').write_bytes(journal)
    cases.append(dict(name='restart_preserves_prefix_state_and_suffix',boundary=boundary,final=snapshot(suffix1),prefix_bytes=len(prefix),prefix_sha256=hashlib.sha256(prefix).hexdigest(),journal_sha256=hashlib.sha256(journal).hexdigest()))

    for name,call in [
        ('same_close',lambda:fill(initial,'same','SELL','1','10',signal=DAY,execution=DAY)),
        ('oversell',lambda:fill(initial,'over','SELL','21','10')),
        ('wrong_instrument_price',lambda:trade(initial,Intent(event_id='wrong',signal_session=DAY,execution_session=NEXT,episode='E',security_id='S',ticker='S',side='SELL',shares='1'),RawOpen(security_id='U',session=NEXT,price='10'))),
        ('no_core_ownership_restore',lambda:fill(initial,'dead','BUY','1','10',live=False)),
        ('duplicate_trade',lambda:fill(reduced,'trim','SELL','1','12')),
        ('missing_mark',lambda:mark(initial,{'S':'10'})),
        ('forged_checkpoint',lambda:restore({**boundary,'state_sha256':'0'*64},SOURCE)),
        ('wrong_checkpoint_source',lambda:restore(boundary,'b'*64)),
    ]:
        negative.append(refuses(call,name))
    need(snapshot(initial)==saved,'REFUSALS_MUST_BE_ATOMIC')
    # Actual removal of the same-close guard must accept what the original refuses.
    import holding_account as account_module
    text=Path(account_module.__file__).read_text()
    broken=text.replace("need(self.execution_session>self.signal_session,'REFUSED_SAME_CLOSE_FILL')","need(True,'REFUSED_SAME_CLOSE_FILL')")
    need(broken!=text,'GUARD_REMOVAL_MATCH')
    mutant=ModuleType('holding_removed_lag_guard');sys.modules[mutant.__name__]=mutant
    exec(compile(broken,'removed-holding-lag-guard','exec'),mutant.__dict__)
    bad=mutant.Intent(event_id='mutant',signal_session=DAY,execution_session=DAY,episode='E',security_id='S',ticker='S',side='SELL',shares='1')
    need(bad.execution_session==bad.signal_session,'ACTUAL_LAG_GUARD_FALSIFIER')
    cases.append(dict(name='actual_lag_guard_removal_falsifier',original_refused=True,removed_guard_accepted=True))
    # Bounded microbenchmark is explicitly not a historical replay forecast.
    benchmark=time.perf_counter()
    for i in range(200):
        value,event=fill(seed(),'bench-'+str(i),'SELL','1','10');restored_value=restore(snapshot(value),SOURCE)
        need(value==restored_value,'BENCHMARK_ROUNDTRIP')
    benchmark_seconds=time.perf_counter()-benchmark
    (output/'account-cases.json').write_text(json.dumps(dict(cases=cases,refusals=negative),indent=2)+'\n')
    (output/'account-events.jsonl').write_text(''.join(json.dumps(e,sort_keys=True)+'\n' for e in events))
    return dict(status='MATCHED_HOLDING_COMPONENT_CASES_PASSED',cases=len(cases),negative_cases=len(negative),
        disabled_layer_equality=True,actual_frozen_canonical_helpers_used=True,actual_guard_removal_falsifier=True,
        serialized_suffix_and_prefix=True,synthetic_trade_restore_benchmark_operations=200,
        synthetic_trade_restore_benchmark_seconds=benchmark_seconds,component_processing_seconds=time.perf_counter()-started,
        full_history_performance_qualified=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_QUALIFICATION')
    from research.pooled_vacancy_funding.backtest import Account as CanonicalAccount
    from stock_strategy_shared.wealth_core import engine,shares,state as core_state,ledger,terminal,v5
    with gzip_open(a.root/'checkpoint.json.gz') as cp:
        source_map=dict(cp['base']['sources'])
    del cp
    bindings={}
    for module in (engine,shares,core_state,ledger,terminal,v5,inspect.getmodule(CanonicalAccount),inspect.getmodule(CanonicalAccount.advance)):
        path=Path(module.__file__);need(str(path).startswith('/fixed/'),'CANONICAL_MODULE_LOCATION')
        relative=str(path).removeprefix('/fixed/');actual=hashlib.sha256(path.read_bytes()).hexdigest()
        need(source_map[relative]==actual,'CANONICAL_SOURCE_HASH');bindings[relative]=actual
    output=a.output;output.mkdir(exist_ok=False);started=time.perf_counter()
    canonical=dict(config=v5.research_config('wealth-core-v5-zero-share-fixed-2008-v1'),entry_cost=engine.entry_cost,
        exit_proceeds=engine.exit_proceeds,split_shares=shares.split_shares,ledger=ledger.Ledger,
        portfolio=core_state.PortfolioState,episode=core_state.HoldingEpisode,terms=terminal.TerminalTerms,
        terminal_kind=terminal.TerminalKind,apply_terminal=terminal.apply_terminal)
    counter=scalar_counterexample(CanonicalAccount);(output/'model-counterexample.json').write_text(json.dumps(counter,indent=2)+'\n')
    components=qualify(output,canonical)
    identity=bind_book(a.root,output/'identity')
    need(identity['duplicate_security_closes']==8 and identity['records']==4765,'ACTUAL_DUPLICATE_EPISODE_COVERAGE')
    result=dict(schema='research.holding-qualification-result/1',status='HOLDING_QUALIFICATION_PASSED',
        old_scalar_equivalence='MODEL_CHANGED_PROVEN',matched_neutral_model='PERSISTENT_HOLDING_H0',
        paired_scripted_model='SAME_ACCOUNT_HQ_SCRIPTED_EVENTS_ONLY',components=components,identity=identity,
        canonical_source_bindings=bindings,total_processing_seconds=time.perf_counter()-started,
        P2_policy_executed=False,full_history_funded_accounts_executed=0,optimization_executed=False,
        production_contacted=False,performance_ready=False,
        remaining_limits=['Full-horizon holding baseline not computed.','Actual P2 rules not executed.',
            'Stock conversions/spinoffs/fractional CIL not implemented in funded prototype.',
            'Broker execution and historical per-stock raw mark coverage not qualified.'])
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print('HOLDING_QUALIFICATION_FINISHED')

def gzip_open(path):
    """Small context wrapper keeps the actual gzip parser explicit."""
    import gzip
    from contextlib import contextmanager
    @contextmanager
    def opened():
        with gzip.open(path,'rt') as stream:yield json.load(stream)
    return opened()

if __name__=='__main__':main()
