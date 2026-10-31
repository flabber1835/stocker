"""Canonical backed environments never fabricate archive-off metadata."""
from contextlib import nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_backed_local_patch import patch
import sentinel_env


def host_fixture(tmp_path, monkeypatch):
    root=tmp_path/'canonical';root.mkdir();(root/'.git').mkdir()
    authority=root/'artifacts/sentinel/authority'
    receipt=authority/'deployments/attempt/activation-receipt.json'
    receipt.parent.mkdir(parents=True)
    old,image='1'*40,'sha256:'+'a'*64
    receipt.write_text(json.dumps(dict(schema='sentinel.activation-receipt/1',
        operational_ready=True,activation_mode='dual',completed_at='2031-01-01T00:00:00+00:00',
        runtime_image=image,git_commit=old,control_generation=86,certificate_sha256='certificate')))
    source=tmp_path/'qualified';source.mkdir()
    op=tmp_path/'operation';op.mkdir()
    host=object.__new__(patch.BackedHost)
    host.source=source;host.deployment=root;host.operation_dir=op
    host.predecessor_receipt=receipt;host.predecessor_roots=(root,)
    host.allow_started_predecessor=False
    host.request=dict(source=str(source),deployment=str(root),predecessor=dict(
        commit=old,image=image,postgres={'same':'postgres'},system='123'),
        candidate=dict(commit='2'*40,image='sha256:'+'b'*64,
            source_identity=dict(source='3'*64,wealth='4'*64,shadow_config='5'*64)))
    previous=dict(SENTINEL_GIT_COMMIT=old,SENTINEL_RUNTIME_IMAGE_DIGEST=image,
        SENTINEL_TEST_IMAGE_DIGEST=image,SENTINEL_RUNTIME_IMAGE_REF=image,SENTINEL_LOCAL_PAPER_IMAGE=image,
        SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256='6'*64,SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256='7'*64,
        SENTINEL_LOCAL_PAPER_BACKUP_POLICY='REQUIRED_V1',SENTINEL_AUTHORITY_ARTIFACTS_DIR=str(authority),
        PRESERVED='same literal value')
    def save(values):
        (root/'.env').write_text(''.join(key+'='+json.dumps(value)+'\n' for key,value in sorted(values.items())))
    save(previous)
    host.literal=SimpleNamespace(parse_bytes=sentinel_env.parse_bytes)
    host.load_values=lambda:sentinel_env.parse_bytes((root/'.env').read_bytes())
    candidate=host.candidate_values(previous)
    built=dict(predecessor_receipt=dict(path=str(receipt),sha256=patch.sha256_file(receipt)),
        foundation=deepcopy(host.request['predecessor']),commit=host.request['candidate']['commit'],
        image=host.request['candidate']['image'],source_identity=host.request['candidate']['source_identity'],
        source=str(source),deployment=str(root))
    (op/'build.json').write_text(json.dumps(built))
    monkeypatch.setattr(patch,'Journal',lambda folder:SimpleNamespace(request=host.request))
    monkeypatch.setattr(patch.builder,'_inspect',lambda selected,reference:dict(Id=image,
        Config=dict(Labels={'org.opencontainers.image.revision':old})))
    return host,previous,candidate,save


def test_canonical_absence_installs_under_native_ownership_without_archive_metadata(tmp_path,monkeypatch):
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    with host.owned():
        assert host._values_install_owned is True
        host.install_values(old,new)
    assert host._values_install_owned is False
    assert host.load_values()==new
    assert not (host.deployment/'local-delivery.json').exists()
    assert not list(host.deployment.glob('.env.local-delivery-*'))


def test_exact_candidate_replay_does_not_replace_or_fabricate_metadata(tmp_path,monkeypatch):
    host,old,new,save=host_fixture(tmp_path,monkeypatch);save(new)
    monkeypatch.setattr(Path,'replace',lambda *_:pytest.fail('exact candidate was rewritten'))
    with host.owned():host.install_values(new,new)
    assert host.load_values()==new and not (host.deployment/'local-delivery.json').exists()


