"""Independent decomposition of retained Core and controller economic paths."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess

REFERENCE = "2a1bd486241ae524eac395490b135cc79715e497"
PREFIX = "research/champion-certification-20y-v1/results/34544522249-1/"
REPLAY = "7b5dda96ce4235363c5c6ded3974d3fb2970f432"
START, END = "2006-07-31", "2026-07-31"


def blob(commit, name):
    return subprocess.check_output(["git", "show", f"{commit}:{name}"])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def csv_gz(raw):
    return list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))


def factor(old, new, prior, opening, closing, bill_on, bill_day, cost=.001):
    """Dollar-fraction accounting; old ownership bears the overnight move."""
    if old == new:
        return new * closing/prior + (1-new)*(1+bill_on)*(1+bill_day)
    overnight = old*opening/prior + (1-old)*(1+bill_on)
    intraday = new*closing/opening + (1-new)*(1+bill_day)
    return overnight * (1-cost*abs(new-old)) * intraday


def curve(rows, core, allocation, cost=.001):
    values, factors = [1.], [1.]
    for previous, row in zip(rows, rows[1:]):
        f = factor(previous[allocation], row[allocation], previous[core+"_close"],
                   row[core+"_open"], row[core+"_close"],
                   row["bill_on"], row["bill_day"], cost)
        if not math.isfinite(f) or f <= 0:
            raise ValueError("nonpositive/nonfinite economic factor")
        factors.append(f)
        values.append(values[-1]*f)
    return values, factors


def stats(values, dates):
    years = (date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.2425
    peak = values[0]
    worst = 0.
    peak_day = dates[0]
    worst_peak, trough = peak_day, peak_day
    underwater, longest = 0, 0
    returns = []
    for i, (day, val) in enumerate(zip(dates, values)):
        if val >= peak:
            peak, peak_day, underwater = val, day, 0
        else:
            underwater += 1
            longest = max(longest, underwater)
        dd = val/peak-1
        if dd < worst:
            worst, worst_peak, trough = dd, peak_day, day
        if i:
            returns.append(val/values[i-1]-1)
    mean = sum(returns)/len(returns)
    vol = math.sqrt(sum((r-mean)**2 for r in returns)/(len(returns)-1)*252)
    return {"multiple":values[-1]/values[0], "cagr":math.expm1(math.log(values[-1]/values[0])/years),
            "max_drawdown":worst, "peak_date":worst_peak,"trough_date":trough,
            "annualized_daily_volatility":vol,"longest_underwater_sessions":longest}


def decompose(a, b, c, d):
    """a=current/current, b=current/ref, c=ref/current, d=ref/ref factors."""
    la, lb, lc, ld = map(math.log, (a,b,c,d))
    return {"core_log_gap":((ld-lb)+(lc-la))/2,
            "exposure_log_gap":((ld-lc)+(lb-la))/2,
            "total_log_gap":ld-la,"interaction_log":ld-lc-lb+la}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    inputs={}
    def get(commit,name):
        raw=blob(commit,name)
        inputs[f"{commit}:{name}"]={"sha256":sha(raw),"bytes":len(raw)}
        return raw
    raw=get(REPLAY,"audit/economic-replay-resume-430/accepted-daily.jsonl.gz")
    actual=[json.loads(line) for line in gzip.decompress(raw).splitlines()]
    ref_obs=csv_gz(get(REFERENCE,PREFIX+"observations.csv.gz"))
    ref_daily=csv_gz(get(REFERENCE,PREFIX+"champion-daily.csv.gz"))
    ref_sessions=csv_gz(get(REFERENCE,PREFIX+"portfolio-sessions.csv.gz"))
    obs={r["date"]:r for r in ref_obs}
    refs={r["date"]:r for r in ref_daily}
    port={r["date"]:r for r in ref_sessions}
    assert [r["date"] for r in actual]==[r["date"] for r in ref_obs]
    raw=args.checkpoint.read_bytes()
    pointer=json.loads(get(REPLAY,"audit/economic-replay-resume-430/latest-checkpoint.json"))
    assert sha(raw)==pointer["sha256"]
    checkpoint=json.loads(gzip.decompress(raw))
    inputs["final_checkpoint"]={"sha256":sha(raw),"bytes":len(raw)}
    evs=checkpoint["state"]["ledger"]["events"]
    events=defaultdict(list)
    for ev in evs:
        events[ev["session"]].append(ev)
    holdings={}
    cash,recv=100000.,0.
    all_rows=[]
    for i,r in enumerate(actual):
        day=r["date"]
        for e in events[day]:
            assert abs(cash-e["cash_before"])<1e-6, (day,"cash continuity")
            cash=e["cash_after"]
            sid=e["security_id"]
            if e["event_type"]=="CONVERSION":
                holdings[sid]=holdings.get(sid,0)-e["detail"]["shares_in"]
                delivered=e["detail"]["delivered_security_id"]
                holdings[delivered]=holdings.get(delivered,0)+e["detail"]["shares_delivered"]
            else:
                holdings[sid]=holdings.get(sid,0)+e["shares_delta"]
            if e["event_type"]=="DIVIDEND_ACCRUED":recv+=e["detail"]["amount"]
            if e["event_type"]=="DIVIDEND_PAID":recv-=e["detail"]["amount"]
        holdings={sid:q for sid,q in holdings.items() if q!=0}
        assert all(q>0 for q in holdings.values())
        # A conversion can deliver an already-owned security into another slot.
        # The retained count is episodes, whereas this ledger aggregates security.
        assert len(holdings)<=r["held_count"], (day,holdings,r["held_count"])
        economics=r["economics"]
        o=obs[day]
        native=r["decision"]["native_target_core_exposure"]
        core=float(r["core_nav"])
        rr={"date":day,"current_close":core,"current_open":float(economics["parent_core_open_equity"]),
            "reference_close":float(o["close_eq"]),"reference_open":float(o["open_eq"]),
            "bill_on":float(economics["bil_overnight_return"] or 0),
            "bill_day":float(economics["bil_intraday_return"]),
            "current_a":float(economics["held_allocation"] or 1),
            "reference_a":float(refs[day]["allocation"]) if day in refs else 1.,
            "native_a":actual[i-1]["decision"]["native_target_core_exposure"] if i else 1.,
            "full":1.,"bills":0.,"current_target":r["decision"]["target_core_exposure"],
            "native_target":native,"reason":r["decision"]["ldrc"]["reason"],
            "native_state":r["decision"]["evidence"]["native_snapshot"]["state"],
            "actual_nav":float(r["nav"]),"reference_nav":float(refs[day]["nav"]) if day in refs else None,
            "spy":float(r["spy_level"]),"cash":cash,"receivables":recv,
            "stock_fraction":(core-cash-recv)/core,"held_count":r["held_count"],
            "unique_security_count":len(holdings),
            "reference_cash_fraction":float(port[day]["cash"])/float(port[day]["core_equity"]),
            "reference_stock_fraction":float(port[day]["stock_value"])/float(port[day]["core_equity"]),
            "reference_held_count":int(port[day]["stock_count"]),
            "owned_ids":sorted(holdings),"reference_ids":json.loads(port[day]["held_ids_json"]),
            "trades":[e for e in events[day] if e["event_type"] in ("BUY","SELL")]}
        if i:
            assert rr["current_a"]==all_rows[-1]["current_target"], (day,"signal lag")
        all_rows.append(rr)
    expected=Counter()
    for ep in checkpoint["state"]["wealth_core"]["episodes"].values():
        expected[ep["security_id"]]+=ep["current_shares"]
    assert dict(expected)==holdings
    assert abs(cash-checkpoint["state"]["wealth_core"]["cash"])<1e-6
    rows=[r for r in all_rows if r["date"]>=START]
    assert rows[0]["date"]==START and rows[-1]["date"]==END
    dates=[r["date"] for r in rows]
    curves={}; factors={}
    specs={"current":("current","current_a"),"reference":("reference","reference_a"),
           "current_core_reference_exposure":("current","reference_a"),
           "reference_core_current_exposure":("reference","current_a"),
           "current_core":("current","full"),"reference_core":("reference","full"),
           "native_only":("current","native_a"),"bill_only":("current","bills")}
    for name,(c,a) in specs.items():
        curves[name],factors[name]=curve(rows,c,a)
    for name,cost in (("current_zero_overlay_fee",0.),("current_double_overlay_fee",.002)):
        curves[name],factors[name]=curve(rows,"current","current_a",cost)
    curves["spy"]=[r["spy"]/rows[0]["spy"] for r in rows]
    errors={}
    for name in ("current","reference"):
        key="actual_nav" if name=="current" else "reference_nav"
        expected=[r[key]/rows[0][key] for r in rows]
        errors[name]=max(abs(a/b-1) for a,b in zip(curves[name],expected))
        assert errors[name]<1e-9, (name,errors[name])
    total=decompose(*(curves[n][-1] for n in ("current","current_core_reference_exposure","reference_core_current_exposure","reference")))
    annual={}
    for i,r in enumerate(rows):
        d=decompose(*(factors[n][i] for n in ("current","current_core_reference_exposure","reference_core_current_exposure","reference")))
        r.update(d)
        r.update({"curve_"+k:v[i] for k,v in curves.items()})
        a=annual.setdefault(r["date"][:4], {"sessions":0,"core_log_gap":0.,"exposure_log_gap":0.,"total_log_gap":0.,"different_allocations":0,"current_return_factor":1.,"reference_return_factor":1.,"current_core_factor":1.,"reference_core_factor":1.})
        a["sessions"]+=1
        for k in ("core_log_gap","exposure_log_gap","total_log_gap"):a[k]+=d[k]
        a["different_allocations"]+=r["current_a"]!=r["reference_a"]
        for key,name in (("current_return_factor","current"),("reference_return_factor","reference"),("current_core_factor","current_core"),("reference_core_factor","reference_core")):a[key]*=factors[name][i]
    # Connected economic windows: differences in today's allocation OR yesterday's
    # carry allocation, so the return-to-equality morning is included.
    windows=[]; current=None
    for i,r in enumerate(rows):
        diff=r["current_a"]!=r["reference_a"] or (i>0 and rows[i-1]["current_a"]!=rows[i-1]["reference_a"])
        if diff:
            if current is None:current={"start":r["date"],"sessions":0,"exposure_log_gap":0.,"current_core_factor":1.,"reference_core_factor":1.,"actual_factor":1.,"reference_factor":1.}
            current["end"]=r["date"];current["sessions"]+=1
            current["exposure_log_gap"]+=r["exposure_log_gap"]
            for k,n in (("current_core_factor","current_core"),("reference_core_factor","reference_core"),("actual_factor","current"),("reference_factor","reference")):current[k]*=factors[n][i]
        elif current is not None:windows.append(current);current=None
    if current is not None:windows.append(current)
    episodes=[]; active=None
    for i,r in enumerate(rows):
        restricted=r["current_a"]<1 or (i>0 and rows[i-1]["current_a"]<1)
        if restricted:
            if active is None:active={"start":r["date"],"sessions":0,"strategy_factor":1.,"core_factor":1.,"native_factor":1.,"zero_sessions":0,"partial_sessions":0,"recovery_only_sessions":0}
            active["end"]=r["date"];active["sessions"]+=1
            active["zero_sessions"]+=r["current_a"]==0
            active["partial_sessions"]+=0<r["current_a"]<1
            active["recovery_only_sessions"]+=r["current_a"]==0 and r["native_a"]==1
            for k,n in (("strategy_factor","current"),("core_factor","current_core"),("native_factor","native_only")):active[k]*=factors[n][i]
        elif active is not None:episodes.append(active);active=None
    if active is not None:episodes.append(active)
    for e in episodes:e["overlay_relative_factor"]=e["strategy_factor"]/e["core_factor"]
    diagnostics={
        "held_allocation_pairs":dict(Counter(f'{r["current_a"]}/{r["reference_a"]}' for r in rows)),
        "current_exposure_counts":dict(Counter(str(r["current_a"]) for r in rows)),
        "mean_current_stock_fraction":sum(r["stock_fraction"] for r in rows)/len(rows),
        "mean_reference_stock_fraction":sum(r["reference_stock_fraction"] for r in rows)/len(rows),
        "mean_current_close_equity_target":sum(r["stock_fraction"]*r["current_target"] for r in rows)/len(rows),
        "mean_current_held_count":sum(r["held_count"] for r in rows)/len(rows),
        "mean_reference_held_count":sum(r["reference_held_count"] for r in rows)/len(rows),
        "event_reasons":dict(Counter(e["reason"] for e in evs)),
        "recovery_only_sessions":sum(r["current_a"]==0 and r["native_a"]==1 for r in rows),
        "exact_holding_set_equal_sessions":sum(set(r["owned_ids"])==set(r["reference_ids"]) for r in rows),
        "average_jaccard_holding_overlap":sum(len(set(r["owned_ids"])&set(r["reference_ids"]))/max(1,len(set(r["owned_ids"])|set(r["reference_ids"]))) for r in rows)/len(rows)}
    out={"source_inputs":inputs,"measured_sessions":len(rows),"diagonal_max_relative_error":errors,
         "metrics":{n:stats(v,dates) for n,v in curves.items()},"log_wealth_decomposition":total,
         "annual":annual,"different_exposure_windows":windows,"restriction_episodes":episodes,"diagnostics":diagnostics,
         "top_core_difference_days":sorted(rows[1:],key=lambda r:abs(r["core_log_gap"]),reverse=True)[:25]}
    # Compact rows avoid publishing licensed price/position detail from checkpoint.
    for r in out["top_core_difference_days"]:
        r.pop("owned_ids",None);r.pop("reference_ids",None);r.pop("trades",None)
    (args.output/"summary.json").write_text(json.dumps(out,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    for r in rows:
        r.pop("owned_ids",None);r.pop("reference_ids",None);r.pop("trades",None)
    with gzip.GzipFile(filename=str(args.output/"daily.jsonl.gz"),mode="wb",mtime=0) as f:
        for r in rows:f.write((json.dumps(r,separators=(",",":"),allow_nan=False)+"\n").encode())
    print(json.dumps({"metrics":out["metrics"],"attribution":total,"diagnostics":diagnostics,"errors":errors},indent=2))


if __name__=="__main__":main()
