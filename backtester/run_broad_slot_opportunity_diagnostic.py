#!/usr/bin/env python3
"""Zero-budget broad Wealth Core slot opportunity diagnostic, 2020-2026.

Consumes the immutable trade/position path emitted by the accepted broad E3
attribution replay, reconstructs accepted broad eligibility + ranking from a 2019
warm-up, and measures leaders blocked while all 25 actual slots were occupied.
No portfolio decisions are changed or replayed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

E3_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
ATTR_RUN_ID = 33943672769
ATTR_HEAD = "ab5a9b9ba8c09bb99ad95fda554b332749756bad"
ATTR_DIGEST = "sha256:22f1cc9bd78eb325c89204a89c7e43358db41805e9907077111fad3ed78b1467"
LABEL = "BROAD_E3_SLOT_OPPORTUNITY_ZERO_BUDGET_DIAGNOSTIC"
WARMUP_YEAR = 2019
START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2026-07-31")
N_SLOTS = 25
MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_DAY_DV = 5_000_000.0
TOP = 0.10
COOLDOWN = 21
HORIZONS = (5, 21, 63, 119)
TERMINAL = {"acquisitionby", "mergerto", "voluntarydelisting", "regulatorydelisting", "bankruptcyliquidation", "delisted"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zcsv(path: Path, usecols=None) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"{path}: expected one csv, got {names}")
        with z.open(names[0]) as f:
            return pd.read_csv(f, usecols=usecols, low_memory=False)


def load_meta(root: Path):
    cols = ["table", "permaticker", "ticker", "category", "firstpricedate", "lastpricedate"]
    d = zcsv(root / "SHARADAR_TICKERS.zip", cols)
    d = d[d.table.eq("SEP")].dropna(subset=["ticker"]).copy()
    if d.ticker.duplicated().any():
        raise RuntimeError("duplicate SEP ticker identity")
    d = d.sort_values("ticker").reset_index(drop=True)
    tick = d.ticker.astype(str).to_numpy(object)
    tmap = {t: i for i, t in enumerate(tick)}
    sid = d.permaticker.astype("Int64").astype(str).to_numpy(object)
    common = d.category.fillna("").astype(str).map(
        lambda c: "Common Stock" in c and "Warrant" not in c and "Preferred" not in c
    ).to_numpy(bool)
    firstdate = pd.to_datetime(d.firstpricedate, errors="coerce").to_numpy("datetime64[D]")
    lastdate = pd.to_datetime(d.lastpricedate, errors="coerce").to_numpy("datetime64[D]")
    return tick, tmap, sid, common, firstdate, lastdate


def load_terminal_actions(path: Path):
    d = pd.read_csv(path, compression="gzip", usecols=["date", "action", "ticker"], low_memory=False)
    d["date"] = pd.to_datetime(d.date).dt.normalize()
    d["action"] = d.action.astype(str).str.lower()
    d["ticker"] = d.ticker.astype(str)
    d = d[d.action.isin(TERMINAL)]
    out = defaultdict(set)
    for r in d.itertuples(index=False):
        out[pd.Timestamp(r.date)].add(str(r.ticker))
    return dict(out)


def year_file(root: Path, y: int) -> Path:
    p = root / f"SHARADAR_SEP_{y}.csv.gz"
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def load_authoritative_path(attr: Path):
    daily = pd.read_csv(attr / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    daily["date"] = daily.date.dt.normalize()
    daily = daily[(daily.date >= START) & (daily.date <= END)].copy()
    marks = pd.read_csv(attr / "broad_r3000_daily_position_marks.csv.gz", compression="gzip")
    marks["date"] = pd.to_datetime(marks.date).dt.normalize()
    marks = marks[(marks.date >= START) & (marks.date <= END)].copy()
    marks["ticker"] = marks.ticker.astype(str)
    held_by_date = {d: set(g.ticker.astype(str)) for d, g in marks.groupby("date", sort=True)}
    trades = pd.read_csv(attr / "broad_r3000_trade_attribution.csv")
    trades["exit_date"] = pd.to_datetime(trades.exit_date, errors="coerce").dt.normalize()
    trades["ticker"] = trades.ticker.astype(str)
    exit_dates = defaultdict(list)
    for r in trades.dropna(subset=["exit_date"]).itertuples(index=False):
        exit_dates[str(r.ticker)].append(pd.Timestamp(r.exit_date))
    for k in exit_dates:
        exit_dates[k].sort()
    return daily, held_by_date, dict(exit_dates)


def reconstruct(root: Path, attr: Path, actions_path: Path, output: Path):
    tick, tmap, sid, common, firstdate, lastdate = load_meta(root)
    n = len(tick)
    daily, held_by_date, exit_dates = load_authoritative_path(attr)
    accepted = daily.set_index("date")[["eligible_count", "leadership_population", "held_count"]]
    terminal = load_terminal_actions(actions_path)

    L = 260
    close_ring = np.full((L, n), np.nan, np.float32)
    r126 = np.zeros((126, n), np.float32); rv126 = np.zeros((126, n), bool)
    s126 = np.zeros(n, np.float64); q126 = np.zeros(n, np.float64); c126 = np.zeros(n, np.int16)
    r21 = np.zeros((21, n), np.float32); rv21 = np.zeros((21, n), bool)
    s21 = np.zeros(n, np.float64); q21 = np.zeros(n, np.float64); c21 = np.zeros(n, np.int16)
    dvbuf = np.zeros((20, n), np.float32); dvsum = np.zeros(n, np.float64)
    score = np.full(n, np.nan); recent = np.full(n, np.nan); clraw = np.full(n, np.nan)
    touched = np.empty(0, np.int32); gday = -1
    session_dates = []
    latest_exit_index = {}
    pending_exits_by_date = defaultdict(list)
    for tk, dates in exit_dates.items():
        for d in dates:
            pending_exits_by_date[d].append(tk)

    parity_rows = []; opportunities = []
    for y in range(WARMUP_YEAR, END.year + 1):
        d = pd.read_csv(year_file(root, y), usecols=["ticker", "date", "open", "close", "volume", "closeunadj"], low_memory=False)
        d["date"] = pd.to_datetime(d.date); d = d[d.date <= END]
        d = d.dropna(subset=["ticker", "date", "close", "closeunadj"]).drop_duplicates(["ticker", "date"], keep="last")
        ids = d.ticker.astype(str).map(tmap); d = d[ids.notna()].copy(); d["tid"] = ids[ids.notna()].astype(np.int32).to_numpy()
        d.sort_values(["date", "tid"], inplace=True, kind="mergesort")
        for date, g in d.groupby("date", sort=True):
            gday += 1; date = pd.Timestamp(date).normalize(); session_dates.append(date)
            for tk in pending_exits_by_date.get(date, []): latest_exit_index[tk] = gday
            if touched.size:
                score[touched] = np.nan; recent[touched] = np.nan; clraw[touched] = np.nan
            tids = g.tid.to_numpy(np.int32, copy=False); touched = tids
            c = g.close.to_numpy(float, copy=False); cu = g.closeunadj.to_numpy(float, copy=False); vol = g.volume.to_numpy(float, copy=False)
            dv = np.nan_to_num(c * vol, nan=0.0, posinf=0.0, neginf=0.0)
            lag21 = close_ring[(gday - 21) % L, tids] if gday >= 21 else np.full(len(tids), np.nan)
            lag126 = close_ring[(gday - 126) % L, tids] if gday >= 126 else np.full(len(tids), np.nan)
            prev = close_ring[(gday - 1) % L, tids] if gday >= 1 else np.full(len(tids), np.nan)
            rr = np.divide(c, lag21, out=np.full_like(c, np.nan), where=np.isfinite(lag21) & (lag21 > 0)) - 1
            mm = np.divide(lag21, lag126, out=np.full_like(c, np.nan), where=np.isfinite(lag21) & np.isfinite(lag126) & (lag126 > 0)) - 1
            lr = np.log(np.divide(c, prev, out=np.full_like(c, np.nan), where=np.isfinite(c) & (c > 0) & np.isfinite(prev) & (prev > 0)))
            k = gday % 126; old = r126[k]; oldv = rv126[k]
            s126 -= old; q126 -= old * old; c126 -= oldv.astype(np.int16); old.fill(0); oldv.fill(False)
            m = np.isfinite(lr); old[tids[m]] = lr[m].astype(np.float32); oldv[tids[m]] = True
            s126[tids[m]] += lr[m]; q126[tids[m]] += lr[m] * lr[m]; c126[tids[m]] += 1
            k2 = gday % 21; o2 = r21[k2]; ov2 = rv21[k2]
            s21 -= o2; q21 -= o2 * o2; c21 -= ov2.astype(np.int16); o2.fill(0); ov2.fill(False)
            o2[tids[m]] = lr[m].astype(np.float32); ov2[tids[m]] = True
            s21[tids[m]] += lr[m]; q21[tids[m]] += lr[m] * lr[m]; c21[tids[m]] += 1
            fsum = s126[tids] - s21[tids]; fsq = q126[tids] - q21[tids]; fcnt = c126[tids] - c21[tids]
            var = np.divide(fsq - fsum * fsum / np.maximum(fcnt, 1), np.maximum(fcnt - 1, 1), out=np.full(len(tids), np.nan), where=fcnt > 1)
            fvol = np.sqrt(np.maximum(var, 0)) * np.sqrt(252)
            sc = np.divide(np.log1p(mm), fvol, out=np.full(len(tids), np.nan), where=np.isfinite(mm) & (mm > -1) & np.isfinite(fvol) & (fvol > 0))
            kd = gday % 20; dvsum -= dvbuf[kd]; dvbuf[kd].fill(0); dvbuf[kd, tids] = dv.astype(np.float32); dvsum[tids] += dv
            av = dvsum[tids] / 20 if gday >= 19 else np.full(len(tids), np.nan)
            close_ring[gday % L].fill(np.nan); close_ring[gday % L, tids] = c.astype(np.float32)
            score[tids] = sc; recent[tids] = rr; clraw[tids] = cu
            dt64 = np.datetime64(date.date()); listed = (firstdate[tids] <= dt64) & (lastdate[tids] >= dt64); continuous = c126[tids] >= 126
            elig = common[tids] & listed & continuous & np.isfinite(mm) & np.isfinite(rr) & np.isfinite(cu) & (cu >= MIN_PRICE) & np.isfinite(av) & (av >= MIN_ADV20) & np.isfinite(dv) & (dv >= MIN_DAY_DV) & np.isfinite(sc) & (fvol > 0)
            et = tids[elig]
            if len(et):
                sid_et = sid[et]; ordm = np.lexsort((sid_et, -mm[elig])); rawall = et[ordm]
                nk = min(len(et), max(25, int(math.ceil(len(et) * TOP)))); pool = rawall[:nk]
                ordscore = np.lexsort((tick[pool], sid[pool], -score[pool])); durable = pool[ordscore]
            else:
                nk = 0; durable = np.empty(0, np.int32)
            if date < START: continue
            if date not in accepted.index: raise RuntimeError(f"accepted broad daily path missing {date.date()}")
            ar = accepted.loc[date]; held = held_by_date.get(date, set())
            parity_rows.append({"date":date,"recomputed_eligible":int(len(et)),"accepted_eligible":int(ar.eligible_count),"recomputed_pool":int(nk),"accepted_pool":int(ar.leadership_population),"marks_held":int(len(held)),"accepted_held":int(ar.held_count)})
            if len(held) != N_SLOTS: continue
            term_today = terminal.get(date, set()); admissible = []
            for rank0, tid0 in enumerate(durable, start=1):
                tid = int(tid0); tk = str(tick[tid])
                if not np.isfinite(recent[tid]) or recent[tid] < 0 or tk in held: continue
                ex = latest_exit_index.get(tk)
                if ex is not None and ex + COOLDOWN > gday: continue
                if tk in term_today or not np.isfinite(clraw[tid]) or clraw[tid] <= 0: continue
                admissible.append((rank0, tid))
                if len(admissible) >= 3: break
            if not admissible: continue
            held_tids = [tmap[tk] for tk in held if tk in tmap and np.isfinite(score[tmap[tk]]) and np.isfinite(clraw[tmap[tk]]) and clraw[tmap[tk]] > 0]
            weak_tid = min(held_tids, key=lambda z: (score[z], str(sid[z]), str(tick[z]))) if held_tids else None
            tid_pos = {int(t):i for i,t in enumerate(tids)}
            for blocked_order, (dur_rank, tid) in enumerate(admissible, start=1):
                pos = tid_pos.get(tid)
                opportunities.append({"date":date,"blocked_order":blocked_order,"ticker":str(tick[tid]),"security_id":str(sid[tid]),"durable_rank":int(dur_rank),"momentum_126_to_21":float(mm[pos]) if pos is not None else np.nan,"recent_r21":float(recent[tid]),"score":float(score[tid]),"held_count":len(held),"weakest_held_ticker":str(tick[weak_tid]) if weak_tid is not None else "","weakest_held_security_id":str(sid[weak_tid]) if weak_tid is not None else "","weakest_held_score":float(score[weak_tid]) if weak_tid is not None else np.nan})

    parity = pd.DataFrame(parity_rows)
    bad = parity[(parity.recomputed_eligible != parity.accepted_eligible) | (parity.recomputed_pool != parity.accepted_pool) | (parity.marks_held != parity.accepted_held)]
    parity.to_csv(output / "broad_slot_ranking_parity.csv.gz", index=False, compression={"method":"gzip","compresslevel":6,"mtime":0})
    if len(bad):
        bad.head(100).to_csv(output / "broad_slot_ranking_parity_failures.csv", index=False)
        raise RuntimeError(f"ranking/path parity failed on {len(bad)} sessions; first={bad.iloc[0].to_dict()}")
    opp = pd.DataFrame(opportunities)
    if opp.empty: raise RuntimeError("no full-slot blocked opportunities found")
    return opp, daily, session_dates


def attach_forward_returns(root: Path, opp: pd.DataFrame, session_dates):
    dates = [d for d in session_dates if START <= d <= END]; date_to_i = {d:i for i,d in enumerate(dates)}
    needed = set(opp.ticker.astype(str)) | set(opp.weakest_held_ticker.astype(str)); needed.discard("")
    prices = defaultdict(dict)
    for y in range(START.year, END.year + 1):
        d = pd.read_csv(year_file(root, y), usecols=["ticker","date","close"], low_memory=False)
        d["ticker"] = d.ticker.astype(str); d = d[d.ticker.isin(needed)].copy(); d["date"] = pd.to_datetime(d.date).dt.normalize()
        d = d[(d.date >= START) & (d.date <= END)].dropna(subset=["close"]).drop_duplicates(["ticker","date"], keep="last")
        for r in d.itertuples(index=False): prices[str(r.ticker)][pd.Timestamp(r.date)] = float(r.close)
    rows=[]
    for r in opp.itertuples(index=False):
        row=r._asdict(); d=pd.Timestamp(r.date); i=date_to_i.get(d)
        for h in HORIZONS:
            out_date = dates[i+h] if i is not None and i+h < len(dates) else None
            cand0=prices.get(str(r.ticker),{}).get(d); weak0=prices.get(str(r.weakest_held_ticker),{}).get(d) if str(r.weakest_held_ticker) else None
            cand1=prices.get(str(r.ticker),{}).get(out_date) if out_date is not None else None; weak1=prices.get(str(r.weakest_held_ticker),{}).get(out_date) if out_date is not None and str(r.weakest_held_ticker) else None
            cr=(cand1/cand0-1.0) if cand0 and cand1 and cand0>0 else np.nan; wr=(weak1/weak0-1.0) if weak0 and weak1 and weak0>0 else np.nan
            row[f"candidate_r{h}"]=cr; row[f"weakest_held_r{h}"]=wr; row[f"spread_vs_weakest_r{h}"]=cr-wr if np.isfinite(cr) and np.isfinite(wr) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def episode_sample(frame: pd.DataFrame) -> pd.DataFrame:
    x=frame[frame.blocked_order.eq(1)].sort_values(["date","ticker"]).copy(); dates=sorted(pd.Timestamp(d) for d in x.date.unique()); di={d:i for i,d in enumerate(dates)}
    chosen=[]; last={}
    for idx,row in x.iterrows():
        j=di[pd.Timestamp(row.date)]; prev=last.get(str(row.ticker),-10**9)
        if j-prev>=21: chosen.append(idx); last[str(row.ticker)]=j
    return x.loc[chosen].copy()


def summarize(frame: pd.DataFrame, daily: pd.DataFrame, output: Path) -> None:
    frame=frame.copy(); frame["date"]=pd.to_datetime(frame.date); episodes=episode_sample(frame)
    frame.to_csv(output/"broad_slot_opportunities_raw.csv.gz",index=False,compression={"method":"gzip","compresslevel":6,"mtime":0})
    episodes.to_csv(output/"broad_slot_opportunity_episodes.csv",index=False)
    top=frame[frame.blocked_order.eq(1)].copy(); top.sort_values("spread_vs_weakest_r63",ascending=False).head(100).to_csv(output/"broad_slot_top_missed_63d.csv",index=False); top.sort_values("spread_vs_weakest_r119",ascending=False).head(100).to_csv(output/"broad_slot_top_missed_119d.csv",index=False)
    rows=[]
    for year in list(range(2020,2027))+[0]:
        d=daily if year==0 else daily[daily.date.dt.year.eq(year)]; f=episodes if year==0 else episodes[episodes.date.dt.year.eq(year)]
        rec={"year":"ALL" if year==0 else str(year),"sessions":int(len(d)),"full_slot_sessions":int((d.held_count.astype(int)>=N_SLOTS).sum()),"opportunity_episodes":int(len(f)),"unique_blocked_tickers":int(f.ticker.nunique()) if len(f) else 0}
        for h in HORIZONS:
            s=f[f"spread_vs_weakest_r{h}"].dropna().astype(float); c=f[f"candidate_r{h}"].dropna().astype(float)
            rec[f"n_r{h}"]=int(len(s)); rec[f"mean_candidate_r{h}"]=float(c.mean()) if len(c) else np.nan; rec[f"median_spread_r{h}"]=float(s.median()) if len(s) else np.nan; rec[f"mean_spread_r{h}"]=float(s.mean()) if len(s) else np.nan; rec[f"hit_rate_vs_weakest_r{h}"]=float((s>0).mean()) if len(s) else np.nan
        rows.append(rec)
    summary=pd.DataFrame(rows); summary.to_csv(output/"broad_slot_opportunity_summary.csv",index=False)
    focus=frame[frame.ticker.isin(["SNDK","LITE","WDC","CRS","CIEN"])].copy(); focus.to_csv(output/"broad_slot_focus_names.csv",index=False)
    manifest={"schema":"backtester.broad-slot-opportunity-diagnostic/1","status":"PASS","evidence_label":LABEL,"zero_budget_diagnostic":True,"strategy_mechanics_changed":False,"portfolio_path_replayed":False,"portfolio_path_authority":"immutable accepted broad E3 attribution marks/trades","strategy_source_head":E3_HEAD,"attribution_run_id":ATTR_RUN_ID,"attribution_head":ATTR_HEAD,"attribution_artifact_digest":ATTR_DIGEST,"analysis_window":[str(START.date()),str(END.date())],"warmup_year":WARMUP_YEAR,"ranking_parity":"exact eligible_count + leadership_population + held_count on every analyzed session","forward_return_domain":"Sharadar split-adjusted close-to-close; diagnostic only, not execution PnL","episode_deduplication":"top blocked candidate; same ticker suppressed for 21 opportunity sessions"}
    mp=output/"broad_slot_opportunity_manifest.json"; mp.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    files=[output/"broad_slot_ranking_parity.csv.gz",output/"broad_slot_opportunities_raw.csv.gz",output/"broad_slot_opportunity_episodes.csv",output/"broad_slot_top_missed_63d.csv",output/"broad_slot_top_missed_119d.csv",output/"broad_slot_opportunity_summary.csv",output/"broad_slot_focus_names.csv",mp]
    (output/"BROAD_SLOT_OPPORTUNITY_SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print("[SUMMARY]"); print(summary.to_string(index=False)); print("[TOP 63D]"); print(pd.read_csv(output/"broad_slot_top_missed_63d.csv").head(30).to_string(index=False)); print("[FOCUS]"); print(focus.head(100).to_string(index=False) if len(focus) else "none")


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--sharadar-root",type=Path,required=True); ap.add_argument("--attribution-root",type=Path,required=True); ap.add_argument("--pit-actions",type=Path,required=True); ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    opp,daily,sessions=reconstruct(args.sharadar_root,args.attribution_root,args.pit_actions,args.output); enriched=attach_forward_returns(args.sharadar_root,opp,sessions); summarize(enriched,daily,args.output); return 0

if __name__=="__main__": raise SystemExit(main())
