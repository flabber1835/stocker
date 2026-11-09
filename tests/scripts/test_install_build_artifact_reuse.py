"""A fresh installation owns fresh authority, not another Docker build."""
from copy import deepcopy
from pathlib import Path

import pytest

from tests.scripts.test_sentinel_local_delivery_cli import (
    OLD, inputs, run_build, builder, cli, model, qualification)
from tests.scripts.test_sentinel_backed_predecessor import chain
from tests.scripts.test_sentinel_access_path_bootstrap import make_host


class Candidate:
    checks = []

    def __init__(self, request, folder):
        self.request, self.folder = request, folder

    def verify_candidate(self):
        # The backed adapter resolves its predecessor this way during prepare.
        assert builder.operation_build(self.folder)['image'] == self.request['candidate']['image']
        self.checks.append(deepcopy(self.request))


def prepare(inputs, folder, **kwargs):
    path = inputs.folder/'build.json'
    return cli.prepare(operation_dir=folder,build_record=path,
        build_sha256=qualification.sha256_file(path),operation_id=folder.name,
        host_type=Candidate,**kwargs)


def test_new_attempt_reuses_original_build_without_copy_build_retag_or_old_authority(inputs,monkeypatch):
    built,builds,_ = run_build(inputs,monkeypatch)
    original = {p:p.read_bytes() for p in inputs.folder.rglob('*') if p.is_file()}
    # Earlier attempt state is deliberately terminal-looking and expired. Only
    # its completed artifact, never its authority, is an input to the new one.
    for name in ('request.json','receipt.json','abandonment.json'):
        model.write_new(inputs.folder/name,{'old':'expired/abandoned'})
    Candidate.checks = []
    for name in ('fresh-first','fresh-second'):
        folder = inputs.folder.parent/name
        journal = prepare(inputs,folder)
        assert journal.read()['stage'] == 'NEW'
        assert journal.read()['history'] == [] and journal.read()['artifacts'] == {}
        assert journal.request['candidate']['image'] == built['image']
        assert journal.request['predecessor']['commit'] == OLD
        assert journal.request['operation_id'] == name
        assert builder.operation_build(folder) == built
        assert sorted(p.name for p in folder.iterdir()) == [
            'build-reference.json','request.json']
        assert model.read_json(folder/'build-reference.json') == dict(
            schema=builder.BUILD_REFERENCE_SCHEMA,path=str(inputs.folder/'build.json'),
            sha256=qualification.sha256_file(inputs.folder/'build.json'),
            request_sha256=journal.subject)
    assert len(builds) == 1 and len(Candidate.checks) == 2
    assert all(path.read_bytes() == raw for path,raw in original.items())


@pytest.mark.parametrize('fault',['record','log','source','qualification','predecessor','image','partial'])
def test_reuse_refuses_changed_or_incomplete_evidence_without_rebuild(inputs,monkeypatch,fault):
    built,builds,_ = run_build(inputs,monkeypatch)
    folder = inputs.folder.parent/'refused'
    path = inputs.folder/'build.json'
    expected = qualification.sha256_file(path)
    if fault == 'record':path.write_text('{}')
    elif fault == 'log':Path(built['log']).write_text('changed')
    elif fault == 'source':(inputs.source/'sentinel/module.py').write_text('changed')
    elif fault == 'qualification':inputs.log.write_text('qualification changed')
    elif fault == 'predecessor':inputs.previous.write_text('{}')
    elif fault == 'partial':path.unlink()
    class MissingImage(Candidate):
        def verify_candidate(self):
            model.require(fault != 'image','CANDIDATE_IMAGE_ABSENT')
            super().verify_candidate()
    with pytest.raises(model.DeliveryRefused):
        cli.prepare(operation_dir=folder,build_record=path,build_sha256=expected,
            operation_id='refused',host_type=MissingImage)
    assert len(builds) == 1 and not (folder/'request.json').exists()


def test_fresh_backed_predecessor_check_is_not_reused_from_old_build(inputs,monkeypatch):
    _,builds,_ = run_build(inputs,monkeypatch)
    calls = []
    def current(path):
        calls.append(path)
        return dict(builder.baseline(path),commit='f'*40)
    with pytest.raises(model.DeliveryRefused,match='BUILD_FOUNDATION_CHANGED'):
        prepare(inputs,inputs.folder.parent/'wrong-predecessor',baseline_reader=current)
    assert calls == [str(inputs.previous)] and len(builds) == 1


@pytest.mark.parametrize('fault',['digest','request','ambiguous','symlink','self'])
def test_operation_consumers_cannot_bypass_reference_binding(inputs,monkeypatch,fault):
    run_build(inputs,monkeypatch)
    folder = inputs.folder.parent/'referenced'
    prepare(inputs,folder)
    path = folder/'build-reference.json'
    ref = model.read_json(path)
    if fault == 'digest':ref['sha256'] = 'f'*64
    elif fault == 'request':ref['request_sha256'] = 'f'*64
    elif fault == 'ambiguous':model.write_new(folder/'build.json',{})
    elif fault == 'self':ref['path'] = str(folder/'build.json')
    else:
        original=Path(ref['path']);other=original.with_name('other.json')
        original.rename(other);original.symlink_to(other)
    path.write_bytes(model.canonical(ref))
    with pytest.raises(model.DeliveryRefused):builder.operation_build(folder)


@pytest.mark.parametrize('guard,fault',[
    ('BUILD_RECORD_CHANGED','digest'),('BUILD_ARTIFACT_REQUEST_CHANGED','request'),
    ('BUILD_ARTIFACT_REFERENCE_AMBIGUOUS','ambiguous')])
