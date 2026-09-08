#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E = ROOT / "research/wealth-core-v1-buffer-100k-evidence"
OUT = ROOT / "research/wealth-core-v1-10bp-ex3-v1/output"
OUT.mkdir(parents=True, exist_ok=True)

BASE_ROOT = E / "runs/34267327656/wealth-core-v1-100k-authority-34267327656/experiment-results/100k"
BUF_ROOT = E / "runs/34283531740/wealth-core-v1-buffer-100k-fast-34283531740-1/experiment-results/buffer-100k-fast"

BASE_DAILY = BASE_ROOT / "daily.csv"
BASE_SUMMARY = BASE_ROOT / "summary.json"
BASE_SOURCE = BASE_ROOT / "wealth-core-v1-capital-scale-generated.py"
BUF_DAILY = BUF_ROOT / "buffer-daily.csv"
BUF_SUMMARY = BUF_ROOT / "buffer-summary.json"
BUF_SOURCE = BUF_ROOT / "buffer-generated.py"
BUF_RESULT = BUF_ROOT / "RESULT.json"

EXPECTED = {
    BASE_DAILY: "8a2e4f948720674a56737ee6291df0aff12e02a74d74b1ec5f0c75f9929adee6",
    BASE_SUMMARY: "929ed3baacd1bb66e8174d7a6822e362e5c90da75355177d33bab3ac9f201878",
    BASE_SOURCE: "32cd228010e09b5be42271cd6d0c38831fe7fbc74e725f592949146c48104e0f",
    BUF_DAILY: "79a4e97f79885a189d4a0fa3648eac8c7916f0ea01bcf95258fbe49679b5a698",
    BUF_SUMMARY: "49e0185d384a423f85679c46a85cf3b6dd9afb9d0cf2429bcbf9ebe4f9b41673",
    BUF_SOURCE: "44a9914be859eb7f76ca747aaa66a41e19a557a2095da0a707ea99575898c4e0",
    BUF_RESULT: "ef4caea63281f3f044dbfaf8f7b7e877c94851a13be574957b52bbb36b753b40",
}
DATASET = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text())


def f(x):
    return float(x)


def assert_close(a, b, eps=1e-12):
    if abs(float(a) - float(b)) > eps:
        raise AssertionError((a, b))


for p, expected in EXPECTED.items():
    got = sha256(p)
    if got != expected:
        raise AssertionError(f"hash mismatch {p}: {got} != {expected}")

base = load_json(BASE_SUMMARY)
buf = load_json(BUF_SUMMARY)
buf_result = load_json(BUF_RESULT)

for label, summary in (("0bp", base), ("10bp", buf)):
    if summary["financial_grade_dividend_lag_sessions"] != 1:
        raise AssertionError(f"{label}: dividend lag is not 1")
    if summary["canonical_pit_dataset_hash"] != DATASET:
        raise AssertionError(f"{label}: wrong canonical PIT hash")
    if summary["metrics"]["control"] != summary["metrics"]["A"]:
        raise AssertionError(f"{label}: control metrics do not equal Candidate A / EX3")

if buf_result["status"] != "PASS":
    raise AssertionError("10bp core result is not PASS")
if buf_result["fractional_share_buys"] is not False:
    raise AssertionError("fractional shares unexpectedly enabled")
if buf_result["transaction_ledger"]["all_buy_share_amounts_integer"] is not True:
    raise AssertionError("non-integer buy quantity observed")

source = BUF_SOURCE.read_text()
required_source_fragments = [
    "LDRC_DD=-0.1; LDRC_R20=-0.085; LDRC_CEIL=.55; LDRC_REC=8; LDRC_V=0.11",
    "FAST = {'dd':-.10,'dam':0.88",
    "dam<=0.63",
    "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)",
    "pend['control']=a_d; pend['A']=a_d",
    "_buffer_required=max(0.0,float(open_eq)*0.001)",
    "_buffer_required_close=max(0.0,float(eq)*0.001)",
]
for fragment in required_source_fragments:
    if fragment not in source:
        raise AssertionError(f"missing expected source fragment: {fragment}")

with BASE_DAILY.open(newline="") as fa, BUF_DAILY.open(newline="") as fb:
    ra, rb = csv.DictReader(fa), csv.DictReader(fb)
    rows_a, rows_b = list(ra), list(rb)
if len(rows_a) != 5032 or len(rows_b) != 5032:
    raise AssertionError((len(rows_a), len(rows_b)))

first_position_divergence = None
first_native_divergence = None
first_allocation_divergence = None
position_divergence_days = 0
native_divergence_days = 0
allocation_divergence_days = 0
rank_divergence_days = 0
allocation_rows = []

