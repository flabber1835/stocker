#!/usr/bin/env python3
"""Frozen R1000 + causal correlation-peer research replay.

This is a domain-translation experiment over the retained LD-RC strategy. It
changes only:
  * candidate/leadership eligibility -> strict-prior historical IWB/R1000 proxy;
  * issuer-family blocking -> independent security ids;
  * sector contagion -> prior-only residual-correlation peer contagion.

All Wealth Core ranking, sizing, exit, native Sentinel and LD-RC parameters are
left at the retained research source values.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd

from backtester import run_research_ldrc_corrected_warmup_cash as base

EVIDENCE_LABEL = "BEST_EFFORT_PIT_R1000_CORRELATION_PEERS"
STARTING_EQUITY = 100_000_000.0
STANDARD_WINDOWS = {
    "5": ("2021-07-30", 5.0),
    "10": ("2016-07-29", 10.0),
    "15": ("2011-07-29", 15.0),
    "20": ("2006-07-31", 20.0),
}


def replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return out


def transformed_source(output: Path) -> str:
    text = base.transformed_source("fullpit", output)

    text = base.old.replace_once(
        text,
        "import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util",
        "import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util, bisect",
        "R1000 bisect import",
    )

    text = base.old.replace_once(
        text,
        "TOP = 0.10",
        """TOP = 0.10

R1000_PATH=Path(os.environ['R1000_MEMBERSHIP_SNAPSHOTS'])
_r1000=pd.read_csv(R1000_PATH,compression='gzip',usecols=['as_of_date','ticker'],low_memory=False)
_r1000['as_of_date']=_r1000['as_of_date'].astype(str).str[:10]
_R1000_BY_DATE={d:frozenset(g.ticker.astype(str).str.upper()) for d,g in _r1000.groupby('as_of_date',sort=True)}
_R1000_DATES=sorted(_R1000_BY_DATE)
if not _R1000_DATES: raise RuntimeError('R1000 membership snapshots are empty')

def r1000_membership(ds):
    # Strict-prior: a holdings snapshot stamped t can influence decisions only after t.
    i=bisect.bisect_left(_R1000_DATES,str(ds))-1
    return frozenset() if i<0 else _R1000_BY_DATE[_R1000_DATES[i]]

PEER_LOOKBACK=252
PEER_MIN_OBS=120
PEER_COUNT=3
PEER_CORR_FLOOR=.145
PEER_STATS={'breadth_sessions':0,'holding_observations':0,'insufficient_residual_histories':0,'pair_correlations':0,'accepted_peer_edges':0,'neighborhood_size_sum':0}
""",
        "R1000 membership loader",
    )

    # Keep PIT ACTIONS, but remove SEC CIK/SIC from the strategy domain. Every
    # security is its own issuer family and sector taxonomy is irrelevant.
    init_pattern = (
        r"    pit_model=None\n"
        r"    if PIT_MODE:.*?"
        r"    actions,split_dates=load_actions\(\); spy,bil=load_funds\(\); book=Book\(\); native=Native\(\)"
    )
    init_replacement = """    def sector_key(tid, ds):
        return f'SID:{sid[tid]}'
    def issuer_key(tid, ds):
        return f'SID:{sid[tid]}'
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"""
    text = replace_regex(text, init_pattern, init_replacement, "remove SEC metadata authority")

    text = base.old.replace_once(
        text,
        "def finite(x): return x is not None and np.isfinite(x)",
        """def finite(x): return x is not None and np.isfinite(x)

def _peer_corr(left,right):
    common=sorted(set(left).intersection(right))
    if len(common)<PEER_MIN_OBS: return None
    a=np.array([left[k] for k in common],float); b=np.array([right[k] for k in common],float)
    am=float(a.mean()); bm=float(b.mean()); da=a-am; db=b-bm
    den=float(np.sqrt(np.dot(da,da)*np.dot(db,db)))
    if not np.isfinite(den) or den<=0: return None
    out=float(np.dot(da,db)/den)
    return out if np.isfinite(out) else None

