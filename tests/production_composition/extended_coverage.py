"""Executable evidence map for the second-layer production fault campaign."""
from __future__ import annotations

EXTENDED_EVIDENCE = {
    "cold_reboot": (
        "tests/production_composition/test_reboot_restore_upgrade.py",
        "tests/production_composition/test_lock_process_boundary.py",
    ),
    "restore_upgrade_go": (
        "tests/production_composition/test_reboot_restore_upgrade.py",
        "tests/internal_state/test_physical.py",
        ".github/workflows/production-composition-harness.yml",
    ),
    "phase_boundary_kill": (
        "tests/production_composition/test_phase_boundary_kills.py",
        "tests/production_composition/test_operator_entry_process.py",
        "tests/production_composition/test_phase_c_authority_process.py",
    ),
    "filesystem_nas_fault": (
        "tests/production_composition/test_filesystem_evidence_faults.py",
        "tests/backup/test_runtime_backup_authority.py",
    ),
    "docker_lifecycle_fault": (
        "tests/production_composition/test_docker_network_faults.py",
        "tests/production_composition/test_runtime_handoff_atomicity.py",
        "tools/production_composition_harness.py",
    ),
    "concurrency_cross_actor": (
        "tests/production_composition/test_cross_actor_concurrency.py",
        "tests/production_composition/test_lock_process_boundary.py",
    ),
    "clock_calendar_boundary": (
        "tests/production_composition/test_clock_calendar_faults.py",
        "tests/scripts/test_issue240_go_weekend_publication.py",
    ),
    "network_auth_partial": (
        "tests/production_composition/test_docker_network_faults.py",
        "tests/production_composition/test_broker_network_faults.py",
        "tests/production_composition/test_ci_runtime_boundary.py",
    ),
    "promotion_handoff_atomicity": (
        "tests/production_composition/test_runtime_handoff_atomicity.py",
        "tests/production_composition/test_filesystem_evidence_faults.py",
        "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
    ),
    "evidence_survivability": (
        "tests/production_composition/test_filesystem_evidence_faults.py",
        "tests/production_composition/test_go_preparation_authority.py",
        "tests/scripts/test_sentinel_go_validate.py",
    ),
}
