#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
IMPEDANCE_DIR = HERE.parent / "wealth-core-v5-sentinel-ex3-impedance-v1"
if str(IMPEDANCE_DIR) not in sys.path:
    sys.path.insert(0, str(IMPEDANCE_DIR))

import run_impedance as base

_BASE_APPLY_VARIANT = base.apply_variant
SELECTED_EX3_V5 = {
    "rec": 8,
    "r40_floor": -0.05,
    "fast_damaged": 0.88,
    "healthy_damaged": 0.63,
}

VARIANTS = {
    "split_clocks": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "none",
        "health_gate": False,
        "tier_confirm_sessions": 1,
        "study_role": "single_split_release_clocks",
    },
    "global_tier": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": -0.05,
        "tier_scope": "global",
        "health_gate": False,
        "tier_confirm_sessions": 1,
        "study_role": "single_global_existing_tier_rerisk",
    },
    "positive_gate": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": -0.05,
        "tier_scope": "none",
        "health_gate": True,
        "tier_confirm_sessions": 1,
        "study_role": "single_positive_recovery_gate",
    },
    "divergence_tier": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": -0.05,
        "tier_scope": "divergence",
        "health_gate": False,
        "tier_confirm_sessions": 1,
        "study_role": "single_divergence_only_tiering",
    },
    "native_tier": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": -0.05,
        "tier_scope": "native",
        "health_gate": False,
        "tier_confirm_sessions": 1,
        "study_role": "single_native_only_tiering",
    },
    "split_divergence_tier": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "divergence",
        "health_gate": False,
        "tier_confirm_sessions": 1,
        "study_role": "combo_split_plus_divergence_tier",
    },
    "split_divergence_tier_gate": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "divergence",
        "health_gate": True,
        "tier_confirm_sessions": 1,
        "study_role": "combo_split_divergence_tier_positive_gate",
    },
    "split_global_tier_gate": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "global",
        "health_gate": True,
        "tier_confirm_sessions": 1,
        "study_role": "combo_split_global_tier_positive_gate",
    },
    "split_global_tier_gate_c2": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "global",
        "health_gate": True,
        "tier_confirm_sessions": 2,
        "study_role": "robustness_two_session_tier_confirmation",
    },
    "split_global_tier_gate_c3": {
        **SELECTED_EX3_V5,
        "divergence_r40_floor": 0.00,
        "tier_scope": "global",
        "health_gate": True,
        "tier_confirm_sessions": 3,
        "study_role": "robustness_three_session_tier_confirmation",
    },
}

BASELINE_REFERENCE = {
    "authority": "Sentinel EX3 V5 selected REC=8 / full-recovery r40=-5%",
    "source_run": 34319850800,
    "windows": {
        "5": {"cagr": 0.310337, "max_drawdown": -0.204196, "sharpe_daily_252": 1.3466},
        "10": {"cagr": 0.264739, "max_drawdown": -0.273755, "sharpe_daily_252": 1.2466},
        "15": {"cagr": 0.222368, "max_drawdown": -0.273755, "sharpe_daily_252": 1.1776},
        "20": {"cagr": 0.215572, "max_drawdown": -0.273755, "sharpe_daily_252": 1.1211},
    },
}

_LAST_SELECTED_SHA256 = None


