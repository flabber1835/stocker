#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


def read_csv(zpath:Path,needle:str):
    with zipfile.ZipFile(zpath) as z:
        names=[n for n in z.namelist() if n.endswith(needle)]
        if len(names)!=1: raise RuntimeError(f"{zpath}: {needle}: {names}")
        return pd.read_csv(io.BytesIO(z.read(names[0])),parse_dates=["date"])


def pos(x): return set(map(str,json.loads(str(x))))

def first(mask,dates):
    ix=np.flatnonzero(mask)
    return None if not len(ix) else str(pd.Timestamp(dates.iloc[int(ix[0])]).date())

def divergence(base,case):
    m=base.merge(case,on="date",suffixes=("_b","_c"),validate="one_to_one")
    pb=[pos(x) for x in m.research_selected_positions_b]; pc=[pos(x) for x in m.research_selected_positions_c]
    core=np.array([a!=b for a,b in zip(pb,pc)],bool)
    native=np.abs(m.native_close_target_b.astype(float)-m.native_close_target_c.astype(float))>1e-12
    alloc=np.abs(m.A_allocation_b.astype(float)-m.A_allocation_c.astype(float))>1e-12
    return m,pb,pc,core,native,alloc

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline",type=Path,required=True)
    ap.add_argument("--high",type=Path,required=True)
    ap.add_argument("--ordinary1",type=Path,required=True)
    ap.add_argument("--ordinary2",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    b=read_csv(a.baseline,"/engine/daily.csv")
    high=read_csv(a.high,"/engine/daily.csv")
    m,pb,pc,core,native,alloc=divergence(b,high)
    excluded="301606049357818446"
    present=np.array([excluded in x for x in pb],bool); li=int(np.flatnonzero(present)[-1])
    ni=int(np.flatnonzero(native)[0])
    # Drawdown crossing is the observable event that starts the ordinary base episode.
    cb=(m.wc_dd_b<=-.155)&(m.wc_dd_b.shift(1)>-.155)
    cc=(m.wc_dd_c<=-.155)&(m.wc_dd_c.shift(1)>-.155)
    win=m.date.between("2010-01-01","2010-05-28")
    cross_b=m.loc[cb&win,"date"].iloc[0]
    cross_c=m.loc[cc&win,"date"].iloc[0]
    witness={
        "security_id":excluded,
        "first_core_divergence":first(core,m.date),
        "last_session_excluded_security_in_baseline":str(m.date.iloc[li].date()),
        "first_native_divergence":first(native,m.date),
        "first_ex3_allocation_divergence":first(alloc,m.date),
        "ordinary_trigger_crossing_baseline":str(cross_b.date()),
        "ordinary_trigger_crossing_case":str(cross_c.date()),
        "first_native_witness":{
            "date":str(m.date.iloc[ni].date()),
            "holdings_equal":pb[ni]==pc[ni],
            "baseline_shadow_equity":float(m.shadow_equity_b.iloc[ni]),
            "case_shadow_equity":float(m.shadow_equity_c.iloc[ni]),
            "baseline_wc_dd":float(m.wc_dd_b.iloc[ni]),
            "case_wc_dd":float(m.wc_dd_c.iloc[ni]),
            "damaged_equal":bool(abs(float(m.damaged_b.iloc[ni])-float(m.damaged_c.iloc[ni]))<1e-12),
            "green_equal":bool(abs(float(m.green_b.iloc[ni])-float(m.green_c.iloc[ni]))<1e-12),
            "recent_r20_equal":bool(abs(float(m.recent_r20_b.iloc[ni])-float(m.recent_r20_c.iloc[ni]))<1e-12),
            "recent_r40_equal":bool(abs(float(m.recent_r40_b.iloc[ni])-float(m.recent_r40_c.iloc[ni]))<1e-12),
            "baseline_slow_signal":bool(m.slow_signal_b.iloc[ni]),
            "case_slow_signal":bool(m.slow_signal_c.iloc[ni]),
            "baseline_native":float(m.native_close_target_b.iloc[ni]),
            "case_native":float(m.native_close_target_c.iloc[ni]),
        },
        "fractions":{"core":float(core.mean()),"native":float(native.mean()),"ex3":float(alloc.mean())},
    }
    assert witness["first_core_divergence"]=="2007-08-24"
    assert witness["last_session_excluded_security_in_baseline"]=="2007-11-12"
    assert witness["ordinary_trigger_crossing_baseline"]=="2010-04-16"
    assert witness["ordinary_trigger_crossing_case"]=="2010-04-27"
    assert witness["first_native_divergence"]=="2010-05-28"
    assert witness["first_ex3_allocation_divergence"]=="2010-06-01"
    assert witness["first_native_witness"]["holdings_equal"] is True
    assert witness["first_native_witness"]["baseline_slow_signal"] is True
    assert witness["first_native_witness"]["case_slow_signal"] is False

    ordinary=[]
    for p in (a.ordinary1,a.ordinary2):
        c=read_csv(p,"/engine/daily.csv"); mm,pp,qq,co,nn,aa=divergence(b,c)
        ordinary.append({"core_divergence_fraction":float(co.mean()),"native_divergence_fraction":float(nn.mean()),"allocation_divergence_fraction":float(aa.mean())})
    assert all(x["core_divergence_fraction"]>0 for x in ordinary)
    assert all(x["native_divergence_fraction"]==0 and x["allocation_divergence_fraction"]==0 for x in ordinary)

    out={"high_amplification_causal_chain":witness,"ordinary_path_diversity_controls":ordinary,
         "interpretation":"Core trajectory diversity can exist with zero Sentinel divergence; the high case reaches Native through Core NAV/high-water -> ordinary onset -> base duration -> slow trigger."}
    (a.out/"PRIOR-SLICE-TRACE.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps(out,indent=2,sort_keys=True))

if __name__=="__main__": main()
