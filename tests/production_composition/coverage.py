"""Executable evidence map for every production composition authority edge."""
from __future__ import annotations

ADJACENT_GO_SUITE = (
    "tests/scripts/test_sentinel_go_validate.py",
    "tests/scripts/test_sentinel_go_ci_runtime.py",
    "tests/scripts/test_sentinel_ci_certification_verify.py",
    "tests/scripts/test_sentinel_ci_certification_verify_redirect.py",
    "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    "tests/scripts/test_sentinel_bringup_entrypoint.py",
    "tests/scripts/test_sentinel_env_writer_serialization.py",
    "tests/scripts/test_issue240_go_weekend_publication.py",
)

EDGE_EVIDENCE = {
    "operator_to_lock": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/production_composition/test_lock_process_boundary.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
    "lock_to_verified_entry": (
        "tests/production_composition/test_lock_process_boundary.py",
        "tests/production_composition/test_phase_c_authority_process.py",
        "tests/production_composition/test_preparation_diagnostics.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
    "env_file_to_shell": (
        "tests/production_composition/test_env_process_boundary.py",
        "tests/production_composition/test_phase_c_authority_process.py",
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_env_writer_serialization.py",
    ),
    "shell_to_ci_verifier": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/production_composition/test_ci_runtime_boundary.py",
        "tests/scripts/test_sentinel_ci_certification_verify.py",
    ),
    "ci_artifact_to_registry": (
        "tests/production_composition/test_ci_runtime_boundary.py",
        "tests/scripts/test_sentinel_ci_certification_verify.py",
        "tests/scripts/test_sentinel_ci_certification_verify_redirect.py",
    ),
    "registry_to_local_image": (
        "tests/production_composition/test_ci_runtime_boundary.py",
        "tests/scripts/test_sentinel_go_ci_runtime.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
    "certification_to_preparation": (
        "tests/production_composition/test_phase_c_authority_process.py",
        "tests/production_composition/test_preparation_diagnostics.py",
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
    "lock_to_preparation": (
        "tests/production_composition/test_phase_c_authority_process.py",
        "tests/production_composition/test_lock_process_boundary.py",
        "tests/production_composition/test_preparation_diagnostics.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
    "backup_to_database_mutation": (
        "tests/backup/test_runtime_backup_authority.py",
        "tests/internal_state/test_physical.py",
        ".github/workflows/backup-reliability.yml",
    ),
    "certified_identity_to_feed_binding": (
        "tests/production_composition/test_phase_c_authority_process.py",
        "tests/production_composition/test_preparation_diagnostics.py",
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/internal_state/test_contract.py",
    ),
    "preparation_to_publication": (
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/scripts/test_issue240_go_weekend_publication.py",
        "tests/internal_state/test_physical.py",
    ),
    "publication_to_parity": (
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
        "tests/internal_state/test_contract.py",
    ),
    "publication_to_readiness": (
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/scripts/test_issue240_go_weekend_publication.py",
    ),
    "readiness_to_target_proof": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    ),
    "target_proof_to_promotion": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_go_ci_runtime.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    ),
    "promotion_to_pointer": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_go_ci_runtime.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    ),
    "pointer_to_panel": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
        "tests/scripts/test_sentinel_bringup_entrypoint.py",
    ),
    "panel_to_handoff": (
        "tests/production_composition/test_operator_entry_process.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    ),
    "failure_to_bundle": (
        "tests/production_composition/test_preparation_diagnostics.py",
        "tests/scripts/test_sentinel_go_validate.py",
        "tests/scripts/test_go_certification_observability.py",
    ),
    "restore_upgrade_to_go": (
        "tests/internal_state/test_physical.py",
        "tests/internal_state/test_contract.py",
        "tests/backup/test_runtime_backup_authority.py",
        ".github/workflows/internal-state-harness.yml",
        ".github/workflows/backup-reliability.yml",
    ),
}

REQUIRED_EXTERNAL_WORKFLOWS = (
    ".github/workflows/sentinel-safety.yml",
    ".github/workflows/internal-state-harness.yml",
    ".github/workflows/backup-reliability.yml",
)
