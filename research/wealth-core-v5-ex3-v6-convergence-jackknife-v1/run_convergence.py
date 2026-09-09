#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
V6_RUNNER = HERE.parent / "wealth-core-v5-sentinel-ex3-v6-adversarial-v1" / "run_adversarial_v6.generated.py"
SCHEMA = "research.wealth-core-v5-ex3-v6-convergence-jackknife/1"
PATCH_NAME = "neutral-full-native-rec8-canonicalization"

OLD_B = '''class CandidateB:
    def __init__(self): self.episode=False; self.streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,r20,spy20):
        healthy=finite(r20) and r20>0
        self.streak=self.streak+1 if healthy else 0
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('EPISODE_START')
        desired=native
        if self.episode and native>=1-1e-12:
            release=(self.streak>=LDRC_REC) or (finite(spy20) and spy20>LDRC_V)
            if release:
                self.episode=False; desired=1.; reasons.append('RELEASE_R20_7' if self.streak>=LDRC_REC else 'RELEASE_SPY')
            else:
                desired=self.prev_desired; reasons.append('HOLD')
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'
'''

NEW_B = '''class CandidateB:
    """Exact CandidateA economics plus research-only finite-memory convergence."""
    def __init__(self):
        self.episode=False; self.latched=False
        self.full_streak=0; self.recent_positive_streak=0; self.neutral_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.concordance_releases=0; self.convergence_releases=0

    def step(self,native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20):
        full_healthy=(finite(recent_r20) and finite(recent_r40)
                      and recent_r20>0 and recent_r40>-0.04)
        self.full_streak=self.full_streak+1 if full_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]

        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True
            self.recent_positive_streak=0; self.neutral_streak=0
            reasons.append('RECOVERY_EPISODE_START')

        if self.episode:
            if native>0 and finite(recent_r20) and recent_r20>0:
                self.recent_positive_streak+=1
            else:
                self.recent_positive_streak=0
        else:
            self.recent_positive_streak=0

        avail=(finite(wcdd) and finite(recent_r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        divergence=(
            native>=1-1e-12
            and effective_native is not None and finite(effective_native)
            and effective_native>=1-1e-12
            and avail and wcdd<=LDRC_DD
            and recent_r20<=LDRC_R20 and spy20>=0.0
        )
        neutral=(native>=1-1e-12
                 and effective_native is not None and finite(effective_native)
                 and effective_native>=1-1e-12
                 and avail and not divergence)
        self.neutral_streak=self.neutral_streak+1 if neutral else 0
        converged=self.neutral_streak>=LDRC_REC

        cleared=self.latched and (self.full_streak>=LDRC_REC or vre or converged)
        if cleared:
            self.latched=False
            if converged and self.full_streak<LDRC_REC and not vre:
                self.convergence_releases+=1; reasons.append('DIVERGENCE_CLEAR_CONVERGENCE_REC8')
            else:
                reasons.append('DIVERGENCE_CLEAR')

        desired=native
        if self.episode and native>=1-1e-12:
            concordant=(
                self.recent_positive_streak>=LDRC_REC
                and finite(wc_r20) and wc_r20>0
                and finite(recent_r20) and recent_r20>=wc_r20
                and finite(spy20) and spy20>=wc_r20
            )
            if self.full_streak>=LDRC_REC or vre or concordant or converged:
                self.episode=False; desired=1.
                if converged and self.full_streak<LDRC_REC and not vre and not concordant:
                    self.convergence_releases+=1; reasons.append('FULL_RISK_CERTIFIED_CONVERGENCE_REC8')
                elif concordant and self.full_streak<LDRC_REC and not vre:
                    self.concordance_releases+=1; reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
                elif self.full_streak>=LDRC_REC:
                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
                else:
                    reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')
                self.recent_positive_streak=0
            else:
                desired=self.prev_desired
                reasons.append('FULL_RISK_HELD')

        if not self.latched and not cleared and divergence:
            self.latched=True
            self.neutral_streak=0
            reasons.append('LD_ENTER_DIVERGENCE')

        if self.latched:
            desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'
'''

