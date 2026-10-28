"""One canonical exposure-only comparison; hosted only, unchanged Core trace."""
import argparse,gzip,hashlib,json,math,os,time,re
from pathlib import Path
from copy import deepcopy
from decimal import Decimal as D,localcontext
from datetime import date
from entry_gate_policy import load_variants,Policies
from trace_screen import validate_baseline,encoded,digest,require
from weighted_account_adapter import account_step
from policy import PROTOCOL

HERE=Path(__file__).resolve().parent
START,END,COUNT='2008-02-22','2026-07-31',4639
PLAN_DIGEST='902f58bf7c4eea3eaffe65761f0c7032332dde507482d175da88a0086b275694'


def validate_plan(plan):
    expected=json.loads((HERE/'entry-gate-protocol.json').read_bytes())
    require(digest(plan)==PLAN_DIGEST and plan==expected and plan['id']=='owned55-entry-gate-001'
        and plan['original_damage']=='0.88' and plan['candidate_damage']=='0.75'
        and plan['arms']==['B','E75'] and plan['worker_deadline_seconds']==420
        and plan['job_timeout_minutes']==20 and not plan['core_financial_changes']
        and not plan['correlation_changes'] and not plan['parameter_sweep']
        and not plan['automatic_extension'] and not plan['production_contacted'],
        'REFUSED_ENTRY_PROTOCOL')


def initial_account(previous,row,target,completed):
    e=row['economics']
    if completed==0:
        require(row['session']==START and D(e['strategy_nav'])==50000 and
            e['held_allocation'] is None and D(e['net_factor'])==1 and
            D(e['pending_allocation'])==D(str(target))==0,'REFUSED_ENTRY_ANCHOR')
    else:
        require(previous['held_allocation'] is None and D(previous['pending_allocation'])==0
            and e['initial_deployment'] and D(e['held_allocation'])==0,'REFUSED_ENTRY_STARTUP_SCOPE')
        p=e['strategy_prices'];gross=D(p['bil_close_adjusted'])/D(p['bil_open_adjusted'])
        require(D(e['net_factor'])==gross-D('.001') and
            D(e['strategy_nav'])==D('50000')*(gross-D('.001')),'REFUSED_ENTRY_STARTUP_ACCOUNTING')
    return {**deepcopy(e),'pending_allocation':format(D(str(target)).normalize(),'f')}


def next_account(previous,row,target,completed,canonical):
    if completed<2:return initial_account(previous,row,target,completed)
    return account_step(previous,row,target,canonical)


def admit_completion_lineage(root,cp):
    proof=json.loads((root/'fixed-review.json').read_bytes())
    require(proof['status']=='INDEPENDENT_COMPLETION_REVIEW_PASSED'
        and proof['arm']=='fixed' and proof['canonical_roundtrip']
        and proof['all_historical_prefixes_verified'] and proof['full_chain_verified']
        and proof['final_file_sha256']==hashlib.sha256((root/'checkpoint.json.gz').read_bytes()).hexdigest()
        and proof['final_outer']==cp['sha256'] and proof['final_inner']==cp['run']['checkpoint_sha256']
        and proof['journal_commitments']==cp['journals']
        and set(cp['journals'])=={'formation','daily','monthly','watch'},
        'REFUSED_ENTRY_ORIGINAL_COMPLETION_BINDING')
    return dict(exact_original_checkpoint_and_all_four_commitments_bound=True,
        raw_streams_directly_verified=['formation','daily','monthly'],
        watch_proof='EXACT_AUTHENTICATED_ORIGINAL_COMPLETION_REVIEW_REUSED_NO_RAW_WATCH_IN_TRANSFER',
        completion_review_sha256=hashlib.sha256((root/'fixed-review.json').read_bytes()).hexdigest())


def metric(samples,start,end,*,anchor_at_first=False):
    selected=[i for i,r in enumerate(samples) if start<=r['session']<=end]
    require(bool(selected),'REFUSED_ENTRY_METRIC_AXIS');lo,hi=selected[0],selected[-1];anchor=lo if anchor_at_first else max(0,lo-1)
    series={}
    with localcontext() as ctx:
        ctx.prec=50
        for arm in ('B','E75','SPY'):
            initial=D(samples[anchor][arm]);peak=initial;worst=D(0);pi=anchor;peakday=samples[anchor]['session'];trough=peakday
            for i in range(lo,hi+1):
                value=D(samples[i][arm]);require(value>0,'REFUSED_ENTRY_NONPOSITIVE_NAV')
                if value>peak:peak=value;pi=i
                dd=value/peak-1
                if dd<worst:worst=dd;peakday=samples[pi]['session'];trough=samples[i]['session']
            final=D(samples[hi][arm]);multiple=final/initial
            days=(date.fromisoformat(samples[hi]['session'])-date.fromisoformat(samples[anchor]['session'])).days
            series[arm]=dict(initial_nav=str(initial),nav=str(final),multiple=str(multiple),
                total_return=str(multiple-1),cagr=math.expm1(float(multiple.ln()*D('365.2425')/days)) if days else None,
                maximum_drawdown=str(worst),peak=peakday,trough=trough)
    return dict(first_close=samples[lo]['session'],last_close=samples[hi]['session'],
        anchor_session=samples[anchor]['session'],closes=len(selected),series=series,
        anchor_convention='FIRST_INCLUDED_CLOSE' if anchor_at_first else 'PRECEDING_CLOSE_WHEN_AVAILABLE')


