"""Recovery cannot call an unaccepted nested activity producer.

All HTTP calls resolve into this file's deterministic read-only fake. Production
constructors, adapter inheritance, guards, reconciliation and PostgreSQL journal
remain in use. Ordinary observation remains available without SSE authority.
"""
import asyncio
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sentinel import binding as B, config, schema
from sentinel.execution import journal, reconcile
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.guarded import GuardedExecutionBroker, PaperPreparationGrant, ExecutionBrokerGuard
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.states import RuntimeState
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables

ACCOUNT='AUDIT-SSE'
DEPLOY=DeploymentIdentity('audit399','alpaca',ACCOUNT,1)
SSE='/v2beta1/events/activities'

class Response:
    def __init__(self,payload=None,code=200,text=''):
        self.payload=payload; self.status_code=code; self.text=text; self.headers={}
    def json(self): return self.payload
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f'fake HTTP {self.status_code}')

class Http:
    def __init__(self,sse_status):
        self.paths=[]
        outer=self
        class Client:
            def __init__(self,**kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): return False
            async def get(self,url,**kwargs):
                path=urlparse(url).path
                outer.paths.append(path)
                if path=='/v2/account':
                    return Response({'id':'audit-native-uuid','account_number':ACCOUNT})
                if path in {'/v2/orders','/v2/positions'}: return Response([])
                if path==SSE: return Response(code=sse_status,text='')
                raise AssertionError(f'unexpected read {url}')
            async def post(self,*args,**kwargs): raise AssertionError('mutation forbidden')
            async def delete(self,*args,**kwargs): raise AssertionError('mutation forbidden')
        self.AsyncClient=Client

async def no_op(*args): pass

def broker(status):
    cfg=config.SentinelConfig(alpaca_key='AUDIT-ONLY',alpaca_secret='AUDIT-ONLY',
        base_url=config.DEFAULT_BASE_URL,state_dir=Path('/audit/state'),max_cycles=1,poll_seconds=0)
    inner=config.build_execution_broker(cfg,resolve_security_id=lambda symbol,*args:symbol)
    assert isinstance(inner,AssetIdAlpacaExecutionBroker)
    http=Http(status)
    inner._http_provider=lambda:http
    outer=GuardedExecutionBroker(inner=inner,
        grant=PaperPreparationGrant(expected_account=ACCOUNT,decision_session=date(2026,9,17)),
        guard=ExecutionBrokerGuard(no_op,no_op,no_op))
    return outer,http

@pytest.fixture(scope='module')
def pg():
    p=_EphemeralPostgres();p.start()
    yield p
    p.stop()

@pytest.fixture
def conn(pg):
    c=store.connect(pg.sync_dsn)
    drop_public_tables(c);schema.ensure_schema(c)
    B.bind(c,deployment_id='audit399',broker='alpaca',broker_account_id=ACCOUNT)
    yield c
    c.close()

def assert_quarantined(b):
    assert not b.financial_activity_sse
    assert not b.capabilities.recent_fill_history
    assert not b.supports_account_cash_activities
    assert not b.supports_account_fill_interval_evidence

def test_ordinary_observation_control_never_reads_candidate_sse(conn):
    b,http=broker(403);assert_quarantined(b)
    observation=asyncio.run(b.observe())
    assert observation.is_complete
    assert SSE not in http.paths

@pytest.mark.parametrize('status', [200, 403])
def test_reconciliation_never_calls_unaccepted_nested_fill_producer(conn, status):
    b, http = broker(status)
    assert_quarantined(b)
    result = asyncio.run(reconcile.reconcile(broker=b,conn=conn,binding=B.load(conn),deployment=DEPLOY))
    assert SSE not in http.paths
    assert result.runtime_state is RuntimeState.RECONCILING
    assert result.observation is not None and not result.observation.is_complete
    assert result.observation.terminal_recovery_through is None
    assert not journal.load_commands(conn, DEPLOY)
