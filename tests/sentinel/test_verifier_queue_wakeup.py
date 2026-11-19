"""Resource admission and owner wakeups confer no financial authority."""
import ast
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import inspect
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

import pytest

from sentinel.panel import authority_reader as reader, model, observer_codec, read_projection, sources
from sentinel.panel import verification_service as service
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)


class Scenario:
    def __init__(self, *, retain=False, work_allowed=None, queued=None):
        self.tick = 0.0
        self.key = 'a'*64
        self.calls = []
        self.wakeup = Event()
        self.slot = BoundedSemaphore(1)
        self.fail = False
        self.failure_row = None
        self.value = reader.Reader(runner=self.run, clock=lambda:self.tick,
            wall_clock=lambda:NOW+timedelta(seconds=self.tick),
            evidence_reader=lambda *_:self.key, key_factory=lambda _url,_paper,key:key,
            queued_evidence_reader=queued, work_allowed=work_allowed,
            unknown_factory=service.paper_unknown,
            expected_keys=frozenset({'paper_reconciliation'}), execution_slot=self.slot,
            completion=self.wakeup, retain_failed_attempt=retain)

    def run(self, _function, _url, _paper, key, **kwargs):
        self.calls.append((key, kwargs['timeout']))
        observed = NOW+timedelta(seconds=self.tick)
        row = self.failure_row if self.fail and self.failure_row is not None else model.Row(
            'paper_reconciliation', 'Paper', 'recorded', model.FAIL if self.fail else model.OK,
            as_of=observed)
        return observer_codec.pack([row], [], observed_at=observed)

    def finish(self):
        pending = self.value.pending
        if pending is not None:pending.join(3)
        assert self.value.pending is None

    def queue(self):
        assert self.slot.acquire(timeout=1)
        self.value.read('private')
        return self.value.attempt_state()

    def grant(self):
        self.slot.release()
        self.finish()


def test_stale_queued_identity_never_spawns_and_current_retry_keeps_original_budgets():
    case = Scenario()
    original = case.queue()
    case.tick=1;case.key='b'*64
    case.grant()
    closed=case.value.attempt_state()
    assert closed['attempt_id']==original['attempt_id'] and closed['subject_sha256']=='a'*64
    assert closed['outcome']=='SUPERSEDED' and closed['work_started_at'] is None
    assert closed['admitted_at']==original['admitted_at'] and closed['deadline']==original['deadline']
    assert case.wakeup.is_set() and case.calls==[]
    case.value.read('private');case.finish()
    assert case.calls==[('b'*64,300)]
    current=case.value.attempt_state()
    assert current['attempt_id']!=closed['attempt_id'] and current['subject_sha256']=='b'*64
    assert current['deadline']==original['deadline']
    assert case.value.queue_deadline_clock==300 and case.value.attempt_deadline_clock==600
    assert case.value.supersession_at==NOW
    assert case.value.read('private')[0][0].status==model.OK
    assert case.value.attempt_state()['outcome']=='VERIFIED'


def test_repeated_coalescing_neither_rebinds_attempts_nor_renews_queue_or_supersession():
    case=Scenario()
    original=case.queue()
    identities=[]
    for n in range(1,9):
        case.tick=n;case.key=f'{n:064x}'
        case.grant()
        closed=case.value.attempt_state();identities.append(closed['attempt_id'])
        assert closed['outcome']=='SUPERSEDED' and closed['deadline']==original['deadline']
        assert case.value.supersession_at==NOW
        if n<8:
            assert case.slot.acquire(timeout=1)
            case.value.read('private')
    assert len(set(identities))==8 and case.calls==[]
    # The original queue budget, not the last coalesced admission, expires.
    case.tick=300
    rows=case.value.read('private',allow_start=False)[0]
    assert case.value.failure is not None and all(row.status!=model.OK for row in rows)
    assert case.value._coalesced_retry is None and case.value.supersession_at==NOW
    assert case.calls==[]


def test_coalesced_public_queue_and_signed_receipt_keep_original_earlier_bound(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-queue-test-'+'x'*40)
    case=Scenario();case.queue();case.tick=90;case.key='b'*64;case.grant()
    assert case.slot.acquire(timeout=1)
    try:
        pending=case.value.read('private')
        assert case.value.work_started is None
        assert pending[0][0].valid_until==NOW+timedelta(seconds=300)
        assert pending[0][0].recovery.deadline==NOW+timedelta(seconds=300)
        envelope,signature=service.snapshot(case.value,pending,scope='PAPER',now=NOW+timedelta(seconds=90))
        assert signature and envelope['valid_until']==(NOW+timedelta(seconds=300)).isoformat()
        assert envelope['rows'][0]['valid_until']==envelope['valid_until']
        assert datetime.fromisoformat(case.value.attempt_state()['deadline'])==NOW+timedelta(seconds=600)
    finally:
        case.slot.release();case.finish()


@pytest.mark.parametrize('fault',['stopped','lost_owner','expired_after_metadata','regressed','identity_unreadable'])
def test_resource_grant_cannot_spawn_after_stop_identity_or_budget_refusal(fault):
    allowed=[True]
    case=None
    def identity(*_):
        if fault=='expired_after_metadata':case.tick=301
        if fault=='lost_owner':allowed[0]=False
        if fault=='identity_unreadable':raise ValueError('private identity unavailable')
        return case.key
    case=Scenario(work_allowed=lambda:allowed[0],queued=identity)
    case.queue()
    if fault=='stopped':allowed[0]=False
    if fault=='regressed':case.tick=-1
    case.grant()
    assert case.calls==[] and case.value.work_started is None
    assert case.value.answer[2].outcome=='FAILED'
    assert case.wakeup.is_set()


def test_current_resource_grant_runs_once_under_one_owned_slot():
    case=Scenario();case.value.read('private');case.finish()
    assert case.calls==[('a'*64,300)] and case.wakeup.is_set()
    assert case.slot.acquire(timeout=1)
    assert not case.slot.acquire(timeout=.01)
    case.slot.release()
    for _ in range(20):assert case.value.read('private')[0][0].status==model.OK
    assert len(case.calls)==1


@pytest.mark.parametrize('change', ['same', 'new-subject', 'idle'])
def test_occupied_scan_keeps_fresh_negative_visible_and_bounds_retry(change):
    case = Scenario(retain=True)
    case.fail = True
    case.value.read('private')
    case.finish()
    original = case.value.read('private')[0][0]
    attempt = case.value.attempt_state()
    assert original.status == model.FAIL
    case.tick = reader.RETRY_SECONDS+1
    if change == 'new-subject':
        case.key = 'b'*64
    result = case.value.read('private', scan_occupied=change != 'idle')[0][0]
    assert result.status == model.FAIL
    if change == 'same':
        assert result == original
        assert case.value.attempt_state() == attempt
        assert len(case.calls) == 1
        case.tick = 2*reader.RETRY_SECONDS
        case.value.read('private', scan_occupied=True)
    case.finish()
    assert [call[0] for call in case.calls] == ['a'*64, case.key]


def test_early_negative_retry_guard_has_executed_falsifier(monkeypatch):
    replace_method(monkeypatch, reader.Reader, 'read', 'scan_occupied and retry_failed_check',
                   'False and retry_failed_check')
    with pytest.raises(AssertionError):
        test_occupied_scan_keeps_fresh_negative_visible_and_bounds_retry('same')


def _slow_read_only_observer(directory, paper, _subject):
    import os
    import time
    from pathlib import Path
    (Path(directory)/('paper' if paper else 'shadow')).write_text(str(os.getpid()))
    time.sleep(10)


def test_verifier_shutdown_reaps_active_child_and_refuses_queued_child_before_owner_release(
        conn, tmp_path, monkeypatch):
    import os
    import signal
    import time
    from tests.sentinel.test_operational_read_projection import install_projection
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-verifier-retirement-'+'x'*32)
    install_projection(conn)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    monkeypatch.delenv('ALPACA_API_KEY', raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY', raising=False)
    monkeypatch.setattr(service, 'HEARTBEAT', tmp_path/'heartbeat')
    # Real native owner, semaphore, supervised subprocess and shutdown. Replace
    # only the expensive read body and stable fixture subject.
    monkeypatch.setattr(service, '_restore_readers', lambda *a, **k: {})
    stopped = Event()
    times, pids = [], []
    def before_shutdown(owner, readers, *args, **kwargs):
        for scope, instance in readers.items():
            instance.observer = _slow_read_only_observer
            instance.evidence_reader = instance.queued_evidence_reader = lambda *_: 'a'*64
            instance.read(str(tmp_path), include_paper=scope=='PAPER')
            if scope == 'SHADOW':
                deadline = time.monotonic()+5
                while not (tmp_path/'shadow').exists() and time.monotonic()<deadline:
                    time.sleep(.02)
                pids.append(int((tmp_path/'shadow').read_text()))
        assert readers['PAPER'].pending and readers['PAPER'].work_started is None
        assert not conn.execute('SELECT pg_try_advisory_lock(%s,%s)', service.OWNER_LOCK).fetchone()[0]
        times.append(time.monotonic())
        signal.raise_signal(signal.SIGTERM)
    monkeypatch.setattr(service, '_run_owned_loop', before_shutdown)
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM,signal.SIGINT)}
    try:
        assert service.run(stopped=stopped) == 0
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    assert stopped.is_set() and time.monotonic()-times[0]<4
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    assert not (tmp_path/'paper').exists()
    assert conn.execute('SELECT pg_try_advisory_lock(%s,%s)', service.OWNER_LOCK).fetchone()[0]
    assert conn.execute(f'SELECT count(*) FROM {service.schema.RECEIPTS}').fetchone() == (0,)


