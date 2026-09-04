#!/usr/bin/env python3
"""Architecture-defect A/B replay on the Strategy 9 broad simplified control.

Fresh chronological replay with one immutable Wealth Core/native path and three
LD-RC arms advanced on every session:
  CONTROL                    exact Strategy 9
  E1_OWNED_DIVERGENCE        add held-book/market divergence entry
  E2_RECOVERY_SIMPLIFICATION preserve divergence; simplify post-severe recovery

This is research evidence, not formal PIT certification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

from backtester import calibrate_broad_simplified_breadth as strategy9
from backtester import run_research_ldrc_corrected_warmup_cash as corrected

LABEL = "BROAD_SIMPLIFIED_ARCHITECTURE_DEFECTS_E1_E2"
E1 = "E1_OWNED_DIVERGENCE"
E2 = "E2_RECOVERY_SIMPLIFICATION"


CANDIDATE_CLASSES = r"""
class CandidateA:
    # E1: current LD-RC plus a second owned-book divergence entry mode.
    def __init__(self):
        self.episode=False; self.latched=False; self.streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,effective_native,wcdd,r20,r40,spy20,wc_r20,wc_r40):
        healthy=finite(r20) and finite(r40) and r20>0 and r40>0
        self.streak=self.streak+1 if healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('RECOVERY_EPISODE_START')
        cleared=self.latched and (self.streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.streak>=LDRC_REC or vre:
                self.episode=False; desired=1.; reasons.append('FULL_RISK_CERTIFIED')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        avail=(finite(wcdd) and finite(r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        owned_avail=(finite(wcdd) and finite(wc_r20) and finite(wc_r40)
                     and finite(spy20) and effective_native is not None
                     and finite(effective_native))
        if not self.latched and not cleared:
            full=(native>=1-1e-12 and effective_native is not None
                  and effective_native>=1-1e-12)
            recent_div=(full and avail and wcdd<=LDRC_DD
                        and r20<=LDRC_R20 and spy20>=0.)
            owned_div=(full and owned_avail and wcdd<=LDRC_DD
                       and wc_r20<0. and wc_r40<=LDRC_R20 and spy20>=0.)
            if recent_div or owned_div:
                self.latched=True
                if recent_div and owned_div: reasons.append('LD_ENTER_BOTH')
                elif owned_div: reasons.append('LD_ENTER_OWNED_BOOK')
                else: reasons.append('LD_ENTER_RECENT_LEADERSHIP')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'


class CandidateB:
    # E2: preserve current divergence; simplify only post-severe recovery.
    def __init__(self):
        self.episode=False; self.latched=False
        self.latch_streak=0; self.recovery_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,effective_native,wcdd,r20,r40,spy20):
        latch_healthy=finite(r20) and finite(r40) and r20>0 and r40>0
        self.latch_streak=self.latch_streak+1 if latch_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; self.recovery_streak=0
            reasons.append('RECOVERY_EPISODE_START')
        if self.episode:
            if native<=1e-12:
                self.recovery_streak=0
            else:
                recovery_healthy=finite(r20) and r20>0
                self.recovery_streak=self.recovery_streak+1 if recovery_healthy else 0
        else:
            self.recovery_streak=0
        cleared=self.latched and (self.latch_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.recovery_streak>=LDRC_REC or vre:
                self.episode=False; desired=1.
                reasons.append('FULL_RISK_CERTIFIED_R20' if self.recovery_streak>=LDRC_REC else 'FULL_RISK_CERTIFIED_SPY')
                self.recovery_streak=0
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        avail=(finite(wcdd) and finite(r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        if not self.latched and not cleared:
            div=(native>=1-1e-12 and effective_native is not None
                 and effective_native>=1-1e-12 and avail
                 and wcdd<=LDRC_DD and r20<=LDRC_R20 and spy20>=0.)
            if div:
                self.latched=True; reasons.append('LD_ENTER_DIVERGENCE')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = strategy9.transformed_source(output)

    pattern = r"class CandidateA:.*?(?=\ndef bil_factors)"
    text, count = re.subn(pattern, CANDIDATE_CLASSES.rstrip() + "\n", text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"candidate class seam: expected one match, got {count}")

    text = replace_once(
        text,
        "a_d,a_reason=ca.step(native_target,recent_r20,spy20)",
        "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20,r40)",
        "E1 call",
    )
    text = replace_once(
        text,
        "b_d,b_reason=cb.step(native_target,recent_r20,spy20)",
        "b_d,b_reason=cb.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20)",
        "E2 call",
    )
    text = replace_once(
        text,
        "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,",
        "'recent_r20':recent_r20,'recent_r40':recent_r40,'wc_r20':r20,'wc_r40':r40,'spy_r20':spy20,",
        "owned-book audit returns",
    )
    return text


def _metric_rows(daily: pd.DataFrame) -> list[dict]:
    starts = {
        "5": ("2021-07-30", 5.0),
        "10": ("2016-07-29", 10.0),
        "15": ("2011-07-29", 15.0),
        "20": ("2006-07-31", 20.0),
        "max": ("1998-01-02", None),
    }
    rows = []
    for window, (start, years) in starts.items():
        for variant, column in ((E1, "A_nav"), (E2, "B_nav")):
            rows.append({
                "window_years": window,
                "variant": variant,
                **corrected.old.metric_block(daily, column, start, years),
            })
    return rows


def _difference_episodes(daily: pd.DataFrame) -> pd.DataFrame:
    specs = ((E1, "A_allocation", "A_nav"), (E2, "B_allocation", "B_nav"))
    rows = []
    for variant, alloc_col, nav_col in specs:
        diff = (daily[alloc_col].astype(float) - daily["research_allocation"].astype(float)).abs() > 1e-12
        group = (diff != diff.shift(fill_value=False)).cumsum()
        for _, block in daily[diff].groupby(group[diff]):
            i0 = int(block.index[0])
            i1 = int(block.index[-1])
            before = max(i0 - 1, 0)
            base_ratio = float(daily.loc[before, nav_col]) / float(daily.loc[before, "research_nav"])
            end_ratio = float(daily.loc[i1, nav_col]) / float(daily.loc[i1, "research_nav"])
            delta = block[alloc_col].astype(float) - block["research_allocation"].astype(float)
            rows.append({
                "variant": variant,
                "start": str(pd.Timestamp(block.iloc[0]["date"]).date()),
                "end": str(pd.Timestamp(block.iloc[-1]["date"]).date()),
                "sessions": int(len(block)),
                "min_allocation_delta": float(delta.min()),
                "max_allocation_delta": float(delta.max()),
                "relative_wealth_change_through_end": float(end_ratio / base_ratio - 1.0),
            })
    return pd.DataFrame(rows)


def finalize(output: Path) -> None:
    strategy9.finalize(output)

    daily = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    required = {
        "date", "research_nav", "research_allocation", "A_nav", "B_nav",
        "A_allocation", "B_allocation", "wc_r20", "wc_r40",
        "recent_r20", "recent_r40", "native_close_target", "effective_native",
    }
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"architecture replay missing audit columns: {sorted(missing)}")

    metrics_path = output / "metrics.csv"
    metrics = pd.read_csv(metrics_path, dtype={"window_years": str})
    candidate_metrics = pd.DataFrame(_metric_rows(daily))
    metrics = pd.concat([metrics, candidate_metrics], ignore_index=True)
    metrics.to_csv(metrics_path, index=False)

    episodes = _difference_episodes(daily)
    episodes_path = output / "architecture_episode_attribution.csv"
    episodes.to_csv(episodes_path, index=False)

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["experiment"] = "broad_simplified_architecture_defects_e1_e2"
    summary["evidence_label"] = LABEL
    summary["experiment_budget"] = {
        "authorized_max": 10,
        "completed_candidate_experiments_in_this_replay": 2,
        "candidate_numbers": [1, 2],
        "control_counts_against_budget": False,
    }
    summary["candidates"] = {
        E1: {
            "change": "OR existing LD entry with owned-book divergence",
            "wc_drawdown_max": -0.10,
            "wc_r20_max": 0.0,
            "wc_r20_comparison": "strictly_less_than",
            "wc_r40_max": -0.08,
            "spy_r20_min": 0.0,
            "ceiling": 0.55,
            "existing_divergence_and_release_preserved": True,
            "new_fitted_numeric_thresholds": 0,
        },
        E2: {
            "change": "separate post-severe recovery clock; recent r20 positive for 7 sessions after native target leaves zero",
            "confirmation_sessions": 7,
            "native_zero_resets_clock": True,
            "native_ramp_may_accumulate_clock": True,
            "existing_divergence_entry_and_latch_release_preserved": True,
            "existing_spy_v_rebound_preserved": True,
            "recent_r40_removed_from_post_severe_recovery_only": True,
            "new_fitted_numeric_thresholds": 0,
        },
    }
    summary["candidate_metrics"] = {
        variant: {
            str(row.window_years): {
                "cagr": float(row.cagr),
                "max_drawdown": float(row.max_drawdown),
                "sharpe": float(row.sharpe),
                "ending_multiple": float(row.ending_multiple),
            }
            for row in metrics[metrics.variant == variant].itertuples(index=False)
        }
        for variant in (E1, E2)
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": "backtester.architecture-defects-e1-e2/1",
        "status": "PASS",
        "evidence_label": LABEL,
        "baseline": {
            "name": "Strategy 9 broad simplified fixed breadth calibration",
            "historical_run": 33876316789,
            "historical_artifact": 9939066139,
            "historical_head": "238891bf67cc75afa3efd4b82b71cfdb52c2fd75",
        },
        "candidate_experiments": [E1, E2],
        "fresh_control_variant": "RESEARCH",
        "formal_pit_certified": False,
        "daily_rows": int(len(daily)),
        "difference_episode_rows": int(len(episodes)),
    }
    manifest_path = output / "architecture-defects-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    experiment2_manifest = output / "experiment2-manifest.json"
    files = [
        output / "daily.csv.gz",
        metrics_path,
        summary_path,
        experiment2_manifest,
        manifest_path,
        episodes_path,
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{corrected.old.sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
    print(metrics.to_string(index=False), flush=True)
    print(episodes.to_string(index=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/broad_simplified_architecture_defects_e1_e2.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} candidates={E1},{E2}", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
