"""Falsify checkpoint and measurement guards only in temporary source copies."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    test = root / "tests/sentinel/test_resumable_historical_replay.py"
    checkpoint_test = "test_checkpoint_roundtrip_preserves_production_state_and_detects_corruption"
    action_test = "test_applied_action_evidence_is_immutable_and_future_evidence_cannot_be_used_early"
    cases = [
        ("july_baseline", 'result = {"base": str(nav)', 'result = {"base": "100000"',
         "test_january_formation_does_not_reset_book_or_enter_july_return"),
        ("checkpoint_bytes", 'if sha256(path) != pointer["sha256"]:', 'if False:', checkpoint_test),
        ("checkpoint_binding", 'if packet["binding"] != binding:', 'if False:', checkpoint_test),
        ("state_commitment", 'if state.state_hash != packet["state_sha256"] or state.last_processed_session != pointer["last_session"]:',
         'if False:', checkpoint_test),
        ("past_action_change", 'if any(by_id.get(key) != row for key, row in applied.items()):',
         'if False:', action_test),
        ("future_action", 'row["known_by"] > row["effective_session"]', 'False', action_test),
    ]
    results = []
    for name, before, after, selector in cases:
        with tempfile.TemporaryDirectory() as temp:
            tmp = Path(temp)
            package = tmp / "research/bounded_20y"
            shutil.copytree(Path(__file__).parent, package)
            source = package / "january.py"
            text = source.read_text(encoding="utf-8")
            if text.count(before) != 1:
                raise AssertionError("mutation seam changed: " + name)
            source.write_text(text.replace(before, after), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                str(test)+"::"+selector], cwd=tmp, env={**os.environ,
                "PYTHONPATH": os.pathsep.join(map(str, (tmp, root, root/"shared")))},
                capture_output=True, text=True, timeout=60)
            killed = result.returncode == 1 and "1 failed" in result.stdout
            results.append({"name": name, "killed": killed, "exit_code": result.returncode})
            if not killed:
                print(result.stdout+result.stderr)
    print(json.dumps(results, indent=2))
    return 0 if all(r["killed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
