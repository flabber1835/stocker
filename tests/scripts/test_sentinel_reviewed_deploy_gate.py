from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


go = _load("sentinel_go_validate_for_deploy_test",
           ROOT / "scripts" / "sentinel_go_validate.py")
deploy = _load("sentinel_autonomous_deploy_review_test",
               ROOT / "scripts" / "sentinel_autonomous_deploy.py")

NOW = datetime(2026, 8, 21, 19, 30, tzinfo=timezone.utc)
NOW_TEXT = "2026-08-21T19:30:00Z"
COMMIT = "a" * 40
RUNTIME = "sha256:" + "b" * 64
TEST = "sha256:" + "c" * 64
SOURCE = "f" * 64
PUBLICATION = {
    "publication_fingerprint": "1" * 64,
    "visible_frontier": "2026-08-20",
}


def _env(**updates):
    value = {
        "SENTINEL_DEPLOY_GIT_BRANCH": "main",
        "SENTINEL_POSTGRES_PASSWORD": "private",
        "SENTINEL_SHADOW_OBSERVATION_ID": "year-end",
        "SENTINEL_SHADOW_STARTING_CASH": "100000",
    }
    value.update(updates)
    return value


def _bundle(tmp_path, *, env=None, dual=False):
    model_env = _env() if env is None else env
    paper_only = {
        gate: go.NOT_PROVEN
        for gate in go.GATE_IDS if gate not in go.SHADOW_GATE_IDS
    }
    if dual:
        paper_only["alpaca_paper_account"] = go.PASS
    gates = {
        gate: go.make_gate(
            gate, paper_only.get(gate, go.PASS), NOW_TEXT,
            {"unit_test": True})
        for gate in go.GATE_IDS
    }
    probes = go.ProbeResults(
        git=go.GitIdentity(
            commit=COMMIT, branch_is_main=True, clean=True,
            origin_main=COMMIT),
        tests=go.TestSummary(
            candidate_image_digest=TEST,
            runtime_image_digest=RUNTIME,
            source_identity_sha256=SOURCE,
            passed=4000, exit_code=0, suites_completed=3,
            auxiliary_image_digests=(),
            non_forward_historical_exclusions=(
                go.NON_FORWARD_HISTORICAL_EXCLUSIONS)),
        gates=gates,
        subject_values={
            "data_publication": go.data_publication_subject_value(PUBLICATION),
            "shadow_configuration": go.shadow_configuration_sha256(
                model_env, source_identity_sha256=SOURCE),
            **({
                "alpaca_paper_account": "paper-account",
                "configured_paper_account": "paper-account",
            } if dual else {}),
        },
        broker_mutation_attempts=0,
        production_db_writes=0,
        input_mode="PRODUCTION",
        preparation=go.PreparationSummary(
            status=go.PASS,
            runtime_image_digest=RUNTIME,
            schema_migration_attempted=True,
            bounded_sharadar_daily_attempted=True,
            broker_mutation_attempts=0,
            evidence_sha256="2" * 64),
        database_health=go.DatabaseHealthSummary(
            status=go.PASS,
            runtime_image_digest=RUNTIME,
            checks={name: True for name in go.DATABASE_CHECK_IDS},
            counts={
                "publication_versions": 42,
                "publication_chain_gaps": 0,
                "duplicate_publication_run_ids": 0,
                "recent_xnys_sessions": 252,
                "frontier_security_rows": 8_000,
                "frontier_duplicate_security_keys": 0,
                "warmup_revision_sessions": 252,
            },
            measured_milliseconds={
                "bounded_sharadar_ingest": 1_000,
                "full_forward_decision_replay": 2_000,
                "warmup_revision_scan": 3_000,
                "combined_pretrade_work": 6_000,
            },
            threshold_milliseconds={
                "bounded_sharadar_ingest": go.MAX_BOUNDED_INGEST_MS,
                "full_forward_decision_replay": (
                    go.MAX_FULL_FORWARD_DECISION_REPLAY_MS),
                "warmup_revision_scan": go.MAX_WARMUP_REVISION_SCAN_MS,
                "combined_pretrade_work": go.MAX_COMBINED_PRETRADE_WORK_MS,
            },
            deadline_milliseconds={
                "minimum_source_final_to_following_open": (
                    go.MIN_SOURCE_FINAL_TO_OPEN_MS),
                "observed_source_final_to_following_open": (
                    go.MIN_SOURCE_FINAL_TO_OPEN_MS),
                "minimum_remaining_margin": (
                    go.MIN_REMAINING_DEADLINE_MARGIN_MS),
                "measured_remaining_margin": (
                    go.MIN_SOURCE_FINAL_TO_OPEN_MS - 6_000),
            },
            production_db_writes=0,
            evidence_sha256="3" * 64),
    )
    return go.emit_bundle(
        probes, output_dir=tmp_path, created_at=NOW,
        valid_for=timedelta(hours=24), scan_env={})


