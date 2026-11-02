"""LIVE never inherits owner-PAPER backup or native restart exemptions."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import backup_guard, backup_runtime_authority as runtime, local_paper
from sentinel.execution import alpaca


@pytest.fixture(autouse=True)
def live_origin(monkeypatch):
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")


def test_live_runtime_uses_real_chain_even_with_paper_exemption(monkeypatch):
    monkeypatch.setattr(local_paper, "backups_suspended_for_account",
        lambda _c: pytest.fail("PAPER exemption entered LIVE"))
    proof = {"enabled": True, "recoverable_through_wal": "qualified"}
    calls = []
    monkeypatch.setattr(runtime, "_require", lambda conn, **kwargs: calls.append(kwargs) or proof)
    assert runtime.require(object(), operation="broker submit") is proof
    assert calls == [{"operation": "broker submit", "base_backup": None}]


def test_live_without_real_backup_policy_cannot_return_disabled_success(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "POLICY_MARKER", tmp_path / "no-policy")
    monkeypatch.delenv(runtime.AUTHORITY_ENV, raising=False)
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAowner")
    assert runtime.enabled() is False
    with pytest.raises(runtime.BackupRuntimeRefused, match="LIVE requires enabled"):
        runtime.require(object(), operation="broker submit")


def test_live_backup_exemption_guard_removal_is_detected(monkeypatch):
    monkeypatch.setattr(local_paper, "backups_suspended_for_account", lambda _c: True)
    monkeypatch.setattr(runtime, "_require", lambda *_a, **_k: {"enabled": True})
    def invariant():
        assert runtime.require(object(), operation="submit")["enabled"] is True
    invariant()
    monkeypatch.setattr(runtime, "_live_origin_selected", lambda: False)
    with pytest.raises(AssertionError):
        invariant()


def test_live_archive_guard_reads_native_health_instead_of_paper_exemption(monkeypatch):
    monkeypatch.setattr(local_paper, "backups_suspended_for_account",
        lambda _c: pytest.fail("PAPER exemption entered archive guard"))
    now = datetime.now(timezone.utc)
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def execute(self, *_a): pass
        def fetchone(self): return ("on", now - timedelta(seconds=1), None, 0, now)
    conn = SimpleNamespace(cursor=Cursor)
    status = backup_guard.status(conn)
    assert status.archive_mode == "on"
    assert status.state != "DISABLED_BY_OPERATOR"


def test_live_namespace_retains_native_restore_increase_fence(monkeypatch):
    monkeypatch.setattr(local_paper, "backups_suspended_for_account",
        lambda _c: pytest.fail("PAPER exemption entered LIVE restore fence"))
    calls = []
    monkeypatch.setattr(alpaca, "_base_restore_increase_fence_reason",
        lambda *_a: calls.append("base") or "restore qualification pending")
    assert alpaca.execution_increase_fence_reason(conn=object(),
        deployment=SimpleNamespace(broker="alpaca-live"), today=date(2026, 11, 2)) == "restore qualification pending"
    assert calls == ["base"]