def test_stopped_owner_discards_results_before_receipt_or_diagnostic(monkeypatch):
    import time
    stopped = Event()
    rollbacks = []
    conn = SimpleNamespace(rollback=lambda:rollbacks.append(True))
    instance = SimpleNamespace(completed=None, read=lambda *_a, **_k:stopped.set())
    monkeypatch.setattr(service, 'snapshot', lambda *_a, **_k:pytest.fail('published during shutdown'))
    service._refresh_readers(conn, {'SHADOW':instance}, 'offline', 'owner', {}, stopped,
                             time.monotonic()+5)
    assert rollbacks == [True]


def test_refresh_samples_native_contention_before_consuming_the_first_answer(pg, monkeypatch):
    import psycopg
    import time
    from sentinel import local_paper, snapshot_scan_admission
    monkeypatch.setattr(local_paper, 'enabled', lambda:True)
    monkeypatch.setattr(service, 'snapshot', lambda *a,**k: None)
    monkeypatch.setattr(service, '_opening_scan_reserve', lambda *a:None)
    monkeypatch.setattr(service, '_closing_scan_reserve', lambda *a:None)
    calls = []
    instance = SimpleNamespace(completed=None, read=lambda *a,**kw:calls.append(kw),
                               attempt_state=lambda:None)
    with psycopg.connect(pg.sync_dsn) as conn, psycopg.connect(pg.sync_dsn) as worker:
        def refresh():
            service._refresh_readers(conn, {'SHADOW':instance}, 'offline', 'owner', {}, Event(),
                                     time.monotonic()+5)
            return calls.pop()
        with snapshot_scan_admission.admitted(worker):
            options = refresh()
            assert options['scan_occupied'] is True
            assert options['defer_refresh_until'] > datetime.now(timezone.utc)
        assert refresh() == {'include_paper':False}


def test_long_first_observation_cannot_immediately_queue_identical_negative_under_contention():
    case = Scenario(retain=True)
    case.fail = True
    # The reader's initial observation remains mandatory even on an occupied
    # scan. Its answer becomes available after the normal retry period.
    assert case.slot.acquire(timeout=1)
    case.value.read('private', scan_occupied=True)
    case.tick = reader.RETRY_SECONDS+3
    case.grant()
    assert case.value.completed is None and case.value.answer is not None
    result = case.value.read('private', scan_occupied=True)
    assert result[0][0].status == model.FAIL and case.value.attempt_state()['outcome'] == 'FAILED'
    assert len(case.calls) == 1 and case.value.pending is None


@pytest.mark.parametrize('clock',['monotonic','utc'])
def test_metadata_read_cannot_regress_either_clock_above_original_admission(clock):
    wall=[0.0];case=None
    def identity(*_):
        if clock=='monotonic':case.tick=1
        else:wall[0]=1
        return case.key
    case=Scenario(queued=identity)
    case.value.wall_clock=lambda:NOW+timedelta(seconds=wall[0])
    case.queue();case.tick=wall[0]=2
    case.grant()
    assert case.calls==[] and case.value.work_started is None
    assert case.value.answer[2].outcome=='FAILED'


def test_stale_paced_repair_cannot_replace_exhausted_supersession_with_transport_failure():
    case=Scenario();case.queue();case.tick=1;case.key='b'*64;case.grant()
    case.tick=600;case.value.read('private',allow_start=False)
    assert case.value.failure_diagnostic.code=='SUPERSESSION_EXHAUSTED'
    case.queue();case.tick=601;case.key='c'*64;case.grant()
    assert case.calls==[] and case.value.answer[2].outcome=='SUPERSEDED'
    case.value.read('private',allow_start=False)
    assert case.value.failure_diagnostic.code=='SUPERSESSION_EXHAUSTED'
    assert case.value._coalesced_retry is None


