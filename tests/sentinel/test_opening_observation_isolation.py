"""Real contention and omission oracles for the observed opening failure."""
from contextlib import contextmanager
import inspect,textwrap
from dataclasses import replace
import psycopg
import pytest

from sentinel import rolling_runtime as rolling,structural_verification as cache,snapshot_scan_admission as admission
from sentinel.panel import model,projection_service as producer,verification_service as verifier
from tests.sentinel.test_compact_guard_projection import compact,conn,pg
from tests.sentinel.test_panel_command_progress import cycle


def test_warm_guard_does_not_wait_for_unrelated_verifier_scan(compact,conn):
    compact.read()
    with psycopg.connect(conn.info.dsn) as other:
        with admission.admitted(other):
            assert compact.read().session=='2026-09-14'
    assert compact.calls['load']==1


def test_warm_path_never_runs_a_cold_load_unadmitted(monkeypatch):
    events=[]
    @contextmanager
    def proof(_conn,**kwargs):
        events.append(kwargs.get('serialize_snapshot',False));yield object()
    monkeypatch.setattr(rolling.committed_read,'proof_connection',proof)
    monkeypatch.setattr(cache,'has_material',lambda slot:True)
    def operation(conn,**kwargs):
        if kwargs.get('cached_only'):
            raise cache.MaterialNotCached('changed version')
        assert events==[False,True]
        return 'proved'
    assert rolling._committed_status(None,operation)=='proved'


def test_removed_cold_admission_fails_oracle(monkeypatch):
    original=rolling._committed_status
    code=textwrap.dedent(inspect.getsource(original))
    assert 'serialize_snapshot=True' in code
    namespace=dict(vars(rolling));exec(code.replace('serialize_snapshot=True','serialize_snapshot=False'),namespace)
    monkeypatch.setattr(rolling,'_committed_status',namespace['_committed_status'])
    with pytest.raises(AssertionError):test_warm_path_never_runs_a_cold_load_unadmitted(monkeypatch)


def test_json_historical_submission_wake_is_progress_not_interruption():
    c=cycle();event=dict(from_state='EXECUTING',to_state='RECONCILING',at=c['updated_at'],
      detail=dict(failure_code=c['failure_code'],failure_detail=c['failure_detail'],
       diagnostic=c['diagnostic'],last_clean_reconciliation_id=c['clean_reconciliation_id'],
       next_wake_at=c['next_wake_at'].isoformat()))
    rows={r.key:r for r in model.automation_step_rows(installed=True,enabled=True,cycle=c,events=[event])}
    assert rows['automation_step_transport'].status!=model.FAIL
    for wake in ('malformed','2030-01-01',None):
        event['detail']['next_wake_at']=wake
        assert next(r for r in model.automation_step_rows(installed=True,enabled=True,cycle=c,events=[event])
          if r.key=='automation_step_transport').status==model.FAIL


def test_removed_timestamp_normalization_fails_real_event_oracle(monkeypatch):
    monkeypatch.setattr(model,'_historical_wake',lambda v:v)
    with pytest.raises(AssertionError):test_json_historical_submission_wake_is_progress_not_interruption()
