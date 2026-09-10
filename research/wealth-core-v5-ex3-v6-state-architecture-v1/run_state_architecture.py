#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCHEMA = "research.wealth-core-v5-ex3-v6-state-architecture-v1/1"
EXPECTED_V6_SELECTED_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"
EXPECTED_V6 = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}
HARNESS_AUTHORITY = "eaddca3f04f279e99663f832bf7293e92ee15662"
MAIN_V6_AUTHORITY = "96f705c3b699ec283dbac7e93b973dba9769f038"
STATE_MIN_WINDOW = 60

ARCHITECTURE_BLOCK = r'''def _arch_replay(_records):
    _n=Native(); _a=CandidateA()
    _pending_native=1.; _effective_native=1.
    _desired=1.; _reason='NORMAL'; _native=1.
    for _ob,_wcdd,_recent_r20,_recent_r40,_spy20,_wc_r20,_measured in _records:
        _native,_,_=_n.step(_ob)
        _desired,_reason=_a.step(_native,_effective_native,_wcdd,_recent_r20,_recent_r40,_spy20,_wc_r20)
        # Preserve the authoritative source ordering: the close decision sees
        # the pre-update effective-native value, then the measurement-session
        # open state is advanced from the previously pending native target.
        if _measured:
            _effective_native=_pending_native
        _pending_native=_native
    return float(_desired),_reason,float(_native),_a

class CandidateB:
    """Research-only 60-session bounded-state Sentinel reconstruction."""
    def __init__(self):
        self.history=[]; self.window=60; self.last_native=1.; self.episodes=0
        self.reconstructions=0
    def step(self,ob,wcdd,recent_r20,recent_r40,spy20,wc_r20,measured):
        self.history.append((ob,wcdd,recent_r20,recent_r40,spy20,wc_r20,bool(measured)))
        if len(self.history)>self.window:
            del self.history[:-self.window]
        desired,reason,native,_a=_arch_replay(self.history)
        self.last_native=float(native); self.episodes=int(_a.episodes); self.reconstructions+=1
        return float(desired),reason

def stateless_step(ob,wcdd,recent_r20,recent_r40,spy20,wc_r20,measured):
    desired,reason,native,_a=_arch_replay([(ob,wcdd,recent_r20,recent_r40,spy20,wc_r20,bool(measured))])
    return float(desired),reason,float(native)
'''

OLD_B_CALL = "b_d,b_reason=cb.step(native_target,recent_r20,spy20)"
NEW_B_CALL = """_arch_ob=(dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq)\n            b_d,b_reason=cb.step(_arch_ob,dd,recent_r20,recent_r40,spy20,r20,date>=START)\n            c_d,c_reason,c_native=stateless_step(_arch_ob,dd,recent_r20,recent_r40,spy20,r20,date>=START)"""
OLD_PENDING = "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
# Keep the authoritative pending-allocation marker byte-for-byte so the inherited
# causal-timing guard continues to prove the production track. The research-only
# stateless track then overwrites only its own control slot at the same close.
NEW_PENDING = OLD_PENDING + "; pend['control']=c_d"
OLD_ROW = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,\n                             'effective_native':effective_native,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],"
NEW_ROW = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,'minimal_native_close_target':cb.last_native,'stateless_native_close_target':c_native,\n                             'effective_native':effective_native,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],"
OLD_REASONS = "'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason"
NEW_REASONS = "'control_reason':c_reason,'A_reason':a_reason,'B_reason':b_reason"


def load(path: Path):
    spec = importlib.util.spec_from_file_location("v6_adversarial_generated_state_arch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def replace_n(src: str, old: str, new: str, expected: int, label: str) -> str:
    n = src.count(old)
    if n != expected:
        raise RuntimeError(f"{label}: expected {expected} seam(s), saw {n}")
    return src.replace(old, new)


def block(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def treatment_source(src: str) -> str:
    if hashlib.sha256(src.encode()).hexdigest() != EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("exact V6 source authority mismatch before architecture treatment")
    original_native = block(src, "class Native:", "class ControlLDRC:")
    original_a = block(src, "class CandidateA:", "class CandidateB")

    b0 = src.index("class CandidateB")
    b1 = src.index("\n\n_cash_frame=", b0)
    out = src[:b0] + ARCHITECTURE_BLOCK + src[b1:]
    out = replace_n(out, OLD_B_CALL, NEW_B_CALL, 1, "bounded/stateless controller call")
    out = replace_n(out, OLD_PENDING, NEW_PENDING, 1, "architecture pending allocation")
    out = replace_n(out, OLD_ROW, NEW_ROW, 1, "architecture evidence columns")
    out = replace_n(out, OLD_REASONS, NEW_REASONS, 1, "architecture reason labels")

    if block(out, "class Native:", "class ControlLDRC:") != original_native:
        raise RuntimeError("authoritative Native implementation changed")
    if block(out, "class CandidateA:", "def _arch_replay") != original_a:
        raise RuntimeError("authoritative CandidateA implementation changed")
    if out.count(OLD_PENDING) != 1:
        raise RuntimeError("authoritative causal timing marker was not preserved exactly once")
    if out.count("pend['control']=c_d") != 1 or out.count("pend['A']=a_d") != 1 or out.count("pend['B']=b_d") != 1:
        raise RuntimeError("architecture allocation timing seam changed")
    if "eff['control']=c_d" in out or "eff['B']=b_d" in out:
        raise RuntimeError("illegal same-session architecture allocation")
    compile(out, "<state-architecture-generated>", "exec")
    return out


def allocation_counts(frame: pd.DataFrame, col: str) -> dict:
    x = frame[col].astype(float)
    return {
        "average": float(x.mean()),
        "sessions_by_level": {str(v): int(np.isclose(x.to_numpy(), v, atol=1e-12).sum()) for v in (0.0, .55, .65, 1.0)},
        "transitions": int((x.diff().abs() > 1e-12).sum()),
    }


def pair_delta(frame: pd.DataFrame, left: str, right: str) -> dict:
    a = frame[left].astype(float).to_numpy(); b = frame[right].astype(float).to_numpy()
    d = np.abs(a-b); mask = d > 1e-12; ix = np.flatnonzero(mask)
    return {
        "sessions": int(mask.sum()),
        "fraction": float(mask.mean()),
        "absolute_area": float(d.sum()),
        "mean_abs": float(d.mean()),
        "first": None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[0])]).date()),
        "last": None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[-1])]).date()),
    }