class Screen:
    def __init__(self,contract,baseline,candidate):
        self.contract=contract;self.policies=Policies(baseline,candidate)
        self.accounts=None;self.completed=0;self.chain='0'*64

    def checkpoint(self):
        value=dict(schema='research.owned55-entry-state/1',contract=self.contract,policies=self.policies.snapshot(),
            accounts=self.accounts,completed=self.completed,chain=self.chain)
        value=json.loads(encoded(value))
        return {**value,'checkpoint_sha256':digest(value)}

    @classmethod
    def restore(cls,value,contract,baseline,candidate):
        require(set(value)=={'schema','contract','policies','accounts','completed','chain','checkpoint_sha256'}
            and value['schema']=='research.owned55-entry-state/1' and value['contract']==contract
            and value['checkpoint_sha256']==digest({k:v for k,v in value.items() if k!='checkpoint_sha256'})
            and type(value['completed']) is int and 0<=value['completed']<=COUNT
            and re.fullmatch('[0-9a-f]{64}',value['chain']),'REFUSED_ENTRY_STATE_IDENTITY')
        result=cls(contract,baseline,candidate);result.policies.restore(deepcopy(value['policies']))
        result.accounts=deepcopy(value['accounts']);result.completed=value['completed'];result.chain=value['chain']
        require((result.accounts is None)==(result.completed==0),'REFUSED_ENTRY_STATE_CURSOR')
        if result.accounts is not None:
            require(set(result.accounts)=={'B','E75'} and all(v['last_session']==result.policies.last_session
                and D(v['strategy_nav'])>0 for v in result.accounts.values()),'REFUSED_ENTRY_ACCOUNT_CURSOR')
        require(result.checkpoint()==value,'REFUSED_ENTRY_STATE_ROUNDTRIP')
        return result

    def consume(self,row,canonical):
        audit=self.policies.step(row);targets=[a['target'] for a in audit]
        if row['phase']=='FORMATION':
            require(self.accounts is None,'REFUSED_ENTRY_LATE_FORMATION');return None
        require(row['phase']=='MEASURED','REFUSED_ENTRY_PHASE')
        before=self.accounts
        self.accounts={arm:next_account(None if before is None else before[arm],row,target,self.completed,canonical)
            for arm,target in zip(('B','E75'),targets)}
        require(self.accounts['B']==row['economics'],'REFUSED_ENTRY_BASELINE_ALL_FIELDS')
        self.completed+=1
        record=dict(session=row['session'],B=self.accounts['B']['strategy_nav'],E75=self.accounts['E75']['strategy_nav'],
            SPY=row['comparison_navs']['spy'],B_economics=self.accounts['B'],E75_economics=self.accounts['E75'],
            control=audit[0],candidate=audit[1],baseline_state_sha256=row['state_sha256'],
            baseline_input_sha256=row['input_sha256'],baseline_chain_sha256=row['chain_sha256'])
        self.chain=digest(dict(previous=self.chain,record=record))
        return {**record,'screen_chain_sha256':self.chain}


