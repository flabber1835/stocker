#!/usr/bin/env python3
"""Fresh causal replay of two simple Strategy-9 architecture-defect candidates.

Control: Broad simplified fixed breadth calibration (Strategy 9).
E1: add an owned-Wealth-Core divergence entry mode to LD-RC.
E2: preserve the divergence latch but simplify post-severe recovery confirmation.

The replay itself is produced by Strategy 9's frozen chronological harness. This
wrapper changes only the two candidate LD-RC arms and post-run reporting. The
control arm, Wealth Core, native Sentinel, data authority, execution timing and
cash model are unchanged.
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

LABEL = "STRATEGY9_ARCHITECTURE_DEFECTS_E1_E2"
CONTROL_PROJECTION_SHA256 = "3348f9db63fa960edb7dca48aa130d0782fab83777fa3b30f07b666128b898e3"
BUDGET_CONSUMED = 2

CONTROL_COLUMNS = [
    "date",
    "research_wealth_core_equity",
    "research_wealth_core_open_equity",
    "wc_dd",
    "damaged",
    "green",
    "recent_r20",
    "recent_r40",
    "spy_r20",
    "native_close_target",
    "effective_native",
    "research_allocation",
    "research_nav",
    "spy_nav",
    "control_reason",
    "fast_signal",
    "slow_signal",
    "eligible_count",
    "leadership_population",
    "held_count",
]


def _replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, got {count}")
    return out


def transformed_source(output: Path) -> str:
    text = strategy9.transformed_source(output)

    candidates = r'''class CandidateA:
    """E1: current LD-RC plus a stateful-owned-book divergence entry mode."""
    def __init__(self):
        self.episode=False; self.latched=False; self.streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0; self.owned_entries=0; self.recent_entries=0
    def step(self,native,effective_native,wcdd,wc_r20,wc_r40,recent_r20,recent_r40,spy20):
        healthy=finite(recent_r20) and finite(recent_r40) and recent_r20>0 and recent_r40>0
        self.streak=self.streak+1 if healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('RECOVERY_EPISODE_START')
        cleared=self.latched and (self.streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False; reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.streak>=LDRC_REC or vre:
                self.episode=False; desired=1.; reasons.append('FULL_RISK_CERTIFIED')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        recent_avail=(finite(wcdd) and finite(recent_r20) and finite(spy20)
                      and effective_native is not None and finite(effective_native))
        owned_avail=(finite(wcdd) and finite(wc_r20) and finite(wc_r40) and finite(spy20)
                     and effective_native is not None and finite(effective_native))
        full=bool(native>=1-1e-12 and effective_native is not None and finite(effective_native)
                  and effective_native>=1-1e-12)
        recent_div=bool(full and recent_avail and wcdd<=LDRC_DD and recent_r20<=LDRC_R20 and spy20>=0.)
        owned_div=bool(full and owned_avail and wcdd<=LDRC_DD and wc_r20<0. and wc_r40<=LDRC_R20 and spy20>=0.)
        if not self.latched and not cleared:
            if recent_div:
                self.latched=True; self.recent_entries+=1; reasons.append('LD_ENTER_RECENT_DIVERGENCE')
            elif owned_div:
                self.latched=True; self.owned_entries+=1; reasons.append('LD_ENTER_OWNED_DIVERGENCE')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'

class CandidateB:
    """E2: preserve current latch; use r20 persistence for post-severe recovery."""
    def __init__(self):
        self.episode=False; self.latched=False; self.latch_streak=0; self.recovery_streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,effective_native,wcdd,wc_r20,wc_r40,recent_r20,recent_r40,spy20):
        latch_healthy=finite(recent_r20) and finite(recent_r40) and recent_r20>0 and recent_r40>0
        self.latch_streak=self.latch_streak+1 if latch_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; self.recovery_streak=0; reasons.append('RECOVERY_EPISODE_START')
        recovery_healthy=finite(recent_r20) and recent_r20>0
        self.recovery_streak=(self.recovery_streak+1 if native>0 and recovery_healthy else 0)
        cleared=self.latched and (self.latch_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False; reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.recovery_streak>=LDRC_REC or vre:
                self.episode=False; desired=1.; reasons.append('FULL_RISK_CERTIFIED_R20' if self.recovery_streak>=LDRC_REC else 'FULL_RISK_CERTIFIED_SPY')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        avail=(finite(wcdd) and finite(recent_r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        if not self.latched and not cleared:
            div=bool(native>=1-1e-12 and effective_native is not None and finite(effective_native)
                     and effective_native>=1-1e-12 and avail and wcdd<=LDRC_DD
                     and recent_r20<=LDRC_R20 and spy20>=0.)
            if div:
                self.latched=True; reasons.append('LD_ENTER_DIVERGENCE')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'


def bil_factors'''
    text = _replace_regex(
        text,
        r"class CandidateA:.*?\ndef bil_factors",
        candidates,
        "candidate architecture classes",
    )

    old_calls = """            a_d,a_reason=ca.step(native_target,recent_r20,spy20)\n            b_d,b_reason=cb.step(native_target,recent_r20,spy20)"""
    new_calls = """            a_d,a_reason=ca.step(native_target,effective_native,dd,r20,r40,recent_r20,recent_r40,spy20)\n            b_d,b_reason=cb.step(native_target,effective_native,dd,r20,r40,recent_r20,recent_r40,spy20)"""
    if text.count(old_calls) != 1:
        raise RuntimeError(f"candidate call seam count={text.count(old_calls)}")
    text = text.replace(old_calls, new_calls, 1)

    old_row = "'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'damaged':dam_b,'green':green_b,"
    new_row = "'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'wc_r20':r20,'wc_r40':r40,'damaged':dam_b,'green':green_b,"
    if text.count(old_row) != 1:
        raise RuntimeError(f"Wealth Core return telemetry seam count={text.count(old_row)}")
    text = text.replace(old_row, new_row, 1)

    old_summary = "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,"
    new_summary = "'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,'candidate_A_owned_entries':ca.owned_entries,'candidate_A_recent_entries':ca.recent_entries,'correlation_peer_stats':PEER_STATS,"
    if text.count(old_summary) != 1:
        raise RuntimeError(f"candidate summary seam count={text.count(old_summary)}")
    text = text.replace(old_summary, new_summary, 1)
    return text


def _canon(value):
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value).hex()
    return str(value)


def control_projection_hash(frame: pd.DataFrame) -> str:
    missing = [column for column in CONTROL_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"control projection missing columns: {missing}")
    h = hashlib.sha256()
    for row in frame[CONTROL_COLUMNS].itertuples(index=False, name=None):
        payload = [_canon(value) for value in row]
        h.update((json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    return h.hexdigest()


def _episode_rows(frame: pd.DataFrame, alloc_col: str, nav_col: str, label: str) -> list[dict]:
    diff = (frame[alloc_col].astype(float) - frame["research_allocation"].astype(float)).abs() > 1e-12
    rows: list[dict] = []
    start = None
    for i, active in enumerate(diff.tolist() + [False]):
        if active and start is None:
            start = i
        elif not active and start is not None:
            end = i - 1
            base = max(start - 1, 0)
            def ret(column: str) -> float:
                a = float(frame.iloc[base][column]); b = float(frame.iloc[end][column])
                return b / a - 1.0 if math.isfinite(a) and math.isfinite(b) and a > 0 else float("nan")
            rows.append({
                "candidate": label,
                "start": str(pd.Timestamp(frame.iloc[start]["date"]).date()),
                "end": str(pd.Timestamp(frame.iloc[end]["date"]).date()),
                "sessions": int(end - start + 1),
                "control_return": ret("research_nav"),
                "candidate_return": ret(nav_col),
                "candidate_minus_control": ret(nav_col) - ret("research_nav"),
                "core_return": ret("research_wealth_core_equity"),
                "spy_return": ret("spy_nav"),
                "control_min_allocation": float(frame.iloc[start:end+1]["research_allocation"].min()),
                "candidate_min_allocation": float(frame.iloc[start:end+1][alloc_col].min()),
            })
            start = None
    return rows


def _yearly_returns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "CONTROL": "research_nav",
        "E1_OWNED_DIVERGENCE": "A_nav",
        "E2_RECOVERY_SIMPLIFICATION": "B_nav",
        "CORE": "research_wealth_core_equity",
        "SPY": "spy_nav",
    }
    out = []
    x = frame.copy()
    x["year"] = pd.to_datetime(x["date"]).dt.year
    for year, group in x.groupby("year", sort=True):
        for variant, column in columns.items():
            vals = group[column].dropna().astype(float)
            if vals.empty:
                continue
            out.append({
                "year": int(year),
                "variant": variant,
                "return": float(vals.iloc[-1] / vals.iloc[0] - 1.0),
            })
    return pd.DataFrame(out)


def finalize(output: Path) -> None:
    strategy9.finalize(output)
    daily_path = output / "daily.csv.gz"
    daily = pd.read_csv(daily_path, compression="gzip", parse_dates=["date"])

    observed_hash = control_projection_hash(daily)
    if observed_hash != CONTROL_PROJECTION_SHA256:
        raise RuntimeError(
            "Strategy 9 control parity failed: "
            f"expected={CONTROL_PROJECTION_SHA256} observed={observed_hash}"
        )

    starts = {
        "5": ("2021-07-30", 5.0),
        "10": ("2016-07-29", 10.0),
        "15": ("2011-07-29", 15.0),
        "20": ("2006-07-31", 20.0),
        "max": ("1998-01-02", None),
    }
    variants = {
        "CONTROL": "research_nav",
        "E1_OWNED_DIVERGENCE": "A_nav",
        "E2_RECOVERY_SIMPLIFICATION": "B_nav",
        "CORE": "research_wealth_core_equity",
        "SPY": "spy_nav",
    }
    metric_rows = []
    for window, (start, years) in starts.items():
        for variant, column in variants.items():
            metric_rows.append({
                "window_years": window,
                "variant": variant,
                **corrected.old.metric_block(daily, column, start, years),
            })
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output / "architecture_metrics.csv", index=False)

    episodes = pd.DataFrame(
        _episode_rows(daily, "A_allocation", "A_nav", "E1_OWNED_DIVERGENCE")
        + _episode_rows(daily, "B_allocation", "B_nav", "E2_RECOVERY_SIMPLIFICATION")
    )
    episodes.to_csv(output / "architecture_episode_attribution.csv", index=False)
    yearly = _yearly_returns(daily)
    yearly.to_csv(output / "architecture_yearly_returns.csv", index=False)

    slice_2018 = daily[
        (daily["date"] >= pd.Timestamp("2018-06-12"))
        & (daily["date"] <= pd.Timestamp("2019-03-31"))
    ].copy()
    slice_2018.to_csv(output / "architecture_2018_2019_daily.csv.gz", index=False, compression="gzip")

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({
        "experiment": "strategy9_architecture_defects_e1_e2",
        "evidence_label": LABEL,
        "experiment_budget_consumed": BUDGET_CONSUMED,
        "experiment_budget_limit": 10,
        "control_parity": {
            "status": "PASS",
            "projection_sha256": observed_hash,
            "expected_strategy9_projection_sha256": CONTROL_PROJECTION_SHA256,
            "historical_control_run": 33876316789,
            "historical_control_artifact": 9939066139,
        },
        "candidate_E1": {
            "name": "owned_book_divergence_mode",
            "wealth_core_changed": False,
            "native_sentinel_changed": False,
            "ldrc_existing_divergence_preserved": True,
            "new_fitted_thresholds": 0,
            "entry": "existing divergence OR (wc_dd<=-10%, wc_r20<0, wc_r40<=-8%, SPY_r20>=0)",
            "ceiling": 0.55,
        },
        "candidate_E2": {
            "name": "single_horizon_recovery_confirmation_latch_preserved",
            "wealth_core_changed": False,
            "native_sentinel_changed": False,
            "ldrc_existing_divergence_preserved": True,
            "new_fitted_thresholds": 0,
            "recovery": "after native exposure becomes positive: seven consecutive recent-leadership r20>0 sessions; existing SPY V-rebound alternative retained",
            "divergence_latch_clear": "unchanged: seven sessions recent r20>0 AND recent r40>0, or SPY V-rebound",
        },
    })
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest_path = output / "architecture_manifest.json"
    manifest = {
        "schema": "backtester.strategy9-architecture-defects/1",
        "status": "PASS",
        "evidence_label": LABEL,
        "experiment_budget_consumed": BUDGET_CONSUMED,
        "control_projection_sha256": observed_hash,
        "metrics": metric_rows,
        "episode_count": int(len(episodes)),
        "daily_rows": int(len(daily)),
        "causal_contract": {
            "fresh_chronological_replay": True,
            "same_session_multi_arm": True,
            "candidate_feedback_into_wealth_core": False,
            "candidate_feedback_into_native_sentinel": False,
            "pre_recorded_decisions_used_as_input": False,
            "prior_control_hash_used_only_after_replay": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [
        daily_path,
        output / "architecture_metrics.csv",
        output / "architecture_episode_attribution.csv",
        output / "architecture_yearly_returns.csv",
        output / "architecture_2018_2019_daily.csv.gz",
        summary_path,
        manifest_path,
    ]
    (output / "ARCHITECTURE_SHA256SUMS.txt").write_text(
        "".join(f"{corrected.old.sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    print("[CONTROL-PARITY] PASS", observed_hash, flush=True)
    print(metrics.to_string(index=False), flush=True)
    if not episodes.empty:
        print("[EPISODE-ATTRIBUTION]", flush=True)
        print(episodes.to_string(index=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/strategy9_architecture_defects_e1_e2.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} budget={BUDGET_CONSUMED}/10", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