def test_known_negative_and_uncommitted_failure_survive_fast_coalesced_retry():
    case=Scenario(retain=True);case.fail=True
    case.value.read('private');case.finish();case.value.read('private')
    first=case.value.attempt_state()
    assert first['outcome']=='FAILED' and case.value.negative_result is not None
    case.tick=31;case.queue()
    retained=case.value.pending_failed_attempt()
    assert retained['attempt_id']==first['attempt_id']
    case.tick=32;case.key='b'*64;case.grant()
    negative=case.value.read('private')[0]
    assert any(row.key=='paper_reconciliation' and row.status==model.FAIL for row in negative)
    assert case.value.pending is None and len(case.calls)==1
    assert case.value.pending_failed_attempt()==retained
    assert case.value.ack_failed_attempt(retained['attempt_id'])
    case.fail=False
    pending=case.value.read('private')[0]
    assert any(row.key=='paper_reconciliation' and row.status==model.FAIL for row in pending)
    case.finish();case.value.read('private')
    assert case.calls[-1][0]=='b'*64 and len(case.calls)==2
    assert case.value.negative_result is None and case.value.attempt_state()['outcome']=='VERIFIED'


def _blocked_paper_observation(monkeypatch, *, state='BLOCKED', completed_at=NOW):
    cycle = {'state': state, 'completed_at': completed_at}
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda conn: cycle)
    monkeypatch.setattr(sources, '_clean_cash_supersession', lambda conn, cycle: None)
    monkeypatch.setattr(sources, '_retired_local_paper_failure', lambda conn: None)
    return sources._dual_paper_row(None, informational_paper_mirror=None,
                                  publication=None, feed_store=None)


