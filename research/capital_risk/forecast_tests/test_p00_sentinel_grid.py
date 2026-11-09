"""Source-only grid qualification and inert DTO falsifiers."""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import inspect
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
from types import SimpleNamespace

import pytest

import p00_sentinel_grid_policy as policy
import p00_sentinel_grid_review as review
import p00_sentinel_grid_job as job

HERE=Path(__file__).resolve().parents[1]
# Inert AST syntax: not compiled or executed.
DTO="""
class Native:
    _schema = 'ramp-free-native/1'
    _caps = CAPS_PLACEHOLDER
    def syntax(self):
        if self.fast_h >= 3:
            first = self.fast_age + 1 >= 10
        if self.slow_h >= 6:
            second = self.slow_age + 1 >= 20
        self.fast_h = min(self.fast_h, 3)
        self.slow_h = min(self.slow_h, 6)
class CandidateA:
    _schema = 'ramp-free-ex3-rebound-false/1'
    def syntax(self):
        if self.full_streak >= LDRC_REC or concordant:
            desired = 1.0
        if self.latched:
            desired = min(desired, .55)
""".replace('CAPS_PLACEHOLDER',repr(policy.NATIVE_CAPS))


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_vacancy','research.pooled_input')):
            raise AssertionError('LOCAL_CANONICAL_IMPORT_FORBIDDEN:'+fullname)


def test_complete_factorial_and_both_existing_controls():
    values=policy.profiles()
    assert len(values)==len({v['id'] for v in values})==144
    assert [v['id'] for v in values[:2]]==[policy.BASELINE,policy.NO_EXTRA]
    assert values[0]['parent']==values[1]['parent'] and values[0]['owned']==values[1]['owned']
    assert values[0]['recovery']==dict(extra_hold=True,fast_healthy=3,slow_healthy=6)
    assert values[1]['recovery']==dict(extra_hold=False,fast_healthy=3,slow_healthy=6)
    for key,expected in [('fast_healthy',{2,3}),('slow_healthy',{3,6}),('extra_hold',{True,False})]:
        assert {v['recovery'][key] for v in values}==expected
    assert {v['owned']['active_ceiling'] for v in values}=={'0.25','0.55','0.75'}


@pytest.mark.parametrize('index',range(8))
def test_every_parameter_and_snapshot_site_has_a_missing_site_falsifier(index):
    changes=policy.source_changes(policy.profiles()[0]);before,_=changes[index]
    changed=DTO.replace(before,'False',1);assert changed!=DTO
    with pytest.raises(ValueError,match='EXACT_SINGLE_AST_SITE'):
        policy.transform(changed,changes)


def test_duplicate_counter_site_refuses():
    with pytest.raises(ValueError,match='EXACT_SINGLE_AST_SITE'):
        policy.transform(DTO+'\nx = min(self.fast_h, 3)\n',policy.source_changes(policy.profiles()[0]))


def test_wrong_source_hash_refuses():
    with pytest.raises(ValueError,match='FROZEN_PARENT_BYTES'):
        policy.source(DTO.encode(),policy.profiles()[0])