@pytest.mark.parametrize('fault',['owner','anchor_hash','anchor_path','active','foundation',
    'candidate','source','environment','non_runtime','symlink'])
def test_unowned_changed_or_malformed_canonical_boundary_refuses_before_write(tmp_path,monkeypatch,fault):
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    path=host.operation_dir/'build.json';built=json.loads(path.read_text())
    if fault=='anchor_hash':built['predecessor_receipt']['sha256']='0'*64
    elif fault=='anchor_path':built['predecessor_receipt']['path']=str(tmp_path/'foreign.json')
    elif fault=='active':
        value=json.loads(host.predecessor_receipt.read_text());value['operational_ready']=False
        host.predecessor_receipt.write_text(json.dumps(value))
        built['predecessor_receipt']['sha256']=patch.sha256_file(host.predecessor_receipt)
    elif fault=='foundation':built['foundation']['commit']='f'*40
    elif fault=='candidate':built['image']='sha256:'+'f'*64
    elif fault=='source':built['source']=str(tmp_path)
    elif fault=='environment':old=dict(old,PRESERVED='not current')
    elif fault=='non_runtime':new=dict(new,PRESERVED='changed')
    elif fault=='symlink':
        target=tmp_path/'private-env';target.write_bytes((host.deployment/'.env').read_bytes())
        (host.deployment/'.env').unlink();(host.deployment/'.env').symlink_to(target)
    path.write_text(json.dumps(built))
    before=(host.deployment/'.env').read_bytes()
    with (nullcontext() if fault=='owner' else host.owned()):
        with pytest.raises(patch.DeliveryRefused):host.install_values(old,new)
    assert (host.deployment/'.env').read_bytes()==before
    assert not (host.deployment/'local-delivery.json').exists()


@pytest.mark.parametrize('bad',['malformed','list','symlink'])
def test_present_invalid_archive_metadata_refuses_before_environment_replace(tmp_path,monkeypatch,bad):
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    metadata=host.deployment/'local-delivery.json'
    if bad=='symlink':metadata.symlink_to(host.predecessor_receipt)
    else:metadata.write_text('{' if bad=='malformed' else '[]')
    before=(host.deployment/'.env').read_bytes()
    with pytest.raises((patch.DeliveryRefused,ValueError)):host.install_values(old,new)
    assert (host.deployment/'.env').read_bytes()==before


def test_present_archive_metadata_keeps_the_existing_update_contract(tmp_path,monkeypatch):
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    metadata=host.deployment/'local-delivery.json';metadata.write_text('{"retained":"archive proof"}')
    host.install_values(old,new)
    actual=json.loads(metadata.read_text())
    assert actual==dict(retained='archive proof',commit=host.request['candidate']['commit'],
        image=host.request['candidate']['image'],identity=host.request['candidate']['source_identity'])
    assert host.load_values()==new


@pytest.mark.parametrize('after_replace',[False,True])
def test_failure_before_or_after_atomic_replace_has_safe_exact_resume(tmp_path,monkeypatch,after_replace):
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    synced=[];fsync=os.fsync
    def sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):synced.append('directory')
        return fsync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    replace=Path.replace
    def fail(path,target):
        if path.name.startswith('.env.local-delivery-'):
            if after_replace:replace(path,target)
            raise OSError('simulated lost host acknowledgement')
        return replace(path,target)
    monkeypatch.setattr(Path,'replace',fail)
    with host.owned():
        with pytest.raises(OSError):host.install_values(old,new)
    assert host.load_values()==(new if after_replace else old)
    monkeypatch.setattr(Path,'replace',replace)
    with host.owned():host.install_values(host.load_values(),new)
    assert synced==['directory'], 'lost acknowledgement did not complete the directory durability barrier'
    assert host.load_values()==new and not (host.deployment/'local-delivery.json').exists()
    assert not list(host.deployment.glob('.env.local-delivery-*'))
