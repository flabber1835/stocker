"""LIVE never inherits owner-PAPER backup or native restart exemptions."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import backup_continuity, backup_guard, backup_runtime_authority as runtime, local_paper
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


@pytest.mark.parametrize('allow_continuity', [False, True])
def test_live_ignores_known_paper_continuity_and_never_touches_its_checkpoints(monkeypatch, allow_continuity):
    monkeypatch.setenv(backup_continuity.POLICY_ENV, backup_continuity.POLICY)
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, 'PAowner')
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setattr(local_paper, 'backups_suspended_for_account',
        lambda _c: pytest.fail('PAPER account lookup entered unbound LIVE bootstrap'))
    for name in ('selected', 'remember', 'degraded'):
        monkeypatch.setattr(backup_continuity, name,
            lambda *_a, **_k: pytest.fail('PAPER continuity entered LIVE'))
    proof = {'enabled': True, 'independent_archive_current': True}
    observed = []
    monkeypatch.setattr(runtime, '_require', lambda conn, **kw: observed.append(kw) or proof)
    assert runtime.require(object(), operation='LIVE bootstrap', allow_continuity=allow_continuity) is proof
    assert observed == [{'operation': 'LIVE bootstrap', 'base_backup': None}]


def test_live_unknown_outage_selection_refuses_before_strict_or_continuity_work(monkeypatch):
    monkeypatch.setenv(backup_continuity.POLICY_ENV, 'unknown-selection')
    monkeypatch.setattr(runtime, '_require', lambda *_a, **_k: pytest.fail('invalid selection reached backup proof'))
    with pytest.raises(runtime.BackupRuntimeRefused, match='unsupported backup outage policy'):
        runtime.require(object(), operation='LIVE mutation', allow_continuity=True)


@pytest.mark.parametrize('proof', [
    {'enabled': False},
    {'enabled': True, 'backup_state': 'DEGRADED'},
    {'enabled': True, 'independent_archive_current': False},
    {'enabled': True, 'independent_archive_current': None},
    {'enabled': True, 'independent_archive_current': 0},
])
def test_live_refuses_any_noncurrent_external_proof(monkeypatch, proof):
    monkeypatch.setattr(runtime, '_require', lambda *_a, **_k: proof)
    with pytest.raises(runtime.BackupRuntimeRefused, match='current independent archive'):
        runtime.require(object(), operation='LIVE mutation', allow_continuity=True)


@pytest.mark.parametrize('proof', [
    {'enabled': False},
    {'enabled': True, 'backup_state': 'DEGRADED'},
    {'enabled': True, 'independent_archive_current': False},
])
def test_live_actual_fresh_mutation_guard_never_selects_or_accepts_continuity(monkeypatch, proof):
    import asyncio
    from sentinel.authority import AuthorityRefused
    from sentinel.execution import authority_gate
    from sentinel.execution.guarded import BrokerOperation, LiveExecutionGrant
    from live_authority_fixtures import live_fixture
    class Connection:
        def close(self): pass
    calls = []
    def backup(conn, **kwargs):
        calls.append(kwargs)
        return proof
    monkeypatch.setattr(runtime, 'require', backup)
    guard = authority_gate.build_fresh_execution_guard(connection_factory=Connection,
        paper_base_url='https://api.alpaca.markets', runtime_identity=lambda: {},
        strategy_identity=lambda: {},
        validate_grant=lambda *_a: pytest.fail('noncurrent LIVE proof reached financial validation'))
    grant = LiveExecutionGrant(live_fixture().subject, 'EXECUTE', 'plan', date(2026, 11, 2), True)
    with pytest.raises(AuthorityRefused, match='current independent archive'):
        asyncio.run(guard.before_mutation(grant, BrokerOperation.SUBMIT))
    assert calls == [{'operation': 'broker submit mutation', 'allow_continuity': False}]


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