def test_reference_guards_have_executed_removed_guard_falsifiers(inputs,monkeypatch,guard,fault):
    original=builder.require
    monkeypatch.setattr(builder,'require',lambda ok,reason:
        None if reason == guard else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_operation_consumers_cannot_bypass_reference_binding(inputs,monkeypatch,fault)


def test_interrupted_prepare_never_overwrites_its_retained_reference(inputs,monkeypatch):
    _,builds,_=run_build(inputs,monkeypatch)
    folder=inputs.folder.parent/'interrupted'
    class Unready(Candidate):
        def verify_candidate(self):raise model.DeliveryRefused('UNREADY')
    with pytest.raises(model.DeliveryRefused,match='UNREADY'):
        cli.prepare(operation_dir=folder,build_record=inputs.folder/'build.json',
            build_sha256=qualification.sha256_file(inputs.folder/'build.json'),
            operation_id='interrupted',host_type=Unready)
    retained=(folder/'build-reference.json').read_bytes()
    with pytest.raises(model.DeliveryRefused,match='ALREADY_REFERENCED'):prepare(inputs,folder)
    assert (folder/'build-reference.json').read_bytes() == retained and len(builds) == 1
    assert prepare(inputs,folder.with_name('replacement')).read()['stage'] == 'NEW'


def test_build_command_refuses_a_directory_already_referencing_an_artifact(inputs,monkeypatch):
    run_build(inputs,monkeypatch)
    folder=inputs.folder.parent/'referenced'
    prepare(inputs,folder)
    inputs.folder=folder
    with pytest.raises(model.DeliveryRefused,match='ALREADY_REFERENCED'):
        run_build(inputs,monkeypatch)


@pytest.mark.parametrize('fault',['ancestor','record','context'])
def test_external_artifact_symlinks_refuse(inputs,monkeypatch,fault):
    built,_,_=run_build(inputs,monkeypatch)
    path=inputs.folder/'build.json';expected=qualification.sha256_file(path)
    if fault=='record':
        other=path.with_name('original.json');path.rename(other);path.symlink_to(other)
    elif fault=='context':
        context=Path(built['context']);other=context.with_name('original-context')
        context.rename(other);context.symlink_to(other,target_is_directory=True)
    else:
        actual=inputs.folder.with_name('original-artifact')
        inputs.folder.rename(actual);inputs.folder.symlink_to(actual,target_is_directory=True)
    with pytest.raises(model.DeliveryRefused):
        cli.prepare(operation_dir=inputs.folder.parent/'refused',build_record=path,
            build_sha256=expected,operation_id='refused',host_type=Candidate)


def test_backed_environment_install_consumes_the_original_artifact(tmp_path,monkeypatch):
    from tests.scripts.test_sentinel_backed_environment_install import host_fixture
    from tests.scripts.test_sentinel_backed_local_patch import patch
    host,old,new,_=host_fixture(tmp_path,monkeypatch)
    artifact=tmp_path/'artifact';artifact.mkdir()
    path=artifact/'build.json';(host.operation_dir/'build.json').rename(path)
    model.write_new(host.operation_dir/'build-reference.json',dict(
        schema=builder.BUILD_REFERENCE_SCHEMA,path=str(path),sha256=qualification.sha256_file(path),
        request_sha256=model.digest(host.request)))
    with host.owned():host.install_values(old,new)
    assert host.load_values() == new
    assert patch.builder.operation_build(host.operation_dir)['image'] == new['SENTINEL_RUNTIME_IMAGE_DIGEST']


def test_backed_cli_validates_digest_before_constructing_a_host(tmp_path,monkeypatch):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    path=tmp_path/'build.json';path.write_text('{}')
    monkeypatch.setattr(patch,'BackedHost',lambda *a,**kw:pytest.fail('unadmitted host'))
    assert patch.main(['prepare','--operation-dir',str(tmp_path/'new'),
        '--build-record',str(path),'--build-sha256','f'*64,'--operation-id','new']) == 2


def reference_original(folder):
    artifact=folder.parent/'original-build';artifact.mkdir()
    path=artifact/'build.json';(folder/'build.json').rename(path)
    request_sha=(model.digest(model.read_json(folder/'request.json'))
        if (folder/'request.json').exists() else 'a'*64)
    model.write_new(folder/'build-reference.json',dict(schema=builder.BUILD_REFERENCE_SCHEMA,
        path=str(path),sha256=qualification.sha256_file(path),request_sha256=request_sha))
    return path


@pytest.mark.parametrize('changed',[False,True])
def test_completed_referenced_operation_remains_a_checked_predecessor(chain,changed):
    from tests.scripts.test_sentinel_backed_predecessor import complete,patch,NEW,NEW_IMAGE
    receipt=complete(chain)
    path=reference_original(chain['operation'])
    if changed:
        path.write_text('{}')
        with pytest.raises(patch.DeliveryRefused,match='BUILD_RECORD_CHANGED'):
            patch.predecessor_witness(receipt)
    else:
        witness=patch.predecessor_witness(receipt)
        assert (witness['git_commit'],witness['runtime_image']) == (NEW,NEW_IMAGE)


@pytest.mark.parametrize('changed',[False,True])
def test_access_path_bootstrap_reads_the_same_pinned_artifact(make_host,changed):
    from tests.scripts.test_sentinel_access_path_bootstrap import bootstrap,model as access_model
    host=make_host()
    path=reference_original(host.operation_dir)
    if changed:
        path.write_text('{}')
        with pytest.raises(access_model.DeliveryRefused,match='BUILD_RECORD_CHANGED'):
            bootstrap.preflight(host,host.state,host.proof)
    else:
        contract=bootstrap.preflight(host,host.state,host.proof)
        assert contract['authority_effect'] == 'NONE'
        assert contract['candidate'] == host.request['candidate']