def _assert_terminal_refresh_pacing(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-blocked-test-'+'x'*40)
    case = Scenario(retain=True)
    case.fail = True
    case.failure_row = _blocked_paper_observation(monkeypatch)
    case.value.read('private'); case.finish()
    result = case.value.read('private')
    original = case.value.attempt_state()
    receipt = service.snapshot(case.value, result, scope='PAPER', now=NOW)
    assert original['outcome'] == 'FAILED' and receipt is not None
    assert result[0][0].operational_fact == model.OperationalFact(
        kind='PAPER_VERIFICATION', state='BLOCKED')
    for tick in (31, 120, reader.REFRESH_SECONDS-1):
        case.tick = tick
        result = case.value.read('private')
        assert case.value.pending is None and len(case.calls) == 1
        assert result[0][0].status == model.FAIL
        assert case.value.attempt_state() == original
        assert service.snapshot(case.value, result, scope='PAPER',
                                now=NOW+timedelta(seconds=tick)) == receipt
    case.tick = reader.REFRESH_SECONDS
    assert case.slot.acquire(timeout=1)
    try:
        result = case.value.read('private')
        assert result[0][0].status == model.FAIL
        assert case.value.attempt_state()['attempt_id'] != original['attempt_id']
        assert case.value.pending_failed_attempt() == original
    finally:
        case.grant()
    assert len(case.calls) == 2


def test_durable_blocked_paper_refresh_keeps_original_negative_and_clocks(monkeypatch):
    _assert_terminal_refresh_pacing(monkeypatch)


def test_removed_terminal_paper_refresh_pacing_is_detected(monkeypatch):
    replace_method(monkeypatch, reader.Reader, 'read',
                   'retry_failed_check = False', 'retry_failed_check = True')
    with pytest.raises(AssertionError):
        _assert_terminal_refresh_pacing(monkeypatch)


@pytest.mark.parametrize('changed', ['subject', 'identity', 'unfinished', 'other_negative'])
def test_terminal_paper_refresh_does_not_delay_changed_or_unproved_results(monkeypatch, changed):
    case = Scenario(retain=True)
    case.fail = True
    case.failure_row = _blocked_paper_observation(monkeypatch,
        state='SUPERSEDED' if changed == 'other_negative' else 'BLOCKED',
        completed_at=None if changed == 'unfinished' else NOW)
    case.value.read('private'); case.finish()
    assert case.value.read('private')[0][0].status == model.FAIL
    case.tick = 31
    if changed == 'subject':
        case.key = 'b'*64
    if changed == 'identity':
        evidence_reader = case.value.evidence_reader
        def refuse(*_):
            raise ValueError('private current subject unavailable')
        case.value.evidence_reader = refuse
        assert case.value.read('private')[0][0].status == model.UNKNOWN
        case.value.evidence_reader = evidence_reader
    case.value.read('private'); case.finish()
    assert len(case.calls) == 2 and case.calls[-1][0] == case.key


class LoopWake:
    def __init__(self, stopped, clock):
        self.event=Event();self.stopped=stopped;self.clock=clock
        self.waits=[];self.clears=0;self.before_wait=None
    def set(self):self.event.set()
    def clear(self):self.clears+=1;self.event.clear()
    def wait(self, seconds):
        self.waits.append(seconds)
        if self.before_wait is not None:self.before_wait()
        if self.event.is_set():return True
        self.clock[0]+=seconds;self.stopped.set();return False


def owner_loop(monkeypatch, *, during='refresh'):
    clock=[0.0];stopped=Event();wake=LoopWake(stopped,clock)
    ready=[during=='before'];consumed=[];iterations=[]
    if ready[0]:wake.set()
    class Connection:
        closed=False;broken=False
        def execute(self,*_):return SimpleNamespace(fetchone=lambda:(NOW+timedelta(seconds=610),NOW))
        def commit(self):pass
        def rollback(self):pass
    def finish():
        ready[0]=True
        for _ in range(100):wake.set()
    def refresh(*_):
        iterations.append(True)
        if ready[0]:consumed.append(clock[0]);ready[0]=False
        elif len(iterations)==1 and during=='refresh':finish()
    def heartbeat(*_args,**_kwargs):
        if len(iterations)==1 and during=='heartbeat':finish()
    if during=='wait':
        def before_wait():
            if len(iterations)==1:finish()
        wake.before_wait=before_wait
    if during=='stop':wake.before_wait=lambda:stopped.set()
    monkeypatch.setattr(service,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(service,'HEARTBEAT',SimpleNamespace(write_text=heartbeat))
    monkeypatch.setattr(service,'_refresh_readers',refresh)
    deadlines=[]
    service._run_owned_loop(Connection(),{},'private','owned',{},stopped,100,
        wakeup=wake,on_owner_deadline=deadlines.append)
    return clock,consumed,iterations,wake,deadlines


@pytest.mark.parametrize('during',['before','refresh','heartbeat','wait'])
def test_completion_before_during_or_after_refresh_is_not_lost_and_bursts_coalesce(monkeypatch,during):
    clock,consumed,iterations,wake,deadlines=owner_loop(monkeypatch,during=during)
    assert consumed == [0.0], 'completion was missed before the periodic fallback'
    assert len(iterations)==(1 if during=='before' else 2)
    assert all(seconds==15 for seconds in wake.waits) and clock[0]==15
    assert len(deadlines)==len(iterations) and wake.clears==len(iterations)


def test_unchanged_periodic_fallback_and_stop_admit_no_extra_refresh(monkeypatch):
    clock,consumed,iterations,wake,_=owner_loop(monkeypatch,during='stop')
    assert not consumed and len(iterations)==1 and wake.waits==[15]
    assert clock[0]==15


@pytest.mark.parametrize('fault',['expired','foreign','current'])
def test_real_owner_metadata_gate_is_read_only_and_rejects_lost_ownership(conn,monkeypatch,fault):
    conn.execute(f'CREATE TABLE {service.schema.OWNER} '
        '(id INTEGER PRIMARY KEY,owner_id UUID NOT NULL,expires_at TIMESTAMPTZ NOT NULL)')
    owner=str(uuid.uuid4());other=str(uuid.uuid4())
    conn.execute(f'INSERT INTO {service.schema.OWNER} VALUES (1,%s,clock_timestamp()+%s::interval)',
        (other if fault=='foreign' else owner,'-1 second' if fault=='expired' else '610 seconds'))
    conn.commit();calls=[]
    def subject(owned,*_):
        assert owned.execute('SHOW transaction_read_only').fetchone()[0]=='on'
        calls.append(True);return 'c'*64
    monkeypatch.setattr(service.read_projection,'subject',subject)
    if fault=='current':assert service._queued_subject(conn.info.dsn,True,owner)=='c'*64
    else:
        with pytest.raises(ValueError,match='owner unavailable'):
            service._queued_subject(conn.info.dsn,True,owner)
    assert len(calls)==(1 if fault=='current' else 0)


def test_actual_owner_row_guard_has_executed_falsifier(conn,monkeypatch):
    replace_method(monkeypatch,service,'_queued_subject','if row != (owner_id, True):','if False:')
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_real_owner_metadata_gate_is_read_only_and_rejects_lost_ownership(conn,monkeypatch,'foreign')


def replace_method(monkeypatch, owner, name, old, new):
    import textwrap
    source=textwrap.dedent(inspect.getsource(getattr(owner,name)))
    assert source.count(old)==1
    namespace=dict(vars(reader if owner is reader.Reader else service))
    exec(source.replace(old,new),namespace)
    monkeypatch.setattr(owner,name,namespace[name])


def test_stale_queue_guard_has_executed_falsifier(monkeypatch):
    replace_method(monkeypatch,reader.Reader,'_work','if current != key:','if False:')
    with pytest.raises(AssertionError):test_stale_queued_identity_never_spawns_and_current_retry_keeps_original_budgets()


def test_expired_queue_guard_has_executed_falsifier(monkeypatch):
    replace_method(monkeypatch,reader.Reader,'_queued_admission',
        'tick < self.queue_deadline_clock and instant < self.queue_deadline_at', 'True')
    with pytest.raises(AssertionError):
        test_resource_grant_cannot_spawn_after_stop_identity_or_budget_refusal('expired_after_metadata')


def test_owner_admission_guard_has_executed_falsifier(monkeypatch):
    replace_method(monkeypatch,reader.Reader,'_queued_admission',
        'self.work_allowed is not None and self.work_allowed() is not True','False')
    with pytest.raises(AssertionError):
        test_resource_grant_cannot_spawn_after_stop_identity_or_budget_refusal('lost_owner')


def test_metadata_clock_high_water_guard_has_executed_falsifier(monkeypatch):
    replace_method(monkeypatch,reader.Reader,'_queued_admission',
        'or tick < self.queue_last_clock or instant < self.queue_last_at','')
    with pytest.raises(AssertionError):
        test_metadata_read_cannot_regress_either_clock_above_original_admission('monotonic')


def test_public_queue_bound_has_executed_falsifier(monkeypatch):
    source=inspect.getsource(reader.Reader.read)
    guard='deadline = self.queue_deadline_at'
    assert source.count(guard)==1
    import textwrap
    namespace=dict(vars(reader));exec(textwrap.dedent(source).replace(guard,
        'deadline = self.pending_at+timedelta(seconds=DEADLINE_SECONDS)'),namespace)
    monkeypatch.setattr(reader.Reader,'read',namespace['read'])
    with pytest.raises(AssertionError):
        test_coalesced_public_queue_and_signed_receipt_keep_original_earlier_bound(monkeypatch)


def test_restoring_clear_after_observe_loses_the_completion_and_is_detected(monkeypatch):
    source=inspect.getsource(service._run_owned_loop)
    tree=ast.parse(source)
    clear_guards=[node for node in ast.walk(tree) if isinstance(node,ast.If)
        and len(node.body)==1 and not node.orelse
        and isinstance(node.body[0],ast.Expr)
        and isinstance(node.body[0].value,ast.Call)
        and isinstance(node.body[0].value.func,ast.Attribute)
        and isinstance(node.body[0].value.func.value,ast.Name)
        and node.body[0].value.func.value.id=='wakeup'
        and node.body[0].value.func.attr=='clear']
    refreshes=[node for node in ast.walk(tree) if isinstance(node,ast.Expr)
        and isinstance(node.value,ast.Call)
        and isinstance(node.value.func,ast.Name)
        and node.value.func.id=='_refresh_readers']
    assert len(clear_guards)==len(refreshes)==1
    clear,refresh=clear_guards[0],refreshes[0]
    assert clear.end_lineno<refresh.lineno
    lines=source.splitlines(keepends=True)
    refresh_line=lines[refresh.lineno-1]
    indent=refresh_line[:len(refresh_line)-len(refresh_line.lstrip())]
    mutated=[]
    for line_number,line in enumerate(lines,1):
        if clear.lineno<=line_number<=clear.end_lineno:
            continue
        mutated.append(line)
        if line_number==refresh.end_lineno:
            mutated.append(indent+'if wakeup is not None: wakeup.clear()\n')
    source=''.join(mutated)
    # The mutated loop must see the same clock, reader and heartbeat fixtures.
    namespace = {}
    exec(compile(source, '<clear-after-observe-falsifier>', 'exec'), vars(service), namespace)
    monkeypatch.setattr(service,'_run_owned_loop',namespace['_run_owned_loop'])
    with pytest.raises(AssertionError, match='completion was missed before the periodic fallback'):
        test_completion_before_during_or_after_refresh_is_not_lost_and_bursts_coalesce(monkeypatch,'refresh')


def test_retained_negative_stays_under_its_original_receipt_and_clock(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'a-test-key-at-least-thirty-two-bytes')
    case = Scenario(retain=True)
    case.fail = True
    case.queue()
    case.tick = 7.377081
    case.grant()
    initial = case.value.read('private')
    original, _ = service.snapshot(case.value, initial, scope='PAPER', now=case.value.wall_clock())
    assert original['subject_sha256'] == 'a' * 64
    assert original['observed_at'] == case.value.wall_clock().isoformat()
    case.tick = 23
    case.key = 'b' * 64
    changed = case.value.read('private')
    assert changed[0][0].status == model.FAIL and 'LAST KNOWN' in changed[0][0].detail
    assert service.snapshot(case.value, changed, scope='PAPER', now=case.value.wall_clock()) is None
    assert case.value.attempt_state()['latched_failure']['code'] == 'NEGATIVE_RESULT'

    code = inspect.getsource(service.snapshot)
    guard = 'and rows[0].as_of == retained[0].as_of'
    assert guard in code
    namespace = {}
    exec(code.replace(guard, 'and False'), vars(service), namespace)
    with pytest.raises(ValueError, match='verification receipt fact is future dated'):
        namespace['snapshot'](case.value, changed, scope='PAPER', now=case.value.wall_clock())


@pytest.mark.parametrize('state,retry,wake,allowed', [
    ('WAITING_OPEN', None, None, True),
    ('EXECUTING', None, None, True),
    ('RECONCILING', None, None, True),
    ('RETRY_WAIT', 'RECOVER', 0, True),
    ('RETRY_WAIT', 'RECOVER', 31, False),
    ('RETRY_WAIT', 'PREPARE', 0, False),
    ('SUCCEEDED', None, None, False),
])
def test_scan_reservation_is_bounded_to_the_current_opening(state, retry, wake, allowed):
    opened = NOW
    execute = NOW + timedelta(minutes=1)
    close = NOW + timedelta(hours=6)
    stamp = NOW if state == 'WAITING_OPEN' else NOW + timedelta(minutes=2)
    values = state, opened, execute, close, None if wake is None else stamp + timedelta(seconds=wake), retry
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: values))
    assert service._opening_scan_reserve(conn, stamp) == (NOW + timedelta(minutes=10) if allowed else None)
    assert service._opening_scan_reserve(conn, NOW + timedelta(minutes=10)) is None
    assert service._opening_scan_reserve(conn, NOW - timedelta(seconds=31)) is None


