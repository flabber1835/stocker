from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sentinel.panel import delivery, model, postclose_feed_wait, presentation, sources
from sentinel.panel.render import render
from sentinel.panel.review_model import OperatorReview
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg  # noqa: F401


CLOSE = datetime(2026, 11, 11, 21, tzinfo=timezone.utc)
OPEN = datetime(2026, 11, 12, 14, 30, tzinfo=timezone.utc)


def test_live_preflight_callback_is_bound_to_the_planless_current_fence(conn, monkeypatch):
    conn.execute("CREATE TEMP TABLE sentinel_automation_control (id int, generation int,"
                 " enabled bool, kill_switch_engaged bool, authority_verdict text,"
                 " certificate_sha256 text, config_sha256 text)")
    conn.execute("CREATE TEMP TABLE sentinel_automation_lease (id int, holder_id text,"
                 " control_generation int, fence_token int, expires_at timestamptz)")
    conn.execute("CREATE TEMP TABLE sentinel_automation_service_instances (instance_id text, state text,"
                 " callback_started_at timestamptz, callback_deadline_at timestamptz, heartbeat_at timestamptz)")
    conn.execute("CREATE TEMP TABLE sentinel_automation_cycles (cycle_id text, state text, control_generation int,"
                 " last_fence_token int, certificate_sha256 text, config_sha256 text, updated_at timestamptz,"
                 " plan_id text, failure_code text, failure_detail text, prepare_at timestamptz,"
                 " execution_open_at timestamptz)")
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    due, started = now-timedelta(seconds=10), now-timedelta(seconds=8)
    deadline, opened = now+timedelta(minutes=1), now+timedelta(hours=8)
    conn.execute("INSERT INTO sentinel_automation_control VALUES(1,5,true,false,'PASS','cert','config')")
    conn.execute("INSERT INTO sentinel_automation_lease VALUES(1,'worker',5,8,%s)", (deadline,))
    conn.execute("INSERT INTO sentinel_automation_service_instances VALUES"
                 " ('worker','PREFLIGHT_RECOVER_CALLBACK',%s,%s,%s)", (started, deadline, now))
    conn.execute("INSERT INTO sentinel_automation_cycles VALUES"
                 " ('cycle','DISCOVERED',5,8,'cert','config',%s,NULL,NULL,NULL,%s,%s)", (due, due, opened))
    callback = sources._broker_callback(conn, 'cycle', 'DISCOVERED')
    assert callback == {'started_at': started, 'deadline': deadline}
    cycle = dict(state='DISCOVERED', cycle_id='cycle', prepare_at=due, updated_at=due,
                 execution_open_at=opened, observation_callback=callback)
    broker_wait = sources._observation_recovery(cycle)
    assert broker_wait.deadline == deadline
    workflow = replace(broker_wait, phase='AUTOMATION_PREFLIGHT_RECOVER')
    cycle['preflight_recovery'] = workflow
    summary = model.automation_cycle_row(installed=True, enabled=True, cycle_id='cycle',
        state='DISCOVERED', prepare_at=due, updated_at=due, preflight_recovery=workflow)
    step = model.automation_step_rows(installed=True, enabled=True, cycle=cycle)[0]
    broker = model.broker_row(available=True, positions=12, working_orders=0, completeness='COMPLETE',
        runtime_state='RUNNING', as_of=due-timedelta(minutes=20), valid_until=due, recovery=broker_wait)
    assert [row.effective_status(now) for row in (summary, step, broker)] == [model.WARN]*3
    assert [row.effective_status(deadline+timedelta(microseconds=1))
            for row in (summary, step, broker)] == [model.FAIL]*3
    unsafe = model.broker_row(available=True, positions=12, uncertain_commands=1, completeness='COMPLETE',
        runtime_state='RUNNING', as_of=due, valid_until=due, recovery=broker_wait)
    assert unsafe.effective_status(now) == model.FAIL

    def rejects_foreign_fence():
        assert sources._broker_callback(conn, 'cycle', 'DISCOVERED') is None
    conn.execute("UPDATE sentinel_automation_cycles SET last_fence_token=7")
    rejects_foreign_fence()
    from sentinel.automation import callback_observation
    active = callback_observation.active_instance
    guard = 'c.last_fence_token=l.fence_token'
    assert guard in active('sampled.at')
    monkeypatch.setattr(callback_observation, 'active_instance',
        lambda clock: active(clock).replace(guard, 'TRUE'))
    with pytest.raises(AssertionError):
        rejects_foreign_fence()


def test_data_only_wake_does_not_expire_fresh_broker_evidence():
    checked, retry = CLOSE+timedelta(seconds=56), CLOSE+timedelta(seconds=68)
    cycle = dict(state='RETRY_WAIT', retry_phase='REFRESH', prepare_at=CLOSE,
                 execution_open_at=OPEN, next_wake_at=retry)
    assert sources._runtime_valid_until(cycle, checked, broker_fact=True) == OPEN
    assert sources._runtime_valid_until(cycle, checked) == retry
    assert sources._runtime_valid_until(dict(cycle, retry_phase='PREPARE'), checked, broker_fact=True) == retry


