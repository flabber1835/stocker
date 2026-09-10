#!/usr/bin/env python3
from __future__ import annotations

import ast
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


def main() -> int:
    for path in (RUNNER, PATCHER, HERE / "aggregate.py"):
        if not path.exists():
            raise RuntimeError(f"missing preflight input: {path}")
        compile(path.read_text(), str(path), "exec")

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

    new_b = str(pv["NEW_B"])
    btree = ast.parse(new_b, filename="<CandidateB-treatment>")
    classes = [n for n in btree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1 or classes[0].name != "CandidateB":
        raise RuntimeError("treatment must define exactly one CandidateB")
    bases = classes[0].bases
    if len(bases) != 1 or not isinstance(bases[0], ast.Name) or bases[0].id != "CandidateA":
        raise RuntimeError("CandidateB must inherit exact CandidateA")
    if new_b.count("super().step(") != 1:
        raise RuntimeError("CandidateB must delegate authoritative economics exactly once")
    if "neutral_streak>=LDRC_REC" not in new_b:
        raise RuntimeError("REC8 convergence horizon is not inherited from LDRC_REC")
    if "FULL_RISK_CERTIFIED_CONVERGENCE_REC8" not in new_b:
        raise RuntimeError("convergence release marker missing")
    for forbidden in ("LDRC_DD=", "LDRC_R20=", "LDRC_V=", "LDRC_CEIL=", "0.55", "0.65"):
        if forbidden in new_b:
            raise RuntimeError(f"treatment redefines frozen economics: {forbidden}")

    patcher = PATCHER.read_text()
    guards = (
        "if candidate_a_block(out) != a_before:",
        'raise RuntimeError("CandidateA changed while inserting convergence treatment")',
        "base.timing_guard(patched)",
        'if "eff[\'B\']=b_d" in out:',
        "base.sha(exact.encode()) != EXPECTED_V6_SELECTED_SOURCE_SHA256",
    )
    for guard in guards:
        if guard not in patcher:
            raise RuntimeError(f"required treatment-isolation guard missing: {guard}")

    print("preflight PASS")
    print("selected", EXPECTED_SELECTED)
    print("selected_source_sha256", EXPECTED_SELECTED_SOURCE_SHA256)
    print("candidate_b_inherits_candidate_a", True)
    print("authoritative_candidate_a_byte_guard", True)
    print("causal_timing_guard", True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
