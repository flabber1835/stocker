"""Host transport owner checks: surprise removal never authorizes foreign unmounts."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC=importlib.util.spec_from_file_location('tested_backup_transport',
    Path(__file__).resolve().parents[2]/'scripts/sentinel_backup_transport.py')
transport=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)
CONFIG=dict(uuid='2ed4fe3b-def6-45db-940b-e78186758164',mount='/mnt/fixture-backup',
    backup='/mnt/fixture-backup/backup',transport='/run/sentinel-backup-transport-fixture')


def mount(number):
    return dict(id=number,device='8:81',fstype='ext4',source='/dev/sdf1',
                options=['rw'],super_options=['rw'],optional=[])


class BackupTransportTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(CONFIG)
        self.table={CONFIG['transport']+'/base':mount(101),CONFIG['transport']+'/wal':mount(102)}
        self.record=dict(config=dict(CONFIG),phase='ATTACHED',
            mounts={'base':copy.deepcopy(self.table[CONFIG['transport']+'/base']),
                    'wal':copy.deepcopy(self.table[CONFIG['transport']+'/wal'])})
        self.commands=[]
        self.saved=[]

    def detach(self,*,exists=True,remove=True):
        owner=SimpleNamespace(exists=lambda:exists,read_text=lambda:json.dumps(self.record))
        def runner(args):
            self.commands.append(args)
            if remove:self.table.pop(args[-1],None)
            return ''
        with patch.object(transport,'state_path',return_value=owner), \
             patch.object(transport,'_private_path'), \
             patch.object(transport,'_save',side_effect=lambda c,r:self.saved.append(r)):
            transport.detach(self.config,runner,lambda:self.table)

    def test_unplug_shutdown_flag_keeps_exact_mount_ownership(self):
        self.table[CONFIG['transport']+'/base']['super_options'].append('shutdown')
        self.table[CONFIG['transport']+'/wal']['super_options'].append('shutdown')
        self.detach()
        self.assertEqual(self.commands,[['umount','--lazy','--',CONFIG['transport']+'/wal'],
                                        ['umount','--lazy','--',CONFIG['transport']+'/base']])
        self.assertEqual(self.saved[-1]['phase'],'DETACHED')

    def test_foreign_mount_id_refuses_before_any_unmount(self):
        self.table[CONFIG['transport']+'/base']['id']=999
        with self.assertRaises(RuntimeError):self.detach()
        self.assertEqual(self.commands,[])

    def test_foreign_device_refuses(self):
        self.table[CONFIG['transport']+'/wal']['device']='8:99'
        with self.assertRaises(RuntimeError):self.detach()
        self.assertEqual(self.commands,[])

    def test_changed_config_refuses(self):
        self.record['config']['uuid']='11111111-1111-1111-1111-111111111111'
        with self.assertRaises(RuntimeError):self.detach()
        self.assertEqual(self.commands,[])

    def test_unrecorded_mount_refuses(self):
        with self.assertRaises(RuntimeError):self.detach(exists=False)
        self.assertEqual(self.commands,[])

    def test_absent_mounts_and_absent_record_are_noop(self):
        self.table.clear();self.detach(exists=False)
        self.assertEqual(self.commands,[])

    def test_partial_owned_attachment_only_unmounts_its_owned_child(self):
        self.table.pop(CONFIG['transport']+'/wal')
        self.record['mounts'].pop('wal')
        self.record['phase']='FAILED_INSPECT'
        self.detach()
        self.assertEqual(len(self.commands),1)
        self.assertTrue(self.commands[0][-1].endswith('/base'))

    def test_failed_unmount_never_claims_detached(self):
        with self.assertRaises(RuntimeError):self.detach(remove=False)
        self.assertEqual(self.saved,[])

    def test_already_detached_owner_is_not_replayed(self):
        self.table.clear();self.record.update(phase='DETACHED',mounts={})
        self.detach()
        self.assertEqual(self.commands,[])

    def test_generated_usb_unit_has_no_engine_lifetime_edge(self):
        files=transport.unit_files(CONFIG,'/usr/local/libexec/sentinel-backup-transport.py',
            '/etc/sentinel-backup-transport.json',lambda a:'mnt-fixture.mount')
        self.assertNotIn('RequiresMountsFor',files['docker-storage.conf'])
        self.assertNotIn('mnt-fixture.mount',files['docker-storage.conf'])
        self.assertNotIn('docker.service',files['sentinel-backup-transport.service'])
        self.assertIn('BindsTo=mnt-fixture.mount',files['sentinel-backup-transport.service'])
        self.assertNotIn('docker.service',files['udev.rules'])

    def test_foreign_mount_guard_removal_is_detected(self):
        self.table[CONFIG['transport']+'/base']['id']=999
        with self.assertRaises(RuntimeError):self.detach()
        with patch.object(transport,'_same_mount',return_value=True):
            self.detach()
        self.assertEqual(len(self.commands),2)


if __name__=='__main__':
    unittest.main()
