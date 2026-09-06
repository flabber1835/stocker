#!/usr/bin/env python3
"""Targeted classification-to-leadership perturbation diagnostics.

RESEARCH / NOT CERTIFIED.

These counterfactuals alter only the eligible set used to form the recent-
leadership basket. Wealth Core eligibility, ranking, holdings and Native
Sentinel remain on the corrected path. This isolates controller mechanism #2.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
from backtester import research_champion_market_risk_full_replay as market
from backtester import run_research_champion_pit_closure_20y as closure

STATUS='RESEARCH / NOT CERTIFIED'
SCENARIOS={
 'reintroduce_eqm':{
   'action':'add','security_ids':['192545371416014112'],'first':'2013-07-17','last':'2020-06-16',
   'basis':'Known corrected EQM limited-partnership classification defect.'},
 'reintroduce_pds_trust':{
   'action':'add','security_ids':['594891209465982980'],'first':'2006-07-05','last':'2010-06-01',
   'basis':'Known corrected PDS pre-conversion trust-unit classification defect.'},
 'drop_audit_top1':{
   'action':'drop','security_ids':['932688238263985034'],'first':'2006-07-31','last':'2026-07-31',
   'basis':'WPM: highest recent-leadership-session count in baseline inferred-common audit.'},
 'drop_audit_top5':{
   'action':'drop','security_ids':['932688238263985034','177331179426033273','985458183012447728','756342866994377362','913893647957981163'],
   'first':'2006-07-31','last':'2026-07-31',
   'basis':'Top five LEADERSHIP_SIGNAL inferred-common names by recent-leadership-session count in baseline audit.'},
}

def _once(text,old,new,label):
 n=text.count(old)
 if n!=1: raise RuntimeError(f'{label}: expected one source seam, found {n}')
 return text.replace(old,new,1)

def install(text:str,scenario:str)->str:
 if scenario not in SCENARIOS: raise RuntimeError(f'unsupported scenario {scenario}')
 cfg=SCENARIOS[scenario]
 helper=f'''TARGET_CLASS_SCENARIO={scenario!r}
TARGET_CLASS_ACTION={cfg['action']!r}
TARGET_CLASS_SECURITY_IDS={cfg['security_ids']!r}
TARGET_CLASS_FIRST={cfg['first']!r}
TARGET_CLASS_LAST={cfg['last']!r}
_TARGET_CLASS_SESSIONS=0
_TARGET_CLASS_MEMBERSHIP_CHANGES=0

def _targeted_leadership_universe(ds,tids,base_elig,et):
    global _TARGET_CLASS_SESSIONS,_TARGET_CLASS_MEMBERSHIP_CHANGES
    if ds<TARGET_CLASS_FIRST or ds>TARGET_CLASS_LAST: return et
    out=list(map(int,et)); before=tuple(out)
    targets=[_SID_TO_TID.get(str(s)) for s in TARGET_CLASS_SECURITY_IDS]
    targets=[int(t) for t in targets if t is not None]
    if TARGET_CLASS_ACTION=='drop':
        remove=set(targets); out=[t for t in out if t not in remove]
    elif TARGET_CLASS_ACTION=='add':
        present={int(t):i for i,t in enumerate(tids)}
        for t in targets:
            j=present.get(t)
            if j is not None and bool(base_elig[j]) and t not in _retired_tids and t not in out:
                out.append(t)
    else: raise RuntimeError(TARGET_CLASS_ACTION)
    after=tuple(out)
    if after!=before:
        _TARGET_CLASS_SESSIONS+=1
        _TARGET_CLASS_MEMBERSHIP_CHANGES+=len(set(before)^set(after))
    return np.asarray(out,dtype=np.int32)
'''
 text=_once(text,'def run():\n',helper+'\ndef run():\n','target helper')
 old="                ordrec=np.lexsort((sid_et,-recent[et])); recsel=et[ordrec[:nk]]"
 new="""                lead_et=_targeted_leadership_universe(ds,tids,_base_elig,et)
                lead_sid=sid[lead_et]; nk_lead=min(len(lead_et),max(25,int(math.ceil(len(lead_et)*TOP)))) if len(lead_et) else 0
                ordrec=np.lexsort((lead_sid,-recent[lead_et])); recsel=lead_et[ordrec[:nk_lead]] if nk_lead else np.empty(0,np.int32)"""
 text=_once(text,old,new,'targeted leadership universe')
 marker="        'leadership_overlap_checks':overlap_checks,"
 repl=marker+"\n        'targeted_classification_perturbation':{'scenario':TARGET_CLASS_SCENARIO,'action':TARGET_CLASS_ACTION,'security_ids':TARGET_CLASS_SECURITY_IDS,'first':TARGET_CLASS_FIRST,'last':TARGET_CLASS_LAST,'sessions_changed':_TARGET_CLASS_SESSIONS,'membership_changes':_TARGET_CLASS_MEMBERSHIP_CHANGES},"
 text=_once(text,marker,repl,'target summary')
 compile(text,'<targeted-classification-perturbation>','exec'); return text

def sha(path:Path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
 return h.hexdigest()

def mark(out:Path,scenario:str,family:str):
 dpath=out/'daily.csv.gz'
 if dpath.exists():
  d=pd.read_csv(dpath); d['targeted_classification_perturbation']=scenario
  d.to_csv(dpath,index=False,compression={'method':'gzip','mtime':0})
 cfg=SCENARIOS[scenario]
 (out/'targeted-classification-perturbation-manifest.json').write_text(json.dumps({'status':STATUS,'scope':'LEADERSHIP_ONLY_AFTER_WEALTH_CORE_SELECTION_FIXED','scenario':scenario,'controller_family':family,**cfg,'interpretation':'robustness counterfactual; not historical truth'},indent=2,sort_keys=True)+'\n')
 ev=sorted(p for p in out.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
 (out/'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in ev))

def run(out:Path,family:str,params:dict,vix:Path,scenario:str):
 original=closure.build_source; closure.build_source=lambda dest: install(original(dest),scenario)
 try: rc=market.run(out,family,params,vix)
 finally: closure.build_source=original
 if rc:return rc
 mark(out.resolve(),scenario,family); return 0

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--family',choices=sorted(market.SUPPORTED),required=True); ap.add_argument('--params-json',default='{}'); ap.add_argument('--vix-csv',type=Path,required=True); ap.add_argument('--scenario',choices=sorted(SCENARIOS),required=True)
 a=ap.parse_args(); return run(a.output,a.family,json.loads(a.params_json),a.vix_csv,a.scenario)
if __name__=='__main__': raise SystemExit(main())
