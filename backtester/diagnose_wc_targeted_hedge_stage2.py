#!/usr/bin/env python3
"""Zero-budget targeted-hedge Stage 2: existing Sentinel event discrimination."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

LABEL="WC_TARGETED_HEDGE_STAGE2_SENTINEL_DISCRIMINATION_ZERO_BUDGET"
E3_HEAD="3f27834db427e71d9bb8d0b6160c8835b739c906"
E3_RUN_ID=33912976460
E3_ARTIFACT_ID=9953264982
E3_DIGEST="sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f"
BETA_HEAD="92e5d340858dae00909d9d459b539b7e76de8297"
BETA_RUN_ID=33976008320
BETA_ARTIFACT_ID=9972330512
PRIMARY=126
HORIZONS=(5,10,20,40,63)

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for ch in iter(lambda:f.read(1024*1024),b""): h.update(ch)
    return h.hexdigest()

def first_date(block,mask):
    q=block[mask]
    return "" if q.empty else str(pd.Timestamp(q.iloc[0].date).date())

def event_outcomes(x,mask,event_type):
    rows=[]
    for i in x.index[mask]:
        base_eq=float(x.at[i,"research_wealth_core_equity"]); base_spy=float(x.at[i,"spy_nav"])
        for h in HORIZONS:
            j=min(int(i)+h,int(x.index.max())); b=x.loc[int(i)+1:j]
            if b.empty: continue
            k=int(b["research_wealth_core_equity"].astype(float).idxmin())
            trough_eq=float(x.at[k,"research_wealth_core_equity"])
            covered=x.loc[int(i)+1:k].dropna(subset=[f"market_pnl_{PRIMARY}"])
            market=float(covered[f"market_pnl_{PRIMARY}"].sum()) if len(covered) else float("nan")
            actual=float(covered["wc_pnl"].sum()) if len(covered) else float("nan")
            share=market/actual if math.isfinite(market) and math.isfinite(actual) and actual<0 else float("nan")
            rows.append({
                "event_type":event_type,"signal_date":str(pd.Timestamp(x.at[i,"date"]).date()),"horizon_sessions":h,
                "wc_dd_at_signal":float(x.at[i,"wc_dd"]),"damaged_at_signal":float(x.at[i,"damaged"]),
                "green_at_signal":float(x.at[i,"green"]),
                "recent_r20_at_signal":float(x.at[i,"recent_r20"]) if pd.notna(x.at[i,"recent_r20"]) else np.nan,
                "recent_r40_at_signal":float(x.at[i,"recent_r40"]) if pd.notna(x.at[i,"recent_r40"]) else np.nan,
                "spy_r20_at_signal":float(x.at[i,"spy_r20"]) if pd.notna(x.at[i,"spy_r20"]) else np.nan,
                "native_close_target":float(x.at[i,"native_close_target"]),"research_allocation":float(x.at[i,"research_allocation"]),
                "control_reason":str(x.at[i,"control_reason"]),"future_wc_trough_date":str(pd.Timestamp(x.at[k,"date"]).date()),
                "future_wc_drawdown_from_signal":trough_eq/base_eq-1.0,"spy_return_to_wc_trough":float(x.at[k,"spy_nav"])/base_spy-1.0,
                "prior_beta_market_share_of_covered_loss":share,
                "broad_index_hedge_directionally_helpful":bool(math.isfinite(market) and market<0),
            })
    return rows

def episode_profiles(daily,attrs):
    out=[]
    for e in attrs.head(15).itertuples(index=False):
        peak=pd.Timestamp(e.peak_date); trough=pd.Timestamp(e.trough_date)
        b=daily[(daily.date>=peak)&(daily.date<=trough)].copy()
        if b.empty: continue
        peak_eq=float(b.iloc[0].research_wealth_core_equity); b["episode_dd"]=b.research_wealth_core_equity.astype(float)/peak_eq-1.0
        s=float(getattr(e,"market_share_of_covered_loss_126"))
        row={"rank":int(e.rank),"peak_date":e.peak_date,"trough_date":e.trough_date,"wc_drawdown":float(e.drawdown),
             "market_share_of_covered_loss_126":s,
             "economic_class":"MARKET_DOMINANT" if s>=2/3 else "RESIDUAL_DOMINANT" if s<1/3 else "MIXED",
             "first_fast_signal":first_date(b,b.fast_signal.astype(bool)),"first_slow_signal":first_date(b,b.slow_signal.astype(bool)),
             "first_native_severe":first_date(b,b.native_close_target.astype(float)<=1e-12),
             "first_ldrc_divergence":first_date(b,b.control_reason.astype(str).str.contains("LD_ENTER_DIVERGENCE",regex=False))}
        for depth in (-.05,-.10,-.15):
            hit=b[b.episode_dd<=depth]; tag=f"at_{int(abs(depth)*100)}pct"
            if hit.empty: row[f"{tag}_date"]=""; continue
            z=hit.iloc[0]
            row.update({f"{tag}_date":str(pd.Timestamp(z.date).date()),f"{tag}_damaged":float(z.damaged),f"{tag}_green":float(z.green),
                        f"{tag}_recent_r20":float(z.recent_r20) if pd.notna(z.recent_r20) else np.nan,
                        f"{tag}_recent_r40":float(z.recent_r40) if pd.notna(z.recent_r40) else np.nan,
                        f"{tag}_spy_r20":float(z.spy_r20) if pd.notna(z.spy_r20) else np.nan,f"{tag}_native_target":float(z.native_close_target)})
        out.append(row)
    return pd.DataFrame(out)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--accepted-root",type=Path,required=True); ap.add_argument("--beta-root",type=Path,required=True); ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    daily=pd.read_csv(a.accepted_root/"daily.csv.gz",compression="gzip",parse_dates=["date"])
    bd=pd.read_csv(a.beta_root/"wc_daily_beta_decomposition.csv.gz",compression="gzip",parse_dates=["date"])
    attrs=pd.read_csv(a.beta_root/"wc_drawdown_beta_attribution.csv")
    required={"date","research_wealth_core_equity","wc_dd","damaged","green","recent_r20","recent_r40","spy_r20","native_close_target","research_allocation","spy_nav","control_reason","fast_signal","slow_signal"}
    miss=required-set(daily.columns)
    if miss: raise RuntimeError(f"accepted E3 missing columns {sorted(miss)}")
    x=daily.merge(bd[["date","wc_pnl",f"market_pnl_{PRIMARY}",f"residual_pnl_{PRIMARY}"]],on="date",how="left").sort_values("date",kind="mergesort").reset_index(drop=True)
    masks={
      "NATIVE_SEVERE_ONSET":(x.native_close_target.astype(float)<=1e-12)&(x.native_close_target.shift(fill_value=1).astype(float)>1e-12),
      "FAST_SIGNAL_ONSET":x.fast_signal.astype(bool)&~x.fast_signal.shift(fill_value=False).astype(bool),
      "SLOW_SIGNAL_ONSET":x.slow_signal.astype(bool)&~x.slow_signal.shift(fill_value=False).astype(bool),
      "LDRC_DIVERGENCE_ENTRY":x.control_reason.astype(str).str.contains("LD_ENTER_DIVERGENCE",regex=False)}
    events=[]
    for name,mask in masks.items(): events.extend(event_outcomes(x,mask,name))
    ev=pd.DataFrame(events); ev.to_csv(a.output/"sentinel_event_prospective_outcomes.csv",index=False)
    prof=episode_profiles(daily,attrs); prof.to_csv(a.output/"major_drawdown_sentinel_profiles.csv",index=False)
    market=prof[prof.economic_class.eq("MARKET_DOMINANT")]; residual=prof[prof.economic_class.eq("RESIDUAL_DOMINANT")]
    caught_market=int((market.first_native_severe!="").sum()); caught_residual=int((residual.first_native_severe!="").sum())
    required_peaks={"2020-02-18","2011-07-07","2025-02-14"}; req=prof[prof.peak_date.astype(str).isin(required_peaks)]
    required_coverage={str(r.peak_date):bool(r.first_native_severe) for r in req.itertuples(index=False)}
    current_gate=(len(market)>0 and caught_market==len(market) and caught_residual==0 and all(required_coverage.get(p,False) for p in required_peaks))
    e63=ev[ev.horizon_sessions.eq(63)]; agg=[]
    for name,g in e63.groupby("event_type",sort=True):
        shares=g.prior_beta_market_share_of_covered_loss.replace([np.inf,-np.inf],np.nan).dropna()
        agg.append({"event_type":name,"activations":int(len(g)),"median_future_wc_drawdown":float(g.future_wc_drawdown_from_signal.median()),
                    "median_spy_return_to_wc_trough":float(g.spy_return_to_wc_trough.median()),"median_market_share":float(shares.median()) if len(shares) else None,
                    "directionally_helpful_fraction":float(g.broad_index_hedge_directionally_helpful.mean()) if len(g) else None})
    aggregate=pd.DataFrame(agg); aggregate.to_csv(a.output/"sentinel_event_aggregate.csv",index=False)
    summary={"status":"PASS","label":LABEL,"zero_budget_diagnostic":True,"strategy_mechanics_changed":False,"experiment_budget_consumed":False,
      "accepted_e3":{"head":E3_HEAD,"run_id":E3_RUN_ID,"artifact_id":E3_ARTIFACT_ID,"digest":E3_DIGEST},
      "prior_beta_diagnostic":{"head":BETA_HEAD,"run_id":BETA_RUN_ID,"artifact_id":BETA_ARTIFACT_ID,"window_sessions":PRIMARY},
      "top15_drawdown_class_rule":{"market_dominant":"market share >= 2/3","mixed":"1/3 <= market share < 2/3","residual_dominant":"market share < 1/3","purpose":"descriptive only; not a production threshold"},
      "native_severe_discrimination":{"market_dominant_episodes":int(len(market)),"market_dominant_caught":caught_market,"residual_dominant_episodes":int(len(residual)),"residual_dominant_caught":caught_residual,"required_episode_coverage":required_coverage,"gate_pass":bool(current_gate)},
      "conclusion":"CURRENT_SENTINEL_EVENT_GO_FOR_HEDGE_TRIGGER" if current_gate else "CURRENT_SENTINEL_EVENT_NO_GO_FOR_HEDGE_TRIGGER",
      "interpretation_contract":{"future_outcomes_used_only_for_diagnostic_labels":True,"future_outcomes_used_to_construct_existing_events":False,"existing_event_definitions_changed":False,"actual_option_strategy_tested":False,"e8_spent":False}}
    (a.output/"stage2_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    files=[a.output/"sentinel_event_prospective_outcomes.csv",a.output/"major_drawdown_sentinel_profiles.csv",a.output/"sentinel_event_aggregate.csv",a.output/"stage2_summary.json"]
    (a.output/"STAGE2_SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print(json.dumps(summary,indent=2,sort_keys=True)); print(aggregate.to_string(index=False)); print(prof[["rank","peak_date","trough_date","wc_drawdown","market_share_of_covered_loss_126","economic_class","first_native_severe","first_ldrc_divergence"]].to_string(index=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
