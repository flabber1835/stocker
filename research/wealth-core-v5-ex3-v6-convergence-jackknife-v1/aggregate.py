#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = "research.wealth-core-v5-ex3-v6-convergence-jackknife/2"


def load_result(path: Path):
    return json.loads(path.read_text())


def pos(raw):
    try:
        return set(json.loads(raw)) if isinstance(raw, str) and raw else set()
    except Exception:
        return set()


def reconvergence_stats(diff: np.ndarray, dates, n: int = 20) -> dict:
    diff = np.asarray(diff, dtype=bool)
    idx = np.flatnonzero(diff)
    if not len(idx):
        return {
            "ever_diverged": False,
            "first_divergence": None,
            "last_divergence": None,
            "first_20_exact_reconvergence": None,
            "sessions_to_first_20_exact_reconvergence": None,
            "terminal_20_exact_reconvergence": None,
            "never_20_session_reconverged": False,
            "terminally_reconverged": True,
        }

    first = int(idx[0])
    last = int(idx[-1])
    same = ~diff
    first_run = None
    for i in range(first + 1, len(same) - n + 1):
        if same[i : i + n].all():
            first_run = i
            break
    terminal_start = last + 1 if len(same) - (last + 1) >= n else None
    return {
        "ever_diverged": True,
        "first_divergence": str(pd.Timestamp(dates.iloc[first]).date()),
        "last_divergence": str(pd.Timestamp(dates.iloc[last]).date()),
        "first_20_exact_reconvergence": None if first_run is None else str(pd.Timestamp(dates.iloc[first_run]).date()),
        "sessions_to_first_20_exact_reconvergence": None if first_run is None else int(first_run - first),
        "terminal_20_exact_reconvergence": None if terminal_start is None else str(pd.Timestamp(dates.iloc[terminal_start]).date()),
        "never_20_session_reconverged": first_run is None,
        "terminally_reconverged": terminal_start is not None,
    }


def path_stats(base: pd.DataFrame, case: pd.DataFrame) -> dict:
    if len(base) != len(case) or not base.date.equals(case.date):
        raise RuntimeError("baseline/case daily tapes are not date-aligned")
    bsets = [pos(x) for x in base.research_selected_positions.fillna("[]")]
    csets = [pos(x) for x in case.research_selected_positions.fillna("[]")]
    sym = np.array([len(a ^ b) for a, b in zip(bsets, csets)], int)
    differing = np.array([max(len(a - b), len(b - a)) for a, b in zip(bsets, csets)], int)
    jac = np.array([1.0 if not (a | b) else len(a & b) / len(a | b) for a, b in zip(bsets, csets)], float)
    diff = sym > 0
    rc = reconvergence_stats(diff, case.date, 20)
    return {
        **rc,
        "core_exact_fraction": float((~diff).mean()),
        "median_jaccard": float(np.median(jac)),
        "max_symmetric_difference": int(sym.max()),
        "max_differing_holdings": int(differing.max()),
        "core_divergence_fraction": float(diff.mean()),
    }


def allocation_diff(base: pd.DataFrame, case: pd.DataFrame, col: str) -> np.ndarray:
    if len(base) != len(case) or not base.date.equals(case.date):
        raise RuntimeError("baseline/case allocation tapes are not date-aligned")
    return np.abs(base[col].astype(float).to_numpy() - case[col].astype(float).to_numpy()) > 1e-12


def alloc_stats(base: pd.DataFrame, case: pd.DataFrame, col: str) -> tuple[dict, np.ndarray]:
    d = allocation_diff(base, case, col)
    rc = reconvergence_stats(d, case.date, 20)
    return {
        **rc,
        "divergence_sessions": int(d.sum()),
        "divergence_fraction": float(d.mean()),
    }, d


def delta(p: dict, b: dict) -> dict:
    return {k: float(p[k]) - float(b[k]) for k in p if p[k] is not None and b[k] is not None}


def perf20(case_result: dict, side: str) -> dict:
    m = case_result["treatment"]["20"] if side == "patched" else case_result["sentinel"]["20"]
    return {k: m[k] for k in ("cagr", "max_drawdown", "sharpe_daily_252", "ending_multiple")}


