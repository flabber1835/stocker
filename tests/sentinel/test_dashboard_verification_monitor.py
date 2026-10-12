"""Independent scopes, browser-free refresh, finite ownership and falsifiers."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from threading import BoundedSemaphore, Lock
import time

import pytest

from sentinel.panel import authority_reader as reader, verification_monitor as monitoring, model
from sentinel import receipt_authentication
from tests.sentinel.test_supervisor_dependency_bounds import pg, conn


def answer(paper=False, at=None):
    rows = ([model.paper_reconciliation_row(state='PENDING')] if paper else [
        model.shadow_verification_row(verdict='SHADOW_GO', verification='VERIFIED', session='2026-10-09'),
        model.shadow_metric_row('shadow_nav', 'NAV', '$50,575.09', verified=True, detail='verified'),
        model.shadow_metric_row('shadow_return', 'Return', '+1.15%', verified=True, detail='verified'),
        *[model.Row(key,key,'verified',model.OK) for key in ('exposure','book','terminals')]])
    return {'rows':[asdict(row) for row in rows], 'errors':[],
            'observed_at':at or datetime.now(timezone.utc)}


def wait(predicate):
    end=time.monotonic()+3
    while time.monotonic()<end:
        if predicate(): return
        time.sleep(.005)
    assert predicate(), 'owned monitor did not progress'


def test_monitor_refreshes_several_lifetimes_without_http_and_serializes_jobs(monkeypatch):
    clock=[0.0]; origin=datetime.now(timezone.utc); calls=[]; active=[0]; peak=[0]; lock=Lock()
    monkeypatch.setattr(reader,'_evidence',lambda *a:'f'*64)
    monkeypatch.setattr(monitoring,'shadow_evidence',lambda *a:'e'*64)
    def run(fn,*args,**kwargs):
        with lock: active[0]+=1; peak[0]=max(peak[0],active[0])
        try:
            time.sleep(.01)
            calls.append((fn,clock[0]))
            return answer(fn is monitoring.observe_paper,origin+timedelta(seconds=clock[0]))
        finally:
            with lock: active[0]-=1
    def factory(**kwargs):
        return reader.Reader(runner=run,clock=lambda:clock[0],
            wall_clock=lambda:origin+timedelta(seconds=clock[0]),**kwargs)
    monitor=monitoring.Monitor(reader_factory=factory,interval=.005)
    try:
        monitor.start('fixture')
        wait(lambda:monitor.shadow.completed is not None and monitor.paper.completed is not None)
        first=monitor.shadow.completed[2]
        # Only the background monitor consumes answers. No browser reads occur.
        for turn in range(1,5):
            clock[0]=turn*reader.REFRESH_SECONDS
            wait(lambda:monitor.shadow.completed is not None and monitor.shadow.completed[2]>first)
            first=monitor.shadow.completed[2]
        assert peak[0]==1
        assert len([x for x in calls if x[0] is monitoring.observe_shadow])>=5
        rows,_,_,errors=monitor.read('fixture')
        assert not errors and rows[0].status==model.OK
        assert rows[1].value=='$50,575.09' and rows[0].as_of==first
        assert monitor.read('different-database') is None
    finally: monitor.stop()
    assert not monitor.thread.is_alive() and monitor.read('fixture') is None


def test_shadow_identity_excludes_control_polling_on_actual_postgres(conn,monkeypatch):
    from sentinel import schema
    from sentinel.feed import store
    schema.ensure_schema(conn); store.migrate_schema(conn)
    dsn=conn.info.dsn
    before=monitoring.shadow_evidence(dsn)
    paper=reader._evidence(dsn,True)
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1');conn.commit()
    assert monitoring.shadow_evidence(dsn)==before
    assert reader._evidence(dsn,True)!=paper
    from sentinel import informational_paper_mirror
    paper=reader._evidence(dsn,True)
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)',
        (informational_paper_mirror.CURSOR_PREFIX+'qualification','2026-10-09','{}'));conn.commit()
    assert monitoring.shadow_evidence(dsn)==before
    assert reader._evidence(dsn,True)!=paper
    # A real annotation dependency still invalidates independent shadow proof.
    conn.execute("UPDATE sentinel_rollout_state SET version=version+1 WHERE id=1");conn.commit()
    assert monitoring.shadow_evidence(dsn)!=before


def test_reintroducing_combined_key_fails_independence(conn,monkeypatch):
    monkeypatch.setattr(monitoring,'shadow_evidence',lambda d,*a:reader._evidence(d,True))
    with pytest.raises(AssertionError):
        test_shadow_identity_excludes_control_polling_on_actual_postgres(conn,monkeypatch)


@pytest.mark.parametrize('owner,constant,exact',[
    ('sentinel.informational_paper_mirror','CURSOR_PREFIX',False),
    ('sentinel.execution.alpaca','_OBSERVATION_PREFIX',False),
    ('sentinel.execution.alpaca','_WITNESS_PREFIX',False),
    ('sentinel.execution.alpaca','_DB_INCARCERATION_CURSOR',True),
    ('sentinel.execution.broker_cash','ACTIVITY_CURSOR_PREFIX',False),
    ('sentinel.execution.broker_cash','PLAN_BASELINE_PREFIX',False),
    ('sentinel.execution.preopen_authority','CURSOR_PREFIX',False),
    ('sentinel.execution.target_reprojection','CURSOR_PREFIX',False),
    ('sentinel.dual_reconciliation','REGENESIS_HANDOVER_PREFIX',False),
    ('sentinel.trial','ACCOUNT_PREFIX',False),
    ('sentinel.trial','VERIFICATION_PREFIX',False),
    ('sentinel.trial_fills','FILL_INTERVAL_PREFIX',False),
    ('sentinel.trial_close','TRIAL_CLOSE_NAV_PREFIX',False),
    ('sentinel.paper_performance','PREFIX',False),
])
def test_actual_broker_owned_cursors_never_reset_shadow_proof(conn,owner,constant,exact):
    import importlib
    from sentinel import schema
    from sentinel.feed import store
    namespace=getattr(importlib.import_module(owner),constant)
    assert namespace in (reader.PAPER_CURSOR_NAMES if exact else reader.PAPER_CURSOR_PREFIXES)
    schema.ensure_schema(conn);store.migrate_schema(conn)
    dsn=conn.info.dsn;before=monitoring.shadow_evidence(dsn);paper=reader._evidence(dsn,True)
    cursor=namespace if exact else namespace+'qualification'
    for state in ('{}','{"updated":true}'):
        conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb) '
            'ON CONFLICT(cursor_name) DO UPDATE SET state=EXCLUDED.state',
            (cursor,'2026-10-09',state));conn.commit()
        assert monitoring.shadow_evidence(dsn)==before
        latest=reader._evidence(dsn,True);assert latest!=paper;paper=latest
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('unrecognized-economic-cursor','2026-10-09','{}')");conn.commit()
    assert monitoring.shadow_evidence(dsn)!=before


def test_removing_broker_namespace_partition_fails_independence(conn,monkeypatch):
    monkeypatch.setattr(monitoring,'shadow_evidence',lambda d,*a:reader._evidence(d,True))
    with pytest.raises(AssertionError):
        test_actual_broker_owned_cursors_never_reset_shadow_proof(
            conn,'sentinel.execution.alpaca','_OBSERVATION_PREFIX',False)


def test_queued_work_is_finite_and_cannot_extend_proof(monkeypatch):
    monkeypatch.setattr(reader,'_evidence',lambda *a:'f'*64)
    origin=datetime.now(timezone.utc); clock=[0.0]; slot=BoundedSemaphore(1);slot.acquire()
    value=reader.Reader(runner=lambda *a,**k:answer(False,origin),execution_slot=slot,
        clock=lambda:clock[0],wall_clock=lambda:origin+timedelta(seconds=clock[0]))
    try:
        rows=value.read('fixture',include_paper=False)[0]
        assert rows[0].status==model.WARN and 'queued' in rows[0].detail
        assert rows[0].recovery.deadline==origin+timedelta(seconds=reader.DEADLINE_SECONDS)
        clock[0]=reader.DEADLINE_SECONDS
        rows=value.read('fixture',include_paper=False)[0]
        assert rows[0].status in {model.UNKNOWN,model.FAIL}
    finally:
        slot.release();wait(lambda:value.pending is None)
    clock[0]=reader.FRESH_SECONDS+1
    rows=value.read('fixture',include_paper=False,allow_start=False)[0]
    assert rows[0].status!=model.OK


def test_paper_failure_cannot_erase_independent_verified_shadow(monkeypatch):
    monkeypatch.setattr(reader,'_evidence',lambda *a:'f'*64)
    shadow=reader.Reader(runner=lambda *a,**k:answer(False))
    bad=answer(True);bad['rows'][0]=asdict(model.paper_reconciliation_row(state='MISMATCH',detail='actual mismatch'))
    paper=reader.Reader(runner=lambda *a,**k:bad,expected_keys=frozenset({'paper_reconciliation'}),
        unknown_factory=monitoring.paper_unknown)
    shadow.read('fixture',include_paper=False);paper.read('fixture')
    wait(lambda:shadow.pending is None and paper.pending is None)
    assert shadow.read('fixture',include_paper=False)[0][0].status==model.OK
    assert paper.read('fixture')[0][0].status==model.FAIL


@pytest.mark.parametrize('payload',[{}, {'purpose':'worker','nested':{'value':1}},
                                  {'value':Decimal('1.23')}, {'value':'Unicode £'}])
def test_light_signature_matches_existing_canonical_bytes(monkeypatch,payload):
    from sentinel.feed import publication
    secret='qualification-secret-with-at-least-32-bytes'
    monkeypatch.setenv(receipt_authentication.KEY_ENV,'  '+secret+'  ')
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode()
    expected=hmac.new(secret.encode(),encoded,hashlib.sha256).hexdigest()
    assert receipt_authentication.sign(payload)==publication._receipt_hmac(payload)==expected


def test_light_signature_refuses_missing_key(monkeypatch):
    from sentinel.feed import publication
    monkeypatch.delenv(receipt_authentication.KEY_ENV,raising=False)
    with pytest.raises(receipt_authentication.ReceiptKeyUnavailable): receipt_authentication.sign({})
    with pytest.raises(publication.CorpusIncoherent): publication._receipt_hmac({})


def test_worker_signature_does_not_import_the_feed_stack():
    import subprocess,sys
    code="""import sys,os
