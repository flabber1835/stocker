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


@pytest.mark.parametrize('status', [200, 403])
def test_informational_current_book_does_not_borrow_historical_authority(conn, status):
    b, http = broker(status)
    assert_quarantined(b)
    result = asyncio.run(reconcile.reconcile(
        broker=b, conn=conn, binding=B.load(conn), deployment=DEPLOY,
        informational_current_book=True))
    assert result.runtime_state is RuntimeState.RUNNING
    assert result.clean and result.observation.is_complete
    assert result.observation.terminal_recovery_through is None
    assert not result.observation.fill_history_complete
    assert SSE not in http.paths
    assert conn.execute('SELECT COUNT(*) FROM sentinel_terminal_recovery_watermark').fetchone()[0] == 0
    assert not journal.load_commands(conn, DEPLOY)


@pytest.mark.parametrize('working_state', ['ACKNOWLEDGED', 'UNKNOWN', 'SEND_PENDING'])
@pytest.mark.parametrize('found', [False, True])
def test_current_book_requires_positive_exact_order_evidence(conn, working_state, found):
    from decimal import Decimal
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState
    from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response, full_order

    b, _http = broker(403)
    command = Command(
        identity=CommandIdentity(DEPLOY, 'fixture-plan', 'AAPL'),
        instrument=BrokerInstrument('AAPL', 'AAPL', 'asset-aapl'),
        side=Side.BUY, quantity=Decimal(2), state=CommandState[working_state],
        broker_order_id='order-1' if working_state == 'ACKNOWLEDGED' else None)
    journal.save_command(conn, command)
    http = Httpx(routes={
        '/v2/account': Response({'id': 'audit-native-uuid', 'account_number': ACCOUNT}),
        '/v2/orders:by_client_order_id': Response(
            full_order(status='filled', filled='2', client_order_id=command.client_key)
            if found else {}, 200 if found else 404),
        '/v2/positions': Response([
            {'symbol': 'AAPL', 'asset_id': 'asset-aapl', 'qty': '2'}] if found else []),
    })
    b._inner._http_provider = lambda: http
    result = asyncio.run(reconcile.reconcile(
        broker=b, conn=conn, binding=B.load(conn), deployment=DEPLOY,
        informational_current_book=True))
    durable = journal.load_commands(conn, DEPLOY)[0]
    assert durable.state is (CommandState.FILLED if found else CommandState.UNKNOWN)
    assert durable.filled_quantity == (Decimal(2) if found else Decimal(0))
    assert result.runtime_state is (RuntimeState.RUNNING if found else RuntimeState.RECONCILING)
    assert any(call[1] == '/v2/orders:by_client_order_id' for call in http.calls)
    assert all(call[0] == 'GET' for call in http.calls)
    assert not any('activities' in call[1] for call in http.calls)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_terminal_recovery_watermark').fetchone()[0] == 0


@pytest.mark.parametrize('scope', [None, 1, 'true'])
def test_current_book_scope_never_uses_truthy_coercion(conn, scope):
    b, http = broker(403)
    with pytest.raises(TypeError, match='must be boolean'):
        asyncio.run(reconcile.reconcile(broker=b, conn=conn, binding=None,
            deployment=DEPLOY, informational_current_book=scope))
    assert http.paths == []


@pytest.mark.parametrize('fault', ['account-flip', 'position-flip', 'foreign-position', 'foreign-order'])
def test_current_book_retains_production_account_and_foreign_activity_fences(conn, fault):
    from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response, full_order
    b, _http = broker(403)
    account_reads = []
    position_reads = []
    def account(_params):
        account_reads.append(1)
        return {'id': 'other-uuid' if fault == 'account-flip' and len(account_reads) == 3 else 'audit-native-uuid',
                'account_number': 'OTHER' if fault == 'account-flip' and len(account_reads) == 3 else ACCOUNT}
    def positions(_params):
        position_reads.append(1)
        present = fault == 'foreign-position' or fault == 'position-flip' and len(position_reads) == 2
        return [{'symbol': 'AAPL', 'asset_id': 'asset-aapl', 'qty': '2'}] if present else []
    http = Httpx(routes={
        '/v2/account': account, '/v2/positions': positions,
        '/v2/orders': Response([full_order(client_order_id='foreign-human-order')]
                               if fault == 'foreign-order' else []),
    })
    b._inner._http_provider = lambda: http
    result = asyncio.run(reconcile.reconcile(
        broker=b, conn=conn, binding=B.load(conn), deployment=DEPLOY,
        informational_current_book=True))
    assert result.runtime_state in {
        RuntimeState.RECONCILING, RuntimeState.BROKER_DEGRADED, RuntimeState.FOREIGN_ACTIVITY}
    if fault.startswith('foreign'):
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
    assert all(call[0] == 'GET' for call in http.calls)
    assert not journal.load_commands(conn, DEPLOY)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_terminal_recovery_watermark').fetchone()[0] == 0
