"""Durable callback context and fork-safe ownership in the attended profile."""
import asyncio
from contextlib import contextmanager
import hashlib
import inspect
import textwrap
from types import MethodType,SimpleNamespace

import pytest

from tools import paper_service_rehearsal as module
from tools.live_paper_rehearsal import AttendedRun,Refused


def test_saved_system_campaign_resumes_through_production_source_factory(tmp_path,monkeypatch):
    import json
    from datetime import date
    from decimal import Decimal
    from tools import system_paper_rehearsal as system
    saved=dict(complete=False,plan={'plan_id':'saved'},plan_fingerprint='fingerprint',
        tickers={'permanent-class':'PBR.A'})
    (tmp_path/'system-plan.json').write_text(json.dumps(saved))
    trace=[]
    @contextmanager
    def connect():yield object()
    run=SimpleNamespace(deployment_id='test-run',connect=connect,
        acquire_owner=lambda:trace.append('owner'),production_fenced=lambda:trace.append('fenced'))
    monkeypatch.setattr(system,'NativeRun',lambda **_:run)
    plan=SimpleNamespace(plan_id='saved',deployment_id='test-run',
        effective_session=date(2026,10,16),fingerprint=lambda:'fingerprint')
    monkeypatch.setattr(system.journal,'load_plan',lambda *_:plan)
    class Connection:
        def execute(self,sql):trace.append(sql)
    source=Connection()
    @contextmanager
    def source_connect(dsn,*,statement_timeout_ms):
        assert dsn=='authenticated-source' and statement_timeout_ms==90000;yield source
    monkeypatch.setattr(system.store,'connect',source_connect)
    monkeypatch.setenv('REHEARSAL_DATABASE_URL','authenticated-source')
    class ReachedProductionFactory(Exception):pass
    def factory(owner,connection,session):
        assert owner is run and connection is source and session==plan.effective_session
        assert trace==['owner','fenced','SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY']
        raise ReachedProductionFactory()
    monkeypatch.setattr(system,'production_broker',factory)
    args=SimpleNamespace(output=tmp_path,account_sha256='fixture',maximum_open_usd=Decimal(5000))
    with pytest.raises(ReachedProductionFactory):asyncio.run(system.main_async(args))


def test_fresh_callback_reloads_durable_order_ownership(tmp_path,monkeypatch):
    import json
    path=tmp_path/'plan.json'
    path.write_text(json.dumps({'plan':{'plan_id':'plan','fingerprint':'hash'},
        'instruments':{'s':dict(security_id='s',symbol='AAA',broker_id='asset')}}))
    campaign=object.__new__(module.ServiceCampaign)
    campaign.path=path
    @contextmanager
    def connect():yield object()
    campaign.run=SimpleNamespace(connect=connect,deployment_id='test-run',keys=set(),ids=set())
    plan=SimpleNamespace(deployment_id='test-run',fingerprint=lambda:'hash')
    monkeypatch.setattr(module.journal,'load_plan',lambda *_:plan)
    monkeypatch.setattr(module.binding,'require',lambda _:SimpleNamespace(identity='bound'))
    monkeypatch.setattr(module.journal,'load_commands',lambda *_:[SimpleNamespace(client_key='owned',broker_order_id='native-order')])
    campaign.load_durable_plan()
    assert campaign.run.keys=={'owned'} and campaign.run.ids=={'native-order'}
    assert campaign.run.allowed_symbols=={'AAA','SPY'}


