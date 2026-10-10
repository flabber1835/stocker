"""Installation milestone identity, decimal cash and strict streamed JSON."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_reviewed_deploy_gate import deploy
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import sentinel_install_backup as backup
import sentinel_autonomous_deploy_bootstrap as bootstrap


@pytest.mark.parametrize('text', ['50000', '50000.0', '50000.000', '5E4'])
def test_equivalent_cash_has_one_authenticated_formation_cache_identity(text, monkeypatch):
    from sentinel.core.formation import FormationPlan
    from sentinel import formation_cache
    from sentinel.strategy import production_strategy
    monkeypatch.setenv('SENTINEL_STATE_DIR', '/tmp/qualification-cache')
    _, strategy = production_strategy()
    args = dict(end='2026-09-11', warmup_sessions=299, strategy=strategy, source_sha256='a'*64)
    plan = FormationPlan(capital=text, **args)
    exact = FormationPlan(capital='50000', **args)
    assert plan.model_dump(by_alias=True) == exact.model_dump(by_alias=True)
    assert formation_cache.location(plan) == formation_cache.location(exact)
    for changed in ({'capital':'50000.01'}, {'source_sha256':'b'*64}):
        assert formation_cache.location(FormationPlan(**{**args, 'capital':'50000', **changed})) != formation_cache.location(exact)


def test_decimal_cash_does_not_round_to_context_precision():
    from sentinel.core.formation import FormationPlan
    from sentinel.strategy import production_strategy
    _, strategy = production_strategy()
    value = '50001.000'
    from decimal import localcontext
    with localcontext() as context:
        context.prec = 3
        plan = FormationPlan(end='2026-09-11', warmup_sessions=299, strategy=strategy,
                             source_sha256='a'*64, capital=value)
    assert Decimal(plan.capital) == Decimal(value)


@pytest.mark.parametrize('delay', [0, 120, 1800])
def test_issuance_relative_clock_survives_host_startup_delay(delay):
    from sentinel.cli.authority import _candidate_not_before
    from datetime import timedelta
    reference = datetime(2026, 10, 7, 5, tzinfo=timezone.utc)
    args = SimpleNamespace(not_before_delay_seconds=delay, not_before=None)
    assert _candidate_not_before(args, reference) == reference + timedelta(seconds=delay)


@pytest.mark.parametrize('delay', [-1, 1801, True, '0'])
def test_invalid_issuance_clock_refuses(delay):
    from sentinel.cli.authority import _candidate_not_before
    with pytest.raises(ValueError):
        _candidate_not_before(SimpleNamespace(not_before_delay_seconds=delay, not_before=None),
                              datetime.now(timezone.utc))


def test_dual_candidate_uses_reviewed_shadow_seed_despite_changed_broker_nav():
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.env = {'SENTINEL_SHADOW_STARTING_CASH':'50000.00'}
    obj.reviewed_validation = SimpleNamespace(mode='dual', source_identity_sha256='a'*64)
    obj.account_equity = Decimal('53000')
    assert obj._observation_starting_cash() == '50000'
    obj.reviewed_validation.mode = 'paper'
    assert obj._observation_starting_cash() == '53000'


def test_candidate_progress_streams_before_completion_without_polluting_json(tmp_path, monkeypatch):
    runner = deploy.Runner(os.environ, tmp_path/'commands.log')
    # The child cannot complete until the parent displays the progress line.
    import builtins
    observed = tmp_path/'progress-observed'
    original = builtins.print
    def display(value, *args, **kwargs):
        if 'FORMATION_PROGRESS' in str(value): observed.touch()
        original(value, *args, **kwargs)
    monkeypatch.setattr(builtins, 'print', display)
    code = ("import sys,time; from pathlib import Path; "
            "print('FORMATION_PROGRESS',file=sys.stderr,flush=True); "
            f"p=Path({str(observed)!r}); deadline=time.monotonic()+1;\n"
            "while not p.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
            "assert p.exists(), 'parent hid progress until completion'\n"
            "print('{\"candidate\":true}')")
    result = runner.run([sys.executable, '-c', code], capture=True, stream=True, timeout=3)
    assert json.loads(result.stdout) == {'candidate':True}
    assert result.stderr.strip() == 'FORMATION_PROGRESS'
    assert 'FORMATION_PROGRESS' in (tmp_path/'commands.log').read_text()


@pytest.mark.parametrize('mode', ['full', 'physical'])
@pytest.mark.parametrize('failure', [None, 'base', 'status', 'restore', 'escaped'])
def test_one_backup_owner_exact_base_and_restore_before_success(mode, failure, monkeypatch, capsys):
    monkeypatch.setenv(backup.LOCK_ROOT_ENV, '/backups')
    monkeypatch.setattr(backup, 'lock_is_held', lambda:True)
    calls = []
    exact = '/backups/base/base-20261007T060000Z'
    def run(argv, **kwargs):
        assert kwargs['private_group'] is True
        assert kwargs['timeout'] > 0
        calls.append(argv)
        name = argv[1]
        fail = (failure == 'base' and 'base-backup' in name or failure == 'status' and 'backup-status' in name
                or failure == 'restore' and 'restore-drill' in name)
        output = 'verified_base_backup:'+('/other/base/base-20261007T060000Z' if failure == 'escaped' else exact)+'\n' if 'base-backup' in name else ''
        return SimpleNamespace(returncode=2 if fail else 0, stdout=output, stderr='')
    if failure:
        with pytest.raises(RuntimeError): backup.milestone(mode, runner=run)
        assert 'verified_installation_backup:' not in capsys.readouterr().out
    else:
        assert backup.milestone(mode, runner=run) == exact
        assert calls[1][-2:] == ['--backup', exact]
        assert '--physical-only' in calls[2] if mode == 'physical' else '--physical-only' not in calls[2]


def test_backup_milestone_cannot_run_without_verified_owner(monkeypatch):
    monkeypatch.setattr(backup, 'lock_is_held', lambda:False)
    with pytest.raises(RuntimeError): backup.milestone('full', runner=lambda *a,**k:pytest.fail('unowned work'))


def test_finalization_reuses_killed_state_restore_milestone():
    obj = object.__new__(bootstrap.BootstrapDeploy)
    obj._activation_backup = '/backups/base/base-20261007T060000Z'
    obj._create_backup = lambda **k:pytest.fail('duplicate backup after activation')
    assert obj._post_deploy_backup() == obj._activation_backup


def test_maintenance_standby_does_not_launch_work_or_report_failure(tmp_path, monkeypatch, capsys):
    import fcntl
    import sentinel_backup_lock as owner
    monkeypatch.setenv(owner.LOCK_ROOT_ENV, str(tmp_path))
    lock = owner._lock_path(os.environ)
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock.open('a+') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(owner.subprocess, 'run', lambda *a, **k:pytest.fail('competing writer launched'))
        assert owner._hold(['never-run'], standby_if_busy=True) == 0
        assert owner._hold(['never-run']) == 2
    assert 'STANDBY_TARGET_OWNED' in capsys.readouterr().out


@pytest.mark.parametrize('schema_current', [True, False, None])
def test_schema_noop_skips_copy_but_migration_keeps_recovery_before_ddl(schema_current):
    obj = object.__new__(bootstrap.BootstrapDeploy)
    obj.base_compose = ['isolated-compose']
    obj.phase = lambda _:None
    events = []
    obj._quiesce_database = lambda: events.append('fence') or True
    obj._confirm_migrated_fence = lambda first: events.append('confirmed')
    obj._migrate_schema = lambda: events.append('migration')
    obj._create_backup = lambda **k: events.append('physical-recovery') or '/backups/base/base-20261007T060000Z'
    def run(argv, **k):
        if any(item.endswith('sentinel-backup-status.sh') for item in argv):
            pytest.fail('financial backup readiness inside software schema transition')
        else:
            events.append('schema-proof')
        return SimpleNamespace(stdout=json.dumps({'schema_current':schema_current}))
    obj.runner = SimpleNamespace(run=run)
    if schema_current is None:
        with pytest.raises(bootstrap.core.DeployRefused, match='malformed'): obj.quiesce_backup_and_migrate()
        assert events == ['fence', 'schema-proof']
    else:
        obj.quiesce_backup_and_migrate()
        assert events == ['fence', 'schema-proof', *([] if schema_current else ['physical-recovery', 'migration']), 'confirmed']
