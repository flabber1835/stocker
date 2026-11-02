"""Inert codec lifecycle tests; no canonical parsing or financial execution."""
import json
from types import SimpleNamespace

import pytest
import system_campaign_pxd_materialize as subject


class Codec:
    def __init__(self,*,fail=False,load_object=True):
        self.fail=fail;self.load_object=load_object;self.objects=[];self.entered=0;self.exited=0
    def __enter__(self):self.entered+=1;return self
    def __exit__(self,*args):self.exited+=1
    def load(self,path,**bindings):
        if self.fail:raise ValueError('inert load refusal')
        self.bindings=bindings;obj=SimpleNamespace(sha256=subject.sha(path.read_bytes()))
        if self.load_object:self.objects=[obj]
        return obj


def fixture(tmp_path,schema=subject.CLOSE):
    raw=json.dumps(dict(schema=schema)).encode();h=subject.sha(raw)
    folder=tmp_path/'book/repairs';folder.mkdir(parents=True)
    (folder/(h+'.json')).write_bytes(raw)
    return dict(filename=h+'.json',sha256=h,resume_session='2023-10-31',
        predecessor_checkpoint_sha256='a'*64)


def test_old_scope_materializes_its_actual_descriptor_not_last_input(tmp_path):
    d=fixture(tmp_path);codec=Codec()
    with subject.materialized(codec,tmp_path,d,schema=subject.CLOSE):
        assert codec.objects[0].sha256==d['sha256']
        assert codec.bindings==dict(resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
    assert codec.entered==codec.exited==1


@pytest.mark.parametrize('kind',['load','empty','body'])
def test_failed_load_or_body_always_restores_hooks(tmp_path,kind):
    d=fixture(tmp_path);codec=Codec(fail=kind=='load',load_object=kind!='empty')
    with pytest.raises(ValueError):
        with subject.materialized(codec,tmp_path,d,schema=subject.CLOSE):
            if kind=='body':raise ValueError('inert caller refusal')
    assert codec.entered==codec.exited==1


@pytest.mark.parametrize('change',['schema','filename','body'])
def test_foreign_or_changed_descriptor_refuses_before_context(tmp_path,change):
    d=fixture(tmp_path);codec=Codec();schema=subject.CLOSE
    if change=='schema':schema=subject.PXD
    elif change=='filename':d['filename']='other.json'
    else:(tmp_path/'book/repairs'/d['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError):
        with subject.materialized(codec,tmp_path,d,schema=schema):pass
    assert codec.entered==codec.exited==0