@pytest.mark.parametrize('damage',[None,'stale','closed'])
def test_rehearsal_quotes_use_actual_endpoint_and_canonical_parser(monkeypatch,damage):
    from datetime import datetime,timedelta,timezone
    from decimal import Decimal
    import httpx
    from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.execution.opening_prices import OpeningPriceUnavailable
    from tools.native_paper_rehearsal import RehearsalAlpacaBroker
    monkeypatch.setenv('ALPACA_API_KEY','synthetic')
    monkeypatch.setenv('ALPACA_SECRET_KEY','synthetic')
    instant=datetime(2026,10,15,17,30,tzinfo=timezone.utc)
    quoted=instant-timedelta(seconds=61 if damage=='stale' else 1)
    if damage=='closed':instant=instant.replace(hour=20,minute=0)
    calls=[]
    def response(request):
        calls.append(str(request.url))
        assert request.url.host=='data.alpaca.markets'
        assert request.url.params['feed']=='iex' and request.url.params['symbols']=='AAA'
        return httpx.Response(200,json={'quotes':{'AAA':dict(ap=101,bp=100,**{'as':10,'bs':10},t=quoted.isoformat())}})
    client=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(response),**kw))
    run=SimpleNamespace(production_fenced=lambda:None,provider=lambda:httpx)
    broker=RehearsalAlpacaBroker(run)
    broker._clock_provider=lambda:instant
    item=BrokerInstrument('security','AAA','asset')
    if damage:
        with pytest.raises((Refused,OpeningPriceUnavailable)):
            asyncio.run(broker.opening_prices(session=instant.date(),instruments={'security':item}))
        if damage=='closed':assert not calls
    else:
        quote=asyncio.run(broker.opening_prices(session=instant.date(),instruments={'security':item}))
        assert quote.prices=={'security':Decimal(101)} and quote.broker_ids=={'security':'asset'}
        production=AssetIdAlpacaExecutionBroker(api_key='synthetic',secret_key='synthetic',
            base_url='https://paper-api.alpaca.markets',clock_provider=lambda:instant)
        with pytest.raises(OpeningPriceUnavailable,match='expired'):
            asyncio.run(production.opening_prices(session=instant.date(),instruments={'security':item}))


@pytest.mark.parametrize('remove_guard',[False,True])
def test_missing_post_prepare_plan_never_certifies_an_empty_account(monkeypatch,remove_guard):
    campaign=object.__new__(module.ServiceCampaign)
    @contextmanager
    def connect():yield object()
    campaign.run=SimpleNamespace(production_fenced=lambda:None,connect=connect)
    campaign.plan=None
    campaign.broker=object()
    campaign.load_durable_plan=lambda:None
    context=SimpleNamespace(require_active=lambda:None,cycle=SimpleNamespace(plan_id='prepared-plan'))
    monkeypatch.setattr(module.binding,'require',lambda _:SimpleNamespace(identity='bound'))
    @contextmanager
    def writer(*_a,**_k):yield
    monkeypatch.setattr(module.journal,'writer_lock',writer)
    monkeypatch.setattr(module.journal,'in_flight_commands',lambda *_:[])
    async def reconcile(**_):
        return SimpleNamespace(transport_ready=True,observation=SimpleNamespace(positions_by_security=lambda:{}),
            observation_id=1,to_dict=lambda:{})
    monkeypatch.setattr(module.reconcile,'reconcile',reconcile)
    if remove_guard:
        source=textwrap.dedent(inspect.getsource(module.ServiceCampaign.recover))
        changed=source.replace('if context.cycle.plan_id and (self.plan is None or self.plan.plan_id!=context.cycle.plan_id):',
            'if False:')
        assert changed!=source
        namespace=dict(vars(module));exec(changed,namespace)
        campaign.recover=MethodType(namespace['recover'],campaign)
        assert asyncio.run(campaign.recover(context)).disposition is module.ExecuteDisposition.SUCCEEDED
    else:
        with pytest.raises(Refused,match='exact durable'):asyncio.run(campaign.recover(context))


@pytest.mark.parametrize('owner_present',[False,True])
def test_forked_callback_uses_a_fresh_exact_parent_owner_check(monkeypatch,owner_present):
    import tools.live_paper_rehearsal as live
    run=object.__new__(AttendedRun)
    account='synthetic-paper'
    run.account_sha256=hashlib.sha256(account.encode()).hexdigest()
    run.owner_process_id=-1
    run.owner_backend_pid=101
    run.owner_backend_start='2026-10-15T17:00:00+00:00'
    run.owner_key=(1<<40)+123
    class InheritedConnection:
        def execute(self,*_):pytest.fail('fork used the inherited psycopg connection')
    run.owner_connection=InheritedConnection()
    checked=[]
    class Fresh:
        def execute(self,sql,params=()):
            if sql.startswith('SELECT EXISTS'):
                checked.append(params)
            return self
        def fetchone(self):return (owner_present,)
        def fetchall(self):return [(False,True,'alpaca',account)]
        def close(self):pass
        def rollback(self):pass
    monkeypatch.setenv('REHEARSAL_PRODUCTION_DATABASE_URL','synthetic-only')
    monkeypatch.setattr(live.store,'connect',lambda *_a,**_k:Fresh())
    if owner_present:run.production_fenced()
    else:
        with pytest.raises(Refused,match='parent attended'):run.production_fenced()
    assert checked==[(101,run.owner_backend_start,256,123)]
