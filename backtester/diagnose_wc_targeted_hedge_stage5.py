#!/usr/bin/env python3
"""Zero-budget Stage 5: causal systemic-concordance episode trigger diagnostic.

The trigger uses only thresholds/sign conditions already present in accepted E3
Sentinel/LD-RC mechanics. It changes no strategy mechanics and consumes no
experiment budget.

Trigger at close:
    wc_dd <= -10%                  (LDRC_DD)
    green <= 25%                   (SLOW green threshold)
    SPY r20 <= -1%                 (FAST SPY threshold)
    recent leadership r20 < 0      (existing recovery-sign surface)
    recent leadership r40 <= -3%   (SLOW r40 threshold)

Once triggered, the insurance episode is latched. It is re-armed only by the
existing LD-RC recovery condition:
    7 consecutive sessions with recent_r20>0 AND recent_r40>0
    OR SPY r20 > +11%.

This script only diagnoses trigger timing/frequency. It does not price or trade
options.
"""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

LABEL = "WC_TARGETED_HEDGE_STAGE5_SYSTEMIC_CONCORDANCE_ZERO_BUDGET"
E3_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
E3_RUN_ID = 33912976460
E3_ARTIFACT_ID = 9953264982
E3_DIGEST = "sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f"
BETA_HEAD = "92e5d340858dae00909d9d459b539b7e76de8297"
BETA_RUN_ID = 33976008320
BETA_ARTIFACT_ID = 9972330512
MEASUREMENT_START = pd.Timestamp("1998-01-02")

TARGETS = {
    "2011": ("2011-07-07", "2011-10-03"),
    "2020": ("2020-02-18", "2020-03-23"),
    "2024_JULAUG": ("2024-07-15", "2024-08-05"),
    "2025": ("2025-02-14", "2025-04-08"),
}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for ch in iter(lambda:f.read(1024*1024),b""): h.update(ch)
    return h.hexdigest()


def trigger_mask(d: pd.DataFrame) -> pd.Series:
    return (
        (d.wc_dd.astype(float) <= -.10)
        & (d.green.astype(float) <= .25)
        & (d.spy_r20.astype(float) <= -.01)
        & (d.recent_r20.astype(float) < 0.)
        & (d.recent_r40.astype(float) <= -.03)
    )


def build_episodes(d: pd.DataFrame) -> pd.DataFrame:
    trig=trigger_mask(d)
    active=False
    healthy_streak=0
    rows=[]
    for i,r in d.iterrows():
        r20=float(r.recent_r20) if pd.notna(r.recent_r20) else np.nan
        r40=float(r.recent_r40) if pd.notna(r.recent_r40) else np.nan
        spy20=float(r.spy_r20) if pd.notna(r.spy_r20) else np.nan
        healthy=np.isfinite(r20) and np.isfinite(r40) and r20>0 and r40>0
        healthy_streak=healthy_streak+1 if healthy else 0
        recovery=(healthy_streak>=7) or (np.isfinite(spy20) and spy20>.11)
        if active and recovery:
            rows[-1]["release_date"]=str(pd.Timestamp(r.date).date())
            rows[-1]["release_index"]=int(i)
            rows[-1]["sessions"]=int(i-rows[-1]["trigger_index"]+1)
            rows[-1]["release_reason"]="LDRC_7_SESSION_HEALTHY" if healthy_streak>=7 else "SPY_V_REBOUND"
            active=False
        if (not active) and bool(trig.loc[i]):
            active=True
            rows.append({
                "episode":len(rows)+1,
                "trigger_date":str(pd.Timestamp(r.date).date()),
                "trigger_index":int(i),
                "release_date":"",
                "release_index":-1,
                "sessions":0,
                "release_reason":"",
                "wc_dd_at_trigger":float(r.wc_dd),
                "damaged_at_trigger":float(r.damaged),
                "green_at_trigger":float(r.green),
                "recent_r20_at_trigger":float(r.recent_r20),
                "recent_r40_at_trigger":float(r.recent_r40),
                "spy_r20_at_trigger":float(r.spy_r20),
                "native_target_at_trigger":float(r.native_close_target),
            })
    if active:
        rows[-1]["release_date"]=str(pd.Timestamp(d.iloc[-1].date).date())
        rows[-1]["release_index"]=int(d.index[-1])
        rows[-1]["sessions"]=int(d.index[-1]-rows[-1]["trigger_index"]+1)
        rows[-1]["release_reason"]="END_OF_SAMPLE"
    return pd.DataFrame(rows)


