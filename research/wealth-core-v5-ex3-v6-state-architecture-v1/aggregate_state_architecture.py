#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

ARCH = {
    "current": ("A_allocation", "A_nav"),
    "state_minimal_60": ("B_allocation", "B_nav"),
    "stateless_1": ("control_allocation", "control_nav"),
}
EXPECTED_START = "2006-07-31"
EXPECTED_END = "2026-07-31"
EXPECTED_SESSIONS = 5032
EXPECTED_SELECTED_CONFIG = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}
EXPECTED_CURRENT = {
    "cagr": 0.215572258056,
    "max_drawdown": -0.273755457386,
    "sharpe_daily_252": 1.1210581190,
}
EXPECTED_FAULTS = {
    0: {"type": "security_leave_one_out", "security_id": "301606049357818446"},
    1: {"type": "security_leave_one_out", "security_id": "1040633074096912075"},
    2: {"type": "security_leave_one_out", "security_id": "277347208162984956"},
    3: {"type": "security_leave_one_out", "security_id": "727329233939509358"},
    4: {"type": "security_leave_one_out", "security_id": "425931792436652190"},
    5: {"type": "security_leave_one_out", "security_id": "311453645065866101"},
    6: {"type": "universe_dropout", "fraction": 0.01, "seed": 11},
}
ALLOWED_LEVELS = np.asarray([0.0, .55, .65, 1.0], dtype=float)
REQUIRED_COLUMNS = {
    "date", "research_selected_positions", "shadow_equity", "wc_dd", "damaged", "green",
    "native_close_target", "minimal_native_close_target", "stateless_native_close_target", "effective_native",
    "A_allocation", "B_allocation", "control_allocation", "A_nav", "B_nav", "control_nav",
}


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def find_one(root: Path, name: str) -> Path:
    xs = list(root.rglob(name))
    if len(xs) != 1:
        fail(f"expected one {name} under {root}, found {len(xs)}")
    return xs[0]


def read_hash(path: Path) -> str:
    value = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        fail(f"invalid SHA-256 text in {path}: {value!r}")
    return value


def nav_metrics(frame: pd.DataFrame, col: str) -> dict:
    if col not in frame:
        fail(f"missing NAV column {col}")
    nav = frame[col].astype(float)
    dates = pd.to_datetime(frame.date)
    if len(nav) < 2 or not np.isfinite(nav.to_numpy()).all() or (nav <= 0).any():
        fail(f"invalid NAV path in {col}")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    if years <= 0:
        fail(f"non-positive measurement horizon for {col}")
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    ret = nav.pct_change().dropna()
    if not np.isfinite(ret.to_numpy()).all():
        fail(f"non-finite return path in {col}")
    sd = float(ret.std(ddof=1))
    dd = nav / nav.cummax() - 1.0
    return {
        "cagr": float(multiple ** (1.0 / years) - 1.0),
        "max_drawdown": float(dd.min()),
        "sharpe_daily_252": float(ret.mean() / sd * math.sqrt(252)) if sd > 0 else None,
        "ending_multiple": multiple,
    }


def load_positions(raw, label: str) -> set[str]:
    if pd.isna(raw):
        fail(f"{label}: selected-position evidence is NaN")
    try:
        value = json.loads(str(raw))
    except Exception as exc:
        fail(f"{label}: malformed selected-position JSON: {exc}")
    if not isinstance(value, list):
        fail(f"{label}: selected-position evidence is not a JSON list")
    out = {str(x) for x in value}
    if len(out) != len(value):
        fail(f"{label}: duplicate security id in selected-position evidence")
    return out


def position_series(frame: pd.DataFrame, label: str) -> list[set[str]]:
    return [load_positions(raw, f"{label} row {i}") for i, raw in enumerate(frame.research_selected_positions)]


