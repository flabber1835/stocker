"""One owner discovers unchanged graph arguments once; changed context re-resolves."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
compose = importlib.import_module('sentinel_compose_context')


def test_same_owner_reuses_discovery_but_never_returned_mutable_list(tmp_path):
    context = compose.ComposeContext()
    calls = []
    def invoke(argv):
        calls.append(argv)
        return SimpleNamespace(returncode=0,stdout='--project-name sentinel -f canonical.yml')
    for _ in range(20):
        result = context.resolve(root=tmp_path,env={},invoke=invoke)
        result.append('foreign modification')
    assert len(calls) == 1
    assert 'foreign modification' not in context.resolve(root=tmp_path,env={},invoke=invoke)
    compose.ComposeContext().resolve(root=tmp_path,env={},invoke=invoke)
    assert len(calls) == 2


@pytest.mark.parametrize('changed', ['source','dotenv','environment','pointer'])
def test_changed_source_environment_or_runtime_pointer_requires_fresh_discovery(tmp_path,changed):
    context = compose.ComposeContext()
    calls = []
    env = {}
    def invoke(argv):
        calls.append(argv)
        return SimpleNamespace(returncode=0,stdout='-f canonical.yml')
    context.resolve(root=tmp_path,env=env,invoke=invoke)
    if changed == 'environment':env['SENTINEL_FORCE_NO_CPU_LIMITS']='1'
    else:
        name = {'source':'scripts/sentinel-compose.sh','dotenv':'.env',
            'pointer':'artifacts/sentinel/deployment/validated-runtime.env'}[changed]
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('changed')
    context.resolve(root=tmp_path,env=env,invoke=invoke)
    assert len(calls) == 2


def test_failed_discovery_is_never_cached(tmp_path):
    context=compose.ComposeContext();calls=[]
    def invoke(argv):calls.append(argv);return SimpleNamespace(returncode=2,stdout='')
    for _ in range(2):
        with pytest.raises(ValueError,match='refused'):context.resolve(root=tmp_path,env={},invoke=invoke)
    assert len(calls)==2


def test_foreign_pid_cannot_reuse_owner_context(tmp_path,monkeypatch):
    context=compose.ComposeContext();calls=[]
    def invoke(argv):calls.append(argv);return SimpleNamespace(returncode=0,stdout='-f canonical.yml')
    context.resolve(root=tmp_path,env={},invoke=invoke)
    monkeypatch.setattr(compose.os,'getpid',lambda:123456789)
    context.resolve(root=tmp_path,env={},invoke=invoke)
    assert len(calls)==2


def test_mounted_helper_content_drift_requires_fresh_discovery(tmp_path):
    helper = tmp_path/'retained'/'sentinel-archive-wal.sh'
    helper.parent.mkdir();helper.write_text('original')
    override = tmp_path/'artifacts/compose/docker-compose.sentinel.postgres-helpers.yml'
    override.parent.mkdir(parents=True)
    override.write_text(json.dumps({'services':{'sentinel-postgres':{'volumes':[
        {'target':'/usr/local/libexec','source':str(helper.parent)}]}}}))
    context = compose.ComposeContext();calls=[]
    def invoke(argv):calls.append(argv);return SimpleNamespace(returncode=0,stdout='-f canonical.yml')
    context.resolve(root=tmp_path,env={},invoke=invoke)
    helper.write_text('changed')
    context.resolve(root=tmp_path,env={},invoke=invoke)
    assert len(calls) == 2


def test_removed_source_context_is_detected(tmp_path,monkeypatch):
    monkeypatch.setattr(compose,'FILES',tuple(name for name in compose.FILES
                                            if name != 'scripts/sentinel-compose.sh'))
    with pytest.raises(AssertionError):
        test_changed_source_environment_or_runtime_pointer_requires_fresh_discovery(tmp_path,'source')
