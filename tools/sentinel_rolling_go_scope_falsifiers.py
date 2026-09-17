"""Falsify the host's distinct rolling runtime/input proof acceptance."""
import argparse
from pathlib import Path
import subprocess
import sys

TEST = "test_rolling_go_proof_requires_supported_runtime_and_exact_input_scope"
MUTANTS = {
    "runtime_contract": ("scripts.sentinel_go_validate",
        'and proof.get("runtime_contract") == "sentinel.rolling-shadow-runtime/1"', 'and True', TEST + "[contract]"),
    "input_scope": ("scripts.sentinel_go_validate",
        'coherence.get("scope") == "ROLLING_CURRENT_INPUTS_ONLY"', 'True', TEST + "[scope]"),
    "snapshot_version": ("scripts.sentinel_go_validate",
        'and snapshot.get("data_version") == proof.get("data_version")', 'and True', TEST + "[version]"),
    "snapshot_digest": ("scripts.sentinel_go_validate",
        'and _HEX64.fullmatch(str(snapshot.get("snapshot_id") or "")) is not None', 'and True', TEST + "[snapshot]"),
    "data_only": ("scripts.sentinel_go_validate",
        'and snapshot.get("operational_go") is False', 'and True', TEST + "[authority]"),
    "cross_image_input_scope": ("scripts.sentinel_go_validate",
        'elif any(report["publication_coherence"] != runtime["publication_coherence"]',
        'elif False and any(report["publication_coherence"] != runtime["publication_coherence"]',
        "test_operational_parity_rejects_invalid_or_different_image_evidence"),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        import pytest
        _, original, replacement, test = MUTANTS[args.child]

        class MutateCollectedHost:
            def pytest_collection_modifyitems(self, items):
                # The host tests deliberately load a standalone script module.
                # Mutate that actual object after collection, not a package alias.
                module = items[0].module.go
                source = Path(module.__file__).read_text(encoding="utf-8")
                if source.count(original) != 1:
                    raise RuntimeError("mutant does not match exactly one guard")
                exec(compile(source.replace(original, replacement), module.__file__, "exec"),
                     module.__dict__)

        return pytest.main(["tests/scripts/test_sentinel_go_validate.py::" + test,
                            "-q", "-p", "no:cacheprovider"], plugins=[MutateCollectedHost()])
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, "-m", "tools.sentinel_rolling_go_scope_falsifiers",
                                 "--child", name], capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        if not killed:
            failed.append(name)
            print(result.stdout)
            print(result.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
