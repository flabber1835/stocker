#!/usr/bin/env python3
"""One-shot sealed LD-RC OOS replay on the best-effort S&P 500 PIT universe.

The strategy source and relevant transformation wrappers are hash-frozen before
the holdout subprocess runs.  This harness changes the universe/data-authority
seams only.  It does not alter LD-RC thresholds, ranking math, sizing, exit
rules, transaction costs, or controller state transitions.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

CORRECTED_WRAPPER = Path("backtester/run_research_ldrc_corrected_warmup_cash.py")
OLD_WRAPPER = Path("backtester/run_research_ldrc_nonpit_vs_fullpit.py")
STRATEGY_SOURCE = Path(
    "research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/"
    "ldrc_ab_replay_20260825.py"
)
PIT_MODEL_SOURCE = Path("backtester/experiments/2026-08-27-sector-abc/run.py")

EXPECTED_BLOBS = {
    str(STRATEGY_SOURCE): "6c30a617b7ee615849dcf09f43612c1483703aa3",
    str(CORRECTED_WRAPPER): "0849f098d4faca4491c3961769bafdc3a188587a",
    str(OLD_WRAPPER): "89f8a9c77963d2d1134530a422fa81d1e20bc48b",
    str(PIT_MODEL_SOURCE): "32db7c1284996ca474e88657c2a37c3946a598d3",
}
EXPECTED_RESEARCH_COMMIT = "c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c"
EXPECTED_MEMBERSHIP_DATASET_HASH = (
    "1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d"
)
WINDOW_START = "1997-12-31"
WINDOW_END = "2005-12-30"
STARTING_EQUITY = 100_000_000.0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    h = hashlib.sha1()
    h.update(f"blob {len(data)}\0".encode("ascii"))
    h.update(data)
    return h.hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def _load_corrected_module():
    spec = importlib.util.spec_from_file_location("sp500_corrected_ldrc", CORRECTED_WRAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load corrected LD-RC wrapper {CORRECTED_WRAPPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _freeze(universe_root: Path, output: Path) -> dict:
    universe_summary = json.loads(
        (universe_root / "best-effort-summary.json").read_text(encoding="utf-8")
    )
    if universe_summary.get("status") != "BEST_EFFORT_RUNNABLE":
        raise RuntimeError("best-effort S&P universe is not runnable")
    if universe_summary.get("formal_pit_certified") is not False:
        raise RuntimeError("best-effort universe unexpectedly claims formal certification")
    if universe_summary.get("membership_dataset_hash") != EXPECTED_MEMBERSHIP_DATASET_HASH:
        raise RuntimeError("best-effort universe membership hash changed")
    if universe_summary.get("window_start") != WINDOW_START or universe_summary.get("window_end") != WINDOW_END:
        raise RuntimeError("best-effort universe window changed")

    observed_blobs = {}
    for path_text, expected in EXPECTED_BLOBS.items():
        path = Path(path_text)
        observed = _git_blob_sha1(path)
        if observed != expected:
            raise RuntimeError(f"frozen source changed: {path}: {observed} != {expected}")
        observed_blobs[path_text] = observed

    strategy_text = STRATEGY_SOURCE.read_text(encoding="utf-8")
    marker = f"COMMIT = '{EXPECTED_RESEARCH_COMMIT}'"
    if marker not in strategy_text:
        raise RuntimeError("retained strategy embedded commit changed")

    eligibility = universe_root / "sp500-best-effort-eligibility.csv.gz"
    freeze = {
        "schema": "backtester.sp500-sealed-oos-freeze/1",
        "status": "SEALED_BEFORE_HOLDOUT_EXECUTION",
        "sealed_window": [WINDOW_START, WINDOW_END],
        "strategy_embedded_commit": EXPECTED_RESEARCH_COMMIT,
        "git_blob_sha1": observed_blobs,
        "membership_dataset_hash": EXPECTED_MEMBERSHIP_DATASET_HASH,
        "best_effort_universe_summary_sha256": _sha256(
            universe_root / "best-effort-summary.json"
        ),
        "best_effort_eligibility_sha256": _sha256(eligibility),
        "harness_commit": os.environ.get("GITHUB_SHA") or None,
        "formal_pit_certified": False,
        "holdout_policy": (
            "strategy/data-authority configuration frozen before subprocess execution; "
            "no LD-RC threshold or strategy change is permitted after observing results "
            "while retaining an untouched-holdout claim"
        ),
    }
    path = output / "freeze.json"
    path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return freeze


def _sealed_source(corrected, output: Path) -> str:
    text = corrected.transformed_source("fullpit", output)

    text = _replace_once(
        text,
        "START = pd.Timestamp('1998-01-02')",
        f"START = pd.Timestamp('{WINDOW_START}')",
        "sealed start",
    )
    text = _replace_once(
        text,
        "END = pd.Timestamp('2026-07-31')",
        f"END = pd.Timestamp('{WINDOW_END}')",
        "sealed end",
    )

    # Load the already-materialized dated eligibility witness.  It maps the exact
    # historical SEP ticker used on each session to its causal security ID.
    marker = "MODE = os.environ.get('RESEARCH_REPLAY_MODE', 'nonpit')\nPIT_MODE = MODE == 'fullpit'"
    injected = marker + r"""
