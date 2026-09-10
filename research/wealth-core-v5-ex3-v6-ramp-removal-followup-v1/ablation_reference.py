#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCHEMA = "research.wealth-core-v5-ex3-v6-state-component-ablation-v1/1"
EXPECTED_V6_SELECTED_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"
EXPECTED_V6 = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}
HARNESS_AUTHORITY = "eaddca3f04f279e99663f832bf7293e92ee15662"
MAIN_V6_AUTHORITY = "96f705c3b699ec283dbac7e93b973dba9769f038"

VARIANTS = (
    "native_base_anchor",
    "native_base_duration",
    "native_slow_persistence",
    "native_recovery_ramp",
    "ex3_episode_memory",
    "ex3_latch_memory",
)

TELEMETRY_INIT_MARKER = "    prev_close_eq=None; prev_perf_date=None"
TELEMETRY_INIT_REPL = TELEMETRY_INIT_MARKER + "; _ablation_ob_rows=[]"
TELEMETRY_CALL_MARKER = "            b_d,b_reason=cb.step(native_target,recent_r20,spy20)"
TELEMETRY_CALL_REPL = TELEMETRY_CALL_MARKER + r"""
            _ablation_ob_rows.append({
                'date':date,'measured':bool(date>=START),
                'dd':dd,'r5':r5,'r10':r10,'r20':r20,'r40':r40,
                'dam':dam_b,'green':green_b,'ddam5':ddam5,'spy20':spy20,
                'volacc':volacc,'stops20':stops20,'nav':eq,
                'open_eq':open_eq,'close_eq':eq,
                'recent_r20':recent_r20,'recent_r40':recent_r40,
                'current_native_close_target':native_target,
                'current_effective_native_preclose':effective_native,
                'current_close_desired':a_d,'current_close_reason':a_reason,
            })"""
TELEMETRY_WRITE_MARKER = "    out=pd.DataFrame(rows)"
TELEMETRY_WRITE_REPL = (
    "    pd.DataFrame(_ablation_ob_rows).to_csv(OUT/'ablation-observations.csv',index=False)\n"
    + TELEMETRY_WRITE_MARKER
)

BASE_BLOCK_START = "        if base:\n"
BASE_BLOCK_END = "        since="
SLOW_BLOCK_START = "        if self.slow:\n"
SLOW_BLOCK_END = "        parent=0."
RECOVERY_BLOCK_START = "        elif recovering:\n"
RECOVERY_BLOCK_END = "        elif self.ramp:\n"
RAMP_BLOCK_START = "        elif self.ramp:\n"
RAMP_BLOCK_END = "        else: target=1.\n"

def load(path: Path):
    spec = importlib.util.spec_from_file_location("v6_adversarial_generated_state_ablation", path)
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
    return src.replace(old, new, expected)

def block(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]

def replace_between(src: str, start_marker: str, end_marker: str, repl: str, label: str) -> str:
    if src.count(start_marker) != 1:
        raise RuntimeError(f"{label}: start marker count {src.count(start_marker)}")
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[:i] + repl + src[j:]

def telemetry_source(src: str) -> str:
    if hashlib.sha256(src.encode()).hexdigest() != EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("exact V6 source authority mismatch before telemetry instrumentation")
    native = block(src, "class Native:", "class ControlLDRC:")
    cand = block(src, "class CandidateA:", "class CandidateB")
    out = replace_n(src, TELEMETRY_INIT_MARKER, TELEMETRY_INIT_REPL, 1, "telemetry init")
    out = replace_n(out, TELEMETRY_CALL_MARKER, TELEMETRY_CALL_REPL, 1, "telemetry observation")
    out = replace_n(out, TELEMETRY_WRITE_MARKER, TELEMETRY_WRITE_REPL, 1, "telemetry write")
    if block(out, "class Native:", "class ControlLDRC:") != native:
        raise RuntimeError("authoritative Native block changed")
    if block(out, "class CandidateA:", "class CandidateB") != cand:
        raise RuntimeError("authoritative CandidateA block changed")
    compile(out, "<state-component-telemetry>", "exec")
    return out

def _rename_class(src: str, old: str, new: str) -> str:
    marker = f"class {old}:"
    if src.count(marker) != 1:
        raise RuntimeError(f"class rename seam for {old}: {src.count(marker)}")
    return src.replace(marker, f"class {new}:", 1)

