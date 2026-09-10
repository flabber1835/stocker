#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

EPS=1e-12


def positions(x):
    if isinstance(x,list): return set(map(str,x))
    return set(map(str,json.loads(str(x))))


def curve_cagr(frame,col):
    x=frame[["date",col]].dropna().copy()
    x["date"]=pd.to_datetime(x.date)
    if len(x)<2 or float(x[col].iloc[0])<=0 or float(x[col].iloc[-1])<=0: return None
    years=(x.date.iloc[-1]-x.date.iloc[0]).days/365.2425
    return float((float(x[col].iloc[-1])/float(x[col].iloc[0]))**(1/years)-1) if years>0 else None


def first_true(mask,dates):
    ix=np.flatnonzero(mask)
    return None if not len(ix) else str(pd.Timestamp(dates.iloc[int(ix[0])]).date())


def last_true(mask,dates):
    ix=np.flatnonzero(mask)
    return None if not len(ix) else str(pd.Timestamp(dates.iloc[int(ix[-1])]).date())


def terminal_reconvergence(mask,dates):
    """First session after the last difference; None if paths end divergent."""
    ix=np.flatnonzero(mask)
    if not len(ix): return str(pd.Timestamp(dates.iloc[0]).date())
    last=int(ix[-1])
    if last>=len(mask)-1: return None
    return str(pd.Timestamp(dates.iloc[last+1]).date())


def first_durable_reconvergence(mask,dates,n=20):
    ix=np.flatnonzero(mask)
    if not len(ix): return str(pd.Timestamp(dates.iloc[0]).date())
    first=int(ix[0])
    same=(~mask).astype(np.int8)
    run=0
    for i in range(first+1,len(mask)):
        run=run+1 if same[i] else 0
        if run>=n:
            return str(pd.Timestamp(dates.iloc[i-n+1]).date())
    return None


def diff_fields(a,b,ignore=()):
    try:
        da=json.loads(a) if isinstance(a,str) else dict(a)
        db=json.loads(b) if isinstance(b,str) else dict(b)
    except Exception:
        return []
    out=[]
    for k in sorted(set(da)|set(db)):
        if k in ignore: continue
        va=da.get(k); vb=db.get(k)
        if va!=vb: out.append({"field":k,"baseline":va,"case":vb})
    return out


def load_pair(path:Path):
    if path.is_file(): return pd.read_csv(path,parse_dates=["date"])
    found=sorted(path.rglob("paired-daily.csv"))
    if len(found)!=1:
        raise RuntimeError(f"expected one paired-daily.csv under {path}, saw {len(found)}: {found}")
    return pd.read_csv(found[0],parse_dates=["date"])


def load_result(path:Path):
    found=sorted(path.rglob("RESULT.json"))
    if len(found)!=1: raise RuntimeError(f"expected one RESULT.json under {path}, saw {len(found)}")
    return json.loads(found[0].read_text())


def single_case_meta(result):
    xs=result.get("cases") or []
    if len(xs)!=1: return {"case":None,"security_id":None,"classification":None}
    x=xs[0]
    return {"case":x.get("case"),"security_id":x.get("security_id"),"classification":x.get("classification")}


