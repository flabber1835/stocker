from __future__ import annotations

from contextlib import contextmanager
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


def test_bootstrap_uses_canonical_corpus_lock_key():
    from sentinel.feed import _publication_impl

    assert bootstrap.CORPUS_LOCK_KEY == _publication_impl.CORPUS_LOCK_KEY


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
        return bootstrap.SAFE_FRESH_DATABASE

    result = bootstrap.ensure_publication_receipt_key(
        path, receipt_state_probe=probe)
    assert result == "GENERATED_" + bootstrap.SAFE_FRESH_DATABASE
    value = _receipt_value(path)
    assert value == observed["candidate"]
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text(encoding="utf-8")
    assert "SENTINEL_POSTGRES_PASSWORD=database-secret" in text
    assert "SHARADAR_API_KEY=sharadar-secret" in text


def test_generation_guard_remains_held_through_durable_key_write(
        tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    events = []

    @contextmanager
    def guarded(_env):
        events.append("authority-locked")
        yield bootstrap.SAFE_FRESH_DATABASE
        events.append("authority-unlocked")

    original = bootstrap._atomic_set_key

    def observed_write(selected, generated):
        events.append("key-write")
        assert events == ["authority-locked", "key-write"]
        return original(selected, generated)

    monkeypatch.setattr(bootstrap, "_receipt_ancestry_guard", guarded)
    monkeypatch.setattr(bootstrap, "_atomic_set_key", observed_write)

    result = bootstrap.ensure_publication_receipt_key(path)
    assert result == "GENERATED_" + bootstrap.SAFE_FRESH_DATABASE
    assert events == [
        "authority-locked", "key-write", "authority-unlocked"]


def test_valid_key_established_after_probe_is_adopted_not_overwritten(
        tmp_path, monkeypatch):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    concurrent = "b" * 64

    def probe(_env):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(bootstrap.RECEIPT_KEY + "=" + concurrent + "\n")
        return bootstrap.SAFE_FRESH_DATABASE

    result = bootstrap.ensure_publication_receipt_key(
        path, receipt_state_probe=probe)
    assert result == "PRESENT_FILE_CONCURRENT"
    assert _receipt_value(path) == concurrent
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_generated_secret_is_never_printed(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    _write_env(path)
    monkeypatch.delenv(bootstrap.RECEIPT_KEY, raising=False)
    monkeypatch.setattr(bootstrap, "ENV_PATH", path)
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


def test_publication_history_without_receipt_authority_is_ambiguous(monkeypatch):
    monkeypatch.setattr(
        bootstrap, "_psql",
        lambda _env, _args, _sql: "1:0:0")
    with pytest.raises(
            bootstrap.BootstrapRefused,
            match="cannot distinguish a verified pre-receipt database"):
        bootstrap._receipt_ancestry_ready({}, [])


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


def test_known_postgres_placeholder_cannot_initialize_database():
    with pytest.raises(bootstrap.BootstrapRefused, match="known credential"):
        bootstrap._require_probe_prerequisites({
            "SENTINEL_POSTGRES_PASSWORD": "replace-with-a-long-random-value",
            "SENTINEL_BACKUP_DIR": "/durable/backup",
        })


def test_backup_durability_is_proven_before_postgres_start(monkeypatch):
    events = []
    monkeypatch.setattr(
        bootstrap, "_require_probe_prerequisites",
        lambda _env: events.append("prerequisites"))
    monkeypatch.setattr(
        bootstrap, "_require_backup_target",
        lambda _env: events.append("backup"))
    monkeypatch.setattr(
        bootstrap, "_compose_args",
        lambda _env: events.append("compose") or ["-f", "compose.yml"])
    monkeypatch.setattr(
        bootstrap, "_ensure_postgres_ready",
        lambda _env, _args: events.append("postgres"))

    @contextmanager
    def lock(_env, _args):
        events.append("lock")
        yield

    monkeypatch.setattr(bootstrap, "_publication_authority_lock", lock)
    monkeypatch.setattr(
        bootstrap, "_psql",
        lambda _env, _args, _sql: events.append("query") or "0:0:0")
    assert bootstrap._receipt_ancestry({}) == bootstrap.SAFE_FRESH_DATABASE
    assert events[:5] == [
        "prerequisites", "backup", "compose", "postgres", "lock"]


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