def _native_variant_sources(exact: str) -> dict[str, str]:
    base = block(exact, "class Native:", "class ControlLDRC:")
    out = {}

    anchor = _rename_class(base, "Native", "NativeAblateBaseAnchor")
    anchor = replace_between(
        anchor,
        BASE_BLOCK_START,
        BASE_BLOCK_END,
        """        if base:
            # Ablation: remove the carried anchor; use only the current NAV.
            self.base_anchor=nav
            if not prior_base: self.base_dur=1
            else: self.base_dur+=1
        else: self.base_anchor=None; self.base_dur=0
""",
        "base-anchor ablation",
    )
    out["native_base_anchor"] = anchor

    duration = _rename_class(base, "Native", "NativeAblateBaseDuration")
    duration = replace_between(
        duration,
        BASE_BLOCK_START,
        BASE_BLOCK_END,
        """        if base:
            # Ablation: remove elapsed-duration memory while preserving anchor state.
            if not prior_base: self.base_anchor=nav
            self.base_dur=SLOW['dur']
        else: self.base_anchor=None; self.base_dur=0
""",
        "base-duration ablation",
    )
    out["native_base_duration"] = duration

    slow = _rename_class(base, "Native", "NativeAblateSlowPersistence")
    slow = replace_between(
        slow,
        SLOW_BLOCK_START,
        SLOW_BLOCK_END,
        """        # Ablation: the slow state is contemporaneous only; no persistence/recovery age.
        self.slow=bool(slowsig); self.slow_age=0; self.slow_h=0
""",
        "slow-persistence ablation",
    )
    out["native_slow_persistence"] = slow

    ramp = _rename_class(base, "Native", "NativeAblateRecoveryRamp")
    ramp = replace_between(
        ramp,
        RECOVERY_BLOCK_START,
        RECOVERY_BLOCK_END,
        """        elif recovering:
            # Ablation: severe-state recovery returns directly to full exposure.
            self.ramp=False; self.ramp_idx=None; self.ramp_h=0; target=1.
""",
        "recovery branch ablation",
    )
    ramp = replace_between(
        ramp,
        RAMP_BLOCK_START,
        RAMP_BLOCK_END,
        """        elif self.ramp:
            # Defensive cleanup if a serialized/legacy ramp state is encountered.
            self.ramp=False; self.ramp_idx=None; self.ramp_h=0; target=1.
""",
        "ramp-state ablation",
    )
    out["native_recovery_ramp"] = ramp
    return out

def _candidate_variant_sources(exact: str) -> dict[str, str]:
    base = block(exact, "class CandidateA:", "class CandidateB")
    out = {}

    episode = _rename_class(base, "CandidateA", "CandidateAAblateEpisodeMemory")
    old = "        if self.prev_native>=1-1e-12 and native<1-1e-12:\n"
    new = "        if False and self.prev_native>=1-1e-12 and native<1-1e-12:\n"
    episode = replace_n(episode, old, new, 1, "EX3 episode-entry ablation")
    out["ex3_episode_memory"] = episode

    latch = _rename_class(base, "CandidateA", "CandidateAAblateLatchMemory")
    old = "        if not self.latched and not cleared:\n"
    new = "        if False and not self.latched and not cleared:\n"
    latch = replace_n(latch, old, new, 1, "EX3 latch-entry ablation")
    out["ex3_latch_memory"] = latch
    return out

def build_variant_classes(module, exact: str) -> dict[str, tuple[type, type]]:
    nsrc = _native_variant_sources(exact)
    csrc = _candidate_variant_sources(exact)
    for text in list(nsrc.values()) + list(csrc.values()):
        exec(compile(text, "<ablation-class>", "exec"), module.__dict__)
    return {
        "native_base_anchor": (module.NativeAblateBaseAnchor, module.CandidateA),
        "native_base_duration": (module.NativeAblateBaseDuration, module.CandidateA),
        "native_slow_persistence": (module.NativeAblateSlowPersistence, module.CandidateA),
        "native_recovery_ramp": (module.NativeAblateRecoveryRamp, module.CandidateA),
        "ex3_episode_memory": (module.Native, module.CandidateAAblateEpisodeMemory),
        "ex3_latch_memory": (module.Native, module.CandidateAAblateLatchMemory),
    }

def _as_bool(value) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes")

def _float_or_nan(value) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except Exception:
        return float("nan")

