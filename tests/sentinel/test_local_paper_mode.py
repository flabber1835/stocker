"""Owner-authorized PAPER iteration does not open a live or foreign account."""
from datetime import date
from types import SimpleNamespace
import ast
import inspect

import pytest

from sentinel import backup_guard, backup_runtime_authority, binding, local_paper
from sentinel.execution import alpaca


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PATESTACCOUNT")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(binding, "require", lambda conn: SimpleNamespace(
        broker="alpaca", broker_account_id="PATESTACCOUNT"))


def test_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    assert not local_paper.enabled()


@pytest.mark.parametrize("endpoint", ["https://api.alpaca.markets", "http://paper-api.alpaca.markets", "https://paper-api.alpaca.markets.evil.test"])
def test_local_mode_never_allows_live_or_proxy(owner, monkeypatch, endpoint):
    monkeypatch.setenv("ALPACA_BASE_URL", endpoint)
    with pytest.raises(RuntimeError):
        local_paper.enabled()


def test_foreign_binding_refuses(owner, monkeypatch):
    monkeypatch.setattr(binding, "require", lambda conn: SimpleNamespace(
        broker="alpaca", broker_account_id="PAFOREIGN"))
    with pytest.raises(RuntimeError, match="durable binding"):
        local_paper.require_bound_account(object())
    with pytest.raises(RuntimeError, match="durable binding"):
        backup_runtime_authority.require(object(), operation="paper order")


class NoBackupReads:
    def cursor(self):
        pytest.fail("local PAPER mode attempted a backup or restart probe")


def test_no_backup_reads_or_restored_horizon_required(owner):
    conn = NoBackupReads()
    assert backup_runtime_authority.require(conn, operation="paper order") == {"enabled": False}
    result = backup_guard.require_writes_permitted(conn, operation="paper order")
    assert result.state == "DISABLED_BY_OPERATOR"
    assert result.writes_permitted
    assert backup_guard.require_bulk_writes_permitted(conn, operation="feed").bulk_writes_permitted


def test_intraday_restart_is_not_a_local_paper_increase_fence(owner):
    conn = NoBackupReads()
    assert alpaca.postmaster_day_order_fence_reason(conn, date(2026, 10, 21)) == ""
    assert alpaca.upgrade_restore_reason(conn) == ""
    assert alpaca.execution_increase_fence_reason(
        conn=conn, deployment=SimpleNamespace(broker="alpaca"), today=date(2026, 10, 21)) == ""


def _runtime(monkeypatch):
    commit = "a" * 40
    digest = "sha256:" + "b" * 64
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", commit)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", commit)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", digest)
    return {"deployment_artifacts": {"schema": "sentinel.runtime-artifacts/1",
        "git_commit": commit, "runtime_image_digest": digest, "test_image_digest": digest}}


def test_local_runtime_records_actual_commit_and_image(owner, monkeypatch):
    local_paper.require_runtime(object(), _runtime(monkeypatch))


def _bad_baked_revision(monkeypatch):
    runtime = _runtime(monkeypatch)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    with pytest.raises(RuntimeError, match="actual local commit"):
        local_paper.require_runtime(object(), runtime)


def test_mislabelled_local_image_refuses(owner, monkeypatch):
    _bad_baked_revision(monkeypatch)


def test_runtime_identity_guard_falsifier(owner, monkeypatch):
    tree = ast.parse(inspect.getsource(local_paper.require_runtime))
    tree.body[0].body[-1].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, "removed-local-image-guard", "exec"), vars(local_paper), namespace)
    monkeypatch.setattr(local_paper, "require_runtime", namespace["require_runtime"])
    with pytest.raises(pytest.fail.Exception):
        _bad_baked_revision(monkeypatch)
