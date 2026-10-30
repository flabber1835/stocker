"""Current future scheduling never erases an authenticated historical warning."""
from dataclasses import replace
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest

from sentinel.panel import model, observer_codec, presentation, sources
from sentinel.paper_plan_preview import PlanPreview
from tests.sentinel.test_local_paper_panel_schedule import (
    NOW, OPEN, panel,
    test_future_unstamped_plan_requires_bound_local_scheduled_proof as scheduled_source_case,
)


def history_row():
    return model.paper_reconciliation_row(state='SCHEDULED_WITH_HISTORY',
        cycle_state='WAITING_OPEN', scheduled_until=OPEN,
        detail='Current future plan is scheduled; one earlier-plan mismatch remains historical.')


def test_historical_warning_remains_amber_and_cannot_be_the_normal_green_schedule_exception():
    row = history_row()
    assert row.status == row.effective_status(NOW) == model.WARN
    assert row.paper_alignment == 'SCHEDULED_WITH_HISTORY'
    assert row.effective_status(OPEN) == model.FAIL
    page = panel(scheduled=False)
    page.rows.append(row)
    assert page.operational == model.WARN
    assert presentation.dashboard_health(page)['color'] != 'green'
    assert 'NOT VERIFIED' in row.value and 'HISTORICAL' in row.value


def test_history_alignment_roundtrips_the_existing_observer_codec_without_claiming_success():
    row = history_row()
    encoded = observer_codec.pack([row], [], observed_at=NOW)['rows'][0]
    decoded = observer_codec.row_from_observation(encoded)
    assert decoded == row
    assert decoded.effective_status(NOW) == model.WARN
    assert decoded.recovery is None and decoded.required_current


def test_json_preserves_the_typed_historical_warning_and_native_expiry(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app
    page = panel(scheduled=False)
    page.rows.append(history_row())
    monkeypatch.setattr(app, '_read_panel', lambda: page)
    with TestClient(app.app) as client:
        body = client.get('/panel.json').json()
    row = next(item for item in body['rows'] if item['key'] == 'paper_reconciliation')
    assert row['paper_alignment'] == 'SCHEDULED_WITH_HISTORY'
    assert row['status'] == 'warn' and row['color'] == 'amber'
    assert row['valid_until'] == history_row().valid_until.isoformat()
    assert body['dashboard_health']['color'] != 'green'


@pytest.mark.parametrize('changes', [
    {'paper_alignment':'UNRECOGNIZED_HISTORY'}, {'valid_until':None},
    {'valid_until':OPEN.replace(tzinfo=None)}, {'required_current':False},
    {'status':model.OK}, {'key':'other'},
    {'recovery':{'phase':'AUTOMATION_OPEN','automatic':True,'deadline':OPEN}},
])
def test_malformed_history_flag_or_missing_native_bound_is_refused(changes):
    encoded = observer_codec.pack([history_row()], [], observed_at=NOW)['rows'][0]
    encoded.update(changes)
    with pytest.raises(ValueError):
        observer_codec.row_from_observation(encoded)


@pytest.mark.parametrize('changes', [
    {'required_current':False}, {'status':model.OK}, {'valid_until':None},
    {'recovery':model.RecoveryEvidence(phase='AUTOMATION_OPEN',automatic=True,deadline=OPEN)},
])
def test_internal_malformed_history_warning_cannot_hide_current_failure(changes):
    assert replace(history_row(), **changes).effective_status(NOW) == model.FAIL


@pytest.mark.parametrize('case', ['global_history', 'stamped_history'])
def test_historical_warning_has_an_executed_false_green_falsifier(monkeypatch, case):
    source = inspect.getsource(sources._scheduled_paper_mirror)
    guard = "state='SCHEDULED_WITH_HISTORY'"
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, "state='SCHEDULED'"),
        '<historical-warning-erased>', 'exec'), namespace)
    monkeypatch.setattr(sources, '_scheduled_paper_mirror', namespace['_scheduled_paper_mirror'])
    with pytest.raises(AssertionError):
        scheduled_source_case(
            monkeypatch, True, True, case, model.WARN)


LIVE_NOW = datetime(2026,10,30,22,15,tzinfo=timezone.utc)
LIVE_OPEN = datetime(2026,11,2,14,31,tzinfo=timezone.utc)