def replay_controller(module, observations: pd.DataFrame, native_cls, candidate_cls) -> pd.DataFrame:
    native = native_cls()
    candidate = candidate_cls()
    pending_native = 1.0
    effective_native = 1.0
    pending_alloc = 1.0
    effective_alloc = 1.0
    nav = 1.0
    prev_close_eq = None
    prev_perf_date = None
    rows = []
    _, bil = module.load_funds()

    for r in observations.itertuples(index=False):
        date = pd.Timestamp(r.date)
        ob = (
            _float_or_nan(r.dd), _float_or_nan(r.r5), _float_or_nan(r.r10),
            _float_or_nan(r.r20), _float_or_nan(r.r40), _float_or_nan(r.dam),
            _float_or_nan(r.green), _float_or_nan(r.ddam5), _float_or_nan(r.spy20),
            _float_or_nan(r.volacc), int(r.stops20), _float_or_nan(r.nav),
        )
        native_target, fastsig, slowsig = native.step(ob)
        desired, reason = candidate.step(
            native_target, effective_native, _float_or_nan(r.dd),
            _float_or_nan(r.recent_r20), _float_or_nan(r.recent_r40),
            _float_or_nan(r.spy20), _float_or_nan(r.r20),
        )
        measured = _as_bool(r.measured)
        if measured:
            if prev_close_eq is None:
                effective_native = pending_native
                effective_alloc = pending_alloc
            else:
                effective_native = pending_native
                new_alloc = pending_alloc
                nav, _ = module.apply_overlay(
                    nav, effective_alloc, new_alloc,
                    float(prev_close_eq), float(r.open_eq), float(r.close_eq),
                    bil, date, prev_perf_date,
                )
                effective_alloc = new_alloc
            rows.append({
                "date": date,
                "allocation": float(effective_alloc),
                "nav": float(nav),
                "native_close_target": float(native_target),
                "effective_native": float(effective_native),
                "close_desired": float(desired),
                "close_reason": str(reason),
                "fast_signal": bool(fastsig),
                "slow_signal": bool(slowsig),
            })
            prev_perf_date = date
            prev_close_eq = float(r.close_eq)
        pending_native = float(native_target)
        pending_alloc = float(desired)

    return pd.DataFrame(rows)

def pair_delta(frame: pd.DataFrame, left: str, right: str) -> dict:
    a = frame[left].astype(float).to_numpy()
    b = frame[right].astype(float).to_numpy()
    d = np.abs(a-b)
    mask = d > 1e-12
    ix = np.flatnonzero(mask)
    return {
        "sessions": int(mask.sum()),
        "fraction": float(mask.mean()),
        "absolute_area": float(d.sum()),
        "mean_abs": float(d.mean()),
        "first": None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[0])]).date()),
        "last": None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[-1])]).date()),
    }

def allocation_counts(frame: pd.DataFrame, col: str) -> dict:
    x = frame[col].astype(float)
    return {
        "average": float(x.mean()),
        "sessions_by_level": {
            str(v): int(np.isclose(x.to_numpy(), v, atol=1e-12).sum())
            for v in (0.0, .55, .65, 1.0)
        },
        "transitions": int((x.diff().abs() > 1e-12).sum()),
    }

def _module_from_source(src: str, name: str):
    module = types.ModuleType(name)
    module.__file__ = f"<{name}>"
    sys.modules[name] = module
    exec(compile(src, module.__file__, "exec"), module.__dict__)
    return module

