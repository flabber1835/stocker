"""DATA/AST falsifiers. No financial module imports or local transitions."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import core_volatility_source as compiler
import core_volatility_job as job

ROOT = Path(__file__).resolve().parents[3]


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_vacancy', 'research.pooled_input')):
            raise AssertionError('LOCAL_CANONICAL_IMPORT_FORBIDDEN:' + fullname)


@pytest.mark.parametrize('name', compiler.SITES)
def test_real_pinned_source_forward_and_exact_inverse(name):
    raw = (ROOT/name).read_bytes()
    assert compiler.sha(raw) == compiler.PINS[name]
    before, after = compiler.SITES[name]
    changed = compiler.transform(raw, before, after)
    assert compiler.transform(changed, after, before) == raw


@pytest.mark.parametrize('name', compiler.SITES)
@pytest.mark.parametrize('mutation', ('missing', 'duplicate', 'comment_only'))
def test_score_site_falsifiers(name, mutation):
    before, after = compiler.SITES[name]
    raw = ('value = '+before+'\n').encode()
    if mutation == 'missing':
        raw = raw.replace(before.encode(), b'0.')
    elif mutation == 'duplicate':
        raw += raw
    else:
        raw = ('# '+before+'\nvalue = 0.\n').encode()
    with pytest.raises(ValueError, match='SINGLE_AST_SITE'):
        compiler.transform(raw, before, after)


def fixture(monkeypatch):
    sources = {name: ('value = '+site[0]+'\n').encode() for name, site in compiler.SITES.items()}
    sources[compiler.RUNTIME] = b'identity = {**identity, "other": 1}\n'
    sources['unchanged/controller.py'] = b'EXPOSURE = 0.55\n'
    monkeypatch.setattr(compiler, 'PINS', {n: compiler.sha(sources[n]) for n in compiler.PINS})
    monkeypatch.setattr(compiler, 'bind_manifest', lambda v: v)
    return sources


def test_control_byte_identity_and_no_unrelated_change(monkeypatch):
    sources = fixture(monkeypatch)
    assert compiler.apply(sources, 'CONTROL') == sources
    alternative = compiler.apply(sources, 'VOL075')
    assert alternative['unchanged/controller.py'] == sources['unchanged/controller.py']
    assert set(n for n in sources if sources[n] != alternative[n]) == set(compiler.SITES) | {compiler.RUNTIME}
    assert 'research_core_volatility_sha256' in alternative[compiler.RUNTIME].decode()
    assert json.loads(json.dumps(compiler.identity('VOL075'))) == compiler.identity('VOL075')


@pytest.mark.parametrize('arm', compiler.ARMS)
def test_parent_parameter_identity_refusal(monkeypatch, arm):
    sources = fixture(monkeypatch)
    sources[next(iter(compiler.SITES))] += b'# wrong source\n'
    with pytest.raises(ValueError, match='EXACT_PARENT'):
        compiler.apply(sources, arm)
    with pytest.raises(ValueError, match='REGISTERED_ARM'):
        compiler.identity('VOL050')


def test_accidental_unrelated_source_edit_refuses(monkeypatch):
    sources = fixture(monkeypatch)
    def bad(v):
        v['unchanged/controller.py'] = b'EXPOSURE = 1.0\n'
        return v
    monkeypatch.setattr(compiler, 'bind_manifest', bad)
    with pytest.raises(ValueError, match='NO_UNRELATED_SOURCE_CHANGE'):
        compiler.apply(sources, 'VOL075')


def test_qualification_changes_only_its_declared_formula():
    raw = (job.HERE/'system_campaign_qualify.py').read_bytes()
    changed = compiler.transform(raw, 'math.log1p(momentum)/vol', 'math.log1p(momentum)/vol**0.75')
    assert compiler.transform(changed, 'math.log1p(momentum)/vol**0.75', 'math.log1p(momentum)/vol') == raw


def test_hosted_canary_closed_before_canonical_import(monkeypatch):
    from core_volatility_worker import qualify
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    fence = NoCanonical()
    sys.meta_path.insert(0, fence)
    try:
        with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
            qualify('VOL075')
    finally:
        sys.meta_path.remove(fence)


@pytest.mark.parametrize('arm', compiler.ARMS)
@pytest.mark.parametrize('review', (False, True))
def test_constructor_and_actual_inspector_on_inert_docker_dto(monkeypatch, arm, review):
    import full_system_trials_job as base
    uid = SimpleNamespace(getuid=lambda: 1001, getgid=lambda: 1001)
    monkeypatch.setattr(base, 'os', uid)
    monkeypatch.setattr(job.os, 'getuid', lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, 'getgid', lambda: 1001, raising=False)
    name = 'core-volatility-'+arm.lower()+'-'+('review' if review else 'worker')+'-123-1'
    values = job.command(name, Path('/source'), Path('/frozen'), Path('/output'), arm,
                         Path('/evidence') if review else None)
    assert values[values.index('--network')+1] == 'none'
    assert values[values.index('--entrypoint')+1] == 'python'
    mounts = ['/variant', '/frozen', '/driver', '/out'] + (['/evidence'] if review else [])
    dto = {'Name': '/'+name, 'Image': job.EXECUTION_IMAGE, 'Id': 'a'*64,
           'HostConfig': {'NetworkMode': 'none', 'Memory': 8*1024**3, 'MemorySwap': 8*1024**3,
                          'NanoCpus': 2000000000, 'PidsLimit': 64, 'ReadonlyRootfs': True,
                          'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges']},
           'Config': {'WorkingDir': '/variant', 'User': '1001:1001', 'Env': ['FULL_SYSTEM_HOSTED=1'],
                      'Labels': {'research.study': 'core-volatility-20261108', 'research.role': 'review' if review else 'worker'},
                      'Entrypoint': ['python'], 'Cmd': values[values.index(job.EXECUTION_IMAGE)+1:]},
           'Mounts': [{'Destination': n, 'Type': 'bind', 'RW': n == '/out'} for n in mounts]}
    def response(v):
        monkeypatch.setattr(job.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps([v]).encode()))
    response(dto)
    assert job.inspect(name, 'a'*64) == dto
    for section, key, bad in (('HostConfig', 'NetworkMode', 'bridge'), ('Config', 'Cmd', ['wrong']),
                              ('Config', 'Env', ['GH_TOKEN=secret']), ('HostConfig', 'MemorySwap', 0)):
        changed = deepcopy(dto)
        changed[section][key] = bad
        response(changed)
        with pytest.raises(ValueError):
            job.inspect(name, 'a'*64)


def test_exact_request_probe_has_no_canonical_imports():
    fence = NoCanonical()
    sys.meta_path.insert(0, fence)
    try:
        assert job.probe(job.HERE/job.REQUEST)['canonical_runtime_executed'] is False
    finally:
        sys.meta_path.remove(fence)