def target_timing(d: pd.DataFrame, eps: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for label,(p0,t0) in TARGETS.items():
        p=pd.Timestamp(p0); t=pd.Timestamp(t0)
        b=d[(d.date>=p)&(d.date<=t)].copy().reset_index(drop=True)
        q=eps[(pd.to_datetime(eps.trigger_date)>=p)&(pd.to_datetime(eps.trigger_date)<=t)].copy()
        caught=not q.empty
        row={"target":label,"peak_date":p0,"trough_date":t0,"caught":bool(caught)}
        if caught:
            td=pd.Timestamp(q.iloc[0].trigger_date)
            tr=b[b.date.eq(td)].iloc[0]
            peak_eq=float(b.iloc[0].research_wealth_core_equity)
            trough_eq=float(b.iloc[-1].research_wealth_core_equity)
            trig_eq=float(tr.research_wealth_core_equity)
            total_loss=max(peak_eq-trough_eq,0.0)
            remaining=max(trig_eq-trough_eq,0.0)
            row.update({
                "trigger_date":str(td.date()),
                "sessions_from_peak":int(b.index[b.date.eq(td)][0]),
                "calendar_days_from_peak":int((td-p).days),
                "wc_dd_at_trigger":float(tr.wc_dd),
                "total_peak_to_trough_loss_fraction":float((peak_eq-trough_eq)/peak_eq),
                "remaining_loss_fraction_of_peak_at_trigger":float(remaining/peak_eq),
                "remaining_fraction_of_episode_loss":float(remaining/total_loss) if total_loss>0 else np.nan,
                "spy_r20_at_trigger":float(tr.spy_r20),
            })
        else:
            row.update({"trigger_date":"","sessions_from_peak":np.nan,"calendar_days_from_peak":np.nan,
                        "wc_dd_at_trigger":np.nan,"total_peak_to_trough_loss_fraction":np.nan,
                        "remaining_loss_fraction_of_peak_at_trigger":np.nan,
                        "remaining_fraction_of_episode_loss":np.nan,"spy_r20_at_trigger":np.nan})
        rows.append(row)
    return pd.DataFrame(rows)


def top15_mapping(eps: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for e in attrs.head(15).itertuples(index=False):
        p=pd.Timestamp(e.peak_date); t=pd.Timestamp(e.trough_date)
        q=eps[(pd.to_datetime(eps.trigger_date)>=p)&(pd.to_datetime(eps.trigger_date)<=t)]
        share=float(e.market_share_of_covered_loss_126)
        cls="MARKET_DOMINANT" if share>=2/3 else ("RESIDUAL_DOMINANT" if share<1/3 else "MIXED")
        rows.append({
            "rank":int(e.rank),"peak_date":e.peak_date,"trough_date":e.trough_date,
            "drawdown":float(e.drawdown),"market_share_126":share,"economic_class":cls,
            "triggered":bool(not q.empty),"first_trigger_date":"" if q.empty else str(q.iloc[0].trigger_date),
            "trigger_count_inside_episode":int(len(q)),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--accepted-root",type=Path,required=True)
    ap.add_argument("--beta-root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)

    d=pd.read_csv(a.accepted_root/"daily.csv.gz",compression="gzip",parse_dates=["date"]).sort_values("date",kind="mergesort").reset_index(drop=True)
    d=d[d.date>=MEASUREMENT_START].copy().reset_index(drop=True)
    required={"date","research_wealth_core_equity","wc_dd","damaged","green","recent_r20","recent_r40","spy_r20","native_close_target"}
    miss=required-set(d.columns)
    if miss: raise RuntimeError(f"accepted E3 missing {sorted(miss)}")
    attrs=pd.read_csv(a.beta_root/"wc_drawdown_beta_attribution.csv")

    eps=build_episodes(d); eps.to_csv(a.output/"systemic_concordance_episodes.csv",index=False)
    timing=target_timing(d,eps); timing.to_csv(a.output/"target_episode_timing.csv",index=False)
    top=top15_mapping(eps,attrs); top.to_csv(a.output/"top15_trigger_mapping.csv",index=False)

    elapsed=(d.date.iloc[-1]-d.date.iloc[0]).days/365.2425
    target_all=bool(timing.caught.all())
    remaining_positive=bool((timing.loc[timing.caught,"remaining_loss_fraction_of_peak_at_trigger"]>0).all())
    residual=top[top.economic_class.eq("RESIDUAL_DOMINANT")]
    market=top[top.economic_class.eq("MARKET_DOMINANT")]

    report={
        "status":"PASS",
        "label":LABEL,
        "zero_budget_diagnostic":True,
        "strategy_mechanics_changed":False,
        "experiment_budget_consumed":False,
        "e8_spent":False,
        "accepted_e3":{"head":E3_HEAD,"run_id":E3_RUN_ID,"artifact_id":E3_ARTIFACT_ID,"digest":E3_DIGEST},
        "prior_beta":{"head":BETA_HEAD,"run_id":BETA_RUN_ID,"artifact_id":BETA_ARTIFACT_ID},
        "trigger_contract":{
            "decision_time":"session close; any hedge execution would occur no earlier than next open",
            "entry":"wc_dd<=-10% AND green<=25% AND SPY_r20<=-1% AND recent_leadership_r20<0 AND recent_leadership_r40<=-3%",
            "threshold_origin":"all numeric thresholds/sign surfaces already exist in accepted E3 Sentinel/LD-RC mechanics",
            "rearm":"existing LD-RC recovery: 7 consecutive r20/r40 positive sessions OR SPY_r20>+11%",
            "new_fitted_numeric_thresholds":0,
        },
        "episode_statistics":{
            "episodes":int(len(eps)),
            "years":float(elapsed),
            "episodes_per_year":float(len(eps)/elapsed),
            "median_sessions":float(eps.sessions.median()),
            "p90_sessions":float(eps.sessions.quantile(.9)),
            "max_sessions":int(eps.sessions.max()),
        },
        "target_coverage":{
            "all_four_caught_before_or_at_trough":target_all,
            "all_four_have_positive_remaining_loss_after_trigger":remaining_positive,
            "pricing_diagnostic_gate":bool(target_all and remaining_positive),
        },
        "top15_mapping":{
            "market_dominant_episodes":int(len(market)),
            "market_dominant_triggered":int(market.triggered.sum()),
            "residual_dominant_episodes":int(len(residual)),
            "residual_dominant_triggered":int(residual.triggered.sum()),
        },
        "interpretation_contract":{
            "future_outcomes_used_to_construct_trigger":False,
            "future_outcomes_used_only_to_score_trigger":True,
            "option_prices_used":False,
            "hedge_pnl_tested":False,
            "pricing_diagnostic_may_proceed":bool(target_all and remaining_positive),
        }
    }
    (a.output/"stage5_summary.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    files=[a.output/"systemic_concordance_episodes.csv",a.output/"target_episode_timing.csv",a.output/"top15_trigger_mapping.csv",a.output/"stage5_summary.json"]
    (a.output/"STAGE5_SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print(json.dumps(report,indent=2,sort_keys=True))
    print(timing.to_string(index=False))
    print(eps.to_string(index=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
