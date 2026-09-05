#!/usr/bin/env python3
"""Enforce the pre-registered Stage 6 dual-horizon modeled-hedge gate."""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
import pandas as pd


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for ch in iter(lambda:f.read(1024*1024),b''): h.update(ch)
    return h.hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    summary_path=a.output/'stage6_summary.json'
    s=json.loads(summary_path.read_text())
    m=pd.read_csv(a.output/'modeled_put_metrics.csv',dtype={'window':str})
    e=pd.read_csv(a.output/'modeled_put_target_episodes.csv')
    passed=[]
    for variant in sorted(m.variant.unique()):
        if not str(variant).endswith('__CONSERVATIVE'): continue
        mx=m[(m.variant==variant)&(m.window=='max')].iloc[0]
        w20=m[(m.variant==variant)&(m.window=='20')].iloc[0]
        positive=int((e[e.variant==variant].improvement>0).sum())
        gate=bool(
            float(mx.relative_maxdd_improvement)>=.20
            and float(w20.relative_maxdd_improvement)>=.20
            and float(mx.cagr_delta)>=-.01
            and float(w20.cagr_delta)>=-.01
            and positive>=2
        )
        s['variant_summaries'][variant]['model_gate']=gate
        s['variant_summaries'][variant]['positive_target_episode_improvements']=positive
        s['variant_summaries'][variant]['max']=mx.to_dict()
        s['variant_summaries'][variant]['20']=w20.to_dict()
        if gate: passed.append((variant,float(mx.relative_maxdd_improvement),float(w20.relative_maxdd_improvement),float(w20.cagr_delta)))
    passed.sort(key=lambda x:(min(x[1],x[2]),x[3]),reverse=True)
    s['model_gate_contract'].update({
        'required_relative_max_history_dd_improvement':.20,
        'required_20y_relative_maxdd_improvement':.20,
        'required_max_history_cagr_delta_min':-.01,
        'required_20y_cagr_delta_min':-.01,
        'required_positive_target_episode_improvements':2,
        'observed_options_validation_still_required_before_E8':True,
    })
    s['conservative_model_gate_passed']=bool(passed)
    s['best_conservative_candidate']=passed[0][0] if passed else None
    s['e8_gate']='CLOSED_PENDING_OBSERVED_2024_2026_VALIDATION' if passed else 'CLOSED_MODELED_ECONOMICS_NO_GO'
    s['strict_dual_horizon_gate_applied']=True
    summary_path.write_text(json.dumps(s,indent=2,sort_keys=True)+'\n')
    files=[a.output/'modeled_put_metrics.csv',a.output/'modeled_put_target_episodes.csv',a.output/'modeled_put_trade_ledger.csv',summary_path]+sorted(a.output.glob('curve_*.csv.gz'))
    (a.output/'STAGE6_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print(json.dumps({
        'strict_dual_horizon_gate_applied':True,
        'conservative_model_gate_passed':bool(passed),
        'best_conservative_candidate':s['best_conservative_candidate'],
        'e8_gate':s['e8_gate'],
    },indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
