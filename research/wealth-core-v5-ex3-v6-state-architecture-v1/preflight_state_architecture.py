#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

import run_state_architecture as arch


CURRENT_NATIVE_CALL = "native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))"
CURRENT_A_CALL = "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
BOUNDED_CALL = "b_d,b_reason=cb.step(_arch_ob,dd,recent_r20,recent_r40,spy20,r20,date>=START)"
STATELESS_CALL = "c_d,c_reason,c_native=stateless_step(_arch_ob,dd,recent_r20,recent_r40,spy20,r20,date>=START)"
APPLY_MARKER = "navs[kname],tc=apply_overlay"
ROW_MARKER = "rows.append({'date':date"
STATELESS_PENDING = "pend['control']=c_d"


def load(path: Path):
    spec = importlib.util.spec_from_file_location("state_arch_v6_runner_preflight", path)
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


def source_invariants(exact: str, patched: str) -> dict:
    if hashlib.sha256(exact.encode()).hexdigest() != arch.EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("preflight exact V6 source hash mismatch")

    # Independent byte-preservation proof for the authoritative current controller.
    native_exact = arch.block(exact, "class Native:", "class ControlLDRC:")
    native_patched = arch.block(patched, "class Native:", "class ControlLDRC:")
    a_exact = arch.block(exact, "class CandidateA:", "class CandidateB")
    a_patched = arch.block(patched, "class CandidateA:", "def _arch_replay")
    if native_exact != native_patched:
        raise RuntimeError("preflight: authoritative Native block changed")
    if a_exact != a_patched:
        raise RuntimeError("preflight: authoritative CandidateA block changed")

    order = {
        "native_call": require_once(patched, CURRENT_NATIVE_CALL, "current Native call"),
        "current_a_call": require_once(patched, CURRENT_A_CALL, "current CandidateA call"),
        "bounded_call": require_once(patched, BOUNDED_CALL, "bounded-state call"),
        "stateless_call": require_once(patched, STATELESS_CALL, "stateless call"),
        "apply": require_once(patched, APPLY_MARKER, "allocation application"),
        "row": require_once(patched, ROW_MARKER, "measurement row"),
        "authoritative_pending": require_once(patched, arch.OLD_PENDING, "authoritative pending marker"),
        "stateless_pending": require_once(patched, STATELESS_PENDING, "stateless pending marker"),
    }
    expected_order = [
        "native_call", "current_a_call", "bounded_call", "stateless_call",
        "apply", "row", "authoritative_pending", "stateless_pending",
    ]
    if [order[k] for k in expected_order] != sorted(order[k] for k in expected_order):
        raise RuntimeError(f"preflight: causal source order changed: {order}")

    for forbidden in ("eff['A']=a_d", "eff['B']=b_d", "eff['control']=c_d"):
        if forbidden in patched:
            raise RuntimeError(f"preflight: illegal same-session exposure write: {forbidden}")

    if "if len(self.history)>self.window:" not in arch.ARCHITECTURE_BLOCK:
        raise RuntimeError("preflight: bounded history trim missing")
    if "del self.history[:-self.window]" not in arch.ARCHITECTURE_BLOCK:
        raise RuntimeError("preflight: bounded history truncation missing")
    if "_arch_replay([(ob,wcdd,recent_r20,recent_r40,spy20,wc_r20,bool(measured))])" not in arch.ARCHITECTURE_BLOCK:
        raise RuntimeError("preflight: stateless one-record reconstruction missing")
    for forbidden in ("baseline_path", "baseline_holdings", "future_return", "future_data"):
        if forbidden in arch.ARCHITECTURE_BLOCK:
            raise RuntimeError(f"preflight: forbidden treatment dependency: {forbidden}")

    return {
        "exact_selected_source_sha256": hashlib.sha256(exact.encode()).hexdigest(),
        "treated_source_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        "current_native_byte_preserved": True,
        "current_candidate_a_byte_preserved": True,
        "current_decision_before_application": order["current_a_call"] < order["apply"],
        "treatments_decide_before_application": order["bounded_call"] < order["apply"] and order["stateless_call"] < order["apply"],
        "all_pending_writes_after_measurement_row": order["row"] < order["authoritative_pending"] < order["stateless_pending"],
        "no_same_session_exposure_write": True,
    }


