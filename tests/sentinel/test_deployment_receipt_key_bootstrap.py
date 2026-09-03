from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_deployment_bootstrap.py"
spec = importlib.util.spec_from_file_location("sentinel_deployment_bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


def _write_env(path: Path, receipt_line: str = "") -> None:
    rows = [
        "SENTINEL_POSTGRES_PASSWORD=database-secret",
        "SENTINEL_BACKUP_DIR=/durable/backup",
        "SHARADAR_API_KEY=sharadar-secret",
    ]
    if receipt_line:
        rows.append(receipt_line)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    path.chmod(0o640)


def _receipt_value(path: Path) -> str:
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(bootstrap.RECEIPT_KEY + "="):
            matches.append(line.split("=", 1)[1])
    assert len(matches) == 1
    return matches[0]


def test_missing_key_is_generated_only_after_no_receipt_ancestry_is_proven(
        tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    observed = {}

    def probe(env):
        candidate = env[bootstrap.RECEIPT_KEY]
        observed["candidate"] = candidate
        assert len(candidate.encode("utf-8")) >= bootstrap.MIN_KEY_BYTES
        assert env["SENTINEL_POSTGRES_PASSWORD"] == "database-secret"
        return bootstrap.SAFE_LEGACY_DATABASE

    result = bootstrap.ensure_publication_receipt_key(
        path, receipt_state_probe=probe)
    assert result == "GENERATED_" + bootstrap.SAFE_LEGACY_DATABASE
    value = _receipt_value(path)
    assert value == observed["candidate"]
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text(encoding="utf-8")
    assert "SENTINEL_POSTGRES_PASSWORD=database-secret" in text
    assert "SHARADAR_API_KEY=sharadar-secret" in text


def test_generated_secret_is_never_printed(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    monkeypatch.setattr(bootstrap, "ENV_PATH", path)
    monkeypatch.setattr(
        bootstrap, "_receipt_ancestry",
        lambda _env: bootstrap.SAFE_FRESH_DATABASE)
    # main() binds the public ensure helper; provide the probe explicitly through
    # a narrow wrapper so this remains a pure host-side unit test.
    original = bootstrap.ensure_publication_receipt_key
    monkeypatch.setattr(
        bootstrap, "ensure_publication_receipt_key",
        lambda selected: original(
            selected,
            receipt_state_probe=lambda _env: bootstrap.SAFE_FRESH_DATABASE))
    assert bootstrap.main(["--env-file", str(path)]) == 0
    value = _receipt_value(path)
    output = capsys.readouterr()
    assert value not in output.out
    assert value not in output.err
    assert "securely persisted" in output.out


def test_existing_key_is_idempotent_and_never_reprobes(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    existing = "a" * 64
    _write_env(path, bootstrap.RECEIPT_KEY + "=" + existing)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)

    def forbidden(_env):
        raise AssertionError("existing key must not touch database ancestry")

    before = path.read_bytes()
    result = bootstrap.ensure_publication_receipt_key(
        path, receipt_state_probe=forbidden)
    assert result == "PRESENT_FILE"
    assert path.read_bytes() == before


def test_authenticated_receipt_ancestry_refuses_rotation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    before = path.read_bytes()
    with pytest.raises(
            bootstrap.BootstrapRefused,
            match="authenticated publication receipts already exist"):
        bootstrap.ensure_publication_receipt_key(
            path,
            receipt_state_probe=lambda _env: bootstrap.AUTHENTICATED_RECEIPTS_EXIST)
    assert path.read_bytes() == before


def test_short_existing_key_refuses_automatic_replacement(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path, bootstrap.RECEIPT_KEY + "=too-short")
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    with pytest.raises(bootstrap.BootstrapRefused, match="refusing automatic rotation"):
        bootstrap.ensure_publication_receipt_key(
            path, receipt_state_probe=lambda _env: bootstrap.SAFE_FRESH_DATABASE)
    assert "too-short" in path.read_text(encoding="utf-8")


def test_placeholder_is_treated_as_unprovisioned(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(
        path,
        bootstrap.RECEIPT_KEY
        + "=replace-with-an-independent-long-random-value")
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    result = bootstrap.ensure_publication_receipt_key(
        path,
        receipt_state_probe=lambda _env: bootstrap.SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS)
    assert result.startswith("GENERATED_")
    assert "replace-with-an-independent" not in path.read_text(encoding="utf-8")


def test_symlink_env_is_refused_without_following_target(tmp_path, monkeypatch):
    target = tmp_path / "real.env"
    _write_env(target)
    link = tmp_path / ".env"
    link.symlink_to(target)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    with pytest.raises(bootstrap.BootstrapRefused, match="non-symlink"):
        bootstrap.ensure_publication_receipt_key(
            link, receipt_state_probe=lambda _env: bootstrap.SAFE_FRESH_DATABASE)
    assert bootstrap.RECEIPT_KEY not in target.read_text(encoding="utf-8")


def test_duplicate_receipt_key_assignments_are_refused(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(bootstrap.RECEIPT_KEY + "=\n")
        handle.write(bootstrap.RECEIPT_KEY + "=\n")
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    with pytest.raises(bootstrap.BootstrapRefused, match="more than once"):
        bootstrap.ensure_publication_receipt_key(
            path, receipt_state_probe=lambda _env: bootstrap.SAFE_FRESH_DATABASE)


def test_supported_launchers_bootstrap_before_compose_dependent_work():
    go = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert go.index("sentinel_deployment_bootstrap.py") < go.index(
        "sentinel_runtime_selection.py preflight")
    assert go.index("sentinel_deployment_bootstrap.py") < go.index(
        "sentinel_go_readonly_data_preflight.py")

    deploy = (ROOT / "scripts" / "sentinel-autonomous-deploy.sh").read_text(
        encoding="utf-8")
    assert deploy.index("sentinel_deployment_bootstrap.py") < deploy.index(
        "sentinel-state-volume-permissions.sh")
    assert deploy.index("sentinel_deployment_bootstrap.py") < deploy.index(
        "sentinel_autonomous_deploy_bootstrap.py")
