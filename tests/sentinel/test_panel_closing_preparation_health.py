"""Routine next-plan work does not manufacture a PAPER incident."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import inspect
import pytest

from sentinel.panel import model,presentation
from tests.sentinel.test_panel_closing_data_wait import closing_cycle,projections,NOW,OPEN
from tests.sentinel.test_panel_postclose_feed_wait import facts,project
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel,changed_history_panel


def preparing_panel():
    base=healthy_history_panel(now=NOW,execute_at=OPEN+timedelta(seconds=1))
    _,cycle,steps,_=projections(closing_cycle())
    financial,worker=facts(now=NOW,frontier='2026-10-21',deadline=OPEN)
    financial={r.key:r for r in financial}
    rows=[r for r in base.rows if r.key not in {'paper_reconciliation','paper_plan','automation_cycle','automation_step_open','automation_step_transport','shadow_worker'}]
    rows=[financial.get(r.key,r) for r in rows]
    rows += [worker,cycle,*steps,
        model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        replace(model.paper_reconciliation_row(state='PENDING',cycle_state='RETRY_WAIT'),
                as_of=NOW, freshness=timedelta(minutes=10))]
    # The actual feed row has its own independently typed close-wait proof.
    rows=[r for r in rows if r.key!='feed']+[project(now=NOW,frontier='2026-10-21',
        financial=list(financial.values()),worker=worker)]
    return replace(base,rows=rows)


def test_reproduced_next_close_pending_paper_is_normal_work():
    page=preparing_panel();before=deepcopy(page)
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    assert presentation.dashboard_health(page)['color']=='green'
    assert presentation.dashboard_health(page)['plan_readiness']=='pending'
    assert page.row('paper_reconciliation').status==model.WARN
    assert 'NOT VERIFIED' in page.row('paper_reconciliation').value and page==before


@pytest.mark.parametrize('fault', [None, 'expired', 'manual', 'wrong_phase', 'wrong_boundary'])
def test_source_wait_exposure_keeps_its_own_proof_during_plan_preparation(fault):
    page = preparing_panel()
    prior = page.row('book')
    recovery = prior.recovery
    if fault == 'manual':
        recovery = replace(recovery, operator_required=True)
    elif fault == 'wrong_phase':
        recovery = replace(recovery, phase='AUTOMATION_OPEN')
    page = changed_history_panel(page, 'exposure', status=model.WARN,
        value='LAST ATTESTED THROUGH 2026-10-21', as_of=prior.as_of, freshness=None,
        recovery=recovery, required_current=True,
        valid_until=NOW if fault == 'expired' else recovery.deadline - timedelta(seconds=1)
            if fault == 'wrong_boundary' else recovery.deadline)
    facts = presentation.health_facts(page)
    assert ('exposure' in facts['active'] + facts['warnings']) is (fault is not None)
    if fault is None:
        assert presentation.dashboard_health(page)['color'] == 'green'


def test_reproduced_completed_check_does_not_create_new_review():
    page=preparing_panel();deadline=NOW+timedelta(minutes=3)
    check=model.Row('paper_reconciliation','Alignment','CHECK IN PROGRESS',model.WARN,
        required_current=True,valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline),
        operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'))
    checking=replace(page,rows=[check if r.key=='paper_reconciliation' else r for r in page.rows])
    assert presentation.health_facts(checking)==presentation.health_facts(page)=={'active':[],'warnings':[]}


@pytest.mark.parametrize('state',['REFRESHING_DATA','PREPARING','PLAN_READY'])
@pytest.mark.parametrize('checking',[False,True])
def test_normal_cycle_transitions_do_not_reintroduce_review(state,checking):
    from datetime import date
    from sentinel.paper_plan_preview import PlanPreview
    page=preparing_panel();recovery=model.RecoveryEvidence(phase='AUTOMATION_'+state,
        automatic=True,deadline=OPEN if state!='PLAN_READY' else OPEN+timedelta(hours=6))
    rows=[replace(r,status=model.OK,recovery=None,as_of=NOW) if r.recovery and r.key!='automation_cycle' else r for r in page.rows]
    page=replace(page,rows=rows)
    page=changed_history_panel(page,'feed',value='2026-10-22 · 0 sessions behind',
        operational_fact=model.OperationalFact(kind='MARKET_DATA',state='READY',session=date(2026,10,22),sessions_behind=0))
    page=changed_history_panel(page,'shadow_verification',value='SHADOW VERIFIED THROUGH 2026-10-22',
        operational_fact=model.OperationalFact(kind='SHADOW_VERIFICATION',state='VERIFIED',session=date(2026,10,22)))
    book=page.row('book').shadow_book.model_copy(update={'session':'2026-10-22'})
    page=changed_history_panel(page,'book',shadow_book=book)
    page=changed_history_panel(page,'automation_cycle',value=state,status=model.WARN,recovery=recovery,valid_until=None)
    current='automation_step_open' if state=='PLAN_READY' else 'automation_step_prepare' if state=='PREPARING' else 'automation_step_data'
    page=changed_history_panel(page,current,value=state,status=model.WARN,recovery=recovery,required_current=True,as_of=NOW)
    if state=='PLAN_READY':
        plan=PlanPreview(cycle_id='next-cycle',plan_id='next-plan',decision_session=date(2026,10,22),
            effective_session=date(2026,10,23),execute_at=OPEN+timedelta(seconds=1),
            created_at=NOW,observation_at=NOW-timedelta(seconds=1),legs=[])
        page=changed_history_panel(page,'paper_plan',value='SAVED',status=model.OK,paper_plan=plan,as_of=NOW,valid_until=plan.execute_at)
    if checking:
        deadline=NOW+timedelta(minutes=3)
        page=changed_history_panel(page,'paper_reconciliation',value='CHECK IN PROGRESS',as_of=None,
            operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'),
            required_current=True,valid_until=deadline,recovery=model.RecoveryEvidence(
                phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline))
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    health = presentation.dashboard_health(page)
    assert health['color'] == 'green'
    if state == 'PREPARING':
        assert health['label'].startswith('Healthy') and health['plan_readiness'] == 'pending'


@pytest.mark.parametrize('key',presentation._HISTORY_CURRENT_FACTS)
@pytest.mark.parametrize('defect',['missing','unknown','expired','future','undated'])
def test_current_safety_capability_cannot_be_borrowed(key,defect):
    page=preparing_panel()
    if defect=='missing':page=replace(page,rows=[r for r in page.rows if r.key!=key])
    else:page=changed_history_panel(page,key,**{'unknown':{'status':model.UNKNOWN},
        'expired':{'valid_until':NOW-timedelta(seconds=1)},'future':{'as_of':NOW+timedelta(seconds=6)},
        'undated':{'as_of':None}}[defect])
    assert presentation.dashboard_health(page)['color']!='green'


def corrupt(page,defect):
    if defect=='source_proof':
        return replace(page,rows=[replace(r,status=model.OK,recovery=None) if r.recovery and r.recovery.phase in {'SOURCE_FRONTIER','POST_CLOSE_SOURCE_WAIT','SOURCE_PUBLICATION','SHADOW_ATTESTATION'} else r for r in page.rows])
    if defect=='generic_retry':
        row=page.row('automation_cycle')
        return changed_history_panel(page,row.key,recovery=replace(row.recovery,phase='AUTOMATION_REFRESH_AVAILABILITY'))
    if defect=='kill':return changed_history_panel(page,'automation',value='ENABLED · KILLED',status=model.FAIL)
    if defect=='source_error':return replace(page,source_errors=['unavailable'])
    if defect=='duplicate':return replace(page,rows=[*page.rows,page.row('authority')])
    if defect=='normal_release':return replace(page,local_paper_mode=False)
    if defect=='mismatch':return changed_history_panel(page,'paper_reconciliation',value='PAPER NOT VERIFIED · MISMATCH · BLOCKED',status=model.FAIL)
    if defect=='paper_unknown':return changed_history_panel(page,'paper_reconciliation',status=model.UNKNOWN)
    if defect=='paper_expired':return changed_history_panel(page,'paper_reconciliation',valid_until=NOW)
    if defect=='paper_undated':return changed_history_panel(page,'paper_reconciliation',as_of=None)
    if defect=='paper_unbounded':return changed_history_panel(page,'paper_reconciliation',freshness=None,valid_until=None)
    if defect=='typed_history':return changed_history_panel(page,'paper_reconciliation',paper_alignment='COMPLETED_WITH_HISTORY')
    if defect=='other_warning':return replace(page,rows=[*page.rows,model.Row('other','Other','Needs attention',model.WARN)])
    if defect=='broker_wait':return changed_history_panel(page,'broker',recovery=model.RecoveryEvidence(phase='BROKER_FILL_SNAPSHOT',automatic=True,deadline=NOW+timedelta(minutes=1)))
    raise AssertionError(defect)


@pytest.mark.parametrize('defect',['source_proof','generic_retry','kill','source_error','duplicate','normal_release',
    'mismatch','paper_unknown','paper_expired','paper_undated','paper_unbounded','typed_history','other_warning','broker_wait'])
def test_preparation_does_not_hide_genuine_failure_or_unproved_work(defect):
    assert presentation.dashboard_health(corrupt(preparing_panel(),defect))['color']!='green'


def test_existing_review_interval_is_never_automatically_acknowledged():
    page=preparing_panel();review=page.operator_review.model_copy(update={'head':2,'reviewed_head':1,'status':'REVIEW'})
    assert presentation.dashboard_health(replace(page,operator_review=review))['color']=='amber'


@pytest.mark.parametrize('key',['paper_plan','automation_cycle','automation_alerts'])
def test_required_preparation_rows_cannot_be_missing(key):
    page=preparing_panel()
    assert not presentation._preparing_work_normal(replace(page,rows=[r for r in page.rows if r.key!=key]))


def test_missing_source_proof_cannot_admit_the_pending_paper_row():
    assert not presentation._preparing_work_normal(corrupt(preparing_panel(),'source_proof'))


def test_original_receipt_and_worker_clocks_still_expire():
    page=changed_history_panel(preparing_panel(),'paper_reconciliation',valid_until=NOW+timedelta(seconds=4))
    assert presentation.dashboard_health(page)['valid_until']==(NOW+timedelta(seconds=4)).isoformat()
    assert presentation.dashboard_health(replace(page,now=NOW+timedelta(seconds=4)))['color']!='green'


def test_raw_json_and_html_keep_financial_warning(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app
    from sentinel.panel.render import render
    page=preparing_panel();monkeypatch.setattr(app,'_read_panel',lambda:page)
    with TestClient(app.app) as client:data=client.get('/panel.json').json()
    row=next(r for r in data['rows'] if r['key']=='paper_reconciliation')
    assert data['dashboard_health']['color']=='green' and row['status']=='warn' and 'NOT VERIFIED' in row['value']
    assert 'class="row warn" id="status-paper_reconciliation"' in render(page)


def test_removed_independent_source_proof_has_executed_falsifier(monkeypatch):
    source=inspect.getsource(presentation._preparing_work_normal);guard='not _closing_source_proof(panel)'
    assert source.count(guard)==1
    namespace=dict(vars(presentation));exec(compile(source.replace(guard,'False'),'<removed preparation source proof>','exec'),namespace)
    monkeypatch.setattr(presentation,'_preparing_work_normal',namespace['_preparing_work_normal'])
    with pytest.raises(AssertionError):test_missing_source_proof_cannot_admit_the_pending_paper_row()


def verified_calculation_panel():
    page=preparing_panel();rows=[replace(r,status=model.OK,recovery=None,as_of=NOW)
        if r.recovery and r.key!='automation_cycle' else r for r in page.rows]
    page=replace(page,rows=rows)
    page=changed_history_panel(page,'feed',value='2026-10-22 · 0 sessions behind',
        operational_fact=model.OperationalFact(kind='MARKET_DATA',state='READY',session=date(2026,10,22),sessions_behind=0))
    page=changed_history_panel(page,'shadow_verification',value='SHADOW VERIFIED THROUGH 2026-10-22',
        operational_fact=model.OperationalFact(kind='SHADOW_VERIFICATION',state='VERIFIED',session=date(2026,10,22)))
    page=changed_history_panel(page,'book',shadow_book=page.row('book').shadow_book.model_copy(update={'session':'2026-10-22'}))
    recovery=model.RecoveryEvidence(phase='AUTOMATION_PREPARING',automatic=True,deadline=OPEN)
    for key in ['automation_cycle','automation_step_prepare']:
        page=changed_history_panel(page,key,value='PREPARING',status=model.WARN,recovery=recovery,required_current=True,as_of=NOW,valid_until=None)
    exposure=model.exposure_row(exposure=.55,controller_active=True,adopted=False,session='2026-10-22',as_of=NOW)
    return replace(page,rows=[exposure if r.key=='exposure' else r for r in page.rows])


def test_native_unadopted_decision_is_expected_only_during_verified_calculation():
    page=verified_calculation_panel();before=deepcopy(page)
    assert page.row('exposure').effective_status(NOW)==model.FAIL
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    health = presentation.dashboard_health(page)
    assert health['color'] == 'green' and health['label'].startswith('Healthy')
    assert health['plan_readiness'] == 'pending'
    assert page==before and page.row('exposure').value=='0.55 NOT ADOPTED'


@pytest.mark.parametrize('fault', [None, 'foreign_step', 'step_deadline', 'step_clock'])
def test_projected_decision_and_native_prepare_step_share_the_cycle_clock(fault):
    page = verified_calculation_panel()
    cycle = page.row('automation_cycle')
    workflow = model.OperationalFact(kind='AUTOMATION_CYCLE', state='PREPARING')
    page = changed_history_panel(page, 'automation_cycle', operational_fact=workflow)
    page = changed_history_panel(page, 'automation_step_prepare',
        operational_fact=workflow if fault != 'foreign_step' else workflow.model_copy(update={'state':'EXECUTING'}),
        recovery=replace(cycle.recovery, phase='AUTOMATION_PREPARE',
            deadline=OPEN if fault != 'step_deadline' else OPEN-timedelta(seconds=1)),
        as_of=cycle.as_of if fault != 'step_clock' else cycle.as_of-timedelta(seconds=1))
    projected = presentation.project_planless_exposure(page)
    assert projected.row('exposure').recovery.phase == 'PLANLESS_EXPOSURE_ADOPTION'
    assert presentation.project_planless_exposure(projected) == projected
    expected = ['automation_step_prepare'] if fault is not None else []
    assert presentation.health_facts(projected) == {'active':[], 'warnings':expected}


def checking_close_panel(monkeypatch):
    from sentinel.panel.authority_reader import _unknown
    page = verified_calculation_panel()
    subject = 'a'*64
    runtime = dict(git_commit='1'*40, image_digest='sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', runtime['git_commit'])
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', runtime['image_digest'])
    end = NOW + timedelta(seconds=35)
    attempt = dict(schema='sentinel.financial-observer-attempt/1', attempt_id='b'*32,
        subject_sha256=subject, outcome='RUNNING', admitted_at=(NOW-timedelta(seconds=2)).isoformat(),
        work_started_at=(NOW-timedelta(seconds=1)).isoformat(), deadline=end.isoformat(),
        work_deadline=end.isoformat())
    diagnostic = dict(observation_fresh=True, financial_authority=False, runtime=runtime, latest=attempt)
    observations = {r.key:r for r in _unknown(False, 'checking', checking_until=end)[0]}
    page = replace(page, rows=[observations.get(r.key, r) for r in page.rows],
        display_basis={'native':{'SHADOW':subject}}, trial_details={'verification_attempts':{'SHADOW':diagnostic}})
    workflow = model.OperationalFact(kind='AUTOMATION_CYCLE', state='PREPARING')
    page = changed_history_panel(page, 'automation_cycle', operational_fact=workflow)
    return changed_history_panel(page, 'automation_step_prepare', operational_fact=workflow,
        recovery=replace(page.row('automation_cycle').recovery, phase='AUTOMATION_PREPARE'))


@pytest.mark.parametrize('fault', [None, 'subject', 'missing', 'stale', 'failed', 'latched', 'expired',
                                   'shadow_changed', 'partial_group', 'worker_failed', 'book_failed'])
def test_authenticated_bounded_shadow_work_preserves_unknown_readiness(monkeypatch, fault):
    page = checking_close_panel(monkeypatch)
    diagnostic = page.trial_details['verification_attempts']['SHADOW']
    if fault == 'subject':
        diagnostic['latest']['subject_sha256'] = 'c'*64
    elif fault == 'missing':
        page = replace(page, trial_details={})
    elif fault == 'stale':
        diagnostic['observation_fresh'] = False
    elif fault in {'failed', 'latched'}:
        from sentinel.panel import observer_failure
        failure = observer_failure.failure('NEGATIVE_RESULT', 'VALIDATION').model_dump(mode='json', by_alias=True)
        if fault == 'latched':
            diagnostic['latest']['latched_failure'] = failure
        else:
            diagnostic['latest'].update(outcome='FAILED', diagnostic=failure, completed_at=NOW.isoformat())
    elif fault == 'expired':
        page = replace(page, now=NOW+timedelta(seconds=35))
    elif fault == 'shadow_changed':
        page = replace(page, observation_changed_scopes=('SHADOW',))
    elif fault == 'partial_group':
        page = replace(page, rows=[row for row in page.rows if row.key != 'terminals'])
    elif fault == 'worker_failed':
        page = changed_history_panel(page, 'shadow_worker', status=model.FAIL)
    elif fault == 'book_failed':
        page = changed_history_panel(page, 'book', status=model.FAIL)
    facts = presentation.health_facts(page)
    health = presentation.dashboard_health(page)
    assert health['plan_readiness'] == 'pending'
    if fault is None:
        assert facts == {'active':[], 'warnings':[]}
        assert health['label'] == 'Checking strategy for the next open · last verified values dated'
        assert health['color'] == 'blue'
        assert page.row('shadow_verification').value == 'CHECK IN PROGRESS'
        assert page.row('book').shadow_book is None
    else:
        assert facts['warnings'] or facts['active']
        assert health['color'] != 'green'


@pytest.mark.parametrize('changed', [('SHADOW',), ('SHADOW', 'PAPER')])
def test_only_a_complete_current_receipt_rollover_keeps_the_matching_strategy_check(monkeypatch, changed):
    from sentinel.panel import delivery, serialization
    from sentinel.panel.render import render

    panel = checking_close_panel(monkeypatch)
    keys = {'shadow_verification', 'shadow_nav', 'shadow_return', 'book', 'exposure', 'terminals'}
    if 'PAPER' in changed:
        keys.add('paper_reconciliation')
    rolled = replace(panel, observation_current=False, observation_display_current=True,
        observation_changed_scopes=changed, observation_revalidated_keys=tuple(sorted(keys)),
        observation_display_keys=delivery.display_keys(panel), observation_valid_until=NOW+timedelta(seconds=15))
    assert presentation.health_facts(rolled) == {'active': [], 'warnings': []}
    payload = serialization.public_payload(rolled)
    assert payload['dashboard_health']['label'] == 'Checking strategy for the next open · last verified values dated'
    assert payload['dashboard_health']['plan_readiness'] == 'pending'
    assert payload['observation']['display_current'] and not payload['observation']['strict_current']
    assert payload['operator_review']['status'] == 'CLEAN' and payload['operator_review']['token'] is None
    assert 'data-strict-observation-current="false"' in render(rolled)
    incomplete = replace(rolled, observation_revalidated_keys=tuple(sorted(keys-{'book'})))
    assert presentation.dashboard_health(incomplete)['label'] != 'Checking strategy for the next open'
    failed = changed_history_panel(rolled, 'book', status=model.FAIL)
    assert presentation.dashboard_health(failed)['color'] == 'red'


def test_friday_published_market_data_cannot_make_pending_monday_plan_green():
    from sentinel.panel.review_model import OperatorReview

    now = datetime(2026, 11, 20, 21, 15, tzinfo=timezone.utc)
    until = now + timedelta(seconds=20)
    feed = model.feed_row(frontier='2026-11-20', sessions_behind=0, ready=None,
                         checks_passed=0, checks_total=0, as_of=now, publication_version=26)
    feed = replace(feed, valid_until=until, recovery=model.RecoveryEvidence(
        phase='SHADOW_ATTESTATION', automatic=True, deadline=until))
    worker = model.Row('shadow_worker', 'Worker', 'Running', model.OK, as_of=now,
                      valid_until=until, required_current=True)
    plan = model.Row('paper_plan', 'Plan', 'Not prepared', model.PENDING)
    review = OperatorReview(scope='1'*64, head=1, reviewed_head=1, status='CLEAN',
                            observed_at=now, reviewed_at=now)
    panel = model.Panel(rows=[feed, worker, plan], now=now, local_paper_mode=True, operator_review=review)
    health = presentation.dashboard_health(panel)
    assert (health['color'], health['label'], health['plan_readiness'], health['valid_until']) == (
        'blue', 'Checking strategy for the next open · last verified values dated', 'pending', until.isoformat())
    assert not health['active_conditions'] and not health['review_conditions']
    failed = changed_history_panel(panel, 'shadow_worker', status=model.FAIL)
    assert presentation.dashboard_health(failed)['color'] == 'red'
    unreviewed = replace(panel, operator_review=review.model_copy(update={'status': 'REVIEW', 'reviewed_head': 0}))
    assert presentation.dashboard_health(unreviewed)['label'] == 'Acknowledgement required'
    assert presentation.dashboard_health(replace(panel, now=until))['label'] != 'Checking strategy for the next open'
    assert presentation.dashboard_health(replace(panel, now=until+timedelta(microseconds=1)))['color'] == 'red'


def test_bypassing_current_attempt_eligibility_exposes_a_latched_failure(monkeypatch):
    from sentinel.panel import readiness_handoff
    monkeypatch.setattr(readiness_handoff, '_active_attempt', lambda *args, **kwargs: True)
    with pytest.raises(AssertionError):
        test_authenticated_bounded_shadow_work_preserves_unknown_readiness(monkeypatch, 'latched')


@pytest.mark.parametrize('fault', [None, 'generic_retry', 'step_clock', 'step_attempt', 'other_schedule',
                                   'at_wake', 'missing_handoff', 'failed_book'])
def test_attestation_retry_owns_only_current_published_check_and_matching_step(monkeypatch, fault):
    from sentinel.panel import postclose_feed_wait, readiness_handoff
    page = checking_close_panel(monkeypatch)
    attempt = page.trial_details['verification_attempts']['SHADOW']['latest']
    subject = attempt['subject_sha256']
    wake = NOW + timedelta(seconds=10)
    schedule = model.OpeningSchedule(market_open=OPEN, execution_start=OPEN+timedelta(minutes=1),
                                     recovery_deadline=OPEN+timedelta(hours=6))
    if fault == 'other_schedule':
        schedule = schedule.model_copy(update={'market_open':OPEN-timedelta(days=1)})
    workflow = model.OperationalFact(kind='AUTOMATION_CYCLE', state='RETRY_WAIT', schedule=schedule)
    recovery = model.RecoveryEvidence(phase='AUTOMATION_REFRESH_AVAILABILITY' if fault == 'generic_retry'
        else 'AUTOMATION_SHADOW_ATTESTATION', automatic=True, attempt=9, next_attempt_at=wake,
        deadline=NOW+timedelta(hours=2))
    for key in ('automation_cycle', 'automation_step_data'):
        page = changed_history_panel(page, key, as_of=NOW-timedelta(minutes=4), required_current=True,
            status=model.WARN, operational_fact=workflow, recovery=recovery, valid_until=None)
    page = replace(page, rows=[r for r in page.rows if r.key != 'automation_step_prepare'])
    if fault == 'step_clock':
        page = changed_history_panel(page, 'automation_step_data', as_of=NOW-timedelta(minutes=2))
    elif fault == 'step_attempt':
        page = changed_history_panel(page, 'automation_step_data', recovery=replace(recovery, attempt=8))
    elif fault == 'failed_book':
        page = changed_history_panel(page, 'book', status=model.FAIL)
    feed = model.feed_row(frontier=str(NOW.date()), sessions_behind=0, ready=None, checks_passed=0,
        checks_total=0, as_of=NOW-timedelta(minutes=5), publication_version=25)
    page = replace(page, rows=[feed if r.key=='feed' else r for r in page.rows])
    proof = readiness_handoff.Progress(schema='sentinel.readiness-handoff-progress/1',
        publication_version=25, session=str(NOW.date()), subject_sha256=subject, attempt_id=attempt['attempt_id'],
        observed_at=NOW, deadline=NOW+timedelta(seconds=30))
    if fault != 'missing_handoff':
        page = replace(page, trial_details={**page.trial_details,
            'readiness_handoff':proof.model_dump(mode='json',by_alias=True)})
    if fault == 'at_wake':
        page = replace(page, now=wake)
    page = postclose_feed_wait.project_panel(page, now=page.now, subject=subject)
    until, keys = presentation._close_check_work(page)
    facts = presentation.health_facts(page)
    if fault is None:
        assert until == wake
        assert {'automation_cycle','automation_step_data','book','exposure','shadow_verification','terminals'} <= keys
        assert facts == {'active':[], 'warnings':[]}
        assert presentation.dashboard_health(page)['label'] == 'Checking strategy for the next open · last verified values dated'
        assert page.row('feed').feed_readiness == 'AWAITING_VERDICT' and page.row('book').shadow_book is None
    else:
        assert until is None and not keys and (facts['active'] or facts['warnings'])


def test_ignoring_the_recorded_retry_clock_loses_the_falsifier(monkeypatch):
    source = inspect.getsource(presentation._attestation_retry_boundary)
    guard = 'step.as_of == cycle.as_of and '
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard,''), '<unbound retry step>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_attestation_retry_boundary', namespace['_attestation_retry_boundary'])
    with pytest.raises(AssertionError):
        test_attestation_retry_owns_only_current_published_check_and_matching_step(monkeypatch,'step_clock')


@pytest.mark.parametrize('state', ['REFRESHING_DATA', 'WAITING_OPEN'])
@pytest.mark.parametrize('fault', [None, 'foreign_clock', 'foreign_state', 'foreign_plan'])
def test_checking_work_needs_the_real_step_and_scheduled_plan(monkeypatch, state, fault):
    from sentinel.panel import delivery
    page = checking_close_panel(monkeypatch)
    if state == 'WAITING_OPEN':
        scheduled = healthy_history_panel(now=NOW, execute_at=OPEN+timedelta(minutes=1))
        fields = {r.key:r for r in scheduled.rows if r.key in {
            'paper_plan', 'automation_cycle', 'automation_step_open', 'paper_reconciliation'}}
        if fault != 'foreign_plan':
            saved = fields['paper_plan']
            fields['paper_plan'] = replace(saved, paper_plan=saved.paper_plan.model_copy(update={
                'decision_session':NOW.date(), 'effective_session':OPEN.date()}))
        page = replace(page, rows=[r for r in page.rows if r.key not in {*fields, 'automation_step_prepare'}]
                       + list(fields.values()))
        # The real close records the cycle after the bell.
        for key in ('automation_cycle','automation_step_open'):
            page = changed_history_panel(page, key, as_of=NOW)
        step = 'automation_step_open'
    else:
        cycle = page.row('automation_cycle')
        workflow = model.OperationalFact(kind='AUTOMATION_CYCLE', state=state)
        page = replace(page, rows=[r for r in page.rows if r.key != 'automation_step_prepare'])
        page = changed_history_panel(page, 'automation_cycle', operational_fact=workflow,
            recovery=replace(cycle.recovery, phase='AUTOMATION_REFRESHING_DATA'))
        step = 'automation_step_data'
        page = changed_history_panel(page, step, status=model.WARN, as_of=cycle.as_of,
            required_current=True, operational_fact=workflow,
            recovery=replace(cycle.recovery, phase='AUTOMATION_DATA'))
    if fault == 'foreign_clock':
        page = changed_history_panel(page, step, as_of=NOW-timedelta(seconds=1))
    elif fault == 'foreign_state':
        page = changed_history_panel(page, step, operational_fact=model.OperationalFact(
            kind='AUTOMATION_CYCLE', state='EXECUTING'))
    elif fault == 'foreign_plan' and state == 'REFRESHING_DATA':
        page = changed_history_panel(page, 'paper_plan', status=model.OK)
    until, keys = presentation._close_check_work(page)
    if fault == 'foreign_plan':
        assert until is None and not keys
        return
    assert until is not None and 'automation_cycle' in keys
    assert (step in keys) is (fault is None)
    for key in keys:
        assert delivery.row_current(page, page.row(key))


@pytest.mark.parametrize('defect',['decision','actual_failure','unknown','unbounded','expired','future','not_required','fraction','generic_retry','wrong_phase'])
def test_unadopted_exposure_cannot_borrow_unproved_preparation(defect):
    page=verified_calculation_panel()
    changes={'decision':{'operational_fact':page.row('exposure').operational_fact.model_copy(update={'session':date(2026,10,21)})},
        'actual_failure':{'status':model.FAIL},'unknown':{'status':model.UNKNOWN},
        'unbounded':{'freshness':None},'expired':{'valid_until':NOW},'future':{'as_of':NOW+timedelta(seconds=6)},
        'not_required':{'required_current':False},'fraction':{'value':'1.10 NOT ADOPTED','operational_fact':None}}
    if defect in changes:page=changed_history_panel(page,'exposure',**changes[defect])
    else:
        phase='AUTOMATION_PREPARE_AVAILABILITY' if defect=='generic_retry' else 'AUTOMATION_REFRESHING_DATA'
        page=changed_history_panel(page,'automation_cycle',recovery=model.RecoveryEvidence(phase=phase,automatic=True,deadline=OPEN))
    assert not presentation._unadopted_preparation_fact(page)
    assert presentation.dashboard_health(page)['color']!='green'


def test_removed_unadopted_decision_binding_has_executed_falsifier(monkeypatch):
    text=inspect.getsource(presentation._unadopted_preparation_fact)
    guard="fact.session == date.fromisoformat(session)"
    assert text.count(guard)==1
    namespace=dict(vars(presentation));exec(compile(text.replace(guard,'True'),'<removed adoption decision>','exec'),namespace)
    monkeypatch.setattr(presentation,'_unadopted_preparation_fact',namespace['_unadopted_preparation_fact'])
    with pytest.raises(AssertionError):test_unadopted_exposure_cannot_borrow_unproved_preparation('decision')