def synthetic_state_invariants(exact: str) -> dict:
    native = arch.block(exact, "class Native:", "class ControlLDRC:")
    cand_a = arch.block(exact, "class CandidateA:", "class CandidateB")
    ns = {
        "np": np,
        "finite": lambda x: x is not None and np.isfinite(x),
        "ORD_DD": -0.155,
        "FAST": {"dd": -.10, "dam": .88, "green": .20, "r5": -.05, "r10": -.08, "ddam5": .30, "volacc": .04, "spy20": -.01, "r10confirm": -.10},
        "SLOW": {"dur": 30, "ret": -.02, "r40": -.03, "dam": .75, "green": .25},
        "LDRC_DD": -.10,
        "LDRC_R20": -.085,
        "LDRC_CEIL": .55,
        "LDRC_REC": 8,
        "LDRC_V": .11,
    }
    exec(native + "\n" + cand_a + "\n" + arch.ARCHITECTURE_BLOCK, ns)
    CandidateB = ns["CandidateB"]
    stateless_step = ns["stateless_step"]

    neutral_ob = (0.0, 0.01, 0.01, 0.01, 0.01, 0.20, 0.80, 0.0, 0.01, 0.0, 0, 100.0)
    stress_ob = (-0.20, -0.10, -0.12, -0.15, -0.12, 0.95, 0.00, 0.50, -0.05, 0.10, 0, 80.0)
    neutral_args = (0.0, 0.01, 0.01, 0.01, 0.01, True)
    stress_args = (-0.20, -0.15, -0.12, -0.05, -0.15, True)

    s1 = stateless_step(neutral_ob, *neutral_args)
    _ = stateless_step(stress_ob, *stress_args)
    s2 = stateless_step(neutral_ob, *neutral_args)
    if s1 != s2:
        raise RuntimeError(f"preflight: stateless output retained cross-call state: {s1} != {s2}")

    b_left = CandidateB(); b_right = CandidateB()
    for _ in range(40):
        b_left.step(stress_ob, *stress_args)
        b_right.step(neutral_ob, *neutral_args)
    left = right = None
    for _ in range(arch.STATE_MIN_WINDOW):
        left = b_left.step(neutral_ob, *neutral_args)
        right = b_right.step(neutral_ob, *neutral_args)
    if len(b_left.history) != arch.STATE_MIN_WINDOW or len(b_right.history) != arch.STATE_MIN_WINDOW:
        raise RuntimeError("preflight: bounded controller exceeded configured memory")
    if b_left.history != b_right.history:
        raise RuntimeError("preflight: prefixes older than the memory bound still affect retained observations")
    if left != right:
        raise RuntimeError(f"preflight: prefixes older than the memory bound still affect output: {left} != {right}")

    allowed = (0.0, .55, .65, 1.0)
    for label, value in (("stateless_neutral", s1[0]), ("bounded_after_common_suffix", left[0])):
        if not any(abs(float(value) - a) <= 1e-12 for a in allowed):
            raise RuntimeError(f"preflight: {label} emitted invalid exposure {value}")

    return {
        "stateless_cross_call_memory": False,
        "bounded_memory_sessions": arch.STATE_MIN_WINDOW,
        "older_prefix_changes_output_after_full_common_suffix": False,
        "synthetic_outputs_in_allowed_domain": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", required=True, type=Path)
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    args = ap.parse_args()

    base = load(args.runner.resolve())
    if base.SELECTED != arch.EXPECTED_V6:
        raise RuntimeError(f"wrong generated V6 config: {base.SELECTED}")
    exact = base.build_selected(args.control_source.resolve(), args.median_overlay.resolve())
    if base.sha(exact.encode()) != arch.EXPECTED_V6_SELECTED_SOURCE_SHA256:
        raise RuntimeError("exact V6 selected-source authority mismatch")
    patched = arch.treatment_source(exact)
    base.timing_guard(patched)

    result = {
        "schema": "research.wealth-core-v5-ex3-v6-state-architecture-v1/preflight-1",
        "status": "PASS",
        "source_invariants": source_invariants(exact, patched),
        "state_invariants": synthetic_state_invariants(exact),
        "reviewed_authorities": {
            "published_v6": arch.MAIN_V6_AUTHORITY,
            "replay_harness": arch.HARNESS_AUTHORITY,
            "selected_source_sha256": arch.EXPECTED_V6_SELECTED_SOURCE_SHA256,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
