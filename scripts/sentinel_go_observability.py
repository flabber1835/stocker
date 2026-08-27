#!/usr/bin/env python3
"""Chatty, fail-fast observability overlay for production Sentinel GO validation.

The financial authority contract is unchanged.  This module only changes operator
visibility and certification-suite orchestration:

* safe build/test subprocess output is streamed live while still captured for
  deterministic parsing;
* commands whose raw output may contain connection or credential material emit
  colored start/heartbeat/completion status without echoing their raw output;
* certification suites run shortest-first and stop after the first failed suite;
* a bounded, sanitized failing suite/node summary is retained in test-summary.json.

The overlay is installed only by the verified GO entrypoint.  Importing this
module has no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Optional, Sequence, Tuple


RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"

CERTIFICATION_SUITE_LABELS = (
    "GO SCRIPT TESTS",
    "BACKTESTER BOUNDARY",
    "BT DATA",
    "BT ENGINE",
    "WEALTH CORE",
    "SENTINEL",
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SAFE_NODE_RE = re.compile(r"^tests/[A-Za-z0-9_./:\-\[\],=+()]+$")
_MAX_FAILURE_NODES = 12
_HEARTBEAT_SECONDS = 10.0
_INSTALLED_MARKER = "_sentinel_go_observability_installed"


def _use_color() -> bool:
    raw = str(os.environ.get("SENTINEL_GO_COLOR", "")).strip().lower()
    if raw in {"1", "true", "yes", "always"}:
        return True
    if raw in {"0", "false", "no", "never"} or os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _paint(color: str, text: str) -> str:
    return color + text + RESET if _use_color() else text


def _banner(text: str) -> None:
    print(_paint(CYAN + BOLD, "\n=== %s ===" % text), flush=True)


def _start(text: str) -> None:
    print(_paint(CYAN, "[RUN]  %s" % text), flush=True)


def _pass(text: str) -> None:
    print(_paint(GREEN, "[PASS] %s" % text), flush=True)


def _warn(text: str) -> None:
    print(_paint(YELLOW, "[WARN] %s" % text), flush=True)


def _fail(text: str) -> None:
    print(_paint(RED + BOLD, "[FAIL] %s" % text), file=sys.stderr, flush=True)


def _working(text: str, elapsed: int) -> None:
    print(_paint(YELLOW, "[WORK] %s -- still running (%ss)" % (text, elapsed)),
          flush=True)


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value or "")


def extract_failure_nodes(output: str) -> Tuple[str, ...]:
    """Return only bounded repo-relative pytest node IDs from failure summaries."""
    found = []
    for raw in _strip_ansi(output).splitlines():
        line = raw.strip()
        if not (line.startswith("FAILED ") or line.startswith("ERROR ")):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        node = parts[1].strip()
        if (len(node) <= 320 and _SAFE_NODE_RE.fullmatch(node)
                and node not in found):
            found.append(node)
        if len(found) >= _MAX_FAILURE_NODES:
            break
    return tuple(found)


def _command_label(command: Sequence[str]) -> str:
    values = [str(item) for item in command]
    if not values:
        return "subprocess"
    if values[0] == "git":
        action = values[1] if len(values) > 1 else "command"
        return "git %s" % action
    if values[:2] == ["docker", "build"]:
        try:
            tag = values[values.index("-t") + 1]
        except (ValueError, IndexError):
            tag = "image"
        return "Docker build %s" % tag
    if values[:2] == ["docker", "image"]:
        return "Docker image identity"
    if values[:2] == ["docker", "run"]:
        tests = [item for item in values if item.startswith("tests/")]
        if tests:
            return "pytest %s" % tests[0]
        return "isolated Docker probe"
    if values[:2] == ["docker", "compose"]:
        if any("SENTINEL_GO_PREPARATION=" in item for item in values):
            return "certified financial preparation"
        return "read-only financial probe"
    if values[:2] == ["bash", "scripts/sentinel-compose.sh"]:
        return "resolve Sentinel Compose runtime"
    return "%s subprocess" % os.path.basename(values[0])


def _raw_stream_is_safe(command: Sequence[str]) -> bool:
    values = [str(item) for item in command]
    if values[:2] == ["docker", "build"]:
        # GO build args are immutable image/source identities, never credentials.
        return True
    if values[:2] == ["docker", "run"]:
        return ("--network" in values
                and values[values.index("--network") + 1] == "none"
                and any(item.startswith("tests/") for item in values))
    return False


def _timeout_seconds(controller: Any, go: Any, command: Sequence[str]) -> int:
    default = controller._safe_int_env("SENTINEL_GO_COMMAND_TIMEOUT_SECONDS", 10_800)
    preparation = controller._safe_int_env(
        "SENTINEL_GO_PREPARATION_TIMEOUT_SECONDS",
        max(1, go.MAX_BOUNDED_INGEST_MS // 1000),
    )
    return preparation if any(
        "SENTINEL_GO_PREPARATION=" in str(item) for item in command) else default


def _streaming_run(controller: Any, go: Any, command: Sequence[str], *,
                   env: Optional[Mapping[str, str]], cwd: Any,
                   raw_stream: bool) -> subprocess.CompletedProcess:
    """Run with live safe output or heartbeat-only sensitive output."""
    values = [str(item) for item in command]
    label = _command_label(values)
    timeout = _timeout_seconds(controller, go, values)
    _start(label)
    try:
        proc = subprocess.Popen(
            values,
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError:
        _fail("%s (could not start)" % label)
        return subprocess.CompletedProcess(values, 127, stdout="", stderr="")

    events = queue.Queue()
    captured = {"stdout": [], "stderr": []}

    def pump(name: str, stream: Any) -> None:
        try:
            for line in iter(stream.readline, ""):
                events.put((name, line))
        finally:
            events.put((name, None))

    threads = []
    for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        thread = threading.Thread(target=pump, args=(name, stream), daemon=True)
        thread.start()
        threads.append(thread)

    start = time.monotonic()
    last_heartbeat = start
    closed = set()
    timed_out = False
    while len(closed) < 2:
        now = time.monotonic()
        if now - start >= timeout:
            timed_out = True
            break
        try:
            name, line = events.get(timeout=0.25)
        except queue.Empty:
            if not raw_stream and now - last_heartbeat >= _HEARTBEAT_SECONDS:
                _working(label, int(now - start))
                last_heartbeat = now
            continue
        if line is None:
            closed.add(name)
            continue
        captured[name].append(line)
        if raw_stream:
            target = sys.stdout if name == "stdout" else sys.stderr
            target.write(line)
            target.flush()

    if timed_out:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
        rc = 124
        _fail("%s (timeout after %ss)" % (label, timeout))
    else:
        rc = proc.wait()
        if rc == 0:
            _pass(label)
        else:
            _fail("%s (exit %s)" % (label, rc))

    for thread in threads:
        thread.join(timeout=1)
    return subprocess.CompletedProcess(
        values,
        rc,
        stdout="".join(captured["stdout"]),
        stderr="".join(captured["stderr"]),
    )


def _suite_specs(go: Any, candidate_digest: str, bt_data_digest: str,
                 bt_engine_digest: str):
    verbose = ("-x", "-vv", "--tb=short", "-ra", "--color=yes")
    return (
        ("GO SCRIPT TESTS", [
            "docker", "run", "--rm", "--network", "none", candidate_digest,
            "tests/scripts/test_sentinel_go_validate.py",
            "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
            *verbose,
        ]),
        ("BACKTESTER BOUNDARY", [
            "docker", "run", "--rm", "--network", "none", candidate_digest,
            "tests/backtester/test_cold_boot_identity.py",
            "tests/backtester/test_wealth_core_replay.py",
            "tests/backtester/test_price_volume_domain_gate.py",
            *verbose,
        ]),
        ("BT DATA", [
            "docker", "run", "--rm", "--network", "none", bt_data_digest,
            "tests/bt_data/test_sharadar_adapter.py",
            "tests/bt_data/test_schema_bootstrap.py",
            "tests/bt_data/test_sf1_coverage.py",
            "tests/bt_data/test_issue_185_volume_domain_migration.py",
            *verbose,
        ]),
        ("BT ENGINE", [
            "docker", "run", "--rm", "--network", "none", bt_engine_digest,
            "tests/bt_engine/test_wealth_core_api.py",
            "tests/bt_engine/test_wealth_core_warmup.py",
            "tests/bt_engine/test_price_volume_domain_gate.py",
            *verbose,
        ]),
        ("WEALTH CORE", [
            "docker", "run", "--rm", "--network", "none", candidate_digest,
            "tests/wealth_core",
            *(item for node in go.NON_FORWARD_HISTORICAL_EXCLUSIONS
              for item in ("--deselect", node)),
            *verbose,
        ]),
        ("SENTINEL", [
            "docker", "run", "--rm", "--network", "none", candidate_digest,
            "tests/sentinel", *verbose,
        ]),
    )


def _summary_from_base(Summary: Any, base: Any, *, failure_suite=None,
                       failure_nodes=()):
    return Summary(
        candidate_image_digest=base.candidate_image_digest,
        runtime_image_digest=base.runtime_image_digest,
        source_identity_sha256=base.source_identity_sha256,
        passed=base.passed,
        failed=base.failed,
        errors=base.errors,
        skipped=base.skipped,
        xfailed=base.xfailed,
        xpassed=base.xpassed,
        exit_code=base.exit_code,
        suites_completed=base.suites_completed,
        auxiliary_image_digests=base.auxiliary_image_digests,
        non_forward_historical_exclusions=base.non_forward_historical_exclusions,
        failure_suite=failure_suite,
        failure_nodes=tuple(failure_nodes),
    )


def _probe_certified_suite(go: Any, Summary: Any, runner: Any, *,
                           commit: Optional[str], now_text: str):
    _banner("PHASE B - EXACT ARTIFACT CERTIFICATION")
    if commit is None:
        summary = Summary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.NOT_PROVEN, now_text,
            {"reason": "GIT_COMMIT_UNAVAILABLE"})

    runtime_ref = "sentinel-go-runtime:%s" % commit
    authorized_ref = "sentinel-go-authorized:%s" % commit
    test_ref = "sentinel-go-test:%s" % commit
    bt_engine_ref = "stocker-go-bt-engine:%s" % commit
    bt_engine_test_ref = "stocker-go-bt-engine-test:%s" % commit
    bt_data_ref = "stocker-go-bt-data:%s" % commit
    bt_data_test_ref = "stocker-go-bt-data-test:%s" % commit
    commands = (
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", runtime_ref,
         "-f", "Dockerfile.sentinel", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SENTINEL_RUNTIME_BASE_IMAGE=" + runtime_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", authorized_ref,
         "-f", "Dockerfile.sentinel-authorized", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SENTINEL_IMAGE=" + authorized_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", test_ref,
         "-f", "Dockerfile.sentinel-test", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", "stocker-base:latest",
         "-f", "Dockerfile.base", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_engine_ref,
         "-f", "services/bt-engine/Dockerfile", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "BT_ENGINE_IMAGE=" + bt_engine_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_engine_test_ref,
         "-f", "services/bt-engine/Dockerfile.test", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_data_ref,
         "-f", "services/bt-data/Dockerfile", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "BT_DATA_IMAGE=" + bt_data_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_data_test_ref,
         "-f", "services/bt-data/Dockerfile.test", "."],
    )
    _banner("BUILD CERTIFICATION IMAGES")
    for command in commands:
        if runner.run(command).returncode != 0:
            summary = Summary(
                None, None, None, failure_suite="IMAGE_BUILD", failure_nodes=())
            return summary, go.make_gate(
                "certified_suite_no_skips", go.FAIL, now_text,
                {"reason": "CANDIDATE_IMAGE_BUILD_FAILED",
                 "failure_suite": "IMAGE_BUILD"})

    runtime_digest = go._inspect_image_id(runner, authorized_ref)
    candidate_digest = go._inspect_image_id(runner, test_ref)
    bt_engine_digest = go._inspect_image_id(runner, bt_engine_test_ref)
    bt_data_digest = go._inspect_image_id(runner, bt_data_test_ref)
    if not all((runtime_digest, candidate_digest,
                bt_engine_digest, bt_data_digest)):
        summary = Summary(
            candidate_image_digest=candidate_digest,
            runtime_image_digest=runtime_digest,
            source_identity_sha256=None,
            auxiliary_image_digests=tuple(
                item for item in (bt_engine_digest, bt_data_digest) if item),
            failure_suite="IMAGE_IDENTITY",
            failure_nodes=(),
        )
        return summary, go.make_gate(
            "certified_suite_no_skips", go.FAIL, now_text,
            {"reason": "CANDIDATE_IMAGE_IDENTITY_UNAVAILABLE",
             "failure_suite": "IMAGE_IDENTITY"})

    _banner("CERTIFIED RUNTIME IDENTITY")
    identity = runner.run([
        "docker", "run", "--rm", "--network", "none",
        "--entrypoint", "python", runtime_digest,
        "-m", "sentinel", "identity", "--require-environment-compatible"])
    identity_hash = None
    if identity.returncode == 0:
        try:
            payload = go.json.loads(identity.stdout or "")
            candidate = str(payload.get("identity_hash") or "")
            if go._HEX64.fullmatch(candidate):
                identity_hash = candidate
        except (AttributeError, go.json.JSONDecodeError):
            identity_hash = None

    aggregate = {
        "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
        "xfailed": 0, "xpassed": 0,
    }
    combined_exit = 0
    suites_completed = 0
    failure_suite = None
    failure_nodes = ()
    specs = _suite_specs(go, candidate_digest, bt_data_digest, bt_engine_digest)
    for index, (label, command) in enumerate(specs, 1):
        _banner("CERTIFICATION %d/6 - %s" % (index, label))
        suite = runner.run(command)
        combined_output = (suite.stdout or "") + "\n" + (suite.stderr or "")
        counts = go._parse_pytest_summary(combined_output)
        for key in aggregate:
            aggregate[key] += counts[key]
        if counts["passed"] > 0:
            suites_completed += 1
        if suite.returncode != 0:
            combined_exit = int(suite.returncode) or 1
            failure_suite = label
            failure_nodes = extract_failure_nodes(combined_output)
            if failure_nodes:
                for node in failure_nodes:
                    _fail("%s: %s" % (label, node))
            else:
                _fail("%s failed; no safe pytest node ID was recoverable" % label)
            _warn("remaining certification suites skipped after first causal failure")
            break

    summary = Summary(
        candidate_image_digest=candidate_digest,
        runtime_image_digest=runtime_digest,
        source_identity_sha256=identity_hash,
        exit_code=combined_exit,
        suites_completed=suites_completed,
        auxiliary_image_digests=tuple(
            item for item in (bt_engine_digest, bt_data_digest) if item),
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS,
        failure_suite=failure_suite,
        failure_nodes=failure_nodes,
        **aggregate,
    )
    gate = go.make_gate(
        "certified_suite_no_skips", go.PASS if summary.complete else go.FAIL,
        now_text,
        {"passed": summary.passed,
         "failed": summary.failed,
         "errors": summary.errors,
         "skipped": summary.skipped,
         "xfailed": summary.xfailed,
         "xpassed": summary.xpassed,
         "exit_code": summary.exit_code,
         "suites_completed": summary.suites_completed,
         "failure_suite": summary.failure_suite,
         "failure_nodes": list(summary.failure_nodes),
         "suite_order": list(CERTIFICATION_SUITE_LABELS),
         "fail_fast": True,
         "auxiliary_images_known": len(summary.auxiliary_image_digests) == 2,
         "non_forward_historical_exclusions": list(
             summary.non_forward_historical_exclusions),
         "image_known": candidate_digest is not None,
         "runtime_known": runtime_digest is not None,
         "identity_known": identity_hash is not None})
    if summary.complete:
        _pass("all six certification suites completed with no skips")
    return summary, gate


def install(*, go: Any, controller: Any) -> None:
    """Install production-only observability without weakening authority checks."""
    if getattr(controller, _INSTALLED_MARKER, False):
        return

    base_runner = controller.DiagnosticRunner

    class ObservableDiagnosticRunner(base_runner):
        def run(self, argv, *, env=None, cwd=go.ROOT):
            command = [str(item) for item in argv]
            completed = _streaming_run(
                controller, go, command, env=env, cwd=cwd,
                raw_stream=_raw_stream_is_safe(command))
            text = (completed.stdout or "") + "\n" + (completed.stderr or "")
            if ("SENTINEL_GO_PREPARATION" in text
                    or any("SENTINEL_GO_PREPARATION=" in item for item in command)):
                self.last_preparation_output = text
            return completed

    @dataclass(frozen=True)
    class ObservableTestSummary(go.TestSummary):
        failure_suite: Optional[str] = None
        failure_nodes: Tuple[str, ...] = ()

        def to_dict(self) -> dict:
            value = dict(super().to_dict())
            value["failure_suite"] = self.failure_suite
            value["failure_nodes"] = list(self.failure_nodes)
            return value

    original_summary_from_dict = controller._summary_from_dict

    def summary_from_dict(value):
        base = original_summary_from_dict(value)
        suite = value.get("failure_suite")
        if suite is not None:
            suite = str(suite)
            if suite not in set(CERTIFICATION_SUITE_LABELS) | {
                    "IMAGE_BUILD", "IMAGE_IDENTITY"}:
                suite = None
        raw_nodes = value.get("failure_nodes") or ()
        nodes = tuple(
            node for node in (str(item) for item in raw_nodes)
            if len(node) <= 320 and _SAFE_NODE_RE.fullmatch(node)
        )[:_MAX_FAILURE_NODES]
        return _summary_from_base(
            ObservableTestSummary, base,
            failure_suite=suite, failure_nodes=nodes)

    controller.DiagnosticRunner = ObservableDiagnosticRunner
    controller._TEST_CACHE_KEYS = frozenset(
        set(controller._TEST_CACHE_KEYS) | {"failure_suite", "failure_nodes"})
    controller._summary_from_dict = summary_from_dict
    go.probe_certified_suite = lambda runner, *, commit, now_text: (
        _probe_certified_suite(
            go, ObservableTestSummary, runner,
            commit=commit, now_text=now_text))

    # Add phase visibility around the financial probes whose raw subprocess output
    # intentionally remains private.  These wrappers do not alter arguments,
    # return values, or authority decisions.
    original_git = go.probe_git
    original_alpaca = go.probe_alpaca_account
    original_preparation = controller.entry.probe_prevalidation_preparation
    original_parity = go.probe_active_wealth_parity
    original_readiness = go.probe_sharadar_readiness
    original_db_health = go.probe_database_financial_health

    def probe_git(*args, **kwargs):
        _banner("PHASE A - CURRENT GIT IDENTITY")
        result = original_git(*args, **kwargs)
        (_pass if result[1].status == go.PASS else _fail)(
            "Git identity %s" % result[1].status)
        return result

    def probe_alpaca(*args, **kwargs):
        _banner("ALPACA PAPER ACCOUNT - GET ONLY")
        result = original_alpaca(*args, **kwargs)
        (_pass if result[0].status == go.PASS else _fail)(
            "Alpaca PAPER account %s" % result[0].status)
        return result

    def probe_preparation(*args, **kwargs):
        _banner("PHASE C - CERTIFIED FINANCIAL PREPARATION")
        result = original_preparation(*args, **kwargs)
        (_pass if result.status == go.PASS else _fail)(
            "financial preparation %s" % result.status)
        return result

    def probe_parity(*args, **kwargs):
        _banner("PHASE D1 - WEALTH CORE PARITY")
        result = original_parity(*args, **kwargs)
        (_pass if result.status == go.PASS else _fail)(
            "Wealth Core parity %s" % result.status)
        return result

    def probe_readiness(*args, **kwargs):
        _banner("PHASE D2 - SHARADAR READINESS")
        result = original_readiness(*args, **kwargs)
        (_pass if result.status == go.PASS else _fail)(
            "Sharadar readiness %s" % result.status)
        return result

    def probe_db_health(*args, **kwargs):
        _banner("PHASE D3 - DATABASE FINANCIAL HEALTH")
        result = original_db_health(*args, **kwargs)
        (_pass if result[1].status == go.PASS else _fail)(
            "database financial health %s" % result[1].status)
        return result

    go.probe_git = probe_git
    go.probe_alpaca_account = probe_alpaca
    controller.entry.probe_prevalidation_preparation = probe_preparation
    go.probe_active_wealth_parity = probe_parity
    go.probe_sharadar_readiness = probe_readiness
    go.probe_database_financial_health = probe_db_health

    setattr(controller, _INSTALLED_MARKER, True)