def healthy_history_panel(*, now=LIVE_NOW, execute_at=LIVE_OPEN):
    """The represented Oct 30 -> Nov 2 quiescent plan, with its retained audit."""
    decision, effective = date(2026,10,30), date(2026,11,2)
    plan = PlanPreview(cycle_id='current-generation-86-cycle',plan_id='current-november-2-plan',
        decision_session=decision,effective_session=effective,execute_at=execute_at,
        created_at=now-timedelta(minutes=2),observation_at=now-timedelta(minutes=3),legs=[])
    current = now+timedelta(minutes=10)
    account = model.alpaca_account_row(available=True,broker='alpaca',
        account_id='PA3NDXAHULSS',expected_account_id='PA3NDXAHULSS',status='ACTIVE',
        flags={},equity='50000',cash='10000',buying_power='10000',multiplier='1',
        observed_at=now,valid_until=current)
    account = replace(account,paper_account=model.PaperAccountOverview(
        account_id='PA3NDXAHULSS',equity=Decimal('50000'),cash=Decimal('10000'),
        buying_power=Decimal('10000'),observed_at=now))
    rows = [replace(model.paper_reconciliation_row(state='SCHEDULED_WITH_HISTORY',
        cycle_state='WAITING_OPEN',scheduled_until=execute_at,
        detail='Historical Oct 20 informational corporate-action discrepancy remains recorded.'),
        as_of=now,freshness=timedelta(minutes=10)),
        model.Row('paper_plan','Next paper plan','SAVED',model.OK,
            as_of=now-timedelta(minutes=2),valid_until=execute_at,paper_plan=plan),
        model.automation_row(installed=True,enabled=True,killed=False,generation=86,
            updated_at=now-timedelta(hours=3)),
        model.automation_leader_row(installed=True,enabled=True,killed=False,holder='current-owner',
            fence=128,heartbeat_at=now,expires_at=now+timedelta(seconds=12),active=True),
        account,
        model.broker_row(available=True,positions=13,completeness='COMPLETE',runtime_state='RUNNING',
            working_orders=0,active_commands=0,uncertain_commands=0,
            command_counts={'PLANNED':0,'ACKNOWLEDGED':0,'UNKNOWN':0},
            as_of=now,valid_until=current),
        model.feed_row(frontier=str(decision),sessions_behind=0,ready=True,
            checks_passed=14,checks_total=14,as_of=now,checked_at=now),
        model.Row('shadow_worker','Worker','RUNNING',model.OK,as_of=now,
            required_current=True,valid_until=now+timedelta(seconds=60)),
        model.Row('shadow_verification','Shadow','SHADOW VERIFIED THROUGH '+str(decision),model.OK,
            as_of=now,freshness=timedelta(minutes=10),required_current=True),
        model.Row('authority','Authority','PASS · active-certificate',model.OK,as_of=now,
            freshness=timedelta(minutes=5),required_current=True),
        model.Row('runtime_identity','Runtime','LOCAL PAPER 7da48b22',model.OK,
            as_of=now,required_current=True),
        model.Row('backup_restore','Backup','BASE 1h · RESTORE 1d',model.OK,
            as_of=now,required_current=True),
        model.Row('alert_dispatcher','Delivery','RUNNING',model.OK,as_of=now,required_current=True),
        model.automation_alerts_row(installed=True,pending=0,dead_letter=0,unacknowledged=0,as_of=now)]
    rows += [model.Row(key,key,'VERIFIED',model.OK,as_of=now,
        freshness=timedelta(minutes=10),required_current=True) for key in ('book','exposure','terminals')]
    rows += [model.Row(key,key,'WAITING_OPEN',model.WARN,
        as_of=now-timedelta(minutes=2),required_current=True,
        recovery=model.RecoveryEvidence(phase=phase,automatic=True,
            next_attempt_at=execute_at,deadline=execute_at+timedelta(hours=6)))
        for key,phase in (('automation_cycle','AUTOMATION_WAITING_OPEN'),
                          ('automation_step_open','AUTOMATION_OPEN'))]
    rows.append(model.Row('automation_step_transport','Transport','NOT REACHED',model.PENDING))
    return model.Panel(rows=rows,now=now,local_paper_mode=True)


def changed_history_panel(panel,key,**changes):
    return replace(panel,rows=[replace(row,**changes) if row.key==key else row for row in panel.rows])


