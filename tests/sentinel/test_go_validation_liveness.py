from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_phase_controller.py"
spec = importlib.util.spec_from_file_location("sentinel_go_phase_controller", SCRIPT)
controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)

ENTRY_SCRIPT = ROOT / "scripts" / "sentinel_go_phase_entry.py"
entry_spec = importlib.util.spec_from_file_location("sentinel_go_phase_entry", ENTRY_SCRIPT)
phase_entry = importlib.util.module_from_spec(entry_spec)
assert entry_spec.loader is not None
sys.modules[entry_spec.name] = phase_entry
entry_spec.loader.exec_module(phase_entry)

VERIFIED_SCRIPT = ROOT / "scripts" / "sentinel_go_verified_entry.py"
verified_spec = importlib.util.spec_from_file_location(
    "sentinel_go_verified_entry_test", VERIFIED_SCRIPT)
verified = importlib.util.module_from_spec(verified_spec)
assert verified_spec.loader is not None
sys.modules[verified_spec.name] = verified
verified_spec.loader.exec_module(verified)


def test_launcher_serializes_and_uses_guarded_verified_entry():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert "sentinel_go_data_preflight.py" not in text
    assert "scripts/sentinel_go_lock.py" in text
    assert 'scripts/sentinel_go_verified_entry.py "$@"' in text
    assert 'scripts/sentinel_go_promote.py "$@"' in text
    assert text.index("sentinel_go_verified_entry.py") < text.index(
        "sentinel_go_promote.py")
    assert 'if [ "$VALIDATION_RC" -ne 0 ]' in text


def test_host_go_lock_spans_child_lifecycle_and_is_provable_at_membrane():
    text = (ROOT / "scripts" / "sentinel_go_lock.py").read_text(encoding="utf-8")
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in text
    assert 'env[LOCK_HELD_ENV] = "1"' in text
    assert 'env[LOCK_FD_ENV] = str(handle.fileno())' in text
    assert "lifecycle_lock_is_held" in text
    assert "os.fstat(fd)" in text
    assert "another Sentinel GO validation is already running" in text
    assert "pass_fds=(handle.fileno(),)" in text


def test_phase_controller_orders_certification_before_single_preparation():
    text = SCRIPT.read_text(encoding="utf-8")
    certification = text.index("_certify_exact_artifacts(")
    preparation = text.index("entry.probe_prevalidation_preparation(")
    parity = text.index("go.probe_active_wealth_parity(")
    assert certification < preparation < parity


def test_failed_certification_cannot_reach_mutable_preparation():
    original = phase_entry._ORIGINAL_PREPARATION
    phase_entry._PHASE["certified"] = False
    phase_entry._PHASE["prepared"] = False

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mutable preparation was called after failed certification")

    phase_entry._ORIGINAL_PREPARATION = forbidden
    try:
        result = phase_entry._preparation_guarded(
            object(), env={}, runtime_ref="sha256:" + "1" * 64,
            commit="a" * 40)
    finally:
        phase_entry._ORIGINAL_PREPARATION = original
    assert result.status == controller.go.NOT_PROVEN
    assert result.schema_migration_attempted is False
    assert result.bounded_sharadar_daily_attempted is False


def test_failed_preparation_short_circuits_expensive_readiness():
    entry_text = ENTRY_SCRIPT.read_text(encoding="utf-8")
    assert 'if not _PHASE["prepared"]' in entry_text
    assert '"wealth_core_nas_parity", controller.go.NOT_PROVEN' in entry_text
    assert '"sharadar_readiness", controller.go.NOT_PROVEN' in entry_text
    assert 'reason="PREPARATION_NOT_PASS"' in entry_text


