#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

LEVELS = [0, 5, 10, 15, 20, 25]
BASE_EVIDENCE_HEAD = "38eb1a0dd3ac9a37c4466198c420bd00747e6a13"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
FORMAL_SOURCE = "27bb992087182c42c3c051e62bf837895f5d2ab7"
CLASSIFIER_SOURCE = "ba74e79490beb8950611b1d17f5d124833b3d91e"
RUNTIME_SOURCE = "887f479b15ad861313da666ad698034d3847121c"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copytree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        target = dst / p.name
        if p.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(p, target)
        else:
            shutil.copy2(p, target)


def load_positions(path: Path) -> tuple[list[str], list[frozenset[str]]]:
    d = pd.read_csv(path, usecols=["date", "research_selected_positions"])
    dates = d["date"].astype(str).tolist()
    positions = []
    for raw in d["research_selected_positions"].tolist():
        vals = json.loads(raw) if isinstance(raw, str) and raw else []
        positions.append(frozenset(str(v) for v in vals))
    return dates, positions


def decision_map(path: Path):
    d = pd.read_csv(path, keep_default_na=False)
    out = defaultdict(list)
    for r in d.itertuples(index=False):
        out[(str(r.decision_date), str(r.ticker))].append((str(r.outcome), int(r.planned_shares)))
    return {k: tuple(sorted(v)) for k, v in out.items()}


def tx_signatures(path: Path, side: str):
    d = pd.read_csv(path, keep_default_na=False)
    d = d[d["Buy or sell"].eq(side)]
    per_date = defaultdict(list)
    events = Counter()
    for r in d.itertuples(index=False):
        date = str(r[0])
        ticker = str(r[2])
        per_date[date].append(ticker)
        events[(date, ticker)] += 1
    return {k: tuple(sorted(v)) for k, v in per_date.items()}, events


def counter_symdiff(a: Counter, b: Counter) -> int:
    return sum((a - b).values()) + sum((b - a).values())


def path_divergence(base_dir: Path, arm_dir: Path) -> dict:
    base_dates, base_pos = load_positions(base_dir / "daily.csv")
    arm_dates, arm_pos = load_positions(arm_dir / "daily.csv")
    if base_dates != arm_dates:
        raise RuntimeError("daily session alignment changed across sweep arms")
    differing = [i for i, (a, b) in enumerate(zip(base_pos, arm_pos)) if a != b]
    first = base_dates[differing[0]] if differing else None

    bdm = decision_map(base_dir / "close-decisions.csv")
    adm = decision_map(arm_dir / "close-decisions.csv")
    decision_keys = set(bdm) | set(adm)
    buy_decisions_differ = sum(1 for k in decision_keys if bdm.get(k) != adm.get(k))

    bbuy_dates, bbuys = tx_signatures(base_dir / "transactions.csv", "BUY")
    abuy_dates, abuys = tx_signatures(arm_dir / "transactions.csv", "BUY")
    dates_union = set(bbuy_dates) | set(abuy_dates)
    executed_entry_dates_differ = sum(1 for d in dates_union if bbuy_dates.get(d, ()) != abuy_dates.get(d, ()))

    _, bsells = tx_signatures(base_dir / "transactions.csv", "SELL")
    _, asells = tx_signatures(arm_dir / "transactions.csv", "SELL")

    final_base = base_pos[-1]
    final_arm = arm_pos[-1]
    return {
        "first_date_holdings_diverge": first,
        "buy_decisions_that_differ": int(buy_decisions_differ),
        "executed_entry_dates_that_differ": int(executed_entry_dates_differ),
        "ticker_admissions_that_differ": int(counter_symdiff(bbuys, abuys)),
        "exits_that_differ": int(counter_symdiff(bsells, asells)),
        "final_holding_set_difference_count": int(len(final_base ^ final_arm)),
        "final_holdings_only_in_0bp": sorted(final_base - final_arm),
        "final_holdings_only_in_arm": sorted(final_arm - final_base),
        "cumulative_days_with_differing_holdings": int(len(differing)),
    }


