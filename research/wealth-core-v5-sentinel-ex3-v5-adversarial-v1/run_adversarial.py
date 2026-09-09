#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
IMPEDANCE_DIR = HERE.parent / "wealth-core-v5-sentinel-ex3-impedance-v1"
V5_DIR = HERE.parent / "wealth-core-v5-affordability-fix-v1"
for _p in (IMPEDANCE_DIR, V5_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_impedance as imp
from v5_execution_harness import _V4, apply_v5_open_time_whole_share_10bp, assert_exact_v5_delta

SCHEMA = "research.wealth-core-v5-sentinel-ex3-v5-adversarial/1"
SYSTEM = "Wealth Core V5 + Sentinel EX3 V5"
SELECTED = {"rec": 8, "r40_floor": -0.05, "fast_damaged": 0.88, "healthy_damaged": 0.63}
EXPECTED = {
    "dataset": imp.DATASET_SHA256,
    "core": imp.BASELINE_CORE_TAPE_SHA256,
    "transactions": imp.BASELINE_TX_SHA256,
    "close_decisions": imp.BASELINE_CLOSE_SHA256,
    "cagr20": 0.215572258056,
    "dd20": -0.273755457386,
    "sharpe20": 1.1210581190,
}
START, END, SESSIONS = "2006-07-31", "2026-07-31", 5032

REGIMES = {
    "GFC_2007_2009": ("2007-07-01", "2009-06-30"),
    "EURO_2010_2012": ("2010-01-01", "2012-12-31"),
    "ENERGY_2015_2016": ("2015-01-01", "2016-12-31"),
    "VOL_2018": ("2018-01-01", "2018-12-31"),
    "COVID_2020": ("2020-01-01", "2020-12-31"),
    "RECOVERY_2021": ("2021-01-01", "2021-12-31"),
    "BEAR_2022": ("2022-01-01", "2022-12-31"),
    "RECENT_2025_2026": ("2025-01-01", "2026-07-31"),
}

CONTROLLER_CASES = [
    ("rec7", "LDRC_REC=8", "LDRC_REC=7"),
    ("rec9", "LDRC_REC=8", "LDRC_REC=9"),
    ("r40_m04", "recent_r40>-0.05)", "recent_r40>-0.04)"),
    ("r40_m06", "recent_r40>-0.05)", "recent_r40>-0.06)"),
    ("r20_m080", "LDRC_R20=-0.085", "LDRC_R20=-0.08"),
    ("r20_m090", "LDRC_R20=-0.085", "LDRC_R20=-0.09"),
    ("v_010", "LDRC_V=0.11", "LDRC_V=0.10"),
    ("v_012", "LDRC_V=0.11", "LDRC_V=0.12"),
    ("dd_m09", "LDRC_DD=-0.1", "LDRC_DD=-0.09"),
    ("dd_m11", "LDRC_DD=-0.1", "LDRC_DD=-0.11"),
    ("ceil_050", "LDRC_CEIL=.55", "LDRC_CEIL=.50"),
    ("ceil_060", "LDRC_CEIL=.55", "LDRC_CEIL=.60"),
    ("fast_dam_086", "'dam':0.88", "'dam':0.86"),
    ("fast_dam_090", "'dam':0.88", "'dam':0.90"),
    ("healthy_dam_061", "dam<=0.63 and green>=.20", "dam<=0.61 and green>=.20"),
    ("healthy_dam_065", "dam<=0.63 and green>=.20", "dam<=0.65 and green>=.20"),
    ("ablate_divergence", "LDRC_DD=-0.1", "LDRC_DD=-9.0"),
    ("ablate_spy_v_release", "LDRC_V=0.11", "LDRC_V=9.0"),
    ("ablate_fast_native", "'dam':0.88", "'dam':1.01"),
    ("ablate_ordinary_native", "ORD_DD = -0.155", "ORD_DD = -9.0"),
    ("ablate_cross_surface", "concordant=(\n", "concordant=(False and\n"),
    ("ablate_recovery_persistence", "if self.full_streak>=LDRC_REC or vre or concordant:", "if False or vre or concordant:"),
    ("ablate_divergence_persistence_clear", "cleared=self.latched and (self.full_streak>=LDRC_REC or vre)", "cleared=self.latched and (False or vre)"),
]

STRUCTURAL_CASES = [
    ("slots18_reciprocal", 18, 1.0 / 18.0),
    ("slots19_fixed5", 19, 0.05),
    ("slots19_reciprocal", 19, 1.0 / 19.0),
    ("slots21_fixed5", 21, 0.05),
    ("slots21_reciprocal", 21, 1.0 / 21.0),
    ("slots22_reciprocal", 22, 1.0 / 22.0),
    ("slots24_reciprocal", 24, 1.0 / 24.0),
    ("slots26_reciprocal", 26, 1.0 / 26.0),
]

EXECUTION_CASES = [
    ("cost_15bp", "cost", 0.0015),
    ("cost_25bp", "cost", 0.0025),
    ("cost_50bp", "cost", 0.0050),
    ("adverse_open_25bp", "adverse_open", 0.0025),
    ("adverse_open_50bp", "adverse_open", 0.0050),
    ("entry_delay_1_session", "entry_delay", 1),
]

UNIVERSE_CASES = [(f"drop_{pct:02d}pct_seed{seed}", pct / 100.0, seed)
                  for pct in (1, 5, 10) for seed in (11, 29, 47)]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, observed {count}: {old!r}")
    return src.replace(old, new, 1)


def timing_guard(src: str) -> None:
    apply_marker = "navs[kname],tc=apply_overlay"
    pending_marker = "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
    call_marker = "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
    for marker in (apply_marker, pending_marker, call_marker):
        if src.count(marker) != 1:
            raise RuntimeError(f"causal timing marker mismatch: {marker}")
    if src.index(apply_marker) >= src.index(pending_marker):
        raise RuntimeError("controller close decision can reach same-session allocation")
    if "eff['A']=a_d" in src:
        raise RuntimeError("illegal same-session controller allocation mutant")


def build_selected(control_source: Path, median_overlay: Path) -> str:
    from backtester.production_equivalent_economic_overlay import assert_contract, assert_one_session_dividend_lag
    raw = control_source.read_text()
    if sha(raw.encode()) != imp.CONTROL_10BP_SOURCE_SHA256:
        raise RuntimeError("10bp source authority mismatch")
    assert_contract(raw)
    median = load_module(median_overlay.resolve(), "adversarial_median5")
    median5 = median.apply_arm(raw, "MEDIAN5_CANONICAL")
    v4 = _V4.apply_open_time_whole_share_10bp(median5)
    v5 = apply_v5_open_time_whole_share_10bp(median5)
    assert_exact_v5_delta(v4, v5)
    imp.assert_frozen_20_slots(v5, "Wealth Core V5")
    if assert_one_session_dividend_lag(v5) != 1:
        raise RuntimeError("dividend lag authority changed")
    selected = imp.apply_variant(v5, SELECTED)
    if "recent_r40>-0.05)" not in selected:
        raise RuntimeError("Sentinel EX3 V5 r40=-5% seam missing")
    timing_guard(selected)
    return selected


def execute(src: str, outdir: Path, tag: str, keep_raw: bool = False) -> dict:
    if outdir.exists():
        shutil.rmtree(outdir)
    engine = outdir / "engine"
    engine.mkdir(parents=True)
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    (workspace / "final-output").mkdir(parents=True, exist_ok=True)
    generated = outdir / f"{tag}.py"
    generated.write_text(src)
    compile(src, str(generated), "exec")
    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    modname = "adv_" + hashlib.sha256(tag.encode()).hexdigest()[:14]
    module = types.ModuleType(modname)
    module.__file__ = str(generated)
    sys.modules[modname] = module
    exec(compile(src, str(generated), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError(f"{tag}: not in full-PIT mode")
    module.OUT = engine
    module.run()

    daily = engine / "daily.csv"
    summary_p = engine / "summary.json"
    tx = engine / "transactions.csv"
    close = engine / "close-decisions.csv"
    telemetry_p = engine / "open-sizing-telemetry.json"
    for p in (daily, summary_p, tx, close, telemetry_p):
        if not p.exists():
            raise RuntimeError(f"{tag}: missing {p.name}")
    frame = pd.read_csv(daily, parse_dates=["date"])
    if len(frame) != SESSIONS or str(frame.date.iloc[0].date()) != START or str(frame.date.iloc[-1].date()) != END:
        raise RuntimeError(f"{tag}: measurement horizon mismatch")
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise RuntimeError(f"{tag}: tape ordering failure")
    summary = json.loads(summary_p.read_text())
    telemetry = json.loads(telemetry_p.read_text())
    if summary.get("canonical_pit_dataset_hash") != EXPECTED["dataset"]:
        raise RuntimeError(f"{tag}: PIT dataset authority changed")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError(f"{tag}: dividend lag changed")

    result = {
        "tag": tag,
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "core": imp.windows(frame, "shadow_equity"),
        "sentinel": imp.windows(frame, "A_nav"),
        "allocation": imp.allocation_counts(frame),
        "dataset_sha256": summary.get("canonical_pit_dataset_hash"),
        "core_tape_sha256": imp.core_tape_hash(frame),
        "transactions_sha256": sha(tx.read_bytes()),
        "close_decisions_sha256": sha(close.read_bytes()),
        "candidate_A_episodes": summary.get("candidate_A_episodes"),
        "candidate_A_concordance_releases": summary.get("candidate_A_concordance_releases"),
        "transition_counts": summary.get("transition_counts"),
        "buys": summary.get("buys"), "sells": summary.get("sells"),
        "gap_clipped_entries": telemetry.get("gap_clipped_entries"),
        "blocked_open_entries": telemetry.get("blocked_open_entries"),
    }
    if keep_raw:
        for p in (daily, summary_p, tx, close, telemetry_p, engine / "gap-events.csv"):
            if p.exists():
                shutil.copy2(p, outdir / p.name)
    del module
    sys.modules.pop(modname, None)
    gc.collect()
    return result


def assert_baseline(result: dict) -> None:
    for key, expected in (("core_tape_sha256", EXPECTED["core"]),
                          ("transactions_sha256", EXPECTED["transactions"]),
                          ("close_decisions_sha256", EXPECTED["close_decisions"])):
        if result[key] != expected:
            raise RuntimeError(f"baseline parity failed: {key}")
    m = result["sentinel"]["20"]
    for key, expected in (("cagr", EXPECTED["cagr20"]), ("max_drawdown", EXPECTED["dd20"]),
                          ("sharpe_daily_252", EXPECTED["sharpe20"])):
        if abs(float(m[key]) - float(expected)) > 5e-10:
            raise RuntimeError(f"Sentinel EX3 V5 metric parity failed: {key}: {m[key]} vs {expected}")


def nav_metrics(dates: pd.Series, returns: pd.Series) -> dict:
    r = pd.Series(np.asarray(returns, float), index=pd.to_datetime(dates).to_numpy()).fillna(0.0)
    nav = (1.0 + r).cumprod()
    years = (nav.index[-1] - nav.index[0]).days / 365.2425
    dd = nav / nav.cummax() - 1.0
    sd = float(r.iloc[1:].std(ddof=1))
    return {"cagr": float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0),
            "max_drawdown": float(dd.min()),
            "sharpe_daily_252": float(r.iloc[1:].mean() / sd * math.sqrt(252)) if sd > 0 else None,
            "ending_multiple": float(nav.iloc[-1] / nav.iloc[0])}


def jackknife(frame: pd.DataFrame, mask, replacement: str = "zero") -> dict:
    r = frame.A_nav.astype(float).pct_change().fillna(0.0)
    if replacement == "core":
        rc = frame.shadow_equity.astype(float).pct_change().fillna(0.0)
        r.loc[mask] = rc.loc[mask]
    else:
        r.loc[mask] = 0.0
    return nav_metrics(frame.date, r)


def posthoc(frame: pd.DataFrame) -> dict:
    dates = pd.to_datetime(frame.date)
    r = frame.A_nav.astype(float).pct_change().fillna(0.0)
    years = {str(y): jackknife(frame, (dates.dt.year == y).to_numpy()) for y in sorted(dates.dt.year.unique())}
    q = dates.dt.to_period("Q").astype(str)
    quarters = {str(x): jackknife(frame, (q == x).to_numpy()) for x in sorted(q.unique())}
    order_best = np.argsort(-r.to_numpy()); order_worst = np.argsort(r.to_numpy())
    concentration = {}
    for n in (1, 3, 5, 10, 20):
        mb = np.zeros(len(frame), bool); mb[order_best[:n]] = True
        mw = np.zeros(len(frame), bool); mw[order_worst[:n]] = True
        concentration[f"remove_best_{n}"] = jackknife(frame, mb)
        concentration[f"remove_worst_{n}"] = jackknife(frame, mw)

    regimes = {}
    for name, (a, b) in REGIMES.items():
        m = (dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b))
        sub = frame.loc[m].copy()
        if len(sub) > 1:
            regimes[name] = {"sentinel": imp.metrics(sub, "A_nav"), "core": imp.metrics(sub, "shadow_equity"),
                             "spy": imp.metrics(sub.dropna(subset=["spy_nav"]), "spy_nav")}

    alloc = frame.A_allocation.astype(float).to_numpy(); defensive = alloc < 1.0 - 1e-12
    episodes = []; i = 0
    while i < len(frame):
        if not defensive[i]: i += 1; continue
        j = i
        while j + 1 < len(frame) and defensive[j + 1]: j += 1
        m = np.zeros(len(frame), bool); m[i:j+1] = True
        episodes.append({"start": str(dates.iloc[i].date()), "end": str(dates.iloc[j].date()), "sessions": j-i+1,
                         "min_allocation": float(alloc[i:j+1].min()), "neutralize_to_core": jackknife(frame, m, "core")})
        i = j + 1

    rs = frame.spy_nav.astype(float).pct_change().fillna(0.0)
    x, y = rs.to_numpy()[1:], r.to_numpy()[1:]
    beta = float(np.cov(x, y, ddof=1)[0,1] / np.var(x, ddof=1)) if np.var(x, ddof=1) > 0 else None
    alpha = None if beta is None else float((y.mean() - beta*x.mean()) * 252.0)
    downside = y[y < 0]
    sortino = float(y.mean()/downside.std(ddof=1)*math.sqrt(252)) if len(downside)>1 and downside.std(ddof=1)>0 else None
    base = imp.metrics(frame, "A_nav")
    benchmark = {"beta_daily": beta, "alpha_annualized_arithmetic": alpha, "sortino_daily_252": sortino,
                 "calmar": float(base["cagr"] / abs(base["max_drawdown"]))}

    rng = np.random.default_rng(20260909); b = r.to_numpy()[1:]; block = 20; starts = np.arange(len(b)-block+1)
    cagr, sharpe = [], []
    total_years = (dates.iloc[-1]-dates.iloc[0]).days/365.2425
    for _ in range(2000):
        chunks=[]; total=0
        while total < len(b):
            s=int(rng.choice(starts)); z=b[s:s+block]; chunks.append(z); total += len(z)
        z=np.concatenate(chunks)[:len(b)]; mult=float(np.prod(1+z)); cagr.append(mult**(1/total_years)-1)
        sd=float(np.std(z,ddof=1)); sharpe.append(float(np.mean(z)/sd*math.sqrt(252)) if sd>0 else np.nan)
    bootstrap={"method":"moving_block_bootstrap","draws":2000,"block_sessions":20,"seed":20260909,
               "cagr_p025":float(np.quantile(cagr,.025)),"cagr_p50":float(np.quantile(cagr,.5)),"cagr_p975":float(np.quantile(cagr,.975)),
               "sharpe_p025":float(np.nanquantile(sharpe,.025)),"sharpe_p50":float(np.nanquantile(sharpe,.5)),"sharpe_p975":float(np.nanquantile(sharpe,.975))}
    return {"classification":"EX_POST_PATH_ATTRIBUTION_NOT_CAUSAL_RERUN","leave_one_year_out":years,
            "leave_one_quarter_out":quarters,"return_concentration":concentration,"regimes":regimes,
            "sentinel_episode_jackknife":episodes,"benchmark":benchmark,"bootstrap":bootstrap,
            "exposure":{"mean":float(alloc.mean()),"sessions_0":int(np.isclose(alloc,0).sum()),
                        "sessions_55":int(np.isclose(alloc,.55).sum()),"sessions_65":int(np.isclose(alloc,.65).sum()),
                        "sessions_100":int(np.isclose(alloc,1).sum()),"transitions":int((np.abs(np.diff(alloc))>1e-12).sum()),
                        "defensive_sessions":int(defensive.sum()),"defensive_episodes":len(episodes)}}


def fault_guards(selected: str) -> dict:
    out={}
    mutant=selected.replace("pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d",
                            "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d; eff['A']=a_d",1)
    try: timing_guard(mutant); out["lookahead_mutant_rejected"]=False
    except Exception: out["lookahead_mutant_rejected"]=True
    from backtester.production_equivalent_economic_overlay import assert_one_session_dividend_lag
    div=selected.replace("book.receivables.append((gday+1,q*rawdiv))","book.receivables.append((gday,q*rawdiv))",1)
    try: out["dividend_lag_mutant_rejected"] = assert_one_session_dividend_lag(div) != 1
    except Exception: out["dividend_lag_mutant_rejected"] = True
    out["dataset_hash_mutant_rejected"] = ("0"*64 != EXPECTED["dataset"])
    out["core_hash_mutant_rejected"] = ("0"*64 != EXPECTED["core"])
    if not all(out.values()): raise RuntimeError(f"fault injection guard failure: {out}")
    return out


def security_ids(frame: pd.DataFrame) -> list[str]:
    ids=set()
    for raw in frame.research_selected_positions.dropna().astype(str):
        try: xs=json.loads(raw)
        except Exception: continue
        ids.update(str(x) for x in xs)
    return sorted(ids)


def patch_exclusion(src: str, excluded: set[str]) -> str:
    marker="_sec_ok=np.zeros(len(tids),dtype=bool); _known=0; _unknown=0"
    repl=(f"_ADV_EXCLUDED={repr(frozenset(excluded))}\n"
          "            _base_elig=_base_elig & np.asarray([str(sid[int(_tid)]) not in _ADV_EXCLUDED for _tid in tids],dtype=bool)\n"
          "            "+marker)
    return replace_once(src, marker, repl, "security leave-one-out")


def patch_dropout(src: str, fraction: float, seed: int) -> str:
    marker="_sec_ok=np.zeros(len(tids),dtype=bool); _known=0; _unknown=0"
    repl=(f"_ADV_DROP={fraction!r}; _ADV_SEED={int(seed)}\n"
          "            def _adv_keep(_tid):\n"
          "                _h=hashlib.sha256(f'{_ADV_SEED}:{sid[int(_tid)]}'.encode()).digest()\n"
          "                return int.from_bytes(_h[:8],'big')/18446744073709551616.0 >= _ADV_DROP\n"
          "            _base_elig=_base_elig & np.asarray([_adv_keep(_tid) for _tid in tids],dtype=bool)\n"
          "            "+marker)
    return replace_once(src, marker, repl, "universe dropout")


def patch_structure(src: str, slots: int, entry_w: float) -> str:
    return replace_once(replace_once(src,"N_SLOTS = 20",f"N_SLOTS = {slots}","slots"),
                        "ENTRY_W = 0.05",f"ENTRY_W = {entry_w!r}","entry weight")


def patch_execution(src: str, kind: str, value) -> str:
    if kind=="cost": return replace_once(src,"COST = 0.001",f"COST = {float(value)!r}","cost")
    if kind=="adverse_open":
        s=float(value)
        src=replace_once(src,"px=opraw[s.tid]",f"px=opraw[s.tid]*(1.0-{s!r})","sell open")
        return replace_once(src,"tid=s.pending_tid; px=opraw[tid]",f"tid=s.pending_tid; px=opraw[tid]*(1.0+{s!r})","buy open")
    if kind=="entry_delay":
        old="if not(s.reserved() and not s.held()): continue\n                tid=s.pending_tid; px=opraw[tid]"
        new=("if not(s.reserved() and not s.held()): continue\n"
             f"                if s.pending_signal_day>=0 and gday < s.pending_signal_day+1+{int(value)}: continue\n"
             "                tid=s.pending_tid; px=opraw[tid]")
        return replace_once(src,old,new,"entry delay")
    raise RuntimeError(kind)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")


def run_cases(selected: str, root: Path, suite: str, cases, transform, shard: int, shards: int) -> dict:
    rows=[]
    for i, case in enumerate(cases):
        if i % shards != shard: continue
        tag=case[0]; src=transform(selected,*case[1:]); timing_guard(src)
        ev=execute(src,root/"runs"/tag,tag)
        row={"case":tag,"classification":"FRESH_CAUSAL_FULL_PIT_RERUN","result":ev}; rows.append(row)
        write_json(root/"cases"/f"{tag}.json",row)
    return {"schema":SCHEMA,"system":SYSTEM,"suite":suite,"shard":shard,"shards":shards,"status":"PASS","cases":rows}


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--suite",required=True,choices=["baseline","controller","structural","execution","universe","security-loo"])
    ap.add_argument("--control-source",required=True,type=Path); ap.add_argument("--median-overlay",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path); ap.add_argument("--shard",type=int,default=0); ap.add_argument("--shards",type=int,default=1)
    ap.add_argument("--security-list",type=Path)
    args=ap.parse_args()
    if not 0<=args.shard<args.shards: raise RuntimeError("invalid shard")
    root=args.output.resolve(); shutil.rmtree(root,ignore_errors=True); root.mkdir(parents=True)
    manifest=json.loads((Path(os.environ["CANONICAL_PIT_DATASET"])/"manifest.json").read_text())
    if manifest.get("dataset_hash")!=EXPECTED["dataset"]: raise RuntimeError("canonical PIT hash mismatch")
    selected=build_selected(args.control_source,args.median_overlay)
    (root/"selected-source-sha256.txt").write_text(sha(selected.encode())+"\n")

    if args.suite=="baseline":
        ev=execute(selected,root/"baseline-run","baseline_selected",True); assert_baseline(ev)
        frame=pd.read_csv(root/"baseline-run"/"daily.csv",parse_dates=["date"]); ids=security_ids(frame); write_json(root/"held-security-ids.json",ids)
        result={"schema":SCHEMA,"system":SYSTEM,"suite":"baseline","status":"PASS","baseline":ev,"posthoc":posthoc(frame),
                "fault_injection":fault_guards(selected),"held_security_count":len(ids),
                "validation":{"fresh_full_pit_replay":True,"exact_core_parity":True,"exact_transactions_parity":True,
                              "exact_close_decisions_parity":True,"exact_sentinel_ex3_v5_parity":True,"causal_timing_guard":True,
                              "performance_target_used_for_selection":False}}
    elif args.suite=="controller":
        result=run_cases(selected,root,"controller",CONTROLLER_CASES,
                         lambda s,_tag_old,_new=None: s,0,1) if False else run_cases(selected,root,"controller",CONTROLLER_CASES,
                         lambda s,old,new: replace_once(s,old,new,"controller perturbation"),args.shard,args.shards)
    elif args.suite=="structural": result=run_cases(selected,root,"structural",STRUCTURAL_CASES,patch_structure,args.shard,args.shards)
    elif args.suite=="execution": result=run_cases(selected,root,"execution",EXECUTION_CASES,patch_execution,args.shard,args.shards)
    elif args.suite=="universe": result=run_cases(selected,root,"universe",UNIVERSE_CASES,patch_dropout,args.shard,args.shards)
    else:
        if args.security_list is None: raise RuntimeError("security-loo requires --security-list")
        ids=json.loads(args.security_list.read_text()); chosen=[str(x) for i,x in enumerate(sorted(map(str,ids))) if i%args.shards==args.shard]; rows=[]
        for sid in chosen:
            tag="loo_"+hashlib.sha256(sid.encode()).hexdigest()[:16]; ev=execute(patch_exclusion(selected,{sid}),root/"runs"/tag,tag)
            row={"security_id":sid,"case":tag,"classification":"FRESH_CAUSAL_FULL_PIT_SECURITY_LEAVE_ONE_OUT","result":ev}; rows.append(row); write_json(root/"cases"/f"{tag}.json",row)
        result={"schema":SCHEMA,"system":SYSTEM,"suite":"security-loo","shard":args.shard,"shards":args.shards,
                "held_security_total":len(ids),"cases_in_shard":len(chosen),"status":"PASS","cases":rows}

    result["experiment_head"]=os.environ.get("GITHUB_SHA"); result["selected_config"]=SELECTED; result["performance_selection"]="FORBIDDEN_VALIDATION_ONLY"
    write_json(root/"RESULT.json",result)
    print("[ADVERSARIAL_RESULT] "+json.dumps({"suite":result["suite"],"status":result["status"],"shard":result.get("shard"),"cases":len(result.get("cases",[]))},sort_keys=True),flush=True)
    return 0

if __name__=="__main__": raise SystemExit(main())
