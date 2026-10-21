"""Independent scopes, browser-free refresh, finite ownership and falsifiers."""
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
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
import ast
import inspect
from types import SimpleNamespace

from sentinel.automation import health
from sentinel.execution import journal
from sentinel.execution.plan import ExecutionPlan
from sentinel.panel import authority_reader, sources, verification_monitor


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


NOW = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)
EXECUTE = NOW + timedelta(minutes=1)
CERTIFICATE = "a" * 64


class Connection:
    def __init__(self, binding=(CERTIFICATE, False, True)):
        self.binding = binding
        self.statements = []
        self.closed = False
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, query, params=None):
        self.statements.append((query, params))
    def fetchone(self):
        return self.binding
    def rollback(self):
        pass
    def close(self):
        self.closed = True


@pytest.fixture
def ready(monkeypatch):
    plan = ExecutionPlan(plan_id="current-plan", decision_session=date(2026, 10, 20),
        effective_session=date(2026, 10, 21), target_exposure=Decimal("1"), data_version=7,
        rollout_mode="CONTROLLER", rollout_version=4, rollout_certificate_sha256=CERTIFICATE)
    cycle = dict(cycle_id="current-cycle", state="WAITING_OPEN", execute_at=EXECUTE,
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        decision_session="2026-10-20", effective_session="2026-10-21")
    current = SimpleNamespace(healthy=True, operational_ready=True, enabled=True,
        kill_switch_engaged=False, policy_state="LEADER_ACTIVE", authority_verdict="PASS",
        authority_lifecycle_current=True, broker_outcome_unresolved=0,
        latest_cycle_id=cycle["cycle_id"], latest_cycle_state="WAITING_OPEN",
        certificate_sha256=CERTIFICATE, rollout_mode="CONTROLLER", rollout_version=4,
        control_generation=12)
    rollout = dict(mode="CONTROLLER", version=4, certificate_sha256=CERTIFICATE)
    monkeypatch.setattr(health, "read_health", lambda conn: current)
    monkeypatch.setattr(journal, "latest_plan", lambda conn: plan)
    monkeypatch.setattr(sources, "_rollout_state", lambda conn: rollout)
    return SimpleNamespace(plan=plan, cycle=cycle, health=current, rollout=rollout,
        publication=SimpleNamespace(version=7), connection=Connection())


def scheduled(ready, *, now=NOW):
    return sources._scheduled_preopen_mirror(ready.connection, ready.cycle,
        ready.publication, "2026-10-20", now=now)


def test_ready_preopen_is_green_but_never_claims_mirror_clean(ready):
    row = scheduled(ready)
    assert row.status == model.OK and "SCHEDULED" in row.value
    assert "NOT VERIFIED" in row.value and "PENDING" in row.value
    assert "CLEAN" not in row.value and row.required_current
    assert model.Panel(rows=[row], now=NOW).operational == model.OK
    assert row.effective_status(EXECUTE) == model.FAIL
    assert row.effective_status(EXECUTE + timedelta(seconds=1)) == model.FAIL
    # A scheduled mirror never conceals another required failure.
    assert model.Panel(rows=[row, model.Row("authority", "Authority", "bad", model.FAIL)], now=NOW).operational == model.FAIL


@pytest.mark.parametrize("field,value", [
    ("state", "PLAN_READY"), ("state", "EXECUTING"), ("state", "BLOCKED"),
    ("execute_at", NOW), ("execute_at", NOW-timedelta(seconds=1)),
    ("failure_code", "BLOCKED"), ("failure_detail", "failure"), ("terminal_reason", "operator"),
    ("cycle_id", "historical-cycle"), ("plan_id", "old-plan"),
    ("plan_fingerprint", "b"*64), ("decision_session", "2026-10-19"),
    ("effective_session", "2026-10-22"),
])
def test_not_ready_or_different_cycle_cannot_be_scheduled(ready, field, value):
    ready.cycle[field] = value
    assert scheduled(ready) is None


@pytest.mark.parametrize("field,value", [
    ("healthy", False), ("operational_ready", False), ("enabled", False),
    ("kill_switch_engaged", True), ("policy_state", "SCHEDULER_STALLED"),
    ("authority_verdict", "FAIL"), ("authority_lifecycle_current", False),
    ("broker_outcome_unresolved", 1), ("latest_cycle_state", "BLOCKED"),
    ("certificate_sha256", "b"*64), ("rollout_mode", "PINNED_1_00"), ("rollout_version", 3),
])
def test_current_native_health_is_required(ready, field, value):
    setattr(ready.health, field, value)
    assert scheduled(ready) is None


@pytest.mark.parametrize("binding", [(CERTIFICATE, False, False), (CERTIFICATE, True, True),
    ("b"*64, False, True), None])
def test_current_generation_nonhistorical_certificate_binding_required(ready, binding):
    ready.connection.binding = binding
    assert scheduled(ready) is None


def test_current_publication_and_rollout_required(ready):
    ready.publication.version = 8
    assert scheduled(ready) is None
    ready.publication.version = 7
    ready.rollout["certificate_sha256"] = "b"*64
    assert scheduled(ready) is None