_SP500_ELIGIBILITY_PATH=Path(os.environ['SP500_BEST_EFFORT_ELIGIBILITY'])
_sp500_frame=pd.read_csv(_SP500_ELIGIBILITY_PATH,compression='gzip',dtype=str)
_sp500_frame['date']=_sp500_frame['date'].astype(str)
_sp500_frame['resolved_ticker']=_sp500_frame['resolved_ticker'].astype(str)
_sp500_frame['security_id']=_sp500_frame['security_id'].astype(str)
_SP500_BY_DATE={}
for _ds,_g in _sp500_frame.groupby('date',sort=False):
    _pairs={}
    for _r in _g.itertuples(index=False):
        _tk=str(_r.resolved_ticker); _sid=str(_r.security_id)
        _prior=_pairs.get(_tk)
        if _prior is not None and _prior != _sid:
            raise RuntimeError(f'conflicting sealed S&P security IDs for {_tk} on {_ds}: {_prior} vs {_sid}')
        _pairs[_tk]=_sid
    _SP500_BY_DATE[str(_ds)]=_pairs
_SP500_ALL_TICKERS=set(_sp500_frame['resolved_ticker'].astype(str))
_SP500_SEEN_SID={}

def sp500_security_id(tid,ds):
    _tk=str(tick[int(tid)])
    _sid=_SP500_BY_DATE.get(str(ds),{}).get(_tk)
    if _sid is not None:
        _SP500_SEEN_SID[_tk]=_sid
        return _sid
    _sid=_SP500_SEEN_SID.get(_tk)
    return _sid if _sid is not None else f'TICKER:{_tk}'
