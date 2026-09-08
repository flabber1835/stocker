#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

CONTROL_COMMIT = "1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d"
CONTROL_RUN_ID = 34071569702
CONTROL_ARTIFACT_ID = 10001317230
CONTROL_ARTIFACT_DIGEST = "sha256:803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f"
CONTROL_SOURCE_SHA256 = "bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077"
CONTROL_NORMALIZED_AST_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
CONTROL_DAILY_SHA256 = "2fc1137529a7bb6e4c596d42a7af9bb0e3c891c3126116d15c342b8988235dfe"
CONTROL_SUMMARY_SHA256 = "d49d28069647097dea6c1c3417213a5dc9333e1ea33c8ef651f015b718cb22da"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"

CONTROL_METRICS = {
    "cagr": 0.1524665012369839,
    "ending_multiple": 17.08407706744625,
    "max_drawdown": -0.4804421814863442,
    "sharpe_daily_252": 0.8044766146429867,
    "average_held_count": 22.67885532591415,
    "median_held_count": 24.0,
    "full_slot_sessions": 1217,
    "buys": 505,
    "sells": 424,
}

VARIANTS = {
    "jit-full-funding": "Require a full intended position at the close decision, but reserve no cash; next-open execution remains V1-style.",
    "micro-tail-reject": "Preserve V1 partial funding except reject entries below 1% of intended entry capital.",
    "opportunity-micro-reclaim": "Preserve V1 entries; if a fully fundable candidate is blocked only by slot capacity, recycle a current microscopic holding (<1% of intended entry capital).",
    "opportunity-partial-reclaim": "Preserve V1 entries; if a fully fundable candidate is blocked only by slot capacity, recycle the most underfunded-at-entry incumbent.",
    "cash-recovery-reclaim": "Preserve V1 entries; when cash can again fund a normal entry and all slots are occupied, recycle the most underfunded-at-entry incumbent even without a current candidate trigger.",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {n}")
    return text.replace(old, new, 1)


def install_common_instrumentation(src: str, variant: str) -> str:
    src = replace_once(
        src,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; slot_exp_rejected=slot_exp_partial=slot_exp_micro=slot_exp_reclaim_requested=slot_exp_reclaim_filled=slot_exp_gap_clipped=0",
        "telemetry counters",
    )
    src = replace_once(
        src,
        "afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)",
        "planned_q=int(round(s.pending_shares)); afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(planned_q,afford); slot_exp_gap_clipped+=int(q<planned_q)",
        "gap telemetry",
    )
    src = replace_once(
        src,
        "book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
        "book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; s._wc_entry_funding_fraction=float(getattr(s,'_wc_pending_funding_fraction',1.0))*float(q)/max(float(planned_q),1.0); book.initialized=True; buys+=1",
        "entry funding state",
    )
    src = replace_once(
        src,
        "                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1\n",
        "                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s._wc_pending_funding_fraction=1.0\n",
        "pending funding clear",
    )
    src = replace_once(
        src,
        "'held_count':int(len(held)),'research_eligible_universe'",
        "'held_count':int(len(held)),'wc_cash':float(book.cash),'wc_cash_fraction':(float(book.cash)/float(eq) if finite(eq) and eq>0 else np.nan),'research_eligible_universe'",
        "daily cash telemetry",
    )
    src = replace_once(
        src,
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        f"        'wealth_core_slot_experiment':{{'variant':{variant!r},'rejected':slot_exp_rejected,'partial_admission_decisions':slot_exp_partial,'micro_admission_decisions':slot_exp_micro,'reclaim_requested':slot_exp_reclaim_requested,'reclaim_filled':slot_exp_reclaim_filled,'next_open_gap_clipped':slot_exp_gap_clipped}},",
        "summary telemetry",
    )
    return src


def partial_admission_block(*, reject_micro: bool) -> str:
    reject = "\n                        if funding_fraction<0.01: slot_exp_rejected+=1; continue" if reject_micro else ""
    return (
        "desired=eq*ENTRY_W; target=min(desired,book.cash); funding_fraction=(float(target)/float(desired) if desired>0 else 0.0); q=int(target//(float(px)*(1+COST)))\n"
        "                        if funding_fraction<1.0-1e-12: slot_exp_partial+=1\n"
        "                        if funding_fraction<0.01: slot_exp_micro+=1" + reject + "\n"
        "                        if q<1: continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s._wc_pending_funding_fraction=float(funding_fraction); resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1"
    )


def install_admission(src: str, variant: str) -> str:
    old = (
        "target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n"
        "                        if q<1: continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1"
    )
    if variant == "jit-full-funding":
        new = (
            "desired=eq*ENTRY_W; q=int(desired//(float(px)*(1+COST))); required_cash=float(q)*float(px)*(1+COST)\n"
            "                        if q<1: continue\n"
            "                        if required_cash>book.cash+1e-8: slot_exp_rejected+=1; continue\n"
            "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s._wc_pending_funding_fraction=1.0; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1"
        )
    elif variant == "micro-tail-reject":
        new = partial_admission_block(reject_micro=True)
    else:
        new = partial_admission_block(reject_micro=False)
    return replace_once(src, old, new, "admission semantics")


def install_reclaim_sell_semantics(src: str) -> str:
    old = (
        "                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n"
        "                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN"
    )
    new = (
        "                    _sold_tid=s.tid; _slot_reclaim=str(s.sell_reason).startswith('slot_exp_reclaim_'); book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n"
        "                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=(gday if _slot_reclaim else gday+COOLDOWN); slot_exp_reclaim_filled+=int(_slot_reclaim)"
    )
    return replace_once(src, old, new, "reclaim sell slot reuse")


def candidate_trigger_code() -> str:
    return '''                    _slot_exp_candidate=None
                    _slot_exp_heldids=book.held_ids(); _slot_exp_resids=book.reserved_ids()
                    _slot_exp_heldissuers={issuer_key(s.tid,ds) for s in book.slots if s.held()}; _slot_exp_resissuers={issuer_key(s.pending_tid,ds) for s in book.slots if s.reserved()}
                    for _slot_exp_tid0 in durable:
                        _slot_exp_tid=int(_slot_exp_tid0)
                        if not finite(recent[_slot_exp_tid]) or recent[_slot_exp_tid]<0: continue
                        if _slot_exp_tid in _slot_exp_heldids or _slot_exp_tid in _slot_exp_resids or book.sec_ready.get(_slot_exp_tid,-1)>gday or _slot_exp_tid in term_tids: continue
                        if issuer_key(_slot_exp_tid,ds) in _slot_exp_heldissuers or issuer_key(_slot_exp_tid,ds) in _slot_exp_resissuers: continue
                        _slot_exp_px=clraw[_slot_exp_tid]
                        if not(finite(_slot_exp_px) and _slot_exp_px>0): continue
                        _slot_exp_q=int((eq*ENTRY_W)//(float(_slot_exp_px)*(1+COST)))
                        if _slot_exp_q<1: continue
                        _slot_exp_required=float(_slot_exp_q)*float(_slot_exp_px)*(1+COST)
                        if _slot_exp_required<=book.cash+1e-8:
                            _slot_exp_candidate=_slot_exp_tid; break
'''


def install_reclaim(src: str, variant: str) -> str:
    src = install_reclaim_sell_semantics(src)
    anchor = "            if first_eligible is not None and gday>=first_eligible:\n                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]\n"
    if variant == "opportunity-micro-reclaim":
        body = '''            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if not ready and not unresolved and book.cash>0 and not any(s.held() and s.pending_sell for s in book.slots):
''' + candidate_trigger_code() + '''                if _slot_exp_candidate is not None:
                    _slot_exp_victims=[]
                    _slot_exp_cut=float(eq)*ENTRY_W*0.01
                    for _slot_exp_s in book.slots:
                        if not _slot_exp_s.held() or _slot_exp_s.pending_sell or _slot_exp_s.tid in book.terminal_pending: continue
                        _slot_exp_vpx=clraw[_slot_exp_s.tid]
                        if not(finite(_slot_exp_vpx) and _slot_exp_vpx>0): continue
                        _slot_exp_value=float(_slot_exp_s.qty)*float(_slot_exp_vpx)
                        if _slot_exp_value<_slot_exp_cut: _slot_exp_victims.append((_slot_exp_value,_slot_exp_s))
                    if _slot_exp_victims:
                        _slot_exp_victims.sort(key=lambda z:z[0]); _slot_exp_victim=_slot_exp_victims[0][1]
                        _slot_exp_victim.pending_sell=True; _slot_exp_victim.sell_reason='slot_exp_reclaim_micro'; slot_exp_reclaim_requested+=1
'''
    elif variant == "opportunity-partial-reclaim":
        body = '''            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if not ready and not unresolved and book.cash>0 and not any(s.held() and s.pending_sell for s in book.slots):
''' + candidate_trigger_code() + '''                if _slot_exp_candidate is not None:
                    _slot_exp_victims=[(float(getattr(s,'_wc_entry_funding_fraction',1.0)),s) for s in book.slots if s.held() and not s.pending_sell and s.tid not in book.terminal_pending and float(getattr(s,'_wc_entry_funding_fraction',1.0))<1.0-1e-12]
                    if _slot_exp_victims:
                        _slot_exp_victims.sort(key=lambda z:z[0]); _slot_exp_victim=_slot_exp_victims[0][1]
                        _slot_exp_victim.pending_sell=True; _slot_exp_victim.sell_reason='slot_exp_reclaim_partial'; slot_exp_reclaim_requested+=1
'''
    elif variant == "cash-recovery-reclaim":
        body = '''            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if not ready and not unresolved and book.cash>=eq*ENTRY_W and not any(s.held() and s.pending_sell for s in book.slots):
                    _slot_exp_victims=[(float(getattr(s,'_wc_entry_funding_fraction',1.0)),s) for s in book.slots if s.held() and not s.pending_sell and s.tid not in book.terminal_pending and float(getattr(s,'_wc_entry_funding_fraction',1.0))<1.0-1e-12]
                    if _slot_exp_victims:
                        _slot_exp_victims.sort(key=lambda z:z[0]); _slot_exp_victim=_slot_exp_victims[0][1]
                        _slot_exp_victim.pending_sell=True; _slot_exp_victim.sell_reason='slot_exp_reclaim_cash'; slot_exp_reclaim_requested+=1
'''
    else:
        return src
    return replace_once(src, anchor, body, "reclaim trigger")


def patch_source(v1: str, variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(variant)
    out = install_common_instrumentation(v1, variant)
    out = install_admission(out, variant)
    if "reclaim" in variant:
        out = install_reclaim(out, variant)
    if out == v1:
        raise RuntimeError("experiment source did not change")
    return out


def metrics(frame: pd.DataFrame) -> dict:
    nav = frame["shadow_equity"].astype(float)
    years = (frame.date.iloc[-1] - frame.date.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna()
    vol = float(r.std(ddof=1))
    held = frame["held_count"].astype(float)
    return {
        "start": str(frame.date.iloc[0].date()),
        "end": str(frame.date.iloc[-1].date()),
        "sessions": int(len(frame)),
        "cagr": multiple ** (1 / years) - 1,
        "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "sharpe_daily_252": float(r.mean() / vol * np.sqrt(252)) if vol > 0 else None,
        "average_held_count": float(held.mean()),
        "median_held_count": float(held.median()),
        "full_slot_sessions": int((held >= 25).sum()),
        "average_cash_fraction": float(frame["wc_cash_fraction"].astype(float).mean()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    ap.add_argument("--candidate-root", required=True, type=Path)
    ap.add_argument("--engine", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    engine = args.engine.resolve()
    output = args.output.resolve()
    engine.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset mismatch")

    _, _, prior = control.build_source(engine, args.candidate_root.resolve())
    v1 = install(prior)
    assert_contract(v1)
    if assert_one_session_dividend_lag(v1) != 1:
        raise RuntimeError("baseline dividend semantics mismatch")
    if sha(v1.encode()) != CONTROL_SOURCE_SHA256:
        raise RuntimeError("V1 source mismatch")
    if sha(normalized_ast(v1).encode()) != CONTROL_NORMALIZED_AST_SHA256:
        raise RuntimeError("V1 AST mismatch")

    exp = patch_source(v1, args.variant)
    assert_contract(exp)
    if assert_one_session_dividend_lag(exp) != 1:
        raise RuntimeError("experiment changed dividend semantics")
    exp_path = output / f"wealth-core-{args.variant}-generated.py"
    exp_path.write_text(exp)

    for stale in (engine / "daily.csv", engine / "summary.json"):
        if stale.exists():
            stale.unlink()
    env = os.environ.copy()
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(exp_path)], cwd=Path.cwd(), env=env, check=True)

    frame = pd.read_csv(engine / "daily.csv", parse_dates=["date"])
    if len(frame) != 5032 or str(frame.date.iloc[0].date()) != "2006-07-31" or str(frame.date.iloc[-1].date()) != "2026-07-31":
        raise RuntimeError("full-horizon witness mismatch")
    summary = json.loads((engine / "summary.json").read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("dividend summary mismatch")
    telemetry = summary.get("wealth_core_slot_experiment") or {}
    if telemetry.get("variant") != args.variant:
        raise RuntimeError("experiment telemetry identity mismatch")

    m = metrics(frame)
    m["buys"] = int(summary["buys"])
    m["sells"] = int(summary["sells"])
    result = {
        "schema": "research.wealth-core-slot-mechanics/1",
        "status": "PASS",
        "variant": args.variant,
        "hypothesis": VARIANTS[args.variant],
        "economic_scope": "WEALTH_CORE_ONLY",
        "metric_authority": "shadow_equity",
        "sentinel_metrics_used": False,
        "dataset_sha256": DATASET_SHA256,
        "wealth_core_v1_control": {
            **CONTROL_METRICS,
            "control_commit": CONTROL_COMMIT,
            "control_run_id": CONTROL_RUN_ID,
            "control_artifact_id": CONTROL_ARTIFACT_ID,
            "control_artifact_digest": CONTROL_ARTIFACT_DIGEST,
            "generated_source_sha256": CONTROL_SOURCE_SHA256,
            "certified_daily_sha256": CONTROL_DAILY_SHA256,
            "certified_summary_sha256": CONTROL_SUMMARY_SHA256,
        },
        "experiment": {**m, "generated_source_sha256": sha(exp.encode()), "telemetry": telemetry},
        "delta_vs_v1": {
            "cagr_percentage_points": (m["cagr"] - CONTROL_METRICS["cagr"]) * 100,
            "max_drawdown_percentage_points": (m["max_drawdown"] - CONTROL_METRICS["max_drawdown"]) * 100,
            "sharpe": m["sharpe_daily_252"] - CONTROL_METRICS["sharpe_daily_252"],
            "average_held_count": m["average_held_count"] - CONTROL_METRICS["average_held_count"],
            "buys": m["buys"] - CONTROL_METRICS["buys"],
            "sells": m["sells"] - CONTROL_METRICS["sells"],
        },
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copy2(engine / "daily.csv", output / "daily.csv")
    shutil.copy2(engine / "summary.json", output / "summary.json")
    (output / "SHA256.json").write_text(json.dumps({
        p.name: sha(p.read_bytes()) for p in sorted(output.iterdir())
        if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print("[WEALTH_CORE_SLOT_EXPERIMENT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