class ReadOnlyHost:
    def __init__(self, *, publication=None):
        self.publication = dict(publication or PUBLICATION)
        self.calls = []

    def __call__(self, argv, **kwargs):
        command = [str(item) for item in argv]
        self.calls.append((command, dict(kwargs.get("env") or {})))
        if command[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["git", "symbolic-ref", "--quiet"]:
            return subprocess.CompletedProcess(command, 0, "main\n", "")
        if command == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, COMMIT + "\n", "")
        if command == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(command, 0, COMMIT + "\n", "")
        if command[:3] == ["docker", "image", "inspect"]:
            ids = command[3:]
            records = []
            for image_id in ids:
                if image_id == RUNTIME:
                    layers = ["runtime-layer"]
                elif image_id == TEST:
                    layers = ["runtime-layer", "test-layer"]
                else:
                    layers = ["aux-" + image_id[-1]]
                records.append({
                    "Id": image_id,
                    "Config": {"Labels": {
                        "org.opencontainers.image.revision": COMMIT}},
                    "RootFS": {"Layers": layers},
                })
            return subprocess.CompletedProcess(
                command, 0, json.dumps(records), "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"identity_hash": SOURCE}), "")
        if command == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
            return subprocess.CompletedProcess(
                command, 0, "-f docker-compose.sentinel.yml\n", "")
        if command[:2] == ["docker", "compose"]:
            if "sentinel.shadow_service" in command:
                payload = {
                    "schema": "sentinel.shadow-service-preflight/1",
                    "mode": "BROKER_FREE_SHADOW",
                    "status": "NOT_STARTED",
                    "broker_mutations_authorized": False,
                }
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(payload) + "\n", "")
            payload = {
                "transaction_read_only": True,
                "binding": self.publication,
            }
            return subprocess.CompletedProcess(
                command, 0,
                "SENTINEL_DEPLOY_DATA_BINDING=" + json.dumps(payload) + "\n",
                "")
        raise AssertionError("unexpected command: %r" % command)


def _verify(result, *, env=None, host=None, mode="shadow"):
    return deploy.verify_reviewed_validation_bundle(
        result.path, mode=mode, confirmation=result.sha256,
        env=_env() if env is None else env, now=NOW,
        invoke=host or ReadOnlyHost())


def _rewrite_validation_bundle(result, tmp_path, mutate):
    import zipfile

    with zipfile.ZipFile(result.path, "r") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    validation = json.loads(members["validation.json"])
    mutate(validation)
    members["validation.json"] = go.canonical_json_bytes(validation)
    base = {name: payload for name, payload in members.items()
            if name not in {"manifest.json", "SHA256SUMS"}}
    base["manifest.json"] = go._manifest_bytes(base)
    base["SHA256SUMS"] = go._sha_sums(base)
    path = tmp_path / "rewritten-validation.zip"
    digest = go.write_zip_no_clobber(path, base)
    return SimpleNamespace(path=path, sha256=digest)


