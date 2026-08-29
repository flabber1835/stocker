#!/usr/bin/env python3
"""Run the retained research LD-RC implementation on non-PIT or full-PIT metadata.

The strategy/accounting source is the frozen retained research script. This wrapper
changes data authority and reporting seams only. It emits daily evidence compatible
with production-vs-research divergence analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

SOURCE = Path("research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/ldrc_ab_replay_20260825.py")
PIT_MODEL_SOURCE = Path("backtester/experiments/2026-08-27-sector-abc/run.py")
EXPECTED_RESEARCH_COMMIT = "c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c"
END = "2026-07-31"
WINDOWS = {
    "5": ("2021-07-30", 5.0),
    "10": ("2016-07-29", 10.0),
    "15": ("2011-07-29", 15.0),
    "20": ("2006-07-31", 20.0),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(mode: str, output: Path) -> str:
    text = SOURCE.read_text(encoding="utf-8")
    if f"COMMIT = '{EXPECTED_RESEARCH_COMMIT}'" not in text:
        raise RuntimeError("retained research source identity changed")

    text = replace_once(
        text,
        "import zipfile, glob, math, json, hashlib, time, gc",
        "import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util",
        "imports",
    )
    text = replace_once(text, "ROOT = Path('/mnt/data')", "ROOT = Path('sharadar')", "root")
    text = replace_once(
        text,
        "OUT = ROOT / 'ldrc_ab_replay_20260825'",
        f"OUT = Path({str(output)!r})",
        "output",
    )
    text = replace_once(
        text,
        "START = pd.Timestamp('2006-07-31')",
        "START = pd.Timestamp('1998-01-02')",
        "start",
    )
    text = replace_once(
        text,
        "END = pd.Timestamp('2026-07-31')",
        "END = pd.Timestamp('2026-07-31')\nMODE = os.environ.get('RESEARCH_REPLAY_MODE', 'nonpit')\nPIT_MODE = MODE == 'fullpit'",
        "mode",
    )

    old_action = "    d=zcsv(ROOT/'SHARADAR_ACTIONS.zip',['date','action','ticker','value','contraticker'])"
    new_action = """    if PIT_MODE:\n        d=pd.read_csv(Path('PIT input data')/'ACTIONS_PIT_ONLY.csv.gz',compression='gzip',usecols=['date','action','ticker','value'],low_memory=False)\n        d['contraticker']=None\n    else:\n        d=zcsv(ROOT/'SHARADAR_ACTIONS.zip',['date','action','ticker','value','contraticker'])"""
    text = replace_once(text, old_action, new_action, "actions authority")

    old_init = "    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    new_init = """    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n    pit_model=None\n    if PIT_MODE:\n        spec=importlib.util.spec_from_file_location('research_pit_authority', Path('backtester/experiments/2026-08-27-sector-abc/run.py'))\n        if spec is None or spec.loader is None: raise RuntimeError('cannot load PIT authority model')\n        pitmod=importlib.util.module_from_spec(spec); spec.loader.exec_module(pitmod)\n        pit_model=pitmod.PITFF12(\n            Path('research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz'),\n            Path('research/sentinel-fastgate/pit-evidence/generated/sec_sic_submissions.csv.gz'),\n            {str(sid[i]):str(tick[i]) for i in range(n)})\n    def sector_key(tid, ds):\n        if not PIT_MODE: return sector[tid]\n        return pit_model.group(str(sid[tid]), str(ds), str(tick[tid]))\n    def issuer_key(tid, ds):\n        if not PIT_MODE: return issuer[tid]\n        ticker=str(tick[tid]); session=str(ds)\n        cik=pit_model._strict_prior(pit_model.cik_dates.get(ticker,()), pit_model.cik_values.get(ticker,()), session)\n        return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sid[tid]}'\n    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"""
    text = replace_once(text, old_init, new_init, "PIT authority initialization")

    text = replace_once(
        text,
        "held.append((tid,sector[tid],own,r21v,r63v,age,green,red))",
        "held.append((tid,sector_key(tid,ds),own,r21v,r63v,age,green,red))",
        "sector authority",
    )
    text = replace_once(
        text,
        "heldissuers={issuer[s.tid] for s in book.slots if s.held()}; resissuers={issuer[s.pending_tid] for s in book.slots if s.reserved()}",
        "heldissuers={issuer_key(s.tid,ds) for s in book.slots if s.held()}; resissuers={issuer_key(s.pending_tid,ds) for s in book.slots if s.reserved()}",
        "issuer sets",
    )
    text = replace_once(
        text,
        "if issuer[tid] in heldissuers or issuer[tid] in resissuers: continue",
        "if issuer_key(tid,ds) in heldissuers or issuer_key(tid,ds) in resissuers: continue",
        "issuer admission",
    )
    text = replace_once(
        text,
        "s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer[tid]); ad+=1",
        "s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "issuer reservation",
    )

    old_year = "        print(f'YEAR {y} rows={len(d):,} seconds={time.time()-t0:.1f}',flush=True)"
    new_year = """        if rows:\n            _curve=pd.Series([float(r['control_nav']) for r in rows], index=pd.to_datetime([r['date'] for r in rows]))\n            _yrs=(_curve.index[-1]-_curve.index[0]).days/365.2425\n            _cagr=float((_curve.iloc[-1]/_curve.iloc[0])**(1/_yrs)-1) if _yrs>0 and _curve.iloc[-1]>0 else float('nan')\n            print(f'[YEAR-END] mode={MODE} year={y} session={_curve.index[-1].date()} multiple={_curve.iloc[-1]/_curve.iloc[0]:.10f} cagr={_cagr:.10%}',flush=True)\n        print(f'YEAR {y} rows={len(d):,} seconds={time.time()-t0:.1f}',flush=True)"""
    text = replace_once(text, old_year, new_year, "year-end checkpoint")

    text = replace_once(
        text,
        "'evidence_level':'exploratory_only_non_PIT_TICKERS_metadata',",
        "'evidence_level':('full_stack_PIT_SEC_CIK_SIC_plus_PIT_ACTIONS' if PIT_MODE else 'research_non_PIT_current_TICKERS_and_ACTIONS'),\n        'replay_mode':MODE,",
        "evidence label",
    )

    # Guard the known economically-active metadata seams. Full-PIT must not retain
    # current sector/related-ticker issuer authority at admissions or breadth.
    if mode == "fullpit":
        forbidden = [
            "held.append((tid,sector[tid]",
            "heldissuers={issuer[s.tid]",
            "if issuer[tid] in heldissuers",
            "resissuers.add(issuer[tid])",
        ]
        for needle in forbidden:
            if needle in text:
                raise RuntimeError(f"full-PIT transform retained forbidden metadata seam: {needle}")
    return text


