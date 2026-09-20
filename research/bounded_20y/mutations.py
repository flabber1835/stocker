"""Run replay-adapter falsifiers in disposable copies, never edit production."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    test = root / "tests/sentinel/test_bounded_historical_performance.py"
    cases = [
        ("source_binding", "supplement.py",
         'if any(original.get(k) != v for k, v in required.items()):', 'if False:',
         'test_rsas_supplement_refuses_wrong_or_duplicate_source[id]'),
        ("source_uniqueness", "supplement.py", 'if len(matches) != 1:', 'if False:',
         'test_rsas_supplement_refuses_wrong_or_duplicate_source[duplicate]'),
        ("settlement_cash", "supplement.py", '"cash_per_share": "28.00"',
         '"cash_per_share": "27.00"',
         'test_rsas_supplement_resolves_actual_production_claim_for_28_dollars_per_share'),
        ("projection_guard", "run.py", 'projected <= max_seconds', 'True',
         'test_budget_projects_runtime_and_refuses_over_budget_continuation'),
        ("deadline_guard", "run.py", 'if elapsed >= max_seconds:', 'if False:',
         'test_budget_projects_runtime_and_refuses_over_budget_continuation'),
    ]
    results = []
    for name, file, before, after, selector in cases:
        with tempfile.TemporaryDirectory(prefix="bounded-replay-mutant-") as temp:
            tmp = Path(temp)
            package = tmp / "research/bounded_20y"
            shutil.copytree(Path(__file__).parent, package)
            source = package / file
            content = source.read_text(encoding="utf-8")
            if content.count(before) != 1:
                raise AssertionError("mutation seam changed: " + name)
            source.write_text(content.replace(before, after), encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": os.pathsep.join(
                map(str, (tmp, root, root / "shared")))}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 str(test) + "::" + selector], cwd=tmp, env=env,
                capture_output=True, text=True, timeout=60)
            killed = result.returncode == 1 and "1 failed" in result.stdout
            results.append({"mutation": name, "killed": killed,
                            "exit_code": result.returncode})
            if not killed:
                print(result.stdout + result.stderr)
    print(json.dumps(results, indent=2))
    return 0 if all(r["killed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