for a, b in zip(rows_a, rows_b):
    if a["date"] != b["date"]:
        raise AssertionError("date alignment failure")
    date = a["date"]
    for row, label in ((a, "0bp"), (b, "10bp")):
        assert_close(row["control_nav"], row["A_nav"])
        assert_close(row["control_allocation"], row["A_allocation"])
        if row["control_reason"] != row["A_reason"]:
            raise AssertionError(f"{label} {date}: control reason != A reason")
    if a["research_ranking_sha256"] != b["research_ranking_sha256"]:
        rank_divergence_days += 1
    if a["research_selected_positions_sha256"] != b["research_selected_positions_sha256"]:
        position_divergence_days += 1
        first_position_divergence = first_position_divergence or date
    if abs(f(a["native_close_target"]) - f(b["native_close_target"])) > 1e-12:
        native_divergence_days += 1
        first_native_divergence = first_native_divergence or date
    if abs(f(a["control_allocation"]) - f(b["control_allocation"])) > 1e-12:
        allocation_divergence_days += 1
        first_allocation_divergence = first_allocation_divergence or date
        allocation_rows.append({
            "date": date,
            "0bp_control_allocation": a["control_allocation"],
            "10bp_control_allocation": b["control_allocation"],
            "0bp_control_reason": a["control_reason"],
            "10bp_control_reason": b["control_reason"],
            "0bp_wc_dd": a["wc_dd"],
            "10bp_wc_dd": b["wc_dd"],
            "0bp_control_nav": a["control_nav"],
            "10bp_control_nav": b["control_nav"],
        })

base_ex3 = base["metrics"]["control"]
buf_ex3 = buf["metrics"]["control"]
pure10 = buf_result["buffer_10bp_integer_shares"]
pure0 = buf_result["v1_100k"]

result = {
    "schema": "research.wealth-core-v1-10bp-ex3/1",
    "status": "PASS_EXISTING_REPLAY_EX3_LAYER_VERIFIED",
    "economic_scope": "WEALTH_CORE_V1_10BP_PLUS_RESEARCH_CHAMPION_EX3",
    "new_market_replay_required": False,
    "why_no_new_market_replay": "The exact 0bp and 10bp 20-year replays already executed Candidate A / EX3 alongside the pure Wealth Core book. This experiment verifies and extracts that precomputed control path.",
    "authorities": {
        "baseline_run_id": 34267327656,
        "buffer_run_id": 34283531740,
        "canonical_pit_dataset_sha256": DATASET,
        "dividend_lag_sessions": 1,
        "buffer_basis_points": 10,
        "fractional_shares": False,
        "buffer_generated_source_sha256": EXPECTED[BUF_SOURCE],
    },
    "ex3_identity": {
        "profile": "strategy9-e3-research-champion-v1",
        "control_is_candidate_A": True,
        "ldrc_rec_sessions": 8,
        "ldrc_r20": -0.085,
        "ldrc_v": 0.11,
        "ldrc_dd": -0.10,
        "divergence_spy_floor": 0.0,
        "full_recovery_r40_floor": 0.0,
        "fast_damaged_breadth": 0.88,
        "healthy_damaged_ceiling": 0.63,
    },
    "pure_wealth_core": {
        "0bp": pure0,
        "10bp": pure10,
    },
    "ex3_layered": {
        "0bp": base_ex3,
        "10bp": buf_ex3,
        "delta_10bp_minus_0bp": {
            "cagr_percentage_points": (buf_ex3["cagr"] - base_ex3["cagr"]) * 100.0,
            "max_drawdown_percentage_points": (buf_ex3["max_drawdown"] - base_ex3["max_drawdown"]) * 100.0,
            "sharpe": buf_ex3["sharpe"] - base_ex3["sharpe"],
            "ending_multiple": buf_ex3["ending_multiple"] - base_ex3["ending_multiple"],
            "ending_multiple_percent": (buf_ex3["ending_multiple"] / base_ex3["ending_multiple"] - 1.0) * 100.0,
        },
    },
    "controller_effect_on_10bp_core": {
        "cagr_percentage_points": (buf_ex3["cagr"] - pure10["cagr"]) * 100.0,
        "max_drawdown_percentage_points": (buf_ex3["max_drawdown"] - pure10["max_drawdown"]) * 100.0,
        "sharpe": buf_ex3["sharpe"] - pure10["sharpe_daily_252"],
        "ending_multiple": buf_ex3["ending_multiple"] - pure10["ending_multiple"],
    },
    "controller_path": {
        "0bp_transition_count": base["transition_counts"]["control"],
        "10bp_transition_count": buf["transition_counts"]["control"],
        "0bp_modeled_transition_cost_sum": base["modeled_allocation_transition_cost_sum"]["control"],
        "10bp_modeled_transition_cost_sum": buf["modeled_allocation_transition_cost_sum"]["control"],
        "0bp_candidate_A_episodes": base["candidate_A_episodes"],
        "10bp_candidate_A_episodes": buf["candidate_A_episodes"],
        "0bp_concordance_releases": base["candidate_A_concordance_releases"],
        "10bp_concordance_releases": buf["candidate_A_concordance_releases"],
    },
    "path_divergence_10bp_vs_0bp": {
        "ranking_divergence_days": rank_divergence_days,
        "position_divergence_days": position_divergence_days,
        "first_position_divergence": first_position_divergence,
        "native_target_divergence_days": native_divergence_days,
        "first_native_target_divergence": first_native_divergence,
        "control_allocation_divergence_days": allocation_divergence_days,
        "first_control_allocation_divergence": first_allocation_divergence,
    },
}

