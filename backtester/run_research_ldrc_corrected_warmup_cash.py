#!/usr/bin/env python3
"""Corrected retained-research LD-RC replay.

Runs the exact retained research implementation in non-PIT or full-PIT mode,
with a full 1997 machine warm-up and the same causal pre-BIL Treasury cash model
used by the corrected production replay. Output remains divergence-compatible.
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
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path]
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
