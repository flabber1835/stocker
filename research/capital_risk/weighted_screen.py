"""One hosted B/R account comparison over the unchanged authenticated Core trace."""
import argparse,gzip,hashlib,json,math,re,shutil
from pathlib import Path
from copy import deepcopy
from decimal import Decimal as D,localcontext
from datetime import date

from policy import PROTOCOL
from trace_screen import advance_account,validate_baseline,encoded,digest
from weighted_features import build
from weighted_policy import RiskState,advance,need,number
from weighted_account_adapter import account_step

START,END,COUNT='2008-02-22','2026-07-31',4639

def validate_plan(plan):
    need(plan['schema']=='research.capital-weighted-exposure-protocol/1'
        and plan['id']=='capital-weighted-deterioration-001' and plan['arms']==['B','R']
        and plan['original_protocol_sha256']==PROTOCOL and plan['start']==START and plan['end']==END
        and plan['formation_records']==126 and plan['measured_closes']==COUNT and plan['capital']=='50000',
        'REFUSED_R_PROTOCOL_SCOPE')
    for key,value in dict(own_drawdown_maximum='-0.10',recent_return_maximum='-0.03',
            deterioration_predicate='BOTH_OR_EXPLICIT_UNKNOWN',duplicate_security_rule='ANY_OWNED_EPISODE_COUNT_CAPITAL_ONCE',
            entry_score='0.30',release_score='0.15',release_consecutive_closes=3,reduced_ceiling='0.55',
            worker_deadline_seconds=600,job_timeout_minutes=15,parameter_sweep=False,core_financial_changes=False,
            automatic_followup=False,production_contacted=False,plaintext_financial_publication=False,
            runtime='GITHUB_HOSTED_OFFLINE_ONLY',shortlist='CAGR_NOT_LOWER_AND_MAXDD_NOT_DEEPER_AT_LEAST_ONE_STRICT').items():
        need(plan[key]==value and type(plan[key])is type(value),'REFUSED_R_FROZEN_PARAMETER_'+key)
    need(plan['diagnostic_windows']==[['2008-01-01','2009-12-31'],['2009-01-01','2010-12-31'],
        ['2020-01-01','2022-12-31'],['2025-01-01',END]],'REFUSED_R_WINDOWS')

def metrics(samples,start,end):
    indices=[i for i,r in enumerate(samples) if start<=r['session']<=end]
    need(bool(indices),'REFUSED_R_EMPTY_WINDOW');lo,hi=indices[0],indices[-1];anchor=max(0,lo-1);series={}
    with localcontext() as c:
        c.prec=50
        for arm in ('B','R','SPY'):
            initial=D(samples[anchor][arm]);peak=initial;dd=D(0)
            for r in samples[lo:hi+1]:
                v=D(r[arm]);need(v>0,'REFUSED_R_NONPOSITIVE_NAV');peak=max(peak,v);dd=min(dd,v/peak-1)
            final=D(samples[hi][arm]);multiple=final/initial
            elapsed=(date.fromisoformat(samples[hi]['session'])-date.fromisoformat(samples[anchor]['session'])).days
            series[arm]=dict(initial_nav=str(initial),nav=str(final),multiple=str(multiple),total_return=str(multiple-1),
                cagr=math.expm1(float(multiple.ln()*D('365.2425')/elapsed)) if elapsed else None,maximum_drawdown=str(dd))
    return dict(first_close=samples[lo]['session'],last_close=samples[hi]['session'],anchor_session=samples[anchor]['session'],
        closes=len(indices),annualization='DIAGNOSTIC_KNOWN_HISTORY',series=series)