def test_optional_shadow_scan_is_deferred_only_while_positive_proof_covers_opening():
    tick = [301.0]
    started = Event()

    def run(*_args, **_kwargs):
        started.set()
        return observer_codec.pack([model.Row('shadow_verification', 'Shadow', 'Verified', model.OK)],
            [], observed_at=NOW + timedelta(seconds=tick[0]))

    evidence = reader.Reader(runner=run, clock=lambda:tick[0],
        wall_clock=lambda:NOW + timedelta(seconds=tick[0]),
        evidence_reader=lambda *_:'shadow', key_factory=lambda _url,_paper,key:key,
        expected_keys=frozenset({'shadow_verification'}))
    evidence.configuration = 'shadow'
    evidence.completed = ([model.Row('shadow_verification', 'Shadow', 'Verified', model.OK,
        as_of=NOW)], [], NOW)
    reserve = NOW + timedelta(minutes=10)
    assert evidence.read('private', include_paper=False, defer_refresh_until=reserve)[0][0].status == model.OK
    assert evidence.pending is None and not started.is_set()
    tick[0] = 449.999
    evidence.read('private', include_paper=False, defer_refresh_until=reserve)
    assert evidence.pending is None and not started.is_set()
    tick[0] = 450
    evidence.read('private', include_paper=False, defer_refresh_until=reserve)
    assert started.wait(2)
    if evidence.pending is not None:
        evidence.pending.join(2)


