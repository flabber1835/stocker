#!/usr/bin/env python3
"""Zero-budget targeted-hedge Stage 4: exact Wealth Core natural-cash telemetry.

Runs the accepted E3 chronology with telemetry-only additions. No strategy decision,
allocation, admission, exit, or Sentinel mechanic is changed.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
from backtester import experiment_architecture_recovery_concordance_e3 as e3

LABEL="WC_TARGETED_HEDGE_STAGE4_NATURAL_CASH_ZERO_BUDGET"
THRESHOLDS=(0.0025,0.005,0.01,0.02,0.04)


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for ch in iter(lambda:f.read(1024*1024),b''): h.update(ch)
    return h.hexdigest()


def telemetry_source(output: Path) -> str:
    text=e3.transformed_source(output)
    old="""rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'damaged':dam_b,'green':green_b,"""
    new="""_pending_buy_est=sum(float(s.pending_shares)*float(clraw[s.pending_tid])*(1+COST) for s in book.slots if s.reserved() and finite(clraw[s.pending_tid]) and clraw[s.pending_tid]>0)\n                _next_open_receivables=sum(float(a) for dd,a in book.receivables if dd<=gday+1)\n                _next_open_cash=float(book.cash)+_next_open_receivables\n                rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_cash_on_hand':float(book.cash),'wc_receivables':sum(float(a) for _,a in book.receivables),'wc_next_open_receivables':_next_open_receivables,'wc_pending_buy_estimate':_pending_buy_est,'wc_cash_fraction':float(book.cash)/eq if eq>0 else np.nan,'wc_unreserved_cash_fraction':max(float(book.cash)-_pending_buy_est,0.0)/eq if eq>0 else np.nan,'wc_next_open_cash_fraction':_next_open_cash/eq if eq>0 else np.nan,'wc_next_open_unreserved_cash_fraction':max(_next_open_cash-_pending_buy_est,0.0)/eq if eq>0 else np.nan,'wc_dd':dd,'damaged':dam_b,'green':green_b,"""
    if text.count(old)!=1:
        raise RuntimeError(f'cash telemetry seam count={text.count(old)}')
    text=text.replace(old,new,1)
    return text


def pct(x,q):
    return float(pd.Series(x).quantile(q))


def summarize_cash(daily: pd.DataFrame) -> dict:
    cols=['wc_cash_fraction','wc_unreserved_cash_fraction','wc_next_open_cash_fraction','wc_next_open_unreserved_cash_fraction']
    out={}
    for c in cols:
        s=daily[c].astype(float).replace([np.inf,-np.inf],np.nan).dropna()
        out[c]={
            'min':float(s.min()),'p05':pct(s,.05),'p10':pct(s,.10),'p25':pct(s,.25),
            'median':pct(s,.5),'mean':float(s.mean()),'p75':pct(s,.75),'p90':pct(s,.90),'max':float(s.max()),
            'availability':{f'{t:.4f}':float((s>=t).mean()) for t in THRESHOLDS},
        }
    return out


def onset(mask: pd.Series) -> pd.Series:
    return mask.fillna(False) & ~mask.fillna(False).shift(fill_value=False)


def signal_cash_rows(d: pd.DataFrame) -> pd.DataFrame:
    masks={
        'NATIVE_SEVERE_ONSET':onset(d.native_close_target.astype(float)<=1e-12),
        'FAST_SIGNAL_ONSET':onset(d.fast_signal.astype(bool)),
        'SLOW_SIGNAL_ONSET':onset(d.slow_signal.astype(bool)),
        'LDRC_DIVERGENCE_ENTRY':d.control_reason.astype(str).str.contains('LD_ENTER_DIVERGENCE',regex=False),
    }
    # Existing-threshold concordance witness. Descriptive only; it is not an E8 trigger.
    witness=(d.wc_dd.astype(float)<=-.10)&(d.green.astype(float)<=.25)&(d.spy_r20.astype(float)<=-.01)&(d.recent_r20.astype(float)<0)&(d.recent_r40.astype(float)<=-.03)
    masks['SYSTEMIC_CONCORDANCE_DIAGNOSTIC_ONSET']=onset(witness)
    rows=[]
    for name,m in masks.items():
        for r in d[m].itertuples(index=False):
            rows.append({
                'signal_type':name,'date':str(pd.Timestamp(r.date).date()),'wc_dd':float(r.wc_dd),
                'wc_cash_fraction':float(r.wc_cash_fraction),'wc_unreserved_cash_fraction':float(r.wc_unreserved_cash_fraction),
                'wc_next_open_cash_fraction':float(r.wc_next_open_cash_fraction),'wc_next_open_unreserved_cash_fraction':float(r.wc_next_open_unreserved_cash_fraction),
                'wc_pending_buy_estimate_fraction':float(r.wc_pending_buy_estimate)/float(r.research_wealth_core_equity),
            })
    return pd.DataFrame(rows)


