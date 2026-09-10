#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

import run_state_component_ablation as abl


def load(path: Path):
    spec = importlib.util.spec_from_file_location("state_component_v6_runner_preflight", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def require_once(text: str, marker: str, label: str) -> int:
    n = text.count(marker)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, saw {n}")
    return text.index(marker)


def _class_test_namespace(exact: str):
    ns = {
        "np": np,
        "finite": lambda x: x is not None and np.isfinite(x),
        "ORD_DD": -0.155,
        "FAST": {"dd": -.10, "dam": .88, "green": .20, "r5": -.05, "r10": -.08,
                 "ddam5": .30, "volacc": .04, "spy20": -.01, "r10confirm": -.10},
        "SLOW": {"dur": 30, "ret": -.02, "r40": -.03, "dam": .75, "green": .25},
        "LDRC_DD": -.10,
        "LDRC_R20": -.085,
        "LDRC_CEIL": .55,
        "LDRC_REC": 8,
        "LDRC_V": .11,
    }
    native = abl.block(exact, "class Native:", "class ControlLDRC:")
    cand = abl.block(exact, "class CandidateA:", "class CandidateB")
    exec(compile(native + "\n" + cand, "<authoritative-classes>", "exec"), ns)
    for text in list(abl._native_variant_sources(exact).values()) + list(abl._candidate_variant_sources(exact).values()):
        exec(compile(text, "<ablation-class>", "exec"), ns)
    return ns


def source_invariants(exact: str, instrumented: str) -> dict:
    if hashlib.sha256(exact.encode()).hexdigest() != abl.EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("exact selected-source hash mismatch")

    native_exact = abl.block(exact, "class Native:", "class ControlLDRC:")
    native_inst = abl.block(instrumented, "class Native:", "class ControlLDRC:")
    cand_exact = abl.block(exact, "class CandidateA:", "class CandidateB")
    cand_inst = abl.block(instrumented, "class CandidateA:", "class CandidateB")
    if native_exact != native_inst:
        raise RuntimeError("telemetry instrumentation changed authoritative Native")
    if cand_exact != cand_inst:
        raise RuntimeError("telemetry instrumentation changed authoritative CandidateA")

    current_call = "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
    apply_marker = "navs[kname],tc=apply_overlay"
    pending_marker = "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
    obs_marker = "_ablation_ob_rows.append({"
    write_marker = "pd.DataFrame(_ablation_ob_rows).to_csv(OUT/'ablation-observations.csv',index=False)"
    order = {
        "current_call": require_once(instrumented, current_call, "current CandidateA call"),
        "obs": require_once(instrumented, obs_marker, "ablation observation append"),
        "apply": require_once(instrumented, apply_marker, "allocation application"),
        "pending": require_once(instrumented, pending_marker, "authoritative pending marker"),
        "write": require_once(instrumented, write_marker, "ablation telemetry write"),
    }
    if not order["current_call"] < order["obs"] < order["apply"] < order["pending"] < order["write"]:
        raise RuntimeError(f"telemetry causal ordering invalid: {order}")

    for forbidden in (
        "eff['A']=a_d",
        "eff['control']=a_d",
        "pend['A']=abl",
        "future_return",
        "baseline_path_access",
    ):
        if forbidden in instrumented:
            raise RuntimeError(f"forbidden instrumentation marker: {forbidden}")

    return {
        "exact_selected_source_sha256": hashlib.sha256(exact.encode()).hexdigest(),
        "instrumented_source_sha256": hashlib.sha256(instrumented.encode()).hexdigest(),
        "authoritative_native_byte_preserved": True,
        "authoritative_candidate_a_byte_preserved": True,
        "authoritative_timing_marker_preserved": True,
        "telemetry_after_current_decision_before_allocation_apply": True,
    }


def variant_invariants(exact: str) -> dict:
    ns = _class_test_namespace(exact)
    classes = {
        "native_base_anchor": (ns["NativeAblateBaseAnchor"], ns["CandidateA"]),
        "native_base_duration": (ns["NativeAblateBaseDuration"], ns["CandidateA"]),
        "native_slow_persistence": (ns["NativeAblateSlowPersistence"], ns["CandidateA"]),
        "native_recovery_ramp": (ns["NativeAblateRecoveryRamp"], ns["CandidateA"]),
        "ex3_episode_memory": (ns["Native"], ns["CandidateAAblateEpisodeMemory"]),
        "ex3_latch_memory": (ns["Native"], ns["CandidateAAblateLatchMemory"]),
    }
    if set(classes) != set(abl.VARIANTS):
        raise RuntimeError("variant registry mismatch")

    neutral = (0.0, 0.01, 0.01, 0.01, 0.01, 0.20, 0.80, 0.0, 0.01, 0.0, 0, 100.0)
    stress = (-0.20, -0.10, -0.12, -0.15, -0.12, 0.95, 0.00, 0.50, -0.05, 0.10, 0, 80.0)
    allowed = (0.0, .55, .65, 1.0)
    observed = {}
    for name, (ncls, ccls) in classes.items():
        n = ncls(); c = ccls()
        effective = 1.0
        pending = 1.0
        values = []
        for i in range(100):
            ob = stress if 10 <= i < 55 else neutral
            nt, _, _ = n.step(ob)
            desired, _ = c.step(nt, effective, ob[0], ob[3], ob[4], ob[8], ob[3])
            effective = pending
            pending = nt
            values.append(float(desired))
        bad = [v for v in values if not any(abs(v-a) <= 1e-12 for a in allowed)]
        if bad:
            raise RuntimeError(f"{name}: invalid allocation domain {bad[:3]}")
        observed[name] = {"min": min(values), "max": max(values), "allowed_domain": True}

    srcs = abl._native_variant_sources(exact)
    if "self.base_anchor=nav\n            if not prior_base" not in srcs["native_base_anchor"]:
        raise RuntimeError("base-anchor ablation seam missing")
    if "self.base_dur=SLOW['dur']" not in srcs["native_base_duration"]:
        raise RuntimeError("base-duration ablation seam missing")
    if "self.slow=bool(slowsig)" not in srcs["native_slow_persistence"]:
        raise RuntimeError("slow-persistence ablation seam missing")
    if "severe-state recovery returns directly to full exposure" not in srcs["native_recovery_ramp"]:
        raise RuntimeError("recovery-ramp ablation seam missing")
    csrcs = abl._candidate_variant_sources(exact)
    if "if False and self.prev_native>=1-1e-12" not in csrcs["ex3_episode_memory"]:
        raise RuntimeError("EX3 episode-memory ablation seam missing")
    if "if False and not self.latched and not cleared" not in csrcs["ex3_latch_memory"]:
        raise RuntimeError("EX3 latch-memory ablation seam missing")
    return observed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", required=True, type=Path)
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    args = ap.parse_args()

    base = load(args.runner.resolve())
    if base.SELECTED != abl.EXPECTED_V6:
        raise RuntimeError(f"wrong generated V6 config: {base.SELECTED}")
    exact = base.build_selected(args.control_source.resolve(), args.median_overlay.resolve())
    if base.sha(exact.encode()) != abl.EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("exact V6 selected-source authority mismatch")
    instrumented = abl.telemetry_source(exact)
    base.timing_guard(instrumented)

    result = {
        "schema": "research.wealth-core-v5-ex3-v6-state-component-ablation-v1/preflight-1",
        "status": "PASS",
        "source": source_invariants(exact, instrumented),
        "variants": variant_invariants(exact),
        "reviewed_authorities": {
            "published_v6": abl.MAIN_V6_AUTHORITY,
            "replay_harness": abl.HARNESS_AUTHORITY,
            "selected_source_sha256": abl.EXPECTED_V6_SELECTED_SOURCE_SHA256,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