def test_same_subject_shadow_renewal_publishes_checking_at_original_attempt_clocks(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-queue-test-'+'x'*40)
    tick = [450.0]
    started, release = Event(), Event()
    key = 'a'*64
    rows = [model.Row(name, name, 'Verified', model.OK, as_of=NOW)
            for name in sorted(read_projection.SHADOW_KEYS)]

    def run(*_args, **_kwargs):
        started.set()
        assert release.wait(3)
        return observer_codec.pack(rows, [], observed_at=NOW+timedelta(seconds=tick[0]))

    evidence = reader.Reader(runner=run, clock=lambda:tick[0],
        wall_clock=lambda:NOW+timedelta(seconds=tick[0]), evidence_reader=lambda *_:key)
    evidence.configuration = key
    evidence.completed = (rows, [], NOW)
    evidence.last_result_at = NOW+timedelta(seconds=1)
    try:
        fresh = evidence.read('private', include_paper=False)
        assert started.wait(2)
        positive, positive_signature = service.snapshot(
            evidence, fresh, scope='SHADOW', now=evidence.wall_clock())
        assert datetime.fromisoformat(positive['valid_until']) == NOW+timedelta(seconds=600)

        tick[0] = 610
        now = evidence.wall_clock()
        with pytest.raises(ValueError, match='verification receipt expired'):
            read_projection.decode(positive, positive_signature,
                                   current_subject=key, scope='SHADOW', now=now)
        pending = evidence.read('private', include_paper=False)
        current = service.snapshot(evidence, pending, scope='SHADOW', now=now)
        assert current is not None, 'the old result clock expired the active check'
        receipt, signature = current
        assert datetime.fromisoformat(receipt['observed_at']) == NOW+timedelta(seconds=450)
        deadline = NOW+timedelta(seconds=750)
        assert datetime.fromisoformat(receipt['valid_until']) == deadline
        checking, _, _, errors = read_projection.decode(
            receipt, signature, current_subject=key, scope='SHADOW', now=now)
        assert not errors and all(row.status == model.WARN for row in checking)
        shadow = next(row for row in checking if row.key == 'shadow_verification')
        assert shadow.value == 'CHECK IN PROGRESS' and shadow.recovery.deadline == deadline

        tick[0] = 750.001
        now = evidence.wall_clock()
        with pytest.raises(ValueError, match='verification receipt expired'):
            read_projection.decode(receipt, signature, current_subject=key, scope='SHADOW', now=now)
        expired = evidence.read('private', include_paper=False)
        assert service.snapshot(evidence, expired, scope='SHADOW', now=now) is None
    finally:
        release.set()
        if evidence.pending is not None:
            evidence.pending.join(3)


def test_scan_reservation_requires_current_binding_control_and_live_lease(conn):
    conn.execute("""CREATE TEMP TABLE sentinel_automation_cycles (
        state text, execution_open_at timestamptz, execute_at timestamptz, execution_close_at timestamptz,
        next_wake_at timestamptz, diagnostic jsonb, control_generation int, deployment_id text,
        broker text, broker_account_id text, takeover_epoch int, effective_session date,
        created_at timestamptz, cycle_id text)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_control (
        id int, generation int, enabled bool, kill_switch_engaged bool, authority_verdict text)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_lease (
        id int, control_generation int, expires_at timestamptz)""")
    conn.execute("""CREATE TEMP TABLE sentinel_account_binding (
        id int, deployment_id text, broker text, broker_account_id text, takeover_epoch int, ownership_state text)""")
    conn.execute("INSERT INTO sentinel_automation_control VALUES (1, 5, true, false, 'PASS')")
    conn.execute("INSERT INTO sentinel_automation_lease VALUES (1, 5, clock_timestamp() + interval '60 sec')")
    conn.execute("INSERT INTO sentinel_account_binding VALUES (1,'d','alpaca','fixture',2,'SENTINEL_OWNED')")
    opened = datetime(2026, 11, 11, 14, 30, tzinfo=timezone.utc)
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES ('EXECUTING',%s,%s,%s,NULL,'{}',
        5,'d','alpaca','fixture',2,'2026-11-11',%s,'fixture-cycle')""",
        (opened, opened + timedelta(minutes=1), opened + timedelta(hours=6), opened))
    now = opened + timedelta(minutes=2)
    assert service._opening_scan_reserve(conn, now) == opened + timedelta(minutes=10)
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE sentinel_account_binding SET takeover_epoch=3")
        assert service._opening_scan_reserve(conn, now) is None
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE sentinel_automation_control SET generation=6")
        assert service._opening_scan_reserve(conn, now) is None
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()")
        assert service._opening_scan_reserve(conn, now) is None


@pytest.fixture
def close_scan(conn):
    conn.execute("""CREATE TEMP TABLE sentinel_automation_cycles (
        state text, decision_session date, effective_session date, prepare_at timestamptz,
        execution_open_at timestamptz, execution_close_at timestamptz,
        updated_at timestamptz, created_at timestamptz, cycle_id text, last_fence_token bigint,
        control_generation int, deployment_id text, broker text, broker_account_id text,
        takeover_epoch int, certificate_sha256 text, config_sha256 text,
        plan_id text, failure_code text, diagnostic jsonb, next_wake_at timestamptz,
        historical_state_only bool DEFAULT false, last_clean_reconciliation_id text,
        execute_at timestamptz, completed_at timestamptz)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_control (
        id int, generation int, enabled bool, kill_switch_engaged bool, authority_verdict text,
        certificate_sha256 text, config_sha256 text, deployment_id text DEFAULT 'd',
        broker text DEFAULT 'alpaca', broker_account_id text DEFAULT 'fixture', takeover_epoch int DEFAULT 2,
        enabled_at timestamptz)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_lease (
        id int, control_generation int, expires_at timestamptz, holder_id text, fence_token bigint)""")
    conn.execute("""CREATE TEMP TABLE sentinel_account_binding (
        id int, deployment_id text, broker text, broker_account_id text, takeover_epoch int,
        ownership_state text)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_service_instances (
        instance_id text, state text, heartbeat_at timestamptz,
        callback_started_at timestamptz, callback_deadline_at timestamptz)""")
    conn.execute("""CREATE TEMP TABLE sentinel_execution_plans (plan_id text, deployment_id text,
        broker text, broker_account_id text, takeover_epoch int, decision_session date, effective_session date)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_events (generation int, action text, detail jsonb,
        at timestamptz)""")
    conn.execute("INSERT INTO sentinel_automation_control VALUES (1,5,true,false,'PASS','cert','config')")
    conn.execute("INSERT INTO sentinel_account_binding VALUES (1,'d','alpaca','fixture',2,'SENTINEL_OWNED')")
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    conn.execute("INSERT INTO sentinel_automation_lease VALUES (1,5,%s,'holder',8)",
                 (now + timedelta(minutes=5),))
    return conn, now


def test_close_scan_reserves_exact_early_close_for_the_bound_settled_cycle(close_scan):
    conn, now = close_scan
    close = datetime(2026, 11, 27, 18, tzinfo=timezone.utc)
    conn.execute('UPDATE sentinel_automation_lease SET expires_at=%s',
                 (max(now, close) + timedelta(minutes=5),))
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES (
        'SUCCEEDED','2026-11-25','2026-11-27',%s,%s,%s,%s,%s,'today',4,
        5,'d','alpaca','fixture',2,'cert','config')""",
        (close - timedelta(days=2), close - timedelta(hours=3), close,
         close - timedelta(hours=2), close - timedelta(days=2)))
    end = close + timedelta(seconds=60)
    observed_lead = timedelta(seconds=95, microseconds=176573)
    assert service._closing_scan_reserve(conn, close - observed_lead) == end
    assert service._closing_scan_reserve(conn, close - timedelta(seconds=105)) == end
    assert service._closing_scan_reserve(conn, close - timedelta(seconds=106)) is None
    assert service._closing_scan_reserve(conn, end - timedelta(seconds=1)) == end
    assert service._closing_scan_reserve(conn, end) is None
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE sentinel_automation_cycles SET effective_session='2026-11-30'")
        assert service._closing_scan_reserve(conn, close) is None
    with conn.transaction(force_rollback=True):
        conn.execute('UPDATE sentinel_account_binding SET takeover_epoch=3')
        assert service._closing_scan_reserve(conn, close) is None