def test_observer_and_cached_reader_preserve_execution_boundary(ready, monkeypatch):
    from sentinel import informational_paper_mirror as mirror
    from sentinel.feed import readers, store
    monkeypatch.setattr(sources, "_informational_mirror_count", lambda conn: 1)
    monkeypatch.setattr(sources, "_latest_automation_cycle", lambda conn: ready.cycle)
    monkeypatch.setattr(readers, "current", lambda conn: ready.publication)
    monkeypatch.setattr(readers, "frontier", lambda *args: "2026-10-20")
    monkeypatch.setattr(mirror, "require_transport_permitted", lambda *args, **kw: {"status": mirror.NO_UNIT_CHANGE})
    monkeypatch.setattr(mirror, "require_current_plan_status", lambda *args, **kw: {"status": mirror.PENDING})
    monkeypatch.setattr(store, "connect", lambda *args, **kw: ready.connection)
    monkeypatch.setattr(authority_reader, "_evidence", lambda *args: "evidence")
    monkeypatch.setattr(authority_reader, "_key", lambda *args: "expected")
    class ClockType(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)
    class Fixed(datetime, metaclass=ClockType):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(sources, "datetime", Fixed)
    monkeypatch.setattr(verification_monitor, "datetime", Fixed)
    answer = verification_monitor.observe_paper("fixture", True, "expected")
    assert answer["rows"][0]["status"] == model.OK
    assert ready.connection.closed
    assert ready.connection.statements[0][0] == "BEGIN TRANSACTION READ ONLY"
    wall = [NOW]
    reader = authority_reader.Reader(runner=lambda *args, **kw: answer,
        evidence_reader=lambda *args: "evidence", wall_clock=lambda: wall[0],
        expected_keys=frozenset({"paper_reconciliation"}))
    try:
        reader.read("fixture")
        deadline = time.monotonic()+3
        while reader.pending is not None and time.monotonic() < deadline:
            reader.read("fixture"); time.sleep(.005)
        rows = reader.read("fixture", allow_start=False)[0]
        assert rows[0].effective_status(NOW) == model.OK
        wall[0] = EXECUTE
        rows = reader.read("fixture", allow_start=False)[0]
        assert rows[0].valid_until == EXECUTE-timedelta(microseconds=1)
        assert rows[0].effective_status(EXECUTE) == model.FAIL
        # Removing the current pending stamp preserves the old warning.
        monkeypatch.setattr(mirror, "require_current_plan_status", lambda *args, **kw: (_ for _ in ()).throw(mirror.InformationalPaperMirrorUnstamped("missing")))
        row = sources._dual_paper_row(ready.connection, informational_paper_mirror=mirror,
            publication=readers, feed_store=store)
        assert row.status == model.WARN and "PENDING" in row.value
    finally:
        if reader.pending is not None:
            reader.pending.join(timeout=2)


def test_removing_generation_guard_breaks_its_falsifier(ready, monkeypatch):
    tree = ast.parse(inspect.getsource(sources._scheduled_preopen_mirror))
    removed = 0
    class Remove(ast.NodeTransformer):
        def visit_If(self, node):
            nonlocal removed
            if ast.unparse(node.test) == "binding != (certificate, False, True)":
                removed += 1
                return None
            return self.generic_visit(node)
    tree = Remove().visit(tree)
    assert removed == 1
    namespace = dict(sources.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<removed generation guard>", "exec"), namespace)
    monkeypatch.setattr(sources, "_scheduled_preopen_mirror", namespace["_scheduled_preopen_mirror"])
    with pytest.raises(AssertionError):
        test_current_generation_nonhistorical_certificate_binding_required(ready, (CERTIFICATE, False, False))


def test_removing_execution_boundary_breaks_composed_falsifier(ready, monkeypatch):
    tree = ast.parse(inspect.getsource(model.paper_reconciliation_row))
    removed = 0
    class Remove(ast.NodeTransformer):
        def visit_keyword(self, node):
            nonlocal removed
            if node.arg == "valid_until":
                removed += 1
                return None
            return self.generic_visit(node)
    tree = Remove().visit(tree)
    assert removed == 1
    namespace = dict(model.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<removed execution boundary>", "exec"), namespace)
    monkeypatch.setattr(model, "paper_reconciliation_row", namespace["paper_reconciliation_row"])
    with pytest.raises(AssertionError):
        test_observer_and_cached_reader_preserve_execution_boundary(ready, monkeypatch)


def test_protected_successor_preserves_exact_predecessor_and_bounded_debug_sources():
    import hashlib
    import json
    from pathlib import Path
    from sentinel import protected_cohort_upgrade as upgrade
    profile = upgrade.profile()
    predecessor_path = upgrade.PROFILE.with_name("protected-cohort-runtime-debug-predecessor.json")
    raw = predecessor_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "f295a701502e0c22dfc591dc378f7fff54407219619dcae3c4584af3aefcb003"
    assert upgrade.RETAINED_PROFILES[predecessor_path.name] == hashlib.sha256(raw).hexdigest()
    old = json.loads(raw)
    added = {"automation/integrity.py", "automation/schedule.py", "automation/store.py",
             "execution/guarded.py",
             "execution/protected_limits.py", "paper/validation.py"}
    assert len(old["files"]) == 23
    assert set(profile["files"]) == set(old["files"]) | added
    changed = {name for name in old["files"]
               if profile["files"][name]["after"] != old["files"][name]["after"]}
    assert changed == {"automation/model.py", "automation/service.py",
                       "automation_runtime.py", "paper/execution.py"}
    for name, record in profile["files"].items():
        actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
        assert record["after"] == actual
        previous = old["files"][name]["after"] if name in old["files"] else upgrade.BASE_FILES[name]
        if name in old["files"]:
            assert set(old["files"][name]["before"]) | {previous} <= set(record["before"])
        assert upgrade.source_allowed(name, previous, actual)
        assert not upgrade.source_allowed(name, previous, "0"*64)