def checking_schedule_panel(*, now=LIVE_NOW, check_seconds=120):
    page = healthy_history_panel(now=now)
    deadline = now+timedelta(seconds=check_seconds)
    checking = model.Row('paper_reconciliation','Paper alignment','CHECK IN PROGRESS',model.WARN,
        'No current financial verification is claimed.',required_current=True,valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline))
    return replace(page,rows=[checking if row.key=='paper_reconciliation' else row for row in page.rows])


def test_complete_current_schedule_is_human_green_while_the_historical_audit_stays_financial_amber():
    from sentinel.panel.render import render
    page = healthy_history_panel()
    before = deepcopy(page)
    health = presentation.dashboard_health(page)
    assert health['status']=='ok' and health['color']=='green'
    assert health['label']=='Healthy · Waiting for market open'
    assert health['plan_readiness']=='ready'
    assert page.overall==page.operational==model.WARN
    audit = page.row('paper_reconciliation')
    assert audit.status==audit.effective_status(page.now)==model.WARN
    assert audit.paper_alignment=='SCHEDULED_WITH_HISTORY' and 'NOT VERIFIED' in audit.value
    html = render(page)
    front = html.split('<details id="system-details"',1)[0]
    assert 'class="state ok"' in front and 'Checks needing attention' not in front
    assert 'Historical paper audit' not in front
    assert 'Historical paper audit' in html and 'Earlier-plan discrepancy retained' in html
    assert 'Historical Oct 20 informational corporate-action discrepancy remains recorded.' in html
    assert 'class="row warn" id="status-paper_reconciliation"' in html
    assert 'Next trading plan: saved for its scheduled market open.' in front
    assert page==before


