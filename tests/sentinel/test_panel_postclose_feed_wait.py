"""The close starts acquisition, not a false failure or a new grace clock."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.feed import calendar, store
from sentinel.panel import app, model, sources
from sentinel.panel import postclose_feed_wait as waiting
from sentinel.panel.render import render


NOW = datetime(2026, 10, 26, 20, 5, tzinfo=timezone.utc)
FRONTIER = '2026-10-23'
DEADLINE = datetime(2026, 10, 27, 13, 30, tzinfo=timezone.utc)


def facts(*, now=NOW, frontier=FRONTIER, deadline=DEADLINE):
    boundary = deadline - timedelta(microseconds=1)
    recovery = model.RecoveryEvidence(phase='SOURCE_FRONTIER', automatic=True, deadline=boundary)
    historical = model.ShadowBook(session=frontier, cash=Decimal('100'),
        receivables=Decimal('0'), nav=Decimal('100'), pending_operations=0, holdings=[])
    financial = [model.Row('shadow_verification', 'Shadow', 'WAITING FOR INPUTS',
        model.WARN, as_of=now, required_current=True, recovery=recovery, valid_until=boundary),
        model.Row('book', 'Book', 'LAST ATTESTED', model.WARN,
            as_of=calendar.session_window(frontier)[1], required_current=True,
            recovery=recovery, valid_until=boundary, shadow_book=historical)]
    worker = model.Row('shadow_worker', 'Strategy worker', 'RUNNING', model.OK,
        as_of=now, required_current=True, valid_until=now+timedelta(seconds=60))
    return financial, worker


def feed(*, now=NOW, frontier=FRONTIER, ready=True, behind=1):
    return model.feed_row(frontier=frontier, sessions_behind=behind,
        ready=ready, checks_passed=14 if ready else 13, checks_total=14,
        as_of=calendar.session_window(frontier)[1], checked_at=now-timedelta(minutes=15))


def project(*, now=NOW, financial=None, worker=None, row=None, ready=True, behind=1,
            frontier=FRONTIER):
    default_financial, default_worker = facts(now=now)
    financial = default_financial if financial is None else financial
    worker = default_worker if worker is None else worker
    wait = waiting.from_rows(financial, worker, now=now)
    row = feed(now=now, ready=ready, behind=behind, frontier=frontier) if row is None else row
    return waiting.project(row, wait, frontier=frontier, sessions_behind=behind,
                           ready=ready, now=now)


def test_close_wait_before_first_ingest_is_bounded_amber():
    assert feed().effective_status(NOW) == model.FAIL
    result = project()
    assert result.effective_status(NOW) == model.WARN
    assert result.value == 'WAITING FOR 2026-10-26 CLOSING DATA'
    assert 'last published session 2026-10-23' in result.detail
    assert result.as_of == feed().as_of
    assert result.valid_until == DEADLINE-timedelta(microseconds=1)
    assert result.recovery.deadline == result.valid_until
    assert result.effective_status(DEADLINE) == model.FAIL


def test_refresh_and_new_heartbeats_never_renew_original_deadline():
    first = project()
    later = project(now=NOW+timedelta(hours=3))
    assert later.valid_until == first.valid_until
    assert later.recovery.deadline == first.recovery.deadline


@pytest.mark.parametrize('fault', ['dead', 'unknown', 'stale', 'future', 'missing_expiry', 'missing_clock'])
def test_unhealthy_publisher_cannot_earn_wait(fault):
    financial, worker = facts()
    updates = {'dead': {'status':model.FAIL}, 'unknown': {'status':model.UNKNOWN},
        'stale': {'valid_until':NOW-timedelta(seconds=1)},
        'future': {'as_of':NOW+timedelta(minutes=1)},
        'missing_expiry': {'valid_until':None}, 'missing_clock': {'as_of':None}}
    worker = replace(worker, **updates[fault])
    assert project(financial=financial, worker=worker).effective_status(NOW) == model.FAIL, 'unhealthy publisher earned wait'


@pytest.mark.parametrize('fault', ['negative', 'unknown', 'missing_recovery', 'wrong_phase',
    'manual', 'missing_book', 'current_book', 'foreign_book', 'wrong_deadline', 'duplicate'])
def test_unproved_or_inconsistent_historical_wait_is_refused(fault):
    financial, worker = facts()
    if fault in {'negative', 'unknown', 'missing_recovery'}:
        financial[0] = replace(financial[0], **{
            'negative':{'status':model.FAIL}, 'unknown':{'status':model.UNKNOWN},
            'missing_recovery':{'recovery':None}}[fault])
    elif fault in {'wrong_phase', 'manual'}:
        financial[0] = replace(financial[0], recovery=replace(financial[0].recovery,
            **({'phase':'FINANCIAL_VERIFICATION'} if fault=='wrong_phase' else {'operator_required':True})))
    elif fault == 'missing_book':
        financial.pop()
    elif fault == 'current_book':
        financial[1] = replace(financial[1], status=model.OK, recovery=None)
    elif fault == 'foreign_book':
        financial[1] = replace(financial[1], shadow_book=financial[1].shadow_book.model_copy(
            update={'session':'2026-10-22'}))
    elif fault == 'wrong_deadline':
        financial, worker = facts(deadline=DEADLINE+timedelta(hours=1))
    else:
        financial.append(financial[0])
    assert project(financial=financial, worker=worker).effective_status(NOW) == model.FAIL, 'unproved history earned wait'


@pytest.mark.parametrize('fault', ['not_ready', 'unchecked', 'many_sessions', 'unknown_lag',
    'foreign_frontier', 'expired_verdict', 'future_fact', 'frontier_error'])
def test_real_feed_fault_is_not_downgraded(fault):
    ready, behind, frontier, row = True, 1, FRONTIER, feed()
    if fault == 'not_ready': ready=False; row=feed(ready=False)
    elif fault == 'unchecked': ready=None; row=feed(ready=None)
    elif fault == 'many_sessions': behind=2
    elif fault == 'unknown_lag': behind=None
    elif fault == 'foreign_frontier': frontier='2026-10-22'
    elif fault == 'expired_verdict': row=replace(row, valid_until=NOW-timedelta(microseconds=1))
    elif fault == 'future_fact': row=replace(row, as_of=NOW+timedelta(minutes=1))
    else: row=replace(row, status=model.UNKNOWN)
    result=project(row=row, ready=ready, behind=behind, frontier=frontier)
    assert result is row


def test_only_current_closed_session_and_actual_half_day_close_can_earn_wait():
    financial, worker=facts(frontier='2026-10-22')
    assert waiting.from_rows(financial,worker,now=NOW) is None
    before=datetime(2026,11,27,17,59,59,tzinfo=timezone.utc)
    after=before+timedelta(seconds=1)
    deadline=calendar.session_window('2026-11-30')[0]
    financial,worker=facts(now=before,frontier='2026-11-25',deadline=deadline)
    assert waiting.from_rows(financial,worker,now=before) is None
    financial,worker=facts(now=after,frontier='2026-11-25',deadline=deadline)
    wait=waiting.from_rows(financial,worker,now=after)
    assert wait is not None and wait.decision_session=='2026-11-27'
    assert wait.deadline==deadline-timedelta(microseconds=1)


def test_unavailable_calendar_never_creates_wait(monkeypatch):
    financial,worker=facts()
    monkeypatch.setattr(calendar,'latest_closed_session',lambda *a: (_ for _ in ()).throw(RuntimeError('unavailable')))
    assert waiting.from_rows(financial,worker,now=NOW) is None


def build(monkeypatch, *, ingest_status='success', extra=(), errors=()):
    financial,worker=facts()
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setattr(sources,'_bounded_dual_authority_rows',lambda *a,**kw:(financial,{},[],[]))
    monkeypatch.setattr(sources,'_shadow_worker_row',lambda *a:worker)
    monkeypatch.setattr(sources,'_ownership',lambda *a:model.Row('ownership','Owner','BOUND'))
    monkeypatch.setattr(sources,'_runtime_rows',lambda *a:([*extra],list(errors)))
    monkeypatch.setattr(sources,'_automation_rows',lambda *a:([
        model.Row('authority','Authority','PASS'),model.Row('automation','Automation','ENABLED')],[]))
    monkeypatch.setattr(sources,'_operator_evidence_rows',lambda *a,**kw:([],[]))
    connection=SimpleNamespace(close=lambda:None,rollback=lambda:None)
    monkeypatch.setattr(store,'connect',lambda *a:connection)
    monkeypatch.setattr(sources,'_set_statement_timeout',lambda *a:None)
    monkeypatch.setattr(sources,'_operational_acquisition',lambda *a:[dict(status=ingest_status,
        kind='OPERATIONAL SNAPSHOT',updated_at=NOW-timedelta(minutes=15),current_chunk='PUBLISHED',
        error_message='actual acquisition failure' if ingest_status=='failed' else None)])
    monkeypatch.setattr(sources,'_feed_status_snapshot',lambda *a:(FRONTIER,SimpleNamespace(
        ready=True,checks_passed=14,checks_total=14,computed_at=NOW-timedelta(minutes=15))))
    monkeypatch.setattr(calendar,'freshness',lambda *a:SimpleNamespace(sessions_behind=1,ahead=False))
    return sources.build_panel(state_dir=Path('/synthetic'),
        database_url='postgresql://fixture@isolated.invalid/fixture',now=NOW)


def test_real_build_json_html_and_health_share_queued_ingest_wait(monkeypatch):
    page=build(monkeypatch)
    assert page.row('feed').status==model.WARN, 'queued post-close preparation remained red: '+page.row('feed').detail
    monkeypatch.setattr(app,'_config',lambda:(Path('/synthetic'),''))
    monkeypatch.setattr(app,'build_panel',lambda **kw:page)
    raw=json.loads(app.panel_json().body)
    health=json.loads(app.operational_health().body)
    assert raw['color']==health['color']=='amber'
    assert health['red_rows']==[] and health['source_errors']==[]
    assert 'WAITING FOR 2026-10-26 CLOSING DATA' in render(page)
    page=replace(page,now=DEADLINE)
    assert page.row('feed').effective_status(DEADLINE)==model.FAIL


@pytest.mark.parametrize('fault',['ingest_failure','other_failure','source_error'])
def test_real_failures_remain_red_on_public_surfaces(monkeypatch,fault):
    page=build(monkeypatch,ingest_status='failed' if fault=='ingest_failure' else 'success',
        extra=[model.Row('other','Other','FAILED',model.FAIL)] if fault=='other_failure' else (),
        errors=['actual read error'] if fault=='source_error' else ())
    assert page.operational==model.FAIL
    if fault=='ingest_failure': assert page.row('feed').status==model.FAIL


@pytest.mark.parametrize('guard,negative',[
    ('or worker.effective_status(now) != model.OK','dead'),
    ('or shadow.valid_until != deadline','wrong_deadline'),
])
def test_removing_wait_guards_is_detected(monkeypatch,guard,negative):
    source=textwrap.dedent(inspect.getsource(waiting.from_rows))
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'or False'),'<postclose-wait-falsifier>','exec'),waiting.__dict__,namespace)
    monkeypatch.setattr(waiting,'from_rows',namespace['from_rows'])
    with pytest.raises(AssertionError,match='earned wait'):
        if negative=='dead': test_unhealthy_publisher_cannot_earn_wait('dead')
        else: test_unproved_or_inconsistent_historical_wait_is_refused('wrong_deadline')


def test_removing_feed_projection_is_detected_at_real_routes(monkeypatch):
    monkeypatch.setattr(waiting,'project',lambda row,*a,**kw:row)
    with pytest.raises(AssertionError,match='remained red'):
        test_real_build_json_html_and_health_share_queued_ingest_wait(monkeypatch)
