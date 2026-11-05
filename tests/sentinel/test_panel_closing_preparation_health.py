"""Routine next-plan work does not manufacture a PAPER incident."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
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
    assert presentation.dashboard_health(page)['color']=='green'


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
    assert presentation.dashboard_health(page)['color']=='green'
    assert page==before and page.row('exposure').value=='0.55 NOT ADOPTED'


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
    assert presentation.dashboard_health(page)['color']!='green'


def test_removed_unadopted_decision_binding_has_executed_falsifier(monkeypatch):
    text=inspect.getsource(presentation._unadopted_preparation_fact)
    guard="fact.session == date.fromisoformat(session)"
    assert text.count(guard)==1
    namespace=dict(vars(presentation));exec(compile(text.replace(guard,'True'),'<removed adoption decision>','exec'),namespace)
    monkeypatch.setattr(presentation,'_unadopted_preparation_fact',namespace['_unadopted_preparation_fact'])
    with pytest.raises(AssertionError):test_unadopted_exposure_cannot_borrow_unproved_preparation('decision')
