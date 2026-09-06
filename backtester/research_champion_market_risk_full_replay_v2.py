#!/usr/bin/env python3
"""Exact observation-only market-risk controller replay V2.

RESEARCH / NOT CERTIFIED.

This harness preserves the corrected Champion's Candidate A state machine and
changes only the leadership-derived observations supplied to that state machine.
"""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
from backtester import research_champion_corrected_classification as corrected
from backtester import run_research_champion_pit_closure_20y as closure
from backtester import research_champion_market_risk_full_replay as legacy

STATUS='RESEARCH / NOT CERTIFIED'
SUPPORTED={'current','spy_price','spy_vol','vix_level_change','vix_percentile','spy_vix'}


def _candidate_source(family:str,params:dict)->str:
 return f'''MARKET_RISK_FAMILY={family!r}
MARKET_RISK_PARAMS={params!r}

class CandidateA:
    """Champion Candidate A with an independent observation adapter."""
    def __init__(self):
        self.episode=False; self.latched=False
        self.full_streak=0; self.recent_positive_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.concordance_releases=0; self.market_entries=0

    def _signals(self,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct):
        p=MARKET_RISK_PARAMS; f=MARKET_RISK_FAMILY
        if f=='spy_price':
            avail=finite(spy20) and finite(spy40) and finite(spydd)
            stress=avail and (spy20<=p['r20_stress'] or spydd<=p['dd_stress'])
            full=avail and spy20>p.get('r20_healthy',0.) and spy40>p.get('r40_healthy',0.)
            positive=finite(spy20) and spy20>0.
            recover=positive
        elif f=='spy_vol':
            avail=finite(rv20) and finite(volratio)
            stress=avail and rv20>=p['rv20_stress'] and volratio>=p['ratio_stress']
            full=avail and rv20<=p['rv20_healthy'] and volratio<=p.get('ratio_healthy',1.)
            positive=finite(volratio) and volratio<1.
            recover=avail and volratio<=1. and rv20<p['rv20_stress']
        elif f=='vix_level_change':
            avail=finite(vix) and finite(vixchg5)
            stress=avail and vix>=p['vix_stress'] and vixchg5>=p['chg5_stress']
            full=avail and vix<=p['vix_healthy'] and vixchg5<=p.get('chg5_healthy',0.)
            positive=finite(vixchg5) and vixchg5<0.
            recover=avail and vix<p['vix_stress'] and vixchg5<=0.
        elif f=='vix_percentile':
            avail=finite(vixpct) and finite(vixz) and finite(vixchg5)
            stress=avail and vixpct>=p['pct_stress'] and vixz>=p['z_stress']
            full=avail and vixpct<=p['pct_healthy']
            positive=finite(vixchg5) and vixchg5<0.
            recover=avail and vixpct<p['pct_stress'] and vixchg5<=0.
        elif f=='spy_vix':
            avail=(finite(spy20) and finite(spy40) and finite(spydd) and finite(vix)
                   and finite(vixz) and finite(vixchg5))
            spy_stress=avail and (spy20<=p['r20_stress'] or spydd<=p['dd_stress'])
            vix_stress=avail and (vix>=p['vix_stress'] or vixz>=p['z_stress'])
            stress=spy_stress and vix_stress
            full=avail and spy20>0 and spy40>0 and vix<=p['vix_healthy']
            positive=avail and spy20>0 and vixchg5<0
            recover=avail and spy20>0 and vix<p['vix_stress'] and vixchg5<=0
        else:
            raise RuntimeError(f'unsupported family {{f}}')
        return bool(avail),bool(stress),bool(full),bool(positive),bool(recover)

    def step(self,native,effective_native,wcdd,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct,wc_r20):
        avail,stress,full_healthy,positive,recovery_confirmed=self._signals(
            spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct)
        self.full_streak=self.full_streak+1 if full_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]

        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True
            self.recent_positive_streak=0
            reasons.append('RECOVERY_EPISODE_START')

        if self.episode:
            if native>0 and positive:
                self.recent_positive_streak+=1
            else:
                self.recent_positive_streak=0
        else:
            self.recent_positive_streak=0

        cleared=self.latched and (self.full_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')

        desired=native
        if self.episode and native>=1-1e-12:
            concordant=(
                self.recent_positive_streak>=LDRC_REC
                and finite(wc_r20) and wc_r20>0
                and recovery_confirmed
                and finite(spy20) and spy20>=wc_r20
            )
            if self.full_streak>=LDRC_REC or vre or concordant:
                self.episode=False; desired=1.
                if concordant and self.full_streak<LDRC_REC and not vre:
                    self.concordance_releases+=1
                    reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
                elif self.full_streak>=LDRC_REC:
                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
                else:
                    reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')
                self.recent_positive_streak=0
            else:
                desired=self.prev_desired
                reasons.append('FULL_RISK_HELD')

        entry=(
            not self.latched and not cleared
            and avail and finite(wcdd)
            and native>=1-1e-12
            and effective_native is not None and finite(effective_native)
            and effective_native>=1-1e-12
            and wcdd<=LDRC_DD
            and stress
        )
        if entry:
            self.latched=True; self.market_entries+=1
            reasons.append('MARKET_RISK_ENTER')

        if self.latched:
            desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'
'''


