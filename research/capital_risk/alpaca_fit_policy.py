"""Registered finite controller class and training-only Pareto selection."""
from __future__ import annotations
import ast
from decimal import Decimal
from fractions import Fraction as Q
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import types

from pydantic import BaseModel,ConfigDict,Field


def need(v,reason):
    if not v:raise ValueError('REFUSED_'+reason)


class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    entry_damage:Decimal=Field(ge=0,le=1)
    entry_sessions:int=Field(ge=1,le=5)
    recovery_sessions:int=Field(ge=3,le=8)
    active_ceiling:Decimal=Field(gt=0,le=1)

    @property
    def id(self):
        return f'D{int(self.entry_damage*100):02d}_E{self.entry_sessions}_R{self.recovery_sessions}_X{int(self.active_ceiling*100):02d}'


def profiles(protocol):
    fields=('entry_damage','entry_sessions','recovery_sessions','active_ceiling')
    need(protocol['family']=='EXISTING_OWNED55_PARAMETERS_ONLY' and protocol['combinations']==108,'FINITE_FAMILY')
    grid=protocol['grid'];need(set(grid)==set(fields),'GRID_FIELDS')
    result=[Profile(**dict(zip(fields,values))) for values in itertools.product(*(grid[f] for f in fields))]
    need(len(result)==108 and len({p.id for p in result})==108,'GRID_COVERAGE')
    baseline=Profile.model_validate(protocol['baseline']);need(baseline in result,'REGISTERED_BASELINE')
    return result,baseline


def leaf(source,profile,expected_sha):
    need(os.environ.get('ALPACA_FIT_HOSTED')=='1','LOCAL_CONTROLLER_REPLAY')
    raw=Path(source).read_bytes();need(hashlib.sha256(raw).hexdigest()==expected_sha,'CONTROLLER_SOURCE')
    tree=ast.parse(raw);changed=[]
    # Only the private leaf's RULE and identity constants change. No predicates,
    # ordering, state validators or production files are modified.
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name=='RULE':
                need(isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='dict','RULE_SHAPE')
                values={item.arg:ast.literal_eval(item.value) for item in node.value.keywords}
                expected=dict(schema=1,entry_drawdown=-.10,entry_damage=.88,entry_green=.20,entry_sessions=5,
                    recovery_damage=.63,recovery_green=.20,recovery_sessions=8,recovery_core_r20_above=0.,active_ceiling=.55)
                need(values==expected,'FROZEN_RULE_BASIS')
                values.update(entry_damage=float(profile.entry_damage),entry_sessions=profile.entry_sessions,
                    recovery_sessions=profile.recovery_sessions,active_ceiling=float(profile.active_ceiling))
                node.value=ast.parse(repr(values),mode='eval').body;changed.append(name)
            elif name=='STRATEGY_ID':
                node.value=ast.Constant('research-alpaca-owned55-fit-001/'+profile.id);changed.append(name)
    need(sorted(changed)==['RULE','STRATEGY_ID'],'PRIVATE_LEAF_PATCH_SCOPE')
    module_name='_research_alpaca_owned55_'+profile.id
    need(module_name not in sys.modules,'DUPLICATE_LEAF_WRITER')
    module=types.ModuleType(module_name);module.__package__='sentinel.controller';sys.modules[module_name]=module
    exec(compile(ast.fix_missing_locations(tree),str(source),'exec'),module.__dict__)
    module.research_identity={'profile':profile.model_dump(mode='json'),'source_sha256':expected_sha,
        'changed_constants':['RULE','STRATEGY_ID'],'production_module_mutated':False}
    return module


def select(records,protocol):
    registered,baseline=profiles(protocol);ids={p.id for p in registered}
    need(len(records)==108 and {r['profile_id'] for r in records}==ids,'REGISTERED_RECORD_COVERAGE')
    need(len({r['profile_id'] for r in records})==108,'DUPLICATE_PROFILE_SCORE')
    for row in records:
        need(row.get('period')=='TRAINING' and row.get('candidate_validation_metrics_included') is False,'VALIDATION_SELECTION_LEAK')
        if row['status']=='REVIEWED':
            m=row['metrics'];need(m['end']==protocol['training_end'] and m['start']==protocol['measured_start'],'TRAINING_AXIS')
    byid={r['profile_id']:r for r in records};base=byid[baseline.id]
    need(base['status']=='REVIEWED','BASELINE_NOT_ADMITTED')
    valid=[r for r in records if r['status']=='REVIEWED'];complete=len(valid)==108
    need(all(r['metrics']['closes']==base['metrics']['closes'] for r in valid),'COMMON_TRAINING_CLOSES')
    def key(row):return (-Q(row['metrics']['multiple']),Q(row['turnover']),row['profile_id']!=baseline.id,row['profile_id'])
    def dominates(a,b):
        am,bm=a['metrics'],b['metrics'];ad,bd=Q(am['maximum_drawdown_magnitude']),Q(bm['maximum_drawdown_magnitude'])
        ag,bg=Q(am['multiple']),Q(bm['multiple'])
        return ag>=bg and ad<=bd and (ag>bg or ad<bd)
    frontier=[r for r in valid if not any(dominates(o,r) for o in valid)]
    choices=[];budgets=[];db=Q(base['metrics']['maximum_drawdown_magnitude'])
    for fraction in protocol['relative_drawdown_budgets']:
        bound=db*Q(fraction)
        allowed=[r for r in valid if Q(r['metrics']['maximum_drawdown_magnitude'])<=bound
                 and (r['profile_id']==baseline.id or r['additional_funded_transitions']>0)]
        winner=min(allowed,key=key) if allowed else None
        budgets.append({'relative_budget':fraction,'drawdown_budget':str(bound),'selected':None if winner is None else winner['profile_id']})
        if winner is not None:choices.append(winner['profile_id'])
    joint=[r for r in valid if r['additional_funded_transitions']>0 and r['metrics']['cagr']>base['metrics']['cagr']+1e-10
           and Q(r['metrics']['maximum_drawdown_magnitude'])<db-Q('0.0000000001')]
    best=min(joint,key=key)['profile_id'] if joint else None
    if best:choices.append(best)
    selected=list(dict.fromkeys(choices));need(len(selected)<=protocol['maximum_shortlist'],'SHORTLIST_BOUND')
    return {'schema':'research.alpaca-fit-locked-selection/1','status':'TRAINING_SELECTION_LOCKED',
        'baseline':baseline.id,'registered_count':108,'reviewed_count':len(valid),'finite_class_exhaustive':complete,
        'global_gap_within_declared_finite_class':'0' if complete else 'UNKNOWN',
        'global_gap_over_all_possible_policies':'UNKNOWN','budgets':budgets,'best_training_joint_gain':best,
        'training_pareto_set':sorted(r['profile_id'] for r in frontier),'selected':selected,
        'selection_cutoff':protocol['training_end'],'validation_used_for_selection':False,
        'known_history_not_unseen':True,'production_contacted':False}