def drawdown_cash(d: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for e in attrs.head(15).itertuples(index=False):
        b=d[(d.date>=pd.Timestamp(e.peak_date))&(d.date<=pd.Timestamp(e.trough_date))]
        if b.empty: continue
        for label,mask in (
            ('PEAK',b.date.eq(pd.Timestamp(e.peak_date))),
            ('TROUGH',b.date.eq(pd.Timestamp(e.trough_date))),
            ('FIRST_10PCT_DD',b.wc_dd.astype(float)<=-.10),
        ):
            q=b[mask]
            if q.empty: continue
            r=q.iloc[0]
            rows.append({'rank':int(e.rank),'peak_date':e.peak_date,'trough_date':e.trough_date,'drawdown':float(e.drawdown),'point':label,'date':str(pd.Timestamp(r.date).date()),'wc_dd':float(r.wc_dd),'wc_cash_fraction':float(r.wc_cash_fraction),'wc_unreserved_cash_fraction':float(r.wc_unreserved_cash_fraction),'wc_next_open_cash_fraction':float(r.wc_next_open_cash_fraction),'wc_next_open_unreserved_cash_fraction':float(r.wc_next_open_unreserved_cash_fraction)})
    return pd.DataFrame(rows)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--beta-root',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/strategy9_e3_cash_telemetry.py'); generated.write_text(telemetry_source(a.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'
    print(f'[RUN] {LABEL} telemetry_only=true experiment_budget=7/10',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    e3.finalize(a.output)
    daily=pd.read_csv(a.output/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    required={'wc_cash_on_hand','wc_receivables','wc_next_open_receivables','wc_pending_buy_estimate','wc_cash_fraction','wc_unreserved_cash_fraction','wc_next_open_cash_fraction','wc_next_open_unreserved_cash_fraction'}
    miss=required-set(daily.columns)
    if miss: raise RuntimeError(f'cash telemetry missing {sorted(miss)}')
    attrs=pd.read_csv(a.beta_root/'wc_drawdown_beta_attribution.csv')
    signals=signal_cash_rows(daily); signals.to_csv(a.output/'cash_at_sentinel_signals.csv',index=False)
    dd=drawdown_cash(daily,attrs); dd.to_csv(a.output/'cash_at_major_drawdowns.csv',index=False)
    stats=summarize_cash(daily)
    summary=json.loads((a.output/'summary.json').read_text())
    if summary['control_parity']['status']!='PASS': raise RuntimeError(f"E3 control parity failed: {summary['control_parity']}")
    bysig={}
    for name,g in signals.groupby('signal_type',sort=True):
        bysig[name]={'count':int(len(g)),'median_next_open_cash_fraction':float(g.wc_next_open_cash_fraction.median()),'median_next_open_unreserved_cash_fraction':float(g.wc_next_open_unreserved_cash_fraction.median()),'fraction_with_0p5pct_next_open_cash':float((g.wc_next_open_cash_fraction>=.005).mean()),'fraction_with_1pct_next_open_cash':float((g.wc_next_open_cash_fraction>=.01).mean()),'fraction_with_2pct_next_open_cash':float((g.wc_next_open_cash_fraction>=.02).mean())}
    report={'status':'PASS','label':LABEL,'zero_budget_diagnostic':True,'strategy_mechanics_changed':False,'experiment_budget_consumed':False,'e8_spent':False,'accepted_e3_control_parity':summary['control_parity'],'cash_definition':{'cash_on_hand':'Book.cash at signal close after current-session open executions and before next-session execution','unreserved_cash':'cash on hand minus estimated notional of pending Wealth Core admission','next_open_cash':'cash on hand plus receivables due by next session open','pending_admission_policy_for_diagnostic':'reported both preserving and redirecting pending-admission cash; no admission was actually changed'},'all_session_cash_statistics':stats,'signal_cash_statistics':bysig}
    (a.output/'stage4_cash_summary.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    files=[a.output/'daily.csv.gz',a.output/'cash_at_sentinel_signals.csv',a.output/'cash_at_major_drawdowns.csv',a.output/'stage4_cash_summary.json']
    (a.output/'STAGE4_CASH_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files),encoding='utf-8')
    print(json.dumps(report,indent=2,sort_keys=True),flush=True)
    print(signals.to_string(index=False),flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