def _prior_residuals(tid,gday,close_ring,spy,shadow_dates):
    # Returns are indexed by their endpoint global session j and end at t-1.
    start=max(1,gday-PEER_LOOKBACK); end=gday-1
    keys=[]; asset=[]; market=[]
    for j in range(start,end+1):
        if j>=len(shadow_dates): break
        p0=float(close_ring[(j-1)%len(close_ring),tid]); p1=float(close_ring[j%len(close_ring),tid])
        date=shadow_dates[j]
        mv=spy.loc[date,'ret'] if date in spy.index else np.nan
        if finite(p0) and p0>0 and finite(p1) and p1>0 and finite(mv):
            keys.append(j); asset.append(p1/p0-1.); market.append(float(mv))
    if len(keys)<PEER_MIN_OBS:
        PEER_STATS['insufficient_residual_histories']+=1
        return {}
    a=np.array(asset,float); m=np.array(market,float)
    am=float(a.mean()); mm=float(m.mean()); dm=m-mm
    den=float(np.dot(dm,dm))
    if not np.isfinite(den) or den<=0:
        PEER_STATS['insufficient_residual_histories']+=1
        return {}
    beta=float(np.dot(a-am,dm)/den)
    return {k:float(x-beta*y) for k,x,y in zip(keys,a,m)}

def dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates):
    if not held: return 0.,0.
    PEER_STATS['breadth_sessions']+=1; PEER_STATS['holding_observations']+=len(held)
    residuals=[_prior_residuals(int(z[0]),gday,close_ring,spy,shadow_dates) for z in held]
    reds=[bool(z[7]) for z in held]; greens=[bool(z[6]) for z in held]
    ng=na=0
    for i,z in enumerate(held):
        scores=[]; left=residuals[i]
        if left:
            for j,right in enumerate(residuals):
                if i==j or not right: continue
                c=_peer_corr(left,right); PEER_STATS['pair_correlations']+=1
                if c is not None and c>=PEER_CORR_FLOOR: scores.append((float(c),int(held[j][0]),j))
        scores.sort(key=lambda row:(-row[0],row[1]))
        neighbors=[i]+[row[2] for row in scores[:PEER_COUNT]]
        PEER_STATS['accepted_peer_edges']+=max(len(neighbors)-1,0)
        PEER_STATS['neighborhood_size_sum']+=len(neighbors)
        stress=sum(int(reds[j]) for j in neighbors)/len(neighbors)
        individual=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03)
        amber=individual or (stress>=.50 and not greens[i])
        ng+=int(greens[i]); na+=int(amber)
    return ng/len(held),na/len(held)