@pytest.mark.parametrize('hold',(False,True))
@pytest.mark.parametrize('fast',(2,3))
@pytest.mark.parametrize('slow',(3,6))
def test_real_frozen_ast_gates_caps_saturation_and_minimum_ages(hold,fast,slow):
    profile=next(v for v in policy.profiles() if v['recovery']==dict(extra_hold=hold,fast_healthy=fast,slow_healthy=slow))
    raw=(HERE.parent.parent/'sentinel/controller/champion_frozen.py').read_bytes()
    text=policy.source(raw,profile);tree=ast.parse(text)
    native=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Native')
    caps=next(n.value for n in native.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_caps' for t in n.targets))
    actual=ast.literal_eval(caps)
    assert actual=={**policy.NATIVE_CAPS,'fast_h':fast,'slow_h':slow}
    assert f'self.fast_h >= {fast}' in text and f'min(self.fast_h, {fast})' in text
    assert f'self.slow_h >= {slow}' in text and f'min(self.slow_h, {slow})' in text
    assert 'self.fast_age + 1 >= 10' in text and 'self.slow_age + 1 >= 20' in text
    assert "desired = min(desired, LDRC_CEIL)" in text
    assert 'research-p00-sentinel-grid-native/'+profile['id'] in text
    assert 'research-p00-sentinel-grid-candidate/'+profile['id'] in text


@pytest.mark.parametrize('index',range(5))
def test_each_independent_vector_site_has_a_missing_site_falsifier(index):
    raw=ast.unparse(ast.parse((HERE/'full_system_controller_vector.py').read_bytes()))
    before,_=policy.VECTOR_CHANGES[index];node=ast.unparse(ast.parse(before,mode='eval').body)
    assert raw.count(node)==1
    with pytest.raises(ValueError,match='EXACT_SINGLE_AST_SITE'):
        policy.transform(raw.replace(node,'False',1),policy.VECTOR_CHANGES)


def test_vector_preserves_native_minimum_ages_and_other_entry_predicates():
    text=policy.transform((HERE/'full_system_controller_vector.py').read_bytes(),policy.VECTOR_CHANGES)
    assert 'age + 1 >= 10' in text and 'sa + 1 >= 20' in text
    assert "fh >= p('recovery.fast_healthy')" in text and "sh >= p('recovery.slow_healthy')" in text
    assert "np.minimum(fh, p('recovery.fast_healthy'))" in text
    assert "np.minimum(sh, p('recovery.slow_healthy'))" in text
    assert "p('recovery.extra_hold') == 0" in text


def test_hosted_canonical_compiler_closed_even_with_spoofed_flag(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED','1')
    with pytest.raises(ValueError,match='HOSTED_ONLY'):
        policy.parent_module(DTO.encode(),policy.profiles()[0],policy.PARENT_SHA)


def records():
    result=[]
    for p in policy.profiles():
        result.append(dict(id=p['id'],core_id='inert-core-identity',group=p['id'],turnover='10',
            metrics=dict(anchor='2018-01-02',start='2018-01-03',end='2022-12-30',closes=10,
                         multiple='19/10',maximum_drawdown_magnitude='31/100')))
    cases=[('2','3/10','10'),('21/10','29/100','10'),('43/20','18/100','12'),
           ('12/5','27/100','11'),('3/2','1/100','0'),('3','2/5','11')]
    for r,(wealth,dd,turn) in zip(result,cases):
        r['metrics'].update(multiple=wealth,maximum_drawdown_magnitude=dd);r['turnover']=turn
    return result


def test_both_objectives_respect_both_controls_and_independent_implementation():
    rows=records();a=policy.select(rows,policy.BASELINE);b=review.lock(rows,policy.BASELINE)
    assert a==b
    assert a['protection_candidate']==rows[2]['id']
    assert a['growth_candidate']==rows[3]['id']
    assert a['protection_candidate']!=rows[4]['id'] # low drawdown loses too much growth
    assert a['growth_candidate']!=rows[5]['id'] # high growth violates the risk ceiling
    assert a['evaluation_used'] is False


def test_unattainable_drawdown_budget_is_explicit():
    rows=records();rows[4]['metrics']['maximum_drawdown_magnitude']='1/4'
    assert policy.select(rows,policy.BASELINE)['budget_choices'][0]['id'] is None
    assert review.lock(rows,policy.BASELINE)==policy.select(rows,policy.BASELINE)


@pytest.mark.parametrize('selector',(policy.select,review.lock))
def test_later_period_record_shape_refuses(selector):
    rows=records();rows[0]['validation_metrics']={'inert':'not allowed'}
    with pytest.raises(ValueError,match='TRAINING_(ONLY_RECORD_SHAPE|INTERFACE)'):
        selector(rows,policy.BASELINE)


def test_later_period_dates_refuse():
    rows=records()
    for row in rows:row['metrics']['end']='2024-12-31'
    with pytest.raises(ValueError,match='COMMON_TRAINING_WINDOW'):
        policy.select(rows,policy.BASELINE)


def test_training_date_falsifier_fails_if_guard_is_removed(monkeypatch):
    original=policy.need
    monkeypatch.setattr(policy,'need',lambda value,code:original(True if code=='COMMON_TRAINING_WINDOW' else value,code))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_later_period_dates_refuse()


def test_default_engine_review_predicate_and_new_optional_arguments():
    tree=ast.parse((HERE/'full_system_controller_worker.py').read_bytes())
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    assert [a.arg for a in run.args.kwonlyargs]==['reference','source_review_path','core_identity']
    gate=next(n for n in ast.walk(run) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
              and n.func.id=='need' and any(isinstance(x,ast.Constant) and x.value=='ACTUAL_CORE_REVIEW' for x in n.args))
    assert ast.unparse(gate.args[0])=="source_review['complete'] and source_review['all_daily_factors_and_chains_verified']"
    assert 'registered_count = len(registered)' in ast.unparse(run)


@pytest.mark.parametrize('reviewer',(False,True))
def test_actual_container_constructor_with_inert_linux_identity(reviewer,monkeypatch):
    import full_system_trials_job
    monkeypatch.setattr(full_system_trials_job,'os',SimpleNamespace(getuid=lambda:1001,getgid=lambda:1001))
    argv=job.command('capital-full-core-b-'+('review' if reviewer else 'worker')+'-123-1',
        Path('/source'),Path('/frozen'),Path('/out'),Path('/core'),Path('/evidence') if reviewer else None)
    assert argv[argv.index('--network')+1]=='none' and '/driver/p00_sentinel_grid_worker.py' in argv
    assert argv[-2:]==['--mode','review' if reviewer else 'worker']
    inspect.signature(job.old_inspector()).bind('inert','id',value=object(),run_id='123',user='1001:1001',correlation_prefix=False)


class LinuxPathDTO(PurePosixPath):
    def resolve(self):return self
    def is_symlink(self):return False
    def exists(self):return False


@pytest.mark.parametrize('bad',(False,True))
def test_workflow_capacity_argument_against_existing_guard(bad,monkeypatch):
    import ephemeral_runner_capacity as capacity
    monkeypatch.setattr(capacity,'Path',LinuxPathDTO)
    line,=[s.strip()[6:].strip("'") for s in (HERE.parent.parent/job.WORKFLOW).read_text().splitlines()
           if s.strip().startswith('run:') and 'ephemeral_runner_capacity.py' in s]
    argv=shlex.split(line);chosen=argv[argv.index('--output')+1]
    if bad:chosen='artifacts/capital-risk/grid-capacity.json'
    path=LinuxPathDTO(chosen.replace('$GITHUB_WORKSPACE',capacity.WORKSPACE))
    if bad:
        with pytest.raises(capacity.Refusal,match='REFUSED_CAPACITY_OUTPUT'):capacity.admitted_output(path)
    else:assert capacity.admitted_output(path)==LinuxPathDTO(capacity.WORKSPACE)/capacity.OUTPUT


@pytest.mark.parametrize('bad',(False,True))
def test_transport_root_against_existing_guard(bad,monkeypatch):
    import system_campaign_factual_admit as transport
    env=dict(RUNNER_TEMP='/home/runner/work/_temp',GITHUB_ACTIONS='true',GITHUB_REPOSITORY='flabber1835/stocker',
             GITHUB_REF='refs/heads/codex/capital-risk-research',GITHUB_ACTOR='flabber1835',RUNNER_ENVIRONMENT='github-hosted',
             RUNNER_OS='Linux',GITHUB_EVENT_NAME='push',GITHUB_SHA='a'*40)
    monkeypatch.setattr(job,'Path',LinuxPathDTO);monkeypatch.setattr(transport,'Path',LinuxPathDTO)
    monkeypatch.setattr(transport,'os',SimpleNamespace(name='posix',environ=env))
    monkeypatch.setattr(transport,'shutil',SimpleNamespace(disk_usage=lambda _:SimpleNamespace(free=12*1024**3)))
    root=job.baseline_transfer_root(env['RUNNER_TEMP'],1)
    if bad:root=LinuxPathDTO(env['RUNNER_TEMP'])/'p00-sentinel-grid-1/original'
    if bad:
        with pytest.raises(ValueError,match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):transport.hosted_destination(root)
    else:assert transport.hosted_destination(root)==root


def test_source_bound_import_probe_under_canonical_import_fence():
    fence=NoCanonical();sys.meta_path.insert(0,fence)
    try:
        assert job.probe(HERE/job.REQUEST)['canonical_runtime_executed'] is False
        request=json.loads((HERE/job.REQUEST).read_bytes())
        assert request['profiles']==144 and request['original_core_backtests_resumed'] is False
        assert request['registry_sha256']==policy.digest(policy.profiles())
    finally:sys.meta_path.remove(fence)