def test_reviewed_shadow_bundle_binds_exact_clean_head_images_model_and_data(tmp_path):
    result = _bundle(tmp_path)
    host = ReadOnlyHost()

    reviewed = _verify(result, host=host)

    assert reviewed.mode == "shadow"
    assert reviewed.source_identity_sha256 == SOURCE
    assert reviewed.shadow_configuration_sha256 == \
        go.shadow_configuration_sha256(_env(), source_identity_sha256=SOURCE)
    assert reviewed.data_publication_sha256 == go._subject_digest(
        "data_publication", go.data_publication_subject_value(PUBLICATION))
    assert all(command[:2] not in (["docker", "tag"], ["docker", "push"])
               and "up" not in command
               for command, _env_value in host.calls)
    compose_envs = [env_value for command, env_value in host.calls
                    if command[:2] == ["docker", "compose"]]
    assert compose_envs
    assert all("ALPACA_API_KEY" not in value for value in compose_envs)
    assert all("ALPACA_SECRET_KEY" not in value for value in compose_envs)


def test_reviewed_dual_bundle_keeps_paper_no_go_but_authorizes_bound_transport(
        tmp_path):
    result = _bundle(tmp_path, dual=True)
    reviewed = _verify(result, mode="dual")

    assert reviewed.mode == "dual"
    assert reviewed.validation["shadow_verdict"] == go.SHADOW_GO
    assert reviewed.validation["dual_run_verdict"] == go.DUAL_RUN_GO
    assert reviewed.validation["paper_execution_verdict"] == go.PAPER_NO_GO
    deploy.verify_reviewed_account_binding(reviewed, "paper-account")
    with pytest.raises(deploy.DeployRefused, match="account"):
        deploy.verify_reviewed_account_binding(reviewed, "other-account")


def test_deployer_independently_refuses_slow_database_health_claim(tmp_path):
    result = _bundle(tmp_path / "original")

    def make_slow(validation):
        health = validation["database_financial_health"]
        measured = health["measured_milliseconds"]
        measured["bounded_sharadar_ingest"] = 7_200_001
        measured["combined_pretrade_work"] = sum(
            measured[name] for name in (
                "bounded_sharadar_ingest",
                "full_forward_decision_replay",
                "warmup_revision_scan"))
        health["deadline_milliseconds"]["measured_remaining_margin"] = (
            35_100_000 - measured["combined_pretrade_work"])

    rewritten = _rewrite_validation_bundle(result, tmp_path, make_slow)
    with pytest.raises(deploy.DeployRefused, match="database financial health"):
        _verify(rewritten)


def test_lineage_preflight_uses_persisted_or_promoted_repodigest_not_local_id(
        tmp_path):
    repo_digest = "sha256:" + "7" * 64
    env = _env(SENTINEL_RUNTIME_IMAGE_DIGEST=repo_digest)
    result = _bundle(tmp_path, env=env)
    host = ReadOnlyHost()

    _verify(result, env=env, host=host)

    lineage_env = next(
        value for command, value in host.calls
        if "sentinel.shadow_service" in command)
    assert RUNTIME != repo_digest
    assert lineage_env["SENTINEL_RUNTIME_IMAGE_REF"] == RUNTIME
    assert lineage_env["SENTINEL_RUNTIME_IMAGE_DIGEST"] == repo_digest
    assert lineage_env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] == \
        go._subject_digest(
            "data_publication", go.data_publication_subject_value(PUBLICATION))


def test_wedged_shadow_lineage_refuses_before_deployment_mutation(tmp_path):
    result = _bundle(tmp_path)
    host = ReadOnlyHost()
    original = host.__call__

    def refused(argv, **kwargs):
        command = [str(item) for item in argv]
        if "sentinel.shadow_service" in command:
            return subprocess.CompletedProcess(command, 2, "", "REFUSED")
        return original(argv, **kwargs)

    with pytest.raises(deploy.DeployRefused, match="not safely resumable"):
        deploy.verify_reviewed_validation_bundle(
            result.path, mode="shadow", confirmation=result.sha256,
            env=_env(), now=NOW, invoke=refused)
    assert all(command[:2] not in (["docker", "tag"], ["docker", "push"])
               and "up" not in command
               for command, _env_value in host.calls)


