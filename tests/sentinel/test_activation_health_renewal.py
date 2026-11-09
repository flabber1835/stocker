"""Activation must join producer health renewal before independent attestation."""
import ast
from datetime import datetime, timedelta, timezone
import json
from subprocess import CompletedProcess

import pytest

from scripts import sentinel_activation_shadow as probe
from sentinel import shadow_health_projection as health, shadow_service
from tests.sentinel.test_shadow_health_projection import projection, conn, pg  # noqa: F401
from tests.sentinel.test_activation_shadow_progress import signed_owner, child_namespace
from tests.sentinel.test_activation_writer_handoff import (
    CLASSES, core, appliance, offline_activation_read_owner)  # noqa: F401


@pytest.fixture(autouse=True)
def synthetic_receipt_key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','synthetic-renewal-regression-key-'*3)


@pytest.fixture
def renewal(projection, signed_owner, monkeypatch):
    publish, _ = signed_owner
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', projection.observation_id)
    monkeypatch.setattr(shadow_service.ShadowServiceConfig, 'from_env', staticmethod(lambda:projection))
    publish(projection.database_url)
    wrapped=json.loads(health.path().read_bytes())
    wrapped['projection']['config_sha256']='0'*64
    wrapped['hmac_sha256']=health._signature(wrapped['projection'])
    health._write(wrapped,health.path())
    ns=child_namespace();calls=[]
    ns['_original_shadow_status']=lambda *_a,**_kw:calls.append('financial attestation') or 'verified'
    return ns,projection,publish,calls


def observe(ns, config):
    return ns['_status_with_formation'](None,observation_id=config.observation_id,starting_cash=config.starting_cash)


def waiting(ns,config,capsys):
    with pytest.raises(SystemExit) as stopped:
        observe(ns,config)
    assert stopped.value.code==probe.FORMATION_EXIT
    return probe.decode_result(CompletedProcess([],stopped.value.code,capsys.readouterr().out,''))


@pytest.mark.parametrize('missing',[False,True])
def test_real_signed_projection_and_owner_wait_before_financial_replay_then_renew(
        renewal,missing,capsys):
    ns,config,publish,calls=renewal
    if missing:health.path().unlink()
    value=waiting(ns,config,capsys)
    assert value['state']=='HEALTH_REBINDING'
    assert value['session']==(None if missing else '2026-09-14')
    assert calls==[]
    # Simulated producer publication: real signed envelope/config/inventory.
    # Canonical worker publication itself is covered by test_shadow_health_projection.
    if missing:
        payload=health.Projection(schema_id=health.SCHEMA,config_sha256='0'*64,
            inventory_sha256='0'*64,session='2026-09-14',record_sha256='a'*64,
            runtime_authority_sha256='b'*64,**health._calendar_bounds('2026-09-14')).model_dump()
        wrapped={'projection':payload}
    else:wrapped=json.loads(health.path().read_bytes())
    from sentinel.feed import store
    connection=store.connect(config.database_url)
    try:inventory,_=health._inventory(connection)
    finally:connection.rollback();connection.close()
    wrapped['projection'].update(config_sha256=health._config(config),inventory_sha256=inventory)
    wrapped['hmac_sha256']=health._signature(wrapped['projection'])
    health._write(wrapped,health.path())
    publish(config.database_url,active=False)
    assert observe(ns,config)=='verified'
    assert calls==['financial attestation']


def test_removing_renewal_gate_fails_the_regression(renewal,capsys):
    ns,config,_,calls=renewal
    waiting(ns,config,capsys)
    assert calls==[]
    ns['_health_renewal']=lambda _:None
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        waiting(ns,config,capsys)
    assert calls==['financial attestation']


@pytest.mark.parametrize('damage',['hmac','schema','idle','stale','permission','unrelated','subclass'])
def test_only_exact_renewal_with_current_active_producer_can_wait(renewal,monkeypatch,damage):
    ns,config,publish,calls=renewal
    if damage in {'hmac','schema'}:
        wrapped=json.loads(health.path().read_bytes())
        if damage=='schema':wrapped['projection']['schema_id']='unknown'
        wrapped['hmac_sha256']='0'*64 if damage=='hmac' else health._signature(wrapped['projection'])
        health.path().write_text(json.dumps(wrapped))
    elif damage=='idle':publish(config.database_url,active=False)
    elif damage=='stale':publish(config.database_url,observed=datetime.now(timezone.utc)-timedelta(seconds=61))
    else:
        class OtherRenewal(health.ProjectionRenewalRequired):pass
        error={'permission':PermissionError('no access'),'unrelated':ValueError('bad evidence'),
               'subclass':OtherRenewal('binding changed',session='2026-09-14')}[damage]
        def refused(*_a,**_kw):raise error
        monkeypatch.setattr(health,'health',refused)
    with pytest.raises((ValueError,OSError)):
        observe(ns,config)
    assert calls==[]


