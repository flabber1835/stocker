"""Actual checkpoint coordinator against strict external command responses."""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_activation_checkpoint as checkpoint
import sentinel_backup_maintenance as maintenance

IMAGE = 'sha256:' + 'd' * 64
HEAD = 'a' * 40
SIZE = 16 * 1024 * 1024
NOW = 1791940000


class Commands:
    def __init__(self):
        self.calls = []
        self.selected = dict(name='base-20261014T010000Z', timestamp=NOW-60,
            metadata_sha256='b'*64, marker='sentinel-backup-20261014T010000Z-42',
            target_lsn='0/C000000', ranges=[dict(timeline=1, end=11*SIZE)])
        self.observation = dict(system_id='123', now=NOW, lsn='0/F000000',
            timeline='00000001', segment_size=SIZE)
        self.receipt = dict(base_backup=self.selected['name'], metadata_sha256='b'*64,
            marker=self.selected['marker'], target_lsn=self.selected['target_lsn'],
            system_identifier='123', physical_only=False, runtime_image=IMAGE)
        self.barrier = dict(system_identifier='123', lsn='0/F000000',
            wal='00000001000000000000000E')
        self.end = 14
        self.change_selection = False
        self.observes = 0
        self.recorded = []

    def __call__(self, argv, timeout):
        assert timeout > 0
        self.calls.append(list(argv))
        if argv == ['git', 'rev-parse', 'HEAD']:
            return HEAD
        if argv[:3] == ['git', 'status', '--porcelain']:
            return ''
        if argv[:3] == ['docker', 'image', 'inspect']:
            return HEAD
        if argv[:2] == ['docker', 'run']:
            assert 'observe' in argv and '--network' in argv and 'none' in argv
            self.observes += 1
            value = deepcopy(self.selected)
            if self.change_selection and self.observes > 1:
                value['metadata_sha256'] = 'c' * 64
            return json.dumps(value)
        if argv[:2] == ['bash', 'scripts/sentinel-backup-status.sh']:
            return ('wal_chain_ready:true start_index=11 end=0000000100000000000000%02X '
                'segments=%d marker=00000001000000000000000B history=none\n'
                'backup_ready:true base=/backups/base/%s age_hours=0 wal_age_hours=0 system_id=123'
                % (self.end, self.end-10, self.selected['name']))
        if 'psql' in argv:
            sql = argv[-1]
            if "'system_id'" in sql:
                return json.dumps(self.observation)
            if "kind='RESTORE_DRILL'" in sql:
                return json.dumps(self.receipt) if self.receipt else ''
            if 'INSERT INTO sentinel_backup_recovery_markers' in sql:
                assert "'synchronous_commit','on',true" in sql
                return re.search(r"SELECT '(sentinel-backup-[^']+)' FROM configured", sql)[1]
            if 'pg_current_wal_flush_lsn' in sql:
                assert any('INSERT INTO sentinel_backup_recovery_markers' in a[-1] for a in self.calls[:-1])
                return json.dumps(self.barrier)
            if sql == 'SELECT pg_switch_wal()':
                return '0/F000000'
            if 'INSERT INTO sentinel_backup_evidence' in sql:
                value = json.loads(re.search(r"SELECT '([^']+)'::jsonb", sql)[1])
                self.recorded.append(value)
                return json.dumps(value)
        pytest.fail('unexpected external operation: ' + repr(argv))


@pytest.fixture
def commands(monkeypatch, tmp_path):
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_REF', IMAGE)
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    return Commands()


@pytest.mark.parametrize('raw', [
    '{"system_identifier":"123","lsn":"0/F000000","lsn":"0/E000000","wal":"00000001000000000000000E"}',
    '{"system_identifier":"123","lsn":NaN,"wal":"00000001000000000000000E"}',
    '{"system_identifier":123,"lsn":"0/F000000","wal":"00000001000000000000000E"}',
    '{"system_identifier":"123","lsn":"0/F000000","wal":"00000001000000000000000E","extra":true}',
])
def test_malformed_boundary_cannot_authorize_archive_checkpoint(raw):
    with pytest.raises(RuntimeError, match='boundary is malformed'):
        checkpoint._boundary_document(raw)


def test_reuses_exact_full_proof_and_archives_committed_state_without_copy(commands, capsys):
    assert checkpoint.reuse(Path('/backups'), commands) == '/backups/base/' + commands.selected['name']
    assert len(commands.recorded) == 1
    assert not any('base-backup' in ' '.join(a) or 'restore-drill' in ' '.join(a) for a in commands.calls)
    result = json.loads(capsys.readouterr().out.split('activation_recovery_checkpoint:')[1])
    assert result['state_wal'] == commands.barrier['wal']
    assert result['new_base_created'] is False and result['full_restore_performed'] is False
    assert result['method'] == 'REUSED_FULL_RESTORE_AND_ARCHIVED_STATE'


