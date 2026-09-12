from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

VARIANTS = (
    "happy",
    "missing",
    "stale",
    "corrupt",
    "crash_before",
    "crash_after",
    "retry",
    "concurrent",
)


@dataclass(frozen=True)
class AuthorityEdge:
    name: str
    source: str
    target: str
    authority: str
    source_path: str
    anchors: tuple[str, ...]
    execution_class: str
    p0: bool = False


@dataclass(frozen=True)
class Scenario:
    edge: AuthorityEdge
    variant: str

    @property
    def scenario_id(self) -> str:
        return f"{self.edge.name}:{self.variant}"

    @property
    def must_advance(self) -> bool:
        return self.variant in {"happy", "retry"}

    @property
    def must_have_reason(self) -> bool:
        return not self.must_advance


EDGES = (
    AuthorityEdge(
        "operator_to_lock", "sentinel-go-validate.sh", "sentinel_go_lock.py",
        "kernel flock + inherited fd", "scripts/sentinel-go-validate.sh",
        ('exec "$PYTHON" scripts/sentinel_go_lock.py', "SENTINEL_GO_LOCK_HELD"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "lock_to_verified_entry", "sentinel_go_lock.py", "verified GO entry",
        "locked open-file description + one-run token", "scripts/sentinel_go_lock.py",
        ("pass_fds=", "RUN_TOKEN_ENV", "LOCK_FD_ENV", "LOCK_HELD_ENV"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "env_file_to_shell", ".env", "Bash process environment",
        "strict parsed environment", "scripts/sentinel-env.sh",
        ("sentinel_env.py --records", 'export "$record"'),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "shell_to_ci_verifier", "Bash process environment", "GitHub certification verifier",
        "GitHub read credential", "scripts/sentinel_ci_certification_verify.py",
        ("SENTINEL_GITHUB_READ_TOKEN", "GITHUB_TOKEN"),
        "external_network", True,
    ),
    AuthorityEdge(
        "ci_artifact_to_registry", "verified GitHub artifact", "GHCR digest",
        "exact protected software certificate", "scripts/sentinel_go_ci_runtime.py",
        ("verify_current", "certified_image", "registry_digest"),
        "external_network", True,
    ),
    AuthorityEdge(
        "registry_to_local_image", "GHCR digest", "local immutable image",
        "digest + revision binding", "scripts/sentinel_go_ci_runtime.py",
        ("docker", "pull", "local_image_id"),
        "docker", True,
    ),
    AuthorityEdge(
        "certification_to_preparation", "certified exact image", "Phase C",
        "verified orchestration capability", "scripts/sentinel_go_validate_entry.py",
        ("authorize_verified_orchestration", "_VERIFIED_ORCHESTRATION",
         "probe_prevalidation_preparation"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "lock_to_preparation", "inherited lifecycle flock", "Phase C",
        "re-proven mutation lock", "scripts/sentinel_go_validate_entry.py",
        ("lifecycle_lock_is_held(env)", "GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "backup_to_database_mutation", "restore horizon", "schema/feed mutation",
        "backup durability authority", "scripts/sentinel_go_validate_entry.py",
        ("backup_guard.require_writes_permitted", "SCHEMA_MIGRATION"),
        "docker_postgres", True,
    ),
    AuthorityEdge(
        "certified_identity_to_feed_binding", "commit + image digest", "feed writer",
        "feed-bound mutation identity", "scripts/sentinel_go_validate_entry.py",
        ("sentinel_feed_gate.py", "FEED_BINDING_UNAVAILABLE", "_FEED_ENV_KEYS"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "preparation_to_publication", "bounded source catch-up", "current publication",
        "publication completeness", "scripts/sentinel_go_24x7_entry.py",
        ("outage_recovery.catch_up", "publication_current", "bounded_sharadar_daily"),
        "docker_postgres", True,
    ),
    AuthorityEdge(
        "publication_to_parity", "held publication", "Wealth Core differential",
        "read-only repeatable-read publication pin", "scripts/sentinel_go_validate.py",
        ("probe_active_wealth_parity", "repeatable read", "first_divergence"),
        "docker_postgres",
    ),
    AuthorityEdge(
        "publication_to_readiness", "current publication", "Sharadar readiness",
        "read-only readiness proof", "scripts/sentinel_go_validate.py",
        ("probe_sharadar_readiness", "BEGIN TRANSACTION READ ONLY"),
        "docker_postgres",
    ),
    AuthorityEdge(
        "readiness_to_target_proof", "GO gate set", "requested-target proof",
        "one-run target verdict", "scripts/sentinel_go_verified_entry.py",
        ("_write_run_pass", "requested_target", "current_run_token"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "target_proof_to_promotion", "requested-target proof", "runtime promotion",
        "same-run token + same boot + exact commit", "scripts/sentinel_go_promote.py",
        ("_current_run_target_pass", "run_token_sha256", "host_boot_id_sha256"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "promotion_to_pointer", "certified local/registry image", "runtime selector",
        "atomic exact-image selection", "scripts/sentinel_go_promote.py",
        ("_write_pointer", "validated runtime pointer verification failed"),
        "filesystem", True,
    ),
    AuthorityEdge(
        "pointer_to_panel", "runtime selector", "running Sentinel panel",
        "exact promoted image", "scripts/sentinel_go_post_validate.py",
        ("recreate_panel", "running_panel_image_id", "--force-recreate"),
        "docker", True,
    ),
    AuthorityEdge(
        "panel_to_handoff", "verified running panel", "deployment handoff",
        "atomic evidence-only handoff", "scripts/sentinel_go_post_validate.py",
        ("atomic_json", "validated-artifact-handoff", "broker_authority_granted"),
        "filesystem",
    ),
    AuthorityEdge(
        "failure_to_bundle", "causal production refusal", "GO evidence bundle",
        "stable machine-readable diagnostic", "scripts/sentinel_go_phase_controller.py",
        ("failure_reason_code", "_classify_preparation_failure", "PreparationView"),
        "host_subprocess", True,
    ),
    AuthorityEdge(
        "restore_upgrade_to_go", "supported persisted NAS state", "current GO lifecycle",
        "upgrade compatibility", "docs/internal-state-harness.md",
        ("physical restore", "Deployment-level paper/GO entry points"),
        "docker_postgres", True,
    ),
)


def scenarios() -> tuple[Scenario, ...]:
    return tuple(Scenario(edge, variant) for edge in EDGES for variant in VARIANTS)


def source_text(edge: AuthorityEdge) -> str:
    return (ROOT / edge.source_path).read_text(encoding="utf-8")


def missing_anchors(edge: AuthorityEdge) -> tuple[str, ...]:
    text = source_text(edge)
    return tuple(anchor for anchor in edge.anchors if anchor not in text)


def require_complete_catalog(items: Iterable[Scenario]) -> None:
    items = tuple(items)
    expected = {(edge.name, variant) for edge in EDGES for variant in VARIANTS}
    actual = {(item.edge.name, item.variant) for item in items}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise AssertionError(f"composition matrix mismatch missing={missing} extra={extra}")
    ids = [item.scenario_id for item in items]
    if len(ids) != len(set(ids)):
        raise AssertionError("composition scenario ids are not unique")