def test_history_human_health_json_does_not_rewrite_financial_or_machine_verdicts(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app
    page = healthy_history_panel()
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    with TestClient(app.app) as client:
        body = client.get('/panel.json').json()
    audit = next(row for row in body['rows'] if row['key']=='paper_reconciliation')
    assert (body['overall'],body['operational'],body['color'])==('warn','warn','amber')
    assert body['dashboard_health']['color']=='green'
    assert (audit['status'],audit['color'],audit['paper_alignment'])==('warn','amber','SCHEDULED_WITH_HISTORY')
    assert audit['value']==page.row('paper_reconciliation').value
    assert audit['detail']==page.row('paper_reconciliation').detail


def test_audit_display_copy_is_not_the_scheduling_authority():
    page = healthy_history_panel()
    changed = changed_history_panel(page,'paper_reconciliation',
        value='Historical audit wording from another compatible renderer',
        detail='The original authenticated historical evidence remains recorded.')
    assert presentation.dashboard_health(changed)['color']=='green'
    assert changed.row('paper_reconciliation').status==model.WARN
    # Familiar display text cannot replace the native typed scheduling fact.
    untyped = changed_history_panel(changed,'paper_reconciliation',paper_alignment=None)
    assert presentation.dashboard_health(untyped)['color']!='green'


@pytest.mark.parametrize('key', [*presentation._HISTORY_CURRENT_FACTS,
    'paper_plan','automation_cycle','automation_step_open'])
def test_missing_current_capabilities_cannot_borrow_a_historical_schedule_flag(key):
    page = healthy_history_panel()
    page = replace(page,rows=[row for row in page.rows if row.key!=key])
    assert presentation.dashboard_health(page)['color']!='green'


@pytest.mark.parametrize('key',['alpaca_account','broker','feed','automation_leader','authority','shadow_worker'])
@pytest.mark.parametrize('fault',['unknown','expired','future','missing_clock'])
def test_current_unreadable_stale_or_undated_proof_always_wins_over_history(key,fault):
    page = healthy_history_panel()
    changes = {'unknown':{'status':model.UNKNOWN},
        'expired':{'valid_until':page.now-timedelta(seconds=1)},
        'future':{'as_of':page.now+timedelta(seconds=6)},
        'missing_clock':{'as_of':None}}[fault]
    page = changed_history_panel(page,key,**changes)
    assert presentation.dashboard_health(page)['color']!='green'


@pytest.mark.parametrize('fault',['current_mismatch','restriction_retry','account_blocked',
    'kill','broker_unknown','other_warning','source_error','expired_history','missing_flag',
    'wrong_boundary','wrong_frontier','wrong_shadow','duplicate','normal_release'])
def test_present_current_restrictions_and_scope_faults_are_never_historical_audit_clearance(fault):
    page = healthy_history_panel()
    if fault=='current_mismatch':
        page = changed_history_panel(page,'paper_reconciliation',paper_alignment=None,
            status=model.FAIL,value='PAPER NOT VERIFIED · MISMATCH · BLOCKED')
    elif fault=='restriction_retry':
        page = changed_history_panel(page,'automation_cycle',value='RETRY_WAIT',
            detail='Current reconciliation reported a restricted security.',
            recovery=model.RecoveryEvidence(phase='AUTOMATION_RECOVER',automatic=True,
                deadline=page.now+timedelta(minutes=5)))
    elif fault=='account_blocked':
        page = changed_history_panel(page,'alpaca_account',status=model.FAIL,value='ACTIVE · BLOCKED')
    elif fault=='kill':
        page = changed_history_panel(page,'automation',status=model.FAIL,value='ENABLED · KILLED')
    elif fault=='broker_unknown':
        page = changed_history_panel(page,'broker',status=model.UNKNOWN,value='OUTCOME UNKNOWN')
    elif fault=='other_warning':
        page = replace(page,rows=[*page.rows,model.Row('other','Other','NEEDS REVIEW',model.WARN)])
    elif fault=='source_error': page = replace(page,source_errors=['current source unavailable'])
    elif fault=='expired_history':
        page = changed_history_panel(page,'paper_reconciliation',valid_until=page.now-timedelta(seconds=1))
    elif fault=='missing_flag': page = changed_history_panel(page,'paper_reconciliation',paper_alignment=None)
    elif fault=='wrong_boundary': page = changed_history_panel(page,'paper_reconciliation',valid_until=LIVE_OPEN)
    elif fault=='wrong_frontier': page = changed_history_panel(page,'feed',value='2026-10-29 · 0 sessions behind')
    elif fault=='wrong_shadow':
        page = changed_history_panel(page,'shadow_verification',value='SHADOW VERIFIED THROUGH 2026-10-29')
    elif fault=='duplicate': page = replace(page,rows=[*page.rows,page.row('authority')])
    elif fault=='normal_release': page = replace(page,local_paper_mode=False)
    assert presentation.dashboard_health(page)['color']!='green'


def test_original_audit_and_current_proof_deadlines_bound_human_green_and_expire_at_execution():
    from sentinel.panel.render import render
    page = healthy_history_panel()
    assert presentation.dashboard_health(page)['valid_until']==(page.now+timedelta(seconds=12)).isoformat()
    assert 'data-max-age-seconds="12.0"' in render(page) and 'refreshes every 6s' in render(page)
    imminent = healthy_history_panel(now=LIVE_OPEN-timedelta(seconds=8))
    assert presentation.dashboard_health(imminent)['valid_until']==(LIVE_OPEN-timedelta(microseconds=1)).isoformat()
    assert 'data-max-age-seconds="7.999999"' in render(imminent)
    expired = replace(imminent,now=LIVE_OPEN)
    assert presentation.dashboard_health(expired)['color']=='red'
    assert 'Current scheduled proof cannot be confirmed' in render(expired)
    retained = render(page,refresh_pending=True)
    assert 'class="state ok"' not in retained.split('</header>',1)[0]
    assert page.row('paper_reconciliation').status==model.WARN


def test_missing_current_clock_guard_has_an_executed_false_green_falsifier(monkeypatch):
    source = inspect.getsource(presentation._current_health_fact)
    guard = 'or not _aware(row.as_of)'
    assert source.count(guard)==1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard,''),'<missing-current-proof-clock>','exec'),namespace)
    monkeypatch.setattr(presentation,'_current_health_fact',namespace['_current_health_fact'])
    with pytest.raises(AssertionError):
        test_current_unreadable_stale_or_undated_proof_always_wins_over_history('alpaca_account','missing_clock')


def test_periodic_owned_paper_check_keeps_healthy_scheduling_green_without_claiming_financial_pass():
    from sentinel.panel.render import render
    page = checking_schedule_panel()
    before = deepcopy(page)
    health = presentation.dashboard_health(page)
    assert health['label']=='Healthy · Checking paper account'
    assert health['color']=='green' and health['plan_readiness']=='ready'
    assert page.overall==page.operational==model.WARN
    assert page.row('paper_reconciliation').paper_alignment is None
    assert page.row('paper_reconciliation').as_of is None  # Existing owned-check wire shape.
    html = render(page)
    assert 'Healthy · Checking paper account</span>' in html
    assert 'class="row warn" id="status-paper_reconciliation"' in html
    assert 'Historical paper audit' not in html
    assert 'No current financial verification is claimed.' in html
    assert page==before