def _candidate_a_source(cfg: dict) -> str:
    native_floor = float(cfg["r40_floor"])
    div_floor = float(cfg["divergence_r40_floor"])
    tier_scope = str(cfg["tier_scope"])
    health_gate = bool(cfg["health_gate"])
    confirm = int(cfg["tier_confirm_sessions"])
    if tier_scope not in {"none", "global", "divergence", "native"}:
        raise RuntimeError(f"invalid tier scope: {tier_scope}")
    if confirm < 1:
        raise RuntimeError("tier_confirm_sessions must be >=1")

    return f"""class CandidateA:
    # Sentinel EX3 V5 with isolated research-only release/execution seams.
    def __init__(self):
        self.episode=False; self.latched=False
        self.full_streak=0; self.divergence_streak=0; self.recent_positive_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.concordance_releases=0
        self.rerisk_scope=None; self.up_confirm_streak=0
        self.tiered_up_moves=0; self.gated_up_holds=0

    @staticmethod
    def _next_existing_tier(previous, raw_desired):
        levels=(0.0, LDRC_CEIL, 0.65, 1.0)
        for level in levels:
            if level>previous+1e-12 and level<=raw_desired+1e-12:
                return float(level)
        return float(raw_desired)

    def step(self,native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20):
        native_full_healthy=(finite(recent_r20) and finite(recent_r40)
                            and recent_r20>0 and recent_r40>{native_floor!r})
        divergence_full_healthy=(finite(recent_r20) and finite(recent_r40)
                                and recent_r20>0 and recent_r40>{div_floor!r})
        strict_positive=(finite(recent_r20) and finite(recent_r40)
                         and recent_r20>0 and recent_r40>0.0)
        self.full_streak=self.full_streak+1 if native_full_healthy else 0
        self.divergence_streak=self.divergence_streak+1 if divergence_full_healthy else 0
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

        cleared=self.latched and (self.divergence_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')

        desired=native
        released_native=False
        if self.episode and native>=1-1e-12:
            concordant=(
                self.recent_positive_streak>=LDRC_REC
                and finite(wc_r20) and wc_r20>0
                and finite(recent_r20) and recent_r20>=wc_r20
                and finite(spy20) and spy20>=wc_r20
            )
            if self.full_streak>=LDRC_REC or vre or concordant:
                self.episode=False; desired=1.; released_native=True
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
                and recent_r20<=LDRC_R20 and spy20>=0.0
            )
            if divergence:
                self.latched=True
                reasons.append('LD_ENTER_DIVERGENCE')

        if self.latched:
            desired=min(desired,LDRC_CEIL)
        raw_desired=min(native,desired)

        if raw_desired<self.prev_desired-1e-12:
            self.rerisk_scope=None
            self.up_confirm_streak=0
        elif cleared:
            self.rerisk_scope='divergence'
        elif released_native:
            self.rerisk_scope='native'

        desired=raw_desired
        if desired>self.prev_desired+1e-12:
            if {health_gate!r} and not strict_positive:
                desired=self.prev_desired
                self.up_confirm_streak=0
                self.gated_up_holds+=1
                reasons.append('UPWARD_HEALTH_HOLD')
            else:
                self.up_confirm_streak+=1
                if self.up_confirm_streak<{confirm}:
                    desired=self.prev_desired
                    self.gated_up_holds+=1
                    reasons.append('UPWARD_CONFIRM_HOLD')
                else:
                    scoped=(
                        {tier_scope!r}=='global'
                        or ({tier_scope!r} in ('divergence','native')
                            and self.rerisk_scope=={tier_scope!r})
                    )
                    if scoped:
                        tiered=self._next_existing_tier(self.prev_desired,raw_desired)
                        if tiered<raw_desired-1e-12:
                            self.tiered_up_moves+=1
                            reasons.append('UPWARD_EXISTING_TIER')
                        desired=tiered
                    self.up_confirm_streak=0

        if desired>=raw_desired-1e-12 and desired>self.prev_desired+1e-12:
            self.rerisk_scope=None
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'

"""


def apply_variant(src: str, cfg: dict) -> str:
    global _LAST_SELECTED_SHA256
    selected = _BASE_APPLY_VARIANT(src, {
        "rec": 8,
        "r40_floor": -0.05,
        "fast_damaged": 0.88,
        "healthy_damaged": 0.63,
    })
    _LAST_SELECTED_SHA256 = hashlib.sha256(selected.encode()).hexdigest()

    start = selected.count("class CandidateA:")
    end = selected.count("class CandidateB:")
    if start != 1 or end != 1:
        raise RuntimeError(f"CandidateA/B source seam mismatch: {start}/{end}")
    i = selected.index("class CandidateA:")
    j = selected.index("class CandidateB:", i)
    candidate = selected[:i] + _candidate_a_source(cfg) + selected[j:]

    for marker in (
        "LDRC_DD=-0.1; LDRC_R20=-0.085; LDRC_CEIL=.55; LDRC_REC=8; LDRC_V=0.11",
        "'dam':0.88",
        "dam<=0.63 and green>=.20",
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"frozen controller marker mismatch: {marker}")
    return candidate


