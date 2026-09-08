#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

CONTROL_SOURCE_SHA256 = "bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077"
CONTROL_NORMALIZED_AST_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
ALLOWED_CAPITALS = (100_000.0, 1_000_000.0, 10_000_000.0)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, got {n}")
    return text.replace(old, new, 1)


def patch_source(v1: str, capital: float) -> str:
    if float(capital) not in ALLOWED_CAPITALS:
        raise ValueError(capital)
    cap = f"{float(capital):.1f}"
    out = v1
    # Only economic change: initial cash. Remaining changes are telemetry.
    out = replace_once(out,
        "    cash:float=100_000_000.; receivables:list=field(default_factory=list)",
        f"    cash:float={cap}; receivables:list=field(default_factory=list)",
        "initial capital")
    out = replace_once(out,
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; pending_intended_capital:float=0.; ready_day:int=0",
        "pending intended capital")
    out = replace_once(out,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; scale_entry_fraction_sum=0.0",
        "capital-scale counters")
    out = replace_once(out,
        "                            if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1\n                            else: s.pending_shares=float(round(q))",
        "                            if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.\n                            else: s.pending_shares=float(round(q))",
        "split pending reset")
    out = replace_once(out,
        "                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        "terminal pending reset")
    out = replace_once(out,
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "                    _planned_q=int(round(s.pending_shares)); afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(_planned_q,afford)\n                    if q>=1:\n                        _gross=float(q)*float(px)*(1+COST); _frac=(_gross/float(s.pending_intended_capital) if s.pending_intended_capital>0 else 0.0)\n                        scale_entries+=1; scale_one_share_entries+=int(q==1); scale_gap_clipped_entries+=int(q<_planned_q); scale_entry_fraction_sum+=_frac; scale_min_entry_fraction=min(scale_min_entry_fraction,_frac); scale_max_entry_fraction=max(scale_max_entry_fraction,_frac); scale_lt1+=int(_frac<0.01); scale_lt5+=int(_frac<0.05); scale_lt10+=int(_frac<0.10); scale_lt25+=int(_frac<0.25); scale_lt50+=int(_frac<0.50); scale_lt99+=int(_frac<0.99)\n                        book.cash-=_gross; s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        "fill telemetry")
    out = replace_once(out,
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "                        _desired=float(eq*ENTRY_W); target=min(_desired,book.cash); _funding_fraction=(float(target)/_desired if _desired>0 else 0.0); q=int(target//(float(px)*(1+COST)))\n                        if q<1: scale_q0_candidate_skips+=1; continue\n                        scale_cash_limited_decisions+=int(_funding_fraction<0.999999999)\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.pending_intended_capital=_desired; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "admission telemetry")
    out = replace_once(out,
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n        'wealth_core_capital_scale':{'initial_capital':float(" + cap + "),'entries':int(scale_entries),'q0_candidate_skips':int(scale_q0_candidate_skips),'one_share_entries':int(scale_one_share_entries),'cash_limited_decisions':int(scale_cash_limited_decisions),'gap_clipped_entries':int(scale_gap_clipped_entries),'entry_fraction_lt_1pct':int(scale_lt1),'entry_fraction_lt_5pct':int(scale_lt5),'entry_fraction_lt_10pct':int(scale_lt10),'entry_fraction_lt_25pct':int(scale_lt25),'entry_fraction_lt_50pct':int(scale_lt50),'entry_fraction_lt_99pct':int(scale_lt99),'minimum_entry_fraction':(float(scale_min_entry_fraction) if scale_entries else None),'maximum_entry_fraction':(float(scale_max_entry_fraction) if scale_entries else None),'average_entry_fraction':(float(scale_entry_fraction_sum/scale_entries) if scale_entries else None)},",
        "summary telemetry")
    compile(out, "<wealth-core-v1-capital-scale>", "exec")
    return out


def metrics(frame: pd.DataFrame) -> dict:
    nav = frame["shadow_equity"].astype(float)
    dates = pd.to_datetime(frame["date"])
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna(); vol = float(r.std(ddof=1))
    held = frame["held_count"].astype(float)
    return {"start":str(dates.iloc[0].date()),"end":str(dates.iloc[-1].date()),"sessions":int(len(frame)),"cagr":multiple**(1/years)-1,"ending_multiple":multiple,"max_drawdown":float((nav/nav.cummax()-1).min()),"sharpe_daily_252":float(r.mean()/vol*np.sqrt(252)) if vol>0 else None,"average_held_count":float(held.mean()),"median_held_count":float(held.median()),"full_slot_sessions":int((held>=25).sum())}


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--capital",required=True,type=float); ap.add_argument("--candidate-root",required=True,type=Path); ap.add_argument("--engine",required=True,type=Path); ap.add_argument("--output",required=True,type=Path); args=ap.parse_args()
    if args.capital not in ALLOWED_CAPITALS: raise RuntimeError(f"capital not preregistered: {args.capital}")
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install,assert_contract,assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast
    engine=args.engine.resolve(); output=args.output.resolve(); engine.mkdir(parents=True,exist_ok=True); output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(os.environ["CANONICAL_PIT_DATASET"])/"manifest.json").read_text())
    if manifest.get("dataset_hash")!=DATASET_SHA256: raise RuntimeError("canonical PIT dataset mismatch")
    _,_,prior=control.build_source(engine,args.candidate_root.resolve()); v1=install(prior); assert_contract(v1)
    if assert_one_session_dividend_lag(v1)!=1: raise RuntimeError("baseline dividend mismatch")
    if sha(v1.encode())!=CONTROL_SOURCE_SHA256: raise RuntimeError(f"V1 source mismatch: {sha(v1.encode())}")
    if sha(normalized_ast(v1).encode())!=CONTROL_NORMALIZED_AST_SHA256: raise RuntimeError("V1 AST mismatch")
    exp=patch_source(v1,args.capital); assert_contract(exp)
    if assert_one_session_dividend_lag(exp)!=1: raise RuntimeError("capital diagnostic changed dividend semantics")
    p=output/"wealth-core-v1-capital-scale-generated.py"; p.write_text(exp); subprocess.run([sys.executable,"-m","py_compile",str(p)],check=True)
    for stale in (engine/"daily.csv",engine/"summary.json"):
        if stale.exists(): stale.unlink()
    env=os.environ.copy(); env["RESEARCH_REPLAY_MODE"]="fullpit"; subprocess.run([sys.executable,str(p)],cwd=Path.cwd(),env=env,check=True)
    frame=pd.read_csv(engine/"daily.csv")
    if len(frame)!=5032 or str(frame.iloc[0]["date"])[:10]!="2006-07-31" or str(frame.iloc[-1]["date"])[:10]!="2026-07-31": raise RuntimeError("full-horizon witness mismatch")
    summary=json.loads((engine/"summary.json").read_text())
    if summary.get("canonical_pit_dataset_hash")!=DATASET_SHA256: raise RuntimeError("dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions")!=1: raise RuntimeError("dividend summary mismatch")
    telemetry=summary.get("wealth_core_capital_scale") or {}
    if abs(float(telemetry.get("initial_capital",-1))-args.capital)>1e-8: raise RuntimeError("capital telemetry mismatch")
    result={"schema":"research.wealth-core-v1-capital-scale/1","status":"PASS","economic_scope":"WEALTH_CORE_V1_ONLY","sentinel_metrics_used":False,"dataset_sha256":DATASET_SHA256,"initial_capital":args.capital,"metrics":metrics(frame),"telemetry":telemetry,"buys":int(summary["buys"]),"sells":int(summary["sells"]),"generated_source_sha256":sha(exp.encode()),"v1_source_sha256_before_capital_patch":CONTROL_SOURCE_SHA256}
    (output/"RESULT.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n"); shutil.copy2(engine/"daily.csv",output/"daily.csv"); shutil.copy2(engine/"summary.json",output/"summary.json"); print("[WEALTH_CORE_V1_CAPITAL_SCALE] "+json.dumps(result,sort_keys=True),flush=True); return 0

if __name__=="__main__": raise SystemExit(main())
