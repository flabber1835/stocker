"""Pytest evidence plugin for required suites; required skips fail CI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


def acceptance(*, collected, passed, failures, skipped, expected_failures, exitstatus):
    accounted = set(passed) | set(failures) | set(skipped) | set(expected_failures)
    return (int(exitstatus) == 0 and bool(collected) and not failures and not skipped
            and set(collected) == accounted)


class Evidence:
    def __init__(self):
        self.collected, self.deselected = [], []
        self.passed, self.failures, self.skipped, self.expected_failures = {}, {}, {}, {}

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failures[report.nodeid] = str(report.longrepr)
        elif report.skipped:
            destination = self.expected_failures if hasattr(report, "wasxfail") else self.skipped
            destination[report.nodeid] = str(report.longrepr)
        elif report.when == "call" and report.passed:
            self.passed[report.nodeid] = report.duration

    def pytest_sessionfinish(self, session, exitstatus):
        result = vars(self).copy()
        passed = acceptance(collected=self.collected, passed=self.passed, failures=self.failures,
            skipped=self.skipped, expected_failures=self.expected_failures, exitstatus=exitstatus)
        result.update(
            verdict="PASS" if passed else "FAIL",
            pytest_exitstatus=int(exitstatus),
            commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            tree=subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
        )
        root = Path(os.environ["INTERNAL_STATE_SUITE_EVIDENCE"])
        root.mkdir(parents=True, exist_ok=True)
        identity = " ".join(map(str, session.config.args))
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
        name = Path(session.config.args[0]).name.replace(".", "_") + "-" + suffix + ".json"
        # Exclusive creation prevents a stale passing report being reused.
        with (root / name).open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
        if not passed:
            session.exitstatus = 1


def pytest_configure(config):
    if "INTERNAL_STATE_SUITE_EVIDENCE" not in os.environ:
        raise RuntimeError("suite evidence path is required")
    config.pluginmanager.register(Evidence(), "internal-state-suite-evidence")
