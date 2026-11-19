"""Use the actual read-only restore upgrade guard before dual activation."""
from types import SimpleNamespace

import pytest

from sentinel.execution import alpaca, journal
from sentinel import dual_reconciliation
from sentinel.feed import store
from tests.sentinel.test_issue282_restore_upgrade_fence import conn, pg
from tests.sentinel.test_activation_writer_handoff import core, appliance


def run_reconciliation(conn, tmp_path, monkeypatch, *, remove_guard=False):
    obj, events, control, running = appliance(tmp_path, core.AutonomousDeploy)
    obj._verify_dual_plan_shadow_reconciliation = (
        core.AutonomousDeploy._verify_dual_plan_shadow_reconciliation.__get__(obj))
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    reads, brokers = [], []
    original_connect = store.connect
    def connect(dsn):
        c = original_connect(dsn)
        reads.append(c)
        return c
    monkeypatch.setattr(store, 'connect', connect)
    monkeypatch.setattr(journal, 'latest_plan', lambda c: SimpleNamespace(plan_id='fixture'))
    def verify(c, **kwargs):
        assert c.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        events.append('native-reconciliation')
        return dict(schema='sentinel.dual-plan-shadow-reconciliation/1', verdict='MATCH',
                    **{field: 'a'*64 for field in ('state_sha256',
                    'shadow_runtime_authority_sha256', 'sizing_authority_sha256',
                    'plan_fingerprint')})
    monkeypatch.setattr(dual_reconciliation, 'require_plan_matches_verified_shadow', verify)
    def prohibited(*args, **kwargs):
        brokers.append('called')
        raise AssertionError('activation diagnostic contacted a broker')
    monkeypatch.setattr(alpaca.AlpacaExecutionBroker, '__init__', prohibited)
    def run(args, **kwargs):
        code = args[-1]
        assert args[-2] == '-c' and kwargs['capture'] is True
        if remove_guard:
            code = code.replace('reason=upgrade_restore_reason(c)', "reason=''")
        import contextlib, io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(code, {})
        return SimpleNamespace(returncode=0, stdout=output.getvalue(), stderr='')
    obj.runner.run = run
    before = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name').fetchall()
    conn.rollback()
    try:
        result = obj._verify_dual_plan_shadow_reconciliation()
    finally:
        for c in reads:
            c.close()
        after = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name').fetchall()
        conn.rollback()
        assert before == after
        assert not brokers
        assert control['kill_switch_engaged'] and not control['enabled']
    return result, events


def test_legacy_backups_without_anchor_refuse_before_plan_reconciliation(
        conn, tmp_path, monkeypatch):
    with pytest.raises(core.DeployRefused, match='read command or owned cleanup failed') as refused:
        run_reconciliation(conn, tmp_path, monkeypatch)
    assert type(refused.value.__cause__) is RuntimeError
    assert 'adopt-restored-account' in str(refused.value.__cause__)


def test_existing_anchor_passes_without_mutation_or_broker_contact(conn, tmp_path, monkeypatch):
    alpaca.database_incarnation(conn)
    result, events = run_reconciliation(conn, tmp_path, monkeypatch)
    assert result['verdict'] == 'MATCH' and events == ['native-reconciliation']


def test_fresh_database_without_backup_history_passes_without_initializing_anchor(
        conn, tmp_path, monkeypatch):
    conn.execute('DELETE FROM sentinel_backup_recovery_markers')
    conn.commit()
    result, _ = run_reconciliation(conn, tmp_path, monkeypatch)
    assert result['verdict'] == 'MATCH'
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name='broker-recovery-db-incarnation:v1'").fetchone()[0] == 0
    conn.rollback()


def test_removed_native_upgrade_guard_is_detected(conn, tmp_path, monkeypatch):
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        with pytest.raises(core.DeployRefused, match='read command or owned cleanup failed'):
            run_reconciliation(conn, tmp_path, monkeypatch, remove_guard=True)


@pytest.mark.parametrize('condition', ['missing-anchor', 'wrong-mode', 'ready', 'pin-busy', 'other-busy'])
def test_combined_activation_cli_checks_native_restore_once_and_types_only_exact_pin(
        conn, monkeypatch, capsys, condition):
    import asyncio
    import json
    from sentinel import automation_runtime, paper
    from sentinel.cli import paper as cli
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel.feed.runtime_schema import require_feed_schema
    import sentinel_activation_read as protocol
    # This module's historical fixture installs its feed schema on first
    # validation. Install it explicitly and restore the production reader.
    store.migrate_schema(conn)
    monkeypatch.setattr(store, 'require_feed_schema', require_feed_schema)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'paper' if condition=='wrong-mode' else 'dual')
    monkeypatch.setattr(automation_runtime, 'shadow_config_from_env', lambda: (True,'primary',50000))
    if condition != 'missing-anchor':
        alpaca.database_incarnation(conn)
    calls = []
    class OtherBusy(CorpusLockUnavailable):
        pass
    def inspect(connection, **kwargs):
        calls.append(connection)
        assert connection.execute('SHOW transaction_read_only').fetchone() == ('on',)
        assert connection.execute('SHOW transaction_isolation').fetchone() == ('repeatable read',)
        if condition in ('pin-busy','other-busy'):
            raise (CorpusLockUnavailable if condition=='pin-busy' else OtherBusy)('fixture')
        return {'database_authorities_match': True}
    monkeypatch.setattr(paper, 'current_paper_plan', inspect)
    cfg = SimpleNamespace(database_url=conn.info.dsn, base_url='https://paper-api.alpaca.markets')
    status = asyncio.run(cli._current_paper_plan(cfg, SimpleNamespace(for_dual_activation=True)))
    out = capsys.readouterr()
    if condition == 'missing-anchor':
        assert status != 0 and 'adopt-restored-account' in out.err and not calls
    elif condition == 'wrong-mode':
        assert status != 0 and 'reviewed dual mode' in out.err and not calls
    elif condition == 'ready':
        assert status == 0 and json.loads(out.out)['activation_restore_checked'] is True
    elif condition == 'pin-busy':
        assert status == protocol.WAIT_EXIT and out.out.strip() == protocol.WAIT_OUTPUT and not out.err
    else:
        assert status not in (0,protocol.WAIT_EXIT) and protocol.WAIT_MARKER not in out.out
    assert all(connection.closed for connection in calls)
