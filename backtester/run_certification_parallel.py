#!/usr/bin/env python3
"""Strict-PIT parallel certification orchestrator.

The full machine warms before measurement. Production and retained research run
concurrently. Each child emits quarter-end cumulative CAGR checkpoints; this
process joins them and prints production/research/SPY blocks when both arrive.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading

import pandas as pd

WARMUP_START = pd.Timestamp("1997-01-02")
MEASUREMENT_START = pd.Timestamp("1998-01-02")
PRODUCTION_WRAPPER = Path("backtester/run_production_strict_pit_certification.py")
RESEARCH_WRAPPER = Path("backtester/run_research_strict_pit_certification.py")
CHECKPOINT = re.compile(r"^\[CERT_CAGR\] role=(production|research) date=(\d{4}-\d{2}-\d{2}) cagr=([-+0-9.eE]+)$")


def _read_production(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip", parse_dates=["date"])
    required = {"date", "D_nav", "SPY_level"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"production daily evidence missing {sorted(required-set(df.columns))}")
    return df[["date", "D_nav", "SPY_level"]].rename(columns={"D_nav": "nav", "SPY_level": "spy"}).sort_values("date")


def _read_research(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip", parse_dates=["date"])
    required = {"date", "research_nav", "spy_nav"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"research daily evidence missing {sorted(required-set(df.columns))}")
    return df[["date", "research_nav", "spy_nav"]].rename(columns={"research_nav": "nav", "spy_nav": "spy"}).sort_values("date")


def _verify_spy_path_equivalence(
    production: pd.DataFrame,
    research: pd.DataFrame,
    tolerance: float = 1e-10,
) -> dict:
    benchmark = production[["date", "spy"]].merge(
        research[["date", "spy"]],
        on="date",
        suffixes=("_production", "_research"),
        how="outer",
        indicator=True,
    ).sort_values("date")
    if benchmark.empty or not benchmark["_merge"].eq("both").all():
        raise RuntimeError("production/research SPY benchmark session axes diverged")
    benchmark = benchmark.drop(columns=["_merge"])
    p = pd.to_numeric(benchmark.spy_production, errors="coerce")
    r = pd.to_numeric(benchmark.spy_research, errors="coerce")
    if not (p.map(math.isfinite).all() and r.map(math.isfinite).all()):
        raise RuntimeError("production/research SPY benchmark contains non-finite levels")
    if not ((p > 0).all() and (r > 0).all()):
        raise RuntimeError("production/research SPY benchmark contains non-positive levels")
    p_anchor = float(p.iloc[0])
    r_anchor = float(r.iloc[0])
    p_normalized = p / p_anchor
    r_normalized = r / r_anchor
    max_delta = float((p_normalized - r_normalized).abs().max())
    if max_delta > tolerance:
        raise RuntimeError(
            "production/research SPY benchmark paths diverged after measurement normalization"
        )
    return {
        "normalization_session": pd.Timestamp(benchmark.date.iloc[0]).date().isoformat(),
        "production_anchor": p_anchor,
        "research_anchor": r_anchor,
        "max_normalized_absolute_delta": max_delta,
        "sessions_compared": int(len(benchmark)),
    }


def _spy_levels(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip", low_memory=False)
    required = {"ticker", "date", "close_to_close_factor"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"SPY factor evidence missing {sorted(required-set(df.columns))}")
    df = df[df.ticker.astype(str).eq("SPY")].copy()
    df["date"] = pd.to_datetime(df.date.astype(str).str[:10])
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    level = 1.0
    levels = []
    prior = False
    for row in df.itertuples(index=False):
        factor = float(row.close_to_close_factor) if pd.notna(row.close_to_close_factor) else float("nan")
        if prior:
            if not math.isfinite(factor) or factor <= 0:
                raise RuntimeError(f"invalid SPY close factor on {row.date}")
            level *= factor
        levels.append((pd.Timestamp(row.date), level))
        prior = True
    out = pd.DataFrame(levels, columns=["date", "nav"])
    return out[out.date >= MEASUREMENT_START].reset_index(drop=True)


def _value_on_or_before(df: pd.DataFrame, when: str, column: str = "nav") -> tuple[pd.Timestamp, float]:
    q = df[df.date <= pd.Timestamp(when)]
    if q.empty:
        raise RuntimeError(f"no evidence on/before {when}")
    row = q.iloc[-1]
    return pd.Timestamp(row.date), float(row[column])


def _cagr(start_value: float, end_value: float, end_date: str) -> float:
    elapsed = (date.fromisoformat(end_date) - MEASUREMENT_START.date()).days / 365.2425
    if elapsed <= 0:
        return 0.0
    if start_value <= 0 or end_value <= 0:
        raise RuntimeError("non-positive value in cumulative CAGR")
    return (end_value / start_value) ** (1.0 / elapsed) - 1.0


def _reader(role: str, pipe, events: queue.Queue) -> None:
    try:
        for raw in iter(pipe.readline, ""):
            line = raw.rstrip("\n")
            print(f"[{role}] {line}", flush=True)
            match = CHECKPOINT.match(line)
            if match:
                events.put(("checkpoint", role, match.group(2), float(match.group(3))))
    finally:
        pipe.close()
        events.put(("eof", role, None, None))


def _stop_parallel(processes: dict[str, subprocess.Popen], failed_role: str, failed_rc: int) -> dict[str, int | None]:
    for role, process in processes.items():
        if role != failed_role and process.poll() is None:
            print(
                f"[CERTIFICATION ABORT] {failed_role} exited {failed_rc}; terminating {role}",
                flush=True,
            )
            process.terminate()
    for process in processes.values():
        if process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return {role: process.poll() for role, process in processes.items()}


def _first_divergence(prod: pd.DataFrame, research: pd.DataFrame, tolerance: float) -> dict | None:
    merged = prod[["date", "nav"]].merge(
        research[["date", "nav"]], on="date", suffixes=("_production", "_research"), how="inner"
    )
    merged = merged[merged.date >= MEASUREMENT_START]
    for row in merged.itertuples(index=False):
        p, r = float(row.nav_production), float(row.nav_research)
        delta = abs(p - r)
        scale = max(abs(p), abs(r), 1.0)
        if delta > tolerance * scale:
            return {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "production_nav": p,
                "research_nav": r,
                "absolute_delta": delta,
                "relative_delta": delta / scale,
            }
    return None


def _verify_authority(path: Path, role: str) -> dict:
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("role") != role:
        raise RuntimeError(f"{role} metadata audit has wrong role")
    if audit.get("current_SHARADAR_TICKERS_economically_active_fields") != []:
        raise RuntimeError(f"{role} retained current SHARADAR_TICKERS economic authority")
    if audit.get("fallbacks", {}).get("security_type_unknown") != "ineligible":
        raise RuntimeError(f"{role} security-type fallback is not fail-closed")
    if role == "production":
        anchor = audit.get("feed_anchor_issuer_authority") or {}
        if anchor.get("authority") != "strict-prior SEC CIK; unknown issuer is causal security singleton":
            raise RuntimeError("production audit lacks strict feed-anchor issuer authority")
        if int(anchor.get("anchors", 0)) <= 0:
            raise RuntimeError("production replay never exercised a strict feed anchor")
        if int(anchor.get("anchors", 0)) != int(anchor.get("sec_cik", 0)) + int(anchor.get("unknown_singleton", 0)):
            raise RuntimeError("production strict feed-anchor issuer counts do not conserve")
    return audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--spy-factors", type=Path, required=True)
    ap.add_argument("--lab-root", type=Path, default=Path("."))
    ap.add_argument("--main-root", type=Path, default=Path("main-src"))
    ap.add_argument("--divergence-tolerance", type=float, default=1e-10)
    args = ap.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    prod_out = args.output_root / "production"
    research_out = args.output_root / "research"
    prod_out.mkdir(parents=True, exist_ok=True)
    research_out.mkdir(parents=True, exist_ok=True)

    spy = _spy_levels(args.spy_factors)
    spy_start_date, spy_start = _value_on_or_before(spy, MEASUREMENT_START.date().isoformat())
    if spy_start_date.date() != MEASUREMENT_START.date():
        raise RuntimeError(f"SPY measurement anchor is {spy_start_date.date()}, expected {MEASUREMENT_START.date()}")

    env = dict(os.environ)
    env["CERTIFICATION_STRICT_PIT"] = "1"
    env["CERTIFICATION_WARMUP_START"] = WARMUP_START.date().isoformat()
    env["CERTIFICATION_MEASUREMENT_START"] = MEASUREMENT_START.date().isoformat()
    env["PYTHONUNBUFFERED"] = "1"
    lab_root = str(args.lab_root.resolve())
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (lab_root, existing_pythonpath) if part
    )

    print(
        f"[CERTIFICATION] strict PIT warmup={WARMUP_START.date()} measurement={MEASUREMENT_START.date()}",
        flush=True,
    )
    for d in ("1997-03-31", "1997-06-30", "1997-09-30", "1997-12-31"):
        print(f"[WARMUP] {d} full machine state accumulating; CAGR=N/A", flush=True)

    prod_cmd = [
        sys.executable, str(PRODUCTION_WRAPPER),
        "--lab-root", str(args.lab_root),
        "--main-root", str(args.main_root),
        "--output", str(prod_out),
    ]
    research_cmd = [
        sys.executable, str(RESEARCH_WRAPPER),
        "--mode", "fullpit",
        "--output", str(research_out),
    ]
    prod = subprocess.Popen(prod_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    research = subprocess.Popen(research_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    processes = {"production": prod, "research": research}
    assert prod.stdout is not None and research.stdout is not None
    events: queue.Queue = queue.Queue()
    threads = [
        threading.Thread(target=_reader, args=("production", prod.stdout, events), daemon=True),
        threading.Thread(target=_reader, args=("research", research.stdout, events), daemon=True),
    ]
    for thread in threads:
        thread.start()

    checkpoints: dict[str, dict[str, float]] = {}
    emitted: set[str] = set()
    eof = set()
    while len(eof) < 2:
        event = None
        try:
            event = events.get(timeout=0.5)
        except queue.Empty:
            pass

        failed = [
            (role, int(rc))
            for role, process in processes.items()
            if (rc := process.poll()) is not None and int(rc) != 0
        ]
        if failed:
            failed_role, failed_rc = failed[0]
            rc_map = _stop_parallel(processes, failed_role, failed_rc)
            for thread in threads:
                thread.join(timeout=5)
            raise RuntimeError(
                "parallel strict-PIT replay failed fast "
                f"failed_role={failed_role} failed_rc={failed_rc} exit_codes={rc_map}"
            )

        if event is None:
            continue
        kind, role, session, value = event
        if kind == "eof":
            eof.add(role)
            continue
        bucket = checkpoints.setdefault(session, {})
        bucket[role] = value
        if session not in emitted and {"production", "research"}.issubset(bucket):
            spy_date, spy_value = _value_on_or_before(spy, session)
            if spy_date.date().isoformat() != session:
                raise RuntimeError(f"SPY checkpoint misalignment: requested {session}, got {spy_date.date()}")
            spy_cagr = _cagr(spy_start, spy_value, session)
            print(f"[CERTIFICATION PROGRESS] {session}", flush=True)
            print(f"Research cumulative CAGR:      {bucket['research']*100:10.4f}%", flush=True)
            print(f"Production cumulative CAGR:    {bucket['production']*100:10.4f}%", flush=True)
            print(f"SPY cumulative CAGR:           {spy_cagr*100:10.4f}%", flush=True)
            print("", flush=True)
            emitted.add(session)

    p_rc = prod.wait()
    r_rc = research.wait()
    for thread in threads:
        thread.join()
    if p_rc != 0 or r_rc != 0:
        raise RuntimeError(f"parallel strict-PIT replay failed production={p_rc} research={r_rc}")

    prod_df = _read_production(prod_out / "daily.csv.gz")
    research_df = _read_research(research_out / "daily.csv.gz")
    pa = _verify_authority(prod_out / "metadata_authority_audit.json", "production")
    ra = _verify_authority(research_out / "metadata_authority_audit.json", "research")

    benchmark_equivalence = _verify_spy_path_equivalence(prod_df, research_df)

    divergence = _first_divergence(prod_df, research_df, args.divergence_tolerance)
    audit = {
        "schema": "backtester.strict-pit-parallel-certification/1",
        "warmup_start": WARMUP_START.date().isoformat(),
        "measurement_start": MEASUREMENT_START.date().isoformat(),
        "progress_cadence": "calendar-quarter, live joined production/research checkpoints",
        "cagr_basis": f"cumulative from {MEASUREMENT_START.date().isoformat()}",
        "research_production_divergence_tolerance": args.divergence_tolerance,
        "spy_benchmark_equivalence": benchmark_equivalence,
        "first_divergence": divergence,
        "production_metadata_authority": pa,
        "research_metadata_authority": ra,
        "quarterly_blocks_emitted": sorted(emitted),
    }
    (args.output_root / "certification_progress_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if divergence is not None:
        print("[CERTIFICATION FAIL] research/production divergence detected", flush=True)
        print(json.dumps(divergence, sort_keys=True), flush=True)
        return 2
    print("[CERTIFICATION PASS] production and retained research are equivalent within tolerance", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