def resolve_v6_runner() -> Path:
    raw = os.environ.get("STATE_ARCH_V6_RUNNER")
    if raw:
        return Path(raw).resolve()
    return (HERE.parent / "wealth-core-v5-sentinel-ex3-v6-adversarial-v1" / "run_adversarial_v6.generated.py").resolve()


def main() -> int:
    v6_runner = resolve_v6_runner()
    if not v6_runner.exists():
        raise RuntimeError(f"generate exact V6 runner first: {v6_runner}")
    base = load(v6_runner)
    if base.SELECTED != EXPECTED_V6:
        raise RuntimeError(f"wrong V6 config: {base.SELECTED}")

    original_build = base.build_selected
    original_execute = base.execute

    def patched_build(control_source: Path, median_overlay: Path) -> str:
        exact = original_build(control_source, median_overlay)
        if base.sha(exact.encode()) != EXPECTED_V6_SELECTED_SOURCE_SHA256:
            raise RuntimeError("exact V6 source authority mismatch")
        patched = treatment_source(exact)
        base.timing_guard(patched)
        return patched

    def patched_execute(src: str, outdir: Path, tag: str, keep_raw: bool = False) -> dict:
        result = original_execute(src, outdir, tag, keep_raw)
        frame = pd.read_csv(outdir / "engine" / "daily.csv", parse_dates=["date"])
        result["architectures"] = {
            "current": {
                "description": "authoritative Native + EX3 V6, unbounded carried controller state",
                "metrics": base.imp.windows(frame, "A_nav"),
                "allocation": allocation_counts(frame, "A_allocation"),
            },
            "state_minimal_60": {
                "description": "exact Native + CandidateA semantics reconstructed from only the last 60 observable sessions",
                "metrics": base.imp.windows(frame, "B_nav"),
                "allocation": allocation_counts(frame, "B_allocation"),
                "memory_sessions": STATE_MIN_WINDOW,
            },
            "stateless_1": {
                "description": "exact Native + CandidateA semantics reconstructed from the current observable session only",
                "metrics": base.imp.windows(frame, "control_nav"),
                "allocation": allocation_counts(frame, "control_allocation"),
                "memory_sessions": 1,
            },
        }
        result["same_tape_deltas"] = {
            "minimal_vs_current": pair_delta(frame, "B_allocation", "A_allocation"),
            "stateless_vs_current": pair_delta(frame, "control_allocation", "A_allocation"),
        }
        result["architecture_contract"] = {
            "research_only": True,
            "production_code_modified": False,
            "future_data": False,
            "baseline_path_access": False,
            "same_wealth_core_tape": True,
            "current_track_byte_preserved": True,
            "state_minimal_memory_sessions": STATE_MIN_WINDOW,
            "stateless_hidden_state_sessions": 0,
            "rolling_features_allowed": True,
            "note": "stateless means no hidden Sentinel state crosses a session boundary; rolling observable inputs remain allowed",
        }
        cols = [
            "date","research_selected_positions","shadow_equity","wc_dd","damaged","green","recent_r20","recent_r40","spy_r20",
            "native_close_target","minimal_native_close_target","stateless_native_close_target","effective_native",
            "A_allocation","B_allocation","control_allocation","A_nav","B_nav","control_nav","A_reason","B_reason","control_reason",
        ]
        frame[cols].to_csv(outdir / "architecture-daily.csv", index=False)
        return result

    base.build_selected = patched_build
    base.execute = patched_execute
    base.SCHEMA = SCHEMA
    base.SYSTEM = "Wealth Core V5 + Sentinel EX3 V6 state architecture experiment"
    base.UNIVERSE_CASES = [("drop_01pct_seed11", .01, 11)]
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
