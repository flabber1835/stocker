"""Backed-up owner PAPER uses real durability evidence, never a green bypass."""
import ast
from datetime import date, datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel import backup_guard, backup_runtime_authority as runtime, binding, local_paper
from sentinel.execution import alpaca
from sentinel.panel import model, render, sources


NOW = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, 'PATESTACCOUNT')
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setattr(binding, 'require', lambda conn: SimpleNamespace(
        broker='alpaca', broker_account_id='PATESTACCOUNT'))


class Connection:
    def __init__(self, *rows):
        self.rows = iter(rows)
        self.statements = []
        self.closed = False

    def cursor(self):
        owner = self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, statement, *_): owner.statements.append(statement)
            def fetchone(self): return next(owner.rows)
        return Cursor()

    def rollback(self): pass
    def close(self): self.closed = True


def test_required_selection_is_independent_of_inherited_normal_authority(owner, monkeypatch):
    assert local_paper.enabled()
    assert not local_paper.backups_suspended()
    monkeypatch.setenv(runtime.AUTHORITY_ENV, runtime.AUTHORITY_VALUE)
    monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV)
    assert local_paper.backups_suspended()
    assert runtime.enabled() is False
    assert local_paper.backups_suspended_for_account(object())


@pytest.mark.parametrize('value', ['on', 'true', '0', 'DISABLED', 'required_v1', 'REQUIRED_V2'])
def test_unknown_local_backup_policy_refuses_instead_of_disabling(owner, monkeypatch, value):
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, value)
    with pytest.raises(RuntimeError, match='unsupported local PAPER backup policy'):
        local_paper.enabled()
    with pytest.raises(RuntimeError, match='unsupported local PAPER backup policy'):
        runtime.enabled()


def test_required_selection_forces_real_authority_even_without_baked_marker(owner, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'POLICY_MARKER', tmp_path / 'absent-policy')
    monkeypatch.delenv(runtime.AUTHORITY_ENV, raising=False)
    assert runtime.enabled() is True


def test_invalid_normal_policy_or_baked_marker_still_refuses(owner, monkeypatch, tmp_path):
    monkeypatch.setenv(runtime.AUTHORITY_ENV, 'wrong')
    with pytest.raises(runtime.BackupRuntimeRefused, match='unsupported runtime backup'):
        runtime.enabled()
    monkeypatch.delenv(runtime.AUTHORITY_ENV)
    marker = tmp_path / 'policy'
    marker.write_bytes(b'forged')
    monkeypatch.setattr(runtime, 'POLICY_MARKER', marker)
    with pytest.raises(runtime.BackupRuntimeRefused, match='invalid baked'):
        runtime.enabled()


def test_normal_mode_and_original_marker_selection_are_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV, raising=False)
    monkeypatch.delenv(runtime.AUTHORITY_ENV, raising=False)
    marker = tmp_path / 'policy'
    monkeypatch.setattr(runtime, 'POLICY_MARKER', marker)
    assert not local_paper.backups_suspended()
    assert runtime.enabled() is False
    marker.write_bytes(runtime.POLICY_BYTES)
    assert runtime.enabled() is True


def test_required_guard_reads_actual_archiver_and_refuses_archive_off(owner):
    conn = Connection(('off', None, None, 0, NOW))
    with pytest.raises(backup_guard.BackupConfigurationRefused, match='archive_mode=off'):
        backup_guard.require_writes_permitted(conn, operation='protected order')
    assert any('FROM pg_stat_archiver' in statement for statement in conn.statements)


def test_required_guard_uses_healthy_actual_archiver_evidence(owner):
    conn = Connection(('on', NOW - timedelta(seconds=5), None, 0, NOW))
    observed = backup_guard.require_bulk_writes_permitted(conn, operation='publication')
    assert observed.state == 'HEALTHY' and observed.archive_mode == 'on'
    assert observed.last_success_age_seconds == 5


def test_required_runtime_calls_existing_horizon_with_original_base(owner, monkeypatch):
    conn, calls = object(), []
    def real_path(connection, **kwargs):
        calls.append((connection, kwargs))
        return {'enabled': True, 'original_horizon': 'checked-by-existing-owner'}
    monkeypatch.setattr(runtime, '_require', real_path)
    result = runtime.require(conn, operation='protected order', base_backup='base-20261024T180000Z')
    assert result['enabled'] is True
    assert calls == [(conn, dict(operation='protected order', base_backup='base-20261024T180000Z'))]


def test_required_staging_checks_actual_archive_and_both_media_markers(owner, monkeypatch):
    conn, calls = object(), []
    monkeypatch.setattr(backup_guard, 'require_bulk_writes_permitted',
        lambda connection, **kwargs: calls.append(('archive', connection, kwargs)) or
            SimpleNamespace(unresolved_failure=False))
    monkeypatch.setattr(runtime, '_require_marker',
        lambda connection, path: calls.append(('marker', connection, path)))
    assert runtime.require_staging(conn, operation='staging') == {
        'enabled': True, 'scope': 'NON_AUTHORITATIVE_STAGING'}
    assert calls == [('archive', conn, {'operation': 'staging'}),
                     ('marker', conn, runtime.WAL_ROOT), ('marker', conn, runtime.BASE_ROOT)]


def test_required_staging_refuses_unresolved_archival_failure(owner, monkeypatch):
    monkeypatch.setattr(backup_guard, 'require_bulk_writes_permitted',
        lambda *a, **kw: SimpleNamespace(unresolved_failure=True))
    with pytest.raises(runtime.BackupRuntimeUnavailable, match='unresolved WAL archive failure'):
        runtime.require_staging(object(), operation='staging')