def install(text:str,family:str,params:dict)->str:
 if family not in SUPPORTED: raise RuntimeError(f'unsupported family {family}')
 # Reuse the V1 feature-loader seams only. family=current leaves Candidate A unchanged.
 text=legacy.install_market_observations(text,'current',{})
 if family!='current':
  text=legacy._replace_block(text,'class CandidateA:\n','class CandidateB:\n',_candidate_source(family,params),'CandidateA V2 replacement')
  old="a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
  new="a_d,a_reason=ca.step(native_target,effective_native,dd,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct,r20)"
  text=legacy._once(text,old,new,'CandidateA V2 observation call')
 compile(text,'<research-champion-market-risk-full-replay-v2>','exec')
 return text


def _sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
 return h.hexdigest()

def _mark_v2(output:Path,family:str,params:dict,vix_csv:Path):
 manifest={
  'status':STATUS,'methodology_version':'OBSERVATION_ONLY_V2','family':family,'params':params,
  'leadership_observation_active':family=='current','classification_independent_controller_observation':family!='current',
  'preserved_state_machine':['episode creation','persistence streak','SPY > 11% rebound route','cross-surface recovery route','latch/clear','55% ceiling','next-open timing'],
  'changed_layer':'leadership-derived market-risk observations only',
  'vix_source':'Cboe VIX historical daily close','vix_cutoff_sha256':_sha256(vix_csv),
  'frozen_profile':'strategy9-e3-research-champion-v1'
 }
 (output/'market-risk-controller-v2-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
 for name in ('summary.json','pit-closure-replay-identity.json'):
  p=output/name
  if p.exists():
   doc=json.loads(p.read_text()); doc.update(status=STATUS,certification_status='NOT_CERTIFIED',market_risk_methodology_version='OBSERVATION_ONLY_V2',market_risk_controller_family=family,market_risk_controller_params=params,leadership_observation_active=(family=='current')); p.write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
 evidence=sorted(p for p in output.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
 (output/'SHA256SUMS.txt').write_text(''.join(f'{_sha256(p)}  {p.name}\n' for p in evidence))

def run(output:Path,family:str,params:dict,vix_csv:Path)->int:
 if os.environ.get('PIT_OFFICIAL_BACKTEST','0') not in ('','0'): raise RuntimeError('research replay requires PIT_OFFICIAL_BACKTEST=0')
 original=closure.build_source
 def build(destination:Path)->str:
  return install(corrected.install(original(destination)),family,params)
 closure.build_source=build
 os.environ['BEST_EFFORT_SECURITY_TYPES']=str(corrected.base.DEFAULT_LEDGER.resolve()); os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO']='reviewed_18'; os.environ['MARKET_RISK_VIX_CSV']=str(vix_csv.resolve())
 try: rc=closure.run(output)
 finally: closure.build_source=original
 if rc:return rc
 corrected.base._rewrite_outputs(output.resolve(),'reviewed_18'); corrected._mark_corrected_outputs(output.resolve()); legacy._mark_outputs(output.resolve(),family,params,vix_csv.resolve()); _mark_v2(output.resolve(),family,params,vix_csv.resolve())
 print(f'[MARKET-RISK-V2] family={family} status={STATUS}',flush=True); return 0

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--family',choices=sorted(SUPPORTED),required=True); ap.add_argument('--params-json',default='{}'); ap.add_argument('--vix-csv',type=Path,required=True); ap.add_argument('--self-test-source',type=Path); a=ap.parse_args(); p=json.loads(a.params_json)
 if a.self_test_source:
  out=install(a.self_test_source.read_text(),a.family,p); print(json.dumps({'status':'PASS','family':a.family,'sha256':hashlib.sha256(out.encode()).hexdigest()},sort_keys=True)); return 0
 return run(a.output,a.family,p,a.vix_csv)
if __name__=='__main__':raise SystemExit(main())