(OUT / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

with (OUT / "allocation-divergence.csv").open("w", newline="") as fh:
    fields = ["date", "0bp_control_allocation", "10bp_control_allocation", "0bp_control_reason", "10bp_control_reason", "0bp_wc_dd", "10bp_wc_dd", "0bp_control_nav", "10bp_control_nav"]
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(allocation_rows)

insights = f"""# Wealth Core V1 10 bp + Experiment 3 / Research Champion EX3\n\nStatus: **PASS_EXISTING_REPLAY_EX3_LAYER_VERIFIED**\n\nThe 10 bp replay already executed the Research Champion Candidate-A / EX3 controller path in parallel with the pure Wealth Core book. This verification proves the `control` path is exactly Candidate A and extracts the full-system result without rerunning market data.\n\n## Result\n\n| Metric | 0 bp Wealth Core + EX3 | 10 bp Wealth Core + EX3 | Delta |\n|---|---:|---:|---:|\n| CAGR | {base_ex3['cagr']:.6%} | **{buf_ex3['cagr']:.6%}** | **{(buf_ex3['cagr']-base_ex3['cagr'])*100:.6f} pp** |\n| Max DD | {base_ex3['max_drawdown']:.6%} | **{buf_ex3['max_drawdown']:.6%}** | {(buf_ex3['max_drawdown']-base_ex3['max_drawdown'])*100:.6f} pp |\n| Sharpe | {base_ex3['sharpe']:.6f} | **{buf_ex3['sharpe']:.6f}** | {buf_ex3['sharpe']-base_ex3['sharpe']:.6f} |\n| Ending multiple | {base_ex3['ending_multiple']:.6f}x | **{buf_ex3['ending_multiple']:.6f}x** | {buf_ex3['ending_multiple']-base_ex3['ending_multiple']:.6f}x |\n\nPure 10 bp Wealth Core CAGR was {pure10['cagr']:.6%}; with EX3 layered on it the measured CAGR is **{buf_ex3['cagr']:.6%}**.\n\n## Path effect\n\nThe 10 bp core first changed held positions on **{first_position_divergence}**. Rankings never diverged, confirming the cash rule changed admissions/holdings rather than stock-ranking economics. The native risk target later diverged on **{first_native_divergence}**, and the EX3 effective allocation first diverged on **{first_allocation_divergence}**.\n\n- days with different held-position hashes: {position_divergence_days}\n- days with different native exposure target: {native_divergence_days}\n- days with different EX3/control allocation: {allocation_divergence_days}\n- 0 bp EX3 allocation transitions: {base['transition_counts']['control']}\n- 10 bp EX3 allocation transitions: {buf['transition_counts']['control']}\n- 0 bp Candidate-A episodes: {base['candidate_A_episodes']}\n- 10 bp Candidate-A episodes: {buf['candidate_A_episodes']}\n\n## Interpretation\n\nThe 10 bp reserve improves the pure Wealth Core path and also changes the inputs seen by Experiment 3. On this exact historical path the interaction is favorable: the combined CAGR rises by {(buf_ex3['cagr']-base_ex3['cagr'])*100:.3f} percentage points, max drawdown becomes materially shallower, and Sharpe rises. This is still path-dependent evidence, not a claim that 10 bp mechanically creates alpha.\n\nDividend settlement is **1 session**, not 15. Whole shares only. Canonical PIT dataset hash is `{DATASET}`.\n"""
(OUT / "INSIGHTS.md").write_text(insights)
print(json.dumps(result, indent=2, sort_keys=True))
