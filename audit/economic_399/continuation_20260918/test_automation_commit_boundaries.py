"""Audit-only SQL atomicity probes against unchanged aff4461d source.

These isolate actual store commits with real PostgreSQL and SIGKILL. Synthetic
phase-plan labels scope the claim to control/cycle persistence, not broker
settlement or production plan certification. No production service is contacted.
"""
from __future__ import annotations
import multiprocessing as mp
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from sentinel import schema, backup_runtime_authority
from sentinel.automation import store, schedule
from sentinel.automation.model import AutomationConfig, ControlBinding, CycleSpec, CycleState, StaleLeaderRefused
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


CASES = ('activate','release_kill','engage_kill','deactivate','config_kill',
         'acquire_lease','heartbeat','release_lease','create_cycle',
         'plan_ready','execute_entry','reconciling','succeeded','adoption')
TABLES = ('sentinel_automation_control','sentinel_automation_lease',
          'sentinel_automation_events','sentinel_automation_cycles',
          'sentinel_automation_cycle_events')

@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try: yield server
    finally: server.stop()


def snapshot(conn):
    result = {}
    for table in TABLES:
        rows = conn.execute(f'SELECT row_to_json(t) FROM {table} t').fetchall()
        result[table] = sorted([r[0] for r in rows],key=lambda v:repr(sorted(v.items())))
    conn.rollback()
    return result


class Cursor:
    def __init__(self, owner, inner): self.owner,self.inner=owner,inner
    def __getattr__(self,name): return getattr(self.inner,name)
    def __enter__(self): self.inner.__enter__();return self
    def __exit__(self,*args): return self.inner.__exit__(*args)
    def execute(self,sql,*args,**kw):
        result=self.inner.execute(sql,*args,**kw)
        if self.owner.marker in ' '.join(str(sql).split()): self.owner.armed=True
        return result

class KillAtCommit:
    def __init__(self,conn,marker,cut): self.conn,self.marker,self.cut,self.armed=conn,marker,cut,False
    def __getattr__(self,name): return getattr(self.conn,name)
    def cursor(self,*a,**kw):return Cursor(self,self.conn.cursor(*a,**kw))
    def commit(self):
        if self.armed and self.cut=='before': os.kill(os.getpid(),signal.SIGKILL)
        self.conn.commit()
        if self.armed and self.cut=='after': os.kill(os.getpid(),signal.SIGKILL)


def child_action(dsn,case,cut,ctx):
    backup_runtime_authority.POLICY_MARKER=Path('/audit/absent-production-policy-for-isolated-sql-probe')
    raw=psycopg.connect(dsn)
    marker = ('UPDATE sentinel_automation_control SET' if case in CASES[:5]
              else 'UPDATE sentinel_automation_lease' if case in {'acquire_lease','heartbeat','release_lease'}
              else 'INSERT INTO sentinel_automation_cycles' if case=='create_cycle'
              else 'UPDATE sentinel_automation_cycles SET')
    conn=KillAtCommit(raw,marker,cut)
    cfg,binding,permit,spec,cycle=ctx
    if case=='activate':store.activate(conn,binding=binding,actor='audit',reason='atomic activate')
    elif case=='release_kill':store.release_kill(conn,expected_binding=binding,actor='audit',reason='atomic release')
    elif case=='engage_kill':store.engage_kill(conn,actor='audit',reason='atomic kill')
    elif case=='deactivate':store.deactivate(conn,actor='audit',reason='atomic deactivate')
    elif case=='config_kill':store.engage_config_mismatch_kill(conn,expected_generation=permit.control_generation,expected_config_sha256=cfg.fingerprint,actual_config_sha256='a'*64)
    elif case=='acquire_lease':store.acquire_lease(conn,holder_id='audit-owner',lease_seconds=60)
    elif case=='heartbeat':store.heartbeat_lease(conn,permit=permit,lease_seconds=60)
    elif case=='release_lease':store.release_lease(conn,permit=permit)
    elif case=='create_cycle':store.create_cycle(conn,permit=permit,spec=spec)
    elif case=='adoption':store.adopt_cycle(conn,permit=permit,cycle_id=cycle.cycle_id)
    else:
        target={'plan_ready':CycleState.PLAN_READY,'execute_entry':CycleState.EXECUTING,
                'reconciling':CycleState.RECONCILING,'succeeded':CycleState.SUCCEEDED}[case]
        fields={'plan_id':'audit-phase-plan','plan_fingerprint':'f'*64} if case=='plan_ready' else {}
        store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=target,**fields)
    raise AssertionError('requested mutation commit boundary was not reached')