def aggregate_side(xs: list[dict], side: str) -> dict:
    if not xs:
        return {}
    ac = np.array([abs(x[f"{side}_perf_delta"]["cagr"]) for x in xs], float)
    fr = np.array([x[side]["divergence_fraction"] for x in xs], float)
    path_amps = np.array([x.get(f"{side}_path_amplification", np.nan) for x in xs], float)
    econ_amps = np.array([x.get(f"{side}_economic_amplification", np.nan) for x in xs], float)
    post = np.array([x[side].get("post_excluded_gone_divergence_fraction", np.nan) for x in xs], float)
    median_path_amp = float(np.nanmedian(path_amps)) if np.isfinite(path_amps).any() else None
    return {
        "cases": len(xs),
        "median_abs_cagr_delta_pp": float(np.median(ac) * 100),
        "p95_abs_cagr_delta_pp": float(np.quantile(ac, 0.95) * 100),
        "max_abs_cagr_delta_pp": float(ac.max() * 100),
        "loss_ge_1pp": int(sum(x[f"{side}_perf_delta"]["cagr"] <= -0.01 for x in xs)),
        "loss_ge_2pp": int(sum(x[f"{side}_perf_delta"]["cagr"] <= -0.02 for x in xs)),
        "median_allocation_divergence_fraction": float(np.median(fr)),
        "never_20_session_reconverged": int(sum(x[side]["never_20_session_reconverged"] for x in xs)),
        "not_terminally_reconverged": int(sum(not x[side]["terminally_reconverged"] for x in xs)),
        "median_path_amplification": median_path_amp,
        "median_amplification": median_path_amp,
        "median_economic_amplification": float(np.nanmedian(econ_amps)) if np.isfinite(econ_amps).any() else None,
        "first_divergence_after_excluded_security_gone": int(sum(x[side].get("first_divergence_after_excluded_security_gone", False) for x in xs)),
        "median_post_excluded_gone_divergence_fraction": float(np.nanmedian(post)) if np.isfinite(post).any() else None,
    }


def core_aggregate(xs: list[dict]) -> dict:
    if not xs:
        return {}
    ac = np.array([abs(x["core_perf_delta"]["cagr"]) for x in xs], float)
    return {
        "cases": len(xs),
        "median_exact_fraction": float(np.median([x["core"]["core_exact_fraction"] for x in xs])),
        "median_jaccard": float(np.median([x["core"]["median_jaccard"] for x in xs])),
        "max_differing_holdings": int(max(x["core"]["max_differing_holdings"] for x in xs)),
        "never_20_session_reconverged": int(sum(x["core"]["never_20_session_reconverged"] for x in xs)),
        "not_terminally_reconverged": int(sum(not x["core"]["terminally_reconverged"] for x in xs)),
        "median_abs_cagr_delta_pp": float(np.median(ac) * 100),
        "p95_abs_cagr_delta_pp": float(np.quantile(ac, 0.95) * 100),
        "max_abs_cagr_delta_pp": float(ac.max() * 100),
    }