def offline_variant_analysis(base, exact: str, instrumented: str, outdir: Path) -> dict:
    engine = outdir / "engine"
    obs_path = engine / "ablation-observations.csv"
    daily_path = engine / "daily.csv"
    if not obs_path.exists():
        raise RuntimeError("missing ablation observations")
    obs = pd.read_csv(obs_path, parse_dates=["date"])
    daily = pd.read_csv(daily_path, parse_dates=["date"])
    if len(daily) != 5032:
        raise RuntimeError(f"daily session count changed: {len(daily)}")
    if not obs["date"].is_monotonic_increasing or obs["date"].duplicated().any():
        raise RuntimeError("ablation observation ordering failure")
    if int(obs["measured"].map(_as_bool).sum()) != 5032:
        raise RuntimeError("ablation observation measurement count mismatch")

    modname = "state_component_defs_" + hashlib.sha256(outdir.as_posix().encode()).hexdigest()[:12]
    module = _module_from_source(instrumented, modname)
    if getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("offline definitions not bound to full-PIT mode")
    module.load_meta()

    classes = build_variant_classes(module, exact)

    current = replay_controller(module, obs, module.Native, module.CandidateA)
    if len(current) != len(daily) or not np.array_equal(current.date.to_numpy(), daily.date.to_numpy()):
        raise RuntimeError("offline current replay date mismatch")

    parity = {
        "allocation_max_abs": float(np.max(np.abs(current.allocation.to_numpy() - daily.A_allocation.astype(float).to_numpy()))),
        "nav_max_abs": float(np.max(np.abs(current.nav.to_numpy() - daily.A_nav.astype(float).to_numpy()))),
        "native_max_abs": float(np.max(np.abs(current.native_close_target.to_numpy() - daily.native_close_target.astype(float).to_numpy()))),
        "effective_native_max_abs": float(np.max(np.abs(current.effective_native.to_numpy() - daily.effective_native.astype(float).to_numpy()))),
        "reason_mismatches": int((current.close_reason.astype(str).to_numpy() != daily.A_reason.astype(str).to_numpy()).sum()),
    }
    if parity["allocation_max_abs"] > 1e-12 or parity["nav_max_abs"] > 1e-10:
        raise RuntimeError(f"offline current economic parity failed: {parity}")
    if parity["native_max_abs"] > 1e-12 or parity["effective_native_max_abs"] > 1e-12 or parity["reason_mismatches"]:
        raise RuntimeError(f"offline current state parity failed: {parity}")

    combined = pd.DataFrame({
        "date": daily.date,
        "research_selected_positions": daily.research_selected_positions,
        "shadow_equity": daily.shadow_equity.astype(float),
        "current_allocation": daily.A_allocation.astype(float),
        "current_nav": daily.A_nav.astype(float),
    })
    summaries = {
        "current": {
            "metrics": base.imp.windows(daily, "A_nav"),
            "allocation": allocation_counts(daily, "A_allocation"),
        }
    }
    for name in VARIANTS:
        ncls, ccls = classes[name]
        r = replay_controller(module, obs, ncls, ccls)
        combined[f"{name}_allocation"] = r.allocation.astype(float)
        combined[f"{name}_nav"] = r.nav.astype(float)
        combined[f"{name}_native_close_target"] = r.native_close_target.astype(float)
        combined[f"{name}_close_reason"] = r.close_reason.astype(str)
        summaries[name] = {
            "metrics": base.imp.windows(combined, f"{name}_nav"),
            "allocation": allocation_counts(combined, f"{name}_allocation"),
            "same_tape_delta_vs_current": pair_delta(combined, f"{name}_allocation", "current_allocation"),
        }

    combined.to_csv(outdir / "ablation-daily.csv", index=False)
    sys.modules.pop(modname, None)
    return {
        "offline_current_replay_parity": parity,
        "tracks": summaries,
        "contract": {
            "research_only": True,
            "production_code_modified": False,
            "wealth_core_economics_modified": False,
            "current_sentinel_modified": False,
            "future_data": False,
            "baseline_path_access": False,
            "all_variants_use_same_wealth_core_tape": True,
            "one_component_changed_per_variant": True,
            "variant_names": list(VARIANTS),
        },
    }

def resolve_v6_runner() -> Path:
    raw = os.environ.get("STATE_ABLATION_V6_RUNNER")
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
    exact_cache = {"src": None}

    def patched_build(control_source: Path, median_overlay: Path) -> str:
        exact = original_build(control_source, median_overlay)
        if base.sha(exact.encode()) != EXPECTED_V6_SELECTED_SOURCE_SHA256:
            raise RuntimeError("exact V6 source authority mismatch")
        exact_cache["src"] = exact
        instrumented = telemetry_source(exact)
        base.timing_guard(instrumented)
        return instrumented

    def patched_execute(src: str, outdir: Path, tag: str, keep_raw: bool = False) -> dict:
        exact = exact_cache["src"]
        if exact is None:
            raise RuntimeError("exact selected source cache unavailable")
        result = original_execute(src, outdir, tag, keep_raw)
        result["state_component_ablation"] = offline_variant_analysis(base, exact, src, outdir)
        return result

    base.build_selected = patched_build
    base.execute = patched_execute
    base.SCHEMA = SCHEMA
    base.SYSTEM = "Wealth Core V5 + Sentinel EX3 V6 state-component ablation"
    base.UNIVERSE_CASES = [("drop_01pct_seed11", .01, 11)]
    return base.main()

if __name__ == "__main__":
    raise SystemExit(main())