def test_bound_prior_generation_preserves_close_reserve_after_software_reactivation(close_scan):
    conn, db_now = close_scan
    close = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)
    conn.execute("UPDATE sentinel_automation_lease SET expires_at=%s", (max(close, db_now)+timedelta(minutes=5),))
    conn.execute("UPDATE sentinel_automation_control SET enabled_at=%s", (close-timedelta(hours=2),))
    conn.execute("""INSERT INTO sentinel_automation_cycles
        (state,decision_session,effective_session,execution_open_at,execute_at,execution_close_at,
        updated_at,created_at,cycle_id,last_fence_token,control_generation,deployment_id,broker,
        broker_account_id,takeover_epoch,certificate_sha256,config_sha256,plan_id,completed_at,
        last_clean_reconciliation_id)
        VALUES ('SUCCEEDED','2026-11-17','2026-11-18',%s,%s,%s,%s,%s,'earlier',4,1,'d','alpaca',
        'fixture',2,'old-cert','old-config','saved',%s,'clean')""",
        (close-timedelta(hours=6,minutes=30), close-timedelta(hours=6,minutes=29),close,
         close-timedelta(hours=6),close-timedelta(days=1),close-timedelta(hours=6)))
    conn.execute("""INSERT INTO sentinel_execution_plans VALUES
        ('saved','d','alpaca','fixture',2,'2026-11-17','2026-11-18')""")
    conn.execute("""INSERT INTO sentinel_automation_events VALUES (1,'KILL_RELEASED',
        '{"deployment_id":"d","broker":"alpaca","broker_account_id":"fixture","takeover_epoch":2,
        "config_sha256":"old-config","certificate_sha256":"old-cert"}',%s)""", (close-timedelta(days=2),))
    conn.execute("""INSERT INTO sentinel_automation_events VALUES (5,'KILL_RELEASED',
        '{"deployment_id":"d","broker":"alpaca","broker_account_id":"fixture","takeover_epoch":2,
        "config_sha256":"config","certificate_sha256":"cert"}',%s)""", (close-timedelta(hours=1),))
    admitted = close-timedelta(seconds=28, microseconds=179783)
    assert service._closing_scan_reserve(conn, admitted) == close+timedelta(seconds=60)
    with conn.transaction(force_rollback=True):
        conn.execute("UPDATE sentinel_automation_control SET enabled_at=enabled_at-interval '1 day'")
        assert service._closing_scan_reserve(conn, admitted) == close+timedelta(seconds=60)

    for change in (
        "UPDATE sentinel_automation_control SET generation=1",
        "UPDATE sentinel_automation_control SET broker_account_id='another'",
        "UPDATE sentinel_automation_control SET enabled_at=enabled_at+interval '2 hours'",
        "UPDATE sentinel_automation_events SET at=at-interval '1 day' WHERE generation=5",
        "UPDATE sentinel_automation_events SET detail=detail-'config_sha256' WHERE generation=5",
        "UPDATE sentinel_automation_cycles SET historical_state_only=true",
        "UPDATE sentinel_automation_cycles SET last_clean_reconciliation_id=NULL",
        "UPDATE sentinel_automation_cycles SET completed_at=execute_at-interval '1 sec'",
        "UPDATE sentinel_execution_plans SET takeover_epoch=3",
        "UPDATE sentinel_automation_events SET detail=detail-'certificate_sha256'",
        "UPDATE sentinel_automation_events SET action='KILL_ENGAGED'",
    ):
        with conn.transaction(force_rollback=True):
            conn.execute(change)
            assert service._closing_scan_reserve(conn, admitted) is None

    # A newer retry without a publisher must not displace the independently
    # proved terminal reservation that still covers the first minute.
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES
        ('RETRY_WAIT','2026-11-18','2026-11-19',%s,%s,%s,%s,%s,'new',8,5,'d','alpaca','fixture',
         2,'cert','config',NULL,'ClosingDataPending','{"retry_phase":"REFRESH"}',%s)""",
        (close,close+timedelta(hours=17),close+timedelta(days=1),close,close,close+timedelta(minutes=15)))
    assert service._closing_scan_reserve(conn, close+timedelta(seconds=3)) == close+timedelta(seconds=60)


def test_only_live_registered_source_successor_reserves_optional_refresh(close_scan):
    from sentinel.feed import calendar, rolling_jobs
    from sentinel.feed.rolling_contract import PriceWindow, canonical_json
    conn, db_now = close_scan
    session = calendar.session_on_or_after((db_now+timedelta(days=1)).date())
    closed = calendar.session_window(session)[1]
    now = closed+timedelta(minutes=3)
    job_end = now+timedelta(minutes=2)
    wake = now+timedelta(minutes=15)
    conn.execute("UPDATE sentinel_automation_lease SET expires_at=%s",(wake,))
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES ('RETRY_WAIT',%s,%s,%s,%s,%s,
        %s,%s,'next',8,5,'d','alpaca','fixture',2,'cert','config',NULL,'ClosingDataPending',
        '{"retry_phase":"REFRESH"}',%s)""",
        (session,calendar.next_session(session),closed,now+timedelta(hours=16),now+timedelta(hours=23),
         now-timedelta(seconds=2),closed,wake))
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through(session),
        expected_publication_version=23, strategy_sha256='1'*64, dependencies_sha256='2'*64)
    conn.execute("CREATE TEMP TABLE sentinel_corpus_publications(version int)")
    conn.execute("INSERT INTO sentinel_corpus_publications VALUES (23)")
    conn.execute("""CREATE TEMP TABLE sentinel_snapshot_jobs(job_id int,request jsonb,request_sha256 text,
        created_at timestamptz,lease_until timestamptz,deadline timestamptz,owner text,fence int,
        state text,publication_version int)""")
    conn.execute("CREATE TEMP TABLE sentinel_snapshot_workers(job_id int,owner text)")
    conn.execute("CREATE TEMP TABLE sentinel_operational_snapshot_jobs(job_id int)")
    conn.execute("INSERT INTO sentinel_operational_snapshot_jobs VALUES (1)")
    conn.execute("INSERT INTO sentinel_snapshot_workers VALUES (1,'publisher')")
    conn.execute("""INSERT INTO sentinel_snapshot_jobs VALUES (1,%s,%s,%s,%s,%s,'publisher',3,'STAGING',NULL)""",
        (canonical_json(request.model_dump(mode='json')),request.request_sha256,closed+timedelta(minutes=1),
         job_end,wake))
    assert service._closing_scan_reserve(conn,now)==job_end
    for change in (
        "UPDATE sentinel_snapshot_jobs SET state='PUBLISHED'",
        "UPDATE sentinel_snapshot_jobs SET fence=0",
        "UPDATE sentinel_snapshot_jobs SET request_sha256='changed'",
        "UPDATE sentinel_snapshot_workers SET owner='stale'",
        "DELETE FROM sentinel_operational_snapshot_jobs",
        "INSERT INTO sentinel_corpus_publications VALUES (24)",
        "UPDATE sentinel_automation_cycles SET plan_id='already-saved'",
        "UPDATE sentinel_automation_cycles SET last_fence_token=7",
        "UPDATE sentinel_automation_cycles SET failure_code='OtherRefusal'",
        "UPDATE sentinel_automation_control SET kill_switch_engaged=true",
    ):
        with conn.transaction(force_rollback=True):
            conn.execute(change)
            assert service._closing_scan_reserve(conn,now) is None
    assert service._closing_scan_reserve(conn,job_end) is None


def test_old_close_reservation_misses_the_observed_admission(close_scan, monkeypatch):
    monkeypatch.setattr(service, 'CLOSE_RESERVATION_LEAD_SECONDS', 90)
    with pytest.raises(AssertionError):
        test_close_scan_reserves_exact_early_close_for_the_bound_settled_cycle(close_scan)


