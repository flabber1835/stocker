"""Backed application roll preserves the legacy path and requires real proof."""
from copy import deepcopy
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import textwrap

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


def test_application_validation_does_not_query_or_run_a_restore(monkeypatch):
    from sentinel_local_delivery.host import Host
    monkeypatch.setattr(Host,'verify_candidate',lambda self:{'source':'qualified'})
    host=object.__new__(patch.BackedHost)
    host.sql=lambda *_args:pytest.fail('application validation queried recovery evidence')
    host.run=lambda *_args,**_kwargs:pytest.fail('application validation launched extra work')
    assert host.verify_candidate()=={'source':'qualified'}


def test_reintroducing_image_specific_restore_gate_is_detected(monkeypatch):
    monkeypatch.setattr(patch.BackedHost,'verify_candidate',lambda self:self.sql('RESTORE_DRILL'))
    with pytest.raises(pytest.fail.Exception,match='queried recovery evidence'):
        test_application_validation_does_not_query_or_run_a_restore(monkeypatch)


@pytest.mark.parametrize('fault',[None,'state','receipt','runtime','proof','stage',
    'issuer_count','issuer_hash','issuer_shape','issuer_boolean','issuer_missing'])
def test_retained_predecessor_proof_requires_exact_unchanged_subject(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    prior=tmp_path/'prior';prior.mkdir()
    path=prior/'receipt.json'
    record=dict(stage='VERIFIED',artifacts=dict(preserved={'book':'same'},
        canonical_proof={'book':'verified'},successor_proof_sha256=patch.digest({'book':'verified'})))
    if fault=='proof':record['artifacts']['successor_proof_sha256']='foreign'
    if fault=='stage':record['stage']='SHADOW_STARTED'
    path.write_text(json.dumps(record))
    old=dict(commit='1'*40,image='sha256:'+'a'*64)
    built=dict(predecessor_receipt=dict(path=str(path),sha256=patch.sha256_file(path)))
    (tmp_path/'build.json').write_text(json.dumps(built))
    if fault=='receipt':path.write_text(path.read_text()+' ')
    monkeypatch.setattr(patch,'Journal',lambda folder:SimpleNamespace(
        request={'candidate':dict(old,image='foreign') if fault=='runtime' else old},read=lambda:record))
    host=object.__new__(patch.BackedHost)
    host.operation_dir=tmp_path;host.predecessor_receipt=path;host.request={'predecessor':old}
    state={'book':'changed' if fault=='state' else 'same',
        'issuer_evidence':{'count':0,'md5':patch.checks.EMPTY_ISSUER_EVIDENCE_MD5}}
    if fault=='issuer_count':state['issuer_evidence']['count']=1
    elif fault=='issuer_hash':state['issuer_evidence']['md5']='a'*32
    elif fault=='issuer_shape':state['issuer_evidence']['extra']='unbound'
    elif fault=='issuer_boolean':state['issuer_evidence']['count']=False
    elif fault=='issuer_missing':state.pop('issuer_evidence')
    if fault in {'receipt','runtime','proof','stage'}:
        with pytest.raises(patch.DeliveryRefused):host.predecessor_canonical_proof(state)
    else:
        missing_proof=fault=='state' or (isinstance(fault,str) and fault.startswith('issuer_'))
        assert host.predecessor_canonical_proof(state)==(None if missing_proof else {'book':'verified'})


def test_removed_retained_predecessor_anchor_guard_is_detected(tmp_path,monkeypatch):
    original=patch.require
    monkeypatch.setattr(patch,'require',lambda ok,reason:
        None if reason=='BACKED_PREDECESSOR_ANCHOR_CHANGED' else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_retained_predecessor_proof_requires_exact_unchanged_subject(tmp_path,monkeypatch,'receipt')


def test_legacy_empty_issuer_bridge_has_a_falsifier(tmp_path,monkeypatch):
    source=textwrap.dedent(inspect.getsource(patch.BackedHost.predecessor_canonical_proof))
    needle="type(issuer['count']) is int and issuer['count']==0"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,"type(issuer['count']) is int"),
        'missing-empty-issuer-bridge-guard','exec'),vars(patch),namespace)
    monkeypatch.setattr(patch.BackedHost,'predecessor_canonical_proof',namespace['predecessor_canonical_proof'])
    with pytest.raises(AssertionError):
        test_retained_predecessor_proof_requires_exact_unchanged_subject(
            tmp_path,monkeypatch,'issuer_count')


