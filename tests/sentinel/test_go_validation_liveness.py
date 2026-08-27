from __future__ import annotations

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


def test_launcher_never_runs_mutable_data_preflight_before_certification():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert "sentinel_go_data_preflight.py" not in text
    assert "sentinel_go_phase_controller.py" in text
    assert text.index("sentinel_go_phase_controller.py") < text.index(
        "sentinel_runtime_selection.py promote")


def test_phase_controller_orders_certification_before_single_preparation():
    text = SCRIPT.read_text(encoding="utf-8")
    certification = text.index("_certify_exact_artifacts(")
    preparation = text.index("entry.probe_prevalidation_preparation(")
    parity = text.index("go.probe_active_wealth_parity(")
    assert certification < preparation < parity


def test_already_current_contract_removes_second_vendor_ingest():
    original = controller.go._PREPARATION_CODE
    try:
        controller._install_single_preparation_contract()
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


def test_stable_certification_cache_is_bound_to_exact_images_and_commit():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'payload.get("git_commit") != commit' in text
    assert "summary.complete" in text
    assert "_image_exact" in text
    assert "stable certification: REUSED exact unchanged commit/image evidence" in text


def test_actual_wall_clock_deadline_is_reobserved_after_readiness_work():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SENTINEL_GO_ACTUAL_DEADLINE=" in text
    assert "actual_remaining_to_execution_open_ms" in text
    assert "FOLLOWING_EXECUTION_OPEN_NOT_FUTURE_AT_FINAL_READINESS" in text


def test_command_deadlines_are_enforced_not_post_hoc_only():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess.TimeoutExpired" in text
    assert "SENTINEL_GO_PREPARATION_TIMEOUT_SECONDS" in text
    assert "timeout=timeout" in text


def test_runtime_promotion_refreshes_origin_main_at_final_boundary():
    text = (ROOT / "scripts" / "sentinel_runtime_selection.py").read_text(
        encoding="utf-8")
    assert "_refresh_origin_main()" in text
    assert '["git", "fetch", "--quiet", "origin", "main"]' in text


def test_post_validation_recreates_panel_and_makes_repo_digest_handoff_explicit():
    text = (ROOT / "scripts" / "sentinel_go_post_validate.py").read_text(
        encoding="utf-8")
    assert '"--force-recreate", "sentinel-panel"' in text
    assert "activation_repo_digest_bound" in text
    assert "registry-qualified SENTINEL_RUNTIME_IMAGE_DIGEST" in text
    assert 'run(["docker", "image", "rm", ref])' in text
