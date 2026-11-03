"""Read-only B/G exposure screen on an authenticated, already audited Core trace.

Invoked only in the retained offline image on a hosted VM. No Core transition,
holding edit, broker access or replacement financial book is implemented here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal as D, localcontext
import hashlib
import json
import math
from pathlib import Path
from datetime import date
from types import SimpleNamespace

from policy import Governor, advance_governor, PROTOCOL

START, END = '2008-02-22', '2026-07-31'
COUNT = 4639


def require(ok, code):
    if not ok:
        raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def independent_factor(prior, row, actual):
    """Independent accounting equation, never an alternative Core book."""
    old, new = D(prior['held_allocation']), D(prior['pending_allocation'])
    require(D(0) <= old <= 1 and D(0) <= new <= 1, 'REFUSED_EXPOSURE')
    e = row['economics']
    op, cl, pc = map(D, (e['parent_core_open_equity'], e['parent_core_close_equity'],
                        prior['parent_core_close_equity']))
    p = e['strategy_prices']
    bo, bc, bp = map(D, (p['bil_open_adjusted'], p['bil_close_adjusted'],
                        p['bil_previous_close_adjusted']))
    if new == old:
        gross = new * cl / pc + (1-new) * bc / bp
    else:
        gross = (1 + old*(op/pc-1) + (1-old)*(bo/bp-1))
        gross *= 1 + new*(cl/op-1) + (1-new)*(bc/bo-1)
    cost = 1 - D('.001')*abs(new-old)
    net = cost*gross
    require(D(actual['gross_factor']) == gross and D(actual['net_factor']) == net
            and D(actual['transaction_cost_factor']) == cost
            and D(actual['turnover']) == abs(new-old)
            and D(actual['strategy_nav']) == D(prior['strategy_nav'])*net,
            'REFUSED_INDEPENDENT_ACCOUNTING')


def advance_account(prior, row, target, canonical):
    # The immutable valuation adapter supplies only fields the unchanged scalar
    # account operation reads. It is never passed to the Core engine or saved as
    # a Core checkpoint. Original evidence and input state identities are kept.
    before = digest(row)
    state = SimpleNamespace(last_processed_session=row['session'],
        shadow_nav_history=[row['evidence']['observation']['shadow_nav']],
        last_evidence=row['evidence'],
        last_decision={**row['decision'], 'target_core_exposure': target})
    result = canonical.advance(previous=prior, state=state,
        strategy_prices=row['economics']['strategy_prices'])
    independent_factor(prior, row, result)
    require(digest(row) == before, 'REFUSED_CORE_TRACE_MUTATION')
    return result


def metrics(samples, start, end):
    wanted = [i for i,r in enumerate(samples) if start <= r['session'] <= end]
    require(bool(wanted), 'REFUSED_EMPTY_METRIC_WINDOW')
    left, right = wanted[0], wanted[-1]
    anchor = max(0, left-1)
    result = {}
    with localcontext() as ctx:
        ctx.prec = 50
        for arm in ('B','G','SPY'):
            initial = D(samples[anchor][arm]); peak = initial; dd = D(0)
            for r in samples[left:right+1]:
                nav = D(r[arm]); peak = max(peak,nav); dd = min(dd,nav/peak-1)
            final = D(samples[right][arm]); multiple = final/initial
            elapsed = (date.fromisoformat(samples[right]['session'])-
                       date.fromisoformat(samples[anchor]['session'])).days
            cagr = math.expm1(float(multiple.ln()*D('365.2425')/elapsed)) if elapsed else None
            result[arm] = dict(initial_nav=str(initial), nav=str(final), multiple=str(multiple),
                total_return=str(multiple-1), cagr=cagr, maximum_drawdown=str(dd))
    return dict(first_close=samples[left]['session'], last_close=samples[right]['session'],
        anchor_session=samples[anchor]['session'], closes=len(wanted),
        annualization='DIAGNOSTIC_KNOWN_HISTORY',series=result)


class Screen:
    def __init__(self, contract):
        self.contract = contract; self.gov = Governor(); self.accounts = None
        self.completed = 0; self.chain = '0'*64

    def checkpoint(self):
        return json.loads(encoded(dict(schema='research.capital-risk-trace-state/1',
            protocol_sha256=PROTOCOL, screen_sha256=self.contract,
            governor=self.gov.to_dict(), accounts=self.accounts,
            completed=self.completed, chain=self.chain)))

    @classmethod
    def restore(cls, saved, contract):
        require(set(saved)=={'schema','protocol_sha256','screen_sha256','governor',
                            'accounts','completed','chain'} and
            saved['schema']=='research.capital-risk-trace-state/1' and
            saved['protocol_sha256']==PROTOCOL and saved['screen_sha256']==contract and
            type(saved['completed']) is int and 0<=saved['completed']<=COUNT and
            isinstance(saved['chain'],str) and len(saved['chain'])==64,
            'REFUSED_SCREEN_RESTORE_IDENTITY')
        result=cls(contract); result.gov=Governor.from_dict(saved['governor'])
        result.accounts=deepcopy(saved['accounts']);result.completed=saved['completed']
        result.chain=saved['chain']
        require((result.accounts is None)==(result.completed==0), 'REFUSED_ACCOUNT_CURSOR')
        if result.accounts is not None:
            require(set(result.accounts)=={'B','G'} and all(
                e['last_session']==result.gov.last_session and D(e['strategy_nav'])>0
                for e in result.accounts.values()), 'REFUSED_ACCOUNT_CURSOR')
        return result

    def consume(self, row, canonical):
        obs = row['evidence']['observation']; day=row['session']
        require(obs['session']==day and row['decision']['session']==day,
                'REFUSED_OBSERVATION_CURSOR')
        native=row['decision']['target_core_exposure']
        self.gov, target=advance_governor(self.gov,current_session=day,
            previous_session=self.gov.last_session,drawdown=obs['shadow_drawdown'],
            core_r20=obs['shadow_r20'],damage=obs['damaged_breadth'],
            green=obs['green_breadth'],native_target=native)
        require(Governor.from_dict(self.gov.to_dict())==self.gov, 'REFUSED_GOVERNOR_ROUNDTRIP')
        if row['phase']=='FORMATION':
            require(self.accounts is None, 'REFUSED_LATE_FORMATION')
            return None
        require(row['phase']=='MEASURED','REFUSED_PHASE')
        old=deepcopy(self.accounts)
        if self.completed==0:
            require(day==START and D(row['economics']['strategy_nav'])==50000 and
                row['economics']['held_allocation'] is None and
                D(row['economics']['net_factor'])==1,'REFUSED_DAY_ZERO')
            self.accounts={arm:deepcopy(row['economics']) for arm in ('B','G')}
            self.accounts['G']['pending_allocation']=str(target)
        elif self.completed==1:
            # The original audited anchor funds zero Core on the next open. Both
            # policies must agree before the retained startup can be reused.
            require(all(D(v['pending_allocation'])==0 and v['held_allocation'] is None
                        for v in old.values()) and row['economics']['initial_deployment']
                    and D(row['economics']['held_allocation'])==0,'REFUSED_FORMED_ENTRY_SCOPE')
            cash=D(row['economics']['strategy_prices']['bil_close_adjusted'])/D(
                row['economics']['strategy_prices']['bil_open_adjusted'])-1
            net=1+cash-D('.001')
            require(D(row['economics']['net_factor'])==net and
                    D(row['economics']['strategy_nav'])==D('50000')*net,
                    'REFUSED_CASH_STARTUP_ACCOUNTING')
            self.accounts={arm:deepcopy(row['economics']) for arm in ('B','G')}
            self.accounts['G']['pending_allocation']=str(target)
        else:
            self.accounts={'B':advance_account(old['B'],row,native,canonical),
                           'G':advance_account(old['G'],row,target,canonical)}
            for k,v in self.accounts['B'].items():
                require(row['economics'].get(k)==v,'REFUSED_BASELINE_DAILY_FIELD_'+k)
        self.completed+=1
        result=dict(session=day,B=self.accounts['B']['strategy_nav'],
            G=self.accounts['G']['strategy_nav'],SPY=row['comparison_navs']['spy'],
            held_B=self.accounts['B']['held_allocation'],held_G=self.accounts['G']['held_allocation'],
            pending_B=self.accounts['B']['pending_allocation'],pending_G=self.accounts['G']['pending_allocation'],
            governor=self.gov.to_dict(),baseline_state_sha256=row['state_sha256'],
            baseline_input_sha256=row['input_sha256'],baseline_chain_sha256=row['chain_sha256'])
        self.chain=digest(dict(previous=self.chain,record=result))
        return {**result, 'screen_chain_sha256':self.chain}


def validate_baseline(root):
    from research.pooled_vacancy_funding.journal import read_checkpoint
    saved=read_checkpoint(root/'checkpoint.json.gz')
    review=json.loads((root/'fixed-review.json').read_bytes())
    require(review['status']=='INDEPENDENT_COMPLETION_REVIEW_PASSED' and
        all(review[k] for k in ('canonical_roundtrip','full_chain_verified',
            'all_historical_prefixes_verified','all_daily_factors_verified')) and
        saved['source_cursor']==END and saved['completed']==COUNT and
        review['measured_closes']==COUNT and review['formation_sessions']==126,
        'REFUSED_AUDITED_BASELINE')
    for name,count in (('formation',126),('daily',COUNT),('monthly',222)):
        path=root/(name+'.jsonl'); spec=saved['journals'][name]
        raw=path.read_bytes(); lines=raw.splitlines(keepends=True)
        require(len(lines)==count and len(raw)==spec['bytes'] and
            hashlib.sha256(raw).hexdigest()==spec['prefix_sha256'] and
            hashlib.sha256(lines[-1]).hexdigest()==spec['last_record_sha256'],
            'REFUSED_BASELINE_JOURNAL_'+name)
    return saved['sha256']


def run(root, output, protocol):
    from sentinel.feed.calendar import sessions_in_range
    from research.pooled_vacancy_funding.backtest import Account
    contract=hashlib.sha256(protocol.read_bytes()).hexdigest()
    plan=json.loads(protocol.read_bytes())
    require(plan['original_protocol_sha256']==PROTOCOL and plan['arms']==['B','G'],
            'REFUSED_SCREEN_SCOPE')
    parent=validate_baseline(root)
    canonical=Account('50000',formed=False)
    engine=Screen(contract); samples=[]; split=None
    axis=sessions_in_range(START,END)
    formation_axis=sessions_in_range('2007-08-22','2008-02-21')
    require(len(axis)==COUNT and len(formation_axis)==126,'REFUSED_SCREEN_CALENDAR')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    output.mkdir(exist_ok=False)
    with (output/'daily.jsonl').open('xb') as target:
        for name,expected in (('formation',formation_axis),('daily',axis)):
            with (root/(name+'.jsonl')).open('rb') as stream:
                for i,line in enumerate(stream):
                    row=json.loads(line)
                    require(i<len(expected) and row['session']==expected[i], 'REFUSED_SCREEN_SESSION_AXIS')
                    record=engine.consume(row,canonical)
                    if record is not None:
                        samples.append(record);target.write(encoded(record)+b'\n')
                        if row['session']=='2020-12-31': split=engine.checkpoint()
                require(i+1==len(expected),'REFUSED_SCREEN_SESSION_COUNT')
    require(engine.completed==COUNT and split is not None,'REFUSED_SCREEN_INCOMPLETE')
    resumed=Screen.restore(split,contract)
    with (root/'daily.jsonl').open('rb') as stream:
        for line in stream:
            row=json.loads(line)
            if row['session']>split['governor']['last_session']: resumed.consume(row,canonical)
    require(resumed.checkpoint()==engine.checkpoint(),'REFUSED_SCREEN_RESTART_EQUIVALENCE')
    require({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}==before,
            'REFUSED_BASELINE_MUTATED')
    full=metrics(samples,START,END)
    annual={str(y):metrics(samples,f'{y}-01-01',f'{y}-12-31') for y in range(2008,2027)}
    windows=[metrics(samples,*w) for w in plan['diagnostic_windows']]
    b,g=full['series']['B'],full['series']['G']
    dominates=g['cagr']>=b['cagr'] and D(g['maximum_drawdown'])>=D(b['maximum_drawdown']) and (
        g['cagr']>b['cagr'] or D(g['maximum_drawdown'])>D(b['maximum_drawdown']))
    result=dict(schema='research.capital-risk-trace-screen/1',status='SCREEN_PASSED',
        interpretation='INITIAL_KNOWN_HISTORY_EXPOSURE_SCREEN_ONLY',
        original_protocol_sha256=PROTOCOL,screen_sha256=contract,
        immutable_baseline_checkpoint=parent,formation_records=126,measured_closes=COUNT,
        baseline_every_daily_field_matched=True,independent_accounting=True,
        serialized_continuation_matched=True,core_trace_unchanged=True,
        production_contacted=False,core_variants_tested=False,
        full=full,annual=annual,diagnostic_windows=windows,
        G_prioritized=dominates,final_checkpoint=engine.checkpoint(),
        limitations=['Known history; no unseen/OOS claim.','Same frozen provider/classification/action conventions.',
            'Scalar next-open exposure model; not broker fill certification.',
            'No C/V/combinations, fresh-origin, capital, cost or delay robustness established.'])
    (output/'summary.json').write_bytes(json.dumps(result,indent=2,allow_nan=False).encode()+b'\n')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--protocol',type=Path,required=True)
    args=p.parse_args();run(args.root,args.output,args.protocol)
    print('SCREEN_PASSED')


if __name__=='__main__': main()