def test_initial_close_wait_needs_verified_prior_book_and_live_preflight():
    now = CLOSE+timedelta(seconds=9)
    deadline = now+timedelta(seconds=12)
    book = model.ShadowBook(session='2026-11-10', cash='100', receivables='0',
        nav='100', pending_operations=0, holdings=[], slots=[])
    financial = [
        model.Row('book', 'Book', 'VERIFIED', model.OK, shadow_book=book),
        model.Row('shadow_verification', 'Shadow', 'VERIFIED', model.OK,
            operational_fact=model.OperationalFact(kind='SHADOW_VERIFICATION', state='VERIFIED',
                                                    session='2026-11-10')),
    ]
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK, as_of=now,
                       required_current=True, valid_until=deadline)
    leader = replace(worker, key='automation_leader')
    control = model.automation_row(installed=True, enabled=True, killed=False, generation=1)
    cycle = model.automation_cycle_row(installed=True, enabled=True, cycle_id='cycle',
        state='DISCOVERED', prepare_at=CLOSE, updated_at=CLOSE,
        preflight_recovery=model.RecoveryEvidence(phase='AUTOMATION_PREFLIGHT_RECOVER',
            automatic=True, deadline=now+timedelta(minutes=2)))
    feed = model.feed_row(frontier='2026-11-10', sessions_behind=1, ready=True,
        checks_passed=4, checks_total=4, as_of=CLOSE-timedelta(days=1), checked_at=CLOSE)
    ingest = model.Row('ingest', 'Ingest', 'PUBLISHED', model.OK, as_of=feed.as_of)
    def projected(*, rows=financial, leader=leader, feed=feed, instant=now):
        return postclose_feed_wait.project_progress(
            [feed, ingest], [leader, control, cycle], rows, worker, now=instant)[0][0]
    assert projected().effective_status(now) == model.WARN
    assert projected().valid_until == deadline
    assert projected(leader=replace(leader, status=model.FAIL)).effective_status(now) == model.FAIL
    assert projected(rows=financial[:1]).effective_status(now) == model.FAIL
    assert projected(instant=deadline).effective_status(deadline) == model.FAIL


def test_late_authority_preserves_new_persisted_clock_and_refuses_wrong_certificate(monkeypatch):
    now = CLOSE+timedelta(minutes=5, seconds=2)
    digest = 'a'*64
    old = model.Row('authority', 'Authority', 'PASS', model.OK, as_of=CLOSE,
                    freshness=timedelta(minutes=5), required_current=True)
    control = dict(certificate_sha256=digest, authority_verdict='PASS', authority_detail='fresh',
                   authority_checked_at=now-timedelta(seconds=1))
    lifecycle = dict(certificate_sha256=digest, lifecycle_status='ACTIVE', lifecycle_current=True)
    monkeypatch.setattr(sources, '_automation_control', lambda *_: control)
    monkeypatch.setattr(sources, '_authority_lifecycle', lambda *_: lifecycle)
    monkeypatch.setattr(sources, '_read', lambda conn, read, *_args, **_kwargs: (read(conn), None))
    current = sources._late_authority_display(None, old, now=now)
    assert current.effective_status(now) == model.OK
    assert current.as_of == control['authority_checked_at']
    assert current.freshness == old.freshness
    control['certificate_sha256'] = 'b'*64
    assert sources._late_authority_display(None, old, now=now).effective_status(now) == model.FAIL


def test_partial_close_uses_original_progress_and_keeps_affected_rows_unavailable():
    now = CLOSE+timedelta(minutes=10)
    until = now+timedelta(seconds=8)
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK, as_of=now,
                       required_current=True, valid_until=until)
    feed = model.feed_row(frontier='2026-11-11', sessions_behind=0, ready=True,
        checks_passed=4, checks_total=4, as_of=now, checked_at=now)
    plan = model.Row('paper_plan', 'Plan', 'NOT PREPARED', model.PENDING)
    review = OperatorReview(scope='1'*64, head=1, reviewed_head=0, status='REVIEW', observed_at=now)
    panel = model.Panel(rows=[worker, feed, plan], now=now, local_paper_mode=True, operator_review=review,
        observation_current=False, observation_changed_scopes=('PAPER',),
        observation_generated_at=now-timedelta(seconds=1), observation_valid_until=until)
    health = presentation.dashboard_health(panel)
    assert (health['color'], health['plan_readiness'], health['valid_until']) == (
        'amber', 'unavailable', until.isoformat())
    assert 'data-closing-refresh="true"' in render(panel)
    assert not delivery.display_current(panel) and not delivery.row_current(panel, plan)
    lost = replace(panel, rows=[replace(worker, status=model.FAIL), feed, plan])
    assert presentation.dashboard_health(lost)['color'] == 'red'
    lost = replace(panel, observation_changed_scopes=('SHADOW', 'PAPER'))
    assert presentation.dashboard_health(lost)['color'] == 'neutral'
    assert delivery.closing_refresh_deadline(replace(panel, now=until)) is None