class Screen:
    def __init__(self,contract):
        self.contract=contract;self.risk=RiskState();self.accounts=None;self.completed=0;self.chain='0'*64

    def checkpoint(self):
        value=json.loads(encoded(dict(schema='research.capital-weighted-account-state/1',contract=self.contract,
            risk=self.risk.to_dict(),accounts=self.accounts,completed=self.completed,chain=self.chain)))
        return {**value,'checkpoint_sha256':digest(value)}

    @classmethod
    def restore(cls,saved,contract):
        need(set(saved)=={'schema','contract','risk','accounts','completed','chain','checkpoint_sha256'}
            and saved['checkpoint_sha256']==digest({k:v for k,v in saved.items() if k!='checkpoint_sha256'})
            and saved['schema']=='research.capital-weighted-account-state/1' and saved['contract']==contract
            and type(saved['completed'])is int and 0<=saved['completed']<=COUNT
            and isinstance(saved['chain'],str) and re.fullmatch('[0-9a-f]{64}',saved['chain']),
            'REFUSED_R_ACCOUNT_RESTORE')
        result=cls(contract);result.risk=RiskState.restore(saved['risk']);result.accounts=deepcopy(saved['accounts'])
        result.completed=saved['completed'];result.chain=saved['chain']
        need((result.accounts is None)==(result.completed==0),'REFUSED_R_ACCOUNT_CURSOR')
        if result.accounts is not None:
            need(set(result.accounts)=={'B','R'} and all(e['last_session']==result.risk.last_session and D(e['strategy_nav'])>0
                for e in result.accounts.values()),'REFUSED_R_ACCOUNT_CURSOR')
        return result

    def consume(self,row,feature,canonical):
        day=row['session'];need(feature['session']==day and row['decision']['session']==day,'REFUSED_R_FEATURE_CURSOR')
        for kind in ('state','input','chain'):
            need(feature['source_'+kind+'_sha256']==row[kind+'_sha256'],'REFUSED_R_FEATURE_SOURCE_'+kind)
        baseline=row['decision']['target_core_exposure']
        self.risk,target=advance(self.risk,session=day,previous_session=self.risk.last_session,
            score=feature['score'],baseline_target=baseline)
        need(RiskState.restore(self.risk.to_dict())==self.risk,'REFUSED_R_RISK_ROUNDTRIP')
        if row['phase']=='FORMATION':
            need(self.accounts is None,'REFUSED_R_LATE_FORMATION');return None
        need(row['phase']=='MEASURED','REFUSED_R_PHASE');old=deepcopy(self.accounts)
        if self.completed==0:
            need(day==START and D(row['economics']['strategy_nav'])==50000 and row['economics']['held_allocation'] is None
                and D(row['economics']['net_factor'])==1 and D(str(baseline))==0 and target==0,'REFUSED_R_DAY_ZERO')
            self.accounts={a:deepcopy(row['economics']) for a in ('B','R')};self.accounts['R']['pending_allocation']=str(target)
        elif self.completed==1:
            need(all(D(e['pending_allocation'])==0 and e['held_allocation'] is None for e in old.values())
                and row['economics']['initial_deployment'] and D(row['economics']['held_allocation'])==0,
                'REFUSED_R_FORMED_STARTUP')
            cash=D(row['economics']['strategy_prices']['bil_close_adjusted'])/D(row['economics']['strategy_prices']['bil_open_adjusted'])-1
            net=1+cash-D('.001')
            need(D(row['economics']['net_factor'])==net and D(row['economics']['strategy_nav'])==D('50000')*net,'REFUSED_R_STARTUP_ACCOUNTING')
            self.accounts={a:deepcopy(row['economics']) for a in ('B','R')};self.accounts['R']['pending_allocation']=str(target)
        else:
            self.accounts=dict(B=account_step(old['B'],row,baseline,canonical),
                R=account_step(old['R'],row,float(target),canonical))
        need(self.accounts['B']==row['economics'],'REFUSED_R_BASELINE_FIELD_EQUALITY')
        self.completed+=1
        record=dict(session=day,B=self.accounts['B']['strategy_nav'],R=self.accounts['R']['strategy_nav'],SPY=row['comparison_navs']['spy'],
            held_B=self.accounts['B']['held_allocation'],held_R=self.accounts['R']['held_allocation'],
            pending_B=self.accounts['B']['pending_allocation'],pending_R=self.accounts['R']['pending_allocation'],
            risk=self.risk.to_dict(),score=feature['score'],unknown_score=feature['unknown_score'],feature_sha256=digest(feature),
            B_economics=self.accounts['B'],R_economics=self.accounts['R'],baseline_state_sha256=row['state_sha256'],
            baseline_input_sha256=row['input_sha256'],baseline_chain_sha256=row['chain_sha256'])
        self.chain=digest(dict(previous=self.chain,record=record));return {**record,'screen_chain_sha256':self.chain}