@pytest.mark.parametrize('changed',[False,True])
def test_current_receipts_preserve_their_full_nonempty_issuer_snapshot(tmp_path,monkeypatch,changed):
    from types import SimpleNamespace
    prior=tmp_path/'prior';prior.mkdir()
    path=prior/'receipt.json'
    state={'book':'same','issuer_evidence':{'count':2,'md5':'a'*32}}
    record=dict(stage='VERIFIED',artifacts=dict(preserved=deepcopy(state),
        canonical_proof={'book':'verified'},successor_proof_sha256=patch.digest({'book':'verified'})))
    path.write_text(json.dumps(record))
    old=dict(commit='1'*40,image='sha256:'+'a'*64)
    built=dict(predecessor_receipt=dict(path=str(path),sha256=patch.sha256_file(path)))
    (tmp_path/'build.json').write_text(json.dumps(built))
    monkeypatch.setattr(patch,'Journal',lambda _folder:SimpleNamespace(
        request={'candidate':old},read=lambda:record))
    host=object.__new__(patch.BackedHost)
    host.operation_dir=tmp_path;host.predecessor_receipt=path;host.request={'predecessor':old}
    if changed:state['issuer_evidence']['md5']='b'*32
    assert host.predecessor_canonical_proof(state)==(None if changed else {'book':'verified'})


def test_postgres_archive_off_cannot_become_a_backed_baseline():
    data={'Mounts':[{'Destination':'/var/lib/postgresql/data','Type':'volume',
        'Name':'sentinel_sentinel_pgdata','Source':'/private/owned'}],
        'State':{'Running':True,'StartedAt':'original'},'Id':'container','Image':'postgres',
        'Config':{'Cmd':['postgres','-c','archive_mode=off']}}
    with pytest.raises(patch.DeliveryRefused,match='ARCHIVE_OFF'):
        patch.postgres_facts(data)


def postgres_identity():
    return dict(container='original-container',image='original-image',
        started='2026-01-01T00:00:00Z',volume='sentinel_sentinel_pgdata',
        source='/original/volume',command=['postgres','-c','archive_mode=on'])


def test_final_observation_can_record_a_new_process_start_without_rewriting_preflight():
    before=postgres_identity();after=dict(before,started='2026-01-02T00:00:00Z')
    patch.require_same_postgres_storage(before,after)
    assert before['started']=='2026-01-01T00:00:00Z'


@pytest.mark.parametrize('key', ['container','image','volume','source','command'])
def test_restart_observation_refuses_replacement_database_or_configuration(key):
    before=postgres_identity();after=dict(before,started='2026-01-02T00:00:00Z')
    after[key]='foreign'
    with pytest.raises(patch.DeliveryRefused,match='STORAGE_CHANGED'):
        patch.require_same_postgres_storage(before,after)


@pytest.mark.parametrize('started', ['2025-01-01T00:00:00Z','2099-01-01T00:00:00Z',
                                   '2026-01-02T00:00:00'])
def test_restart_observation_refuses_backwards_future_or_unzoned_clock(started):
    with pytest.raises(patch.DeliveryRefused,match='TIME_INVALID'):
        patch.require_same_postgres_storage(postgres_identity(),dict(postgres_identity(),started=started))