os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY']='qualification-secret-with-at-least-32-bytes'
from sentinel.shadow_service_status import _signature
_signature({'state':'RUNNING'})
assert 'sentinel.feed.publication' not in sys.modules
assert 'numpy' not in sys.modules
"""
    subprocess.run([sys.executable,'-c',code],check=True,timeout=10)


def test_finite_probe_does_not_import_producer_or_schema_stack():
    import subprocess,sys
    code="""import sys
from sentinel import shadow_service_probe
assert 'pydantic' not in sys.modules
assert 'sentinel.shadow_service_status' not in sys.modules
assert 'sentinel.feed.publication' not in sys.modules
"""
    subprocess.run([sys.executable,'-c',code],check=True,timeout=10)


@pytest.mark.parametrize('damage',['shape','type','oversize'])
def test_unvalidated_probe_frame_cannot_become_current(damage):
    from sentinel import shadow_service_status
    snapshot=dict(critical=False,pending=None,status=b'{}',latest_pending=None)
    if damage=='shape': snapshot['extra']=True
    elif damage=='type': snapshot['critical']='false'
    else: snapshot['status']=b'x'*(shadow_service_status.MAX_BYTES+1)
    with pytest.raises(ValueError,match='snapshot is malformed'):
        shadow_service_status.decode_probe(snapshot,'qualification')


def test_awaiting_monitor_has_original_finite_clock_and_rejects_rollback(monkeypatch):
    monkeypatch.setattr(reader,'_evidence',lambda *a:'f'*64)
    now=datetime.now(timezone.utc)
    value=reader.Reader(wall_clock=lambda:now)
    for clock,expected in ((now,model.WARN),(now-timedelta(seconds=1),model.UNKNOWN),
                           (now+timedelta(seconds=61),model.UNKNOWN)):
        value.wall_clock=lambda:clock
        row=value.read('fixture',allow_start=False,awaiting_since=now,
                       awaiting_until=now+timedelta(seconds=60))[0][0]
        assert row.status==expected


def test_lifespan_starts_monitor_before_any_browser_request(monkeypatch):
    import asyncio
    from sentinel.panel import app
    calls=[]
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setattr(app,'_config',lambda:(None,'fixture'))
    monkeypatch.setattr(monitoring.monitor,'start',lambda d,**k:calls.append((d,k)))
    monkeypatch.setattr(monitoring.monitor,'stop',lambda:calls.append('stopped'))
    async def exercise():
        async with app._verification_lifespan(app.app):
            assert calls==[('fixture',{'include_paper':True})]
    asyncio.run(exercise())
    assert calls[-1]=='stopped'


def test_progress_and_last_success_are_visible_without_opening_details():
    from sentinel.panel.render import render
    from tests.sentinel.test_shadow_worker_monitoring import Visible
    now=datetime.now(timezone.utc)
    rows=reader._unknown(False,'retained portfolio verification · elapsed 12s · deadline '+now.isoformat(),
                         checking_until=now+timedelta(seconds=30))[0]
    html=render(model.Panel(rows=rows,now=now))
    visible=Visible();visible.feed(html.split('<script>',1)[0])
    assert 'elapsed 12s' in ''.join(visible.parts)
