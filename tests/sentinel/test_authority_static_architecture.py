"""Static ownership and transaction-boundary regressions for authority."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from sentinel import administrative_authority as administrative
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
    locks = []
    monkeypatch.setattr(
        repository, "lock_authority_transition",
        lambda conn: locks.append(conn))
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
    assert locks == [committed, outer_transaction]

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
    assert locks == [committed, outer_transaction, failed]


def test_common_transition_lock_precedes_existing_row_lock_orders():
    transition_lock = inspect.getsource(repository.lock_authority_transition)
    assert "pg_advisory_xact_lock" in transition_lock
    assert "pg_try_advisory" not in transition_lock

    lifecycle_install = inspect.getsource(lifecycle.install_signed_certificate)
    assert lifecycle_install.index("verify_signed_certificate") < \
        lifecycle_install.index("lock_authority_transition")
    assert lifecycle_install.index("lock_authority_transition") < \
        lifecycle_install.index("authority_state_for_install")

    lifecycle_activation = inspect.getsource(
        lifecycle.activate_signed_certificate)
    assert lifecycle_activation.index("_verified_durable_certificate") < \
        lifecycle_activation.index("lock_authority_transition")
    assert lifecycle_activation.index("lock_authority_transition") < \
        lifecycle_activation.index("authority_state_for_install")
    assert lifecycle_activation.index("lock_authority_transition") < \
        lifecycle_activation.rindex("_require_durable_revocation_clear")

    lifecycle_revocation = inspect.getsource(
        lifecycle.revoke_signed_certificate)
    assert lifecycle_revocation.index("lock_authority_transition") < \
        lifecycle_revocation.index("revoke_certificate_rows")
    key_revocation_lifecycle = inspect.getsource(lifecycle.revoke_signed_key)
    assert key_revocation_lifecycle.index("lock_authority_transition") < \
        key_revocation_lifecycle.index("revoke_key_rows")

    administrative_install = inspect.getsource(
        administrative.install_administrative_certificate)
    assert administrative_install.index("verify_signed_certificate") < \
        administrative_install.index("lock_authority_transition")
    assert administrative_install.index("lock_authority_transition") < \
        administrative_install.index("_authority_state")

    administrative_activation = inspect.getsource(
        administrative.activate_administrative_certificate)
    assert administrative_activation.index("_verified_row") < \
        administrative_activation.index("lock_authority_transition")
    assert administrative_activation.index("lock_authority_transition") < \
        administrative_activation.index("_authority_state")
    assert administrative_activation.index("lock_authority_transition") < \
        administrative_activation.rindex(
            "sentinel_execution_key_revocations")

    administrative_revocation = inspect.getsource(
        administrative.revoke_administrative_certificate)
    assert administrative_revocation.index("lock_authority_transition") < \
        administrative_revocation.index("_authority_state")
    empty_binding_consumption = inspect.getsource(
        administrative.consume_empty_binding_authority)
    assert empty_binding_consumption.index("lock_authority_transition") < \
        empty_binding_consumption.index(
            "load_active_administrative_certificate")

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
