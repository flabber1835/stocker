#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent / "wealth-core-v5-sentinel-ex3-v6-adversarial-v1" / "run_adversarial_v6.generated.py"
PATCHER = HERE / "run_convergence.py"
EXPECTED_SELECTED = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}
EXPECTED_SELECTED_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"


def literals(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    return out


def class_block(src: str, name: str, next_name: str) -> str:
    start = src.index(f"class {name}:")
    end = src.index(f"class {next_name}", start)
    return src[start:end]


def main() -> int:
    for path in (RUNNER, PATCHER, HERE / "aggregate.py"):
        if not path.exists():
            raise RuntimeError(f"missing preflight input: {path}")
        compile(path.read_text(), str(path), "exec")

    runner = RUNNER.read_text()
    rv = literals(RUNNER)
    if rv.get("SELECTED") != EXPECTED_SELECTED:
        raise RuntimeError(f"wrong generated V6 config: {rv.get('SELECTED')}")

    pv = literals(PATCHER)
    if pv.get("EXPECTED_V6_SELECTED_SOURCE_SHA256") != EXPECTED_SELECTED_SOURCE_SHA256:
        raise RuntimeError("research patcher is not pinned to the reviewed V6 selected-source hash")

    required = ("OLD_B", "NEW_B", "OLD_CALL", "NEW_CALL", "A_CALL", "PENDING")
    missing = [x for x in required if x not in pv]
    if missing:
        raise RuntimeError(f"patcher literal contract missing: {missing}")

    old_b = str(pv["OLD_B"]); new_b = str(pv["NEW_B"])
    old_call = str(pv["OLD_CALL"]); new_call = str(pv["NEW_CALL"])
    a_call = str(pv["A_CALL"]); pending = str(pv["PENDING"])
    if runner.count(old_b) != 1 or runner.count(old_call) != 1:
        raise RuntimeError("generated V6 treatment seams are not unique")
    if runner.count(a_call) != 1 or runner.count(pending) != 1:
        raise RuntimeError("generated V6 control/timing seams are not unique")

    a_before = class_block(runner, "CandidateA", "CandidateB")
    if "recent_r40>-0.04" not in a_before:
        raise RuntimeError("CandidateA is not the reviewed r40_m04_rec8 controller")

    patched = runner.replace(old_b, new_b, 1).replace(old_call, new_call, 1)
    compile(patched, "<preflight-patched-v6>", "exec")
    a_after = class_block(patched, "CandidateA", "CandidateB")
    if a_after != a_before:
        raise RuntimeError("CandidateA changed during treatment insertion")
    if "class CandidateB(CandidateA):" not in patched or "super().step(" not in patched:
        raise RuntimeError("treatment does not inherit the exact authoritative controller")
    if patched.count(a_call) != 1 or patched.count(new_call) != 1 or patched.count(pending) != 1:
        raise RuntimeError("paired controller call/timing contract changed")
    if patched.index(a_call) >= patched.index(pending) or patched.index(new_call) >= patched.index(pending):
        raise RuntimeError("a controller close decision can reach same-session allocation")
    if "eff['A']=a_d" in patched or "eff['B']=b_d" in patched:
        raise RuntimeError("same-session allocation mutant detected")
    if "FULL_RISK_CERTIFIED_CONVERGENCE_REC8" not in patched:
        raise RuntimeError("research convergence release marker missing")

    print("preflight PASS")
    print("selected", EXPECTED_SELECTED)
    print("selected_source_sha256", EXPECTED_SELECTED_SOURCE_SHA256)
    print("candidate_a_sha256", hashlib.sha256(a_before.encode()).hexdigest())
    print("patched_candidate_a_identical", True)
    print("causal_next_session_pairing", True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
