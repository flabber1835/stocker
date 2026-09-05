#!/usr/bin/env python3
"""Zero-budget diagnostic: quantify Wealth Core -> Sentinel threshold coupling in E5.

This is observational only. It reruns the exact surviving E3 control and the exact
completed E5 candidate with extra telemetry fields. No decision rule, threshold,
allocation, execution, or experiment budget state is changed.

Outputs:
- sentinel_coupling_episodes.csv: every E3/E5 allocation-divergence episode
- sentinel_threshold_predicates.csv: decision-day predicate margins
- e5_exit_signal_events.csv: all E5 deterioration-review exit signals
- sentinel_coupling_summary.json
- SENTINEL_COUPLING_SHA256SUMS.txt
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

import pandas as pd

from backtester import experiment_architecture_recovery_concordance_e3 as e3
from backtester import experiment_wc_deterioration_second_review_e5 as e5
from backtester import calibrate_broad_simplified_breadth as strategy9

LABEL = "ZERO_BUDGET_E5_WEALTH_CORE_SENTINEL_COUPLING_DIAGNOSTIC"
BUDGET_CONSUMED = 5

FAST = {
    "dd": -0.10,
    "dam": 0.875,
    "green": 0.20,
    "r5": -0.05,
    "r10": -0.08,
    "ddam5": 0.30,
    "volacc": 0.04,
    "spy20": -0.01,
    "r10confirm": -0.10,
}
SLOW = {"dur": 30, "ret": -0.02, "r40": -0.03, "dam": 0.75, "green": 0.25}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def inject_daily_telemetry(text: str) -> str:
    old = (
        "'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,"
        "'fast_signal':fastsig,'slow_signal':slowsig,"
        "'eligible_count':int(len(et)),'leadership_population':int(nk),"
        "'held_count':int(len(held))})"
    )
    new = (
        "'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,"
        "'fast_signal':fastsig,'slow_signal':slowsig,"
        "'eligible_count':int(len(et)),'leadership_population':int(nk),"
        "'held_count':int(len(held)),"
        "'diag_wc_r5':r5,'diag_wc_r10':r10,'diag_damaged_delta5':ddam5,"
        "'diag_spy_volacc':volacc,'diag_stops20':stops20,"
        "'diag_native_ordinary':bool(native.ordinary),"
        "'diag_native_base_fast':bool(native.base_fast),"
        "'diag_native_fast':bool(native.fast),"
        "'diag_native_slow':bool(native.slow),"
        "'diag_native_ramp':bool(native.ramp),"
        "'diag_native_base_dur':int(native.base_dur),"
        "'diag_native_base_since':((eq/native.base_anchor-1) if native.base_anchor and finite(native.base_anchor) else None)"
        "})"
    )
    return replace_once(text, old, new, "daily telemetry")


def inject_e5_exit_log(text: str) -> str:
    text = replace_once(
        text,
        "e5_second_review_exit_signals=0; e5_second_review_exits=0",
        "e5_second_review_exit_signals=0; e5_second_review_exits=0; e5_diagnostic_exit_signals=[]",
        "E5 diagnostic event state",
    )
    text = replace_once(
        text,
        "e5_second_review_exit_signals+=1\n                        s.pending_sell=True; s.sell_reason='deterioration_review'",
        (
            "e5_second_review_exit_signals+=1\n"
            "                        e5_diagnostic_exit_signals.append({"
            "'signal_date':str(date.date()),'ticker':str(tick[s.tid]),'tid':int(s.tid),"
            "'entry_day':int(s.entry_day),'age':int(age),'price':float(px),"
            "'entry_signal_price':float(s.entry_sig) if finite(s.entry_sig) else None,"
            "'peak':float(s.peak) if finite(s.peak) else None,"
            "'recent21':float(recent[s.tid]) if finite(recent[s.tid]) else None})\n"
            "                        s.pending_sell=True; s.sell_reason='deterioration_review'"
        ),
        "E5 diagnostic exit signal log",
    )
    text = replace_once(
        text,
        "'e5_second_review_exits':e5_second_review_exits,",
        "'e5_second_review_exits':e5_second_review_exits,'e5_diagnostic_exit_signals':e5_diagnostic_exit_signals,",
        "E5 diagnostic event summary",
    )
    return text


def control_source(output: Path) -> str:
    return inject_daily_telemetry(e3.transformed_source(output))


def candidate_source(output: Path) -> str:
    text = e5.candidate_source(output)
    text = inject_daily_telemetry(text)
    text = inject_e5_exit_log(text)
    return text


def run_generated(source: str, path: Path) -> None:
    path.write_text(source, encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(path)], check=True, env=env)


def finite(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def bool_pass(value) -> bool:
    return bool(value) if pd.notna(value) else False


def fast_predicates(row: pd.Series) -> dict:
    dd = row.wc_dd
    dam = row.damaged
    green = row.green
    r5 = row.diag_wc_r5
    r10 = row.diag_wc_r10
    ddam5 = row.diag_damaged_delta5
    volacc = row.diag_spy_volacc
    spy20 = row.spy_r20
    out = {
        "dd": finite(dd) and float(dd) <= FAST["dd"],
        "dam": finite(dam) and float(dam) >= FAST["dam"],
        "green": finite(green) and float(green) <= FAST["green"],
        "short": (finite(r5) and float(r5) <= FAST["r5"]) or (finite(r10) and float(r10) <= FAST["r10"]),
        "ddam5": finite(ddam5) and float(ddam5) >= FAST["ddam5"],
        "volacc": finite(volacc) and float(volacc) >= FAST["volacc"],
        "confirm": (finite(spy20) and float(spy20) <= FAST["spy20"]) or
                   (finite(r10) and float(r10) <= FAST["r10confirm"]),
    }
    out["all"] = all(out.values())
    return out


def slow_predicates(row: pd.Series) -> dict:
    base_active = bool_pass(row.diag_native_ordinary) or bool_pass(row.diag_native_base_fast)
    since = row.diag_native_base_since
    r40 = row.recent_r40
    dam = row.damaged
    green = row.green
    dur = row.diag_native_base_dur
    out = {
        "base_active": base_active,
        "duration": finite(dur) and int(dur) >= SLOW["dur"],
        "base_return": finite(since) and float(since) <= SLOW["ret"],
        "r40": finite(r40) and float(r40) <= SLOW["r40"],
        "dam": finite(dam) and float(dam) >= SLOW["dam"],
        "green": finite(green) and float(green) <= SLOW["green"],
    }
    out["all"] = all(out.values())
    return out


def threshold_delta(control_row: pd.Series, candidate_row: pd.Series, family: str) -> tuple[str, str]:
    if family == "FAST_SIGNAL_CLIFF":
        cp = fast_predicates(control_row)
        xp = fast_predicates(candidate_row)
    elif family == "SLOW_SIGNAL_CLIFF":
        cp = slow_predicates(control_row)
        xp = slow_predicates(candidate_row)
    else:
        return "", ""
    changed = [k for k in cp if k != "all" and cp[k] != xp[k]]
    cpass = [k for k in cp if k != "all" and cp[k]]
    xpass = [k for k in xp if k != "all" and xp[k]]
    return "|".join(changed), f"E3_PASS={','.join(cpass)};E5_PASS={','.join(xpass)}"


def classify(control_row: pd.Series, candidate_row: pd.Series) -> str:
    if bool(control_row.fast_signal) != bool(candidate_row.fast_signal):
        return "FAST_SIGNAL_CLIFF"
    if bool(control_row.slow_signal) != bool(candidate_row.slow_signal):
        return "SLOW_SIGNAL_CLIFF"
    cr = str(control_row.A_reason)
    xr = str(candidate_row.A_reason)
    if "FULL_RISK_CERTIFIED" in cr or "FULL_RISK_CERTIFIED" in xr:
        return "RECOVERY_RELEASE_TIMING"
    if float(control_row.native_close_target) != float(candidate_row.native_close_target):
        return "NATIVE_STATE_OR_RAMP_TIMING"
    if float(control_row.effective_native) != float(candidate_row.effective_native):
        return "EFFECTIVE_NATIVE_RAMP_TIMING"
    return "CARRIED_SENTINEL_STATE_TIMING"


def ret(frame: pd.DataFrame, column: str, start_i: int, end_i: int) -> float:
    a = float(frame.iloc[start_i][column])
    b = float(frame.iloc[end_i][column])
    return b / a - 1.0 if math.isfinite(a) and math.isfinite(b) and a > 0 else float("nan")


def divergence_episodes(control: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    diff = (control.A_allocation.astype(float) - candidate.A_allocation.astype(float)).abs() > 1e-12
    indices = list(control.index[diff])
    blocks = []
    if indices:
        start = prev = indices[0]
        for i in indices[1:]:
            if i != prev + 1:
                blocks.append((start, prev))
                start = i
            prev = i
        blocks.append((start, prev))
    rows = []
    for number, (start, end) in enumerate(blocks, 1):
        decision = max(start - 1, 0)
        c = control.iloc[decision]
        x = candidate.iloc[decision]
        family = classify(c, x)
        changed_predicates, predicate_state = threshold_delta(c, x, family)
        e3_ctl_ret = ret(control, "A_nav", decision, end)
        e5_ctl_ret = ret(candidate, "A_nav", decision, end)
        e3_core_ret = ret(control, "research_wealth_core_equity", decision, end)
        e5_core_ret = ret(candidate, "research_wealth_core_equity", decision, end)
        rows.append({
            "episode": number,
            "decision_date": str(pd.Timestamp(c.date).date()),
            "start": str(pd.Timestamp(control.iloc[start].date).date()),
            "end": str(pd.Timestamp(control.iloc[end].date).date()),
            "sessions": int(end - start + 1),
            "cause_family": family,
            "changed_threshold_predicates": changed_predicates,
            "predicate_state": predicate_state,
            "e3_fast_signal": bool(c.fast_signal),
            "e5_fast_signal": bool(x.fast_signal),
            "e3_slow_signal": bool(c.slow_signal),
            "e5_slow_signal": bool(x.slow_signal),
            "e3_reason": str(c.A_reason),
            "e5_reason": str(x.A_reason),
            "e3_wc_dd": float(c.wc_dd),
            "e5_wc_dd": float(x.wc_dd),
            "wc_dd_delta_e5_minus_e3": float(x.wc_dd - c.wc_dd),
            "e3_damaged": float(c.damaged),
            "e5_damaged": float(x.damaged),
            "damaged_delta_e5_minus_e3": float(x.damaged - c.damaged),
            "e3_green": float(c.green),
            "e5_green": float(x.green),
            "e3_r5": float(c.diag_wc_r5) if finite(c.diag_wc_r5) else None,
            "e5_r5": float(x.diag_wc_r5) if finite(x.diag_wc_r5) else None,
            "e3_r10": float(c.diag_wc_r10) if finite(c.diag_wc_r10) else None,
            "e5_r10": float(x.diag_wc_r10) if finite(x.diag_wc_r10) else None,
            "e3_damaged_delta5": float(c.diag_damaged_delta5) if finite(c.diag_damaged_delta5) else None,
            "e5_damaged_delta5": float(x.diag_damaged_delta5) if finite(x.diag_damaged_delta5) else None,
            "spy_volacc": float(c.diag_spy_volacc) if finite(c.diag_spy_volacc) else None,
            "spy_r20": float(c.spy_r20) if finite(c.spy_r20) else None,
            "e3_native_close_target": float(c.native_close_target),
            "e5_native_close_target": float(x.native_close_target),
            "e3_effective_native": float(c.effective_native),
            "e5_effective_native": float(x.effective_native),
            "e3_start_allocation": float(control.iloc[start].A_allocation),
            "e5_start_allocation": float(candidate.iloc[start].A_allocation),
            "e3_controlled_return": e3_ctl_ret,
            "e5_controlled_return": e5_ctl_ret,
            "e5_minus_e3_controlled_return": e5_ctl_ret - e3_ctl_ret,
            "e3_core_return": e3_core_ret,
            "e5_core_return": e5_core_ret,
            "e5_minus_e3_core_return": e5_core_ret - e3_core_ret,
        })
    return pd.DataFrame(rows)


def predicate_rows(episodes: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "episode", "decision_date", "cause_family", "changed_threshold_predicates",
        "predicate_state", "e3_wc_dd", "e5_wc_dd", "e3_damaged", "e5_damaged",
        "e3_green", "e5_green", "e3_r5", "e5_r5", "e3_r10", "e5_r10",
        "e3_damaged_delta5", "e5_damaged_delta5", "spy_volacc", "spy_r20",
    ]
    return episodes[cols].copy()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def finalize(root: Path, control_out: Path, candidate_out: Path) -> None:
    control = pd.read_csv(control_out / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    candidate = pd.read_csv(candidate_out / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    if len(control) != 7188 or len(candidate) != 7188 or not control.date.equals(candidate.date):
        raise RuntimeError("daily replay shape/calendar mismatch")
    csum = json.loads((control_out / "summary.json").read_text())
    xsum = json.loads((candidate_out / "summary.json").read_text())
    if csum.get("control_parity", {}).get("status") != "PASS":
        raise RuntimeError("fresh E3 control parity failed")
    if int(xsum.get("e5_second_review_exits", -1)) != 14:
        raise RuntimeError(f"E5 replay parity exit count changed: {xsum.get('e5_second_review_exits')}")
    episodes = divergence_episodes(control, candidate)
    episodes.to_csv(root / "sentinel_coupling_episodes.csv", index=False)
    predicate_rows(episodes).to_csv(root / "sentinel_threshold_predicates.csv", index=False)
    exit_events = pd.DataFrame(xsum.get("e5_diagnostic_exit_signals", []))
    exit_events.to_csv(root / "e5_exit_signal_events.csv", index=False)
    if len(episodes) != 13:
        raise RuntimeError(f"expected 13 allocation-divergence episodes, got {len(episodes)}")
    if len(exit_events) != 14:
        raise RuntimeError(f"expected 14 E5 exit signals, got {len(exit_events)}")
    fast = episodes[episodes.cause_family == "FAST_SIGNAL_CLIFF"]
    slow = episodes[episodes.cause_family == "SLOW_SIGNAL_CLIFF"]
    harmful = episodes.sort_values("e5_minus_e3_controlled_return").head(5)
    summary = {
        "status": "PASS",
        "evidence_label": LABEL,
        "economic_experiment_budget_delta": 0,
        "experiment_budget_consumed": BUDGET_CONSUMED,
        "fresh_control_e3_parity": "PASS",
        "fresh_e5_replay_parity": "PASS",
        "allocation_divergence_episodes": int(len(episodes)),
        "allocation_divergence_sessions": int(episodes.sessions.sum()),
        "fast_signal_cliffs": int(len(fast)),
        "slow_signal_cliffs": int(len(slow)),
        "recovery_release_timing_episodes": int((episodes.cause_family == "RECOVERY_RELEASE_TIMING").sum()),
        "other_carried_state_or_ramp_episodes": int((~episodes.cause_family.isin(
            ["FAST_SIGNAL_CLIFF", "SLOW_SIGNAL_CLIFF", "RECOVERY_RELEASE_TIMING"]
        )).sum()),
        "e5_deterioration_exit_signals": int(len(exit_events)),
        "largest_harmful_episodes": harmful[
            ["episode", "decision_date", "start", "end", "sessions", "cause_family",
             "changed_threshold_predicates", "e5_minus_e3_controlled_return",
             "e5_minus_e3_core_return"]
        ].to_dict("records"),
        "mechanical_conclusion": (
            "E5 changes Wealth Core composition; small differences in Wealth Core drawdown/breadth "
            "cross discrete FAST/SLOW or recovery-state boundaries, creating long exposure divergences "
            "whose controlled-return impact can greatly exceed the direct Wealth Core return difference."
        ),
        "causal_contract": {
            "observational_only": True,
            "same_E3_decisions_as_completed_E5_run": True,
            "same_E5_decisions_as_completed_E5_run": True,
            "telemetry_only_source_changes": True,
            "new_economic_thresholds": 0,
            "new_candidate_rules": 0,
        },
        "github_sha": os.environ.get("GITHUB_SHA"),
    }
    (root / "sentinel_coupling_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = [
        root / "sentinel_coupling_episodes.csv",
        root / "sentinel_threshold_predicates.csv",
        root / "e5_exit_signal_events.csv",
        root / "sentinel_coupling_summary.json",
        control_out / "daily.csv.gz",
        candidate_out / "daily.csv.gz",
    ]
    with (root / "SENTINEL_COUPLING_SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
        for path in outputs:
            fh.write(f"{sha256(path)}  {path.relative_to(root)}\n")
    print("[SENTINEL COUPLING EPISODES]", flush=True)
    print(episodes.to_string(index=False), flush=True)
    print("[E5 EXIT SIGNALS]", flush=True)
    print(exit_events.to_string(index=False), flush=True)
    print("[SUMMARY]", flush=True)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    root = args.output
    control_out = root / "control_e3_telemetry"
    candidate_out = root / "candidate_e5_telemetry"
    control_out.mkdir(parents=True, exist_ok=True)
    candidate_out.mkdir(parents=True, exist_ok=True)
    print("[ZERO-BUDGET] fresh E3 replay with telemetry only", flush=True)
    run_generated(control_source(control_out), Path("/tmp/e3_coupling_diag.py"))
    e3.finalize(control_out)
    print("[ZERO-BUDGET] fresh E5 replay with telemetry only; no new economic candidate", flush=True)
    run_generated(candidate_source(candidate_out), Path("/tmp/e5_coupling_diag.py"))
    strategy9.finalize(candidate_out)
    finalize(root, control_out, candidate_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
