from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

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


def test_authorized_dispatch_is_absent_from_ordinary_image_layer() -> None:
    ordinary = (ROOT / "Dockerfile.sentinel").read_text()
    authorized = (ROOT / "Dockerfile.sentinel-authorized").read_text()

    assert "RUN rm /app/sentinel/cli/authorized_routes.py" in ordinary
    assert ("COPY sentinel/cli/authorized_routes.py" in authorized
            and "/app/sentinel/cli/authorized_routes.py" in authorized)
    assert "/app/sentinel/execution/alpaca.py" in ordinary
    assert "stock_strategy_shared/broker/alpaca.py" in ordinary
    assert "sentinel/execution/alpaca.py" in authorized
    assert "shared/stock_strategy_shared/broker/alpaca.py" in authorized


def test_marker_and_executable_cannot_replace_authorized_dispatch(
        tmp_path, monkeypatch) -> None:
    from sentinel.cli import _shared
    from sentinel.cli import main as cli

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
    monkeypatch.setattr(cli, "_authorized_handler", lambda _command: None)
    monkeypatch.setattr(
        cli.SentinelConfig, "from_env",
        classmethod(lambda cls: pytest.fail(
            "configuration loaded without an authorized dispatcher")))

    assert cli.main(["automation-run"]) == cli.EXIT_CONFIG


@pytest.mark.asyncio
async def test_direct_sensitive_handler_refuses_without_runtime_surface(
        tmp_path, monkeypatch) -> None:
    from sentinel.cli import _shared, paper

    monkeypatch.delenv(_shared.AUTHORIZED_RUNTIME_ENV, raising=False)
    monkeypatch.setattr(
        _shared, "AUTHORIZED_RUNTIME_MARKER", tmp_path / "missing-marker")
    config = SimpleNamespace(database_url="must-not-be-opened")

    assert await paper._execute_paper_plan(config, SimpleNamespace()) == \
        _shared.EXIT_CONFIG
    assert await paper._execute_paper_plan.__wrapped__(
        config, SimpleNamespace()) == _shared.EXIT_CONFIG


@pytest.mark.parametrize("evidence", [None, [], "text", 7, True])
def test_publication_authority_refuses_every_non_object_evidence(evidence) -> None:
    from sentinel import authority
    from sentinel.execution.authority_gate import publication_row_identity

    row = (
        1, None, None, datetime(2026, 9, 2, tzinfo=timezone.utc),
        None, None, evidence)
    with pytest.raises(authority.AuthorityRefused, match="non-object evidence"):
        publication_row_identity(row)


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
    fingerprint_final = tmp_path / "sep-fingerprint.json"
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
            "backup_sha256": module._sha256(backup),
            "sha256": "0" * 64,
        }],
    }))

    module._recover_promotion(out, fingerprint_final=fingerprint_final)

    assert final.read_bytes() == b"PRIOR-GENERATION"
    assert not marker.exists()
    assert not staging.exists()


def test_sep_rollback_can_restart_after_consuming_one_backup(
        tmp_path, monkeypatch) -> None:
    module = _load_script("sentinel-split-sep-bulk.py")
    out = tmp_path / "sep"
    out.mkdir()
    staging = out / ".sentinel-sep-staging.deadbeef"
    staging.mkdir()
    backup_dir = out / ".sentinel-sep-backup.deadbeef"
    backup_dir.mkdir()
    fingerprint_final = tmp_path / "sep-fingerprint.json"

    entries = []
    for year in (2007, 2008):
        final = out / f"SHARADAR_SEP_{year}.csv.gz"
        staged = staging / final.name
        backup = backup_dir / final.name
        final.write_bytes(f"new-{year}".encode())
        staged.write_bytes(f"staged-{year}".encode())
        backup.write_bytes(f"old-{year}".encode())
        entries.append({
            "final": str(final),
            "staged": str(staged),
            "backup": str(backup),
            "had_original": True,
            "backup_sha256": module._sha256(backup),
            "sha256": module._sha256(staged),
        })
    marker = out / module.PROMOTION_MARKER
    marker.write_text(json.dumps({
        "schema": module.PROMOTION_SCHEMA,
        "phase": "BACKED_UP",
        "token": "deadbeef",
        "staging": str(staging),
        "entries": entries,
    }))

    real_replace = module.os.replace
    interrupted = False

    def replace_then_die(source, destination):
        nonlocal interrupted
        real_replace(source, destination)
        if not interrupted:
            interrupted = True
            raise RuntimeError("simulated power loss during rollback")

    monkeypatch.setattr(module.os, "replace", replace_then_die)
    with pytest.raises(RuntimeError, match="power loss"):
        module._recover_promotion(out, fingerprint_final=fingerprint_final)
    monkeypatch.setattr(module.os, "replace", real_replace)

    module._recover_promotion(out, fingerprint_final=fingerprint_final)

    assert (out / "SHARADAR_SEP_2007.csv.gz").read_bytes() == b"old-2007"
    assert (out / "SHARADAR_SEP_2008.csv.gz").read_bytes() == b"old-2008"
    assert not marker.exists()


def test_sep_fingerprint_staging_name_matches_recovery_contract() -> None:
    source = (ROOT / "scripts" / "sentinel-split-sep-bulk.py").read_text()
    assert ".sep-stage." not in source
    assert source.count(".sep-staging.") >= 2


def test_sep_recovery_refuses_marker_paths_outside_generation(tmp_path) -> None:
    module = _load_script("sentinel-split-sep-bulk.py")
    out = tmp_path / "sep"
    out.mkdir()
    fingerprint = tmp_path / "sep-fingerprint.json"
    victim = tmp_path / "victim"
    victim.write_text("must survive")
    token = "deadbeef"
    marker = out / module.PROMOTION_MARKER
    marker.write_text(json.dumps({
        "schema": module.PROMOTION_SCHEMA,
        "phase": "BACKED_UP",
        "token": token,
        "staging": str(out / (".sentinel-sep-staging." + token)),
        "entries": [{
            "final": str(victim),
            "staged": str(out / "staged"),
            "backup": str(out / "backup"),
            "had_original": False,
            "backup_sha256": None,
            "sha256": "a" * 64,
        }],
    }))

    with pytest.raises(SystemExit, match="escaped output"):
        module._recover_promotion(out, fingerprint_final=fingerprint)
    assert victim.read_text() == "must survive"


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