def validate_frame(frame: pd.DataFrame, label: str) -> None:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        fail(f"{label}: required columns missing: {missing}")
    if len(frame) != EXPECTED_SESSIONS:
        fail(f"{label}: sessions {len(frame)} != {EXPECTED_SESSIONS}")
    dates = pd.to_datetime(frame.date)
    if str(dates.iloc[0].date()) != EXPECTED_START or str(dates.iloc[-1].date()) != EXPECTED_END:
        fail(f"{label}: measurement horizon mismatch")
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        fail(f"{label}: date ordering/uniqueness failure")
    for col in ("shadow_equity", "A_nav", "B_nav", "control_nav"):
        x = frame[col].astype(float).to_numpy()
        if not np.isfinite(x).all() or (x <= 0).any():
            fail(f"{label}: invalid positive finite path in {col}")
    for col in ("native_close_target", "minimal_native_close_target", "stateless_native_close_target", "effective_native",
                "A_allocation", "B_allocation", "control_allocation"):
        x = frame[col].astype(float).to_numpy()
        if not np.isfinite(x).all():
            fail(f"{label}: non-finite exposure in {col}")
        ok = np.any(np.isclose(x[:, None], ALLOWED_LEVELS[None, :], atol=1e-12), axis=1)
        if not bool(ok.all()):
            fail(f"{label}: exposure outside allowed domain in {col}")
    # Parse every row now; malformed portfolio evidence must never degrade to an empty set.
    position_series(frame, label)


def holding_delta(base_positions: list[set[str]], case_positions: list[set[str]]) -> dict:
    if len(base_positions) != len(case_positions):
        fail("holding comparison length mismatch")
    anydiff = np.asarray([x != y for x, y in zip(base_positions, case_positions)], dtype=bool)
    sym = np.asarray([len(x ^ y) for x, y in zip(base_positions, case_positions)], dtype=float)
    jac = np.asarray([1.0 if not (x | y) else len(x & y) / len(x | y) for x, y in zip(base_positions, case_positions)], dtype=float)
    return {
        "any_set_difference_sessions": int(anydiff.sum()),
        "any_set_difference_fraction": float(anydiff.mean()),
        "mean_symmetric_name_difference": float(sym.mean()),
        "mean_jaccard": float(jac.mean()),
    }


def allocation_delta(base: pd.DataFrame, case: pd.DataFrame, col: str) -> dict:
    a = base[col].astype(float).to_numpy(); b = case[col].astype(float).to_numpy()
    if len(a) != len(b):
        fail(f"allocation comparison length mismatch for {col}")
    d = np.abs(a - b); mask = d > 1e-12; ix = np.flatnonzero(mask)
    tail = 0
    for flag in mask[::-1]:
        if flag:
            break
        tail += 1
    return {
        "difference_sessions": int(mask.sum()),
        "difference_fraction": float(mask.mean()),
        "absolute_area": float(d.sum()),
        "mean_abs": float(d.mean()),
        "first": None if not len(ix) else str(pd.Timestamp(base.date.iloc[int(ix[0])]).date()),
        "last": None if not len(ix) else str(pd.Timestamp(base.date.iloc[int(ix[-1])]).date()),
        "terminal_equal": bool(not mask[-1]),
        "terminal_equal_tail_sessions": int(tail),
    }


def median(xs):
    vals = [float(x) for x in xs if x is not None and np.isfinite(float(x))]
    return None if not vals else float(np.median(vals))


def verify_common_result(result: dict, label: str) -> None:
    if result.get("status") != "PASS_FRESH_CAUSAL_PIT_REPLAY":
        fail(f"{label}: replay status is not PASS_FRESH_CAUSAL_PIT_REPLAY")
    contract = result.get("architecture_contract") or {}
    required = {
        "research_only": True,
        "production_code_modified": False,
        "future_data": False,
        "baseline_path_access": False,
        "same_wealth_core_tape": True,
        "current_track_byte_preserved": True,
        "state_minimal_memory_sessions": 60,
        "stateless_hidden_state_sessions": 0,
    }
    for key, expected in required.items():
        if contract.get(key) != expected:
            fail(f"{label}: architecture contract mismatch for {key}: {contract.get(key)!r} != {expected!r}")
    if set((result.get("architectures") or {}).keys()) != set(ARCH):
        fail(f"{label}: architecture result set mismatch")


