"""Fresh deployed ingress reaches the original signed predicate without runtime."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType
import uuid

import pytest

from sentinel import shadow_supervisor as supervisor
from sentinel.shadow_service_config import ShadowServiceConfig,ShadowServiceWaiting
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


GUARD='''import importlib.abc,importlib.machinery,os,sys
class Denied(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in
   ('sentinel.shadow_recovery','sentinel.shadow_service','sentinel.shadow_runtime',
    'sentinel.shadow_worker','pandas','numpy','exchange_calendars')):
   raise RuntimeError('FORBIDDEN_HEALTH_BOOTSTRAP:'+fullname)
sys.meta_path.insert(0,Denied())
if os.environ.get('HEALTH_TEST_RESTORE_EAGER')=='1':
 class Loader:
  def __init__(self,original):self.original=original
  def get_code(self,fullname):
   source=self.original.get_source(fullname)
   broken=source.replace('from sentinel.shadow_service_config import ShadowServiceConfig, ShadowServiceWaiting',
    'from sentinel.shadow_recovery import ShadowServiceConfig, ShadowServiceWaiting',1)
   assert broken!=source
   return compile(broken,self.original.get_filename(fullname),'exec')
  def is_package(self,fullname):return False
 class Restored(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   if fullname=='sentinel.shadow_supervisor':
    spec=importlib.machinery.PathFinder.find_spec(fullname,path)
    spec.loader=Loader(spec.loader);return spec
 sys.meta_path.insert(0,Restored())
'''


def _cli(tmp_path,*,env=None,restore_eager=False,service_only=False):
    hook=tmp_path/'cold-hook';hook.mkdir(exist_ok=True)
    (hook/'sitecustomize.py').write_text(GUARD)
    values=dict(os.environ if env is None else env)
    values['PYTHONPATH']=str(hook)+os.pathsep+values.get('PYTHONPATH','')
    if restore_eager:values['HEALTH_TEST_RESTORE_EAGER']='1'
    else:values.pop('HEALTH_TEST_RESTORE_EAGER',None)
    return subprocess.run([sys.executable,'-B','-m','sentinel.shadow_supervisor',
        '--service-health' if service_only else '--health'],env=values,
        capture_output=True,text=True,timeout=10)


def _assert_clean_ingress(result,expected):
    assert 'FORBIDDEN_HEALTH_BOOTSTRAP' not in result.stderr,'entrypoint loaded financial bootstrap'
    assert result.returncode==expected,result.stderr


def test_actual_cold_cli_missing_heartbeat_is_original_negative(tmp_path):
    # Qualification runs in an isolated tmp namespace; never overwrite a live file.
    assert not supervisor.HEARTBEAT_FILE.exists(),'requires isolated private /tmp'
    result=_cli(tmp_path)
    _assert_clean_ingress(result,1)
    assert 'supervisor heartbeat absent' in result.stderr


@pytest.fixture
def signed_health(pg,tmp_path,monkeypatch):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from sentinel import shadow_health_projection as health
    database='cold_health_'+uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    dsn=make_conninfo(pg.sync_dsn,dbname=database)
    with psycopg.connect(dsn) as conn:
        conn.execute('CREATE TABLE sentinel_processed_sessions(cursor_name text PRIMARY KEY,session date,state jsonb)')
        conn.execute('CREATE TABLE sentinel_corpus_publications(version bigint PRIMARY KEY)')
        conn.execute("INSERT INTO sentinel_processed_sessions VALUES('rolling-cold-start:v1',CURRENT_DATE,'{}')")
        conn.execute('INSERT INTO sentinel_corpus_publications VALUES(1)')
    state=tmp_path/'state';state.mkdir()
    values={
        'SENTINEL_DATABASE_URL':dsn,'SENTINEL_STATE_DIR':str(state),
        'SENTINEL_FEED_SERVICE_MODE':'SHADOW','SENTINEL_SHADOW_OBSERVATION_ENABLED':'true',
        'SENTINEL_REVIEWED_DEPLOYMENT_MODE':'shadow',
        'SENTINEL_PUBLICATION_RECEIPT_KEY':'private-health-fixture-key-'*3,
        'ALPACA_API_KEY':'private-fixture-not-a-credential',
        'ALPACA_SECRET_KEY':'private-fixture-not-a-credential',
        'SHARADAR_API_KEY':'','SENTINEL_PAPER_ACCOUNT_ID':'',
        **{name:'a'*64 for name in ('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256',
            'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256','SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256',
            'SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256')},
    }
    for name,value in values.items():monkeypatch.setenv(name,value)
    config=ShadowServiceConfig.from_env()
    with psycopg.connect(dsn) as conn:inventory,present=health._inventory(conn)
    assert present
    now=datetime.now(timezone.utc)
    # Synthetic signed observation only: calendar eligibility itself has the
    # independent DST/holiday/half-day cohort. No financial state is certified.
    begin,current,end=now-timedelta(days=1),now+timedelta(days=1),now+timedelta(days=2)
    payload=health.Projection(schema_id=health.SCHEMA,config_sha256=health._config(config),
        inventory_sha256=inventory,session=begin.date().isoformat(),record_sha256='b'*64,
        runtime_authority_sha256='c'*64,waiting_session=current.date().isoformat(),
        calendar_identity='XNYS/exchange_calendars private-fixture',valid_from=begin.isoformat(),
        current_until=current.isoformat(),valid_until=end.isoformat()).model_dump()
    target=state/'shadow-health-projection.json'
    target.write_text(json.dumps(dict(projection=payload,hmac_sha256=health._signature(payload))))
    assert not supervisor.HEARTBEAT_FILE.exists(),'requires isolated private /tmp'
    supervisor.HEARTBEAT_FILE.touch()
    try:yield dict(env=dict(os.environ),state=state,target=target,config=config)
    finally:
        supervisor.HEARTBEAT_FILE.unlink(missing_ok=True)
        with psycopg.connect(pg.sync_dsn,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


def test_actual_cold_cli_valid_signed_projection_avoids_financial_bootstrap(signed_health,tmp_path):
    _assert_clean_ingress(_cli(tmp_path,env=signed_health['env']),0)


def test_restoring_original_eager_ingress_is_detected(signed_health,tmp_path):
    broken=_cli(tmp_path,env=signed_health['env'],restore_eager=True)
    with pytest.raises(AssertionError,match='loaded financial bootstrap'):
        _assert_clean_ingress(broken,0)


@pytest.mark.parametrize('damage',['stale','critical','pending','tampered','missing_projection'])
def test_cold_cli_keeps_original_negative_guards(signed_health,tmp_path,damage):
    if damage=='stale':
        old=time.time()-60;os.utime(supervisor.HEARTBEAT_FILE,(old,old))
    elif damage=='critical':
        (signed_health['state']/'shadow-supervisor-critical.json').write_text('private critical marker')
    elif damage=='pending':
        (signed_health['state']/'shadow-supervisor-pending.json').write_text('{}')
    elif damage=='tampered':
        value=json.loads(signed_health['target'].read_text());value['hmac_sha256']='0'*64
        signed_health['target'].write_text(json.dumps(value))
    else:signed_health['target'].unlink()
    _assert_clean_ingress(_cli(tmp_path,env=signed_health['env']),1)


def test_cold_process_health_still_excludes_financial_readiness(signed_health,tmp_path):
    signed_health['target'].unlink()
    _assert_clean_ingress(_cli(tmp_path,env=signed_health['env'],service_only=True),0)


def test_lazy_fallback_forwards_to_original_recovery_with_same_types(monkeypatch):
    fake=ModuleType('sentinel.shadow_recovery');calls=[]
    config=object();now=datetime.now(timezone.utc)
    def original(value,*,now=None):calls.append((value,now));return {'original':True}
    fake.service_health=original
    monkeypatch.setitem(sys.modules,'sentinel.shadow_recovery',fake)
    assert supervisor.service_health(config,now=now)=={'original':True}
    assert calls==[(config,now)]
    def refused(*_args,**_kwargs):raise ShadowServiceWaiting('same exception')
    fake.service_health=refused
    with pytest.raises(ShadowServiceWaiting,match='same exception'):supervisor.service_health(config)


@pytest.mark.parametrize('active',[False,True])
def test_public_fallback_patchpoint_preserves_active_waiting_rule(tmp_path,monkeypatch,active):
    heartbeat=tmp_path/'heartbeat';heartbeat.touch()
    critical=tmp_path/'shadow-supervisor-critical.json'
    monkeypatch.setattr(supervisor,'HEARTBEAT_FILE',heartbeat)
    monkeypatch.setattr(supervisor,'LATCH_FILE',critical)
    monkeypatch.setattr(supervisor.shadow_worker_liveness,'matches',lambda _:active)
    if active:critical.with_name('shadow-supervisor-pending.json').write_text('{}')
    calls=[]
    def waiting(value):calls.append(value);raise ShadowServiceWaiting('original waiting')
    monkeypatch.setattr(supervisor,'service_health',waiting)
    config=ShadowServiceConfig('private','primary',__import__('decimal').Decimal(50000),'unused',300)
    assert supervisor._health_snapshot(30,config)==(0 if active else 1)
    assert calls==[config]


def test_parent_dependency_health_deadline_stays_three_seconds(monkeypatch):
    calls=[]
    def run(function,*args,**kwargs):calls.append((function,args,kwargs));return 1
    monkeypatch.setattr(supervisor.supervisor_io,'run',run)
    assert supervisor._health(30,config='private')==1
    assert calls==[(supervisor._health_snapshot,(30,'private'),{'timeout':3})]
