from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile.sentinel"
AUTHORIZED = ROOT / "Dockerfile.sentinel-authorized"


def _position(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position >= 0, "missing Docker layering contract marker: %s" % needle
    return position


def test_stable_base_dependency_and_identity_layers_precede_app_source():
    text = DOCKERFILE.read_text(encoding="utf-8")
    base = _position(text, "FROM python:3.12-slim@sha256:")
    locks = _position(
        text, "COPY sentinel/requirements.txt sentinel/requirements.lock /tmp/req/")
    dependency_install = _position(text, "pip install --no-cache-dir --require-hashes")
    shared = _position(text, "COPY shared/ /shared/")
    shared_install = _position(
        text, "pip install --no-cache-dir --no-build-isolation --no-deps /shared/")
    runtime_user = _position(text, "groupadd --system --gid 10001 sentinel")
    frozen_rule = _position(text, "COPY docs/sentinel-handoff/00_README/")
    app_source = _position(text, "COPY sentinel/ /app/sentinel/")

    assert base < locks < dependency_install < shared < shared_install
    assert shared_install < runtime_user < frozen_rule < app_source


def test_authorized_runtime_inherits_the_complete_ordinary_layer_graph():
    text = AUTHORIZED.read_text(encoding="utf-8")
    assert "ARG SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest" in text
    assert "FROM ${SENTINEL_RUNTIME_BASE_IMAGE}" in text


def test_dependency_layer_changes_only_after_lock_copy_boundary():
    text = DOCKERFILE.read_text(encoding="utf-8")
    lock_copy = _position(
        text, "COPY sentinel/requirements.txt sentinel/requirements.lock /tmp/req/")
    source_copy = _position(text, "COPY sentinel/ /app/sentinel/")
    assert lock_copy < source_copy
    between = text[lock_copy:source_copy]
    assert "COPY sentinel/ /app/sentinel/" not in between