def run(root,archive,output,protocol,predecessor):
    from sentinel.feed.calendar import sessions_in_range
    from research.pooled_vacancy_funding.backtest import Account
    plan=json.loads(protocol.read_bytes());validate_plan(plan);contract=hashlib.sha256(protocol.read_bytes()).hexdigest()
    parent=validate_baseline(root);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    with gzip.open(root/'checkpoint.json.gz','rt') as f:checkpoint=json.load(f)
    from seal import sha256_file
    need(sha256_file(archive)==checkpoint['base']['archive_sha256'],'REFUSED_R_RAW_ARCHIVE')
    rows=[]
    for name,axis in [('formation',sessions_in_range('2007-08-22','2008-02-21')),('daily',sessions_in_range(START,END))]:
        chunk=[json.loads(x) for x in (root/(name+'.jsonl')).read_bytes().splitlines()]
        need([r['session'] for r in chunk]==axis,'REFUSED_R_BASELINE_AXIS');rows+=chunk
    output.mkdir(exist_ok=False)
    descriptor=json.loads(Path('/driver/weighted-predecessor.json').read_bytes())
    need(descriptor['contract_sha256']==contract and sha256_file(predecessor/'screen/features.jsonl')==descriptor['features_sha256'],
        'REFUSED_R_RETAINED_FEATURE_BYTES')
    shutil.copyfile(predecessor/'screen/features.jsonl',output/'features.jsonl')
    features=[json.loads(x) for x in (output/'features.jsonl').read_bytes().splitlines()]
    need(len(features)==4765 and [f['session'] for f in features]==[r['session'] for r in rows],'REFUSED_R_RETAINED_FEATURE_AXIS')
    feature_proof=dict(status='EXACT_AUTHENTICATED_PREDECESSOR_FEATURES_REUSED',observations=4765,
        original_run_id=descriptor['run_id'],features_sha256=descriptor['features_sha256'],no_core_transition=True,
        unknown_feature_sessions=sum(number(f['unknown_score'])>0 for f in features),
        duplicate_security_sessions=sum(f['duplicate_security_ids']>0 for f in features),
        maximum_equity_difference=str(max(abs(number(f['equity_difference'])) for f in features)))
    from weighted_resume import resume_prefix
    engine,samples,prefix,saved=resume_prefix(predecessor,contract,rows,descriptor,screen_type=Screen)
    canonical=Account('50000',formed=False);split=None
    boundary=dict(schema='research.capital-weighted-source-successor/1',predecessor=descriptor,
        unchanged_state_checkpoint=saved,financial_state_unchanged=True,numerical_protocol_unchanged=True,
        change='Carry prior research_entry_mode and measurement_anchor_session after unchanged canonical account calculation',
        next_uncommitted_session=descriptor['next_session'])
    (output/'source-successor.json').write_text(json.dumps(boundary,indent=2)+'\n')
    with (output/'daily.jsonl').open('xb') as stream:
        stream.write(prefix)
        for row,f in zip(rows,features):
            if row['session']<=descriptor['last_session']:continue
            record=engine.consume(row,f,canonical)
            if record is not None:
                stream.write(encoded(record)+b'\n');samples.append(record)
                if row['session']=='2020-12-31':split=engine.checkpoint()
    need(engine.completed==COUNT and split is not None,'REFUSED_R_SCREEN_INCOMPLETE')
    need((output/'daily.jsonl').read_bytes()[:len(prefix)]==prefix,'REFUSED_R_PREFIX_MUTATED')
    restored=Screen.restore(split,contract)
    for row,f in zip(rows,features):
        if row['session']>restored.risk.last_session:restored.consume(row,f,canonical)
    need(restored.checkpoint()==engine.checkpoint(),'REFUSED_R_CONTINUATION')
    need({p.name:sha256_file(p) for p in root.iterdir() if p.is_file()}==before,'REFUSED_R_CORE_TRACE_MUTATION')
    full=metrics(samples,START,END);b,r=full['series']['B'],full['series']['R']
    prioritize=r['cagr']>=b['cagr'] and D(r['maximum_drawdown'])>=D(b['maximum_drawdown']) and (
        r['cagr']>b['cagr'] or D(r['maximum_drawdown'])>D(b['maximum_drawdown']))
    turnover={};switches={}
    for arm in ('B','R'):
        turnover[arm]=str(sum((D(x[arm+'_economics']['turnover']) for x in samples),D(0)))
        switches[arm]=sum(x['held_'+arm]!=samples[i-1]['held_'+arm] for i,x in enumerate(samples) if i>1)
    result=dict(schema='research.capital-weighted-screen/1',status='WEIGHTED_SCREEN_PASSED',contract_sha256=contract,
        original_protocol_sha256=PROTOCOL,immutable_baseline_checkpoint=parent,formation_records=126,measured_closes=COUNT,
        baseline_every_daily_field_matched=True,independent_accounting=True,serialized_continuation_matched=True,
        core_trace_unchanged=True,production_contacted=False,feature_proof=feature_proof,
        full=full,annual={str(y):metrics(samples,f'{y}-01-01',f'{y}-12-31') for y in range(2008,2027)},
        diagnostic_windows=[metrics(samples,*w) for w in plan['diagnostic_windows']],
        turnover=turnover,allocation_switches=switches,
        extra_reduced_open_sessions=sum(number(x['held_R'] or 0)<number(x['held_B'] or 0) for x in samples),
        risk_reduced_decision_closes=sum(x['risk']['reduced'] for x in samples),R_prioritized=prioritize,
        final_checkpoint=engine.checkpoint(),continuation_checkpoint=split,
        exact_suffix=True,source_successor=boundary,
        limitations=['One fixed known-history hypothesis; no unseen OOS claim.','Original frozen provider/classification/action conventions.',
            'Scalar next-open account model, not broker fill certification.','No Core rule, fresh-origin, capital, cost or execution robustness tested.'])
    (output/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print('WEIGHTED_SCREEN_PASSED')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('root','archive','output','protocol','predecessor'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();run(a.root,a.archive,a.output,a.protocol,a.predecessor)