def robustness_verdict(unpatched: dict, patched: dict, rows: list[dict], dropouts: list[dict]) -> tuple[str, dict]:
    if not unpatched or not patched or not rows:
        return "MIXED / REQUIRES REVIEW", {"reason": "incomplete evidence"}

    udiv = unpatched["median_allocation_divergence_fraction"]
    pdiv = patched["median_allocation_divergence_fraction"]
    uamp = unpatched.get("median_path_amplification")
    pamp = patched.get("median_path_amplification")
    div_reduction = None if udiv <= 0 else (udiv - pdiv) / udiv
    amp_reduction = None if uamp is None or uamp <= 0 or pamp is None else (uamp - pamp) / uamp
    case_wins = sum(r["patched"]["divergence_fraction"] < r["unpatched"]["divergence_fraction"] - 1e-15 for r in rows)
    case_losses = sum(r["patched"]["divergence_fraction"] > r["unpatched"]["divergence_fraction"] + 1e-15 for r in rows)
    dropout_wins = sum(r["patched"]["divergence_fraction"] < r["unpatched"]["divergence_fraction"] - 1e-15 for r in dropouts)
    dropout_losses = sum(r["patched"]["divergence_fraction"] > r["unpatched"]["divergence_fraction"] + 1e-15 for r in dropouts)

    detail = {
        "median_allocation_divergence_reduction_fraction": div_reduction,
        "median_amplification_reduction_fraction": amp_reduction,
        "case_level_divergence_wins": int(case_wins),
        "case_level_divergence_losses": int(case_losses),
        "dropout_divergence_wins": int(dropout_wins),
        "dropout_divergence_losses": int(dropout_losses),
        "evaluation_basis": "path stability and Sentinel amplification; performance diagnostics excluded",
    }

    material = (
        div_reduction is not None and div_reduction >= 0.25
        and amp_reduction is not None and amp_reduction >= 0.25
        and patched["never_20_session_reconverged"] <= unpatched["never_20_session_reconverged"]
        and case_wins >= 12
        and case_losses <= 4
        and dropout_losses <= 1
    )
    worse = (
        pdiv > udiv
        and uamp is not None and pamp is not None and pamp > uamp
        and case_losses > case_wins
        and dropout_losses >= dropout_wins
    )
    some = (
        pdiv < udiv
        and (uamp is None or pamp is None or pamp < uamp)
        and case_wins > case_losses
        and dropout_losses <= 1
    )
    if material:
        return "MATERIAL ROBUSTNESS IMPROVEMENT", detail
    if worse:
        return "WORSE", detail
    if some:
        return "SOME IMPROVEMENT, BUT BUTTERFLY ISSUE REMAINS", detail
    return "NO MEANINGFUL IMPROVEMENT", detail


