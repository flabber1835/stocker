#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CONTROL_SOURCE_SHA256 = "5f61d5ed5afd784bfb247d554344199743de11dcf9b31956430c6a77b91fedf7"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
CONTROL_10BP_RESULT = {
    "cagr": 0.15488287845556004,
    "max_drawdown": -0.49042738751414783,
    "sharpe_daily_252": 0.805082394739427,
    "end_equity": 1646091.825445194,
    "entries": 519,
    "open_blocks": 1,
    "gap_clips": 19,
    "close_q0": 1004,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def metrics(nav: pd.Series, dates: pd.Series) -> dict:
    nav = nav.astype(float)
    dates = pd.to_datetime(dates)
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    rets = nav.pct_change().dropna()
    vol = float(rets.std(ddof=1))
    return {
        "start": str(dates.iloc[0].date()),
        "end": str(dates.iloc[-1].date()),
        "sessions": int(len(nav)),
        "cagr": multiple ** (1.0 / years) - 1.0,
        "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "sharpe_daily_252": float(rets.mean() / vol * np.sqrt(252)) if vol > 0 else None,
        "start_equity": float(nav.iloc[0]),
        "end_equity": float(nav.iloc[-1]),
    }


def replace_between(src: str, start: str, end: str, replacement: str, label: str) -> str:
    if src.count(start) != 1:
        raise RuntimeError(f"{label} start seam mismatch: {src.count(start)}")
    i = src.index(start)
    j = src.index(end, i)
    return src[:i] + replacement + src[j:]


def patch(src: str, mode: str) -> str:
    if mode not in {"whole", "fractional"}:
        raise ValueError(mode)

    init_old = (
        "rows=[]; trade_rows=[]; gap_event_rows=[]; close_decision_rows=[]; _pending_meta={}; "
        "overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; "
        "scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; "
        "scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; "
        "scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; "
        "scale_entry_fraction_sum=0.0; buffer_blocked_open_entries=0; "
        "buffer_min_post_buy_excess=float('inf'); buffer_min_actual_cash=float(book.cash); "
        "buffer_reserve_violations=0"
    )
    init_new = init_old + (
        "; open_sizing_event_rows=[]; open_close_admissions=0; open_invalid_market_blocks=0; "
        "open_zero_quantity_blocks=0; open_cash_limited_execs=0; open_rounding_underfill_dollars=0.0; "
        "open_rounding_underfill_fraction_sum=0.0; open_full_target_execs=0; open_partial_target_execs=0; "
        "open_fractional_buy_count=0"
    )
    if src.count(init_old) != 1:
        raise RuntimeError(f"init seam mismatch: {src.count(init_old)}")
    src = src.replace(init_old, init_new, 1)

    open_start = (
        "            for s in book.slots:\n"
        "                if not(s.reserved() and not s.held()): continue\n"
        "                tid=s.pending_tid; px=opraw[tid]\n"
    )
    open_end = "            for _tid0,_sig_close,_raw_close,_reported_volume in zip(tids,c,cu,vol):\n"

    if mode == "whole":
        quantity_expr = "q=float(math.floor(_execution_budget/(float(px)*(1+COST)))) if _execution_budget>0 else 0.0"
        fractional_counter = ""
    else:
        quantity_expr = "q=float(_execution_budget/(float(px)*(1+COST))) if _execution_budget>0 else 0.0"
        fractional_counter = "; open_fractional_buy_count+=int(q>0 and abs(q-round(q))>1e-9)"

    open_replacement = f'''            for s in book.slots:\n                if not(s.reserved() and not s.held()): continue\n                tid=s.pending_tid; px=opraw[tid]; _pm=_pending_meta.get(id(s),{{}})\n                _desired=float(s.pending_intended_capital); _cash_before=float(book.cash)\n                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:\n                    _execution_budget=max(0.0,min(_desired,_cash_before)); {quantity_expr}\n                    if q>1e-12:\n                        _gross=float(q)*float(px)*(1+COST); _frac=(_gross/_desired if _desired>0 else 0.0)\n                        _cash_limited=bool(_cash_before+1e-8<_desired); _rounding=max(0.0,_execution_budget-_gross)\n                        _round_frac=(_rounding/_execution_budget if _execution_budget>0 else 0.0)\n                        scale_entries+=1; scale_one_share_entries+=int(abs(q-1.0)<=1e-9); scale_entry_fraction_sum+=_frac; scale_min_entry_fraction=min(scale_min_entry_fraction,_frac); scale_max_entry_fraction=max(scale_max_entry_fraction,_frac); scale_lt1+=int(_frac<0.01); scale_lt5+=int(_frac<0.05); scale_lt10+=int(_frac<0.10); scale_lt25+=int(_frac<0.25); scale_lt50+=int(_frac<0.50); scale_lt99+=int(_frac<0.99)\n                        open_cash_limited_execs+=int(_cash_limited); open_rounding_underfill_dollars+=_rounding; open_rounding_underfill_fraction_sum+=_round_frac; open_full_target_execs+=int(abs(_gross-_desired)<=max(1e-8,1e-10*_desired)); open_partial_target_execs+=int(abs(_gross-_desired)>max(1e-8,1e-10*_desired)){fractional_counter}\n                        open_sizing_event_rows.append({{'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'{mode}','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':float(q),'executed_gross_dollars':_gross,'entry_fraction_of_intended':_frac,'cash_limited_at_open':_cash_limited,'rounding_underfill_dollars':_rounding,'rounding_underfill_fraction':_round_frac,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':False,'block_reason':''}})\n                        book.cash-=_gross; buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); buffer_min_post_buy_excess=min(buffer_min_post_buy_excess,float(book.cash)); trade_rows.append({{'Transaction date':ds,'Buy or sell':'BUY','Ticker':str(tick[tid]),'Ticker name':'','Amount of shares':float(q)}}); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    else:\n                        open_zero_quantity_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({{'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'{mode}','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':bool(_cash_before+1e-8<_desired),'rounding_underfill_dollars':_execution_budget,'rounding_underfill_fraction':1.0 if _execution_budget>0 else 0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'ZERO_QUANTITY'}})\n                else:\n                    open_invalid_market_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({{'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'{mode}','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px) if finite(px) else np.nan,'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':0.0,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':False,'rounding_underfill_dollars':0.0,'rounding_underfill_fraction':0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'INVALID_OPEN_MARKET'}})\n                _pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.\n'''
    src = replace_between(src, open_start, open_end, open_replacement, "open execution")

    close_start = "                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001);"
    close_end = "            buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); shadow_dates.append(date);"
    close_replacement = '''                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001); _buffer_available_close=max(0.0,float(book.cash)-_buffer_required_close); _funding_fraction=(float(min(_desired,_buffer_available_close))/_desired if _desired>0 else 0.0)\n                        if _buffer_available_close<=1e-12: scale_q0_candidate_skips+=1; close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'Q0_SKIP','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'CASH_SCARCITY','buffer_basis_points':10}); continue\n                        scale_cash_limited_decisions+=int(_funding_fraction<0.999999999); close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'PLAN_OPEN_SIZE','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'','buffer_basis_points':10})\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=0.; s.pending_signal_day=gday; s.pending_intended_capital=_desired; _pending_meta[id(s)]={'decision_date':ds,'close_price':float(px),'close_nav':float(eq),'close_cash_before':float(book.cash),'close_required_reserve':float(_buffer_required_close),'close_uncommitted_cash':float(_buffer_available_close),'intended_capital':float(_desired)}; open_close_admissions+=1; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1\n'''
    src = replace_between(src, close_start, close_end, close_replacement, "close admission")

    csv_marker = "    pd.DataFrame(close_decision_rows,columns=['decision_date','ticker','outcome','planned_shares','close_price','close_nav','cash_before_decision','required_reserve','uncommitted_cash_after_reserve','intended_capital','funding_fraction','q0_reason','buffer_basis_points']).to_csv(OUT/'close-decisions.csv',index=False)\n"
    csv_insert = csv_marker + "    pd.DataFrame(open_sizing_event_rows,columns=['decision_date','execution_date','ticker','mode','close_price','open_price','intended_target_dollars','cash_before_execution','execution_budget','executed_shares','executed_gross_dollars','entry_fraction_of_intended','cash_limited_at_open','rounding_underfill_dollars','rounding_underfill_fraction','close_required_10bp_cushion','close_cash_above_cushion','blocked','block_reason']).to_csv(OUT/'open-sizing-events.csv',index=False)\n"
    if src.count(csv_marker) != 1:
        raise RuntimeError("CSV marker mismatch")
    src = src.replace(csv_marker, csv_insert, 1)

    telemetry_marker = "    print(json.dumps(summary,indent=2),flush=True)\n"
    custom = f'''    _open_telemetry={{'schema':'research.wealth-core-v1-open-sizing-10bp/1','mode':'{mode}','buffer_basis_points':10,'buffer_fraction':0.001,'buffer_role':'CLOSE_TIME_ADMISSION_CUSHION_RELEASED_AT_OPEN','close_admissions':int(open_close_admissions),'completed_entries':int(scale_entries),'close_q0_no_cash_above_cushion':int(scale_q0_candidate_skips),'next_open_blocks':int(open_invalid_market_blocks+open_zero_quantity_blocks),'invalid_open_market_blocks':int(open_invalid_market_blocks),'zero_quantity_blocks':int(open_zero_quantity_blocks),'cash_limited_open_executions':int(open_cash_limited_execs),'rounding_underfill_dollars_total':float(open_rounding_underfill_dollars),'average_rounding_underfill_fraction':float(open_rounding_underfill_fraction_sum/scale_entries) if scale_entries else None,'full_target_executions':int(open_full_target_execs),'partial_target_executions':int(open_partial_target_execs),'fractional_buy_count':int(open_fractional_buy_count),'minimum_actual_cash':float(buffer_min_actual_cash),'fractional_shares_allowed':{str(mode == 'fractional')},'all_admitted_trades_executed':bool(open_invalid_market_blocks+open_zero_quantity_blocks==0)}}\n    (OUT/'open-sizing-telemetry.json').write_text(json.dumps(_open_telemetry,indent=2,sort_keys=True))\n    print(json.dumps(summary,indent=2),flush=True)\n'''
    if src.count(telemetry_marker) != 1:
        raise RuntimeError("telemetry marker mismatch")
    src = src.replace(telemetry_marker, custom, 1)

    compile(src, f"<open-sizing-{mode}>", "exec")
    return src


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["whole", "fractional"], required=True)
    ap.add_argument("--control-source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    control = args.control_source.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    engine = Path("/home/runner/work/stocker/stocker/final-output/engine")
    engine.mkdir(parents=True, exist_ok=True)

    raw = control.read_bytes()
    if sha(raw) != CONTROL_SOURCE_SHA256:
        raise RuntimeError(f"certified 10bp control source mismatch: {sha(raw)}")
    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset mismatch")

    candidate = patch(raw.decode(), args.mode)
    generated = out / f"open-sizing-{args.mode}-generated.py"
    generated.write_text(candidate)
    subprocess.run([sys.executable, "-m", "py_compile", str(generated)], check=True)

    for stale in (
        engine / "daily.csv",
        engine / "summary.json",
        engine / "transactions.csv",
        engine / "gap-events.csv",
        engine / "close-decisions.csv",
        engine / "open-sizing-events.csv",
        engine / "buffer-telemetry.json",
        engine / "open-sizing-telemetry.json",
    ):
        if stale.exists():
            stale.unlink()

    env = os.environ.copy()
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(generated)], cwd=Path.cwd(), env=env, check=True)

    for name in (
        "daily.csv",
        "summary.json",
        "transactions.csv",
        "close-decisions.csv",
        "open-sizing-events.csv",
        "open-sizing-telemetry.json",
    ):
        shutil.copy2(engine / name, out / name)

    frame = pd.read_csv(out / "daily.csv")
    perf = metrics(frame.shadow_equity, frame.date)
    summary = json.loads((out / "summary.json").read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("output PIT hash mismatch")
    if int(summary.get("financial_grade_dividend_lag_sessions", -1)) != 1:
        raise RuntimeError("dividend lag changed")

    scale = summary["wealth_core_capital_scale"]
    tel = json.loads((out / "open-sizing-telemetry.json").read_text())
    tx = pd.read_csv(out / "transactions.csv")
    buys = pd.to_numeric(tx.loc[tx["Buy or sell"].eq("BUY"), "Amount of shares"], errors="raise").to_numpy()

    if args.mode == "whole" and not np.allclose(buys, np.round(buys), atol=1e-9):
        raise RuntimeError("fractional buy in whole-share arm")
    if float(tel["minimum_actual_cash"]) < -1e-7:
        raise RuntimeError(f"negative cash: {tel['minimum_actual_cash']}")

    result = {
        "schema": "research.wealth-core-v1-open-sizing-10bp-arm/1",
        "status": "PASS",
        "mode": args.mode,
        "buffer_basis_points": 10,
        "buffer_role": "CLOSE_TIME_ADMISSION_CUSHION_RELEASED_AT_OPEN",
        "economic_scope": "WEALTH_CORE_V1_ONLY",
        "dataset_sha256": DATASET_SHA256,
        "control_10bp_source_sha256": CONTROL_SOURCE_SHA256,
        "generated_source_sha256": sha(candidate.encode()),
        "financial_grade_dividend_lag_sessions": 1,
        "portfolio_performance": perf,
        "execution": tel,
        "entry_telemetry": scale,
        "transaction_ledger": {
            "rows": int(len(tx)),
            "buys": int(tx["Buy or sell"].eq("BUY").sum()),
            "sells": int(tx["Buy or sell"].eq("SELL").sum()),
            "fractional_buy_rows": int(np.sum(np.abs(buys - np.round(buys)) > 1e-9)),
            "all_buy_quantities_integer": bool(np.allclose(buys, np.round(buys), atol=1e-9)),
        },
        "certified_10bp_control": CONTROL_10BP_RESULT,
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("[OPEN_SIZING_10BP] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
