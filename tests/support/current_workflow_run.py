"""Production PAPER callbacks, native notifications and durable HTTP projection."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from threading import Event, Thread
import time
import uuid

from sentinel import automation_runtime, binding, rolling_checkpoint, web_push
from sentinel.automation import store as automation_store, schedule, outbox
from sentinel.automation.model import ControlBinding, CycleContext, CycleSpec, CycleState, ExecuteDisposition
from sentinel.authority import load_rollout_state
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution import journal, target_reprojection
from sentinel.feed import normalized_layout, store
from tests.support.current_workflow_transport import NativeWorkflowAlpaca


@contextmanager
def live_lease(dsn,permit,config):
    """Use the real finite DB heartbeat while synchronous callbacks run."""
    stopped,errors = Event(),[]
    def heartbeat():
        conn = store.connect(dsn,connect_timeout=3,statement_timeout_ms=5000)
        try:
            while not stopped.wait(config.heartbeat_seconds):
                automation_store.heartbeat_lease(conn,permit=permit,lease_seconds=config.lease_seconds)
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()
    worker = Thread(target=heartbeat,name='isolated-workflow-lease',daemon=True)
    worker.start()
    try:
        yield
        assert not errors,errors
    finally:
        stopped.set()
        worker.join(timeout=10)
        assert not worker.is_alive()


def _assets(conn,published):
    candidate = published['candidate_id']
    day = conn.execute('SELECT window_end FROM sentinel_price_candidates WHERE candidate_id=%s',
                       (candidate,)).fetchone()[0]
    rows = conn.execute(normalized_layout.candidate_query(conn,
        'SELECT security_id,ticker,close_unadjusted FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND session=%s ORDER BY security_id'),(candidate,day)).fetchall()
    result = {ticker:{'id':sid,'security_id':sid,'symbol':ticker,'price':Decimal(str(price))}
              for sid,ticker,price in rows}
    defensive = conn.execute(normalized_layout.candidate_query(conn,
        'SELECT bil_close_unadjusted FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s'),
        (candidate,day)).fetchone()[0]
    result['BIL'] = {'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'isolated-current-asset:BIL')),
        'security_id':'SENTINEL:BIL','symbol':'BIL','price':Decimal(str(defensive))}
    return result


def _browser(conn):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from sentinel.panel.push_enrollment import _upsert_subscription
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    endpoint = 'https://isolated-push.invalid/device/current-workflow'
    p256dh,auth = web_push.b64url_encode(public),web_push.b64url_encode(b'current-workflow')
    web_push.validate_subscription(endpoint,p256dh,auth)
    with conn.cursor() as cur:
        identity = _upsert_subscription(cur,endpoint=endpoint,p256dh=p256dh,auth=auth,user_agent='isolated current browser')
    conn.commit()
    return identity


def _deliver(conn,config,dsn):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    credentials = web_push.VapidCredentials(private,public,'mailto:isolated@example.invalid')
    sent = []
    def sender(endpoint,body,headers,timeout):
        assert endpoint == 'https://isolated-push.invalid/device/current-workflow'
        assert isinstance(body,bytes) and body
        assert headers['Content-Encoding'] == 'aes128gcm'
        assert headers['Authorization'].startswith('vapid ')
        sent.append((body,dict(headers)))
        return 201
    adapter = web_push.WebPushAlertAdapter(connection_factory=lambda:store.connect(dsn),
        credentials=credentials,sender=sender)
    for _ in range(200):
        delivered = asyncio.run(outbox.dispatch_once(conn,adapter=adapter,holder_id='isolated-current-sender',
            claim_seconds=config.alert_claim_seconds))
        if delivered.alert is None:
            break
        assert delivered.delivered and not delivered.error,delivered
    else:
        raise AssertionError('finite notification dispatch did not converge')
    assert sent
    return sent


def _verification_and_http(conn,dsn,clock,cycle,monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from sentinel.panel import app, model, observer_codec, read_projection, verification_service
    from sentinel.panel import operational_schema as panel_schema
    owner = str(uuid.uuid4())
    assert conn.execute('SELECT pg_try_advisory_lock(%s,%s)',verification_service.OWNER_LOCK).fetchone()[0]
    conn.execute(f'INSERT INTO {panel_schema.OWNER} VALUES(1,%s,clock_timestamp()+INTERVAL \'610 seconds\') '
        'ON CONFLICT(id) DO UPDATE SET owner_id=EXCLUDED.owner_id,expires_at=EXCLUDED.expires_at',(owner,))
    conn.commit()
    expected_rows = {}
    for scope in ('SHADOW','PAPER'):
        key = read_projection.subject_for(dsn,scope=='PAPER')
        material = verification_service.observe(dsn,scope=='PAPER',key)
        expected = read_projection.PAPER_KEYS if scope=='PAPER' else read_projection.SHADOW_KEYS
        observer_codec.validate_envelope(material,expected)
        assert not material['errors'],material['errors']
        rows = [observer_codec.row_from_observation(raw) for raw in material['rows']]
        expected_rows.update({row.key:row for row in rows})
        value,signature = read_projection.make(scope,key,rows,[],observed_at=material['observed_at'])
        assert read_projection.subject(conn,dsn,scope)==key
        read_projection.publish(conn,owner_id=owner,value=value,signature=signature)
        conn.commit()
    current_rows,_,_,errors = read_projection.read(dsn,now=clock.now())
    assert not errors
    assert {row.key for row in current_rows} == read_projection.SHADOW_KEYS | read_projection.PAPER_KEYS
    assert expected_rows['shadow_verification'].status == model.OK
    assert expected_rows['paper_reconciliation'].status not in {model.UNKNOWN,model.FAIL}
    monkeypatch.setenv('SENTINEL_STATE_DIR',str(tmp_path/'state'))
    monkeypatch.setenv('SENTINEL_DATABASE_URL',dsn)
    with TestClient(app.app) as client:
        response = client.get('/panel.json')
        assert response.status_code==200,response.text
        payload = response.json()
        rows = {row['key']:row for row in payload['rows']}
        assert rows['shadow_verification']['status']==model.OK
        assert rows['paper_reconciliation']['status'] not in {model.UNKNOWN,model.FAIL}
        assert rows['book']['shadow_book'] is not None
        assert len(rows['book']['shadow_book']['slots'])==20
        # The business session is prospective while DB lease/mutation clocks
        # stay real. Production correctly keeps a future-dated run out of
        # Today's trading; its durable automation result is still displayed.
        assert rows['automation_cycle']['value']=='SUCCEEDED'
        assert cycle.cycle_id in rows['automation_cycle']['detail']
        assert cycle.last_clean_reconciliation_id in rows['automation_cycle']['detail']
        html = client.get('/')
        assert html.status_code==200 and html.headers['Cache-Control']=='no-store'
        assert 'Wealth Core' in html.text
    conn.execute('SELECT pg_advisory_unlock(%s,%s)',verification_service.OWNER_LOCK)
    conn.commit()


def paper_and_delivery(conn,published,clock,config,certificate,monkeypatch,tmp_path):
    """Single genuine signed-paper cycle; synthetic business clock only."""
    bound = binding.require(conn)
    rollout = load_rollout_state(conn)
    origin = rolling_checkpoint.read(conn).model_dump(by_alias=True)
    timing = schedule.for_decision_session(origin['session'],config)
    dsn = conn.info.dsn
    assets = _assets(conn,published)
    assert len(assets)>=501
    http = NativeWorkflowAlpaca(account=bound.broker_account_id,cash='50000',assets=assets,
        window=lambda:(timing.execution_open_at,timing.execution_close_at),
        forbid_quotes=True,marketable_limit_fills=True)
    _browser(conn)
    since = clock.now()-timedelta(minutes=1)
    monkeypatch.setenv('SENTINEL_FILL_NOTIFICATIONS_SINCE',since.isoformat())
    monkeypatch.setenv('SENTINEL_FEED_SERVICE_MODE','AUTOMATION')

    class Campaign(automation_runtime.ProductionAutomation):
        def _broker(self,reader,session):
            broker = super()._broker(reader,session)
            broker._http_provider = lambda:http
            broker._clock_provider = clock.now
            return broker
    campaign = Campaign(sentinel_config=SentinelConfig(database_url=dsn,alpaca_key='isolated',
        alpaca_secret='no-network',base_url=DEFAULT_BASE_URL,state_dir=tmp_path/'state',
        max_cycles=1,poll_seconds=0),automation_config=config,holder_id='isolated-current-worker')
    control = ControlBinding(deployment_id=bound.deployment_id,broker=bound.broker,
        broker_account_id=bound.broker_account_id,takeover_epoch=bound.takeover_epoch,
        certificate_sha256=certificate,rollout_mode=rollout.mode.value,
        rollout_version=rollout.version,config_sha256=config.fingerprint)
    automation_store.activate(conn,binding=control,actor='ISOLATED_QUALIFICATION',reason='genuinely signed current PAPER fixture')
    automation_store.release_kill(conn,expected_binding=control,actor='ISOLATED_QUALIFICATION',reason='external local transport only')
    permit = automation_store.acquire_lease(conn,holder_id=campaign.holder_id,lease_seconds=config.lease_seconds)
    spec = CycleSpec(**timing.model_dump(),**control.model_dump(),control_generation=permit.control_generation)
    cycle = automation_store.create_cycle(conn,permit=permit,spec=spec,now=clock.now(),config=config)
    conn.rollback()
    with live_lease(dsn,permit,config):
        def context():return CycleContext(cycle=cycle,permit=permit)
        def transition(state,**fields):
            return automation_store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=state,**fields)
        print('CURRENT_WORKFLOW preflight',flush=True)
        recovered = asyncio.run(campaign.recover(context()))
        assert recovered.disposition==ExecuteDisposition.SUCCEEDED,recovered
        assert recovered.last_clean_reconciliation_id
        cycle = transition(CycleState.REFRESHING_DATA)
        refreshed = asyncio.run(campaign.refresh(context()))
        assert refreshed.already_published
        cycle = transition(CycleState.PREPARING)
        print('CURRENT_WORKFLOW prepare',flush=True)
        prepared = asyncio.run(campaign.prepare(context()))
        cycle = transition(CycleState.PLAN_READY,plan_id=prepared.plan_id,plan_fingerprint=prepared.plan_fingerprint,
            state_fingerprint=prepared.state_fingerprint,data_version=prepared.data_version,
            publication_fingerprint=prepared.publication_fingerprint)
        plan = journal.latest_plan(conn)
        assert plan.plan_id == prepared.plan_id
        assert plan.target_basket and not http.orders
        from sentinel import paper_plan_preview
        wall_now,created_at = conn.execute('SELECT clock_timestamp(),created_at '
            'FROM sentinel_execution_plans WHERE plan_id=%s',(plan.plan_id,)).fetchone()
        # This composition fixture advances market time only. The database
        # keeps real creation/lease clocks, so a future synthetic observation
        # must be refused rather than made to look like a valid saved preview.
        if wall_now >= cycle.execute_at:
            assert paper_plan_preview.read(conn) is None
        elif clock.now() > created_at:
            import pytest
            with pytest.raises(ValueError,match='^original plan snapshot clock is inconsistent$'):
                paper_plan_preview.read(conn)
        else:
            preview = paper_plan_preview.read(conn)
            assert preview is not None and preview.plan_id==plan.plan_id
        conn.rollback()
        cycle = transition(CycleState.WAITING_OPEN)
        clock.instant = cycle.execute_at+timedelta(seconds=1)
        cycle = transition(CycleState.EXECUTING)
        http.started = time.monotonic()
        print('CURRENT_WORKFLOW execute',flush=True)
        execution = asyncio.run(campaign.execute(context()))
        assert execution.disposition==ExecuteDisposition.RECONCILE,execution
        cycle = transition(CycleState.RECONCILING)
        for _ in range(10):
            print('CURRENT_WORKFLOW recover',flush=True)
            recovered = asyncio.run(campaign.recover(context()))
            if recovered.disposition==ExecuteDisposition.SUCCEEDED:
                break
            assert recovered.disposition in {ExecuteDisposition.READY_TO_EXECUTE,ExecuteDisposition.RECONCILE},recovered
            if recovered.disposition==ExecuteDisposition.READY_TO_EXECUTE:
                cycle = transition(CycleState.RETRY_WAIT,diagnostic={'retry_phase':'EXECUTE'})
                cycle = transition(CycleState.EXECUTING)
                execution = asyncio.run(campaign.execute(context()))
                assert execution.disposition==ExecuteDisposition.RECONCILE,execution
                cycle = transition(CycleState.RECONCILING)
        else:
            raise AssertionError('bounded production recovery did not converge')
        assert recovered.last_clean_reconciliation_id
        cycle = transition(CycleState.SUCCEEDED,last_clean_reconciliation_id=recovered.last_clean_reconciliation_id)
        projection = target_reprojection.load_projection(conn,plan_id=plan.plan_id)
        assert projection is not None
        expected = {sid:quantity for sid,quantity in projection.target_basket.items() if quantity}
        actual = {http.by_id[asset]['security_id']:quantity for asset,quantity in http.positions.items() if quantity}
        assert actual==expected and actual
        commands = journal.load_commands(conn,bound.identity,plan_id=plan.plan_id)
        assert commands and len(commands)==len(http.orders)
        assert all(command.state.value=='FILLED' for command in commands)
        assert all(order['type']=='limit' and order['time_in_force']=='day' for order in http.orders.values())
        assert not http.requests['GET /v2/stocks/quotes/latest']
        assert rolling_checkpoint.read(conn).model_dump(by_alias=True)==origin
        conn.rollback()
        print('CURRENT_WORKFLOW collector',flush=True)
        from sentinel import execution_collector
        reader = campaign._broker(conn,cycle.effective_session.isoformat())
        conn.rollback()
        assert execution_collector.collect_once('ACCOUNT',reader=reader,config=campaign.sentinel_config)=='COLLECTED'
        for _ in range(20):
            before = conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0]
            conn.rollback()
            outcome = execution_collector.collect_once('FILL',reader=reader,config=campaign.sentinel_config)
            refusal = conn.execute("SELECT payload FROM sentinel_alert_outbox "
                "WHERE event_type='FILL_NOTIFICATION_COLLECTION_FAILED' ORDER BY created_at DESC LIMIT 1").fetchone()
            conn.rollback()
            assert outcome=='COLLECTED', (outcome,refusal)
            after = conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0]
            conn.rollback()
            if after==before:break
        else:
            raise AssertionError('bounded native fill collection did not converge')
        fills = conn.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchall()
        assert len(fills)==len(http.orders)
        assert all(row[0]['source']=='ALPACA_ORDER_ACTIVITIES_V1' and row[0]['notification_only'] for row in fills)
        conn.rollback()
        sent = _deliver(conn,config,dsn)
        assert len(sent)>=len(http.orders)
        receipts = conn.execute("SELECT a.state,d.state,d.last_status_code FROM sentinel_alert_outbox a "
            'JOIN sentinel_web_push_deliveries d USING(alert_id) WHERE a.event_type=\'BROKER_FILL\'').fetchall()
        assert len(receipts)==len(http.orders)
        assert all(row==('DELIVERED','DELIVERED',201) for row in receipts)
        conn.rollback()
        print('CURRENT_WORKFLOW verifier + HTTP',flush=True)
        clock.follow_wall()
        assert execution_collector.collect_once('ACCOUNT',reader=reader,
            config=campaign.sentinel_config)=='COLLECTED'
        _verification_and_http(conn,dsn,clock,cycle,monkeypatch,tmp_path)
        assert rolling_checkpoint.read(conn).model_dump(by_alias=True)==origin
        conn.rollback()
    automation_store.release_lease(conn,permit=permit)
