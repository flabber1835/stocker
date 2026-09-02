from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        "test_script_" + name.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authorized_runtime_requires_executable_capability(
        tmp_path, monkeypatch) -> None:
    from sentinel.cli import _shared

    marker = tmp_path / "authorized-runtime-v1"
    marker.write_bytes(_shared.AUTHORIZED_RUNTIME_MARKER_BYTES)
    capability = tmp_path / "authorized-runtime-capability-v1"
    capability.write_text(
        "#!/bin/sh\nprintf 'sentinel-authorized-capability/1\\n'\n")
    capability.chmod(0o755)

    monkeypatch.setattr(_shared, "AUTHORIZED_RUNTIME_MARKER", marker)
    monkeypatch.setattr(_shared, "AUTHORIZED_RUNTIME_CAPABILITY", capability)
    monkeypatch.setenv(
        _shared.AUTHORIZED_RUNTIME_ENV, _shared.AUTHORIZED_RUNTIME_VALUE)

    assert _shared.require_authorized_runtime("automation-run") is None

    capability.unlink()
    assert _shared.require_authorized_runtime("automation-run") == \
        _shared.EXIT_CONFIG


def test_env_writer_refuses_symlink_destination_even_with_force(
        tmp_path) -> None:
    module = _load_script("sentinel-env-from-stocker.py")
    source = tmp_path / "legacy.env"
    source.write_text("SHARADAR_API_KEY=retained-secret\n")
    victim = tmp_path / "victim"
    victim.write_text("ORIGINAL\n")
    destination = tmp_path / ".env"
    destination.symlink_to(victim)

    rc = module.main([
        "--from", str(source), "--to", str(destination), "--force"])

    assert rc == 2
    assert victim.read_text() == "ORIGINAL\n"
    assert destination.is_symlink()


def test_env_writer_creates_mode_0600_from_first_publication(tmp_path) -> None:
    module = _load_script("sentinel-env-from-stocker.py")
    source = tmp_path / "legacy.env"
    source.write_text("SHARADAR_API_KEY=retained-secret\n")
    destination = tmp_path / ".env"

    assert module.main([
        "--from", str(source), "--to", str(destination)]) == 0
    assert destination.stat().st_mode & 0o777 == 0o600


def test_sep_interrupted_backed_up_promotion_restores_prior_generation(
        tmp_path) -> None:
    module = _load_script("sentinel-split-sep-bulk.py")
    out = tmp_path / "sep"
    out.mkdir()
    staging = out / ".sentinel-sep-staging.deadbeef"
    staging.mkdir()
    backup_dir = out / ".sentinel-sep-backup.deadbeef"
    backup_dir.mkdir()

    final = out / "SHARADAR_SEP_2007.csv.gz"
    backup = backup_dir / final.name
    staged = staging / final.name
    final.write_bytes(b"PARTIAL-NEW")
    backup.write_bytes(b"PRIOR-GENERATION")
    staged.write_bytes(b"NEW-STAGED")

    marker = out / module.PROMOTION_MARKER
    marker.write_text(json.dumps({
        "schema": module.PROMOTION_SCHEMA,
        "phase": "BACKED_UP",
        "token": "deadbeef",
        "staging": str(staging),
        "entries": [{
            "final": str(final),
            "staged": str(staged),
            "backup": str(backup),
            "had_original": True,
            "sha256": "0" * 64,
        }],
    }))

    module._recover_promotion(out)

    assert final.read_bytes() == b"PRIOR-GENERATION"
    assert not marker.exists()
    assert not staging.exists()


def test_administrative_wrapper_exposes_only_inert_broker_identity() -> None:
    from sentinel import administrative_authority
    from sentinel.guarded_administration import (
        AdministrativeAccessGrant,
        AdministrativeBrokerGuard,
        GuardedAdministrativeBroker,
    )

    class RawAdapter:
        name = "alpaca"

        def submit_order(self):
            raise AssertionError("raw adapter escaped guard")

    class Inner:
        adapter = RawAdapter()

        def has_credentials(self):
            return True

    inner = Inner()
    wrapped = GuardedAdministrativeBroker(
        inner=inner,
        grant=AdministrativeAccessGrant(
            operation=administrative_authority.ADMIN_INSPECT,
            deployment_id="deployment", broker_account_id="account",
            takeover_epoch=1),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, _operation, _result: None))

    assert wrapped.adapter.name == "alpaca"
    assert wrapped.adapter is not inner.adapter
    assert not hasattr(wrapped.adapter, "submit_order")


def test_restored_namespace_cannot_use_ordinary_pagination_as_negative_space(
        monkeypatch) -> None:
    from sentinel.execution import recovered_order_policy as policy

    monkeypatch.setenv(policy.AUTHORITY_ENV, policy.STRICT_AUTHORITY)

    class Deferred(RuntimeError):
        pass

    calls = []
    fake_alpaca = SimpleNamespace(
        strict_advance=lambda _conn, through: calls.append(through) or through,
        RestoreGradeIncreaseDeferred=Deferred,
    )
    policy.install_alpaca_restore_guard(fake_alpaca)

    class Cursor:
        def __init__(self, epoch):
            self.epoch = epoch

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql, _params=None):
            return None

        def fetchone(self):
            return (self.epoch,)

    class Conn:
        def __init__(self, epoch):
            self.epoch = epoch

        def cursor(self):
            return Cursor(self.epoch)

    with pytest.raises(Deferred, match="restore-grade order completeness"):
        fake_alpaca.strict_advance(Conn(2), "through")
    assert calls == []

    assert fake_alpaca.strict_advance(Conn(1), "through") == "through"
    assert calls == ["through"]
