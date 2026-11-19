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
                 " execution_open_at timestamptz, diagnostic jsonb, next_wake_at timestamptz)")
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    due, started = now-timedelta(seconds=10), now-timedelta(seconds=8)
    deadline, opened = now+timedelta(minutes=1), now+timedelta(hours=8)
    conn.execute("INSERT INTO sentinel_automation_control VALUES(1,5,true,false,'PASS','cert','config')")
    conn.execute("INSERT INTO sentinel_automation_lease VALUES(1,'worker',5,8,%s)", (deadline,))
    conn.execute("INSERT INTO sentinel_automation_service_instances VALUES"
                 " ('worker','PREFLIGHT_RECOVER_CALLBACK',%s,%s,%s)", (started, deadline, now))
    conn.execute("INSERT INTO sentinel_automation_cycles VALUES"
                 " ('cycle','DISCOVERED',5,8,'cert','config',%s,NULL,NULL,NULL,%s,%s,NULL,NULL)",
                 (due, due, opened))
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


def test_unselected_owner_paper_activation_uses_deployment_state_and_retains_legacy_selection(tmp_path, monkeypatch):
    from sentinel import local_paper
    from sentinel.panel import projection_service
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, 'PAfixture')
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', '')
    def built():
        return sources.build_panel(state_dir=tmp_path, database_url='', now=CLOSE)
    fenced = built()
    assert fenced.row('financial_activation').value == 'ACTIVATION PENDING'
    assert fenced.row('financial_activation').effective_status(CLOSE) != model.OK
    assert fenced.row('trial_verification') is None and fenced.row('actual_account') is None
    assert projection_service._financial_receipt_overlay(None, '', fenced,
        now=CLOSE, changed=('PAPER',), facts=None, basis={}) == ({}, {})
    native_rows, errors = sources._automation_rows('')
    authority = model.Row('authority', 'Execution authority', 'WITHDRAWN', model.UNKNOWN,
        operational_fact=model.OperationalFact(kind='AUTHORITY', state='ACTIVATION_VERDICT_WITHDRAWN'))
    monkeypatch.setattr(sources, '_automation_rows',
        lambda _dsn: ([authority if row.key == 'authority' else row for row in native_rows], errors))
    assert built().row('financial_activation').value == 'DISABLED · KILL ENGAGED'
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'paper')
    assert built().row('trial_verification') is not None
    monkeypatch.delenv(local_paper.MODE_ENV)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', '')
    assert built().row('trial_verification') is not None


