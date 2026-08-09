#!/usr/bin/env python3
"""Validation-only comparator. Not imported by the strategy runtime."""
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--daily',type=Path,required=True,help='fresh standalone sentinel_1p1_daily.csv')
    ap.add_argument('--frozen',type=Path,required=True,help='frozen 03_exact_candidate_daily.csv')
    a=ap.parse_args()
    raw=pd.read_csv(a.daily,parse_dates=['date'])
    ref=pd.read_csv(a.frozen,parse_dates=['date'])
    m=raw.merge(ref,on='date',suffixes=('_raw','_ref'),validate='one_to_one')
    alloc=np.abs(m.allocation.to_numpy(float)-m.candidate_alloc.to_numpy(float))
    # raw parent_allocation is the target decided at this close for the next open.
    parent_eff=np.r_[1.0,m.parent_allocation.to_numpy(float)[:-1]]
    p=np.abs(parent_eff-m.canonical_alloc.to_numpy(float))
    sr=(m.shadow_equity/m.wealth_core_nav); sr=sr/sr.iloc[0]-1
    nr=m.nav/m.candidate_nav-1
    result={
        'sessions':len(m),
        'candidate_allocation_mismatches':int(np.sum(alloc>1e-12)),
        'parent_effective_allocation_mismatches':int(np.sum(p>1e-12)),
        'damaged_mismatches':int(np.sum(np.abs(m.damaged_raw-m.damaged_ref)>1e-12)),
        'green_mismatches':int(np.sum(np.abs(m.green_raw-m.green_ref)>1e-12)),
        'shadow_max_normalized_relative_error':float(np.max(np.abs(sr))),
        'nav_max_relative_difference':float(np.max(np.abs(nr))),
        'nav_ending_relative_difference':float(nr.iloc[-1]),
    }
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