def test_exact_preopen_recovery_state_is_deploy_preflight_safe(tmp_path):
    result = _bundle(tmp_path)
    host = ReadOnlyHost()
    original = host.__call__

    def recoverable(argv, **kwargs):
        command = [str(item) for item in argv]
        if "sentinel.shadow_service" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema": "sentinel.shadow-service-preflight/1",
                "mode": "BROKER_FREE_SHADOW",
                "status": "RECOVERY_REQUIRED",
                "broker_mutations_authorized": False,
                "recovery_kind": "TRAILING_CANDIDATE",
                "recovery_session": "2026-08-21",
                "execution_session": "2026-08-24",
                "recovery_cutoff_at": "2026-08-24T13:30:00Z",
            }) + "\n", "")
        return original(argv, **kwargs)

    reviewed = deploy.verify_reviewed_validation_bundle(
        result.path, mode="shadow", confirmation=result.sha256,
        env=_env(), now=NOW, invoke=recoverable)

    assert reviewed.mode == "shadow"


@pytest.mark.parametrize(("changed", "message"), [
    ({"SENTINEL_SHADOW_STARTING_CASH": "100001"}, "capital/model/source"),
    ({"SENTINEL_SHADOW_OBSERVATION_ID": "different"}, "capital/model/source"),
    ({"SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY": "EARLY_AND_UNSAFE"},
     "timing policy differs"),
])
def test_changed_shadow_cash_or_observation_id_refuses(tmp_path, changed, message):
    result = _bundle(tmp_path)
    with pytest.raises(deploy.DeployRefused, match=message):
        _verify(result, env=_env(**changed))


def test_changed_publication_or_visible_frontier_refuses(tmp_path):
    result = _bundle(tmp_path)
    changed = dict(PUBLICATION)
    changed["visible_frontier"] = "2026-08-21"
    with pytest.raises(deploy.DeployRefused, match="fingerprint/frontier"):
        _verify(result, host=ReadOnlyHost(publication=changed))


def test_quiesced_recheck_refuses_publication_change_after_initial_review(
        tmp_path):
    result = _bundle(tmp_path)
    host = ReadOnlyHost()
    reviewed = _verify(result, host=host)
    host.publication["visible_frontier"] = "2026-08-21"

    class Runner:
        env = _env()

        def run(self, argv, **kwargs):
            return host(argv, **kwargs)

    deployment = deploy.AutonomousDeploy(
        SimpleNamespace(), Runner(), tmp_path,
        reviewed_validation=reviewed)
    deployment.phase = lambda _text: None

    with pytest.raises(deploy.DeployRefused, match="fingerprint/frontier"):
        deployment.verify_reviewed_shadow_bindings_quiesced()

    assert all("up" not in command for command, _env_value in host.calls)


def test_current_two_source_bundle_cannot_be_promoted_to_paper(tmp_path):
    result = _bundle(tmp_path)
    host = ReadOnlyHost()
    with pytest.raises(deploy.DeployRefused, match="paper gate"):
        _verify(result, host=host, mode="paper")
    assert host.calls == []


def test_review_confirmation_must_be_exact_bundle_digest(tmp_path):
    result = _bundle(tmp_path)
    with pytest.raises(deploy.DeployRefused, match="does not match"):
        deploy.verify_reviewed_validation_bundle(
            result.path, mode="shadow", confirmation="0" * 64,
            env=_env(), now=NOW, invoke=ReadOnlyHost())


def test_partial_review_arguments_refuse_and_no_args_stays_fenced():
    assert deploy.deployment_request(
        mode=None, validation_bundle=None, confirmation=None,
        env=_env(), now=NOW, invoke=ReadOnlyHost()) is None
    with pytest.raises(deploy.DeployRefused, match="one required set"):
        deploy.deployment_request(
            mode="shadow", validation_bundle=None, confirmation=None,
            env=_env(), now=NOW, invoke=ReadOnlyHost())
