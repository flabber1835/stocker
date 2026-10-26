"""Backed application roll preserves the legacy path and requires real proof."""
from copy import deepcopy
import importlib
import os
from pathlib import Path
import sys

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
patch=importlib.import_module('sentinel_backed_local_patch')
from tests.scripts import test_sentinel_local_delivery_evidence as fixture


def backed_host():
    host=fixture.Host()
    host.state.update(archive_mode='on',archive_command='/canonical/archive %p %f')
    host.request['predecessor']['postgres']={'command':['postgres','-c','archive_mode=on',
        '-c','archive_command=/canonical/archive %p %f']}
    host.load_values=lambda:{'SENTINEL_LOCAL_PAPER_ACCOUNT_ID':'PAPER-Z',
        'SENTINEL_LOCAL_PAPER_BACKUP_POLICY':'REQUIRED_V1'}
    return host


def test_backed_snapshot_accepts_only_preserved_archive_on_configuration():
    host=backed_host()
    assert fixture.evidence.snapshot(host)['archive_mode']=='on'


@pytest.mark.parametrize('key,value',[('archive_mode','off'),('archive_command','foreign'),
                                    ('fsync','off'),('full_page_writes','off')])
def test_backed_snapshot_refuses_durability_changes(key,value):
    host=backed_host();host.state[key]=value
    with pytest.raises(fixture.model.DeliveryRefused):fixture.evidence.snapshot(host)


def test_legacy_archive_off_mode_does_not_inherit_backed_permissions():
    host=fixture.Host();host.state['archive_mode']='on'
    with pytest.raises(fixture.model.DeliveryRefused):fixture.evidence.snapshot(host)


def witness():
    request={'candidate':{'image':'sha256:'+'a'*64},'predecessor':{'system':'1234'}}
    value={'authentic':True,'age':50,'proof':{'physical_only':False,
        'runtime_image':request['candidate']['image'],'system_identifier':'1234',
        'metadata_sha256':'b'*64,'base_backup':'base-20261026T000000Z'}}
    return value,request


def test_candidate_full_restore_is_required():
    patch.require_restore(*witness())


@pytest.mark.parametrize('key,value',[('physical_only',True),('runtime_image','foreign'),
    ('system_identifier','foreign'),('metadata_sha256',''),('base_backup','../base')])
def test_foreign_physical_or_malformed_restore_refuses(key,value):
    value_record,request=witness();value_record['proof'][key]=value
    with pytest.raises(patch.DeliveryRefused):patch.require_restore(value_record,request)


@pytest.mark.parametrize('key,value',[('authentic',False),('age',-1),('age',86401)])
def test_restore_freshness_and_content_authentication_still_refuse(key,value):
    record,request=witness();record[key]=value
    with pytest.raises(patch.DeliveryRefused):patch.require_restore(record,request)


def test_removing_restore_subject_guard_is_detected(monkeypatch):
    monkeypatch.setattr(patch,'require_restore',lambda *a:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_foreign_physical_or_malformed_restore_refuses('runtime_image','foreign')


def test_postgres_archive_off_cannot_become_a_backed_baseline():
    data={'Mounts':[{'Destination':'/var/lib/postgresql/data','Type':'volume',
        'Name':'sentinel_sentinel_pgdata','Source':'/private/owned'}],
        'State':{'Running':True,'StartedAt':'original'},'Id':'container','Image':'postgres',
        'Config':{'Cmd':['postgres','-c','archive_mode=off']}}
    with pytest.raises(patch.DeliveryRefused,match='ARCHIVE_OFF'):
        patch.postgres_facts(data)