def test_restart_storage_guard_has_falsifier(monkeypatch):
    original=patch.require
    monkeypatch.setattr(patch,'require',lambda value,reason:
        None if reason=='BACKED_POSTGRES_STORAGE_CHANGED' else original(value,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_restart_observation_refuses_replacement_database_or_configuration('volume')


@pytest.mark.parametrize('fault', [None,'not_selected','not_started','financial','native',
                                 'history','image','unhealthy','stopped','oom','restarting'])
def test_started_replacement_requires_each_preservation_boundary(monkeypatch, fault):
    from types import SimpleNamespace
    from sentinel_local_delivery import evidence
    expected=postgres_identity()
    record=dict(unfinished=True,postgres=expected,system='original-system',
        preserved={'book':'original'},native_positions={'A':'7'},notification_history={'old':'record'})
    item=dict(Image='original-image',State=dict(Running=True,Health={'Status':'healthy'},
        OOMKilled=False,Restarting=False))
    host=SimpleNamespace(allow_started_predecessor=True,request={'predecessor':{}},container=lambda name:item)
    monkeypatch.setattr(evidence,'snapshot',lambda h:{'book':'changed' if fault=='financial' else 'original'})
    monkeypatch.setattr(evidence,'native_positions',lambda *a:{'A':'8' if fault=='native' else '7'})
    def history(*args):patch.require(fault!='history','NOTIFICATION_HISTORY_CHANGED')
    monkeypatch.setattr(evidence,'check_notification_history',history)
    if fault=='not_selected':host.allow_started_predecessor=False
    if fault=='not_started':record['unfinished']=False
    if fault=='image':item['Image']='foreign'
    if fault=='unhealthy':item['State']['Health']['Status']='unhealthy'
    if fault=='stopped':item['State']['Running']=False
    if fault=='oom':item['State']['OOMKilled']=True
    if fault=='restarting':item['State']['Restarting']=True
    if fault is None:
        patch.require_started_state(host,record,{},dict(expected,started='2026-01-02T00:00:00Z'),'original-image')
    else:
        with pytest.raises(patch.DeliveryRefused):
            patch.require_started_state(host,record,{},dict(expected,started='2026-01-02T00:00:00Z'),'original-image')


def test_image_overlay_changes_only_exact_application_selectors(tmp_path):
    image='sha256:'+'a'*64
    path=patch.immutable_image_overlay(tmp_path,image)
    expected={'services':{name:{'image':image,'pull_policy':'never'}
        for name in (*patch.SERVICES,'sentinel','sentinel-authorized-cli')}}
    assert json.loads(path.read_text())==expected
    assert 'sentinel-postgres' not in expected['services']
    assert patch.immutable_image_overlay(tmp_path,image)==path


@pytest.mark.parametrize('image',['mutable:latest','repo@sha256:'+'a'*64,'sha256:'+'a'*63])
def test_image_overlay_refuses_nonlocal_or_mutable_selectors(tmp_path,image):
    with pytest.raises(patch.DeliveryRefused,match='OVERLAY_IMAGE_INVALID'):
        patch.immutable_image_overlay(tmp_path,image)


def test_image_overlay_refuses_changed_retained_bytes(tmp_path):
    image='sha256:'+'a'*64
    path=patch.immutable_image_overlay(tmp_path,image)
    path.write_text('{}')
    with pytest.raises(patch.DeliveryRefused,match='OVERLAY_CHANGED'):
        patch.immutable_image_overlay(tmp_path,image)


def test_image_overlay_refuses_symlink(tmp_path):
    image='sha256:'+'a'*64
    path=patch.immutable_image_overlay(tmp_path,image)
    target=tmp_path/'other';path.rename(target);path.symlink_to(target)
    with pytest.raises(patch.DeliveryRefused,match='OVERLAY_UNSAFE'):
        patch.immutable_image_overlay(tmp_path,image)


def test_image_overlay_tamper_guard_has_a_falsifier(tmp_path,monkeypatch):
    original=patch.require
    monkeypatch.setattr(patch,'require',lambda value,reason:
        None if reason=='BACKED_IMAGE_OVERLAY_CHANGED' else original(value,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_image_overlay_refuses_changed_retained_bytes(tmp_path)


def test_backed_compose_adds_image_overlay_without_changing_backing(tmp_path):
    host=object.__new__(patch.BackedHost)
    host.source=tmp_path;host.operation_dir=tmp_path
    old='1'*40;new='2'*40;old_image='sha256:'+'a'*64;new_image='sha256:'+'b'*64
    host.request={'predecessor':{'commit':old,'image':old_image},
        'candidate':{'commit':new,'image':new_image}}
    for commit,image in [(old,old_image),(new,new_image)]:
        values={'SENTINEL_GIT_COMMIT':commit,'SENTINEL_RUNTIME_IMAGE_DIGEST':image,
            'SENTINEL_LOCAL_PAPER_IMAGE':image}
        paths=host.compose_paths(values)
        assert paths[:3]==tuple(tmp_path/name for name in patch.COMPOSE)
        assert len(paths)==4
        assert all(item['image']==image for item in json.loads(paths[-1].read_text())['services'].values())
        values['SENTINEL_LOCAL_PAPER_IMAGE']=old_image if image==new_image else new_image
        with pytest.raises(patch.DeliveryRefused,match='SELECTOR_CHANGED'):
            host.compose_paths(values)


def settled_host():
    host=backed_host();host.supports_post_trade=True;host.request['handoff_mode']='POST_TRADE'
    host.state['cycle'].update(state='SUCCEEDED',completed_at='2031-04-22T14:00:00Z',
        last_clean_reconciliation_id='247',failure_code=None,failure_detail=None)
    host.state['reconciliation']={'seq':247,'fingerprint':'original','provenance':'original'}
    return host


def test_post_trade_preserves_a_completed_reconciled_plan():
    host=settled_host()
    assert fixture.evidence.snapshot(host)==host.state
    assert host.calls==[fixture.checks.snapshot_sql('POST_TRADE')]


@pytest.mark.parametrize('fault',['adapter','policy','state','completed','reconciliation','wrong_observation','failure'])
def test_post_trade_refuses_unsettled_or_unsupported_handoffs(fault):
    host=settled_host()
    if fault=='adapter':host.supports_post_trade=False
    elif fault=='policy':host.load_values=lambda:{'SENTINEL_LOCAL_PAPER_BACKUP_POLICY':''}
    elif fault=='state':host.state['cycle']['state']='RECONCILING'
    elif fault=='completed':host.state['cycle']['completed_at']=None
    elif fault=='reconciliation':host.state['reconciliation']=None
    elif fault=='wrong_observation':host.state['reconciliation']['seq']=248
    else:host.state['cycle']['failure_code']='UNKNOWN_OUTCOME'
    with pytest.raises(fixture.model.DeliveryRefused):fixture.evidence.snapshot(host)


def test_reconciliation_guard_removal_has_a_falsifier(monkeypatch):
    original=fixture.evidence.require
    monkeypatch.setattr(fixture.evidence,'require',lambda value,reason:
        None if reason=='POST_TRADE_POSITIVE_RECONCILIATION_REQUIRED' else original(value,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_post_trade_refuses_unsettled_or_unsupported_handoffs('wrong_observation')