def analyze_case(base,case,meta):
    m=base.merge(case,on="date",suffixes=("_base","_case"),how="inner",validate="one_to_one")
    if len(m)!=len(base) or len(m)!=len(case): raise RuntimeError("date alignment mismatch")
    dates=m.date
    pbase=[positions(x) for x in m.research_selected_positions_base]
    pcase=[positions(x) for x in m.research_selected_positions_case]
    core=np.array([a!=b for a,b in zip(pbase,pcase)],bool)
    jac=np.array([len(a&b)/len(a|b) if a|b else 1. for a,b in zip(pbase,pcase)],float)
    sym=np.array([len(a^b) for a,b in zip(pbase,pcase)],int)

    nA=np.abs(m.native_close_target_base.astype(float).to_numpy()-m.native_close_target_case.astype(float).to_numpy())>EPS
    nB=np.abs(m.native_close_target_v2_base.astype(float).to_numpy()-m.native_close_target_v2_case.astype(float).to_numpy())>EPS
    aA=np.abs(m.A_allocation_base.astype(float).to_numpy()-m.A_allocation_case.astype(float).to_numpy())>EPS
    aB=np.abs(m.B_allocation_base.astype(float).to_numpy()-m.B_allocation_case.astype(float).to_numpy())>EPS

    sid=meta.get("security_id")
    last_excluded=None; gone_mask=np.ones(len(m),bool)
    if sid:
        present=np.array([str(sid) in x for x in pbase],bool)
        ix=np.flatnonzero(present)
        if len(ix):
            last_excluded=int(ix[-1]); gone_mask=np.arange(len(m))>last_excluded

    def layer(mask):
        return {
            "difference_sessions":int(mask.sum()),"divergence_fraction":float(mask.mean()),
            "first_divergence":first_true(mask,dates),"last_divergence":last_true(mask,dates),
            "first_20_session_durable_reconvergence":first_durable_reconvergence(mask,dates,20),
            "terminal_reconvergence":terminal_reconvergence(mask,dates),
            "terminally_reconverged":terminal_reconvergence(mask,dates) is not None,
            "post_excluded_gone_divergence_fraction":None if not gone_mask.any() else float(mask[gone_mask].mean()),
        }

    core_frac=float(core.mean())
    nAf=float(nA.mean()); nBf=float(nB.mean()); aAf=float(aA.mean()); aBf=float(aB.mean())
    trace={
        "first_core_divergence":first_true(core,dates),
        "first_native_divergence_control":first_true(nA,dates),
        "first_native_divergence_v2":first_true(nB,dates),
        "first_ex3_divergence_control":first_true(aA,dates),
        "first_ex3_divergence_v2":first_true(aB,dates),
        "last_baseline_session_holding_excluded_security":None if last_excluded is None else str(pd.Timestamp(dates.iloc[last_excluded]).date()),
    }

    def state_witness(mask,native=True,post_gone=False):
        usable=mask.copy()
        if post_gone: usable &= gone_mask
        ix=np.flatnonzero(usable)
        if not len(ix): return None
        i=int(ix[0])
        if native:
            fa=diff_fields(m.research_native_state_base.iloc[i],m.research_native_state_case.iloc[i])
            fb=diff_fields(m.research_native_state_v2_base.iloc[i],m.research_native_state_v2_case.iloc[i],ignore=("canonicalizations",))
        else:
            fa=diff_fields(m.research_ldrc_state_base.iloc[i],m.research_ldrc_state_case.iloc[i],ignore=("episodes","concordance_releases"))
            fb=diff_fields(m.research_ldrc_state_v2_base.iloc[i],m.research_ldrc_state_v2_case.iloc[i],ignore=("episodes","concordance_releases","canonicalizations"))
        return {"date":str(pd.Timestamp(dates.iloc[i]).date()),"control_differing_fields":fa,"v2_differing_fields":fb}

    trace["native_state_at_first_native_divergence"]=state_witness(nA,True,False)
    trace["ex3_state_at_first_ex3_divergence"]=state_witness(aA,False,False)
    trace["native_state_first_divergence_after_excluded_gone"]=state_witness(nA,True,True)
    trace["ex3_state_first_divergence_after_excluded_gone"]=state_witness(aA,False,True)

    core_cagr_base=curve_cagr(m.rename(columns={"shadow_equity_base":"x"}),"x")
    core_cagr_case=curve_cagr(m.rename(columns={"shadow_equity_case":"x"}),"x")
    a_cagr_base=curve_cagr(m.rename(columns={"A_nav_base":"x"}),"x")
    a_cagr_case=curve_cagr(m.rename(columns={"A_nav_case":"x"}),"x")
    b_cagr_base=curve_cagr(m.rename(columns={"B_nav_base":"x"}),"x")
    b_cagr_case=curve_cagr(m.rename(columns={"B_nav_case":"x"}),"x")
    core_delta=None if None in (core_cagr_base,core_cagr_case) else abs(core_cagr_case-core_cagr_base)
    econA=None if None in (a_cagr_base,a_cagr_case) else abs(a_cagr_case-a_cagr_base)
    econB=None if None in (b_cagr_base,b_cagr_case) else abs(b_cagr_case-b_cagr_base)

    return {
        **meta,
        "core":{"divergence_fraction":core_frac,"mean_jaccard":float(jac.mean()),"max_symmetric_difference":int(sym.max()),
                "first_divergence":first_true(core,dates),"terminal_reconvergence":terminal_reconvergence(core,dates),
                "post_excluded_gone_divergence_fraction":None if not gone_mask.any() else float(core[gone_mask].mean())},
        "native_control":layer(nA),"native_v2":layer(nB),
        "ex3_control":layer(aA),"ex3_v2":layer(aB),
        "amplification":{
            "native_over_core_control":None if core_frac<=EPS else nAf/core_frac,
            "native_over_core_v2":None if core_frac<=EPS else nBf/core_frac,
            "ex3_over_native_control":None if nAf<=EPS else aAf/nAf,
            "ex3_over_native_v2":None if nBf<=EPS else aBf/nBf,
            "final_over_core_control":None if core_frac<=EPS else aAf/core_frac,
            "final_over_core_v2":None if core_frac<=EPS else aBf/core_frac,
        },
        "economics":{
            "abs_core_cagr_delta_pp":None if core_delta is None else 100*core_delta,
            "abs_final_cagr_delta_pp_control":None if econA is None else 100*econA,
            "abs_final_cagr_delta_pp_v2":None if econB is None else 100*econB,
            "economic_amplification_control":None if not core_delta or econA is None else econA/core_delta,
            "economic_amplification_v2":None if not core_delta or econB is None else econB/core_delta,
        },
        "causal_trace":trace,
    }


