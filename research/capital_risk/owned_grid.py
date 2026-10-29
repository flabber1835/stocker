"""Declared finite class and training-only mathematics; no market acquisition."""
from datetime import date
from decimal import Decimal as D
from fractions import Fraction as Q
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import sys
import types


FIELDS=('entry_drawdown','entry_damage','entry_green','entry_sessions','recovery_damage',
    'recovery_green','recovery_core_r20_above','recovery_sessions','active_ceiling')
BASELINE=dict(entry_drawdown='-0.10',entry_damage='0.88',entry_green='0.20',entry_sessions=5,
    recovery_damage='0.63',recovery_green='0.20',recovery_core_r20_above='0',recovery_sessions=8,active_ceiling='0.55')


def need(value,reason):
    if not value:raise ValueError('REFUSED_OWNED_GRID_'+reason)


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()
def identifier(config):return 'P'+digest(config)[:20]


def profiles(protocol):
    need(protocol['schema']=='research.sharadar-owned55-grid/1' and protocol['study_id']=='sharadar-owned55-grid-001'
        and protocol['family']=='ALL_NINE_EXISTING_OWNED55_NUMERIC_FIELDS' and protocol['baseline']==BASELINE,'PROTOCOL_FAMILY')
    grid=protocol['grid'];need(set(grid)==set(FIELDS) and protocol['combinations']==26244,'GRID_FIELDS')
    result=[dict(zip(FIELDS,values)) for values in itertools.product(*(grid[k] for k in FIELDS))]
    need(len(result)==26244 and len({identifier(c) for c in result})==26244 and BASELINE in result,'GRID_COMPLETENESS')
    need(protocol['selection_uses_evaluation'] is False and protocol['postselection_retuning'] is False
        and protocol['production_contacted'] is False,'SCOPE')
    return result


def hosted():need(os.environ.get('OWNED_GRID_HOSTED')=='1','LOCAL_CONTROLLER_OR_ACCOUNT_REPLAY')


def canonical_leaf(path,expected_sha,*,name='_private_sharadar_owned_grid'):
    hosted();raw=Path(path).read_bytes();need(hashlib.sha256(raw).hexdigest()==expected_sha,'CANONICAL_LEAF_SOURCE')
    need(name.startswith('_private_sharadar_owned_grid') and name not in sys.modules,'PRIVATE_MODULE_COLLISION')
    module=types.ModuleType(name);module.__package__='sentinel.controller';sys.modules[name]=module
    exec(compile(raw,str(path),'exec'),module.__dict__)
    expected={'schema':1,**{k:(int(v) if k.endswith('_sessions') else float(v)) for k,v in BASELINE.items()}}
    need(module.RULE==expected and module.STRATEGY_ID=='sentinel-compact-champion-owned55-v1','CANONICAL_RULE_BASIS')
    return module


def configure(module,config):
    need(set(config)==set(FIELDS),'PROFILE_FIELDS')
    module.RULE={'schema':1,**{k:int(v) if k.endswith('_sessions') else float(v) for k,v in config.items()}}
    module.STRATEGY_ID='research-sharadar-owned55-grid-001/'+identifier(config)


def metric(values,anchor):
    need(values and values[0][0]>anchor[0],'METRIC_ANCHOR')
    initial=Q(anchor[1]);peak=initial;dd=Q(0)
    for day,value in values:
        nav=Q(value);need(nav>0,'METRIC_POSITIVE_NAV');peak=max(peak,nav);dd=max(dd,1-nav/peak)
    multiple=Q(values[-1][1])/initial;elapsed=(date.fromisoformat(values[-1][0])-date.fromisoformat(anchor[0])).days
    return {'anchor':anchor[0],'start':values[0][0],'end':values[-1][0],'closes':len(values),
        'initial_nav':str(initial),'nav':str(Q(values[-1][1])),'multiple':str(multiple),'total_return':str(multiple-1),
        'cagr':math.expm1(math.log(float(multiple))*365.2425/elapsed),'maximum_drawdown_magnitude':str(dd)}


def select(records,protocol):
    expected=profiles(protocol);base_id=identifier(BASELINE)
    need(len(records)==26244 and {r['profile_id'] for r in records}=={identifier(c) for c in expected},'SELECTION_COMPLETE_CLASS')
    need(all(r['period']=='TRAINING' and r['evaluation_metrics_included'] is False for r in records),'SELECTION_EVALUATION_LEAK')
    need(all(r['metrics']['start']==protocol['training_start'] and r['metrics']['end']==protocol['training_end'] for r in records),'SELECTION_DATES')
    by_id={r['profile_id']:r for r in records};base=by_id[base_id];draw=Q(base['metrics']['maximum_drawdown_magnitude'])
    need(all(r['metrics']['closes']==base['metrics']['closes'] for r in records),'SELECTION_COMMON_AXIS')
    def key(r):return (-Q(r['metrics']['multiple']),Q(r['turnover']),r['profile_id']!=base_id,r['profile_id'])
    eligible=[r for r in records if r['profile_id']==base_id or r['different_funded_training_exposure']]
    chosen=[];budgets=[]
    for fraction in protocol['relative_drawdown_budgets']:
        limit=draw*Q(fraction);allowed=[r for r in eligible if Q(r['metrics']['maximum_drawdown_magnitude'])<=limit]
        winner=min(allowed,key=key) if allowed else None
        budgets.append({'relative_budget':fraction,'absolute_drawdown_budget':str(limit),'profile_id':None if winner is None else winner['profile_id']})
        if winner:chosen.append(winner['profile_id'])
    joint=[r for r in eligible if r['metrics']['cagr']>base['metrics']['cagr']+1e-10
        and Q(r['metrics']['maximum_drawdown_magnitude'])<draw-Q('1e-10')]
    best=min(joint,key=key)['profile_id'] if joint else None
    if best:chosen.append(best)
    chosen=list(dict.fromkeys(chosen));need(len(chosen)<=4,'SHORTLIST_BOUND')
    # Sweep once in descending growth order. Equal growth retains equal-DD ties.
    frontier=[];minimum=None;block_growth=None;block=[]
    def flush():
        nonlocal minimum,block
        if not block:return
        lowest=min(Q(r['metrics']['maximum_drawdown_magnitude']) for r in block)
        if minimum is None or lowest<minimum:frontier.extend(r['profile_id'] for r in block if Q(r['metrics']['maximum_drawdown_magnitude'])==lowest)
        minimum=lowest if minimum is None else min(minimum,lowest);block=[]
    for row in sorted(eligible,key=key):
        growth=Q(row['metrics']['multiple'])
        if block_growth is not None and growth!=block_growth:flush()
        block_growth=growth;block.append(row)
    flush()
    return {'schema':'research.sharadar-owned55-locked-selection/1','status':'TRAINING_SELECTION_LOCKED',
        'registered_profiles':26244,'reviewed_profiles':26244,'selected':chosen,'baseline':base_id,
        'budget_choices':budgets,'best_training_joint_gain':best,'training_pareto_profiles':sorted(frontier),
        'selection_cutoff':protocol['training_end'],'evaluation_used_for_selection':False,
        'known_history_not_unseen':True,'global_optimum_outside_declared_class':'UNKNOWN','production_contacted':False}
