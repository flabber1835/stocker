"""Bounded financial falsification and single-child compatibility certificate.

Run inside the pinned test image; /baseline/spinoffs.py is extracted from the
recorded main commit. Evidence is written to --output, never into runtime state.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sentinel/core/spinoffs.py"
TEST = "tests/sentinel/test_in_kind_distributions.py"
BASE = "f3e60671b525219287231d517ad6945e6ef2b649"

# Each replacement is required to match exactly once. A passing baseline is
# required, followed by an assertion-bearing failure of the intended test.
MUTANTS = {
    "parent_only_uniqueness": (
        "key = (event.session, event.parent_security_id, event.child_security_id)",
        "key = (event.session, event.parent_security_id)",
        "test_multiple_children_independent_financial_oracle"),
    "duplicate_guard_removed": ("if key in seen:", "if False:",
        "test_duplicate_child_refuses_even_with_distinct_source"),
    "source_id_creates_second_entitlement": (
        "key = (event.session, event.parent_security_id, event.child_security_id)",
        "key = (event.session, event.parent_security_id, event.child_security_id, event.source_row_id)",
        "test_duplicate_child_refuses_even_with_distinct_source"),
    "opening_ticker_guard_removed": (
        "if (parent_bar.ticker.upper() != event.parent_ticker.upper()\n                or child_bar.ticker.upper() != event.child_ticker.upper()):",
        "if False:", "test_invalid_later_sibling_is_atomic"),
    "ambiguous_bar_guard_removed": (
        "if (event.parent_security_id in ambiguous_bars\n                or event.child_security_id in ambiguous_bars):",
        "if False:", "test_ambiguous_opening_identity_refuses_atomically"),
    "second_child_omitted_from_basis": (
        'math.fsum(group["child_values"])', 'group["child_values"][0]',
        "test_multiple_children_independent_financial_oracle"),
    "basis_applied_twice": (
        'parent.entry_split_adjusted_price *= group["reference_scale"]',
        'parent.entry_split_adjusted_price *= group["reference_scale"] ** 2',
        "test_multiple_children_independent_financial_oracle"),
    "holder_rounding_broken": (
        "whole = entitlement.numerator // entitlement.denominator",
        "whole = sum((Fraction(str(p.current_shares)) * ratio).__floor__() for p in parents)",
        "test_multiple_children_round_each_at_holder_boundary"),
    "whole_share_fees_omitted": (
        "whole_proceeds = exit_proceeds(float(whole), child_open, config)",
        "whole_proceeds = float(whole) * child_open",
        "test_multiple_children_independent_financial_oracle"),
    "fractional_payout_omitted": (
        "cil_proceeds = float(fractional * cil) if cil is not None else 0.0",
        "cil_proceeds = 0.0", "test_lvnta_two_share_fractional_entitlements"),
    "canonical_order_removed": (
        'plans.sort(key=lambda plan: (plan["event"].session,\n                                plan["event"].parent_security_id,\n                                plan["event"].child_security_id))',
        "pass", "test_sibling_order_and_serialized_restart_are_identical"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def differential(baseline):
    spec = importlib.util.spec_from_file_location("certification_old_spinoffs", baseline)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    sys.path.insert(0, str(ROOT / "tests/sentinel"))
    import test_in_kind_distributions as t
    import sentinel.core.spinoffs as new
    from dataclasses import asdict
    cases = []
    for shares in (1, 2, 3, 105, 1000):
        for ratio in ("1", "1/3", "1/2", "7/5"):
            for episodes in (1, 2):
                outputs = []
                for module in (old, new):
                    state, ledger = t.held_state(shares=shares), t.Ledger()
                    if episodes == 2:
                        state.slots[1].occupied_by = "P:ADP"
                        state.episodes[1] = replace(state.episodes[0], slot_id=1, source_lots=[])
                    event = module.SpinoffDistribution(**asdict(t.complete_event(
                        child_shares_per_parent=ratio, cash_in_lieu_price="30")))
                    audit = module.apply_supported_entitlements(state, [event], bars=t.bars(),
                        ledger=ledger, config=t.WealthCoreConfig())
                    outputs.append(json.dumps((state.to_dict(), ledger.to_dict(), audit), sort_keys=True))
                assert outputs[0] == outputs[1], (shares, ratio, episodes)
                cases.append({"shares": shares, "ratio": ratio, "episodes": episodes,
                              "output_sha256": hashlib.sha256(outputs[0].encode()).hexdigest()})
    return cases


def run_tests(output, mutant=None):
    label = mutant or "baseline"
    junit = output / (label + ".xml")
    command = [sys.executable, str(Path(__file__).resolve()), "--child", label,
               "--junit", str(junit)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (output / (label + ".log")).write_text(result.stdout + result.stderr)
    tree = ET.parse(junit)
    cases = tree.findall(".//testcase")
    failures = [c for c in cases if c.find("failure") is not None]
    assert cases and not tree.findall(".//error") and not tree.findall(".//skipped"), label
    if mutant:
        assert result.returncode == 1 and failures, (label, result.returncode)
        target = MUTANTS[mutant][2]
        assert all(target in c.attrib["name"] for c in failures), label
    else:
        assert result.returncode == 0 and not failures, label
    return {"name": label, "exit_code": result.returncode, "tests": len(cases),
            "failed": [c.attrib["name"] for c in failures],
            "junit_sha256": digest(junit), "log_sha256": digest(output / (label + ".log"))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--child")
    parser.add_argument("--junit")
    args = parser.parse_args()
    if args.child:
        import pytest
        if args.child != "baseline":
            import sentinel.core.spinoffs as module
            before, after, test = MUTANTS[args.child]
            source = SOURCE.read_text()
            assert source.count(before) == 1, args.child
            exec(compile(source.replace(before, after), str(SOURCE), "exec"), module.__dict__)
            target = TEST + "::" + test
        else:
            target = TEST
        raise SystemExit(pytest.main([target, "-q", "-p", "no:cacheprovider", "--junitxml", args.junit]))
    assert args.output and args.baseline and args.baseline_sha256
    assert digest(args.baseline) == args.baseline_sha256
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "bounded_multi_child_ownership_financial_certification",
              "baseline_commit": BASE, "baseline_source_sha256": digest(args.baseline),
              "source_sha256": digest(SOURCE), "test_sha256": digest(ROOT / TEST),
              "runner_sha256": digest(__file__)}
    report["baseline"] = run_tests(args.output)
    report["single_child_byte_equivalence"] = differential(args.baseline)
    report["mutants"] = [run_tests(args.output, name) for name in MUTANTS]
    report["result"] = "PASS"
    (args.output / "certificate.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": "PASS", "baseline_tests": report["baseline"]["tests"],
                      "single_child_cases": len(report["single_child_byte_equivalence"]),
                      "killed_mutants": len(report["mutants"])}))


if __name__ == "__main__":
    main()
