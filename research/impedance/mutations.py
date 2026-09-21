"""Isolated in-memory falsifiers. Production files are never rewritten."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys


CASES = {
    "ignore_damage_acceleration": "test_saturation_has_independent_bounded_fraction_oracle",
    "retain_confirmation_forever": "test_phase_memory_repairs_only_bounded_delay",
}


def child(name):
    import pytest
    from sentinel.controller import champion_frozen
    from . import study
    if name == "ignore_damage_acceleration":
        source = inspect.getsource(champion_frozen)
        old = "(ddam5 >= FAST['ddam5'])"
        assert source.count(old) == 1
        namespace = {}
        exec(compile(source.replace(old, "True"), "<native-delta-mutant>", "exec"), namespace)
        study.Native = namespace["Native"]
    else:
        source = inspect.getsource(study.entry_probes)
        old = "(history + [(acceleration, volatility)])[-5:]"
        assert source.count(old) == 1
        namespace = dict(study.__dict__)
        exec(compile(source.replace(old, "history + [(acceleration, volatility)]"), "<memory-mutant>", "exec"), namespace)
        study.entry_probes = namespace["entry_probes"]
    return int(pytest.main(["research/impedance/test_study.py::" + CASES[name],
                           "-q", "-p", "no:cacheprovider"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=CASES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    if args.output is None:
        parser.error("--output is required for the parent run")
    results = []
    for name, test in CASES.items():
        proc = subprocess.run([sys.executable, "-m", "research.impedance.mutations", "--child", name],
                              text=True, capture_output=True, check=False)
        # Exit 1 is an assertion failure. Collection/import errors are not kills.
        killed = proc.returncode == 1 and "1 failed" in proc.stdout
        results.append({"mutant": name, "test": test, "killed": killed,
                        "returncode": proc.returncode, "output": proc.stdout + proc.stderr})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps([{k:v for k,v in r.items() if k != "output"} for r in results], indent=2))
    return 0 if all(r["killed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
