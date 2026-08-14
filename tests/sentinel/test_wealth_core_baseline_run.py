"""Formal Wealth Core baseline authority must come from one actual invocation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from stock_strategy_shared.runtime_identity import wealth_core_baseline_identity
from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
from tools import wealth_core_baseline_run as baseline


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or
            Path(__file__).resolve().parents[2])


def hashes() -> dict[str, str]:
    return {name: f"{index:x}" * 64
            for index, name in enumerate(HASH_ORDER, start=1)}


def expected_artifact() -> dict:
    behavior = wealth_core_baseline_identity()
    return {
        "schema": "wealth_core_expected_hashes.v1",
        "status": "ready",
        "window": {"requested_start": "2021-01-04",
                   "requested_end": "2023-12-29"},
        "hashes": hashes(),
        "corpus": {"version": "generation-7", "status": "READY",
                   "source_mode": "sharadar", "split_source": "actions"},
        "run": {"strategy_id": "wealth-core", "strategy_version": "1",
                "starting_cash": 1_000_000.0,
                "config_hash": behavior["engine_config_hash"],
                "behavior_identity": behavior},
        "provenance": {"producer": "tools/wealth_core_expected_hashes.py"},
    }


def manifest() -> dict:
    commit = "a" * 40
    return {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS", "failures": [],
        "git_tree_clean": True, "git_commit": commit,
        "wealth_core_source_hash": "b" * 64,
        "bt_engine_app_source_hash": "c" * 64,
        "bt_engine_image": {
            "ref": "registry.example/bt-engine@sha256:" + "d" * 64,
            "id": "sha256:" + "e" * 64,
            "source_revision": commit,
            "repo_digests": ["registry.example/bt-engine@sha256:" + "d" * 64],
        },
        "bt_engine_runtime_identity": {
            "requirements_lock_sha256": "f" * 64,
            "distributions_sha256": "1" * 64,
            "distributions_count": 42,
        },
        "parity_generations": {
            "sentinel_data_version": 9,
            "canonical_data_version": "generation-7",
            "canonical_source_mode": "sharadar",
        },
        "final_corpus_hash": "2" * 64,
    }


def engine_identity(m: dict) -> dict:
    return {
        "python": "3.12.13",
        "wealth_core_source_hash": m["wealth_core_source_hash"],
        "bt_engine_app_source_hash": m["bt_engine_app_source_hash"],
        "image_id": m["bt_engine_image"]["id"],
        "image_ref": m["bt_engine_image"]["ref"],
        "source_revision": m["git_commit"],
        **m["bt_engine_runtime_identity"],
    }


def terminal_row(run_id: str, expected: dict, m: dict) -> dict:
    spec = baseline.canonical_request(expected)
    spec["engine_identity"] = engine_identity(m)
    spec["baseline_identity"] = expected["run"]["behavior_identity"]
    return {
        "run_id": run_id, "mode": "baseline_replay", "status": "success",
        "started_at": "2026-08-13T10:00:01+00:00",
        "completed_at": "2026-08-13T10:00:02+00:00",
        "spec": spec,
        "summary": {
            "divergence": {"identical": True},
            "provenance": {
                "bt_data_version": "generation-7", "bt_data_status": "READY",
                "bt_data_source_mode": "sharadar", "split_source": "actions",
            },
        },
        "parity_hashes": expected["hashes"], "error_message": None,
    }


class Clock:
    def __init__(self):
        self.value = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


def invoke_fixture(tmp_path: Path):
    expected = expected_artifact()
    m = manifest()
    expected_path = tmp_path / "expected.json"
    manifest_path = tmp_path / "manifest.json"
    expected_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    manifest_path.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    run_id = "11111111-1111-4111-8111-111111111111"
    row = terminal_row(run_id, expected, m)
    calls = []

    def request(method, url, payload, *, timeout):
        calls.append((method, url, payload, timeout))
        if method == "POST":
            assert payload == baseline.canonical_request(expected)
            return {"run_id": run_id, "mode": "baseline_replay",
                    "status": "running"}
        assert url.endswith(f"/wealth-core/runs/{run_id}")
        return row

    record = baseline.invoke(
        expected_path=expected_path, manifest_path=manifest_path,
        output_path=tmp_path / "baseline.json",
        base_url="http://127.0.0.1:8031",
        argv=[baseline.sys.executable, "-m", "tools.wealth_core_baseline_run",
              "--expected-hashes", str(expected_path),
              "--manifest", str(manifest_path),
              "--bt-engine-url", "http://127.0.0.1:8031",
              "--output", str(tmp_path / "baseline.json"),
              "--timeout-seconds", "30"],
        timeout_seconds=30, request_json=request, now=Clock(),
        monotonic=lambda: 1.0, sleeper=lambda _seconds: None)
    return record, calls, row, expected_path, manifest_path


def test_actual_invocation_binds_exact_endpoint_row_inputs_and_behavior(tmp_path):
    record, calls, row, expected_path, manifest_path = invoke_fixture(tmp_path)
    assert [call[0] for call in calls] == ["POST", "GET"]
    assert calls[1][1].endswith("/wealth-core/runs/" + record["run_id"])
    assert record["terminal_run"]["row"] == row
    assert record["expected_hashes"]["sha256"] == hashlib.sha256(
        expected_path.read_bytes()).hexdigest()
    assert record["certification_manifest"]["sha256"] == hashlib.sha256(
        manifest_path.read_bytes()).hexdigest()
    assert record["invocation"]["request"]["starting_cash"] == 1_000_000.0
    behavior = row["spec"]["baseline_identity"]
    assert behavior["wealth_core_config_sha256"]
    assert behavior["eligibility_config_sha256"]
    assert baseline.validate_record(record) is record


def test_prior_minimal_hand_authored_portable_envelope_is_not_authority():
    old = {
        "schema": "sentinel.rehearsal_envelope/1", "run_id": "run-1",
        "mode": "baseline_replay", "status": "success",
        "spec": {"expected_hashes": hashes(),
                 "expected_data_version": "generation-7"},
        "parity_hashes": hashes(),
        "summary": {"divergence": {"identical": True}},
    }
    with pytest.raises(baseline.BaselineRunRefused, match="fields differ|schema"):
        baseline.validate_record(old)


def test_expected_config_must_equal_full_behavior_identity():
    expected = expected_artifact()
    expected["run"]["config_hash"] = "0" * 16
    assert expected["run"]["behavior_identity"]["engine_config_hash"] != "0" * 16
    with pytest.raises(baseline.BaselineRunRefused, match="behavior identity"):
        baseline.canonical_request(expected)


def test_cli_has_no_portable_row_or_existing_run_adoption_surface(capsys):
    with pytest.raises(SystemExit):
        baseline.main(["--run-id", "11111111-1111-4111-8111-111111111111"])
    error = capsys.readouterr().err
    assert "unrecognized arguments" in error or "required" in error
    source = (ROOT / "tools/wealth_core_baseline_run.py").read_text()
    parser_source = source[source.index("def main("):]
    assert 'add_argument("--run-id"' not in parser_source
    assert 'add_argument("--from-json"' not in parser_source


@pytest.mark.parametrize("bad_argv", [
    ["python", "portable-export.py", "success.json"],
    ["python", "-m", "tools.wealth_core_baseline_run",
     "--expected-hashes", "e", "--manifest", "m",
     "--bt-engine-url", "http://127.0.0.1:8031", "--output", "o",
     "--run-id", "11111111-1111-4111-8111-111111111111"],
])
def test_record_refuses_non_invocation_or_existing_run_argv(tmp_path, bad_argv):
    record, *_ = invoke_fixture(tmp_path)
    record["invocation"]["argv"] = bad_argv
    record["invocation"]["argv_sha256"] = baseline.canonical_sha256(bad_argv)
    with pytest.raises(baseline.BaselineRunRefused, match="producer command|arguments"):
        baseline.validate_record(record)


def test_invalid_invocation_argv_is_refused_before_submit(tmp_path):
    expected = expected_artifact()
    expected_path = tmp_path / "expected.json"
    manifest_path = tmp_path / "manifest.json"
    expected_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    manifest_path.write_text(json.dumps(manifest(), indent=2, sort_keys=True) + "\n")
    calls = []

    with pytest.raises(baseline.BaselineRunRefused, match="producer command"):
        baseline.invoke(
            expected_path=expected_path, manifest_path=manifest_path,
            output_path=tmp_path / "baseline.json",
            base_url="http://127.0.0.1:8031",
            argv=[baseline.sys.executable, "portable-export.py", "success.json"],
            timeout_seconds=30,
            request_json=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []


def test_invocation_argv_must_name_actual_inputs_output_and_timeout(tmp_path):
    expected_path = tmp_path / "expected.json"
    manifest_path = tmp_path / "manifest.json"
    output = tmp_path / "baseline.json"
    expected_path.write_text(
        json.dumps(expected_artifact(), indent=2, sort_keys=True) + "\n")
    manifest_path.write_text(
        json.dumps(manifest(), indent=2, sort_keys=True) + "\n")
    calls = []
    argv = [
        baseline.sys.executable, "-m", "tools.wealth_core_baseline_run",
        "--expected-hashes", str(tmp_path / "portable-copy.json"),
        "--manifest", str(manifest_path),
        "--bt-engine-url", "http://127.0.0.1:8031",
        "--output", str(output), "--timeout-seconds", "30",
    ]

    with pytest.raises(baseline.BaselineRunRefused, match="artifact path"):
        baseline.invoke(
            expected_path=expected_path, manifest_path=manifest_path,
            output_path=output, base_url="http://127.0.0.1:8031",
            argv=argv, timeout_seconds=30,
            request_json=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []


def test_remote_or_credentialed_endpoint_is_not_formal_authority(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    record["invocation"]["endpoint"]["base_url"] = "https://engine.example"
    with pytest.raises(baseline.BaselineRunRefused, match="loopback"):
        baseline.validate_record(record)


def test_log_must_be_exact_monotonic_run_scoped_sequence(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    entries = record["invocation"]["log"]["entries"]
    entries[-1]["run_id"] = "33333333-3333-4333-8333-333333333333"
    record["invocation"]["log"]["sha256"] = baseline.canonical_sha256(entries)
    with pytest.raises(baseline.BaselineRunRefused, match="foreign event/run"):
        baseline.validate_record(record)


@pytest.mark.parametrize("mutate,match", [
    (lambda record: record.update(schema="sentinel.rehearsal_envelope/1"),
     "schema"),
    (lambda record: record.update(extra="asserted-pass"), "fields differ"),
    (lambda record: record["invocation"]["request"].update(config={"n_slots": 24}),
     "request is not canonical"),
    (lambda record: record["terminal_run"]["row"]["spec"][
        "baseline_identity"].update(starting_cash=2_000_000.0),
     "terminal row binding differs"),
])
def test_schema_behavior_and_row_tampering_refuse(tmp_path, mutate, match):
    record, *_ = invoke_fixture(tmp_path)
    mutate(record)
    with pytest.raises(baseline.BaselineRunRefused, match=match):
        baseline.validate_record(record)


def test_input_raw_bytes_are_self_authenticated_not_reserialized(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    record["expected_hashes"]["bytes_base64"] = "e30="  # {}
    with pytest.raises(baseline.BaselineRunRefused, match="binding differs"):
        baseline.validate_record(record)


def test_bound_input_base64_must_be_canonical(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    # Python's strict decoder accepts redundant padding, but a formal record
    # has one byte representation for a given input artifact.
    record["expected_hashes"]["bytes_base64"] += "="
    with pytest.raises(baseline.BaselineRunRefused, match="canonical base64"):
        baseline.validate_record(record)


def test_engine_commit_dependency_and_image_drift_refuse(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    record["terminal_run"]["row"]["spec"]["engine_identity"][
        "source_revision"] = "9" * 40
    record["terminal_run"]["sha256"] = baseline.canonical_sha256(
        record["terminal_run"]["row"])
    with pytest.raises(baseline.BaselineRunRefused, match="source_revision differs"):
        baseline.validate_record(record)


def test_failed_terminal_run_never_builds_authority(tmp_path):
    expected = expected_artifact()
    m = manifest()
    expected_path = tmp_path / "expected.json"
    manifest_path = tmp_path / "manifest.json"
    expected_path.write_text(json.dumps(expected))
    manifest_path.write_text(json.dumps(m))
    run_id = "11111111-1111-4111-8111-111111111111"
    row = terminal_row(run_id, expected, m)
    row.update(status="failed", error_message="parity_violation")

    def request(method, _url, _payload, *, timeout):
        return ({"run_id": run_id, "mode": "baseline_replay",
                 "status": "running"} if method == "POST" else row)

    with pytest.raises(baseline.BaselineRunRefused, match="not a successful"):
        baseline.invoke(
            expected_path=expected_path, manifest_path=manifest_path,
            output_path=tmp_path / "baseline.json",
            base_url="http://127.0.0.1:8031",
            argv=[baseline.sys.executable, "-m", "tools.wealth_core_baseline_run",
                  "--expected-hashes", str(expected_path),
                  "--manifest", str(manifest_path),
                  "--bt-engine-url", "http://127.0.0.1:8031",
                  "--output", str(tmp_path / "baseline.json"),
                  "--timeout-seconds", "30"],
            timeout_seconds=30, request_json=request, now=Clock(),
            monotonic=lambda: 1.0, sleeper=lambda _: None)


def test_atomic_publication_is_no_clobber_and_exact(tmp_path):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    baseline.write_record_atomic(output, record)
    assert output.read_bytes() == baseline.canonical_bytes(record)
    before = output.read_bytes()
    with pytest.raises(baseline.BaselineRunRefused, match="exists"):
        baseline.write_record_atomic(output, record)
    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_atomic_link_failure_leaves_no_authoritative_or_staging_file(
        tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    monkeypatch.setattr(baseline.os, "link", lambda *_: (_ for _ in ()).throw(
        OSError("injected link failure")))
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_link_then_reported_failure_detects_inode_and_rolls_back(
        tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    real_link = os.link

    def link_then_raise(source, target):
        real_link(source, target)
        raise OSError("injected post-link wrapper failure")

    monkeypatch.setattr(baseline.os, "link", link_then_raise)
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_post_link_durability_failure_rolls_back_authoritative_name(
        tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    calls = 0

    def fail_first(_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected directory fsync failure")

    monkeypatch.setattr(baseline, "_fsync_directory", fail_first)
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_staging_cleanup_failure_rolls_back_authoritative_name(
        tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    original = baseline._unlink_retry
    injected = False

    def fail_staging_once(path, *, attempts=4):
        nonlocal injected
        if path.suffix == ".tmp" and not injected:
            injected = True
            raise OSError("injected staging cleanup failure")
        return original(path, attempts=attempts)

    monkeypatch.setattr(baseline, "_unlink_retry", fail_staging_once)
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_unlink_retry_recovers_from_transient_failures(tmp_path, monkeypatch):
    path = tmp_path / "transient"
    path.write_bytes(b"x")
    real = Path.unlink
    calls = 0

    def transient(self, *args, **kwargs):
        nonlocal calls
        if self == path and calls < 2:
            calls += 1
            raise OSError("transient")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", transient)
    baseline._unlink_retry(path)
    assert calls == 2
    assert not path.exists()


def test_atomic_publish_retries_transient_staging_unlink(tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    real = Path.unlink
    staging_failures = 0

    def transient_staging(self, *args, **kwargs):
        nonlocal staging_failures
        if self.suffix == ".tmp" and staging_failures < 2:
            staging_failures += 1
            raise OSError("transient staging unlink")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", transient_staging)
    baseline.write_record_atomic(output, record)
    assert staging_failures == 2
    assert output.read_bytes() == baseline.canonical_bytes(record)
    assert not list(tmp_path.glob(".baseline.json.*.tmp"))


def test_rollback_retries_transient_authoritative_unlink(tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    real_unlink = Path.unlink
    real_fsync = baseline._fsync_directory
    target_failures = 0
    fsync_calls = 0

    def fail_first_fsync(path):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("post-link durability failure")
        return real_fsync(path)

    def transient_target(self, *args, **kwargs):
        nonlocal target_failures
        if self == output and target_failures < 2:
            target_failures += 1
            raise OSError("transient target unlink")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(baseline, "_fsync_directory", fail_first_fsync)
    monkeypatch.setattr(Path, "unlink", transient_target)
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert target_failures == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.rollback.*"))


def test_rollback_quarantines_when_authoritative_unlink_stays_blocked(
        tmp_path, monkeypatch):
    record, *_ = invoke_fixture(tmp_path)
    output = tmp_path / "baseline.json"
    real_unlink = baseline._unlink_retry
    real_fsync = baseline._fsync_directory
    fsync_calls = 0

    def fail_first_fsync(path):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("post-link durability failure")
        return real_fsync(path)

    def block_authoritative(path, *, attempts=4):
        if path == output:
            raise OSError("indexer owns authoritative name")
        return real_unlink(path, attempts=attempts)

    monkeypatch.setattr(baseline, "_fsync_directory", fail_first_fsync)
    monkeypatch.setattr(baseline, "_unlink_retry", block_authoritative)
    with pytest.raises(baseline.BaselineRunRefused, match="atomically publish"):
        baseline.write_record_atomic(output, record)
    assert not output.exists()
    assert not list(tmp_path.glob(".baseline.json.rollback.*"))


def test_built_engine_records_commit_dependencies_and_effective_behavior():
    api = (ROOT / "services/bt-engine/app/wealth_core_api.py").read_text()
    compose = (ROOT / "docker-compose.backtest.yml").read_text()
    launcher = (ROOT / "scripts/bt-engine-up.sh").read_text()
    manifest_source = (ROOT / "scripts/sentinel_manifest.py").read_text()
    assert "dependency_identity(\"/app/requirements.lock\")" in api
    assert 'spec_json["baseline_identity"]' in api
    assert "BT_ENGINE_SOURCE_REVISION" in compose
    assert "BT_ENGINE_SOURCE_REVISION=\"${REVISION}\"" in launcher
    assert "bt_engine_runtime_identity" in manifest_source
    assert re.search(r"image inspect .*org.opencontainers.image.revision",
                     " ".join(launcher.splitlines()))
