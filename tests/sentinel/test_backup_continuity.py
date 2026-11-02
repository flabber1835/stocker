"""Bounded PAPER continuity refuses forged, stale and foreign local evidence."""
from contextlib import nullcontext
import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sentinel import backup_continuity as continuity
from sentinel import backup_runtime_authority as runtime, local_paper
from sentinel.backup_guard import BackupConfigurationRefused, BackupUnavailable


ENV = {
    continuity.KEY_ENV: 'private-fixture-key-only-' * 3,
    continuity.POLICY_ENV: continuity.POLICY,
    local_paper.MODE_ENV: local_paper.MODE,
    local_paper.ACCOUNT_ENV: 'PAFIXTURE',
    local_paper.BACKUP_POLICY_ENV: local_paper.BACKUP_POLICY,
    'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets',
    'SENTINEL_GIT_COMMIT': 'a' * 40,
    'SENTINEL_RUNTIME_IMAGE_DIGEST': 'sha256:' + 'b' * 64,
}
OBSERVATION = dict(system_identifier='7691913275518591014', postmaster_start_us=123000000,
    now=10000, last_archive_at=9990, last_archived_wal='000000010000000000000003',
    archive_mode='on', primary_wal_bytes=16*1024**2)
CHAIN = dict(enabled=True, system_identifier=OBSERVATION['system_identifier'],
    recoverable_through_wal=OBSERVATION['last_archived_wal'], base_backup='base-20261101T000000Z')
CONTEXT = dict(system_identifier=OBSERVATION['system_identifier'], postmaster_start_us=123000000,
    deployment_id='fixture', broker='alpaca', broker_account_id='PAFIXTURE', takeover_epoch=1,
    git_commit='a'*40, runtime_image_digest='sha256:'+'b'*64)


class Connection:
    def __init__(self):
        self.records = {}
        self.statements = []
        self.observation = dict(OBSERVATION)
        self.program_error = False

    def transaction(self):
        return nullcontext()

    def cursor(self):
        owner=self
        class Cursor:
            row=None
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def execute(self,statement,args=()):
                owner.statements.append((statement,args))
                if statement.startswith('SELECT pg_read_binary_file'):
                    self.row=(owner.records.get(args[0]),)
                elif statement.startswith('SELECT system_identifier'):
                    value=owner.observation
                    self.row=tuple(value[k] for k in ('system_identifier','postmaster_start_us',
                        'now','last_archived_wal','last_archive_at','archive_mode','primary_wal_bytes'))
                elif statement.startswith('COPY') and owner.program_error:
                    raise OSError('private failed capacity/media program')
            def fetchone(self): return self.row
        return Cursor()


class BackupContinuityTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,ENV,clear=True); self.env.start()
        self.addCleanup(self.env.stop)
        self.bound=patch.object(local_paper,'bound_account',return_value=SimpleNamespace(
            deployment_id='fixture',broker='alpaca',broker_account_id='PAFIXTURE',takeover_epoch=1))
        self.bound.start(); self.addCleanup(self.bound.stop)
        self.conn=Connection()
        self.checkpoint=dict(context=copy.deepcopy(CONTEXT),engine_id='fixture-native-engine',
            last_archive_at=9990,chain=copy.deepcopy(CHAIN))
        self.capacity=dict(system_identifier=OBSERVATION['system_identifier'],postmaster_start_us=123000000,
            observed_at=9995,physical_free_bytes=continuity.RESERVE_BYTES,engine_id='fixture-native-engine')
        self.write(continuity.CHECKPOINT,'CHECKPOINT',self.checkpoint)
        self.write(continuity.CAPACITY,'CAPACITY',self.capacity)

    def write(self,name,kind,value):
        self.conn.records[name]=continuity._bytes(continuity.seal(kind,value))

    def degraded(self):
        with patch.object(continuity,'require_absent_media'):
            return continuity.degraded(self.conn,operation='protected order')

    def test_explicit_policy_only(self):
        self.assertTrue(continuity.selected())
        os.environ.pop(continuity.POLICY_ENV)
        self.assertFalse(continuity.selected())

    def test_unknown_policy_refuses(self):
        os.environ[continuity.POLICY_ENV]='yes'
        with self.assertRaises(BackupConfigurationRefused): continuity.selected()

    def test_runtime_classifies_unknown_policy_as_integrity_refusal(self):
        os.environ[continuity.POLICY_ENV]='yes'
        with patch.object(local_paper,'backups_suspended_for_account',return_value=False):
            with self.assertRaises(runtime.BackupRuntimeRefused):
                runtime.require(self.conn,operation='protected order',allow_continuity=True)

    def test_normal_mode_cannot_acquire_grace(self):
        os.environ.pop(local_paper.MODE_ENV)
        with self.assertRaises(BackupConfigurationRefused): continuity.selected()

    def test_live_endpoint_cannot_acquire_grace(self):
        os.environ['ALPACA_BASE_URL']='https://api.alpaca.markets'
        with self.assertRaises(RuntimeError): continuity.selected()

    def test_suspended_backups_cannot_acquire_grace(self):
        os.environ[local_paper.BACKUP_POLICY_ENV]=''
        with self.assertRaises(BackupConfigurationRefused): continuity.selected()

    def test_record_hmac_and_domain(self):
        raw=self.conn.records[continuity.CHECKPOINT]
        self.assertEqual(continuity.authenticate(raw,'CHECKPOINT'),self.checkpoint)
        with self.assertRaises(BackupConfigurationRefused): continuity.authenticate(raw,'CAPACITY')

    def test_tampered_checkpoint_refuses(self):
        raw=self.conn.records[continuity.CHECKPOINT].replace(b'9990',b'9999')
        self.conn.records[continuity.CHECKPOINT]=raw
        with self.assertRaises(BackupConfigurationRefused): self.degraded()

    def test_duplicate_json_member_refuses(self):
        raw=self.conn.records[continuity.CHECKPOINT].replace(b'"kind":',b'"kind":"forged","kind":',1)
        with self.assertRaises(BackupConfigurationRefused): continuity.authenticate(raw,'CHECKPOINT')

    def test_oversized_checkpoint_refuses(self):
        with self.assertRaises(BackupConfigurationRefused):
            continuity.authenticate(b' '*(continuity.MAX_BYTES+1),'CHECKPOINT')

    def test_missing_checkpoint_refuses(self):
        self.conn.records.pop(continuity.CHECKPOINT)
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_valid_absence_allows_explicit_degraded_order(self):
        result=self.degraded()
        self.assertEqual(result['backup_state'],'DEGRADED')
        self.assertIs(result['independent_archive_current'],False)
        self.assertEqual(result['continuity_deadline'],9990+30*3600)
        self.assertFalse(any('mktemp' in sql for sql,_ in self.conn.statements))

    def test_healthy_later_frontier_does_not_retime_prior_checkpoint(self):
        self.conn.observation['last_archive_at']=9998
        self.conn.observation['last_archived_wal']='000000010000000000000004'
        self.assertEqual(self.degraded()['continuity_deadline'],9990+30*3600)

    def test_expired_at_exact_deadline_refuses(self):
        self.conn.observation['now']=9990+continuity.MAX_AGE
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_future_checkpoint_refuses(self):
        self.conn.observation['now']=9989
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_changed_epoch_account_system_runtime_or_postmaster_refuses(self):
        for key,value in [('takeover_epoch',2),('broker_account_id','PAFOREIGN'),
                ('system_identifier','2'),('runtime_image_digest','sha256:'+'c'*64),
                ('postmaster_start_us',999)]:
            with self.subTest(key=key):
                proof=copy.deepcopy(self.checkpoint); proof['context'][key]=value
                self.write(continuity.CHECKPOINT,'CHECKPOINT',proof)
                with self.assertRaises(BackupUnavailable): self.degraded()

    def test_archive_off_refuses(self):
        self.conn.observation['archive_mode']='off'
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_timeline_change_or_frontier_regression_refuses(self):
        for name in ['000000020000000000000004','000000010000000000000002']:
            self.conn.observation['last_archived_wal']=name
            with self.assertRaises(BackupUnavailable): self.degraded()

    def test_stale_future_or_unsafe_capacity_refuses(self):
        for key,value in [('observed_at',10000-continuity.CAPACITY_MAX_AGE),
                          ('observed_at',10001),('physical_free_bytes',continuity.RESERVE_BYTES-1),
                          ('physical_free_bytes',True),('engine_id','foreign'),
                          ('postmaster_start_us',456)]:
            with self.subTest(key=key,value=value):
                proof=dict(self.capacity);proof[key]=value
                self.write(continuity.CAPACITY,'CAPACITY',proof)
                with self.assertRaises(BackupUnavailable): self.degraded()

    def test_primary_wal_budget_refuses(self):
        self.conn.observation['primary_wal_bytes']=continuity.MAX_PRIMARY_WAL_BYTES
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_failed_primary_filesystem_probe_refuses(self):
        self.conn.program_error=True
        with self.assertRaises(BackupUnavailable): self.degraded()

    def test_mounted_media_refuses_grace(self):
        self.conn.program_error=True
        with self.assertRaises(BackupUnavailable):
            continuity.require_absent_media(self.conn)

    def test_media_is_rechecked_after_capacity_work(self):
        with patch.object(continuity,'require_absent_media',side_effect=[None,BackupUnavailable('reconnected')]) as check:
            with self.assertRaises(BackupUnavailable):
                continuity.degraded(self.conn,operation='order')
            self.assertEqual(check.call_count,2)

    def test_no_file_write_when_healthy_frontier_is_unchanged(self):
        continuity.remember(self.conn,copy.deepcopy(CHAIN))
        self.assertFalse(any('mktemp' in sql for sql,_ in self.conn.statements))

    def test_degraded_result_can_never_refresh_checkpoint(self):
        with self.assertRaises(BackupUnavailable):
            continuity.remember(self.conn,dict(CHAIN,backup_state='DEGRADED'))

    def test_healthy_proof_does_not_invent_checkpoint_without_capacity(self):
        self.conn.records.pop(continuity.CAPACITY)
        self.conn.records.pop(continuity.CHECKPOINT)
        continuity.remember(self.conn,copy.deepcopy(CHAIN))
        self.assertFalse(any('mktemp' in sql for sql,_ in self.conn.statements))

    def test_raced_later_archive_success_does_not_retime_chain(self):
        self.conn.observation['last_archived_wal']='000000010000000000000004'
        continuity.remember(self.conn,copy.deepcopy(CHAIN))
        self.assertFalse(any('mktemp' in sql for sql,_ in self.conn.statements))

    def test_runtime_uses_savepoint_and_degraded_path_only_for_unavailability(self):
        with patch.object(local_paper,'backups_suspended_for_account',return_value=False), \
             patch.object(runtime,'_require',side_effect=runtime.BackupRuntimeUnavailable('absent')), \
             patch.object(continuity,'degraded',return_value={'backup_state':'DEGRADED'}) as degraded:
            self.assertEqual(runtime.require(self.conn,operation='order',allow_continuity=True)['backup_state'],'DEGRADED')
            self.assertEqual(degraded.call_count,1)
            with self.assertRaises(runtime.BackupRuntimeUnavailable):
                runtime.require(self.conn,operation='install')
            self.assertEqual(degraded.call_count,1)

    def test_integrity_failure_is_never_an_outage(self):
        with patch.object(local_paper,'backups_suspended_for_account',return_value=False), \
             patch.object(runtime,'_require',side_effect=runtime.BackupRuntimeRefused('corrupt')), \
             patch.object(continuity,'degraded') as degraded:
            with self.assertRaises(runtime.BackupRuntimeRefused):
                runtime.require(self.conn,operation='order',allow_continuity=True)
            degraded.assert_not_called()

    def test_explicit_base_install_proof_stays_strict(self):
        with patch.object(local_paper,'backups_suspended_for_account',return_value=False), \
             patch.object(runtime,'_require',side_effect=runtime.BackupRuntimeUnavailable('absent')), \
             patch.object(continuity,'degraded') as degraded:
            with self.assertRaises(runtime.BackupRuntimeUnavailable):
                runtime.require(self.conn,operation='install',base_backup=CHAIN['base_backup'],allow_continuity=True)
            degraded.assert_not_called()

    def test_authentication_guard_removal_is_detected(self):
        raw=self.conn.records[continuity.CHECKPOINT].replace(b'9990',b'9999')
        self.conn.records[continuity.CHECKPOINT]=raw
        with self.assertRaises(BackupConfigurationRefused): self.degraded()
        # Execute the removed-authentication control: the same tampering is now
        # accepted by the parser, demonstrating that the real refusal is causal.
        with patch.object(continuity.hmac,'compare_digest',return_value=True):
            altered=continuity.authenticate(raw,'CHECKPOINT')
        self.assertEqual(altered['last_archive_at'],9999)

    def test_age_guard_removal_is_detected(self):
        self.conn.observation['now']=9990+continuity.MAX_AGE
        self.capacity['observed_at']=self.conn.observation['now']
        self.write(continuity.CAPACITY,'CAPACITY',self.capacity)
        with self.assertRaises(BackupUnavailable): self.degraded()
        with patch.object(continuity,'MAX_AGE',continuity.MAX_AGE+1):
            self.assertEqual(self.degraded()['backup_state'],'DEGRADED')


if __name__=='__main__':
    unittest.main()