def run(root,output,protocol):
    require(os.environ.get('OWNED55_ENTRY_HOSTED')=='1','REFUSED_ENTRY_LOCAL_FINANCIAL_EXECUTION')
    from sentinel.feed.calendar import sessions_in_range
    from research.pooled_vacancy_funding.backtest import Account
    plan=json.loads(protocol.read_bytes());validate_plan(plan);contract=hashlib.sha256(protocol.read_bytes()).hexdigest()
    parent=validate_baseline(root)
    with gzip.open(root/'checkpoint.json.gz','rt') as stream:cp=json.load(stream)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    completion_proof=admit_completion_lineage(root,cp)
    baseline,candidate,source=load_variants(cp['base']['sources']['sentinel/controller/owned_impairment.py'])
    output.mkdir(exist_ok=False)
    (output/'baseline-admission.json').write_bytes(encoded(completion_proof)+b'\n')
    (output/'policy-source-proof.json').write_bytes(encoded(source)+b'\n')
    rows=[]
    for name,axis in [('formation',sessions_in_range('2007-08-22','2008-02-21')),('daily',sessions_in_range(START,END))]:
        chunk=[json.loads(line) for line in (root/(name+'.jsonl')).open('rb')]
        require([r['session'] for r in chunk]==axis,'REFUSED_ENTRY_COMPLETE_AXIS');rows.extend(chunk)
    require(len(rows)==4765,'REFUSED_ENTRY_RECORDS')
    canonical=Account('50000',formed=False);policies=Policies(baseline,candidate)
    previous=None;completed=0;coverage=[];decisions=[];started=time.monotonic()
    # Gate: complete ORIGINAL account/state equivalence before ANY candidate NAV.
    with (output/'decisions.jsonl').open('xb') as stream:
        for row in rows:
            audits=policies.step(row);record=dict(session=row['session'],phase=row['phase'],control=audits[0],candidate=audits[1],
                policies=policies.snapshot(),baseline_state_sha256=row['state_sha256'],baseline_input_sha256=row['input_sha256'],
                baseline_chain_sha256=row['chain_sha256'])
            decisions.append(record);stream.write(encoded(record)+b'\n')
            if row['phase']=='FORMATION':continue
            previous=next_account(previous,row,audits[0]['target'],completed,canonical)
            require(previous==row['economics'],'REFUSED_ENTRY_ADMISSION_BASELINE_FIELD')
            completed+=1
            if audits[1]['target']<audits[0]['target']:coverage.append(row['session'])
        stream.flush();os.fsync(stream.fileno())
    elapsed=time.monotonic()-started
    require(completed==COUNT and elapsed<=plan['baseline_readiness_seconds'],'REFUSED_ENTRY_BASELINE_RUNTIME')
    window_coverage={lo+'..'+hi:sum(lo<=day<=hi for day in coverage) for lo,hi in plan['coverage_windows']}
    gate=dict(status='BASELINE_AND_TREATMENT_ADMITTED' if any(window_coverage.values()) else 'NO_TREATMENT',
        baseline_daily_fields_matched=COUNT,formation_policy_observations_matched=126,
        total_lower_target_closes=len(coverage),coverage_windows=window_coverage,baseline_processing_seconds=elapsed,
        candidate_account_returns_calculated=False)
    (output/'admission.json').write_bytes(encoded(gate)+b'\n')
    if not any(window_coverage.values()):
        (output/'summary.json').write_bytes(encoded(dict(status='ENTRY_NO_TREATMENT',contract_sha256=contract,
            formation_records=126,measured_closes=COUNT,admission=gate,production_contacted=False))+b'\n')
        return
    engine=Screen(contract,baseline,candidate);samples=[];split=None
    with (output/'daily.jsonl').open('xb') as stream:
        for row,decision in zip(rows,decisions):
            record=engine.consume(row,canonical)
            require(engine.policies.snapshot()==decision['policies'],'REFUSED_ENTRY_PREDECLARED_POLICY_PATH')
            if record:
                samples.append(record);stream.write(encoded(record)+b'\n')
                if row['session']==plan['restart_boundary']:split=engine.checkpoint()
        stream.flush();os.fsync(stream.fileno())
    require(engine.completed==COUNT and split is not None,'REFUSED_ENTRY_COMPLETE')
    restored=Screen.restore(split,contract,baseline,candidate)
    for row in rows:
        if row['session']>split['policies']['last_session']:restored.consume(row,canonical)
    require(restored.checkpoint()==engine.checkpoint(),'REFUSED_ENTRY_SERIALIZED_CONTINUATION')
    require({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}==before,'REFUSED_ENTRY_BASELINE_MUTATION')
    full=metric(samples,START,END);b,e=full['series']['B'],full['series']['E75']
    result=dict(schema='research.owned55-entry-screen/1',status='ENTRY_SCREEN_PASSED',contract_sha256=contract,
        original_protocol_sha256=PROTOCOL,immutable_baseline_checkpoint=parent,formation_records=126,measured_closes=COUNT,
        baseline_every_daily_field_matched=True,independent_accounting=True,canonical_owned55_state_matched=True,
        serialized_continuation_matched=True,core_trace_unchanged=True,policy_source_proof=source,admission=gate,
        full=full,annual={str(y):metric(samples,f'{y}-01-01',f'{y}-12-31') for y in range(2008,2027)},
        diagnostic_windows=[metric(samples,*w,anchor_at_first=True) for w in plan['diagnostic_windows']],
        turnover={arm:str(sum((D(r[arm+'_economics']['turnover']) for r in samples),D(0))) for arm in ('B','E75')},
        allocation_switches={arm:sum(r[arm+'_economics']['held_allocation']!=samples[i-1][arm+'_economics']['held_allocation']
            for i,r in enumerate(samples) if i>1) for arm in ('B','E75')},
        E75_prioritized=e['cagr']>b['cagr'] and D(e['maximum_drawdown'])>D(b['maximum_drawdown']),
        final_checkpoint=engine.checkpoint(),continuation_checkpoint=split,production_contacted=False,
        limitations=['One fixed known-history sensitivity; no unseen OOS.','Frozen provider/classification/action/origin limitations.',
            'Scalar sleeve economics, not broker execution qualification.','No Core trade, selection, stop or correlation change.'])
    (output/'summary.json').write_bytes(encoded(result)+b'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('root','output','protocol'):p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args();run(args.root,args.output,args.protocol)
    print('ENTRY_SCREEN_FINISHED')