""",
        "dynamic peer helpers",
    )

    text = base.old.replace_once(
        text,
        "    L=130",
        "    L=260",
        "correlation history ring",
    )

    old_elig = "elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    new_elig = "member=np.array([str(tick[int(_tid)]).upper() in r1000_membership(ds) for _tid in tids],dtype=bool); elig=member&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    text = base.old.replace_once(text, old_elig, new_elig, "R1000 eligibility")

    # Full-PIT transform already routes this through sector_key; the dynamic
    # calculation ignores the placeholder grouping but keeping SID here makes
    # the absence of historical sector authority explicit.
    old_breadth = """            secct=defaultdict(lambda:[0,0])
            for z in held: secct[z[1]][0]+=int(z[7]); secct[z[1]][1]+=1
            ng=na=0
            for z in held:
                stress=secct[z[1]][0]/secct[z[1]][1] if secct[z[1]][1] else 0.
                amber=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03) or (stress>=.50 and not z[6])
                ng+=int(z[6]); na+=int(amber)
            green_b=ng/len(held) if held else 0.; dam_b=na/len(held) if held else 0."""
    new_breadth = """            green_b,dam_b=dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates)"""
    text = base.old.replace_once(text, old_breadth, new_breadth, "correlation peer breadth")

    text = base.old.replace_once(
        text,
        "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,",
        "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,\n        'r1000_evidence_label':'BEST_EFFORT_PIT_R1000_CORRELATION_PEERS',\n        'r1000_snapshot_first':_R1000_DATES[0],'r1000_snapshot_last':_R1000_DATES[-1],\n        'r1000_snapshot_count':len(_R1000_DATES),'correlation_peer_stats':PEER_STATS,",
        "R1000 summary evidence",
    )

    forbidden = (
        "held.append((tid,sector[tid]",
        "heldissuers={issuer[s.tid]",
        "resissuers.add(issuer[tid])",
        "pit_model.group(",
        "SEC_CIK:",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"R1000 transform retained forbidden metadata seam: {needle}")
    return text


def metric_block(frame: pd.DataFrame, column: str, start: str, years: float | None) -> dict:
    return base.old.metric_block(frame, column, start, years)


def finalize_experiment(output: Path, membership_manifest: Path) -> None:
    daily = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    metrics = pd.read_csv(output / "metrics.csv", dtype={"window_years": str})
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    membership = json.loads(membership_manifest.read_text(encoding="utf-8"))

    # First economically non-flat Wealth Core observation. The machine has a
    # full pre-membership feature warm-up but cannot trade before a strict-prior
    # R1000 snapshot exists.
    eq = daily["research_wealth_core_equity"].astype(float)
    active = daily[(eq - STARTING_EQUITY).abs() > 1.0]
    if active.empty:
        raise RuntimeError("R1000 replay never became economically invested")
    active_start = str(active.iloc[0]["date"].date())

    starts = dict(STANDARD_WINDOWS)
    starts["max"] = (active_start, None)
    rows = []
    for window in ("5", "10", "15", "20", "max"):
        start, years = starts[window]
        if pd.Timestamp(start) < pd.Timestamp(daily.iloc[0]["date"]):
            continue
        for variant, column in (
            ("RESEARCH", "research_nav"),
            ("CORE", "research_wealth_core_equity"),
            ("SPY", "spy_nav"),
        ):
            block = metric_block(daily, column, start, years)
            rows.append({"window_years": window, "variant": variant, **block})
    pd.DataFrame(rows).to_csv(output / "metrics.csv", index=False)

    summary["status"] = "PASS"
    summary["experiment"] = "r1000_iwb_proxy_correlation_peers_frozen_ldrc"
    summary["evidence_label"] = EVIDENCE_LABEL
    summary["formal_pit_certified"] = False
    summary["active_start"] = active_start
    summary["membership_proxy"] = {
        "source": membership["source"],
        "first_as_of": membership["first_as_of"],
        "last_as_of": membership["last_as_of"],
        "snapshot_count": membership["snapshot_count"],
        "minimum_mapping_coverage": membership["minimum_mapping_coverage"],
        "median_mapping_coverage": membership["median_mapping_coverage"],
        "membership_file_sha256": membership["output_sha256"],
        "causal_rule": membership["causal_rule"],
    }
    summary["domain_changes"] = {
        "universe": "strict-prior historical IWB equity holdings as best-effort Russell 1000 proxy",
        "issuer_family": "disabled; each stable security id is independent",
        "sector_contagion": "prior-only 252-session SPY-residual correlations; min 120 observations; top 3 peers at correlation >= 0.145",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": "backtester.r1000-correlation-peers/1",
        "status": "PASS",
        "evidence_label": EVIDENCE_LABEL,
        "formal_pit_certified": False,
        "strategy_embedded_commit": summary.get("research_embedded_commit"),
        "membership_manifest": membership,
        "active_start": active_start,
        "metrics": rows,
    }
    (output / "r1000-experiment-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [
        output / "daily.csv.gz",
        output / "metrics.csv",
        output / "summary.json",
        output / "r1000-experiment-manifest.json",
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{base.old.sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    print("[RESULT] R1000 correlation-peer metrics", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--membership", type=Path, required=True)
    ap.add_argument("--membership-manifest", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/r1000_correlation_peers_frozen.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    env["R1000_MEMBERSHIP_SNAPSHOTS"] = str(args.membership)
    print(f"[RUN] {EVIDENCE_LABEL}", flush=True)
    print("[RUN] membership strict-prior; issuer families disabled; sector metadata disabled; causal correlation peers enabled", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    base.old.postprocess("fullpit", args.output)
    base.finalize("fullpit", args.output)
    finalize_experiment(args.output, args.membership_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
