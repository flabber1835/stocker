#!/usr/bin/env python3
"""Walk-forward dynamic calibration for the simplified broad PIT-estimate architecture.

Only Sentinel's damaged-breadth scale adapts. Wealth Core, correlation peers,
SLOW, ramp, and LD-RC remain frozen. No realized strategy return is used to
select parameters at run time.

Protocol:
- monthly candidate from strictly prior breadth observations;
- all prior history retained with a 5-year (1260-session) exponential half-life;
- expanding causal history defines the fixed-anchor percentile;
- 50% shrinkage toward fixed anchors 87.5% FAST / 62.5% healthy;
- 2.5 percentage-point steps, +/-5pp hard bands, max one step per activation;
- minimum 504 FAST observations and 252 healthy-state observations;
- activation deferred during any native/LD-RC defensive or recovery episode.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

from backtester import calibrate_broad_simplified_breadth as fixed
from backtester import run_research_ldrc_corrected_warmup_cash as corrected

LABEL = "BROAD_SIMPLIFIED_DYNAMIC_BREADTH_5Y_HALFLIFE_V1"


def once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one match, got {n}")
    return text.replace(old, new, 1)


HELPERS = r'''
DYN_FAST_ANCHOR=.875
DYN_HEALTHY_ANCHOR=.625
DYN_HALF_LIFE=1260.
DYN_SHRINK=.50
DYN_STEP=.025
DYN_FAST_MIN=.825
DYN_FAST_MAX=.925
DYN_HEALTHY_MIN=.575
DYN_HEALTHY_MAX=.675
DYN_MIN_FAST_OBS=504
DYN_MIN_HEALTHY_OBS=252

class DynamicBreadthCalibration:
    def __init__(self):
        self.fast=DYN_FAST_ANCHOR; self.healthy=DYN_HEALTHY_ANCHOR
        self.last_month=None; self.pending=None; self.active_cutoff=None
        self.candidates=0; self.activations=0; self.changed=0; self.deferred=0; self.no_change=0
        self.fast_values=[self.fast]; self.healthy_values=[self.healthy]

    @staticmethod
    def _anchor_percentile(hist,anchor):
        vals=[float(v) for _,v in hist if finite(v)]
        return None if not vals else sum(int(v<=anchor) for v in vals)/len(vals)

    @staticmethod
    def _weighted_quantile(hist,q,gday):
        rows=[]
        for day,val in hist:
            if finite(val): rows.append((float(val),.5**(max(gday-int(day),1)/DYN_HALF_LIFE)))
        if not rows: return None
        rows.sort(key=lambda z:z[0]); total=sum(w for _,w in rows); target=q*total; acc=0.
        for val,w in rows:
            acc+=w
            if acc>=target: return val
        return rows[-1][0]

    @staticmethod
    def _snap(anchor,value,lo,hi):
        value=min(max(float(value),lo),hi)
        return min(max(anchor+round((value-anchor)/DYN_STEP)*DYN_STEP,lo),hi)

    @staticmethod
    def _one_step(current,target):
        if target>current+DYN_STEP+1e-12: return current+DYN_STEP
        if target<current-DYN_STEP-1e-12: return current-DYN_STEP
        return target

    def _target(self,hist,anchor,lo,hi,min_obs,gday):
        if len(hist)<min_obs: return anchor
        q=self._anchor_percentile(hist,anchor)
        if q is None: return anchor
        q=min(max(q,.02),.98)
        recent=self._weighted_quantile(hist,q,gday)
        if recent is None or not finite(recent): return anchor
        return self._snap(anchor,anchor+DYN_SHRINK*(recent-anchor),lo,hi)

    def before_session(self,date,gday,fast_hist,healthy_hist,stable,cutoff):
        events=[]; month=(int(date.year),int(date.month))
        if month!=self.last_month:
            self.last_month=month
            self.pending={
                'fast':float(self._target(fast_hist,DYN_FAST_ANCHOR,DYN_FAST_MIN,DYN_FAST_MAX,DYN_MIN_FAST_OBS,gday)),
                'healthy':float(self._target(healthy_hist,DYN_HEALTHY_ANCHOR,DYN_HEALTHY_MIN,DYN_HEALTHY_MAX,DYN_MIN_HEALTHY_OBS,gday)),
                'cutoff':None if cutoff is None else str(pd.Timestamp(cutoff).date()),
            }
            self.candidates+=1; events.append('MONTH_CANDIDATE')
            if not stable: self.deferred+=1; events.append('DEFER_EPISODE')
        if self.pending is not None and stable:
            nf=min(max(self._one_step(self.fast,self.pending['fast']),DYN_FAST_MIN),DYN_FAST_MAX)
            nh=min(max(self._one_step(self.healthy,self.pending['healthy']),DYN_HEALTHY_MIN),DYN_HEALTHY_MAX)
            changed=abs(nf-self.fast)>1e-12 or abs(nh-self.healthy)>1e-12
            self.fast=float(nf); self.healthy=float(nh); self.active_cutoff=self.pending['cutoff']; self.activations+=1
            if changed:
                self.changed+=1; self.fast_values.append(self.fast); self.healthy_values.append(self.healthy); events.append('ACTIVATE_CHANGED')
            else:
                self.no_change+=1; events.append('ACTIVATE_NO_CHANGE')
            self.pending=None
        return '|'.join(events) if events else 'NONE'

    def summary(self):
        return {
            'kind':'causal_dynamic_breadth_scale_calibration','half_life_sessions':DYN_HALF_LIFE,
            'half_life_years':DYN_HALF_LIFE/252.,'shrinkage_to_anchor':DYN_SHRINK,'step':DYN_STEP,
            'fast_anchor':DYN_FAST_ANCHOR,'healthy_anchor':DYN_HEALTHY_ANCHOR,
            'fast_band':[DYN_FAST_MIN,DYN_FAST_MAX],'healthy_band':[DYN_HEALTHY_MIN,DYN_HEALTHY_MAX],
            'minimum_fast_observations':DYN_MIN_FAST_OBS,'minimum_healthy_observations':DYN_MIN_HEALTHY_OBS,
            'candidate_count':self.candidates,'activation_count':self.activations,'changed_activation_count':self.changed,
            'deferred_count':self.deferred,'no_change_count':self.no_change,
            'fast_min':float(min(self.fast_values)),'fast_max':float(max(self.fast_values)),
            'healthy_min':float(min(self.healthy_values)),'healthy_max':float(max(self.healthy_values)),
            'final_fast':float(self.fast),'final_healthy':float(self.healthy),'active_cutoff':self.active_cutoff,
            'return_optimized':False,'frequency':'monthly candidate; episode-latched activation',
        }
'''


def transformed_source(output: Path) -> str:
    text = fixed.transformed_source(output)
    marker = "    return ng/len(held),na/len(held)\n"
    text = once(text, marker, marker + "\n" + HELPERS + "\n", "dynamic helpers")
    text = once(
        text,
        "        self.ramp=False; self.ramp_idx=None; self.ramp_h=0; self.r40hist=[]",
        "        self.ramp=False; self.ramp_idx=None; self.ramp_h=0; self.r40hist=[]\n"
        "        self.fast_damaged=DYN_FAST_ANCHOR; self.healthy_damaged=DYN_HEALTHY_ANCHOR",
        "native thresholds",
    )
    text = once(
        text,
        "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=.625 and green>=.20",
        "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=self.healthy_damaged and green>=.20",
        "healthy dynamic seam",
    )
    text = once(text, "dam>=FAST['dam']", "dam>=self.fast_damaged", "FAST dynamic seam")
    text = once(
        text,
        "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()",
        "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native(); calibrator=DynamicBreadthCalibration()",
        "calibrator init",
    )
    text = once(
        text,
        "    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]",
        "    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]\n    cal_fast_hist=[]; cal_healthy_hist=[]",
        "calibration histories",
    )
    old = """            stops20=sum(1 for q in stop_days if 0<=gday-q<20)
            spy20=float(spy.loc[date,'r20']) if date in spy.index and finite(spy.loc[date,'r20']) else None
            volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None
            native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))"""
    new = """            stops20=sum(1 for q in stop_days if 0<=gday-q<20)
            spy20=float(spy.loc[date,'r20']) if date in spy.index and finite(spy.loc[date,'r20']) else None
            volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None
            stable_cal=(not (native.ordinary or native.base_fast or native.fast or native.slow or native.ramp or ctl.episode or ctl.latched)
                        and abs(pending_native-1.)<1e-12 and abs(effective_native-1.)<1e-12
                        and abs(pend['control']-1.)<1e-12 and abs(eff['control']-1.)<1e-12)
            prior_cutoff=shadow_dates[-2] if len(shadow_dates)>=2 else None
            cal_event=calibrator.before_session(date,gday,cal_fast_hist,cal_healthy_hist,stable_cal,prior_cutoff)
            native.fast_damaged=calibrator.fast; native.healthy_damaged=calibrator.healthy
            native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))
            if held:
                cal_fast_hist.append((gday,float(dam_b)))
                if finite(r20) and r20>0 and finite(green_b) and green_b>=.20: cal_healthy_hist.append((gday,float(dam_b)))"""
    text = once(text, old, new, "causal monthly decision")
    old_row = "'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held))})"
    new_row = "'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'dynamic_fast_damaged':float(calibrator.fast),'dynamic_healthy_damaged':float(calibrator.healthy),'calibration_cutoff':calibrator.active_cutoff,'calibration_event':cal_event})"
    text = once(text, old_row, new_row, "calibration telemetry")
    text = once(text, "'correlation_peer_stats':PEER_STATS,", "'correlation_peer_stats':PEER_STATS,'dynamic_calibration_stats':calibrator.summary(),", "calibration summary")
    return text


def finalize(output: Path) -> None:
    fixed.finalize(output)
    sp = output / "summary.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["experiment"] = "broad_simplified_dynamic_breadth_5y_halflife"
    s["evidence_label"] = LABEL
    s["calibration"] = {
        "kind":"causal_dynamic_breadth_scale_calibration","fast_anchor":.875,"healthy_anchor":.625,
        "half_life_sessions":1260,"half_life_years":5.0,"shrinkage_to_anchor":.50,"step":.025,
        "fast_band":[.825,.925],"healthy_band":[.575,.675],"minimum_fast_observations":504,
        "minimum_healthy_observations":252,"frequency":"monthly candidate; episode-latched activation",
        "return_optimized":False,"wealth_core_parameters_changed":False,"peer_definition_changed":False,
        "slow_parameters_changed":False,"ramp_parameters_changed":False,"ldrc_parameters_changed":False,
        "causality":"first-session monthly candidate uses observations through the prior session only; activation deferred until stable full-risk state",
    }
    sp.write_text(json.dumps(s,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    d = pd.read_csv(output/"daily.csv.gz",compression="gzip")
    ledger = d[d.calibration_event.fillna("NONE").ne("NONE")][[
        "date","dynamic_fast_damaged","dynamic_healthy_damaged","calibration_cutoff","calibration_event",
        "native_close_target","control_allocation",
    ]].copy()
    ledger.to_csv(output/"calibration-ledger.csv",index=False)

    mp = output/"experiment2-manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["schema"]="backtester.broad-simplified-dynamic-breadth/1"; m["evidence_label"]=LABEL
    m["experiment"]=s["experiment"]; m["calibration"]=s["calibration"]
    m["dynamic_calibration_stats"]=s.get("dynamic_calibration_stats")
    mp.write_text(json.dumps(m,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    files=[output/"daily.csv.gz",output/"metrics.csv",sp,mp,output/"calibration-ledger.csv"]
    (output/"SHA256SUMS.txt").write_text("".join(f"{corrected.old.sha256(p)}  {p.name}\n" for p in files),encoding="utf-8")
    print("[DYNAMIC]",json.dumps(s.get("dynamic_calibration_stats"),indent=2,sort_keys=True),flush=True)
    print(pd.read_csv(output/"metrics.csv",dtype={"window_years":str}).to_string(index=False),flush=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    generated=Path("/tmp/broad_simplified_dynamic_breadth.py")
    generated.write_text(transformed_source(args.output),encoding="utf-8")
    env=dict(os.environ); env["RESEARCH_REPLAY_MODE"]="fullpit"
    print(f"[RUN] {LABEL}",flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    finalize(args.output); return 0


if __name__=="__main__": raise SystemExit(main())
