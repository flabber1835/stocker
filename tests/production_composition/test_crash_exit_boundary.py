"""Fixture exit ordering falsifiers complement the mandatory live Docker case."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import production_composition_harness as harness


@pytest.mark.parametrize('result',[
    (0,'137'),(0,'0'),(1,'137'),(0,''),(0,'not-an-exit'),
])
def test_wait_requires_confirmed_nonzero_container_exit(monkeypatch,result):
    calls=[]
    def run(args,**kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(returncode=result[0],stdout=result[1])
    monkeypatch.setattr(harness,'_run',run)
    if result==(0,'137'):
        harness._wait_for_crashed_container('a'*64,label='fixture')
    else:
        with pytest.raises(harness.HarnessFailure):
            harness._wait_for_crashed_container('a'*64,label='fixture')
    assert calls==[(['docker','wait','a'*64],{'timeout':15})]


def test_unidentified_or_unbounded_exit_cannot_authorize_retry(monkeypatch):
    monkeypatch.setattr(harness,'_run',lambda *a,**k:pytest.fail('unidentified container waited'))
    with pytest.raises(harness.HarnessFailure):
        harness._wait_for_crashed_container('',label='fixture')
    def timeout(*a,**k): raise subprocess.TimeoutExpired(a[0],15)
    monkeypatch.setattr(harness,'_run',timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        harness._wait_for_crashed_container('a'*64,label='fixture')


def ordered_case(tmp_path,monkeypatch):
    state={'killed':False,'exited':False,'ready_calls':0}
    def ensure(*a,**k):
        if state['killed']: assert state['exited'],'retry preceded the daemon exit'
        state['ready_calls']+=1
    monkeypatch.setattr(harness,'_ensure_ready',ensure)
    monkeypatch.setattr(harness,'_cleanup',lambda *a:None)
    def require(args,**kwargs):
        if 'kill' in args: state['killed']=True
        text=('a'*64 if '-q' in args else '1,2' if state['ready_calls']==3
              else '1' if 'SELECT' in args[-1] else '')
        return SimpleNamespace(returncode=0,stdout=text)
    monkeypatch.setattr(harness,'_require',require)
    class Worker:
        returncode=137
        def poll(self): return self.returncode
        def communicate(self,**kwargs): return '', ''
    monkeypatch.setattr(harness.subprocess,'Popen',lambda *a,**k:Worker())
    def run(args,**kwargs):
        assert args==['docker','wait','a'*64] and kwargs=={'timeout':15}
        assert state['killed']
        state['exited']=True
        return SimpleNamespace(returncode=0,stdout='137')
    monkeypatch.setattr(harness,'_run',run)
    assert harness._crash_transaction_case(tmp_path)['status']=='PASS'
    assert state['ready_calls']==3


def test_crash_case_waits_before_retry(tmp_path,monkeypatch):
    ordered_case(tmp_path,monkeypatch)


def test_removed_exit_barrier_fails_ordering(tmp_path,monkeypatch):
    monkeypatch.setattr(harness,'_wait_for_crashed_container',lambda *a,**k:None)
    with pytest.raises(AssertionError,match='retry preceded'):
        ordered_case(tmp_path,monkeypatch)


def test_diagnostic_failure_preserves_original_refusal(tmp_path,monkeypatch):
    monkeypatch.setattr(harness.probe_contract,'ensure_postgres_ready',
        lambda *a,**k:{'reason':'POSTGRES_CONTAINER_ID_UNAVAILABLE'})
    def timeout(*a,**k): raise subprocess.TimeoutExpired(a[0],10)
    monkeypatch.setattr(harness,'_run',timeout)
    with pytest.raises(harness.HarnessFailure,match='POSTGRES_CONTAINER_ID_UNAVAILABLE.*TimeoutExpired'):
        harness._ensure_ready(tmp_path/'fixture.yml','fixture',timeout_seconds=45,label='case')