def _max_dd_episode(frame: pd.DataFrame, years: int) -> dict:
    dates = pd.to_datetime(frame["date"])
    end = dates.iloc[-1]
    x = frame.loc[dates >= end - pd.DateOffset(years=years)].copy().reset_index(drop=True)
    nav = x["A_nav"].astype(float)
    running = nav.cummax()
    dd = nav / running - 1.0
    trough_i = int(dd.idxmin())
    peak_i = int(nav.iloc[:trough_i + 1].idxmax())
    allocation = x["A_allocation"].astype(float)
    seg = x.iloc[peak_i:trough_i + 1].copy()
    seg_alloc = allocation.iloc[peak_i:trough_i + 1].reset_index(drop=True)

    drops = np.flatnonzero(seg_alloc.diff().fillna(0.0).to_numpy() < -1e-12)
    rises = np.flatnonzero(seg_alloc.diff().fillna(0.0).to_numpy() > 1e-12)

    def _event(indices):
        if len(indices) == 0:
            return None
        local = int(indices[0])
        row = seg.iloc[local]
        return {
            "date": str(pd.Timestamp(row["date"]).date()),
            "allocation": float(row["A_allocation"]),
            "reason": str(row.get("A_reason", "")),
        }

    return {
        "window_years": years,
        "peak_date": str(pd.Timestamp(x.loc[peak_i, "date"]).date()),
        "trough_date": str(pd.Timestamp(x.loc[trough_i, "date"]).date()),
        "max_drawdown": float(dd.iloc[trough_i]),
        "allocation_at_peak": float(allocation.iloc[peak_i]),
        "allocation_at_trough": float(allocation.iloc[trough_i]),
        "minimum_allocation_peak_to_trough": float(seg_alloc.min()),
        "average_allocation_peak_to_trough": float(seg_alloc.mean()),
        "first_derisk_fill": _event(drops),
        "first_rerisk_fill_before_trough": _event(rises),
        "allocation_transitions_peak_to_trough": int(
            (seg_alloc.diff().abs().fillna(0.0) > 1e-12).sum()
        ),
    }


def _augment(output: Path, variant: str) -> None:
    result_path = output / "RESULT.json"
    daily_path = output / "daily.csv"
    result = json.loads(result_path.read_text())
    frame = pd.read_csv(daily_path, parse_dates=["date"])
    cfg = VARIANTS[variant]
    drawdown = {
        "schema": "research.wealth-core-v5-sentinel-ex3-v6-drawdown/1",
        "variant": variant,
        "study_role": cfg["study_role"],
        "baseline_reference": BASELINE_REFERENCE,
        "selected_ex3_v5_generated_sha256": _LAST_SELECTED_SHA256,
        "structural_contract": {
            "wealth_core_v5_frozen": True,
            "sentinel_entry_predictors_frozen": True,
            "downward_transitions_remain_immediate_next_open": True,
            "tier_levels_are_preexisting_controller_levels": [0.0, 0.55, 0.65, 1.0],
            "performance_feedback_used_to_define_arm": False,
        },
        "episodes": {
            str(years): _max_dd_episode(frame, years)
            for years in (5, 10, 15, 20)
        },
    }
    (output / "DRAWDOWN.json").write_text(json.dumps(drawdown, indent=2, sort_keys=True) + "\n")
    result["drawdown_study"] = drawdown
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    hashes = {}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "SHA256.json":
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "SHA256.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")


def main() -> int:
    base.VARIANTS = VARIANTS
    base.apply_variant = apply_variant
    rc = base.main()
    if rc != 0:
        return rc
    try:
        output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
        variant = sys.argv[sys.argv.index("--variant") + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("wrapper requires --variant and --output") from exc
    _augment(output, variant)
    print("[V6_DRAWDOWN_AUGMENTED] " + json.dumps({
        "variant": variant,
        "output": str(output),
        "selected_ex3_v5_generated_sha256": _LAST_SELECTED_SHA256,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