@pytest.mark.parametrize('state,callback', [
    ('DISCOVERED', 'PREFLIGHT_RECOVER_CALLBACK'),
    ('REFRESHING_DATA', 'REFRESH_CALLBACK'),
    ('PREPARING', 'PREPARE_CALLBACK'),
])
def test_close_scan_requires_exact_current_callback_and_original_deadline(close_scan, state, callback, monkeypatch):
    conn, now = close_scan
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    deadline = now + timedelta(seconds=80)
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES (
        %s,%s,%s,%s,%s,%s,%s,%s,'next',8,5,'d','alpaca','fixture',2,'cert','config')""",
        (state, today, today + timedelta(days=1), now - timedelta(seconds=3),
         now + timedelta(hours=1), now + timedelta(hours=2), now - timedelta(seconds=2),
         now - timedelta(seconds=3)))
    conn.execute("INSERT INTO sentinel_automation_service_instances VALUES ('holder',%s,%s,%s,%s)",
                 (callback, now, now - timedelta(seconds=1), deadline))
    assert service._closing_scan_reserve(conn, now) == deadline
    assert service._closing_scan_reserve(conn, deadline) is None
    for change in (
        "UPDATE sentinel_automation_service_instances SET state='IDLE'",
        "UPDATE sentinel_automation_service_instances SET heartbeat_at=heartbeat_at-interval '31 sec'",
        "UPDATE sentinel_automation_service_instances SET callback_started_at=callback_started_at-interval '3 sec'",
        "UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()",
        "UPDATE sentinel_automation_control SET certificate_sha256='changed'",
    ):
        with conn.transaction(force_rollback=True):
            conn.execute(change)
            assert service._closing_scan_reserve(conn, now) is None

    with conn.transaction(force_rollback=True):
        conn.execute('UPDATE sentinel_automation_lease SET fence_token=9')
        assert service._closing_scan_reserve(conn, now) is None
        from sentinel.automation import callback_observation
        active = callback_observation.active_instance
        guard = 'c.last_fence_token=l.fence_token'
        assert guard in active('market.database_now')
        monkeypatch.setattr(callback_observation, 'active_instance',
            lambda clock: active(clock).replace(guard, 'TRUE'))
        assert service._closing_scan_reserve(conn, now) == deadline


def test_optional_shadow_scan_respects_the_original_row_expiry():
    elapsed = timedelta(seconds=301)
    started = Event()

    def run(*_args, **_kwargs):
        started.set()
        return observer_codec.pack([model.Row('shadow_verification', 'Shadow', 'Verified', model.OK)],
                                    [], observed_at=NOW + elapsed)

    evidence = reader.Reader(runner=run, clock=elapsed.total_seconds, wall_clock=lambda: NOW + elapsed,
        evidence_reader=lambda *_: 'same', key_factory=lambda _url, _paper, key: key,
        expected_keys=frozenset({'shadow_verification'}))
    evidence.configuration = 'same'
    evidence.completed = ([model.Row('shadow_verification', 'Shadow', 'Verified', model.OK,
        as_of=NOW, valid_until=NOW + elapsed + timedelta(seconds=29))], [], NOW)
    evidence.read('private', include_paper=False, defer_refresh_until=NOW + timedelta(minutes=10))
    assert started.wait(2)
    if evidence.pending is not None:
        evidence.pending.join(2)


@pytest.mark.parametrize('phase,remaining,expected_start', [
    ('SOURCE_FRONTIER', 151, False), ('SOURCE_FRONTIER', 150, True),
    ('FINANCIAL_VERIFICATION', 200, True),
])
def test_only_a_finite_dated_source_wait_yields_before_original_renewal(phase, remaining, expected_start):
    instant = NOW + timedelta(seconds=301)
    end = instant + timedelta(seconds=remaining)
    started = Event()
    recovery = model.RecoveryEvidence(phase=phase, automatic=True, deadline=end)
    row = model.Row('shadow_verification', 'Shadow', 'Waiting', model.WARN,
        as_of=NOW, required_current=True, valid_until=end, recovery=recovery)

    def run(*_args, **_kwargs):
        started.set()
        return observer_codec.pack([row], [], observed_at=instant)

    evidence = reader.Reader(runner=run, clock=lambda: 301., wall_clock=lambda: instant,
        evidence_reader=lambda *_: 'same', key_factory=lambda _url, _paper, key: key,
        expected_keys=frozenset({'shadow_verification'}))
    evidence.configuration = 'same'
    evidence.completed = ([row], [], NOW)
    evidence.read('private', include_paper=False, defer_refresh_until=instant+timedelta(minutes=3))
    if expected_start:
        assert started.wait(2)
    else:
        assert evidence.pending is None and not started.is_set()
    if evidence.pending is not None:
        evidence.pending.join(2)


def test_close_scan_reserves_only_the_exact_planless_publication_pin_retry(close_scan):
    conn, now = close_scan
    day = now.astimezone(ZoneInfo('America/New_York')).date()
    deadline = now + timedelta(seconds=80)
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES (
        'RETRY_WAIT',%s,%s,%s,%s,%s,%s,%s,'next',8,5,'d','alpaca','fixture',2,'cert','config',
        NULL,'PreflightPublicationPinUnavailable','{"retry_phase":"PREFLIGHT_RECOVER"}',%s)""",
        (day, day + timedelta(days=1), now - timedelta(seconds=9), now + timedelta(hours=1),
         now + timedelta(hours=2), now - timedelta(seconds=3), now - timedelta(seconds=9),
         now - timedelta(seconds=2)))
    conn.execute("""INSERT INTO sentinel_automation_service_instances
        VALUES ('holder','PREFLIGHT_RECOVER_CALLBACK',%s,%s,%s)""",
        (now, now - timedelta(seconds=1), deadline))
    assert service._closing_scan_reserve(conn, now) == deadline
    for change in (
        "plan_id='already-prepared'",
        "failure_code='DifferentFailure'",
        "diagnostic='{\"retry_phase\":\"RECOVER\"}'",
        "next_wake_at=next_wake_at+interval '2 sec'",
    ):
        with conn.transaction(force_rollback=True):
            conn.execute(f'UPDATE sentinel_automation_cycles SET {change}')
            assert service._closing_scan_reserve(conn, now) is None


def test_close_scan_planless_guard_omission_admits_the_wrong_retry(close_scan, monkeypatch):
    code = inspect.getsource(service._closing_scan_reserve)
    guard = "c.state='RETRY_WAIT' AND c.plan_id IS NULL"
    assert guard in code
    scope = dict(vars(service))
    exec(code.replace(guard, "c.state='RETRY_WAIT'"), scope)
    monkeypatch.setattr(service, '_closing_scan_reserve', scope['_closing_scan_reserve'])
    with pytest.raises(AssertionError):
        test_close_scan_reserves_only_the_exact_planless_publication_pin_retry(close_scan)


@pytest.mark.parametrize('proof', ['clean', 'scheduled_history', 'completed_history',
                                   'short_expiry', 'changed_subject', 'unqualified', 'error'])
def test_optional_paper_scan_requires_a_still_current_positive_close_receipt(proof):
    case = Scenario()
    case.tick = 301
    case.value.configuration = case.key
    row = model.Row('paper_reconciliation', 'Paper', 'recorded', model.OK, as_of=NOW)
    if proof in {'scheduled_history', 'completed_history'}:
        row = replace(row, status=model.WARN, required_current=True,
            paper_alignment=f'{proof.split("_")[0].upper()}_WITH_HISTORY',
            valid_until=NOW+timedelta(minutes=10))
    elif proof == 'short_expiry':
        row = replace(row, valid_until=NOW+timedelta(seconds=330))
    elif proof == 'changed_subject':
        case.key = 'b'*64
    elif proof == 'unqualified':
        row = replace(row, status=model.WARN)
    errors = ['unreadable'] if proof == 'error' else []
    case.value.completed = ([row], errors, NOW)
    reserve = NOW+timedelta(minutes=10)
    case.value.read('private', defer_refresh_until=reserve)
    case.finish()
    if proof in {'clean', 'scheduled_history', 'completed_history'}:
        assert case.calls == []
        case.tick = 450
        case.value.read('private', defer_refresh_until=reserve)
        case.finish()
    assert case.calls == [(case.key, 300)]