def metric_block(frame: pd.DataFrame, column: str, start: str, years: float | None) -> dict:
    x = frame[frame["date"] >= start][["date", column]].dropna().copy()
    if x.empty:
        raise RuntimeError(f"{column}: empty metric window from {start}")
    values = x[column].astype(float).to_numpy()
    norm = values / values[0]
    rets = norm[1:] / norm[:-1] - 1.0
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    peak = np.maximum.accumulate(norm)
    dd = float(np.min(norm / peak - 1.0))
    if years is None:
        elapsed = (pd.Timestamp(x.iloc[-1]["date"]) - pd.Timestamp(x.iloc[0]["date"])).days / 365.2425
        years = elapsed
    cagr = float(norm[-1] ** (1.0 / years) - 1.0)
    return {
        "start": str(pd.Timestamp(x.iloc[0]["date"]).date()),
        "end": str(pd.Timestamp(x.iloc[-1]["date"]).date()),
        "sessions": int(len(x)),
        "cagr": cagr,
        "max_drawdown": dd,
        "sharpe": sharpe,
        "ending_multiple": float(norm[-1]),
    }


def postprocess(mode: str, output: Path) -> None:
    daily_path = output / "daily.csv"
    summary_path = output / "summary.json"
    if not daily_path.exists() or not summary_path.exists():
        raise RuntimeError("research replay did not emit required outputs")
    daily = pd.read_csv(daily_path, parse_dates=["date"])
    daily = daily[daily["date"] <= pd.Timestamp(END)].copy()
    daily.rename(columns={
        "shadow_equity": "research_wealth_core_equity",
        "open_equity": "research_wealth_core_open_equity",
        "control_nav": "research_nav",
        "control_allocation": "research_allocation",
    }, inplace=True)
    required = {"date", "research_wealth_core_equity", "research_nav", "research_allocation", "spy_nav"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"research daily evidence missing: {sorted(missing)}")
    metric_rows = []
    starts = dict(WINDOWS)
    starts["max"] = (str(daily.iloc[0]["date"].date()), None)
    for window in ("5", "10", "15", "20", "max"):
        start, years = starts[window]
        for variant, column in (("RESEARCH", "research_nav"), ("SPY", "spy_nav")):
            block = metric_block(daily, column, start, years)
            metric_rows.append({"window_years": window, "variant": variant, **block})
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output / "metrics.csv", index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({
        "status": "PASS",
        "mode": mode,
        "research_strategy_source": str(SOURCE),
        "research_strategy_source_sha256": sha256(SOURCE),
        "research_embedded_commit": EXPECTED_RESEARCH_COMMIT,
        "full_stack_pit": mode == "fullpit",
        "pit_authority": {
            "sector": "strict-prior SEC CIK -> strict-prior SEC SIC -> FF12" if mode == "fullpit" else "current Sharadar sector",
            "issuer": "strict-prior SEC CIK; unknown issuer is security singleton" if mode == "fullpit" else "current Sharadar relatedtickers/permaticker grouping",
            "actions": "PIT ACTIONS" if mode == "fullpit" else "current Sharadar ACTIONS snapshot",
            "exchange": "not economically active",
            "category": "current TICKERS field retained under prior zero-delta/equivalence evidence",
        },
        "measurement_windows": ["5", "10", "15", "20", "max"],
        "daily_evidence_columns": sorted(required),
    })
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    daily.to_csv(
        output / "daily.csv.gz",
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    daily_path.unlink()
    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    print("[RESULT]", mode)
    print(metrics.to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("nonpit", "fullpit"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    generated = Path("/tmp") / f"research_ldrc_{args.mode}.py"
    generated.write_text(transformed_source(args.mode, args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = args.mode
    print(f"[RUN] retained research LD-RC mode={args.mode} source_sha256={sha256(SOURCE)}", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    postprocess(args.mode, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
