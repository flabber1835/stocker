"""One frozen P2 latch. Inputs are already bound canonical own labels."""
from fractions import Fraction as Q
from copy import deepcopy
import math

def need(v,c):
    if not v:raise ValueError(c)

def step(previous,observations,*,enabled=True):
    need(len({r['episode'] for r in observations})==len(observations),'REFUSED_P2_DUPLICATE_EPISODE')
    scores={}
    for r in observations:
        weight,dd=Q(r['weight']),Q(r['drawdown'])
        need(weight>=0 and dd>=0,'REFUSED_P2_NEGATIVE_RISK')
        if r['red'] and not r['unknown']:scores[r['security_id']]=scores.get(r['security_id'],Q(0))+weight*dd
    result={};transitions=[];evidence=[]
    for r in observations:
        key=r['episode'];old=previous.get(key,dict(active=False,entry=0,recovery=0))
        state=deepcopy(old);score=scores.get(r['security_id'],Q(0));changed=None
        if r['core_exit']:continue
        if not enabled:state=dict(active=False,entry=0,recovery=0)
        elif r['unknown']:state.update(entry=0,recovery=0)
        elif state['active']:
            state['entry']=0;state['recovery']=state['recovery']+1 if r['green'] else 0
            if state['recovery']>=8:state=dict(active=False,entry=0,recovery=0);changed='RECOVER'
        else:
            state['recovery']=0;state['entry']=state['entry']+1 if r['red'] and score>=Q('0.02') else 0
            if state['entry']>=5:state=dict(active=True,entry=0,recovery=0);changed='ENTER'
        result[key]=state
        if changed:transitions.append(dict(episode=key,security_id=r['security_id'],transition=changed))
        evidence.append({**r,'security_impairment':str(score),'state_before':old,'state_after':state,'transition':changed})
    return result,transitions,evidence

def retention(states,key):return Q('0.55') if states.get(key,{}).get('active') else Q(1)