OLD_CALL = "b_d,b_reason=cb.step(native_target,recent_r20,spy20)"
NEW_CALL = "b_d,b_reason=cb.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"


def load(path: Path):
    spec = importlib.util.spec_from_file_location("v6_adversarial_generated", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def replace_once(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one seam, saw {n}")
    return src.replace(old, new, 1)


def treatment_source(src: str) -> str:
    # A remains byte-for-byte exact EX3 V6. Only B is replaced.
    out = replace_once(src, OLD_B, NEW_B, "CandidateB convergence treatment")
    out = replace_once(out, OLD_CALL, NEW_CALL, "CandidateB full-input call")
    for marker in (
        "recent_r40>-0.04)",
        "LDRC_REC=8",
        "DIVERGENCE_CLEAR_CONVERGENCE_REC8",
        "FULL_RISK_CERTIFIED_CONVERGENCE_REC8",
    ):
        if marker not in out:
            raise RuntimeError(f"convergence authority marker missing: {marker}")
    return out


def b_allocation_counts(frame: pd.DataFrame) -> dict:
    x = frame["B_allocation"].astype(float)
    return {
        "average": float(x.mean()),
        "sessions_by_level": {str(v): int(np.isclose(x.to_numpy(), v, atol=1e-12).sum()) for v in (0.0, .55, .65, 1.0)},
        "transitions": int((x.diff().abs() > 1e-12).sum()),
    }


def paired_direct(frame: pd.DataFrame) -> dict:
    a = frame.A_allocation.astype(float).to_numpy()
    b = frame.B_allocation.astype(float).to_numpy()
    d = np.abs(a-b) > 1e-12
    idx = np.flatnonzero(d)
    return {
        "allocation_difference_sessions": int(d.sum()),
        "allocation_difference_fraction": float(d.mean()),
        "first_allocation_difference": None if not len(idx) else str(pd.Timestamp(frame.date.iloc[int(idx[0])]).date()),
        "last_allocation_difference": None if not len(idx) else str(pd.Timestamp(frame.date.iloc[int(idx[-1])]).date()),
    }


def main() -> int:
    if not V6_RUNNER.exists():
        raise RuntimeError(f"generate V6 runner first: {V6_RUNNER}")
    base = load(V6_RUNNER)
    if base.SELECTED != {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}:
        raise RuntimeError(f"wrong V6 config: {base.SELECTED}")

    original_build = base.build_selected
    original_execute = base.execute

    def patched_build(control_source: Path, median_overlay: Path) -> str:
        exact = original_build(control_source, median_overlay)
        # Exact A authority must still be present before treatment insertion.
        if base.sha(exact.encode()) != base.V6_SELECTED_SOURCE_SHA256:
            raise RuntimeError("exact V6 source authority mismatch before convergence patch")
        return treatment_source(exact)

    def patched_execute(src: str, outdir: Path, tag: str, keep_raw: bool = False) -> dict:
        result = original_execute(src, outdir, tag, keep_raw)
        frame = pd.read_csv(outdir / "engine" / "daily.csv", parse_dates=["date"])
        result["treatment"] = base.imp.windows(frame, "B_nav")
        result["treatment_allocation"] = b_allocation_counts(frame)
        result["paired_direct"] = paired_direct(frame)
        result["convergence_patch"] = {
            "name": PATCH_NAME,
            "research_only": True,
            "neutral_sessions_required": 8,
            "future_data": False,
            "baseline_path_access": False,
        }
        cols = ["date","research_selected_positions","A_allocation","B_allocation","A_nav","B_nav","native_close_target","effective_native","A_reason","B_reason"]
        frame[cols].to_csv(outdir / "paired-daily.csv", index=False)
        return result

    base.build_selected = patched_build
    base.execute = patched_execute
    base.SCHEMA = SCHEMA
    base.SYSTEM = "Wealth Core V5 + exact r40_m04_rec8 / convergence-patched paired experiment"
    base.UNIVERSE_CASES = [
        ("drop_01pct_seed11", .01, 11),
        ("drop_01pct_seed29", .01, 29),
        ("drop_01pct_seed47", .01, 47),
    ]

    # Baseline A parity assertion still validates the untouched controller.
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
