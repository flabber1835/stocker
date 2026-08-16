"""Static deployment contracts for the shared Sentinel Compose resolver."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_authorized_and_automation_wrappers_share_host_capability_resolver():
    authorized = _read("scripts/sentinel-authorized-cli.sh")
    automation = _read("scripts/sentinel-automation-compose.sh")

    for text in (authorized, automation):
        assert "scripts/sentinel-compose.sh --automation-overlay --run" in text
        assert "exec docker compose" not in text


def test_no_cpu_resolver_strips_the_authority_overlay_too():
    resolver = _read("scripts/sentinel-compose.sh")

    assert 'AUTOMATION="docker-compose.sentinel-automation.yml"' in resolver
    assert (
        'GENERATED_AUTOMATION="artifacts/compose/'
        'docker-compose.sentinel-automation.nocpu.yml"' in resolver
    )
    assert '"$AUTOMATION" "$GENERATED_AUTOMATION"' in resolver
    assert 'append_automation_overlay "$GENERATED_AUTOMATION"' in resolver


def test_compose_run_propagates_measured_deployment_artifacts():
    resolver = _read("scripts/sentinel-compose.sh")

    assert "RUN_ENV+=(-e SENTINEL_GIT_COMMIT)" in resolver
    assert "RUN_ENV+=(-e SENTINEL_RUNTIME_IMAGE_DIGEST)" in resolver
    assert "RUN_ENV+=(-e SENTINEL_TEST_IMAGE_DIGEST)" in resolver


def test_authorized_image_has_no_mutable_base_default():
    dockerfile = _read("Dockerfile.sentinel-authorized")

    assert "ARG SENTINEL_RUNTIME_BASE_IMAGE\n" in dockerfile
    assert "ARG SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest" not in dockerfile
    assert "FROM ${SENTINEL_RUNTIME_BASE_IMAGE}" in dockerfile