def self_test() -> None:
    dates = pd.Series(pd.date_range("2020-01-01", periods=80, freq="D"))
    d = np.zeros(80, bool)
    d[30:35] = True
    r = reconvergence_stats(d, dates, 20)
    assert r["first_divergence"] == "2020-01-31"
    assert r["first_20_exact_reconvergence"] == "2020-02-05"
    assert r["sessions_to_first_20_exact_reconvergence"] == 5
    assert r["terminally_reconverged"] is True
    assert r["never_20_session_reconverged"] is False

    late = np.zeros(80, bool)
    late[70:] = True
    r = reconvergence_stats(late, dates, 20)
    assert r["first_20_exact_reconvergence"] is None
    assert r["never_20_session_reconverged"] is True
    assert r["terminally_reconverged"] is False

    none = np.zeros(80, bool)
    r = reconvergence_stats(none, dates, 20)
    assert r["ever_diverged"] is False
    assert r["terminally_reconverged"] is True
    print("aggregate self-test PASS")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return
    if a.root is None or a.out is None:
        ap.error("--root and --out are required unless --self-test is used")

    br = load_result(a.root / "baseline" / "RESULT.json")
    bd = pd.read_csv(a.root / "baseline" / "paired-daily.csv", parse_dates=["date"])
    bpc = br["baseline"]["core"]["20"]
    bpa = br["baseline"]["sentinel"]["20"]
    bpb = br["baseline"]["treatment"]["20"]
    rows = []

    for p in sorted(a.root.glob("case-*")):
        rp = list(p.rglob("RESULT.json"))
        if len(rp) != 1:
            raise RuntimeError(f"{p}: expected exactly one RESULT.json, found {len(rp)}")
        rr = load_result(rp[0])
        cases = rr.get("cases", [])
        if len(cases) != 1:
            raise RuntimeError(f"{p}: expected exactly one case, found {len(cases)}")
        c = cases[0]
        tag = c["case"]
        csvs = list(p.rglob(f"runs/{tag}/paired-daily.csv"))
        if len(csvs) != 1:
            raise RuntimeError(f"{p}: expected exactly one paired-daily.csv for {tag}, found {len(csvs)}")
        cd = pd.read_csv(csvs[0], parse_dates=["date"])
        ps = path_stats(bd, cd)
        sa, da = alloc_stats(bd, cd, "A_allocation")
        sb, db = alloc_stats(bd, cd, "B_allocation")
        ccore = c["result"]["core"]["20"]
        pa = perf20(c["result"], "unpatched")
        pb = perf20(c["result"], "patched")
        core_delta = delta(ccore, bpc)
        row = {
            "case": tag,
            "security_id": c.get("security_id"),
            "core": ps,
            "unpatched": sa,
            "patched": sb,
            "core_perf_delta": core_delta,
            "unpatched_perf_delta": delta(pa, bpa),
            "patched_perf_delta": delta(pb, bpb),
        }
        if ps["core_divergence_fraction"] > 0:
            row["unpatched_path_amplification"] = sa["divergence_fraction"] / ps["core_divergence_fraction"]
            row["patched_path_amplification"] = sb["divergence_fraction"] / ps["core_divergence_fraction"]
        core_cagr_delta = core_delta.get("cagr")
        if core_cagr_delta is not None and abs(core_cagr_delta) > 1e-12:
            row["unpatched_economic_amplification"] = abs(row["unpatched_perf_delta"]["cagr"]) / abs(core_cagr_delta)
            row["patched_economic_amplification"] = abs(row["patched_perf_delta"]["cagr"]) / abs(core_cagr_delta)

        sid = c.get("security_id")
        if sid:
            held = np.array([sid in pos(x) for x in bd.research_selected_positions.fillna("[]")], bool)
            ix = np.flatnonzero(held)
            last_i = None if not len(ix) else int(ix[-1])
            last_date = None if last_i is None else pd.Timestamp(bd.date.iloc[last_i])
            for name, st, dmask in (("unpatched", sa, da), ("patched", sb, db)):
                fd = st["first_divergence"]
                st["first_divergence_after_excluded_security_gone"] = bool(
                    fd and last_date is not None and pd.Timestamp(fd) > last_date
                )
                if last_i is not None and last_i + 1 < len(dmask):
                    tail = dmask[last_i + 1 :]
                    st["post_excluded_gone_divergence_sessions"] = int(tail.sum())
                    st["post_excluded_gone_divergence_fraction"] = float(tail.mean())
                else:
                    st["post_excluded_gone_divergence_sessions"] = 0
                    st["post_excluded_gone_divergence_fraction"] = 0.0
        rows.append(row)

    loo = [r for r in rows if r["security_id"]]
    drops = [r for r in rows if not r["security_id"]]
    if len(loo) != 16 or len(drops) != 3:
        raise RuntimeError(f"incomplete campaign: expected 16 LOO + 3 dropouts, got {len(loo)} + {len(drops)}")

    au = aggregate_side(loo, "unpatched")
    apc = aggregate_side(loo, "patched")
    core = core_aggregate(loo)
    verdict, verdict_detail = robustness_verdict(au, apc, loo, drops)
    baseline_delta = delta(bpb, bpa)
    out = {
        "schema": SCHEMA,
        "baseline": {
            "core": bpc,
            "unpatched": bpa,
            "patched": bpb,
            "patched_minus_unpatched": baseline_delta,
            "paired_direct": br["baseline"]["paired_direct"],
        },
        "core_path_aggregate": core,
        "loo_aggregate": {"unpatched": au, "patched": apc},
        "dropout_cases": drops,
        "loo_cases": loo,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "patch": "research-only neutral full-native REC8 canonicalization",
        "promotion": "FORBIDDEN_BY_THIS_EXPERIMENT",
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "SUMMARY.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    pd.DataFrame(
        [
            {
                **{"case": r["case"], "security_id": r["security_id"]},
                **{f"u_{k}": v for k, v in r["unpatched"].items()},
                **{f"p_{k}": v for k, v in r["patched"].items()},
            }
            for r in rows
        ]
    ).to_csv(a.out / "compact.csv", index=False)
    print(json.dumps({"verdict": verdict, "loo": len(loo), "dropouts": len(drops), "unpatched": au, "patched": apc}, indent=2))


if __name__ == "__main__":
    main()
