"""Replay the November 9 independent daily renewal, including its cadence gap."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import inspect,textwrap

import pytest

from sentinel.panel import model,presentation

def stamp(value):return datetime.fromisoformat('2026-11-09T'+value+'+00:00')


def copying():
    before='base-20261108T090052Z'
    return dict(now=stamp('09:09:53'),base_at=datetime(2026,11,8,9,13,35,tzinfo=timezone.utc),
      restore_at=datetime(2026,10,25,12,tzinfo=timezone.utc),runtime_at=stamp('08:59:50'),
      runtime_valid_until=stamp('09:09:50'),
      base_proof=dict(base_backup=before,marker='marker',marker_lsn='3B/BB01C0E8',marker_wal='wal',system_identifier='123'),
      restore_proof=dict(base_backup='base-20261025T090000Z',physical_only=False,marker='drill',target_lsn='0/1',system_identifier='123'),
      runtime_proof=dict(enabled=True,base_backup=before,system_identifier='123',wal_integrity='sha256-sidecar-v1',
       recoverable_from_wal='start',recoverable_through_wal='end',wal_segments=2),
      maintenance_at=stamp('09:04:55'),maintenance_proof=dict(schema='sentinel.backup-maintenance-progress/1',
       attempt='a'*32,started_at=int(stamp('09:04:53').timestamp()),deadline=int(stamp('10:04:53').timestamp()),
       system_identifier='123',image='sha256:'+'9'*64,predecessor_base=before,base_backup=before,phase='BASE_BACKUP'))


def normal(values,row):
    return presentation._normal_warning(model.Panel(rows=[row],now=values['now']),row)


def test_observed_slow_copy_is_ordinary_without_application_image_or_deadline_extension(monkeypatch):
    values=copying();monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST','sha256:'+'2'*64)
    row=model.backup_restore_row(**values)
    assert row.status==model.WARN and row.value=='BACKUP CHECK IN PROGRESS'
    assert row.valid_until==stamp('10:04:53') and row.as_of==values['maintenance_at']
    assert normal(values,row)
    assert row.effective_status(stamp('10:04:54'))==model.FAIL
    assert values['runtime_valid_until']==stamp('09:09:50')


def test_exact_rollover_completes_only_with_fresh_successor_chain():
    values=copying();values['now']=stamp('09:13:20')
    values['base_at']=stamp('09:13:19');values['base_proof']['base_backup']='base-20261109T090457Z'
    values['maintenance_at']=stamp('09:13:20');values['maintenance_proof'].update(
      phase='VERIFY_CHAIN',base_backup=values['base_proof']['base_backup'])
    row=model.backup_restore_row(**values);assert normal(values,row)
    values['maintenance_proof']['phase']='COMPLETE'
    assert model.backup_restore_row(**values).status==model.FAIL
    values.update(now=stamp('09:13:31'),runtime_at=stamp('09:13:23'),runtime_valid_until=stamp('09:23:23'))
    values['runtime_proof']['base_backup']=values['base_proof']['base_backup']
    assert model.backup_restore_row(**values).status==model.OK


@pytest.mark.parametrize('which',['base','drill'])
def test_maintenance_cannot_outlive_the_original_base_or_drill_objective(which):
    values=copying();boundary=values['now']+timedelta(seconds=20)
    values['base_at' if which=='base' else 'restore_at']=boundary-(
        timedelta(hours=26) if which=='base' else timedelta(days=31))
    row=model.backup_restore_row(**values)
    assert row.valid_until==row.recovery.deadline==boundary
    assert row.effective_status(boundary+timedelta(microseconds=1))==model.FAIL


def test_ordinary_maintenance_does_not_create_review_conditions_or_hide_another_failure():
    values=copying();row=model.backup_restore_row(**values)
    panel=model.Panel(rows=[row],now=values['now'])
    assert presentation.health_facts(panel)=={'active':[],'warnings':[]}
    broken=replace(panel,rows=[row,model.Row('broker','Broker','DOWN',model.FAIL)])
    assert 'broker' in presentation.health_facts(broken)['active']


@pytest.mark.parametrize('fault',['missing','phase','deadline','future','image','cluster','lineage','old_chain',
 'old_base','old_drill','integrity','marker','failed','complete'])
def test_copy_progress_never_excuses_foreign_or_unbounded_failure(fault):
    values=copying()
    if fault=='missing':values['maintenance_proof']=None
    elif fault=='phase':values['maintenance_proof']['phase']='arbitrary'
    elif fault=='deadline':values['now']=stamp('10:04:54')
    elif fault=='future':values['maintenance_at']=stamp('09:10:00')
    elif fault=='image':values['maintenance_proof']['image']='mutable:latest'
    elif fault=='cluster':values['maintenance_proof']['system_identifier']='456'
    elif fault=='lineage':values['maintenance_proof']['base_backup']='base-20261109T090457Z'
    elif fault=='old_chain':values['runtime_at']=stamp('08:50:00')
    elif fault=='old_base':values['base_at']=values['now']-timedelta(hours=27)
    elif fault=='old_drill':values['restore_at']=values['now']-timedelta(days=32)
    elif fault=='integrity':values['runtime_proof']['wal_integrity']='bad'
    elif fault=='marker':values['base_proof'].pop('marker')
    else:values['maintenance_proof']['phase']=fault.upper()
    row=model.backup_restore_row(**values)
    assert row.effective_status(values['now'])==model.FAIL
    assert not normal(values,row)


def test_copy_lineage_guard_has_executed_falsifier():
    code=textwrap.dedent(inspect.getsource(model.backup_restore_row))
    guard="and progress.base_backup == progress.predecessor_base"
    assert guard in code
    namespace=dict(vars(model));exec(code.replace(guard,''),namespace)
    values=copying();values['maintenance_proof']['predecessor_base']='base-20261107T090000Z'
    # Break the complete predecessor binding, including its general identity arm.
    altered=code.replace(guard,'').replace("and progress.predecessor_base == str(runtime_proof.get('base_backup') or '')",'')
    exec(altered,namespace)
    assert model.backup_restore_row(**values).status==model.FAIL
    assert namespace['backup_restore_row'](**values).status==model.WARN


@pytest.mark.parametrize('fault',['value','phase','deadline','status'])
def test_headline_requires_exact_earned_maintenance_row(fault):
    values=copying();row=model.backup_restore_row(**values)
    if fault=='value':row=replace(row,value='ordinary warning')
    elif fault=='phase':row=replace(row,recovery=replace(row.recovery,phase='OTHER'))
    elif fault=='deadline':row=replace(row,valid_until=row.valid_until+timedelta(seconds=1))
    else:row=replace(row,status=model.FAIL)
    assert not normal(values,row)
