from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_ci_certification_verify as verifier  # noqa: E402
import sentinel_go_phase_controller as phase  # noqa: E402
import sentinel_go_probe_contract as probe  # noqa: E402


def _completed(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(["fixture"], rc, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize(("completed", "expected"), [
    (_completed(124), "SUBPROCESS_TIMEOUT"),
    (_completed(127), "COMMAND_UNAVAILABLE"),
    (_completed(137), "PROCESS_TERMINATED"),
    (_completed(143), "PROCESS_TERMINATED"),
    (_completed(1, stderr="Killed"), "PROCESS_TERMINATED"),
    (_completed(1, stderr="password authentication failed"), "DATABASE_AUTHENTICATION_FAILURE"),
    (_completed(1, stderr="connection refused"), "DATABASE_CONNECTION_FAILURE"),
    (_completed(1, stderr="network is unreachable"), "DATABASE_CONNECTION_FAILURE"),
    (_completed(1, stderr="permission denied"), "RUNTIME_PERMISSION_FAILURE"),
    (_completed(1, stderr="No space left on device"), "RESOURCE_STORAGE_FAILURE"),
])
def test_subprocess_fault_classes_are_stable(completed, expected):
    evidence = probe.subprocess_evidence(completed, context="FAULT")
    assert evidence["failure_class"] == expected
    assert evidence["exit_code"] == completed.returncode
    assert len(evidence["stdout_sha256"]) == 64
    assert len(evidence["stderr_sha256"]) == 64


class ScriptedRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run_with_timeout(self, argv, *, env=None, timeout_seconds, cwd=None):
        self.calls.append(([str(x) for x in argv], float(timeout_seconds)))
        if not self.results:
            raise AssertionError("unexpected Docker call")
        return self.results.pop(0)


def test_postgres_container_disappears_before_identity_is_observed():
    runner = ScriptedRunner([
        _completed(0),
        _completed(0, stdout=""),
    ])
    evidence = probe.ensure_postgres_ready(
        runner, env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-f", "fixture.yml"], sleep=lambda _x: None,
        monotonic=lambda: 0.0)
    assert evidence["reason"] == "POSTGRES_CONTAINER_ID_UNAVAILABLE"


@pytest.mark.parametrize("status", ["dead", "exited", "removing"])
def test_postgres_exit_states_fail_before_probe_mutation(status):
    runner = ScriptedRunner([
        _completed(0),
        _completed(0, stdout="abc123def456\n"),
        _completed(0, stdout=status + "\n"),
    ])
    evidence = probe.ensure_postgres_ready(
        runner, env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-f", "fixture.yml"], sleep=lambda _x: None,
        monotonic=lambda: 0.0)
    assert evidence["reason"] == "POSTGRES_EXITED_BEFORE_HEALTHY"
    assert evidence["service_status"] == status


def test_postgres_daemon_start_failure_stays_machine_classified():
    runner = ScriptedRunner([
        _completed(1, stderr="Cannot connect to the Docker daemon"),
    ])
    evidence = probe.ensure_postgres_ready(
        runner, env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-f", "fixture.yml"], sleep=lambda _x: None,
        monotonic=lambda: 0.0)
    assert evidence["reason"] == "POSTGRES_START_FAILED"
    assert evidence["exit_code"] == 1


def test_postgres_health_inspection_failure_is_not_misreported_as_semantic_health():
    runner = ScriptedRunner([
        _completed(0),
        _completed(0, stdout="abc123def456\n"),
        _completed(1, stderr="container disappeared"),
    ])
    evidence = probe.ensure_postgres_ready(
        runner, env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-f", "fixture.yml"], sleep=lambda _x: None,
        monotonic=lambda: 0.0)
    assert evidence["reason"] == "POSTGRES_HEALTH_UNAVAILABLE"


def test_postgres_healthy_after_start_is_success():
    runner = ScriptedRunner([
        _completed(0),
        _completed(0, stdout="abc123def456\n"),
        _completed(0, stdout="healthy\n"),
    ])
    evidence = probe.ensure_postgres_ready(
        runner, env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-f", "fixture.yml"], sleep=lambda _x: None,
        monotonic=lambda: 0.0)
    assert evidence is None


@pytest.mark.parametrize("status", [401, 403, 404, 408, 429, 500, 502, 503])
def test_github_partial_http_failures_are_fail_closed_and_secret_free(status):
    token = "github_pat_secret_fixture_value"

    def opener(request, timeout=30):
        assert timeout == 30
        assert request.get_method() == "GET"
        raise urllib.error.HTTPError(
            request.full_url, status, "fixture", hdrs=None, fp=None)

    client = verifier.GitHubReadClient(token=token, opener=opener)
    with pytest.raises(verifier.CertificationVerificationRefused) as caught:
        client.json("/repos/flabber1835/stocker/actions/runs")
    assert caught.value.code == "CERT_GITHUB_UNAVAILABLE"
    assert token not in str(caught.value)
    assert token not in caught.value.detail


def test_github_dns_or_tls_style_url_failure_is_fail_closed():
    def opener(request, timeout=30):
        raise urllib.error.URLError("temporary failure in name resolution")

    client = verifier.GitHubReadClient(token="fixture", opener=opener)
    with pytest.raises(verifier.CertificationVerificationRefused) as caught:
        client.json("/repos/flabber1835/stocker/actions/runs")
    assert caught.value.code == "CERT_GITHUB_UNAVAILABLE"


@pytest.mark.parametrize(("text", "reason"), [
    ("VendorPublicationUnstable", "SOURCE_PUBLICATION_UNSTABLE"),
    ("SharadarMutationRefused: source cursor cannot move backward", "LOCAL_CURSOR_CORRUPT"),
    ("SharadarMutationRefused: no permanent identity for fixture", "SOURCE_IDENTITY_UNRESOLVED"),
    ("SharadarMutationRefused: no positive raw close for fixture", "SOURCE_RAW_CLOSE_INVALID"),
])
def test_vendor_partial_failures_keep_specific_preparation_reason(text, reason):
    observed, _detail = phase._classify_preparation_failure(text)
    assert observed == reason