def verify_package(root: Path, meta: dict, expected_treatment_hash: str) -> tuple[dict, dict, str]:
    result_path = root / "RESULT.json"
    hash_path = root / "selected-source-sha256.txt"
    if not result_path.exists() or not hash_path.exists():
        fail(f"{root}: missing RESULT.json or selected-source-sha256.txt")
    result = json.loads(result_path.read_text())
    source_hash = read_hash(hash_path)
    if source_hash != expected_treatment_hash:
        fail(f"{root}: treatment source hash {source_hash} != preflight {expected_treatment_hash}")
    if result.get("status") != "PASS":
        fail(f"{root}: suite status is not PASS")
    if result.get("selected_config") != EXPECTED_SELECTED_CONFIG:
        fail(f"{root}: selected V6 config mismatch: {result.get('selected_config')}")
    if result.get("performance_selection") != "FORBIDDEN_VALIDATION_ONLY":
        fail(f"{root}: performance-selection guard missing")

    if meta["kind"] == "baseline":
        if result.get("suite") != "baseline" or "baseline" not in result:
            fail(f"{root}: baseline package/result mismatch")
        replay = result["baseline"]
    else:
        cases = result.get("cases") or []
        if len(cases) != 1:
            fail(f"{root}: expected exactly one fault case, saw {len(cases)}")
        case = cases[0]
        replay = case.get("result") or {}
        fault = meta["fault"]
        if fault["type"] == "security_leave_one_out":
            if result.get("suite") != "security-loo" or str(case.get("security_id")) != fault["security_id"]:
                fail(f"{root}: LOO metadata/result mismatch")
        elif fault["type"] == "universe_dropout":
            if result.get("suite") != "universe" or case.get("case") != "drop_01pct_seed11":
                fail(f"{root}: universe-dropout metadata/result mismatch")
        else:
            fail(f"{root}: unknown fault type {fault}")
    verify_common_result(replay, str(root))
    return result, replay, source_hash


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out; out.mkdir(parents=True, exist_ok=True)

    preflight_path = find_one(args.inputs, "preflight.json")
    preflight = json.loads(preflight_path.read_text())
    if preflight.get("status") != "PASS":
        fail("preflight evidence did not pass")
    source_inv = preflight.get("source_invariants") or {}
    treatment_hash = source_inv.get("treated_source_sha256")
    if not isinstance(treatment_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", treatment_hash):
        fail("preflight treatment-source hash missing/invalid")

    metas = []
    for p in args.inputs.rglob("metadata.json"):
        metas.append((p, json.loads(p.read_text())))
    baseline_meta = [(p, m) for p, m in metas if m.get("kind") == "baseline"]
    case_meta = sorted([(p, m) for p, m in metas if m.get("kind") == "case"], key=lambda x: int(x[1]["index"]))
    if len(baseline_meta) != 1 or len(case_meta) != 7:
        fail(f"expected 1 baseline + 7 cases, got {len(baseline_meta)} + {len(case_meta)}")
    bp, bm = baseline_meta[0]
    if bm != {"kind": "baseline", "case": "no_fault", "index": -1}:
        fail(f"baseline metadata mismatch: {bm}")
    observed_indices = [int(m["index"]) for _, m in case_meta]
    if observed_indices != list(range(7)):
        fail(f"fault indices mismatch: {observed_indices}")
    for _p, meta in case_meta:
        idx = int(meta["index"])
        if meta.get("fault") != EXPECTED_FAULTS[idx]:
            fail(f"fault metadata mismatch for index {idx}: {meta.get('fault')} != {EXPECTED_FAULTS[idx]}")

    verify_package(bp.parent, bm, treatment_hash)
    base_csv = bp.parent / "architecture-daily.csv"
    if not base_csv.exists():
        fail("baseline architecture-daily.csv missing")
    base = pd.read_csv(base_csv, parse_dates=["date"])
    validate_frame(base, "baseline")
    base_positions = position_series(base, "baseline")

    baseline_economics = {name: nav_metrics(base, nav_col) for name, (_alloc, nav_col) in ARCH.items()}
    baseline_core_economics = nav_metrics(base, "shadow_equity")
    current = baseline_economics["current"]
    for key, expected in EXPECTED_CURRENT.items():
        actual = current[key]
        if actual is None or abs(float(actual) - expected) > 5e-10:
            fail(f"authoritative current baseline metric mismatch for {key}: {actual} != {expected}")

    baseline_relative = {}
    for name, metrics in baseline_economics.items():
        if metrics["sharpe_daily_252"] is None or current["sharpe_daily_252"] is None:
            fail("unexpected undefined Sharpe in baseline architecture")
        baseline_relative[name] = {
            "cagr_delta_vs_current": float(metrics["cagr"] - current["cagr"]),
            "max_drawdown_delta_vs_current": float(metrics["max_drawdown"] - current["max_drawdown"]),
            "sharpe_delta_vs_current": float(metrics["sharpe_daily_252"] - current["sharpe_daily_252"]),
            "ending_multiple_ratio_vs_current": float(metrics["ending_multiple"] / current["ending_multiple"]),
        }

    cases = []
    for mp, meta in case_meta:
        idx = int(meta["index"])
        verify_package(mp.parent, meta, treatment_hash)
        case_csv = mp.parent / "architecture-daily.csv"
        if not case_csv.exists():
            fail(f"case {idx}: architecture-daily.csv missing")
        case = pd.read_csv(case_csv, parse_dates=["date"])
        validate_frame(case, f"case {idx}")
        if not np.array_equal(pd.to_datetime(base.date).to_numpy(), pd.to_datetime(case.date).to_numpy()):
            fail(f"date mismatch for case {idx}")
        case_positions = position_series(case, f"case {idx}")
        hdelta = holding_delta(base_positions, case_positions)
        if hdelta["any_set_difference_sessions"] <= 0:
            fail(f"case {idx}: deterministic Wealth Core fault produced no holding-path perturbation")

        fault = meta["fault"]
        if fault["type"] == "security_leave_one_out":
            sid = fault["security_id"]
            if not any(sid in xs for xs in base_positions):
                fail(f"case {idx}: excluded security {sid} was never held in baseline")
            if any(sid in xs for xs in case_positions):
                fail(f"case {idx}: excluded security {sid} still appears in faulted holdings")

        core_metrics = nav_metrics(case, "shadow_equity")
        hdelta["economics"] = core_metrics
        hdelta["economic_delta_from_no_fault"] = {
            "cagr": float(core_metrics["cagr"] - baseline_core_economics["cagr"]),
            "max_drawdown": float(core_metrics["max_drawdown"] - baseline_core_economics["max_drawdown"]),
            "sharpe_daily_252": None if core_metrics["sharpe_daily_252"] is None or baseline_core_economics["sharpe_daily_252"] is None else float(core_metrics["sharpe_daily_252"] - baseline_core_economics["sharpe_daily_252"]),
            "ending_multiple_ratio": float(core_metrics["ending_multiple"] / baseline_core_economics["ending_multiple"]),
        }

        row = {"index": idx, "case": meta["case"], "fault": fault, "wealth_core": hdelta, "architectures": {}}
        for name, (alloc_col, nav_col) in ARCH.items():
            ad = allocation_delta(base, case, alloc_col)
            cm = nav_metrics(case, nav_col); bmtr = baseline_economics[name]
            if cm["sharpe_daily_252"] is None or bmtr["sharpe_daily_252"] is None:
                fail(f"case {idx} {name}: undefined Sharpe")
            ad["economics"] = cm
            ad["economic_delta_from_no_fault"] = {
                "cagr": float(cm["cagr"] - bmtr["cagr"]),
                "max_drawdown": float(cm["max_drawdown"] - bmtr["max_drawdown"]),
                "sharpe_daily_252": float(cm["sharpe_daily_252"] - bmtr["sharpe_daily_252"]),
                "ending_multiple_ratio": float(cm["ending_multiple"] / bmtr["ending_multiple"]),
            }
            row["architectures"][name] = ad
        current_area = row["architectures"]["current"]["absolute_area"]
        for name in ("state_minimal_60", "stateless_1"):
            area = row["architectures"][name]["absolute_area"]
            row["architectures"][name]["area_reduction_vs_current"] = None if current_area <= 1e-12 else float(1.0 - area / current_area)
        cases.append(row)

    agg = {}
    for name in ARCH:
        agg[name] = {
            "affected_cases": int(sum(c["architectures"][name]["absolute_area"] > 1e-12 for c in cases)),
            "median_difference_sessions": median([c["architectures"][name]["difference_sessions"] for c in cases]),
            "median_difference_fraction": median([c["architectures"][name]["difference_fraction"] for c in cases]),
            "median_absolute_area": median([c["architectures"][name]["absolute_area"] for c in cases]),
            "max_absolute_area": max(float(c["architectures"][name]["absolute_area"]) for c in cases),
            "median_abs_cagr_fault_delta": median([abs(c["architectures"][name]["economic_delta_from_no_fault"]["cagr"]) for c in cases]),
            "max_abs_cagr_fault_delta": max(abs(float(c["architectures"][name]["economic_delta_from_no_fault"]["cagr"])) for c in cases),
            "median_abs_mdd_fault_delta": median([abs(c["architectures"][name]["economic_delta_from_no_fault"]["max_drawdown"]) for c in cases]),
            "terminal_equal_cases": int(sum(c["architectures"][name]["terminal_equal"] for c in cases)),
        }
    current_affected = [c for c in cases if c["architectures"]["current"]["absolute_area"] > 1e-12]
    for name in ("state_minimal_60", "stateless_1"):
        reductions = [c["architectures"][name]["area_reduction_vs_current"] for c in current_affected]
        agg[name]["current_affected_case_count"] = len(current_affected)
        agg[name]["median_area_reduction_vs_current_on_current_affected_cases"] = median(reductions)
        agg[name]["cases_with_lower_area_than_current"] = int(sum(c["architectures"][name]["absolute_area"] + 1e-12 < c["architectures"]["current"]["absolute_area"] for c in current_affected))
        agg[name]["cases_with_higher_area_than_current"] = int(sum(c["architectures"][name]["absolute_area"] > c["architectures"]["current"]["absolute_area"] + 1e-12 for c in current_affected))

    summary = {
        "schema": "research.wealth-core-v5-ex3-v6-state-architecture-v1/aggregate-2",
        "status": "PASS",
        "question": "How much of Sentinel fault amplification requires carried internal state?",
        "integrity": {
            "preflight_status": preflight["status"],
            "exact_selected_source_sha256": source_inv.get("exact_selected_source_sha256"),
            "treated_source_sha256": treatment_hash,
            "current_authoritative_metrics_verified": True,
            "fault_set_verified": True,
            "all_position_evidence_parsed_fail_closed": True,
            "all_packages_bound_to_preflight_treatment_source": True,
        },
        "architectures": {
            "current": "authoritative Native + EX3 V6 with full carried state",
            "state_minimal_60": "bounded-state proxy: exact controller logic rebuilt from only the most recent 60 observable sessions",
            "stateless_1": "exact controller logic rebuilt from only the current observable session",
        },
        "baseline_wealth_core_economics": baseline_core_economics,
        "baseline_economics": baseline_economics,
        "baseline_relative_to_current": baseline_relative,
        "aggregate_fault_robustness": agg,
        "cases": cases,
        "interpretation_guard": "Research attribution only. State-minimal-60 is a bounded-state proxy, not a claim that 60 sessions is optimal. No architecture is promoted automatically; robustness gains must be weighed against baseline economic changes.",
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Sentinel state architecture experiment — results",
        "",
        "Research-only comparison on the same Wealth Core V5 fault tapes. All artifacts passed source, timing, metadata and fault-application integrity gates.",
        "",
        "| Architecture | Baseline CAGR | Baseline MDD | Sharpe | Median fault allocation area | Median abs CAGR fault delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ARCH:
        b = baseline_economics[name]; a = agg[name]
        lines.append(f"| {name} | {b['cagr']:.4%} | {b['max_drawdown']:.4%} | {b['sharpe_daily_252']:.4f} | {a['median_absolute_area']:.2f} | {a['median_abs_cagr_fault_delta']:.4%} |")
    lines += ["", "## Robustness change vs current", ""]
    for name in ("state_minimal_60", "stateless_1"):
        v = agg[name]["median_area_reduction_vs_current_on_current_affected_cases"]
        better = agg[name]["cases_with_lower_area_than_current"]
        worse = agg[name]["cases_with_higher_area_than_current"]
        lines.append(f"- {name}: median integrated allocation-divergence area reduction on current-affected cases = {('N/A' if v is None else f'{v:.2%}')}; better in {better}, worse in {worse}.")
    lines += [
        "",
        "State-minimal-60 is a bounded-state attribution proxy, not a claim that 60 sessions is optimal.",
        "No automatic promotion. See SUMMARY.json for all seven deterministic cases, Wealth Core deltas, and architecture economics.",
        "",
    ]
    (out / "SUMMARY.md").write_text("\n".join(lines))
    print(json.dumps({"status": "PASS", "cases": len(cases), "treated_source_sha256": treatment_hash, "aggregate_fault_robustness": agg}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
