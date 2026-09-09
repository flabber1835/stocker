#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ADV_PATH = HERE.parent / "wealth-core-v5-sentinel-ex3-v5-adversarial-v1" / "run_adversarial.py"


def _load_adv():
    spec = importlib.util.spec_from_file_location("reconv_adv", ADV_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ADV_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconv_adv"] = mod
    spec.loader.exec_module(mod)
    return mod


adv = _load_adv()
SCHEMA = "research.wealth-core-v5-canonical-reconvergence/1"
SYSTEM = "Wealth Core V5 + Sentinel EX3 V5"
HOLDOUT_COUNT = 6
PREVIOUSLY_UNTOUCHED_MIN_SHARD = 29
ORIGINAL_SHARDS = 96
DROPOUT_SEEDS = (11, 29, 47)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def replace_once(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one seam, observed {n}")
    return src.replace(old, new, 1)


def apply_reconvergence(src: str) -> str:
    """Add a path-restoring canonical target at the existing 119-session review boundary.

    No existing parameter is changed. The current hardened ranking, 20-slot geometry,
    cooldowns, risk exits, affordability rules, and one-admission-per-day throttle remain.
    After a holding reaches REVIEW_AGE, canonical membership is checked every close.
    At most one discretionary reconvergence sell is initiated per close.
    """
    if "N_SLOTS = 20" not in src or "ENTRY_W = 0.05" not in src:
        raise RuntimeError("frozen 20x5 geometry missing")
    if "REVIEW_AGE = 119" not in src or "COOLDOWN = 21" not in src:
        raise RuntimeError("frozen review/cooldown authority missing")
    if "for tid0 in _harden_order(durable,score,_rank_order_hist):" not in src:
        raise RuntimeError("Median-5 hardened admission seam missing")

    close_marker = "            # Close: peaks/exits, mark equity, breadth, then admissions.\n            for s in book.slots:"
    target_code = """            # Canonical reconvergence target: path-independent ranking surface for this close.\n            _reconv_order=[int(x) for x in _harden_order(durable,score,_rank_order_hist)]\n            _reconv_target=[]; _reconv_target_issuers=set()\n            for _rtid in _reconv_order:\n                if not finite(recent[_rtid]) or recent[_rtid]<0 or _rtid in term_tids: continue\n                _riss=issuer_key(_rtid,ds)\n                if _riss in _reconv_target_issuers: continue\n                _reconv_target.append(_rtid); _reconv_target_issuers.add(_riss)\n                if len(_reconv_target)>=N_SLOTS: break\n            _reconv_target_set=set(_reconv_target)\n            _reconv_reserved_issuers={issuer_key(_s.pending_tid,ds) for _s in book.slots if _s.reserved()}\n            _reconv_discretionary_sell_used=False\n\n            # Close: peaks/exits, mark equity, breadth, then admissions.\n            for s in book.slots:"""
    src = replace_once(src, close_marker, target_code, "canonical target insertion")

    old_review = """                elif age>=REVIEW_AGE and not s.reviewed and finite(px):\n                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)\n                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig\n                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'\n                    else: s.reviewed=True"""

    new_review = """                elif age>=REVIEW_AGE and finite(px):\n                    # Preserve the original one-time economic review exactly.\n                    if not s.reviewed:\n                        qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)\n                        underwater=finite(s.entry_sig) and float(px)<s.entry_sig\n                        if underwater and not qualifies:\n                            s.pending_sell=True; s.sell_reason='review'\n                        else:\n                            s.reviewed=True\n                    # After REVIEW_AGE, continually restore the book toward today's canonical target.\n                    if (not s.pending_sell and not _reconv_discretionary_sell_used and s.tid not in _reconv_target_set):\n                        _other_issuers={issuer_key(_x.tid,ds) for _x in book.slots if _x.held() and _x is not s}\n                        _held_now=book.held_ids(); _reserved_now=book.reserved_ids(); _replacement=None\n                        for _cand in _reconv_target:\n                            if _cand in _held_now or _cand in _reserved_now or _cand in term_tids: continue\n                            if book.sec_ready.get(_cand,-1)>gday: continue\n                            _ciss=issuer_key(_cand,ds)\n                            if _ciss in _other_issuers or _ciss in _reconv_reserved_issuers: continue\n                            _replacement=_cand; break\n                        if _replacement is not None:\n                            s.pending_sell=True; s.sell_reason='reconverge'; _reconv_discretionary_sell_used=True"""
    src = replace_once(src, old_review, new_review, "119-session review replacement")

    # Contract guards: no timing, sizing, stop, cooldown, or controller thresholds changed.
    for marker in (
        "budget=len(ready) if not book.initialized else 1",
        "STOP_RET = 0.70",
        "COOLDOWN = 21",
        "REVIEW_AGE = 119",
        "LDRC_REC=8",
        "recent_r40>-0.05)",
        "'dam':0.88",
        "dam<=0.63 and green>=.20",
        "book.receivables.append((gday+1,q*rawdiv))",
    ):
        if marker not in src:
            raise RuntimeError(f"frozen invariant missing after patch: {marker}")
    adv.timing_guard(src)
    compile(src, "<canonical-reconvergence>", "exec")
    return src


def load_daily(path: Path) -> pd.DataFrame:
    f = pd.read_csv(path, parse_dates=["date"])
    if len(f) != adv.SESSIONS:
        raise RuntimeError(f"unexpected daily length: {len(f)}")
    return f


def parse_positions(raw) -> frozenset[str]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return frozenset()
    try:
        xs = json.loads(str(raw))
    except Exception:
        return frozenset()
    return frozenset(str(x) for x in xs)


def position_sets(frame: pd.DataFrame) -> list[frozenset[str]]:
    return [parse_positions(x) for x in frame.research_selected_positions]


def path_metrics(reference: pd.DataFrame, variant: pd.DataFrame, security_id: str | None = None) -> dict:
    if not reference.date.equals(variant.date):
        raise RuntimeError("daily dates differ")
    a = position_sets(reference); b = position_sets(variant)
    sym = np.asarray([len(x.symmetric_difference(y)) for x, y in zip(a, b)], dtype=float)
    common = np.asarray([len(x.intersection(y)) for x, y in zip(a, b)], dtype=float)
    denom = np.asarray([max(len(x.union(y)), 1) for x, y in zip(a, b)], dtype=float)
    jac = common / denom
    exact = sym == 0
    alloc_a = reference.A_allocation.astype(float).to_numpy()
    alloc_b = variant.A_allocation.astype(float).to_numpy()
    alloc_diff = np.abs(alloc_a - alloc_b) > 1e-12

    nz = np.flatnonzero(~exact)
    first = int(nz[0]) if len(nz) else None

    def first_run(start: int, predicate: np.ndarray, run: int = 20):
        if start >= len(predicate): return None
        streak = 0
        for i in range(start, len(predicate)):
            streak = streak + 1 if bool(predicate[i]) else 0
            if streak >= run:
                return i - run + 1
        return None

    out = {
        "exact_match_fraction": float(exact.mean()),
        "mean_symmetric_difference": float(sym.mean()),
        "median_jaccard": float(np.median(jac)),
        "max_symmetric_difference": int(sym.max()),
        "sentinel_allocation_divergence_sessions": int(alloc_diff.sum()),
        "first_portfolio_divergence_date": None if first is None else str(reference.date.iloc[first].date()),
        "first_exact_20_session_reconvergence_date": None,
        "sessions_to_exact_20_reconvergence": None,
    }
    if first is not None:
        rr = first_run(first + 1, exact, 20)
        if rr is not None:
            out["first_exact_20_session_reconvergence_date"] = str(reference.date.iloc[rr].date())
            out["sessions_to_exact_20_reconvergence"] = int(rr - first)

    if security_id is not None:
        held_idx = [i for i, s in enumerate(a) if str(security_id) in s]
        if held_idx:
            last = int(max(held_idx))
            start = min(last + 1, len(a))
            out["reference_last_holding_date"] = str(reference.date.iloc[last].date())
            if start < len(a):
                out["post_last_holding_exact_match_fraction"] = float(exact[start:].mean())
                out["post_last_holding_mean_symmetric_difference"] = float(sym[start:].mean())
                rr = first_run(start, exact, 20)
                out["post_last_holding_20_session_reconvergence_date"] = None if rr is None else str(reference.date.iloc[rr].date())
                out["post_last_holding_sessions_to_reconvergence"] = None if rr is None else int(rr - start)
            else:
                out["post_last_holding_exact_match_fraction"] = 1.0
                out["post_last_holding_mean_symmetric_difference"] = 0.0
                out["post_last_holding_20_session_reconvergence_date"] = None
                out["post_last_holding_sessions_to_reconvergence"] = None
        else:
            out["reference_last_holding_date"] = None
    return out


def metric_delta(base: dict, var: dict) -> dict:
    out = {}
    for layer in ("core", "sentinel"):
        bm = base[layer]["20"]; vm = var[layer]["20"]
        out[layer] = {
            "cagr_delta": float(vm["cagr"] - bm["cagr"]),
            "max_drawdown_delta": float(vm["max_drawdown"] - bm["max_drawdown"]),
            "sharpe_delta": float(vm["sharpe_daily_252"] - bm["sharpe_daily_252"]),
            "variant": vm,
            "baseline": bm,
        }
    core_abs = abs(out["core"]["cagr_delta"])
    sent_abs = abs(out["sentinel"]["cagr_delta"])
    out["sentinel_to_core_abs_cagr_impact_ratio"] = None if core_abs < 1e-12 else float(sent_abs / core_abs)
    out["sentinel_incremental_cagr_delta"] = float(out["sentinel"]["cagr_delta"] - out["core"]["cagr_delta"])
    return out


def frozen_holdouts(old_frame: pd.DataFrame, reconv_frame: pd.DataFrame) -> list[str]:
    old_ids = adv.security_ids(old_frame)
    reconv_ids = set(adv.security_ids(reconv_frame))
    eligible = []
    for i, sid in enumerate(sorted(map(str, old_ids))):
        shard = i % ORIGINAL_SHARDS
        if shard < PREVIOUSLY_UNTOUCHED_MIN_SHARD: continue
        if sid not in reconv_ids: continue
        eligible.append(sid)
    eligible.sort(key=lambda sid: hashlib.sha256(("canonical-reconvergence-holdout-v1:" + sid).encode()).hexdigest())
    if len(eligible) < HOLDOUT_COUNT:
        raise RuntimeError(f"insufficient untouched common held IDs: {len(eligible)}")
    return eligible[:HOLDOUT_COUNT]


def run_baseline(args) -> dict:
    root = args.output.resolve(); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    selected = adv.build_selected(args.control_source, args.median_overlay)
    old = adv.execute(selected, root / "old", "old_baseline", keep_raw=True)
    adv.assert_baseline(old)
    reconv_src = apply_reconvergence(selected)
    reconv = adv.execute(reconv_src, root / "reconv", "reconv_baseline", keep_raw=True)
    oldf = load_daily(root / "old" / "daily.csv"); recf = load_daily(root / "reconv" / "daily.csv")
    holdouts = frozen_holdouts(oldf, recf)
    result = {
        "schema": SCHEMA, "suite": "baseline", "status": "PASS",
        "system": SYSTEM, "experiment_head": os.environ.get("GITHUB_SHA"),
        "old": old, "reconvergence": reconv,
        "architecture_change_only": True,
        "holdout_policy": {
            "count": HOLDOUT_COUNT,
            "original_96_shard_minimum": PREVIOUSLY_UNTOUCHED_MIN_SHARD,
            "selection": "sha256(canonical-reconvergence-holdout-v1:<security_id>) among IDs held by both unperturbed paths",
            "performance_used_for_selection": False,
        },
        "holdout_security_ids": holdouts,
    }
    write_json(root / "RESULT.json", result)
    write_json(root / "holdout-security-ids.json", holdouts)
    return result


def run_pair_case(args) -> dict:
    root = args.output.resolve(); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    base = json.loads((args.baseline_input / "RESULT.json").read_text())
    selected = adv.build_selected(args.control_source, args.median_overlay)
    reconv_src = apply_reconvergence(selected)

    security_id = None
    if args.case_kind == "loo":
        security_id = args.case_value
        old_src = adv.patch_exclusion(selected, {security_id})
        new_src = adv.patch_exclusion(reconv_src, {security_id})
    elif args.case_kind == "dropout":
        seed = int(args.case_value)
        old_src = adv.patch_dropout(selected, 0.01, seed)
        new_src = adv.patch_dropout(reconv_src, 0.01, seed)
    else:
        raise RuntimeError(args.case_kind)

    old = adv.execute(old_src, root / "old", f"old_{args.case_kind}_{hashlib.sha256(args.case_value.encode()).hexdigest()[:10]}", keep_raw=True)
    new = adv.execute(new_src, root / "reconv", f"reconv_{args.case_kind}_{hashlib.sha256(args.case_value.encode()).hexdigest()[:10]}", keep_raw=True)
    old_ref = load_daily(args.baseline_input / "old" / "daily.csv")
    new_ref = load_daily(args.baseline_input / "reconv" / "daily.csv")
    old_var = load_daily(root / "old" / "daily.csv")
    new_var = load_daily(root / "reconv" / "daily.csv")

    result = {
        "schema": SCHEMA, "suite": "case", "status": "PASS", "case_kind": args.case_kind,
        "case_value": args.case_value, "security_id": security_id,
        "old": {"event": old, "delta": metric_delta(base["old"], old), "path": path_metrics(old_ref, old_var, security_id)},
        "reconvergence": {"event": new, "delta": metric_delta(base["reconvergence"], new), "path": path_metrics(new_ref, new_var, security_id)},
        "performance_selection": "FORBIDDEN_VALIDATION_ONLY",
    }
    write_json(root / "RESULT.json", result)
    return result


def run_execution(args) -> dict:
    root = args.output.resolve(); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    base = json.loads((args.baseline_input / "RESULT.json").read_text())
    selected = adv.build_selected(args.control_source, args.median_overlay)
    reconv_src = apply_reconvergence(selected)
    old_ref = load_daily(args.baseline_input / "old" / "daily.csv")
    new_ref = load_daily(args.baseline_input / "reconv" / "daily.csv")
    rows = []
    for bp in (15, 25):
        value = bp / 10000.0
        old = adv.execute(adv.patch_execution(selected, "cost", value), root / f"old-{bp}", f"old_cost_{bp}", keep_raw=True)
        new = adv.execute(adv.patch_execution(reconv_src, "cost", value), root / f"reconv-{bp}", f"reconv_cost_{bp}", keep_raw=True)
        rows.append({
            "bp": bp,
            "old": {"event": old, "delta": metric_delta(base["old"], old), "path": path_metrics(old_ref, load_daily(root / f"old-{bp}" / "daily.csv"))},
            "reconvergence": {"event": new, "delta": metric_delta(base["reconvergence"], new), "path": path_metrics(new_ref, load_daily(root / f"reconv-{bp}" / "daily.csv"))},
        })
    result = {"schema": SCHEMA, "suite": "execution", "status": "PASS", "cases": rows, "performance_selection": "FORBIDDEN_VALIDATION_ONLY"}
    write_json(root / "RESULT.json", result)
    return result


def med(values):
    xs = [float(x) for x in values if x is not None and np.isfinite(float(x))]
    return None if not xs else float(np.median(xs))


def run_aggregate(args) -> dict:
    base = json.loads((args.baseline_input / "RESULT.json").read_text())
    results = []
    for p in sorted(args.cases_root.rglob("RESULT.json")):
        try: r = json.loads(p.read_text())
        except Exception: continue
        if r.get("suite") in ("case", "execution") and r.get("status") == "PASS": results.append(r)
    loo = [r for r in results if r.get("case_kind") == "loo"]
    drop = [r for r in results if r.get("case_kind") == "dropout"]
    exe = next((r for r in results if r.get("suite") == "execution"), None)

    old_post = [r["old"]["path"].get("post_last_holding_mean_symmetric_difference") for r in loo]
    new_post = [r["reconvergence"]["path"].get("post_last_holding_mean_symmetric_difference") for r in loo]
    improved_loo = 0
    for r in loo:
        a = r["old"]["path"].get("post_last_holding_mean_symmetric_difference")
        b = r["reconvergence"]["path"].get("post_last_holding_mean_symmetric_difference")
        if a is not None and b is not None and b < a: improved_loo += 1

    old_amp = [r["old"]["delta"].get("sentinel_to_core_abs_cagr_impact_ratio") for r in loo]
    new_amp = [r["reconvergence"]["delta"].get("sentinel_to_core_abs_cagr_impact_ratio") for r in loo]
    old_drop_core = [abs(r["old"]["delta"]["core"]["cagr_delta"]) for r in drop]
    new_drop_core = [abs(r["reconvergence"]["delta"]["core"]["cagr_delta"]) for r in drop]
    old_drop_full = [abs(r["old"]["delta"]["sentinel"]["cagr_delta"]) for r in drop]
    new_drop_full = [abs(r["reconvergence"]["delta"]["sentinel"]["cagr_delta"]) for r in drop]

    gates = {
        "all_6_untouched_loo_completed": len(loo) == HOLDOUT_COUNT,
        "all_3_dropout_completed": len(drop) == 3,
        "loo_majority_path_improves": improved_loo >= 4,
        "loo_median_path_dispersion_halved": (med(new_post) is not None and med(old_post) is not None and med(new_post) <= 0.5 * med(old_post)),
        "sentinel_amplification_not_worse": (med(new_amp) is not None and med(old_amp) is not None and med(new_amp) <= med(old_amp)),
        "dropout_core_median_impact_reduced": (med(new_drop_core) is not None and med(old_drop_core) is not None and med(new_drop_core) < med(old_drop_core)),
        "dropout_full_median_impact_reduced": (med(new_drop_full) is not None and med(old_drop_full) is not None and med(new_drop_full) < med(old_drop_full)),
    }
    if exe is not None:
        rows = sorted(exe["cases"], key=lambda x: x["bp"])
        if len(rows) == 2:
            gates["reconvergence_cost_response_monotonic_15_to_25bp"] = rows[1]["reconvergence"]["event"]["sentinel"]["20"]["cagr"] <= rows[0]["reconvergence"]["event"]["sentinel"]["20"]["cagr"]
            gates["old_cost_response_monotonic_15_to_25bp"] = rows[1]["old"]["event"]["sentinel"]["20"]["cagr"] <= rows[0]["old"]["event"]["sentinel"]["20"]["cagr"]

    summary = {
        "loo_completed": len(loo), "dropout_completed": len(drop), "execution_completed": exe is not None,
        "loo_old_median_post_last_symdiff": med(old_post),
        "loo_reconvergence_median_post_last_symdiff": med(new_post),
        "loo_cases_with_lower_path_dispersion": improved_loo,
        "loo_old_median_sentinel_to_core_impact_ratio": med(old_amp),
        "loo_reconvergence_median_sentinel_to_core_impact_ratio": med(new_amp),
        "dropout_old_median_abs_core_cagr_delta": med(old_drop_core),
        "dropout_reconvergence_median_abs_core_cagr_delta": med(new_drop_core),
        "dropout_old_median_abs_full_cagr_delta": med(old_drop_full),
        "dropout_reconvergence_median_abs_full_cagr_delta": med(new_drop_full),
    }
    required = [v for k, v in gates.items() if k != "old_cost_response_monotonic_15_to_25bp"]
    verdict = "PASS" if required and all(required) else "FAIL"
    result = {
        "schema": SCHEMA, "suite": "aggregate", "status": "PASS", "verdict": verdict,
        "baseline": base, "summary": summary, "gates": gates,
        "cases": results,
        "interpretation_contract": "Robustness-first. No parameter selection or historical performance optimization was permitted.",
    }
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True); write_json(out / "RESULT.json", result)
    lines = [
        "# Wealth Core V5 canonical reconvergence v1",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## Robustness summary",
        "",
        f"- Untouched security LOO completed: {len(loo)}/{HOLDOUT_COUNT}",
        f"- Median post-exclusion portfolio symmetric difference: old {summary['loo_old_median_post_last_symdiff']} -> reconvergence {summary['loo_reconvergence_median_post_last_symdiff']}",
        f"- LOO cases with lower path dispersion: {improved_loo}/{len(loo) if loo else 0}",
        f"- Median Sentinel/Core absolute CAGR-impact ratio: old {summary['loo_old_median_sentinel_to_core_impact_ratio']} -> reconvergence {summary['loo_reconvergence_median_sentinel_to_core_impact_ratio']}",
        f"- Median 1% universe-dropout |Core CAGR delta|: old {summary['dropout_old_median_abs_core_cagr_delta']} -> reconvergence {summary['dropout_reconvergence_median_abs_core_cagr_delta']}",
        f"- Median 1% universe-dropout |full-system CAGR delta|: old {summary['dropout_old_median_abs_full_cagr_delta']} -> reconvergence {summary['dropout_reconvergence_median_abs_full_cagr_delta']}",
        "",
        "## Gates",
        "",
    ]
    lines += [f"- {'PASS' if v else 'FAIL'} — {k}" for k, v in gates.items()]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["baseline", "case", "execution", "aggregate"])
    ap.add_argument("--control-source", type=Path)
    ap.add_argument("--median-overlay", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--baseline-input", type=Path)
    ap.add_argument("--cases-root", type=Path)
    ap.add_argument("--case-kind", choices=["loo", "dropout"])
    ap.add_argument("--case-value")
    args = ap.parse_args()

    if args.suite in ("baseline", "case", "execution") and (args.control_source is None or args.median_overlay is None):
        raise RuntimeError("source authorities required")
    if args.suite == "baseline": result = run_baseline(args)
    elif args.suite == "case":
        if args.baseline_input is None or args.case_kind is None or args.case_value is None: raise RuntimeError("case inputs required")
        result = run_pair_case(args)
    elif args.suite == "execution":
        if args.baseline_input is None: raise RuntimeError("baseline input required")
        result = run_execution(args)
    else:
        if args.baseline_input is None or args.cases_root is None: raise RuntimeError("aggregate inputs required")
        result = run_aggregate(args)
    print("[RECONVERGENCE_RESULT] " + json.dumps({"suite": args.suite, "status": result.get("status"), "verdict": result.get("verdict")}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