def med(xs,key):
    vals=[x[key] for x in xs if x.get(key) is not None and math.isfinite(float(x[key]))]
    return None if not vals else float(np.median(vals))


def aggregate(cases):
    if not cases: return {}
    return {
        "n":len(cases),
        "median_core_divergence":med([x["core"] for x in cases],"divergence_fraction"),
        "median_native_divergence_control":med([x["native_control"] for x in cases],"divergence_fraction"),
        "median_native_divergence_v2":med([x["native_v2"] for x in cases],"divergence_fraction"),
        "median_final_divergence_control":med([x["ex3_control"] for x in cases],"divergence_fraction"),
        "median_final_divergence_v2":med([x["ex3_v2"] for x in cases],"divergence_fraction"),
        "median_native_over_core_control":med([x["amplification"] for x in cases],"native_over_core_control"),
        "median_native_over_core_v2":med([x["amplification"] for x in cases],"native_over_core_v2"),
        "median_ex3_over_native_control":med([x["amplification"] for x in cases],"ex3_over_native_control"),
        "median_ex3_over_native_v2":med([x["amplification"] for x in cases],"ex3_over_native_v2"),
        "terminal_native_reconvergence_control":sum(bool(x["native_control"]["terminally_reconverged"]) for x in cases),
        "terminal_native_reconvergence_v2":sum(bool(x["native_v2"]["terminally_reconverged"]) for x in cases),
        "terminal_final_reconvergence_control":sum(bool(x["ex3_control"]["terminally_reconverged"]) for x in cases),
        "terminal_final_reconvergence_v2":sum(bool(x["ex3_v2"]["terminally_reconverged"]) for x in cases),
    }


def baseline_gate(frame):
    native=np.abs(frame.native_close_target.astype(float)-frame.native_close_target_v2.astype(float))>EPS
    alloc=np.abs(frame.A_allocation.astype(float)-frame.B_allocation.astype(float))>EPS
    an=frame.A_nav.astype(float); bn=frame.B_nav.astype(float)
    nav_abs=float(np.max(np.abs(an-bn)))
    result={
        "native_difference_sessions":int(native.sum()),
        "allocation_difference_sessions":int(alloc.sum()),
        "max_abs_nav_difference":nav_abs,
        "native_canonicalization_final_count":int(frame.native_v2_canonicalizations.iloc[-1]),
        "ex3_canonicalization_final_count":int(frame.ex3_v2_canonicalizations.iloc[-1]),
    }
    result["pass"]=(result["native_difference_sessions"]==0 and result["allocation_difference_sessions"]==0 and nav_abs<=1e-11)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline",type=Path,required=True)
    ap.add_argument("--cases",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--screen",action="store_true")
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    base=load_pair(args.baseline)
    gate=baseline_gate(base)
    rows=[]
    if args.cases and args.cases.exists():
        for d in sorted(x for x in args.cases.iterdir() if x.is_dir()):
            try:
                c=load_pair(d); r=load_result(d); meta=single_case_meta(r)
                rows.append(analyze_case(base,c,meta))
            except RuntimeError:
                continue
    agg=aggregate(rows)

    # A safe semantic quotient is only promising as a butterfly treatment if it
    # preserves baseline exactly and reduces controller divergence in the screen.
    improve_native=(agg.get("median_native_divergence_v2") is not None and agg.get("median_native_divergence_control") is not None and agg["median_native_divergence_v2"] < agg["median_native_divergence_control"]-1e-9)
    improve_final=(agg.get("median_final_divergence_v2") is not None and agg.get("median_final_divergence_control") is not None and agg["median_final_divergence_v2"] < agg["median_final_divergence_control"]-1e-9)
    proceed=bool(gate["pass"] and (improve_native or improve_final))
    verdict=("CONVERGENCE V2 SOLVES MATERIAL SENTINEL AMPLIFICATION" if proceed and improve_native and improve_final else
             "CONVERGENCE V2 HELPS BUT MATERIAL AMPLIFICATION REMAINS" if proceed else
             "SENTINEL IS NOT THE PRIMARY BUTTERFLY SOURCE")
    out={"baseline_gate":gate,"cases":rows,"aggregate":agg,"proceed_full_campaign":proceed,"provisional_verdict":verdict}
    (args.out/"SUMMARY.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    (args.out/"PROCEED_FULL_CAMPAIGN.txt").write_text(("true" if proceed else "false")+"\n")
    print(json.dumps({"baseline_gate":gate,"aggregate":agg,"proceed":proceed,"verdict":verdict},indent=2,sort_keys=True))
    if not gate["pass"]: raise SystemExit(2)

if __name__=="__main__": main()
