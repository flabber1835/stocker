"""Preregistered transformations of the exact stored simplified candidate."""
import ast
import hashlib
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
V1=HERE.parent/'wealth-core-v5-ex3-v6-simplification-v1'
sys.path.insert(0,str(V1))
from treatments import scope, replace_once, assert_scope

SOURCE_SHA='26b99f4a5f7fefc9d295479cc604e85a761db64cc5416664145fdd1b94b72939'
VARIANTS=('baseline','cleanup_state','symmetric_peers','clean_cached','no_peers',
          'fixed_ramp10','persistence_only','no_peers_fixed_ramp','no_peers_persistence','minimal_recovery')
EXACT_ARMS=('cleanup_state','symmetric_peers','clean_cached')
BREADTH_ARMS=('no_peers','no_peers_fixed_ramp','no_peers_persistence','minimal_recovery')
BASELINE_RESULT=json.loads((V1/'SIMPLIFIED_CANDIDATE_MANIFEST.json').read_text())['result']


def reference():
    source=(V1/'simplified_candidate.py').read_text()
    if hashlib.sha256(source.encode()).hexdigest()!=SOURCE_SHA:raise RuntimeError('stored simplified source changed')
    return source


def cleanup_native(body):
    old='''        elif self.ramp:
            need=10
            if self.ramp_h>=need:
                self.ramp_idx+=1; self.ramp_h=0
                if self.ramp_idx>=1: self.ramp=False; self.ramp_idx=None; target=1.
                else: target=.65
            else: target=.55 if self.ramp_idx==0 else .65
            if self.ramp: self.ramp_h=self.ramp_h+1 if healthy else 0
'''
    new='''        elif self.ramp:
            if self.ramp_h>=10:
                self.ramp=False; self.ramp_h=0; target=1.
            else: target=.55
            if self.ramp: self.ramp_h=self.ramp_h+1 if healthy else 0
'''
    body=replace_once(body,old,new)
    if body.count('; self.ramp_idx=None')!=3 or body.count('; self.ramp_idx=0')!=1:
        raise RuntimeError('ramp-index cleanup seam changed')
    return body.replace('; self.ramp_idx=None','').replace('; self.ramp_idx=0','')


def cleanup_overlay(body):
    body=replace_once(body,'        vre=False\n','')
    body=replace_once(body,'(self.full_streak>=LDRC_REC or vre)','(self.full_streak>=LDRC_REC)')
    body=replace_once(body,'self.full_streak>=LDRC_REC or vre or concordant','self.full_streak>=LDRC_REC or concordant')
    body=replace_once(body,'self.full_streak<LDRC_REC and not vre','self.full_streak<LDRC_REC')
    body=replace_once(body,"                elif self.full_streak>=LDRC_REC:\n                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')\n                else:\n                    reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')", "                else:\n                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')")
    return body


def cache_peers(body):
    body=replace_once(body,'    for i,z in enumerate(held):\n','    pair_cache={}\n    for i,z in enumerate(held):\n')
    return replace_once(body,"                c=_peer_corr(left,right); PEER_STATS['pair_correlations']+=1",'''                key=(min(i,j),max(i,j))
                if key not in pair_cache:
                    pair_cache[key]=_peer_corr(left,right); PEER_STATS['pair_correlations']+=1
                c=pair_cache[key]''')


def remove_peers(_):
    return '''def dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates):
    if not held: return 0.,0.
    PEER_STATS['breadth_sessions']+=1; PEER_STATS['holding_observations']+=len(held)
    green=sum(int(bool(z[6])) for z in held)
    damaged=sum(int((finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03)) for z in held)
    return green/len(held),damaged/len(held)
'''


def fixed_ramp(body):
    old='''        elif recovering:
            delta=(self.r40hist[-1]-self.r40hist[-6]) if len(self.r40hist)>=6 and finite(self.r40hist[-1]) and finite(self.r40hist[-6]) else None
            fragile=(delta<=0.) if finite(delta) else None
            if fragile is not False:
                self.ramp=True; self.ramp_h=1 if healthy else 0; target=.55
            else:
                self.ramp=False; self.ramp_h=0; target=1.
'''
    body=replace_once(body,old,'''        elif recovering:
            self.ramp=True; self.ramp_h=1 if healthy else 0; target=.55
''')
    body=replace_once(body,'; self.r40hist=[]','')
    return replace_once(body,'        self.r40hist=(self.r40hist+[r40])[-6:]\n','')


def persistence(body):
    old='''        if self.episode:
            if native>0 and finite(recent_r20) and recent_r20>0:
                self.recent_positive_streak+=1
            else:
                self.recent_positive_streak=0
        else:
            self.recent_positive_streak=0
'''
    body=replace_once(body,old,'')
    start=body.index('            concordant=(\n')
    end=body.index("                self.recent_positive_streak=0",start)
    body=body[:start]+'''            if self.full_streak>=LDRC_REC:
                self.episode=False; desired=1.
                reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
'''+body[end:]
    body=replace_once(body,'self.full_streak=0; self.recent_positive_streak=0','self.full_streak=0')
    # Only initialization/reset/capping references remain after release-route deletion.
    lines=[line for line in body.splitlines(keepends=True) if 'self.recent_positive_streak=' not in line]
    return ''.join(lines)


def build(variant):
    if variant not in VARIANTS:raise ValueError(variant)
    original=source=reference()
    if variant not in ('baseline','symmetric_peers'):
        source=scope(source,'Native',cleanup_native)
        source=scope(source,'CandidateA',cleanup_overlay)
    if variant in ('symmetric_peers','clean_cached'):
        source=scope(source,'dynamic_peer_breadth',cache_peers)
    if variant in BREADTH_ARMS:
        source=scope(source,'dynamic_peer_breadth',remove_peers)
    if variant in ('fixed_ramp10','no_peers_fixed_ramp','minimal_recovery'):
        source=scope(source,'Native',fixed_ramp)
    if variant in ('persistence_only','no_peers_persistence','minimal_recovery'):
        source=scope(source,'CandidateA',persistence)
    assert_scope(original,source,{'Native','CandidateA','dynamic_peer_breadth'})
    compile(source,variant+'.py','exec')
    return source