@pytest.mark.parametrize('damage',['incarnation','binding','clock','deadline','attempt'])
def test_replaced_or_changed_producer_cannot_supply_the_wait(renewal,damage):
    ns,config,_,calls=renewal
    before=ns['_owner'](config);after=dict(before)
    if damage=='incarnation':after['incarnation']='d'*32
    elif damage=='binding':after['binding_sha256']='e'*64
    elif damage=='clock':after['observed_at']-=timedelta(seconds=1)
    elif damage=='deadline':after['worker_deadline']+=timedelta(seconds=1)
    else:after['attempt_id']='f'*32
    owners=iter([before,after]);ns['_owner']=lambda _:next(owners)
    if damage=='attempt':assert ns['_health_renewal'](config) is False
    else:
        with pytest.raises(ValueError,match='changed'):
            ns['_health_renewal'](config)
    assert calls==[]


def test_owner_change_and_attempt_guard_falsifiers(renewal):
    ns,config,_,_=renewal
    before=ns['_owner'](config)
    for field in ('incarnation','attempt_id'):
        tree=ast.parse(probe.code())
        function=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='_health_renewal')
        guard=next(v for v in ast.walk(function) if isinstance(v,ast.If) and
            any(isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and n.slice.value==field
                for n in ast.walk(v.test)))
        guard.test=ast.Constant(False)
        mutant=dict(ns)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'<removed-owner-guard>','exec'),mutant)
        after=dict(before);after[field]='d'*32
        owners=iter([before,after]);mutant['_owner']=lambda _:next(owners)
        assert mutant['_health_renewal'](config)['state']=='HEALTH_REBINDING'


def test_worker_completion_is_reobserved_before_attestation(renewal,monkeypatch):
    ns,config,_,calls=renewal
    before=ns['_owner'](config);idle=dict(before,reason='IDLE',attempt_id=None,worker_deadline=None)
    owners=iter([before,idle,idle]);ns['_owner']=lambda _:next(owners)
    real_health=health.health;reads=[]
    def current(*a,**kw):
        reads.append(True)
        if len(reads)==1:return real_health(*a,**kw)
        return {'service_health':'HEALTHY_ATTESTED'}
    monkeypatch.setattr(health,'health',current)
    assert observe(ns,config)=='verified'
    assert len(reads)==2 and calls==['financial attestation']


@pytest.mark.parametrize('cls',CLASSES)
@pytest.mark.parametrize('expires',[False,True])
def test_actual_resumed_activation_waits_and_never_dispatches_expired_renewal(
        tmp_path,monkeypatch,cls,expires):
    obj,events,control,running=appliance(tmp_path,cls)
    control.update(enabled=True,kill_switch_engaged=False)
    running.update(shadow=False,automation=False)
    obj.cfg.health_timeout=1
    obj.cfg.formation_timeout_seconds=6
    obj.cfg.data_wait_timeout_seconds=9 if expires else 120
    obj._wait_for_dual_shadow_session=core.AutonomousDeploy._wait_for_dual_shadow_session.__get__(obj)
    clock=[0.0]
    monkeypatch.setattr(core.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(core.time,'sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    now=datetime.now(timezone.utc)
    wait=dict(schema=probe.SCHEMA,state='HEALTH_REBINDING',session=None,
        publisher_attempt_id='a'*32,publisher_binding_sha256='b'*64,
        publisher_observed_at=now.isoformat(),publisher_deadline=(now+timedelta(seconds=120)).isoformat())
    original=obj.runner.run;reads=[]
    def run(args,**kwargs):
        if args[-1]!='shadow-status':return original(args,**kwargs)
        reads.append(True)
        assert 'start-collector' not in events and 'start-automation' not in events
        if expires or len(reads)==1:
            events.append('health-renewal-wait')
            return CompletedProcess(args,probe.FORMATION_EXIT,probe.WAIT_MARKER+json.dumps(wait),'')
        events.append('producer-renewed')
        return CompletedProcess(args,0,json.dumps(dict(mode='BROKER_FREE_SHADOW',
            broker_mutations_authorized=False,shadow_verdict='SHADOW_GO',verification='VERIFIED',
            session='2026-10-08')),'')
    obj.runner.run=run
    if expires:
        with pytest.raises(core.ActivationPending):
            with obj.activation_transition():obj.start_activated_runtime('certificate','2026-10-08')
        assert control['kill_switch_engaged'] and not running['automation']
        assert running['shadow']  # Existing availability policy lets broker-free renewal finish.
        assert 'start-collector' not in events and 'start-automation' not in events
    else:
        with obj.activation_transition():obj.start_activated_runtime('certificate','2026-10-08')
        assert events.index('health-renewal-wait')<events.index('producer-renewed')<events.index('start-collector')<events.index('start-automation')
        assert len(reads)==2 and clock[0]==30
