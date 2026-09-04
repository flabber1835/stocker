#!/usr/bin/env python3
"""Experiment 5: one additional deterioration-triggered Wealth Core review.

Fresh chronological A/B construction using identical pinned inputs:
  CONTROL_E3                      exact surviving Experiment 3 architecture
  E5_DETERIORATION_SECOND_REVIEW  E3 plus one additional Wealth Core review

The only candidate decision change is:
  after a holding has consumed its existing age-119 review, the first later
  session on which it is outside the existing top-decile momentum pool AND its
  existing recent-21 return is negative triggers one additional application of
  the existing review test. If the holding is underwater versus the existing
  entry-review basis and does not qualify, it queues the existing next-open
  review exit. Otherwise the second review is consumed and never repeats for
  that entry episode.

Existing stop priority, age-119 review, cooldown, sizing, admissions, ranking,
E3 Sentinel, LD-RC, and execution timing remain unchanged. No new fitted numeric
threshold is introduced.

Research evidence only. No production activation and no formal PIT certificate.
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
from backtester import calibrate_broad_simplified_breadth as strategy9
from backtester import run_research_ldrc_corrected_warmup_cash as corrected

LABEL = "WEALTH_CORE_E5_DETERIORATION_TRIGGERED_SECOND_REVIEW_WITH_E3"
CONTROL = "CONTROL_E3"
CANDIDATE = "E5_DETERIORATION_SECOND_REVIEW_E3"
BUDGET_NUMBER = 5
BUDGET_LIMIT = 10

EXPECTED_E3_MAX = {
    "cagr": 0.19954801557875324,
    "max_drawdown": -0.3345904831084261,
    "sharpe": 1.0736657409261394,
    "ending_multiple": 181.12202909286611,
}
EXPECTED_E3_20 = {
    "cagr": 0.203277,
    "max_drawdown": -0.286186,
    "sharpe": 1.101492,
    "ending_multiple": 40.486504,
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def candidate_source(output: Path) -> str:
    """Return exact E3 source plus the single declared second-review rule."""
    text = e3.transformed_source(output)

    init_old = "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    init_new = (
        "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; "
        "e5_second_reviewed=set(); e5_second_reviews=0; e5_second_review_passes=0; "
        "e5_second_review_exit_signals=0; e5_second_review_exits=0"
    )
    text = replace_once(text, init_old, init_new, "E5 state and counters")

    # Existing stop remains first priority. The added branch is eligible only
    # after the original age-119 review has already been consumed. The review
    # predicate itself is copied from the existing rule and evaluated once.
    exit_old = """                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    s.pending_sell=True; s.sell_reason='stop'
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True"""
    exit_new = """                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    s.pending_sell=True; s.sell_reason='stop'
                elif (s.reviewed and finite(px) and (not bool(inpool[s.tid]))
                      and finite(recent[s.tid]) and float(recent[s.tid])<0.0
                      and f'{s.tid}:{s.entry_day}' not in e5_second_reviewed):
                    e5_key=f'{s.tid}:{s.entry_day}'
                    e5_second_reviewed.add(e5_key); e5_second_reviews+=1
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies:
                        e5_second_review_exit_signals+=1
                        s.pending_sell=True; s.sell_reason='deterioration_review'
                    else:
                        e5_second_review_passes+=1
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True"""
    text = replace_once(text, exit_old, exit_new, "E5 deterioration second review")

    open_old = """                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)"""
    open_new = """                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='deterioration_review': e5_second_review_exits+=1
                    if s.sell_reason=='stop': stop_days.append(gday)"""
    text = replace_once(text, open_old, open_new, "E5 execution counter")

    summary_old = "'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,"
    summary_new = (
        "'buys':buys,'sells':sells,'e5_second_reviews':e5_second_reviews,"
        "'e5_second_review_passes':e5_second_review_passes,"
        "'e5_second_review_exit_signals':e5_second_review_exit_signals,"
        "'e5_second_review_exits':e5_second_review_exits,"
        "'split_events_applied':split_events,'dividend_events_held':div_events,"
    )
    text = replace_once(text, summary_old, summary_new, "E5 summary counters")
    return text


def run_generated(source: str, path: Path) -> None:
    path.write_text(source, encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(path)], check=True, env=env)


def metric_rows(frame: pd.DataFrame, variant: str, nav_col: str, core_col: str) -> list[dict]:
    starts = {
        "5": ("2021-07-30", 5.0),
        "10": ("2016-07-29", 10.0),
        "15": ("2011-07-29", 15.0),
        "20": ("2006-07-31", 20.0),
        "max": ("1998-01-02", None),
    }
    rows = []
    for window, (start, years) in starts.items():
        rows.append({
            "window_years": window,
            "variant": variant,
            "surface": "E3_CONTROLLED",
            **corrected.old.metric_block(frame, nav_col, start, years),
        })
        rows.append({
            "window_years": window,
            "variant": variant,
            "surface": "WEALTH_CORE",
            **corrected.old.metric_block(frame, core_col, start, years),
        })
    return rows


def period_return(frame: pd.DataFrame, column: str, start: str, end: str) -> float:
    q = frame[(frame.date >= pd.Timestamp(start)) & (frame.date <= pd.Timestamp(end))]
    if len(q) < 2:
        return float("nan")
    a = float(q.iloc[0][column])
    b = float(q.iloc[-1][column])
    return b / a - 1.0 if math.isfinite(a) and math.isfinite(b) and a > 0 else float("nan")


def yearly_rows(control: pd.DataFrame, candidate: pd.DataFrame) -> list[dict]:
    rows = []
    for year in sorted(set(control.date.dt.year).intersection(candidate.date.dt.year)):
        c = control[control.date.dt.year == year]
        x = candidate[candidate.date.dt.year == year]
        if len(c) < 2 or len(x) < 2:
            continue
        cr = float(c.iloc[-1].A_nav) / float(c.iloc[0].A_nav) - 1.0
        xr = float(x.iloc[-1].A_nav) / float(x.iloc[0].A_nav) - 1.0
        cc = float(c.iloc[-1].research_wealth_core_equity) / float(c.iloc[0].research_wealth_core_equity) - 1.0
        xc = float(x.iloc[-1].research_wealth_core_equity) / float(x.iloc[0].research_wealth_core_equity) - 1.0
        rows.append({
            "year": int(year),
            "control_e3_return": cr,
            "candidate_e5_return": xr,
            "candidate_minus_control": xr - cr,
            "control_core_return": cc,
            "candidate_core_return": xc,
            "candidate_core_minus_control_core": xc - cc,
        })
    return rows


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def finalize(root: Path, control_out: Path, candidate_out: Path) -> None:
    control = pd.read_csv(control_out / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    candidate = pd.read_csv(candidate_out / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    if len(control) != 7188 or len(candidate) != 7188:
        raise RuntimeError(f"unexpected daily rows control={len(control)} candidate={len(candidate)}")
    if not control.date.equals(candidate.date):
        raise RuntimeError("control/candidate session calendars differ")

    control_summary = json.loads((control_out / "summary.json").read_text(encoding="utf-8"))
    candidate_summary = json.loads((candidate_out / "summary.json").read_text(encoding="utf-8"))
    if control_summary.get("control_parity", {}).get("status") != "PASS":
        raise RuntimeError(f"fresh E3 control parity failed: {control_summary.get('control_parity')}")

    rows = []
    rows.extend(metric_rows(control, CONTROL, "A_nav", "research_wealth_core_equity"))
    rows.extend(metric_rows(candidate, CANDIDATE, "A_nav", "research_wealth_core_equity"))
    metrics = pd.DataFrame(rows)
    metrics.to_csv(root / "e5_comparison_metrics.csv", index=False)

    periods = [
        ("calendar_2018", "2018-01-02", "2018-12-31"),
        ("early_deterioration", "2018-06-12", "2018-09-20"),
        ("q4_selloff_to_slow", "2018-09-20", "2018-12-19"),
        ("recovery_to_e3_release", "2018-12-20", "2019-02-04"),
        ("e3_release_to_control_release", "2019-02-05", "2019-02-22"),
    ]
    prow = []
    for name, start, end in periods:
        prow.append({
            "period": name,
            "start": start,
            "end": end,
            "control_e3_return": period_return(control, "A_nav", start, end),
            "candidate_e5_return": period_return(candidate, "A_nav", start, end),
            "control_core_return": period_return(control, "research_wealth_core_equity", start, end),
            "candidate_core_return": period_return(candidate, "research_wealth_core_equity", start, end),
            "spy_return": period_return(control, "spy_nav", start, end),
        })
    periods_df = pd.DataFrame(prow)
    periods_df["candidate_minus_control"] = periods_df.candidate_e5_return - periods_df.control_e3_return
    periods_df["candidate_core_minus_control_core"] = periods_df.candidate_core_return - periods_df.control_core_return
    periods_df.to_csv(root / "e5_2018_2019_periods.csv", index=False)

    years = pd.DataFrame(yearly_rows(control, candidate))
    years.to_csv(root / "e5_yearly_attribution.csv", index=False)

    def pick(frame: pd.DataFrame, variant: str, surface: str, window: str) -> dict:
        r = frame[
            (frame.variant == variant)
            & (frame.surface == surface)
            & (frame.window_years.astype(str) == window)
        ].iloc[0]
        return {
            "cagr": float(r.cagr),
            "max_drawdown": float(r.max_drawdown),
            "sharpe": float(r.sharpe),
            "ending_multiple": float(r.ending_multiple),
        }

    control_max = pick(metrics, CONTROL, "E3_CONTROLLED", "max")
    control_20 = pick(metrics, CONTROL, "E3_CONTROLLED", "20")
    candidate_max = pick(metrics, CANDIDATE, "E3_CONTROLLED", "max")
    candidate_20 = pick(metrics, CANDIDATE, "E3_CONTROLLED", "20")
    candidate_core_max = pick(metrics, CANDIDATE, "WEALTH_CORE", "max")
    candidate_core_20 = pick(metrics, CANDIDATE, "WEALTH_CORE", "20")

    for key, expected in EXPECTED_E3_MAX.items():
        if abs(control_max[key] - expected) > 5e-6:
            raise RuntimeError(f"E3 max parity {key}: {control_max[key]} != {expected}")
    for key, expected in EXPECTED_E3_20.items():
        if abs(control_20[key] - expected) > 5e-6:
            raise RuntimeError(f"E3 20y parity {key}: {control_20[key]} != {expected}")

    changed_years = years[years.candidate_minus_control.abs() > 1e-12]
    summary = {
        "status": "PASS",
        "evidence_label": LABEL,
        "experiment_budget_number": BUDGET_NUMBER,
        "experiment_budget_consumed_after_completion": BUDGET_NUMBER,
        "experiment_budget_limit": BUDGET_LIMIT,
        "fresh_control_e3_parity": "PASS",
        "diagnostic_hypothesis": "one-shot lifetime review becomes stale after later deterioration",
        "candidate_rule": (
            "after original age-119 review is consumed, first later deterioration "
            "(outside existing top-10% momentum pool AND recent-21 return < 0) "
            "applies the existing review predicate once; underwater non-qualifiers "
            "queue the existing next-open review exit"
        ),
        "new_fitted_numeric_thresholds": 0,
        "one_additional_review_per_entry": True,
        "candidate_second_reviews": int(candidate_summary.get("e5_second_reviews", 0)),
        "candidate_second_review_passes": int(candidate_summary.get("e5_second_review_passes", 0)),
        "candidate_second_review_exit_signals": int(candidate_summary.get("e5_second_review_exit_signals", 0)),
        "candidate_second_review_exits": int(candidate_summary.get("e5_second_review_exits", 0)),
        "control_buys": int(control_summary.get("buys", 0)),
        "control_sells": int(control_summary.get("sells", 0)),
        "candidate_buys": int(candidate_summary.get("buys", 0)),
        "candidate_sells": int(candidate_summary.get("sells", 0)),
        "control_e3_max": control_max,
        "candidate_e5_max": candidate_max,
        "control_e3_20y": control_20,
        "candidate_e5_20y": candidate_20,
        "candidate_core_max": candidate_core_max,
        "candidate_core_20y": candidate_core_20,
        "changed_calendar_years": int(len(changed_years)),
        "candidate_better_calendar_years": int((changed_years.candidate_minus_control > 0).sum()),
        "candidate_worse_calendar_years": int((changed_years.candidate_minus_control < 0).sum()),
        "github_sha": os.environ.get("GITHUB_SHA"),
    }
    (root / "e5_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest = {
        "schema": "backtester.wealth-core-e5-deterioration-second-review/1",
        "status": "PASS",
        "evidence_label": LABEL,
        "experiment": BUDGET_NUMBER,
        "control": "exact E3 surviving architecture rerun fresh",
        "candidate": CANDIDATE,
        "causal_contract": {
            "fresh_chronological_control_replay": True,
            "fresh_chronological_candidate_replay": True,
            "same_pinned_market_inputs": True,
            "same_frozen_numerical_runtime": True,
            "pre_recorded_decisions_used_as_input": False,
            "candidate_change": "one additional post-review deterioration-triggered application of the existing Wealth Core review predicate per entry episode",
            "decision_at_close_next_open_effect": True,
            "existing_stop_priority_preserved": True,
            "existing_cooldown_preserved": True,
            "existing_age119_review_preserved": True,
            "existing_review_predicate_preserved": True,
            "E3_sentinel_preserved": True,
        },
        "input_authority": {
            "sfp_sha256": "8d2ebf7485977d9c40ec379eb33bd9d36d39d69db13602e5c51862d03172400c",
        },
        "github_sha": os.environ.get("GITHUB_SHA"),
        "daily_rows_each": int(len(control)),
    }
    (root / "e5_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    files = [
        control_out / "daily.csv.gz",
        control_out / "e3_metrics.csv",
        control_out / "summary.json",
        control_out / "e3_manifest.json",
        candidate_out / "daily.csv.gz",
        candidate_out / "metrics.csv",
        candidate_out / "summary.json",
        root / "e5_comparison_metrics.csv",
        root / "e5_2018_2019_periods.csv",
        root / "e5_yearly_attribution.csv",
        root / "e5_summary.json",
        root / "e5_manifest.json",
    ]
    with (root / "E5_SHA256SUMS.txt").open("w", encoding="utf-8") as f:
        for path in files:
            f.write(f"{sha256(path)}  {path.relative_to(root)}\n")

    print("[E5 METRICS]", flush=True)
    print(metrics.to_string(index=False), flush=True)
    print("[E5 2018-2019 PERIODS]", flush=True)
    print(periods_df.to_string(index=False), flush=True)
    print("[E5 SUMMARY]", flush=True)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output
    control_out = root / "control_e3"
    candidate_out = root / "candidate_e5"
    control_out.mkdir(parents=True, exist_ok=True)
    candidate_out.mkdir(parents=True, exist_ok=True)

    print("[RUN CONTROL] exact E3; control does not consume budget", flush=True)
    run_generated(e3.transformed_source(control_out), Path("/tmp/e5_control_e3.py"))
    e3.finalize(control_out)

    print(f"[RUN CANDIDATE] {LABEL} experiment={BUDGET_NUMBER}/{BUDGET_LIMIT}", flush=True)
    run_generated(candidate_source(candidate_out), Path("/tmp/e5_deterioration_second_review_candidate.py"))
    strategy9.finalize(candidate_out)

    finalize(root, control_out, candidate_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
