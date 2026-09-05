#!/usr/bin/env python3
"""Corrected retained-research LD-RC replay.

Runs the exact retained research implementation in non-PIT or full-PIT mode,
with a full 1997 machine warm-up and the same causal pre-BIL Treasury cash model
used by the corrected production replay. Output remains divergence-compatible.

When RESEARCH_EMIT_POSITION_TRACE=1, the generated replay additionally emits a
read-only diagnostic prior-close holdings trace. The trace is observational: it
does not participate in selection, accounting, controller state, or execution.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

OLD_WRAPPER = Path("backtester/run_research_ldrc_nonpit_vs_fullpit.py")
CASH_AUTHORITY = Path("backtester/data/GS3M_1996-12_2007-05.csv")
WARMUP_START = "1997-01-02"
MEASUREMENT_START = "1998-01-02"

spec = importlib.util.spec_from_file_location("research_old_wrapper", OLD_WRAPPER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load research wrapper {OLD_WRAPPER}")
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


def transformed_source(mode: str, output: Path) -> str:
    text = old.transformed_source(mode, output)
    text = old.replace_once(
        text,
        "    for y in range(1998,END.year+1):",
        "    for y in range(1997,END.year+1):",
        "full-machine warm-up year",
    )
    old_cash = """def bil_factors(bil,date,prevdate):\n    if prevdate is None or date not in bil.index or prevdate not in bil.index: return 0.,0.,1.\n    prev=float(bil.loc[prevdate,'closeadj']); op=float(bil.loc[date,'adjopen']); cl=float(bil.loc[date,'closeadj'])\n    if not all(np.isfinite([prev,op,cl])) or min(prev,op,cl)<=0: return 0.,0.,1.\n    return op/prev-1,cl/op-1,cl/prev\n"""
    new_cash = """_cash_frame=pd.read_csv(Path('backtester/data/GS3M_1996-12_2007-05.csv'))\n_cash_frame['month']=pd.to_datetime(_cash_frame['month'])\n_CASH_YIELD={pd.Timestamp(r.month):float(r.annual_yield_percent) for r in _cash_frame.itertuples(index=False)}\n\ndef bil_factors(bil,date,prevdate):\n    if prevdate is not None and date in bil.index and prevdate in bil.index:\n        prev=float(bil.loc[prevdate,'closeadj']); op=float(bil.loc[date,'adjopen']); cl=float(bil.loc[date,'closeadj'])\n        if all(np.isfinite([prev,op,cl])) and min(prev,op,cl)>0:\n            return op/prev-1,cl/op-1,cl/prev\n    if prevdate is None:\n        return 0.,0.,1.\n    key=(pd.Timestamp(date).to_period('M')-1).to_timestamp()\n    if key not in _CASH_YIELD:\n        raise RuntimeError(f'no causal GS3M yield for {date}: need {key.date()}')\n    annual=_CASH_YIELD[key]/100.0\n    elapsed=(pd.Timestamp(date)-pd.Timestamp(prevdate)).days\n    if elapsed<=0: raise RuntimeError(f'non-positive cash accrual gap {prevdate} -> {date}')\n    gap_days=max(elapsed-1,0)\n    gap_factor=(1.0+annual)**(gap_days/365.2425)\n    intra_factor=(1.0+annual)**(1.0/365.2425)\n    return gap_factor-1.0,intra_factor-1.0,gap_factor*intra_factor\n"""
    text = old.replace_once(text, old_cash, new_cash, "causal historical cash")

    # Optional forensic trace. It records the prior-close portfolio exposure and
    # the next close-to-close split-adjusted return for each continuing holding.
    # No trace value is read by strategy/accounting/controller logic.
    text = old.replace_once(
        text,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0\n    _trace_on=os.environ.get('RESEARCH_EMIT_POSITION_TRACE','0')=='1'; _trace_rows=[]; _trace_prev={}; _trace_prev_date=None",
        "trace state",
    )
    trace_anchor = """            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    trace_insert = """            if _trace_on:\n                # Attribute today's close-to-close security move to yesterday's close exposure.\n                for _tid0,_z in _trace_prev.items():\n                    _p1=clsig[_tid0]\n                    if finite(_p1) and _p1>0 and finite(_z['adj_close']) and _z['adj_close']>0:\n                        _sr=float(_p1)/float(_z['adj_close'])-1.0\n                        _trace_rows.append({'date':date,'holding_date':_trace_prev_date,'ticker':tick[_tid0],\n                                            'weight':_z['weight'],'security_return':_sr,'adv20':_z['adv20']})\n                _trace_prev={}\n                if finite(eq) and eq>0:\n                    for _s in book.slots:\n                        if not _s.held(): continue\n                        _tid0=int(_s.tid); _raw=clraw[_tid0]; _adj=clsig[_tid0]\n                        if finite(_raw) and _raw>0 and finite(_adj) and _adj>0:\n                            _trace_prev[_tid0]={'weight':float(_s.qty)*float(_raw)/float(eq),\n                                                'adj_close':float(_adj),\n                                                'adv20':(float(adv[_tid0]) if finite(adv[_tid0]) else np.nan)}\n                    _trace_prev_date=date\n            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    text = old.replace_once(text, trace_anchor, trace_insert, "trace observation")
    text = old.replace_once(
        text,
        "    out=pd.DataFrame(rows)\n    out.to_csv(OUT/'daily.csv',index=False)",
        "    out=pd.DataFrame(rows)\n    out.to_csv(OUT/'daily.csv',index=False)\n    if _trace_on:\n        pd.DataFrame(_trace_rows).to_csv(OUT/'position_trace.csv.gz',index=False,compression='gzip')",
        "trace output",
    )
    return text


def finalize(mode: str, output: Path) -> None:
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["warmup"] = {
        "start": WARMUP_START,
        "measurement_start": MEASUREMENT_START,
        "full_machine_state_carried": True,
        "measured_warmup_sessions": 0,
    }
    summary["defensive_cash_authority"] = {
        "source_id": "FRED:GS3M",
        "source_description": "Federal Reserve H.15 3-month constant-maturity Treasury yield, investment basis; monthly average",
        "causal_rule": "actual BIL when available; otherwise previous completed calendar month's GS3M with calendar-day accrual",
        "gs3m_sha256": old.sha256(CASH_AUTHORITY),
    }
    summary["max_history_measurement_start"] = MEASUREMENT_START
    trace_path = output / "position_trace.csv.gz"
    if trace_path.exists():
        summary["diagnostic_position_trace"] = {
            "file": trace_path.name,
            "observational_only": True,
            "return_domain": "prior-close portfolio weight times next split-adjusted close-to-close security return",
        }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path]
    if trace_path.exists():
        files.append(trace_path)
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{old.sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("nonpit", "fullpit"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    generated = Path("/tmp") / f"research_ldrc_corrected_{args.mode}.py"
    generated.write_text(transformed_source(args.mode, args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = args.mode
    print(
        f"[RUN] corrected retained research mode={args.mode} warmup={WARMUP_START} measurement={MEASUREMENT_START}",
        flush=True,
    )
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    old.postprocess(args.mode, args.output)
    finalize(args.mode, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())