def test_already_current_contract_is_source_owned_and_has_no_second_ingest():
    original = controller.go._PREPARATION_CODE
    try:
        phase_entry._install_reviewed_preparation_contract()
        code = controller.go._PREPARATION_CODE
        marker = "if recovered.mode == 'ALREADY_CURRENT':"
        start = code.index(marker)
        end = code.index("elif recovered.mode == 'RETAINED_FULL_RESEED':", start)
        block = code[start:end]
        assert "ingest.daily" not in block
        assert "pass" in block
    finally:
        controller.go._PREPARATION_CODE = original


def test_mutation_refusal_reason_codes_distinguish_local_from_source_authority():
    local = (
        "sentinel.feed.maintenance_impl.SharadarMutationRefused: "
        "source cursor sharadar-sep-lastupdated:v1 has an unknown durable state shape")
    source = (
        "sentinel.feed.maintenance_impl.SharadarMutationRefused: "
        "SEP mutation ABC/2026-08-20 has no permanent identity; refusing to advance")
    assert controller._classify_preparation_failure(local)[0] == "LOCAL_CURSOR_CORRUPT"
    assert controller._classify_preparation_failure(source)[0] == "SOURCE_IDENTITY_UNRESOLVED"


def test_mutation_refusal_detail_never_echoes_secret_or_url_shaped_text():
    code, detail = controller._classify_preparation_failure(
        "SharadarMutationRefused: https://example.invalid?api_key=secret")
    assert code == "SOURCE_AUTHORITY_REFUSED"
    assert detail is None


def test_requested_target_exit_is_not_shadow_only():
    class Result:
        shadow_verdict = controller.go.SHADOW_GO
        dual_run_verdict = controller.go.DUAL_RUN_NO_GO
        paper_execution_verdict = controller.go.PAPER_NO_GO

    assert controller._target_ok(Result(), controller.TARGET_SHADOW) is True
    assert controller._target_ok(Result(), controller.TARGET_DUAL) is False
    assert controller._target_ok(Result(), controller.TARGET_PAPER) is False


def test_stable_certification_reuse_is_exact_same_boot_and_time_bounded():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'payload.get("git_commit") != commit' in text
    assert "summary.complete" in text
    assert "_image_exact" in text
    assert "stable certification: REUSED exact unchanged commit/image evidence" in text

    entry_text = ENTRY_SCRIPT.read_text(encoding="utf-8")
    assert "ordinary_runtime_image_digest" in entry_text
    assert 'ref = "sentinel-go-runtime:%s" % commit' in entry_text
    assert "host_boot_id_sha256" in entry_text
    assert "MAX_REUSE_AGE = timedelta(hours=24)" in entry_text
    assert "_ordinary_binding_matches" in entry_text
    assert "_load_with_ordinary" in entry_text


def test_promotion_requires_exact_certified_ordinary_image_id():
    text = (ROOT / "scripts" / "sentinel_go_promote.py").read_text(
        encoding="utf-8")
    assert "_certified_ordinary(head)" in text
    assert "observed != expected" in text
    assert "ordinary candidate image id changed after certification" in text
    assert "_refresh_origin_main()" in text


def test_actual_wall_clock_deadline_requires_reviewed_margin():
    class Base:
        complete = True

        def to_dict(self):
            return {"schema": "test", "status": "PASS"}

    minimum = controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS
    observed = phase_entry._utc(datetime.now(timezone.utc))
    too_late = phase_entry.StrictDatabaseHealthView(
        Base(), minimum - 1, observed)
    valid = phase_entry.StrictDatabaseHealthView(
        Base(), minimum + 60_000, observed)
    assert too_late.complete is False
    assert valid.complete is True


def test_supported_database_health_view_keeps_v1_public_schema_exact():
    class Base:
        complete = True

        def to_dict(self):
            return {
                "schema": controller.go.DATABASE_HEALTH_SCHEMA,
                "status": "PASS",
                "runtime_image_digest": "sha256:" + "1" * 64,
            }

    minimum = controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS
    observed = phase_entry._utc(datetime.now(timezone.utc))
    view = verified.DeploymentCompatibleDatabaseHealthView(
        Base(), minimum + 60_000, observed)
    assert view.complete is True
    assert view.to_dict() == Base().to_dict()
    assert "actual_deadline" not in view.to_dict()