def test_required_policy_never_bypasses_foreign_account(owner, monkeypatch):
    monkeypatch.setattr(binding, 'require', lambda conn: SimpleNamespace(
        broker='alpaca', broker_account_id='PAFOREIGN'))
    with pytest.raises(RuntimeError, match='durable binding'):
        backup_guard.status(object())
    with pytest.raises(RuntimeError, match='durable binding'):
        runtime.require(object(), operation='order')


def test_backed_paper_restores_missing_incarnation_anchor_restriction(owner):
    conn = Connection(None, (1,), ('sentinel_backup_recovery_markers',), (1,))
    reason = alpaca.upgrade_restore_reason(conn)
    assert 'predates the physical incarnation anchor' in reason
    assert 'adopt-restored-account' in reason


def test_backed_paper_restores_intraday_postmaster_restriction(owner):
    conn = Connection((datetime(2026, 10, 21, 15, tzinfo=timezone.utc),))
    reason = alpaca.postmaster_day_order_fence_reason(conn, date(2026, 10, 21))
    assert 'PostgreSQL restarted during XNYS session' in reason


def test_backed_paper_execution_keeps_restore_fence_precedence(owner, monkeypatch):
    monkeypatch.setattr(alpaca, '_base_restore_increase_fence_reason', lambda *args: 'original restore fence')
    assert alpaca.execution_increase_fence_reason(conn=object(),
        deployment=SimpleNamespace(broker='alpaca'), today=date(2026, 10, 21)) == 'original restore fence'


def test_backup_opt_in_guard_removal_falsifier(owner, monkeypatch):
    test_required_runtime_calls_existing_horizon_with_original_base(owner, monkeypatch)
    tree = ast.parse(inspect.getsource(local_paper.backups_suspended))
    returned = next(node for node in tree.body[0].body if isinstance(node, ast.Return))
    returned.value = ast.parse('enabled(values)', mode='eval').body
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<removed-backed-paper-opt-in>', 'exec'),
         vars(local_paper), namespace)
    monkeypatch.setattr(local_paper, 'backups_suspended', namespace['backups_suspended'])
    with pytest.raises(AssertionError):
        test_required_runtime_calls_existing_horizon_with_original_base(owner, monkeypatch)


def operator_fixture(monkeypatch):
    from sentinel.feed import store
    from sentinel.execution import account_status
    conn, reads = Connection(), []
    monkeypatch.setattr(store, 'connect', lambda dsn: conn)
    monkeypatch.setattr(sources, '_latest_account_evidence', lambda conn: None)
    monkeypatch.setattr(sources, '_bound_account_id', lambda conn: 'PATESTACCOUNT')
    monkeypatch.setattr(sources, '_authority_lifecycle', lambda conn: None)
    monkeypatch.setattr(sources, '_runtime_verdict', lambda conn: None)
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda conn: None)
    monkeypatch.setattr(sources, '_matched_resting_reservation', lambda *a, **kw: None)
    monkeypatch.setattr(account_status, 'recorded_reservation', lambda *a, **kw: None)
    monkeypatch.setattr(local_paper, 'require_runtime', lambda *a, **kw: None)
    monkeypatch.setattr(sources, '_latest_backup_evidence',
        lambda conn, kind: reads.append(kind) or None)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a' * 40)
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', 'a' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('SENTINEL_TEST_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    return conn, reads


@pytest.mark.parametrize('required', [False, True])
def test_backed_panel_reads_real_evidence_and_cannot_hide_missing_proof(owner, monkeypatch, required):
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY if required else '')
    conn, reads = operator_fixture(monkeypatch)
    rows, errors = sources._operator_evidence_rows('postgresql://fixture@isolated.invalid/test', now=NOW)
    backup = next(row for row in rows if row.key == 'backup_restore')
    assert not errors and conn.closed
    if required:
        assert reads == ['BASE_BACKUP', 'RESTORE_DRILL', 'RUNTIME_CHAIN', 'MAINTENANCE_PROGRESS']
        assert backup.status == model.FAIL and backup.required_current
        assert backup.value == 'MISSING EVIDENCE'
    else:
        assert reads == [] and backup.status == model.OK and not backup.required_current
        assert backup.value == 'DISABLED BY OWNER'


def test_panel_backup_read_guard_removal_is_observable(owner, monkeypatch):
    test_backed_panel_reads_real_evidence_and_cannot_hide_missing_proof(owner, monkeypatch, True)
    source = inspect.getsource(sources._operator_evidence_rows)
    assert 'if not backups_suspended:' in source
    source = source.replace('if not backups_suspended:', 'if not local:', 1)
    namespace = {}
    exec(compile(source, '<removed-backed-panel-evidence-read>', 'exec'), vars(sources), namespace)
    monkeypatch.setattr(sources, '_operator_evidence_rows', namespace['_operator_evidence_rows'])
    with pytest.raises(AssertionError):
        test_backed_panel_reads_real_evidence_and_cannot_hide_missing_proof(owner, monkeypatch, True)


def test_backed_panel_guide_does_not_claim_suspended_or_successful_backup():
    row = model.backup_restore_row(base_at=None, restore_at=None, now=NOW)
    panel = model.Panel(rows=[row], now=NOW, local_paper_mode=True)
    html = render.render(panel)
    assert 'Backup and restore readiness has its own current evidence check' in html
    assert 'backup verification are disabled' not in html
    assert 'PR release certification is suspended' not in html
    assert panel.operational == model.FAIL