def test_periodic_check_label_precedes_a_retained_published_job():
    page = checking_schedule_panel()
    now = page.now
    work = model.PreparationWork(job_id='published-october-30',decision_session=date(2026,10,30),
        effective_session=date(2026,11,2),state='PUBLISHED',rows_done=1720712,components_done=31,
        created_at=now-timedelta(minutes=20),updated_at=now-timedelta(minutes=2),
        last_progress_at=now-timedelta(minutes=2),observed_at=now,deadline=now+timedelta(hours=1),
        owner_registered=False,fence=4)
    page = replace(page,rows=[*page.rows,model.Row('ingest','Acquisition','PUBLISHED',model.OK,
        as_of=work.updated_at,preparation=work)])
    assert presentation.preparation_stage(page)=='Checking paper account'
    assert presentation.dashboard_health(page)['label']=='Healthy · Checking paper account'


@pytest.mark.parametrize('fault',['wrong_phase','dead_owner','operator_required','missing_owner',
    'expired','changed_deadline','not_required','current_fail','current_unknown','other_warning',
    'restriction_retry','missing_account','stale_source','wrong_value'])
def test_only_current_owned_bounded_paper_checks_can_explain_a_scheduled_wait(fault):
    page = checking_schedule_panel()
    check = page.row('paper_reconciliation')
    if fault=='wrong_phase': check = replace(check,recovery=replace(check.recovery,phase='SOMETHING_ELSE'))
    elif fault=='dead_owner': check = replace(check,recovery=replace(check.recovery,automatic=False))
    elif fault=='operator_required': check = replace(check,recovery=replace(check.recovery,operator_required=True))
    elif fault=='missing_owner':
        check = replace(check,status=model.UNKNOWN,value='OWNER UNAVAILABLE',recovery=None)
    elif fault=='expired': page = replace(page,now=check.valid_until+timedelta(seconds=1))
    elif fault=='changed_deadline': check = replace(check,valid_until=check.valid_until+timedelta(seconds=1))
    elif fault=='not_required': check = replace(check,required_current=False)
    elif fault=='current_fail': check = replace(check,status=model.FAIL)
    elif fault=='current_unknown': check = replace(check,status=model.UNKNOWN)
    elif fault=='other_warning':
        page = replace(page,rows=[*page.rows,model.Row('other','Other','UNEXPECTED',model.WARN)])
    elif fault=='restriction_retry':
        page = changed_history_panel(page,'automation_cycle',value='RETRY_WAIT')
    elif fault=='missing_account': page = replace(page,rows=[row for row in page.rows if row.key!='alpaca_account'])
    elif fault=='stale_source':
        page = changed_history_panel(page,'feed',valid_until=page.now-timedelta(seconds=1))
    elif fault=='wrong_value': check = replace(check,value='WAITING')
    page = replace(page,rows=[check if row.key=='paper_reconciliation' else row for row in page.rows])
    assert presentation.dashboard_health(page)['color']!='green'


def test_periodic_paper_check_keeps_its_original_deadline_and_leader_bound():
    from sentinel.panel.render import render
    page = checking_schedule_panel()
    assert presentation.dashboard_health(page)['valid_until']==(page.now+timedelta(seconds=12)).isoformat()
    near = checking_schedule_panel(check_seconds=4)
    assert presentation.dashboard_health(near)['valid_until']==near.row('paper_reconciliation').valid_until.isoformat()
    assert 'data-max-age-seconds="4.0"' in render(near) and 'refreshes every 5s' in render(near)
    assert presentation.dashboard_health(replace(near,now=near.row('paper_reconciliation').valid_until))['color']!='green'


def test_periodic_check_phase_guard_has_an_executed_false_green_falsifier(monkeypatch):
    source = inspect.getsource(presentation._paper_check_normal)
    guard = "and recovery.phase == 'FINANCIAL_VERIFICATION'"
    assert source.count(guard)==1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard,''),'<missing-bounded-paper-check-phase>','exec'),namespace)
    monkeypatch.setattr(presentation,'_paper_check_normal',namespace['_paper_check_normal'])
    with pytest.raises(AssertionError):
        test_only_current_owned_bounded_paper_checks_can_explain_a_scheduled_wait('wrong_phase')
