import os
from pathlib import Path


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
DOCKERFILE = ROOT / "Dockerfile.sentinel"


def _position(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position >= 0, "missing Docker layering contract marker: %s" % needle
    return position


def test_stable_layers_precede_commit_identity_and_app_source():
    text = DOCKERFILE.read_text(encoding="utf-8")
    base = _position(text, "FROM python:3.12-slim@sha256:")
    locks = _position(
        text, "COPY sentinel/requirements.txt sentinel/requirements.lock /tmp/req/")
    dependency_install = _position(text, "pip install --no-cache-dir --require-hashes")
    shared = _position(text, "COPY shared/ /shared/")
    shared_install = _position(
        text, "pip install --no-cache-dir --no-build-isolation --no-deps /shared/")
    runtime_user = _position(text, "groupadd --system --gid 10001 sentinel")
    source_arg = _position(text, "ARG SOURCE_GIT_SHA=unknown")
    source_label = _position(
        text, "LABEL org.opencontainers.image.revision=${SOURCE_GIT_SHA}")
    source_env = _position(
        text, "ENV SENTINEL_IMAGE_SOURCE_REVISION=${SOURCE_GIT_SHA}")
    frozen_rule = _position(text, "COPY docs/sentinel-handoff/00_README/")
    app_source = _position(text, "COPY sentinel/ /app/sentinel/")

    assert base < locks < dependency_install < shared < shared_install
    assert shared_install < runtime_user < source_arg < source_label < source_env
    assert source_env < frozen_rule < app_source


def test_exact_source_identity_is_still_baked_into_the_final_image():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert text.count("ARG SOURCE_GIT_SHA=unknown") == 1
    assert text.count("LABEL org.opencontainers.image.revision=${SOURCE_GIT_SHA}") == 1
    assert text.count("ENV SENTINEL_IMAGE_SOURCE_REVISION=${SOURCE_GIT_SHA}") == 1


def test_one_runtime_contains_broker_code_and_execution_capability():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY sentinel/ /app/sentinel/" in text
    assert "COPY shared/ /shared/" in text
    assert "COPY deploy/sentinel-authorized-runtime-v1" in text
    assert "authorized-runtime-capability-v1" in text
    assert "rm /app/sentinel/cli/authorized_routes.py" not in text
    assert "rm /shared/stock_strategy_shared/broker/alpaca.py" not in text
    assert (ROOT / "sentinel" / "cli" / "authorized_routes.py").is_file()
    assert (ROOT / "sentinel" / "execution" / "alpaca.py").is_file()
    assert (ROOT / "shared" / "stock_strategy_shared" / "broker" / "alpaca.py").is_file()


def test_default_runtime_command_remains_non_trading():
    text = DOCKERFILE.read_text(encoding="utf-8")
    directives = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert 'ENTRYPOINT ["python", "-m", "sentinel"]' in directives
    assert 'CMD ["status"]' in directives


def test_dependency_layer_changes_only_after_lock_copy_boundary():
    text = DOCKERFILE.read_text(encoding="utf-8")
    lock_copy = _position(
        text, "COPY sentinel/requirements.txt sentinel/requirements.lock /tmp/req/")
    source_identity = _position(text, "ARG SOURCE_GIT_SHA=unknown")
    source_copy = _position(text, "COPY sentinel/ /app/sentinel/")
    assert lock_copy < source_identity < source_copy
    stable = text[lock_copy:source_identity]
    assert "SOURCE_GIT_SHA" not in stable
    assert "COPY sentinel/ /app/sentinel/" not in stable