def test_go_bundle_lifetime_is_capped_by_remaining_readiness_margin():
    text = ENTRY_SCRIPT.read_text(encoding="utf-8")
    assert "_emit_at_completion" in text
    assert "remaining - controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS" in text
    assert "GO evidence lost its minimum pre-open margin before emission" in text
    assert 'kwargs["valid_for"] = min(' in text


def test_final_paper_account_is_reobserved_after_long_phases():
    text = VERIFIED_SCRIPT.read_text(encoding="utf-8")
    original = text.index("probes = _ORIGINAL_PHASED(")
    fresh = text.index("_final_account_probe(", original)
    replace = text.index('gates["alpaca_paper_account"] = alpaca', fresh)
    assert original < fresh < replace
    assert '"final_paper_account_reobserved": True' in text


def test_early_paper_account_preflight_is_get_only_and_target_aware():
    text = (ROOT / "scripts" / "sentinel_go_account_preflight.py").read_text(
        encoding="utf-8")
    launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    assert "probe_alpaca_account" in text
    assert 'target == "SHADOW"' in text
    assert "parse_known_args" in text
    assert 'scripts/sentinel_go_account_preflight.py "$@"' in launcher
    assert launcher.index("sentinel_go_account_preflight.py") < launcher.index(
        "sentinel_go_verified_entry.py")


def test_command_deadlines_are_enforced_not_post_hoc_only():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess.TimeoutExpired" in text
    assert "SENTINEL_GO_PREPARATION_TIMEOUT_SECONDS" in text
    assert "timeout=timeout" in text


def test_runtime_preflight_uses_same_validated_pointer_precedence_as_compose():
    text = (ROOT / "scripts" / "sentinel_runtime_selection.py").read_text(
        encoding="utf-8")
    assert "def _pointer_digest" in text
    assert 'values["SENTINEL_RUNTIME_IMAGE_REF"] = pointer' in text
    assert "REFUSED: runtime preflight configuration" in text
    assert "validation may build a fresh current candidate" in text


def test_runtime_promotion_refreshes_origin_main_at_final_boundary():
    text = (ROOT / "scripts" / "sentinel_runtime_selection.py").read_text(
        encoding="utf-8")
    assert "_refresh_origin_main()" in text
    assert '["git", "fetch", "--quiet", "origin", "main"]' in text


def test_post_validation_recreates_panel_then_publishes_registry_handoff():
    text = (ROOT / "scripts" / "sentinel_go_post_validate.py").read_text(
        encoding="utf-8")
    assert 'env = phase.controller.go.merged_environment()' in text
    assert '"scripts/sentinel-compose.sh", "--run"' in text
    assert '"--force-recreate", "sentinel-panel"' in text
    assert '"schema": "sentinel.validated-artifact-handoff/2"' in text
    assert '"output_identity_domain": "REGISTRY_REPODIGEST"' in text
    assert '"authorized_compose_requires_repo_digest": True' in text
    assert "Local Docker image IDs are *not* authorized-service RepoDigests" in text
    assert "no automatic image deletion" in text
    assert 'docker", "image", "rm"' not in text
    assert "phase._load_with_ordinary" in text
    assert text.index("recreate_panel(env)") < text.index("atomic_json(OUT, handoff)")


def test_autonomous_deploy_promotes_exact_reviewed_local_ids_to_repo_digests():
    text = (ROOT / "scripts" / "sentinel_autonomous_deploy.py").read_text(
        encoding="utf-8")
    assert '"docker", "tag", reviewed.runtime_image_digest' in text
    assert '"docker", "push", runtime_tag' in text
    assert '"capture-promotion"' in text
    assert '"resolve-promotion"' in text
    assert 'self.runtime_repo_digest, self.runtime_digest = _repo_digest' in text