@pytest.mark.parametrize('field,value', [('runtime_image','sha256:'+'e'*64),
    ('runtime_image','mutable:latest'), ('physical_only',True), ('physical_only',0),
    ('system_identifier','456'), ('metadata_sha256','c'*64), ('target_lsn','0/1'),
    ('marker','foreign'), ('base_backup','base-20261014T000000Z')])
def test_ineligible_receipt_cannot_reuse_or_write_marker(commands, field, value):
    commands.receipt[field] = value
    assert checkpoint.reuse(Path('/backups'), commands) is None
    assert not any('INSERT' in a[-1] for a in commands.calls)


@pytest.mark.parametrize('reason', ['absent', 'age', 'wal'])
def test_normal_fresh_milestone_needed_only_before_new_marker(commands, reason):
    if reason == 'absent':
        commands.receipt = None
    elif reason == 'age':
        commands.selected['timestamp'] = NOW - maintenance.RENEW_SECONDS
    else:
        # The selected base ends in segment 0B. Reach the approved 8 GiB
        # renewal threshold; the former 512 MiB fixture is now reusable.
        commands.observation['lsn'] = '2/0C000000'
    assert checkpoint.reuse(Path('/backups'), commands) is None
    assert not commands.recorded and not any('INSERT' in a[-1] for a in commands.calls)


@pytest.mark.parametrize('field,value', [('system_identifier','456'),
    ('wal','00000002000000000000000E'), ('wal','00000001000000000000000D'),
    ('lsn','0/E000001'), ('lsn','NaN')])
def test_barrier_mismatch_refuses_without_success_or_new_copy(commands, field, value):
    commands.barrier[field] = value
    with pytest.raises(RuntimeError):
        checkpoint.reuse(Path('/backups'), commands)
    assert not commands.recorded


def test_selected_metadata_change_refuses(commands):
    commands.change_selection = True
    with pytest.raises(RuntimeError, match='selected generation changed'):
        checkpoint.reuse(Path('/backups'), commands)
    assert not commands.recorded


def test_delayed_archive_has_one_fixed_budget_and_never_publishes_prematurely(commands, monkeypatch):
    clock = [0]
    monkeypatch.setattr(checkpoint.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(checkpoint.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0]+duration))
    commands.end = 13
    with pytest.raises(RuntimeError, match='archive deadline exhausted'):
        checkpoint.reuse(Path('/backups'), commands)
    assert clock[0] == 60  # independent documented archive budget
    assert not commands.recorded


def test_pending_archive_can_catch_up_without_another_marker(commands, monkeypatch):
    sleeps = []
    commands.end = 13
    def advance(duration):
        sleeps.append(duration)
        commands.end = 14
    monkeypatch.setattr(checkpoint.time, 'sleep', advance)
    assert checkpoint.reuse(Path('/backups'), commands)
    assert sleeps == [1]
    assert sum('INSERT INTO sentinel_backup_recovery_markers' in a[-1] for a in commands.calls) == 1


def test_public_milestone_reuses_proof_under_verified_owner(commands,monkeypatch):
    from types import SimpleNamespace
    import sentinel_install_backup as install
    monkeypatch.setenv(install.LOCK_ROOT_ENV,'/backups')
    monkeypatch.setattr(install,'lock_is_held',lambda:True)
    def runner(argv,**kwargs):
        assert kwargs['private_group'] is True
        return SimpleNamespace(returncode=0,stdout=commands(argv,kwargs['timeout']),stderr='')
    assert install.milestone('full',runner=runner,reuse_current=True).endswith(commands.selected['name'])
    assert not any('sentinel-base-backup.sh' in a or 'sentinel-restore-drill.sh' in a for a in commands.calls)


def test_absent_receipt_falls_back_once_to_exact_fresh_full_milestone(commands,monkeypatch):
    from types import SimpleNamespace
    import sentinel_install_backup as install
    monkeypatch.setenv(install.LOCK_ROOT_ENV,'/backups')
    monkeypatch.setattr(install,'lock_is_held',lambda:True)
    commands.receipt=None
    calls=[]
    exact='/backups/base/base-20261014T020000Z'
    def runner(argv,**kwargs):
        calls.append(argv)
        if argv[0]=='bash':
            value='verified_base_backup:'+exact if argv[1]=='scripts/sentinel-base-backup.sh' else ''
        else:value=commands(argv,kwargs['timeout'])
        return SimpleNamespace(returncode=0,stdout=value,stderr='')
    assert install.milestone('full',runner=runner,reuse_current=True)==exact
    assert [a for a in calls if a[0]=='bash']==[
        ['bash','scripts/sentinel-base-backup.sh'],
        ['bash','scripts/sentinel-backup-status.sh','--backup',exact],
        ['bash','scripts/sentinel-restore-drill.sh','--backup',exact]]
