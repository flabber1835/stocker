#!/usr/bin/env python3
"""Experiment 3: cross-surface recovery concordance for Strategy 9.

Fresh chronological replay. The Strategy 9 control is untouched. Candidate A
changes only the post-severe LD-RC release route:

    7 positive recent-leadership r20 sessions
    AND owned Wealth Core r20 > 0
    AND recent-leadership r20 >= Wealth Core r20
    AND SPY r20 >= Wealth Core r20

The existing r20+r40 seven-session recovery and SPY V-rebound remain fallback
release routes. Divergence entry/latch semantics are unchanged.

Research evidence only; no production activation and no formal PIT certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd

from backtester import calibrate_broad_simplified_breadth as strategy9
from backtester import run_research_ldrc_corrected_warmup_cash as corrected

LABEL = "STRATEGY9_E3_CROSS_SURFACE_RECOVERY_CONCORDANCE"
VARIANT = "E3_RECOVERY_CONCORDANCE"
BUDGET_NUMBER = 3
EXPECTED_CONTROL_HASH_12SIG = "3a8a03799ddd06f14e1d8625e2f6540192e7255a11cb33e9462b2c9ffd625053"

CONTROL_HASH_COLUMNS = (
    "date",
    "research_nav",
    "research_allocation",
    "research_wealth_core_equity",
    "research_wealth_core_open_equity",
    "spy_nav",
    "native_close_target",
    "effective_native",
)


def _replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, got {count}")
    return out


def transformed_source(output: Path) -> str:
    text = strategy9.transformed_source(output)

    candidate = r'''class CandidateA:
    """Current LD-RC plus one early cross-surface recovery route."""
    def __init__(self):
        self.episode=False; self.latched=False
        self.full_streak=0; self.recent_positive_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.concordance_releases=0

    def step(self,native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20):
        full_healthy=(finite(recent_r20) and finite(recent_r40)
                      and recent_r20>0 and recent_r40>0)
        self.full_streak=self.full_streak+1 if full_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]

        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True
            self.recent_positive_streak=0
            reasons.append('RECOVERY_EPISODE_START')

        if self.episode:
            if native>0 and finite(recent_r20) and recent_r20>0:
                self.recent_positive_streak+=1
            else:
                self.recent_positive_streak=0
        else:
            self.recent_positive_streak=0

        cleared=self.latched and (self.full_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')

        desired=native
        if self.episode and native>=1-1e-12:
            concordant=(
                self.recent_positive_streak>=LDRC_REC
                and finite(wc_r20) and wc_r20>0
                and finite(recent_r20) and recent_r20>=wc_r20
                and finite(spy20) and spy20>=wc_r20
            )
            if self.full_streak>=LDRC_REC or vre or concordant:
                self.episode=False; desired=1.
                if concordant and self.full_streak<LDRC_REC and not vre:
                    self.concordance_releases+=1
                    reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
                elif self.full_streak>=LDRC_REC:
                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
                else:
                    reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')
                self.recent_positive_streak=0
            else:
                desired=self.prev_desired
                reasons.append('FULL_RISK_HELD')

        avail=(finite(wcdd) and finite(recent_r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        if not self.latched and not cleared:
            divergence=(
                native>=1-1e-12
                and effective_native is not None and finite(effective_native)
                and effective_native>=1-1e-12
                and avail and wcdd<=LDRC_DD
                and recent_r20<=LDRC_R20 and spy20>=0.
            )
            if divergence:
                self.latched=True
                reasons.append('LD_ENTER_DIVERGENCE')

        if self.latched:
            desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'

'''
    text = _replace_regex(
        text,
        r"class CandidateA:.*?(?=class CandidateB:)",
        candidate,
        "E3 candidate class",
    )

    old_call = "a_d,a_reason=ca.step(native_target,recent_r20,spy20)"
    new_call = "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
    if text.count(old_call) != 1:
        raise RuntimeError(f"E3 candidate call seam count={text.count(old_call)}")
    text = text.replace(old_call, new_call, 1)

    old_summary = "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,"
    new_summary = "'candidate_A_episodes':ca.episodes,'candidate_A_concordance_releases':ca.concordance_releases,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,"
    if text.count(old_summary) != 1:
        raise RuntimeError(f"E3 summary seam count={text.count(old_summary)}")
    text = text.replace(old_summary, new_summary, 1)

    # The experiment must not add telemetry columns to Strategy 9's output row;
    # control-path parity is checked after the replay on the untouched columns.
    if "'wc_r20':" in text or "'wc_r40':" in text:
        raise RuntimeError("E3 transform unexpectedly inserted owned-return telemetry")
    return text


def control_hash_12sig(frame: pd.DataFrame) -> str:
    missing = [c for c in CONTROL_HASH_COLUMNS if c not in frame.columns]
    if missing:
        raise RuntimeError(f"control parity columns missing: {missing}")
    h = hashlib.sha256()
    for row in frame[list(CONTROL_HASH_COLUMNS)].itertuples(index=False, name=None):
        payload = []
        for i, value in enumerate(row):
            if i == 0:
                payload.append(pd.Timestamp(value).strftime("%Y-%m-%d"))
            elif pd.isna(value):
                payload.append(None)
            else:
                payload.append(format(float(value), ".12g"))
        h.update((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
    return h.hexdigest()


def _difference_episodes(daily: pd.DataFrame) -> pd.DataFrame:
    diff = (daily["A_allocation"].astype(float)
            - daily["research_allocation"].astype(float)).abs() > 1e-12
    group = (diff != diff.shift(fill_value=False)).cumsum()
    rows = []
    for _, block in daily[diff].groupby(group[diff]):
        i0 = int(block.index[0]); i1 = int(block.index[-1]); before = max(i0 - 1, 0)
        def ret(column: str) -> float:
            a = float(daily.loc[before, column]); b = float(daily.loc[i1, column])
            return b / a - 1.0 if math.isfinite(a) and math.isfinite(b) and a > 0 else float("nan")
        rows.append({
            "variant": VARIANT,
            "start": str(pd.Timestamp(block.iloc[0]["date"]).date()),
            "end": str(pd.Timestamp(block.iloc[-1]["date"]).date()),
            "sessions": int(len(block)),
            "control_min_allocation": float(block["research_allocation"].min()),
            "candidate_min_allocation": float(block["A_allocation"].min()),
            "control_max_allocation": float(block["research_allocation"].max()),
            "candidate_max_allocation": float(block["A_allocation"].max()),
            "core_return": ret("research_wealth_core_equity"),
            "spy_return": ret("spy_nav"),
            "control_return": ret("research_nav"),
            "candidate_return": ret("A_nav"),
            "candidate_minus_control": ret("A_nav") - ret("research_nav"),
        })
    return pd.DataFrame(rows)


def finalize(output: Path) -> None:
    strategy9.finalize(output)
    daily = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])

    observed_hash = control_hash_12sig(daily)
    control_parity = observed_hash == EXPECTED_CONTROL_HASH_12SIG

    starts = {
        "5": ("2021-07-30", 5.0),
        "10": ("2016-07-29", 10.0),
        "15": ("2011-07-29", 15.0),
        "20": ("2006-07-31", 20.0),
        "max": ("1998-01-02", None),
    }
    metric_rows = []
    for window, (start, years) in starts.items():
        for variant, column in (("CONTROL", "research_nav"), (VARIANT, "A_nav"), ("CORE", "research_wealth_core_equity"), ("SPY", "spy_nav")):
            metric_rows.append({
                "window_years": window,
                "variant": variant,
                **corrected.old.metric_block(daily, column, start, years),
            })
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output / "e3_metrics.csv", index=False)

    episodes = _difference_episodes(daily)
    episodes.to_csv(output / "e3_episode_attribution.csv", index=False)

    release_rows = daily[daily["A_reason"].astype(str).str.contains("FULL_RISK_CERTIFIED_CROSS_SURFACE", regex=False)].copy()
    release_rows[[
        "date", "wc_dd", "damaged", "green", "recent_r20", "recent_r40",
        "spy_r20", "native_close_target", "effective_native",
        "research_allocation", "A_allocation", "A_reason",
    ]].to_csv(output / "e3_release_sessions.csv", index=False)

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({
        "experiment": "strategy9_e3_cross_surface_recovery_concordance",
        "evidence_label": LABEL,
        "experiment_budget_number": BUDGET_NUMBER,
        "experiment_budget_consumed_after_completion": 3,
        "experiment_budget_limit": 10,
        "control_parity": {
            "status": "PASS" if control_parity else "FAIL",
            "method": "eight untouched economic/control columns, 12 significant digits per numeric value",
            "expected_sha256": EXPECTED_CONTROL_HASH_12SIG,
            "observed_sha256": observed_hash,
            "historical_control_run": 33876316789,
            "historical_control_artifact": 9939066139,
        },
        "candidate_E3": {
            "name": "cross_surface_recovery_concordance",
            "wealth_core_changed": False,
            "native_sentinel_changed": False,
            "divergence_entry_changed": False,
            "fallback_recovery_changed": False,
            "new_fitted_numeric_thresholds": 0,
            "rule": "7 positive recent-r20 sessions AND wc_r20>0 AND recent_r20>=wc_r20 AND spy_r20>=wc_r20",
            "cross_surface_release_count": int(len(release_rows)),
        },
    })
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest_path = output / "e3_manifest.json"
    manifest = {
        "schema": "backtester.strategy9-e3-recovery-concordance/1",
        "status": "PASS" if control_parity else "CONTROL_PARITY_FAIL",
        "evidence_label": LABEL,
        "candidate_experiment_number": BUDGET_NUMBER,
        "daily_rows": int(len(daily)),
        "difference_episode_rows": int(len(episodes)),
        "cross_surface_release_rows": int(len(release_rows)),
        "causal_contract": {
            "fresh_chronological_replay": True,
            "same_session_control_and_candidate": True,
            "candidate_feedback_into_wealth_core": False,
            "candidate_feedback_into_native_sentinel": False,
            "pre_recorded_decisions_used_as_input": False,
            "historical_control_hash_used_only_after_replay": True,
            "decision_at_close_next_open_effect": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [
        output / "daily.csv.gz",
        output / "e3_metrics.csv",
        output / "e3_episode_attribution.csv",
        output / "e3_release_sessions.csv",
        summary_path,
        manifest_path,
    ]
    (output / "E3_SHA256SUMS.txt").write_text(
        "".join(f"{corrected.old.sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    print(f"[CONTROL-PARITY] {'PASS' if control_parity else 'FAIL'} expected={EXPECTED_CONTROL_HASH_12SIG} observed={observed_hash}", flush=True)
    print(metrics.to_string(index=False), flush=True)
    print("[E3-RELEASES]", flush=True)
    print(release_rows[["date", "A_reason"]].to_string(index=False), flush=True)
    print("[E3-EPISODES]", flush=True)
    print(episodes.to_string(index=False) if not episodes.empty else "none", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/strategy9_e3_recovery_concordance.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} experiment={BUDGET_NUMBER}/10", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
