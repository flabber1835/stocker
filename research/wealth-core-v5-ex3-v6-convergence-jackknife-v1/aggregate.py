#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd


def load_result(path: Path): return json.loads(path.read_text())
def pos(raw):
    try: return set(json.loads(raw)) if isinstance(raw,str) and raw else set()
    except Exception: return set()

def sustained_exact(diff: np.ndarray, dates, n=20):
    same=~diff
    for i in range(0,len(same)-n+1):
        if same[i:i+n].all() and same[i:].mean() >= .99:
            return str(pd.Timestamp(dates.iloc[i]).date())
    return None

def path_stats(base, case):
    bsets=[pos(x) for x in base.research_selected_positions.fillna('[]')]
    csets=[pos(x) for x in case.research_selected_positions.fillna('[]')]
    sym=np.array([len(a^b) for a,b in zip(bsets,csets)],int)
    jac=np.array([1.0 if not (a|b) else len(a&b)/len(a|b) for a,b in zip(bsets,csets)],float)
    diff=sym>0; idx=np.flatnonzero(diff)
    return {"first_core_divergence":None if not len(idx) else str(pd.Timestamp(case.date.iloc[int(idx[0])]).date()),
            "core_exact_fraction":float((~diff).mean()),"median_jaccard":float(np.median(jac)),
            "max_symmetric_difference":int(sym.max()),"sustained_20_exact_reconvergence":sustained_exact(diff,case.date,20),
            "core_divergence_fraction":float(diff.mean())}

def alloc_stats(base,case,col):
    d=np.abs(base[col].astype(float).to_numpy()-case[col].astype(float).to_numpy())>1e-12
    idx=np.flatnonzero(d)
    return {"first_divergence":None if not len(idx) else str(pd.Timestamp(case.date.iloc[int(idx[0])]).date()),
            "divergence_sessions":int(d.sum()),"divergence_fraction":float(d.mean()),
            "sustained_20_reconvergence":sustained_exact(d,case.date,20),"never_reconverged":sustained_exact(d,case.date,20) is None and bool(d.any())}

def perf(result,key):
    m=result["result"][key]["20"] if key=="treatment" else result["result"]["sentinel"]["20"]
    return {k:m[k] for k in ("cagr","max_drawdown","sharpe_daily_252","ending_multiple")}
def delta(p,b): return {k:float(p[k])-float(b[k]) for k in p if p[k] is not None and b[k] is not None}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args()
    br=load_result(a.root/'baseline'/'RESULT.json'); bd=pd.read_csv(a.root/'baseline'/'paired-daily.csv',parse_dates=['date'])
    bpa=br['baseline']['sentinel']['20']; bpb=br['baseline']['treatment']['20']
    rows=[]
    for p in sorted(a.root.glob('case-*')):
        rp=list(p.rglob('RESULT.json'))
        if not rp: continue
        rr=load_result(rp[0]); cases=rr.get('cases',[])
        for c in cases:
            tag=c['case']; csvs=list(p.rglob(f'runs/{tag}/paired-daily.csv'))
            if not csvs: continue
            cd=pd.read_csv(csvs[0],parse_dates=['date']); ps=path_stats(bd,cd); sa=alloc_stats(bd,cd,'A_allocation'); sb=alloc_stats(bd,cd,'B_allocation')
            pa=c['result']['sentinel']['20']; pb=c['result']['treatment']['20']
            row={"case":tag,"security_id":c.get('security_id'),"core":ps,"unpatched":sa,"patched":sb,
                 "unpatched_perf_delta":delta(pa,bpa),"patched_perf_delta":delta(pb,bpb)}
            if ps['core_divergence_fraction']>0:
                row['unpatched_amplification']=sa['divergence_fraction']/ps['core_divergence_fraction']
                row['patched_amplification']=sb['divergence_fraction']/ps['core_divergence_fraction']
            sid=c.get('security_id')
            if sid:
                held=np.array([sid in pos(x) for x in bd.research_selected_positions.fillna('[]')]); ix=np.flatnonzero(held)
                last=None if not len(ix) else pd.Timestamp(bd.date.iloc[int(ix[-1])])
                for name,st in [('unpatched',sa),('patched',sb)]:
                    fd=st['first_divergence']; row[name]['first_divergence_after_excluded_security_gone']=bool(fd and last is not None and pd.Timestamp(fd)>last)
            rows.append(row)
    loo=[r for r in rows if r['security_id']]; drops=[r for r in rows if not r['security_id']]
    def agg(xs,side):
        if not xs:return {}
        ac=np.array([abs(x[f'{side}_perf_delta']['cagr']) for x in xs]); fr=np.array([x[side]['divergence_fraction'] for x in xs]); amps=np.array([x.get(f'{side}_amplification',np.nan) for x in xs])
        return {"cases":len(xs),"median_abs_cagr_delta_pp":float(np.median(ac)*100),"p95_abs_cagr_delta_pp":float(np.quantile(ac,.95)*100),
                "max_abs_cagr_delta_pp":float(ac.max()*100),"loss_ge_1pp":sum(x[f'{side}_perf_delta']['cagr']<=-.01 for x in xs),
                "loss_ge_2pp":sum(x[f'{side}_perf_delta']['cagr']<=-.02 for x in xs),"median_allocation_divergence_fraction":float(np.median(fr)),
                "never_reconverged":sum(x[side]['never_reconverged'] for x in xs),"median_amplification":float(np.nanmedian(amps)) if np.isfinite(amps).any() else None}
    au,apc=agg(loo,'unpatched'),agg(loo,'patched')
    score=[]
    for k in ('median_allocation_divergence_fraction','never_reconverged','median_abs_cagr_delta_pp','p95_abs_cagr_delta_pp'):
        if k in au and k in apc: score.append(apc[k] < au[k])
    if score and all(score): verdict='MATERIAL ROBUSTNESS IMPROVEMENT'
    elif score and sum(score)>=2: verdict='SOME IMPROVEMENT, BUT BUTTERFLY ISSUE REMAINS'
    elif score and sum(score)==0: verdict='NO MEANINGFUL IMPROVEMENT'
    else: verdict='MIXED / REQUIRES REVIEW'
    out={"schema":"research.wealth-core-v5-ex3-v6-convergence-jackknife/1","baseline":{"unpatched":bpa,"patched":bpb,"paired_direct":br['baseline']['paired_direct']},
         "loo_aggregate":{"unpatched":au,"patched":apc},"dropout_cases":drops,"loo_cases":loo,"verdict":verdict,
         "patch":"research-only neutral full-native REC8 canonicalization","promotion":"FORBIDDEN_BY_THIS_EXPERIMENT"}
    a.out.mkdir(parents=True,exist_ok=True); (a.out/'SUMMARY.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    pd.DataFrame([{**{"case":r['case'],"security_id":r['security_id']},**{f'u_{k}':v for k,v in r['unpatched'].items()},**{f'p_{k}':v for k,v in r['patched'].items()}} for r in rows]).to_csv(a.out/'compact.csv',index=False)
    print(json.dumps({"verdict":verdict,"loo":len(loo),"dropouts":len(drops),"unpatched":au,"patched":apc},indent=2))
if __name__=='__main__': main()