def test_matching_saved_plan_is_visible_only_as_unadopted_metadata(conn):
    from sentinel.panel.overview import _plan_html
    conn.execute("""CREATE TEMP TABLE sentinel_automation_cycles AS SELECT 'cycle'::text AS cycle_id,
        'PREPARING'::text AS state, 4 AS control_generation, 'deploy'::text AS deployment_id,
        'alpaca'::text AS broker,'account'::text AS broker_account_id,'epoch'::text AS takeover_epoch,
        'certificate'::text AS certificate_sha256,'config'::text AS config_sha256,
        'CONTROLLER'::text AS rollout_mode,2 AS rollout_version,current_date AS decision_session,
        current_date+1 AS effective_session,false AS historical_state_only,NULL::text AS plan_id,
        NULL::text AS failure_code,NULL::text AS failure_detail,
        '3'::text AS data_version,'publication'::text AS publication_fingerprint,
        statement_timestamp()+interval '8 hours' AS execute_at""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_control AS SELECT 1 AS id, true AS enabled,
        false AS kill_switch_engaged,'PASS'::text AS authority_verdict,control_generation AS generation,
        deployment_id,broker,broker_account_id,takeover_epoch,certificate_sha256,config_sha256,
        rollout_mode,rollout_version FROM sentinel_automation_cycles""")
    conn.execute("""CREATE TEMP TABLE sentinel_execution_plans AS SELECT deployment_id,broker,broker_account_id,
        takeover_epoch,decision_session,effective_session,rollout_mode,rollout_version,
        certificate_sha256 AS rollout_certificate_sha256,NULL::text AS superseded_by,
        data_version::integer AS data_version,publication_fingerprint,
        statement_timestamp() AS created_at FROM sentinel_automation_cycles""")
    conn.execute("""CREATE TEMP TABLE sentinel_rollout_state AS SELECT 1 AS id,rollout_mode AS mode,
        rollout_version AS version,certificate_sha256 FROM sentinel_automation_cycles""")
    created, expires = sources._saved_plan_adoption(conn, 'cycle')
    row = model.Row('paper_plan','Next paper plan',model.AWAITING_PLAN_ADOPTION,model.PENDING,
        as_of=created,valid_until=expires)
    view = model.Panel(rows=[row], now=created)
    assert 'Plan saved · awaiting verification' in _plan_html(view)
    assert 'Plan saved · awaiting verification' in presentation.preparation_stage(view)
    assert not row.can_show_paper_plan(created)
    assert presentation.dashboard_health(view)['plan_readiness'] == 'pending'
    assert 'Plan saved' not in _plan_html(replace(view, now=expires))
    for table, field in (
        ('automation_control', 'generation=3'), ('automation_control', 'kill_switch_engaged=true'),
        ('execution_plans', "broker_account_id='other'"), ('execution_plans', 'effective_session=current_date+2'),
        ('execution_plans', "superseded_by='next'"), ('execution_plans', 'data_version=1'),
        ('execution_plans', "publication_fingerprint='old'"), ('rollout_state', "certificate_sha256='old'"),
        ('automation_cycles', "execute_at=clock_timestamp()-interval '1 second'"),
        ('automation_cycles', "state='WAITING_OPEN'"), ('automation_cycles', "plan_id='adopted'"),
    ):
        conn.execute('SAVEPOINT independent')
        conn.execute('UPDATE sentinel_'+table+' SET '+field)
        assert sources._saved_plan_adoption(conn, 'cycle') is None, (table, field)
        conn.execute('ROLLBACK TO SAVEPOINT independent')
    conn.execute('INSERT INTO sentinel_execution_plans SELECT * FROM sentinel_execution_plans')
    with pytest.raises(ValueError, match='multiple matching'):
        sources._saved_plan_adoption(conn, 'cycle')


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
    stage = model.automation_cycle_row(installed=True, enabled=True, cycle_id='close-cycle',
        state='PREPARING', decision_session='2026-11-11', updated_at=CLOSE, execution_open_at=OPEN)
    steps = model.automation_step_rows(installed=True, enabled=True, cycle={
        'cycle_id': 'close-cycle', 'state': 'PREPARING', 'decision_session': '2026-11-11',
        'updated_at': CLOSE, 'execution_open_at': OPEN})
    assert all(row.operational_fact == stage.operational_fact for row in steps)
    panel = model.Panel(rows=[worker, feed, plan, stage], now=now, local_paper_mode=True, operator_review=review,
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
    assert delivery.closing_refresh_deadline(replace(panel, rows=[worker, feed, plan])) is None
    for change in (dict(state='WAITING_OPEN'), dict(session='2026-11-10')):
        fact = stage.operational_fact.model_copy(update=change)
        stopped = replace(stage, operational_fact=fact)
        assert delivery.closing_refresh_deadline(replace(panel, rows=[worker, feed, plan, stopped])) is None


def test_retained_ready_lag_expires_at_the_exchange_close():
    before = CLOSE - timedelta(milliseconds=350)
    feed = model.feed_row(frontier='2026-11-10', sessions_behind=0, ready=True,
        checks_passed=4, checks_total=4, as_of=before, checked_at=before)
    panel = model.Panel(rows=[feed], now=before, observation_current=False,
        observation_retained=True, observation_generated_at=before,
        observation_changed_scopes=('PAPER',))
    assert delivery.row_current(panel, feed)
    assert not delivery.row_current(replace(panel, now=CLOSE), feed)
    assert delivery.row_current(replace(panel, now=CLOSE), replace(feed, status=model.FAIL))


def test_retained_close_names_only_current_registered_work_on_the_due_session():
    now = CLOSE + timedelta(minutes=4)
    lease = now + timedelta(seconds=3)
    until = now + timedelta(seconds=9)
    work = model.PreparationWork(job_id='close-job', decision_session='2026-11-11',
        effective_session='2026-11-12', state='ACQUIRING', rows_done=1200, components_done=2,
        created_at=CLOSE, updated_at=now, last_progress_at=now, observed_at=now,
        deadline=OPEN, lease_until=lease, owner_registered=True, fence=1)
    ingest = model.Row('ingest', 'Ingest', 'ACQUIRING', model.WARN, as_of=now,
                       preparation=work, valid_until=until)
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK, as_of=now,
                       required_current=True, valid_until=until)
    feed = replace(model.feed_row(frontier='2026-11-10', sessions_behind=1,
        ready=True, checks_passed=4, checks_total=4, as_of=now, checked_at=now),
        status=model.WARN, valid_until=until, recovery=model.RecoveryEvidence(
            phase='POST_CLOSE_SOURCE_WAIT', automatic=True, deadline=until))
    review = OperatorReview(scope='1'*64, head=1, reviewed_head=0, status='REVIEW', observed_at=now)
    panel = model.Panel(rows=[worker, feed, ingest], now=now, local_paper_mode=True,
        operator_review=review, observation_current=False, observation_retained=True,
        observation_generated_at=now, observation_valid_until=until)
    assert delivery.closing_refresh_deadline(panel) == lease
    assert not delivery.display_current(panel)
    assert presentation.dashboard_health(panel)['plan_readiness'] == 'unavailable'
    assert delivery.closing_refresh_deadline(replace(panel, now=lease)) is None
    for changes in ({'owner_registered': False}, {'decision_session': CLOSE.date()-timedelta(days=1)}):
        changed = replace(ingest, preparation=work.model_copy(update=changes))
        assert delivery.closing_refresh_deadline(replace(panel, rows=[worker, feed, changed])) is None
