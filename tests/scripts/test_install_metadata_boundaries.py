"""Immutable image facts are shared; source and presence boundaries are fresh."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_cli import inputs,request,NEW_IMAGE,NEW,cli,model,builder


def metadata_host():
    host=object.__new__(cli.Host);host.calls=[]
    host.metadata=dict(Id=NEW_IMAGE,Config={'Labels':{'org.opencontainers.image.revision':NEW}},
        RepoDigests=['registry.invalid/runtime@sha256:'+'e'*64])
    def run(argv,**kwargs):
        host.calls.append(argv)
        return SimpleNamespace(stdout=json.dumps([host.metadata]).encode())
    host.run=run
    return host


def test_immutable_metadata_reuses_facts_and_returns_independent_copies():
    host=metadata_host();reference=host.metadata['RepoDigests'][0]
    first=host.image_metadata(reference);first['Config'].clear()
    assert host.image_metadata(reference)==host.metadata
    assert host.image_metadata(NEW_IMAGE)==host.metadata
    assert len(host.calls)==1
    assert metadata_host().image_metadata(NEW_IMAGE)==host.metadata


def test_fresh_boundary_reinspects_even_a_cached_exact_digest():
    host=metadata_host();host.image_metadata(NEW_IMAGE)
    host.metadata['Config']['Labels']['org.opencontainers.image.revision']='changed'
    assert host.image_metadata(NEW_IMAGE,fresh=True)==host.metadata
    assert len(host.calls)==2


def test_mutable_tag_is_never_cached_and_a_moved_tag_is_visible():
    host=metadata_host();first=host.image_metadata('mutable:tag')
    host.metadata['Id']='sha256:'+'f'*64
    assert host.image_metadata('mutable:tag')['Id']!=first['Id']
    assert len(host.calls)==2


@pytest.mark.parametrize('fault',['missing','shape','foreign_digest','foreign_repo'])
def test_failed_or_malformed_inspection_never_admits_a_fact(fault):
    host=metadata_host();reference=NEW_IMAGE
    if fault=='missing':
        host.run=lambda *a,**kw:(_ for _ in ()).throw(model.DeliveryRefused('IMAGE_ABSENT'))
    elif fault=='shape':host.metadata={}
    elif fault=='foreign_digest':host.metadata['Id']='sha256:'+'f'*64
    else:reference='registry.invalid/foreign@sha256:'+'e'*64
    with pytest.raises(model.DeliveryRefused):host.image_metadata(reference)
    assert getattr(host,'_image_metadata_facts',{})=={}


def test_candidate_uses_one_clean_check_per_boundary_with_fresh_bytes_and_image_presence(inputs):
    host=metadata_host();host.source=host.deployment=inputs.source
    host.request=model.validate_request(request(inputs,inputs.approved))
    host.git_calls=[]
    def git(*args):host.git_calls.append(args);return inputs.git(inputs.source,*args)
    host.git=git
    host.git_bytes=lambda _show,name:(inputs.source/name.split(':',1)[1]).read_bytes()
    host.probe=lambda *a:host.request['candidate']['source_identity']
    host.verify_candidate()
    assert host.git_calls.count(('rev-parse','HEAD'))==1
    assert host.git_calls.count(('status','--porcelain'))==1
    assert host.git_calls.count(('merge-base',host.request['predecessor']['commit'],NEW))==1
    host.verify_candidate()
    assert len(host.calls)==2 and host.git_calls.count(('status','--porcelain'))==2
    (inputs.source/'sentinel/module.py').write_text('changed=1\n')
    with pytest.raises(model.DeliveryRefused,match='QUALIFIED_SOURCE_BYTES_CHANGED'):
        host.verify_candidate()
    assert len(host.calls)==2


def test_shared_builder_inspection_uses_the_same_immutable_memo():
    host=metadata_host()
    assert builder._inspect(host,NEW_IMAGE)==builder._inspect(host,NEW_IMAGE)
    assert len(host.calls)==1


def test_fresh_presence_guard_has_an_executed_falsifier(inputs,monkeypatch):
    original=cli.Host.image_metadata
    monkeypatch.setattr(cli.Host,'image_metadata',lambda self,ref,**kw:original(self,ref))
    with pytest.raises(AssertionError):
        test_candidate_uses_one_clean_check_per_boundary_with_fresh_bytes_and_image_presence(inputs)
