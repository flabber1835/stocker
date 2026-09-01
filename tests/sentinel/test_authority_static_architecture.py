"""Static ownership and transaction-boundary regressions for authority."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from sentinel import authority
from sentinel.authority import canonical, lifecycle, model, repository, validation


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))


def test_authority_package_has_one_static_owner_per_responsibility():
    assert not (ROOT / "sentinel" / "authority.py").exists()
    assert authority.AuthorityRefused is model.AuthorityRefused
    assert authority.canonical_json_bytes is canonical.canonical_json_bytes
    assert authority.verify_signed_certificate is \
        validation.verify_signed_certificate
    assert authority.load_rollout_state is repository.load_rollout_state
    assert authority.install_signed_certificate is \
        lifecycle.install_signed_certificate

    for module in (authority, model, canonical, validation, repository,
                   lifecycle):
        source = inspect.getsource(module)
        assert "def __getattr__" not in source
        assert "import *" not in source
    for module in (model, canonical, validation, lifecycle):
        assert ".execute(" not in inspect.getsource(module)


def test_obsolete_unsigned_installer_and_private_proxy_are_gone():
    assert not hasattr(authority, "install_system_certificate")
    assert not hasattr(authority, "trust_roots_bytes")
    source = (ROOT / "sentinel" / "empty_account_authority.py").read_text()
    assert "authority._validate_observation_bindings" not in source
    assert "validate_observation_bindings(bound)" in source


class _Connection:
    def __init__(self, *, rollback_fails: bool = False):
        self.commits = 0
        self.rollbacks = 0
        self.rollback_fails = rollback_fails

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        if self.rollback_fails:
            raise RuntimeError("secondary rollback failure")


def test_lifecycle_commit_false_and_rollback_preserve_existing_boundary(
        monkeypatch):
    calls = []
    monkeypatch.setattr(
        repository, "revoke_key_rows",
        lambda conn, *, key_id, reason: calls.append((conn, key_id, reason)))

    committed = _Connection()
    lifecycle.revoke_signed_key(
        committed, key_id="key-1", reason="reviewed", commit=True)
    assert (committed.commits, committed.rollbacks) == (1, 0)

    outer_transaction = _Connection()
    lifecycle.revoke_signed_key(
        outer_transaction, key_id="key-2", reason="reviewed", commit=False)
    assert (outer_transaction.commits, outer_transaction.rollbacks) == (0, 0)
    assert calls == [
        (committed, "key-1", "reviewed"),
        (outer_transaction, "key-2", "reviewed"),
    ]

    class PrimaryFailure(BaseException):
        pass

    def fail(*_args, **_kwargs):
        raise PrimaryFailure("primary lifecycle failure")

    monkeypatch.setattr(repository, "revoke_key_rows", fail)
    failed = _Connection(rollback_fails=True)
    with pytest.raises(PrimaryFailure, match="primary lifecycle failure"):
        lifecycle.revoke_signed_key(
            failed, key_id="key-3", reason="reviewed", commit=False)
    assert (failed.commits, failed.rollbacks) == (0, 1)


def test_repository_pins_existing_row_lock_order():
    activation = inspect.getsource(repository.activate_certificate_rows)
    assert activation.index("UPDATE sentinel_rollout_state") < \
        activation.index(
            "SELECT status FROM sentinel_execution_certificate_lifecycle")
    assert activation.index(
        "SELECT status FROM sentinel_execution_certificate_lifecycle") < \
        activation.index("SET status='ACTIVE',activated_at=NOW()")
    assert activation.index("SET status='ACTIVE',activated_at=NOW()") < \
        activation.index("UPDATE sentinel_execution_authority_state")

    revocation = inspect.getsource(repository.revoke_certificate_rows)
    assert revocation.index(
        "SELECT status FROM sentinel_execution_certificate_lifecycle") < \
        revocation.index(
            "FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")

    key_revocation = inspect.getsource(repository.revoke_key_rows)
    assert key_revocation.index("sentinel_execution_key_revocations") < \
        key_revocation.index(
            "FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")
    assert key_revocation.index(
        "FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE") < \
        key_revocation.index("FROM sentinel_administrative_authority_state")
