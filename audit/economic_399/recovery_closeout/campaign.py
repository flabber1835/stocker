"""Require green acceptance, then assertion failures at named broken contracts.

Only run in the disposable container checkout. Each mutation is restored before
the next case; test errors, collection failures and skips never count as detection.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


COMPOUND = ("tests/sentinel/test_historical_recovery_process_death.py::"
            "test_killed_sender_absence_and_late_fill_keep_original_identity"
            "[accepted_before_ack_commit-new-close]")
ACCEPTANCE = [
    "tests/sentinel/test_historical_recovery_process_death.py",
    "tests/sentinel/test_historical_cycle_recovery.py",
    "tests/sentinel/test_execution_callback_death.py",
    "tests/sentinel/test_unknown_absence_finality.py",
    "tests/sentinel/test_process_death_recovery.py",
    "tests/sentinel/test_strict_recovery_predecessor.py",
    "tests/sentinel/test_planless_action_units.py",
    "tests/sentinel/test_p0_recovery_and_staleness.py",
    "tests/sentinel/test_recovery_numeric_identity.py",
    "tests/sentinel/test_recovery_capability_boundary.py",
    "tests/sentinel/test_automation_runtime.py::test_newly_rejected_submit_requires_read_only_recovery",
    "tests/sentinel/test_automation_runtime.py::test_adopted_old_generation_recovery_never_loads_stale_plan",
    "tests/sentinel/test_automation_runtime.py::test_old_generation_grant_is_read_only_recovery_only",
]
MUTANTS = [
    ("send-before-durable-pending", "sentinel/execution/executor.py",
     "    journal.save_command(conn, pending, previous=command.state)",
     "    pass  # deliberately remove pre-transport durability",
     COMPOUND, "assert retained[0].state is expected"),
    ("absence-as-terminal", "sentinel/execution/reconcile.py",
     "            # Absent current reads do not settle an indeterminate request.",
     "            else:\n                command = command.transition(CommandState.CANCELLED)\n"
     "            # Deliberately manufacture request finality from absence.",
     COMPOUND, "DID NOT RAISE"),
    ("reinterpret-old-shadow-target", "sentinel/paper/recovery.py",
     "and str(plan.decision_session) < str(feed_inputs.frontier(conn, current))",
     "and False",
     COMPOUND, "different decision closes"),
    ("forget-positive-fill-commit", "sentinel/execution/reconcile.py",
     "            journal.save_command(conn, command, previous=before_state)",
     "            if command.state is not CommandState.FILLED:\n"
     "                journal.save_command(conn, command, previous=before_state)",
     COMPOUND, "assert durable[0].state is CommandState.FILLED"),
    ("forget-command-action-basis", "sentinel/paper/targets.py",
     "        start = min(start, row[0])", "        start = max(start, row[0])",
     "tests/sentinel/test_planless_action_units.py::"
     "test_planless_retired_history_preserves_held_and_exited_units[False-1-AAA]",
     "assert actions(security) == 6"),
    ("remove-predecessor-fence", "sentinel/execution/recovered_order_policy.py",
     "        if _takeover_epoch(conn) > 1:", "        if _takeover_epoch(conn) > 999:",
     "tests/sentinel/test_strict_recovery_predecessor.py::test_fresh_process_strict_policy[restore]",
     "restored namespace must be fenced"),
]


def run(name, selections):
    with tempfile.TemporaryDirectory(prefix="recovery-junit-") as temp:
        report = Path(temp) / "results.xml"
        command = [sys.executable, "-m", "pytest", *selections, "-q", "-ra",
                   "--tb=short", "--show-capture=no", "-p", "no:cacheprovider",
                   f"--junitxml={report}"]
        print(f"CAMPAIGN {name}: {command!r}", flush=True)
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=600)
        print(result.stdout, flush=True)
        assert report.exists(), f"{name}: missing test evidence"
        cases = ET.parse(report).findall(".//testcase")
        assert cases and not any(c.find("error") is not None or
                                 c.find("skipped") is not None for c in cases), (
                                     f"{name}: errors/skips are not acceptance")
        return result, cases


def main():
    assert Path.cwd() == Path("/tmp/repo"), "disposable offline container only"
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    assert mode in {"all", "acceptance", "mutations"}
    # Even mutation-only runs first establish green controls for their selectors.
    selection = ACCEPTANCE if mode != "mutations" else list(dict.fromkeys(
        mutation[4] for mutation in MUTANTS))
    result, cases = run("green-controls", selection)
    assert result.returncode == 0 and all(c.find("failure") is None for c in cases)
    if mode == "acceptance":
        return
    for name, filename, before, after, selector, signal in MUTANTS:
        path = Path(filename)
        original = path.read_bytes()
        source = original.decode()
        assert source.count(before) == 1, f"{name}: mutation seam changed"
        try:
            changed = source.replace(before, after)
            compile(changed, filename, "exec")
            path.write_text(changed)
            result, cases = run(name, [selector])
            assert result.returncode == 1 and len(cases) == 1
            failure = cases[0].find("failure")
            assert failure is not None and signal in (failure.text or ""), (
                f"{name}: intended contract assertion did not detect mutant")
            print(f"DETECTED {name}", flush=True)
        finally:
            path.write_bytes(original)
    print(f"DETECTED {len(MUTANTS)}/{len(MUTANTS)} recovery mutants", flush=True)


if __name__ == "__main__":
    main()