"""
    text = _replace_once(text, marker, injected, "sealed universe load")

    # Verify that every historical mapped ticker can be represented by the retained
    # replay's ticker index.  This is only an indexing seam; eligibility itself is
    # supplied by the dated PIT witness.
    old_init = (
        "    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n"
        "    pit_model=None"
    )
    new_init = (
        "    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n"
        "    _missing_sp500=sorted(_SP500_ALL_TICKERS-set(map(str,tick)))\n"
        "    if _missing_sp500: raise RuntimeError(f'sealed S&P mapped tickers absent from replay index: {_missing_sp500[:20]}')\n"
        "    pit_model=None"
    )
    text = _replace_once(text, old_init, new_init, "ticker-index witness")

    # Remove economically-active current TICKERS category/listing fields.  S&P
    # membership plus exact-session SEP observation establishes the security's
    # eligibility domain for this best-effort experiment.
    old_elig = (
        "elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&"
        "np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&"
        "np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    )
    new_elig = (
        "_sp500_today=_SP500_BY_DATE.get(ds,{})\n"
        "            _sp500_ok=np.array([str(tick[int(_i)]) in _sp500_today for _i in tids],dtype=bool)\n"
        "            elig=_sp500_ok&continuous&np.isfinite(mm)&np.isfinite(rr)&"
        "np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&"
        "np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    )
    text = _replace_once(text, old_elig, new_elig, "S&P eligibility gate")

    # Use causal security IDs from the eligibility witness for deterministic
    # tie-breaking, not current vendor permaticker values.
    text = _replace_once(
        text,
        "sid_et=sid[et]; ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]",
        "sid_et=np.array([sp500_security_id(int(_i),ds) for _i in et],dtype=object); ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]",
        "causal momentum tie-break",
    )
    text = _replace_once(
        text,
        "ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]",
        "_pool_sid=np.array([sp500_security_id(int(_i),ds) for _i in pool],dtype=object); ordscore=np.lexsort((tick[pool],_pool_sid,-score[pool])); durable=pool[ordscore]",
        "causal score tie-break",
    )

    # The full-PIT sector/issuer transform in the existing wrapper already uses
    # strict-prior SEC evidence.  Replace its singleton/cache security key with
    # the causal S&P security ID so current permaticker is not economically active.
    text = _replace_once(
        text,
        "return pit_model.group(str(sid[tid]), str(ds), str(tick[tid]))",
        "return pit_model.group(sp500_security_id(tid,ds), str(ds), str(tick[tid]))",
        "causal sector security key",
    )
    text = _replace_once(
        text,
        "return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sid[tid]}'",
        "return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sp500_security_id(tid,ds)}'",
        "causal issuer singleton",
    )

    # Do not expose the previously researched Candidate A/B holdout performance.
    # They remain inert side calculations in the retained source and do not affect
    # the control LD-RC path.
    text = _replace_once(
        text,
        "'metrics':{k:metrics(idx[f'{k}_nav']) for k in ('control','A','B')},",
        "'metrics':{'control':metrics(idx['control_nav'])},",
        "suppress candidate metrics",
    )
    text = _replace_once(
        text,
        "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,",
        "'candidate_performance_suppressed_for_sealed_oos':True,",
        "suppress candidate diagnostics",
    )
    return text


def _metric(frame: pd.DataFrame, column: str, start: pd.Timestamp) -> dict:
    x = frame[frame["date"] >= start][["date", column]].dropna().copy()
    if len(x) < 2:
        raise RuntimeError(f"{column}: insufficient rows from {start.date()}")
    values = x[column].astype(float).to_numpy()
    if values[0] <= 0 or values[-1] <= 0 or not np.all(np.isfinite(values)):
        raise RuntimeError(f"{column}: invalid values")
    normalized = values / values[0]
    returns = normalized[1:] / normalized[:-1] - 1.0
    elapsed = (x.iloc[-1]["date"] - x.iloc[0]["date"]).days / 365.2425
    if elapsed <= 0:
        raise RuntimeError(f"{column}: non-positive elapsed years")
    cagr = float(normalized[-1] ** (1.0 / elapsed) - 1.0)
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else float("nan")
    sharpe = (
        float(np.mean(returns) / std * math.sqrt(252.0))
        if std > 0 and math.isfinite(std) else float("nan")
    )
    peak = np.maximum.accumulate(normalized)
    return {
        "start": str(x.iloc[0]["date"].date()),
        "end": str(x.iloc[-1]["date"].date()),
        "sessions": int(len(x)),
        "elapsed_years": elapsed,
        "cagr": cagr,
        "max_drawdown": float(np.min(normalized / peak - 1.0)),
        "sharpe": sharpe,
        "ending_multiple": float(normalized[-1]),
    }


def _first_invested_session(frame: pd.DataFrame) -> pd.Timestamp:
    equity = frame["shadow_equity"].astype(float).to_numpy()
    changed = np.flatnonzero(np.abs(equity - STARTING_EQUITY) > 1e-4)
    if not len(changed):
        raise RuntimeError("Wealth Core never became economically invested in sealed OOS")
    return pd.Timestamp(frame.iloc[int(changed[0])]["date"])


def run(*, universe_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    freeze = _freeze(universe_root, output)

    corrected = _load_corrected_module()
    generated = output / "_sealed_generated_ldrc.py"
    generated.write_text(_sealed_source(corrected, output), encoding="utf-8")

    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    env["SP500_BEST_EFFORT_ELIGIBILITY"] = str(
        (universe_root / "sp500-best-effort-eligibility.csv.gz").resolve()
    )
    print(
        f"[SEALED-RUN] window={WINDOW_START}..{WINDOW_END} "
        f"freeze_sha256={_sha256(output / 'freeze.json')}",
        flush=True,
    )
    subprocess.run([sys.executable, str(generated)], check=True, env=env)

    raw_daily = output / "daily.csv"
    raw_summary = output / "summary.json"
    if not raw_daily.exists() or not raw_summary.exists():
        raise RuntimeError("retained LD-RC replay did not emit daily/summary outputs")

    engine_summary = json.loads(raw_summary.read_text(encoding="utf-8"))
    if set((engine_summary.get("metrics") or {}).keys()) != {"control"}:
        raise RuntimeError("sealed engine exposed non-control candidate metrics")
    if engine_summary.get("candidate_performance_suppressed_for_sealed_oos") is not True:
        raise RuntimeError("sealed candidate-performance suppression witness missing")
    shutil.move(str(raw_summary), str(output / "engine-summary.json"))

    daily = pd.read_csv(raw_daily, parse_dates=["date"])
    daily = daily[
        (daily["date"] >= pd.Timestamp(WINDOW_START))
        & (daily["date"] <= pd.Timestamp(WINDOW_END))
    ].copy()
    if daily.empty or str(daily.iloc[-1]["date"].date()) != WINDOW_END:
        raise RuntimeError(
            f"sealed daily evidence does not reach {WINDOW_END}: "
            f"{None if daily.empty else daily.iloc[-1]['date']}"
        )
    required = {"date", "shadow_equity", "control_nav", "spy_nav", "control_allocation"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"sealed daily evidence missing columns: {sorted(missing)}")

    first_invested = _first_invested_session(daily)
    full_start = pd.Timestamp(daily.iloc[0]["date"])
    metric_rows = []
    for window_name, start in (
        ("active_oos", first_invested),
        ("full_available_tape_including_warmup", full_start),
    ):
        for variant, column in (("LD_RC", "control_nav"), ("SPY", "spy_nav")):
            metric_rows.append({
                "window": window_name,
                "variant": variant,
                **_metric(daily, column, start),
            })
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output / "metrics.csv", index=False)

    # Final artifact contains only the control strategy path.  Delete the retained
    # source's A/B side-calculation columns and uncompressed raw file.
    candidate_cols = [
        c for c in daily.columns
        if c.startswith("A_") or c.startswith("B_")
    ]
    daily.drop(columns=candidate_cols, inplace=True, errors="ignore")
    daily.to_csv(output / "daily.csv.gz", index=False, compression={"method":"gzip","mtime":0})
    raw_daily.unlink()
    generated.unlink(missing_ok=True)

    universe_summary = json.loads(
        (universe_root / "best-effort-summary.json").read_text(encoding="utf-8")
    )
    active_ldrc = next(
        r for r in metric_rows if r["window"] == "active_oos" and r["variant"] == "LD_RC"
    )
    active_spy = next(
        r for r in metric_rows if r["window"] == "active_oos" and r["variant"] == "SPY"
    )
    summary = {
        "schema": "backtester.sp500-sealed-oos-result/1",
        "status": "PASS",
        "experiment": "SEALED_SP500_BEST_EFFORT_PIT_OOS",
        "formal_pit_certified": False,
        "best_effort_pit": True,
        "one_shot_holdout_observation_completed": True,
        "sealed_window": [WINDOW_START, WINDOW_END],
        "first_invested_session": str(first_invested.date()),
        "strategy_embedded_commit": EXPECTED_RESEARCH_COMMIT,
        "strategy_git_blob_sha1": EXPECTED_BLOBS[str(STRATEGY_SOURCE)],
        "membership_dataset_hash": EXPECTED_MEMBERSHIP_DATASET_HASH,
        "eligibility_sha256": freeze["best_effort_eligibility_sha256"],
        "universe": universe_summary,
        "active_oos": {
            "ld_rc": active_ldrc,
            "spy": active_spy,
            "cagr_spread_ldrc_minus_spy": active_ldrc["cagr"] - active_spy["cagr"],
        },
        "interpretation_guard": (
            "This is a one-shot best-effort PIT viability result, not formal PIT certification. "
            "The pre-2001 membership source is explicitly incomplete/best-effort. "
            "Any LD-RC strategy change after observing this result consumes this holdout for the revised strategy."
        ),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    members = [
        output / "freeze.json",
        output / "engine-summary.json",
        output / "summary.json",
        output / "metrics.csv",
        output / "daily.csv.gz",
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(**vars(args))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
