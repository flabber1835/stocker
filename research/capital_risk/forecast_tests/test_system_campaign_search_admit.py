"""Invented stopped-inspection objects; no real financial histories or replay."""
import ast,copy
from pathlib import Path
import pytest
from system_campaign_search_admit import actual_stop,admit
from system_campaign_select import select


def inspection():
    return {'Name':'/capital-system-joint-p00-worker-42-1','Id':'a'*64,
        'Image':'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        'State':{'Running':False,'OOMKilled':False,'ExitCode':0},
        'HostConfig':{'NetworkMode':'none','Memory':8*1024**3,'MemorySwap':8*1024**3,'NanoCpus':2000000000,
            'PidsLimit':64,'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges']},
        'Config':{'Cmd':['-B','/driver/system_campaign_numeric.py'],'WorkingDir':'/variant','User':'1001:1001',
            'Labels':{'research.study':'full-system-search-20261029','research.role':'worker'},'Env':['SAFE=1']},
        'Mounts':[{'Destination':n,'Type':'bind','RW':n=='/out'} for n in ('/variant','/frozen','/driver','/out','/core')]}


def test_actual_stop_and_fence_mutations():
    v=inspection();actual_stop(v,'P00',42,'worker')
    for field,bad in [('Running',True),('OOMKilled',True),('ExitCode',1)]:
        wrong=copy.deepcopy(v);wrong['State'][field]=bad
        with pytest.raises(ValueError,match='ACTUAL_STOP'):actual_stop(wrong,'P00',42,'worker')
    wrong=copy.deepcopy(v);wrong['Config']['Env']=['GH_TOKEN=fictional']
    with pytest.raises(ValueError,match='NO_CREDENTIALS'):actual_stop(wrong,'P00',42,'worker')
    wrong=copy.deepcopy(v);wrong['Mounts'][0]['RW']=True
    with pytest.raises(ValueError,match='ACTUAL_MOUNTS'):actual_stop(wrong,'P00',42,'worker')


def test_actual_network_guard_removal_falsifier():
    wrong=inspection();wrong['HostConfig']['NetworkMode']='bridge'
    with pytest.raises(ValueError,match='ACTUAL_FENCES'):actual_stop(wrong,'P00',42,'worker')
    node=next(n for n in ast.parse(Path(actual_stop.__code__.co_filename).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='actual_stop')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='SEARCH_ADMIT_ACTUAL_FENCES' for x in ast.walk(n))]
    scope=dict(actual_stop.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-search-fence>','exec'),scope)
    assert scope['actual_stop'](wrong,'P00',42,'worker') is None


def test_local_training_and_download_refuse_before_outputs(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    target=tmp_path/'absent'
    with pytest.raises(ValueError,match='HOSTED_JOINT_NUMERICAL_ONLY'):select({},target)
    with pytest.raises((ValueError,RuntimeError,KeyError)):admit({},target,b'fake')
    assert not target.exists()


def test_selector_complete_source_dependency_closure():
    from forecast_tests.test_basis_job_sources import dependencies
    from system_campaign_select_job import SOURCES
    assert not dependencies(SOURCES)-set(SOURCES)
    broken=tuple(n for n in SOURCES if n!='system_campaign_search_admit.py')
    assert 'system_campaign_search_admit.py' in dependencies(broken)-set(broken)