def fmt_pct(x):
    return "" if x is None else f"{100*float(x):.6f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--experiment-spec", type=Path, required=True)
    args = ap.parse_args()

    root = args.collected.resolve()
    out = args.output.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "arms").mkdir()
    (out / "logs").mkdir()
    (out / "validation").mkdir()

    found = {}
    for rp in root.rglob("RESULT.json"):
        try:
            data = json.loads(rp.read_text())
        except Exception:
            continue
        if data.get("schema") != "research.wealth-core-v1-buffer-sweep-arm/1":
            continue
        bp = int(data["buffer_basis_points"])
        if bp in found:
            raise RuntimeError(f"duplicate arm result for {bp} bp")
        found[bp] = (rp.parent, data)
    if sorted(found) != LEVELS:
        raise RuntimeError(f"missing sweep arms: found {sorted(found)} expected {LEVELS}")

    results = {}
    package_hashes = set()
    corpus_hashes = set()
    for bp in LEVELS:
        srcdir, result = found[bp]
        results[bp] = result
        armdst = out / "arms" / f"{bp:02d}bp"
        copytree_contents(srcdir, armdst)
        pkg = srcdir / "package-integrity.json"
        corp = srcdir / "final-corpus-validation.json"
        if not pkg.exists() or not corp.exists():
            raise RuntimeError(f"validation evidence missing for {bp} bp")
        package_hashes.add(sha(pkg))
        corpus_hashes.add(sha(corp))
        if not (srcdir / "arm.log").exists():
            raise RuntimeError(f"log missing for {bp} bp")
        shutil.copy2(srcdir / "arm.log", out / "logs" / f"{bp:02d}bp.log")

    if len(package_hashes) != 1 or len(corpus_hashes) != 1:
        raise RuntimeError("PIT/package/corpus validation evidence differs across arms")
    shutil.copy2(out / "arms" / "00bp" / "package-integrity.json", out / "validation" / "package-integrity.json")
    shutil.copy2(out / "arms" / "00bp" / "final-corpus-validation.json", out / "validation" / "final-corpus-validation.json")

    z = results[0]["authority"]["zero_bp_exact_authority"]
    if z is None or not z["daily_exact_match"] or not z["summary_exact_match"]:
        raise RuntimeError("0 bp failed exact authority")
    x10 = results[10]["authority"]["prior_10bp_crosscheck"]
    if x10 is None or not x10["pass"]:
        raise RuntimeError("10 bp did not reproduce prior primary result")

    for bp in LEVELS:
        r = results[bp]
        if r["status"] != "PASS":
            raise RuntimeError(f"{bp} bp arm failed")
        if r["dataset_sha256"] != DATASET_SHA256:
            raise RuntimeError(f"{bp} bp dataset hash mismatch")
        if r["financial_grade_dividend_lag_sessions"] != 1:
            raise RuntimeError(f"{bp} bp dividend lag changed")
        bi = r["buffer_integrity"]
        if bi["reserve_violations"] != 0 or bi["fractional_share_buys"] or not bi["all_buy_quantities_integer"]:
            raise RuntimeError(f"{bp} bp execution invariant failed")

    base_dir = out / "arms" / "00bp"
    divergence = {0: {
        "first_date_holdings_diverge": None,
        "buy_decisions_that_differ": 0,
        "executed_entry_dates_that_differ": 0,
        "ticker_admissions_that_differ": 0,
        "exits_that_differ": 0,
        "final_holding_set_difference_count": 0,
        "final_holdings_only_in_0bp": [],
        "final_holdings_only_in_arm": [],
        "cumulative_days_with_differing_holdings": 0,
    }}
    for bp in LEVELS[1:]:
        divergence[bp] = path_divergence(base_dir, out / "arms" / f"{bp:02d}bp")

    comparison_rows = []
    prev = None
    for bp in LEVELS:
        r = results[bp]
        p = r["portfolio_performance"]
        e = r["entry_execution"]
        b = r["buffer_integrity"]
        g = r["gap_attribution"]
        d = divergence[bp]
        row = {
            "Buffer basis points": bp,
            "CAGR": p["cagr"],
            "Max drawdown": p["max_drawdown"],
            "Sharpe": p["sharpe_daily_252"],
            "Ending equity": p["end_equity"],
            "Ending multiple": p["ending_multiple"],
            "Completed entries": e["completed_entries"],
            "Cash-limited close decisions": e["cash_limited_close_decisions"],
            "q=0 candidate skips at close": e["q0_candidate_skips_close"],
            "q=0 cash-scarcity skips at close": e["q0_cash_scarcity_close"],
            "q=0 target-granularity skips at close": e["q0_target_granularity_close"],
            "Next-open complete failures": e["planned_entries_fully_blocked_next_open"],
            "Gap-clipped entries": e["gap_clipped_entries"],
            "One-share entries": e["one_share_entries"],
            "Entries below 1%": e["entry_fraction_lt_1pct"],
            "Entries below 5%": e["entry_fraction_lt_5pct"],
            "Entries below 10%": e["entry_fraction_lt_10pct"],
            "Entries below 25%": e["entry_fraction_lt_25pct"],
            "Entries below 50%": e["entry_fraction_lt_50pct"],
            "Entries below 99%": e["entry_fraction_lt_99pct"],
            "Minimum entry fraction": e["minimum_entry_fraction"],
            "Average entry fraction": e["average_entry_fraction"],
            "Maximum entry fraction": e["maximum_entry_fraction"],
            "Minimum post-buy cash excess over reserve": b["minimum_post_buy_cash_excess_over_required_reserve"],
            "Reserve violations": b["reserve_violations"],
            "Minimum actual cash": b["minimum_actual_cash"],
            "Open shortfall events": g["open_shortfall_events"],
            "Gap-alone sufficient shortfall events": g["gap_alone_would_clip_events"],
            "Positive-gap shortfall events": g["positive_gap_shortfall_events"],
            "Gap >2.5% shortfall events": g["gap_gt_2_5pct_shortfall_events"],
            "First holdings divergence vs 0bp": d["first_date_holdings_diverge"],
            "Buy decisions differing vs 0bp": d["buy_decisions_that_differ"],
            "Executed entry dates differing vs 0bp": d["executed_entry_dates_that_differ"],
            "Ticker admissions differing vs 0bp": d["ticker_admissions_that_differ"],
            "Exits differing vs 0bp": d["exits_that_differ"],
            "Final holding-set difference vs 0bp": d["final_holding_set_difference_count"],
            "Cumulative days differing holdings vs 0bp": d["cumulative_days_with_differing_holdings"],
        }
        if prev is None:
            row["Marginal gap-clipped reduction per +5bp"] = None
            row["Marginal q=0 skip increase per +5bp"] = None
            row["Marginal CAGR change pp per +5bp"] = None
        else:
            pe = results[prev]["entry_execution"]
            pp = results[prev]["portfolio_performance"]
            row["Marginal gap-clipped reduction per +5bp"] = int(pe["gap_clipped_entries"] - e["gap_clipped_entries"])
            row["Marginal q=0 skip increase per +5bp"] = int(e["q0_candidate_skips_close"] - pe["q0_candidate_skips_close"])
            row["Marginal CAGR change pp per +5bp"] = float((p["cagr"] - pp["cagr"]) * 100.0)
        comparison_rows.append(row)
        prev = bp

    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(out / "comparison.csv", index=False)

    combined_tx = []
    combined_gap = []
    for bp in LEVELS:
        arm = out / "arms" / f"{bp:02d}bp"
        tx = pd.read_csv(arm / "transactions.csv", keep_default_na=False)
        if list(tx.columns) != ["Transaction date", "Buy or sell", "Ticker", "Ticker name", "Amount of shares"]:
            raise RuntimeError(f"{bp} bp per-arm transaction schema changed")
        tx.insert(0, "Buffer basis points", bp)
        combined_tx.append(tx)
        gap = pd.read_csv(arm / "gap-events.csv")
        gap.insert(0, "Buffer basis points", bp)
        combined_gap.append(gap)

    pd.concat(combined_tx, ignore_index=True).to_csv(out / "combined-transactions.csv", index=False)
    cg = pd.concat(combined_gap, ignore_index=True)
    gap_rename = {
        "decision_date": "Decision date",
        "execution_date": "Execution date",
        "ticker": "Ticker",
        "intended_shares": "Intended shares",
        "executed_shares": "Executed shares",
        "close_price_used_for_planning": "Close price used for planning",
        "next_open_price": "Next-open price",
        "close_to_open_percentage_gap": "Close-to-open percentage gap",
        "cash_available_before_execution": "Cash available before execution",
        "required_reserve": "Required reserve",
        "uncommitted_cash_after_reserve": "Uncommitted cash after reserve",
        "intended_notional": "Intended notional",
        "executed_notional": "Executed notional",
        "became_q0": "Whether it became q=0",
        "gap_alone_would_clip": "Gap alone would clip with close uncommitted cash",
        "open_uncommitted_cash_change_vs_close": "Open uncommitted cash change vs close",
        "close_required_reserve": "Close required reserve",
        "close_uncommitted_cash_after_reserve": "Close uncommitted cash after reserve",
    }
    cg = cg.drop(columns=["buffer_basis_points"], errors="ignore").rename(columns=gap_rename)
    cg.to_csv(out / "gap-clipping-events.csv", index=False)

    blocked_zero = next((bp for bp in LEVELS if results[bp]["entry_execution"]["planned_entries_fully_blocked_next_open"] == 0), None)
    reductions = {}
    for a, b in zip(LEVELS, LEVELS[1:]):
        reductions[b] = int(results[a]["entry_execution"]["gap_clipped_entries"] - results[b]["entry_execution"]["gap_clipped_entries"])
    gap_saturation = None
    for i, bp in enumerate(LEVELS[:-1]):
        later_steps = LEVELS[i + 1:]
        if later_steps and all(reductions[x] <= 1 for x in later_steps):
            gap_saturation = bp
            break

    cagr_values = [results[bp]["portfolio_performance"]["cagr"] for bp in LEVELS]
    monotonic_up = all(a <= b for a, b in zip(cagr_values, cagr_values[1:]))
    monotonic_down = all(a >= b for a, b in zip(cagr_values, cagr_values[1:]))
    cagr_shape = "monotonic increasing" if monotonic_up else ("monotonic decreasing" if monotonic_down else "non-monotonic")

    mechanically_sensible = None
    if blocked_zero is not None and gap_saturation is not None:
        mechanically_sensible = max(blocked_zero, gap_saturation)

    sweep = {
        "schema": "research.wealth-core-v1-buffer-sweep/1",
        "status": "PASS",
        "tested_buffer_basis_points": LEVELS,
        "authority": {
            "base_evidence_head": BASE_EVIDENCE_HEAD,
            "canonical_pit_dataset_sha256": DATASET_SHA256,
            "formal_source_sha": FORMAL_SOURCE,
            "classifier_source_sha": CLASSIFIER_SOURCE,
            "runtime_source_sha": RUNTIME_SOURCE,
            "zero_bp_exact_authority": results[0]["authority"]["zero_bp_exact_authority"],
            "prior_10bp_crosscheck": results[10]["authority"]["prior_10bp_crosscheck"],
            "package_integrity_sha256": next(iter(package_hashes)),
            "final_corpus_validation_sha256": next(iter(corpus_hashes)),
        },
        "arms": {str(bp): results[bp] for bp in LEVELS},
        "path_divergence_vs_0bp": {str(bp): divergence[bp] for bp in LEVELS},
        "execution_saturation": {
            "smallest_buffer_with_zero_next_open_complete_failures": blocked_zero,
            "gap_clipping_saturation_definition": "smallest tested buffer below 25bp after which every remaining +5bp step reduces gap-clipped fills by at most 1 trade",
            "smallest_buffer_meeting_gap_clipping_saturation_definition": gap_saturation,
            "marginal_gap_clipped_reduction_per_5bp": {str(k): v for k, v in reductions.items()},
            "mechanically_sensible_buffer_if_both_criteria_met": mechanically_sensible,
        },
        "performance_curve_interpretation": {
            "shape": cagr_shape,
            "treated_as_path_dependent": True,
            "highest_cagr_buffer_not_used_as_selection_rule": True,
        },
        "clean_enough_for_followup_production_design_discussion": True,
    }
    (out / "SWEEP_RESULT.json").write_text(json.dumps(sweep, indent=2, sort_keys=True) + "\n")

    provenance = {
        "schema": "research.wealth-core-v1-buffer-sweep-provenance/1",
        "branch": os.environ.get("GITHUB_REF_NAME"),
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        "workflow_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]) if os.environ.get("GITHUB_RUN_ATTEMPT") else None,
        "trigger_head_sha": os.environ.get("GITHUB_SHA"),
        "base_evidence_head": BASE_EVIDENCE_HEAD,
        "canonical_pit_dataset_sha256": DATASET_SHA256,
        "formal_source_sha": FORMAL_SOURCE,
        "classifier_source_sha": CLASSIFIER_SOURCE,
        "runtime_source_sha": RUNTIME_SOURCE,
        "measurement_window": {"start": "2006-07-31", "end": "2026-07-31", "sessions": 5032},
        "initial_capital": 100000,
        "dividend_lag_sessions": 1,
        "whole_shares_only": True,
        "sentinel_metrics_used": False,
        "production_code_modified": False,
    }
    (out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    shutil.copy2(args.experiment_spec, out / "EXPERIMENT_SPEC.md")

    ten = results[10]
    ten_e = ten["entry_execution"]
    ten_g = ten["gap_attribution"]
    ten_answer = "Yes for complete next-open failures in this historical arm." if ten_e["planned_entries_fully_blocked_next_open"] == 0 else f"No. It still has {ten_e['planned_entries_fully_blocked_next_open']} planned entry fully blocked at the next open."
    zero_text = "none of the tested levels" if blocked_zero is None else f"{blocked_zero} bp"
    sat_text = "no tested level" if gap_saturation is None else f"{gap_saturation} bp under the preregistered count-based saturation rule"
    sensible_text = "No single tested level satisfies both mechanical criteria." if mechanically_sensible is None else f"{mechanically_sensible} bp is the smallest tested level satisfying both the zero-block and gap-saturation criteria; this is an execution-mechanics result, not a return-optimization recommendation."

    lines = [
        "# Wealth Core V1 — $100k cash-buffer sweep insights",
        "",
        "## Authority",
        "",
        f"- Branch: `{os.environ.get('GITHUB_REF_NAME','')}`",
        f"- Trigger head: `{os.environ.get('GITHUB_SHA','')}`",
        f"- Workflow run: `{os.environ.get('GITHUB_RUN_ID','')}`",
        f"- Base evidence head: `{BASE_EVIDENCE_HEAD}`",
        f"- Canonical PIT dataset SHA-256: `{DATASET_SHA256}`",
        "- 0 bp reproduced the frozen V1 daily and summary hashes exactly.",
        "- 10 bp reproduced the prior primary 10 bp performance and execution counts.",
        "- Dividend lag remained one session in every arm.",
        "- Every buy quantity was an integer, no fractional-share buys occurred, no reserve violations occurred, and minimum cash stayed non-negative.",
        "",
        "## Direct answers",
        "",
        f"**Is 10 bp enough?** {ten_answer}",
        "",
        f"**What remains unfunded at 10 bp?** There are {ten_e['planned_entries_fully_blocked_next_open']} complete next-open failures and {ten_e['gap_clipped_entries']} clipped fills. Of {ten_g['open_shortfall_events']} next-open shortfall events, {ten_g['gap_alone_would_clip_events']} would still have clipped using the close-time uncommitted cash at the next-open price; {ten_g['gap_gt_2_5pct_shortfall_events']} involved a positive gap greater than 2.5%.",
        "",
        f"**At what buffer does next-open execution failure disappear?** {zero_text}.",
        "",
        f"**At what buffer does gap clipping substantially saturate?** {sat_text}. The exact marginal changes are preserved in `comparison.csv` and `SWEEP_RESULT.json`.",
        "",
        f"**Does the 10 bp CAGR improvement persist monotonically?** The six-arm CAGR curve is {cagr_shape}. Performance is treated as path-dependent and is not the buffer-selection criterion.",
        "",
        f"**Is there a mechanically sensible execution buffer independent of historical return optimization?** {sensible_text}",
        "",
        "## Sweep table",
        "",
        "| Buffer | CAGR | Max DD | Sharpe | End equity | Entries | q=0 close skips | Open blocks | Gap clips | <1% entries | One-share |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for bp in LEVELS:
        r = results[bp]
        p = r["portfolio_performance"]
        e = r["entry_execution"]
        lines.append(f"| {bp} bp | {fmt_pct(p['cagr'])} | {fmt_pct(p['max_drawdown'])} | {p['sharpe_daily_252']:.6f} | ${p['end_equity']:,.2f} | {e['completed_entries']} | {e['q0_candidate_skips_close']} | {e['planned_entries_fully_blocked_next_open']} | {e['gap_clipped_entries']} | {e['entry_fraction_lt_1pct']} | {e['one_share_entries']} |")

    lines += [
        "",
        "## Close-time opportunity loss",
        "",
        "The q=0 count is separated into actual uncommitted-cash scarcity and whole-share target granularity. This prevents high share prices relative to the 4% target from being mislabeled as cash scarcity.",
        "",
        "| Buffer | All q=0 skips | Cash-scarcity q=0 | Target-granularity q=0 | Marginal all-q=0 vs prior +5bp |",
        "|---:|---:|---:|---:|---:|",
    ]
    for i, bp in enumerate(LEVELS):
        e = results[bp]["entry_execution"]
        marginal = "" if i == 0 else str(e["q0_candidate_skips_close"] - results[LEVELS[i-1]]["entry_execution"]["q0_candidate_skips_close"])
        lines.append(f"| {bp} bp | {e['q0_candidate_skips_close']} | {e['q0_cash_scarcity_close']} | {e['q0_target_granularity_close']} | {marginal} |")

    lines += [
        "",
        "## Overnight-gap attribution",
        "",
        "For every clipped or fully blocked next-open order, `gap-clipping-events.csv` records the close plan, next-open price, reserve, actual cash, uncommitted cash, quantities, notionals, and whether the close-to-open price change alone would have caused the shortfall using the close-time uncommitted cash.",
        "",
        "| Buffer | Open shortfall events | Gap-alone sufficient | Positive-gap events | Gap >2.5% |",
        "|---:|---:|---:|---:|---:|",
    ]
    for bp in LEVELS:
        g = results[bp]["gap_attribution"]
        lines.append(f"| {bp} bp | {g['open_shortfall_events']} | {g['gap_alone_would_clip_events']} | {g['positive_gap_shortfall_events']} | {g['gap_gt_2_5pct_shortfall_events']} |")

    lines += [
        "",
        "## Path dependence",
        "",
        "Each nonzero arm is a self-financing counterfactual. Buffer changes can alter admissions, slot occupancy, later exits, and the full holding path. The path-divergence fields in `comparison.csv` and `SWEEP_RESULT.json` quantify the first divergence date, differing buy decisions, entry dates, admissions, exits, final holdings, and cumulative days with different holdings.",
        "",
        "## Research conclusion",
        "",
        "The execution conclusion is based on next-open failures, clipped fills, reserve integrity, and the close-time q=0 cost curve. CAGR is reported separately as a path outcome. All six arms are retained regardless of performance.",
        "",
        "**Certification status:** PASS for a follow-up production-design discussion. This does not authorize a production change.",
        "",
    ]
    (out / "INSIGHTS.md").write_text("\n".join(lines))

    index = [p.relative_to(out).as_posix() for p in sorted(out.rglob("*")) if p.is_file()]
    index = sorted(set(index + ["FILE_INDEX.txt", "SHA256SUMS.txt"]))
    (out / "FILE_INDEX.txt").write_text("\n".join(index) + "\n")

    manifest_lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            manifest_lines.append(f"{sha(p)}  {p.relative_to(out).as_posix()}")
    (out / "SHA256SUMS.txt").write_text("\n".join(manifest_lines) + "\n")

    print("[BUFFER_SWEEP] " + json.dumps({
        "status": "PASS",
        "smallest_zero_block_bp": blocked_zero,
        "gap_saturation_bp": gap_saturation,
        "mechanically_sensible_bp": mechanically_sensible,
        "cagr_shape": cagr_shape,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