def setup_case(conn,case):
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    cfg=AutomationConfig(lease_seconds=60,heartbeat_seconds=5)
    binding=ControlBinding(deployment_id='audit-deployment',broker='alpaca-paper',
        broker_account_id='audit-account',takeover_epoch=1,certificate_sha256='d'*64,
        rollout_mode='PINNED_1_00',rollout_version=1,config_sha256=cfg.fingerprint)
    permit=spec=cycle=None
    if case=='activate':return cfg,binding,permit,spec,cycle
    store.activate(conn,binding=binding,actor='audit',reason='setup activate')
    if case=='release_kill':return cfg,binding,permit,spec,cycle
    store.release_kill(conn,expected_binding=binding,actor='audit',reason='setup release')
    if case=='acquire_lease':return cfg,binding,permit,spec,cycle
    permit=store.acquire_lease(conn,holder_id='audit-owner',lease_seconds=60)
    if case in {'engage_kill','deactivate','config_kill','heartbeat','release_lease'}:return cfg,binding,permit,spec,cycle
    timing=schedule.for_decision_session('2026-08-12',cfg)
    spec=CycleSpec(**{key:getattr(timing,key) for key in ('decision_session','effective_session','decision_close_at','prepare_at','execution_open_at','execute_at','execution_close_at')},
        **binding.model_dump(),control_generation=permit.control_generation)
    if case=='create_cycle':return cfg,binding,permit,spec,cycle
    cycle=store.create_cycle(conn,permit=permit,spec=spec)
    for target in (CycleState.REFRESHING_DATA,CycleState.PREPARING):
        cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=target)
    if case=='plan_ready':return cfg,binding,permit,spec,cycle
    cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=CycleState.PLAN_READY,plan_id='audit-phase-plan',plan_fingerprint='f'*64)
    cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=CycleState.WAITING_OPEN)
    if case=='execute_entry':return cfg,binding,permit,spec,cycle
    cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=CycleState.EXECUTING)
    if case=='succeeded':
        cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=CycleState.RECONCILING)
    if case=='adoption':
        store.engage_kill(conn,actor='audit',reason='fence old executor')
        store.release_kill(conn,expected_binding=binding,actor='audit',reason='current recovery authority')
        permit=store.acquire_lease(conn,holder_id='audit-replacement',lease_seconds=60)
    return cfg,binding,permit,spec,cycle


@pytest.mark.parametrize('case',CASES)
@pytest.mark.parametrize('cut',('before','after'))
def test_store_commit_is_atomic_across_real_process_death(pg,monkeypatch,case,cut):
    monkeypatch.setattr(backup_runtime_authority,'POLICY_MARKER',Path('/audit/absent-production-policy-for-isolated-sql-probe'))
    with psycopg.connect(pg.sync_dsn) as conn:
        ctx=setup_case(conn,case)
        before=snapshot(conn)
        proc=mp.get_context('fork').Process(target=child_action,args=(pg.sync_dsn,case,cut,ctx))
        proc.start();proc.join(10)
        if proc.is_alive():proc.kill();proc.join();pytest.fail('child did not reach audited boundary')
        assert proc.exitcode==-signal.SIGKILL,proc.exitcode
        after=snapshot(conn)
        if cut=='before':
            assert after==before
            return
        assert after!=before
        cfg,binding,permit,spec,cycle=ctx
        if case in CASES[:5]:
            b=before[TABLES[0]][0];a=after[TABLES[0]][0]
            assert a['generation']==b['generation']+1
            assert len(after[TABLES[2]])==len(before[TABLES[2]])+1
            event=max(after[TABLES[2]],key=lambda v:v['seq'])
            assert event['generation']==a['generation']
            assert a['enabled']==(case!='deactivate')
            assert a['kill_switch_engaged']==(case!='release_kill')
            lease=after[TABLES[1]][0]
            assert lease['holder_id'] is None and lease['expires_at'] is None
        elif case in {'acquire_lease','heartbeat','release_lease'}:
            lease=after[TABLES[1]][0]
            if case=='release_lease':assert lease['holder_id'] is None and lease['expires_at'] is None
            else:
                assert lease['holder_id']=='audit-owner'
                if permit:assert lease['fence_token']==permit.fence_token
                else:assert lease['fence_token']==before[TABLES[1]][0]['fence_token']+1
                assert lease['expires_at']>lease['heartbeat_at']
            assert after[TABLES[2]]==before[TABLES[2]]
        else:
            assert len(after[TABLES[4]])==len(before[TABLES[4]])+1
            event=max(after[TABLES[4]],key=lambda v:v['seq'])
            row=after[TABLES[3]][0]
            target={'create_cycle':'DISCOVERED','plan_ready':'PLAN_READY','execute_entry':'EXECUTING',
                    'reconciling':'RECONCILING','succeeded':'SUCCEEDED','adoption':'EXECUTING'}[case]
            assert row['state']==target==event['to_state']
            assert event['fence_token']==row['last_fence_token']==permit.fence_token
            assert event['control_generation']==permit.control_generation
            assert bool(row['completed_at'])==(case=='succeeded')
            if case=='adoption':
                assert row['control_generation']==cycle.control_generation
                assert row['control_generation']<event['control_generation']
            if case=='succeeded':assert row['plan_id']=='audit-phase-plan'
