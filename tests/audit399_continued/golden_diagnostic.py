"""Read-only execution of one immutable source version's golden scenario."""
from dataclasses import asdict
import gzip,hashlib,json,sys
from pathlib import Path
from stock_strategy_shared.wealth_core.golden import golden_scenario
from stock_strategy_shared.wealth_core.run import run_sessions
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.ledger import Ledger
import stock_strategy_shared.wealth_core.golden as golden

def main(label):
    g=golden_scenario()
    raw=json.dumps(asdict(g),sort_keys=True,separators=(',',':'),default=str)
    state=PortfolioState.fresh(g.starting_cash)
    ledger=Ledger()
    trace=[]
    def observe(res):
        trace.append({'session':res.session,'cash':state.cash,'receivables':ledger.receivable_total(),
          'resolved_equity':res.resolved_equity,'slots':{str(i):asdict(slot) for i,slot in state.slots.items()},
          'security_cooldowns':dict(state.security_cooldowns),
          'admissions':[o for o in res.decision.to_dict()['operations'] if o['operation']=='OPEN_SLOT_POSITION'] if res.decision else []})
    result=run_sessions(sessions=g.sessions,bars_by_session=g.bars_by_session,
        meta=g.meta,starting_cash=g.starting_cash,terminal_events=g.terminal_events,
        state=state,ledger=ledger,on_session=observe)
    output=result.to_dict()
    summary={'label':label,'source':golden.__file__,'result_hash':result.result_hash(),
      'state_hash':result.state.state_hash(),'ledger_hash':result.ledger.ledger_hash(),
      'cash':result.state.cash,'input_dataclass_hash':hashlib.sha256(raw.encode()).hexdigest(),
      'positions':len(result.state.episodes),'event_count':len(result.ledger.events)}
    with gzip.open('/evidence/golden-'+label+'.json.gz','wt') as f:
        json.dump({'summary':summary,'input':json.loads(raw),'result':output,'trace':trace},f,sort_keys=True,default=str)
    print(json.dumps(summary,sort_keys=True))
if __name__=='__main__':main(sys.argv[1])
