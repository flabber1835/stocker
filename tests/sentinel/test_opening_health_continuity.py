"""Current opening progress and clean retirement remain nonfinancial facts."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel.panel import model, presentation
from sentinel.paper_plan_preview import PlanPreview
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel
from tests.sentinel.test_dashboard_review import conn, pg  # noqa: F401

NOW = datetime(2026, 11, 10, 14, 39, tzinfo=timezone.utc)
OPEN = NOW.replace(hour=14, minute=31)


def base_panel():
    page = healthy_history_panel(now=NOW)
    rows = []
    for row in page.rows:
        if row.key == 'feed':
            row = replace(row, operational_fact=model.OperationalFact(
                kind='MARKET_DATA', state='READY', session=date(2026, 11, 9), sessions_behind=0))
        if row.key == 'shadow_verification':
            row = replace(row, operational_fact=model.OperationalFact(
                kind='SHADOW_VERIFICATION', state='VERIFIED', session=date(2026, 11, 9)))
        if row.key == 'book':
            row = replace(row, shadow_book=model.ShadowBook(session='2026-11-09',
                cash=Decimal('50000'), receivables=Decimal(0), nav=Decimal('50000'),
                pending_operations=0, holdings=[]))
        rows.append(row)
    return replace(page, rows=rows)


def intent():
    return PlanPreview(cycle_id='opening-cycle', plan_id='opening-plan',
        decision_session=date(2026, 11, 9), effective_session=date(2026, 11, 10),
        execute_at=OPEN, created_at=NOW-timedelta(days=1), observation_at=NOW-timedelta(days=1), legs=[])


def clean_skip_panel():
    """Public-payload fixture for the exact safe post-cash skipped-plan state."""
    page = base_panel()
    updated = NOW-timedelta(seconds=30)
    boundary = NOW+timedelta(minutes=5)
    evidence = model.OpeningEvidence(cycle_id='opening-cycle', plan_id='opening-plan',
        started_at=updated, deadline=boundary, observation_id=396)
    recovery = model.RecoveryEvidence(phase='AWAITING_NEXT_DECISION', automatic=True, deadline=boundary)
    fact = model.OperationalFact(kind='PAPER_VERIFICATION', state='AWAITING_NEXT_DECISION', opening=evidence)
    candidate = model.OperationalFact(kind='EXECUTION_PROGRESS', state='AWAITING_NEXT_DECISION',
        opening=evidence.model_copy(update={'deadline':NOW.replace(hour=21,minute=10)}))
    run = model.TradingRun(intent=intent(), state='SUPERSEDED', updated_at=updated)
    changed = {'paper_plan':model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        'paper_reconciliation':model.Row('paper_reconciliation','Paper','PLAN SKIPPED · CASH ACTIVITY RECONCILED',
            model.WARN, as_of=NOW, valid_until=boundary, required_current=True,
            recovery=recovery, operational_fact=fact),
        'trading_run':model.Row('trading_run','Today’s plan','SUPERSEDED',model.FAIL,
            as_of=updated, valid_until=NOW+timedelta(hours=10), trading_run=run)}
    for key in ('automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete'):
        changed[key] = model.Row(key,key,'SUPERSEDED',model.FAIL,as_of=updated,
            required_current=True, operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='SUPERSEDED'))
    changed['automation_step_open'] = model.Row('automation_step_open','Open','COMPLETED',model.OK,
        as_of=updated, operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='SUPERSEDED'))
    changed['broker'] = replace(page.row('broker'), operational_fact=candidate,
        as_of=NOW-timedelta(minutes=2),valid_until=NOW+timedelta(minutes=8))
    rows = [changed.pop(row.key,row) for row in page.rows]
    rows.extend(changed.values())
    return replace(page, rows=model.project_opening_rows(rows,now=NOW))


def executing_panel(*, stale_broker=False, pending_transport=False):
    page=base_panel();updated=NOW-timedelta(minutes=8)
    bound=NOW+timedelta(minutes=7)
    evidence=model.OpeningEvidence(cycle_id='opening-cycle',plan_id='opening-plan',
        started_at=updated+timedelta(milliseconds=30),deadline=bound)
    fact=model.OperationalFact(kind='EXECUTION_PROGRESS',state='EXECUTING',opening=evidence)
    run=model.TradingRun(intent=intent(),state='EXECUTING',updated_at=updated)
    cycle=model.OperationalFact(kind='AUTOMATION_CYCLE',state='EXECUTING')
    changed={'paper_plan':model.Row('paper_plan','Next','NOT PREPARED',model.PENDING),
        'trading_run':model.Row('trading_run','Run','EXECUTING',model.WARN,as_of=updated,
            valid_until=NOW+timedelta(hours=10),trading_run=run),
        'automation_cycle':model.Row('automation_cycle','Cycle','EXECUTING',model.WARN,
            as_of=updated,required_current=True,operational_fact=cycle,
            recovery=model.RecoveryEvidence(phase='AUTOMATION_EXECUTING',automatic=True,deadline=NOW.replace(hour=21,minute=0))),
        'automation_step_transport':model.Row('automation_step_transport','Transport','IN PROGRESS',model.WARN,
            as_of=updated,required_current=True,operational_fact=cycle,
            recovery=model.RecoveryEvidence(phase='AUTOMATION_TRANSPORT',automatic=True,deadline=NOW.replace(hour=21,minute=0))),
        'automation_step_open':model.Row('automation_step_open','Open','COMPLETED',model.OK,as_of=updated),
        'paper_reconciliation':model.Row('paper_reconciliation','Paper','CHECK IN PROGRESS',model.WARN,
            required_current=True,valid_until=bound,
            operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'),
            recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=bound))}
    changed['broker']=replace(page.row('broker'),operational_fact=fact,
        as_of=NOW-timedelta(days=1) if stale_broker else NOW,
        valid_until=NOW-timedelta(hours=20) if stale_broker else NOW+timedelta(minutes=10),
        recovery=model.RecoveryEvidence(phase='BROKER_CALLBACK_REFRESH',automatic=True,deadline=bound))
    if pending_transport:
        changed['paper_reconciliation'] = replace(
            model.paper_reconciliation_row(state='PENDING', cycle_state='EXECUTING'),
            as_of=updated, required_current=True, valid_until=bound,
            recovery=model.RecoveryEvidence(phase='PAPER_TRANSPORT', automatic=True, deadline=bound))
    return replace(page,rows=[changed.get(row.key,row) for row in page.rows]+[changed['trading_run']])


def test_clean_skip_is_green_without_rewriting_original_plan_or_claiming_success():
    page=clean_skip_panel();before=deepcopy(page)
    assert presentation._clean_skip_work_normal(page)
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    assert presentation.dashboard_health(page)['color']=='green'
    assert page.row('trading_run').trading_run.state=='SUPERSEDED'
    assert page.row('trading_run').trading_run.orders==[]
    assert page.row('paper_plan').paper_plan is None
    assert page.row('automation_cycle').value=='WAITING FOR NEXT DECISION · PLAN SKIPPED'
    assert page==before


@pytest.mark.parametrize('stale',[False,True])
def test_exact_execution_progress_is_ordinary_but_stale_broker_cannot_establish_green(stale):
    page=executing_panel(stale_broker=stale)
    assert presentation._execution_work_normal(page)
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    health=presentation.dashboard_health(page)
    assert health['color']==('amber' if stale else 'green')
    assert datetime.fromisoformat(health['valid_until'])>page.now
    assert page.row('broker').is_stale(page.now) is stale
    assert page.row('broker').as_of== (NOW-timedelta(days=1) if stale else NOW)


@pytest.mark.parametrize('fault', ['untyped', 'not_required', 'expired', 'negative'])
def test_unproved_paper_transport_keeps_review_or_failure(fault):
    page = executing_panel(pending_transport=True)
    paper = page.row('paper_reconciliation')
    if fault == 'untyped':
        paper = replace(paper, operational_fact=None)
    elif fault == 'not_required':
        paper = replace(paper, required_current=False)
    elif fault == 'expired':
        paper = replace(paper, valid_until=NOW, recovery=replace(paper.recovery, deadline=NOW))
    else:
        paper = replace(paper, status=model.FAIL)
    page = replace(page, rows=[paper if row.key == paper.key else row for row in page.rows])
    assert not presentation._execution_work_normal(page)
    facts = presentation.health_facts(page)
    assert paper.key in facts['warnings'] + facts['active']


def test_removed_paper_transport_type_guard_is_detected(monkeypatch):
    source = inspect.getsource(presentation._execution_work_normal)
    guard = "and paper_fact is not None and paper_fact.kind == 'PAPER_VERIFICATION' and paper_fact.state == 'PENDING'"
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard, ''), '<untyped-paper-transport>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_execution_work_normal', namespace['_execution_work_normal'])
    with pytest.raises(AssertionError):
        test_unproved_paper_transport_keeps_review_or_failure('untyped')


@pytest.mark.parametrize('fixture',[clean_skip_panel,executing_panel])
@pytest.mark.parametrize('key',['automation_leader','shadow_worker','authority','alpaca_account','feed','book','backup_restore'])
def test_missing_or_negative_independent_capability_never_borrows_opening_progress(fixture,key):
    page=fixture();page=replace(page,rows=[replace(row,status=model.FAIL) if row.key==key else row for row in page.rows])
    assert not presentation._clean_skip_work_normal(page)
    assert not presentation._execution_work_normal(page)
    assert key in presentation.health_facts(page)['active']


@pytest.mark.parametrize('fixture',[clean_skip_panel,executing_panel])
@pytest.mark.parametrize('fault',['foreign_plan','foreign_cycle','expired','missing_fact','negative_paper'])
def test_opening_classification_requires_exact_subject_and_original_bounds(fixture,fault):
    page=fixture();key='paper_reconciliation' if fixture==clean_skip_panel else 'broker';row=page.row(key)
    fact=row.operational_fact
    if fault=='missing_fact':row=replace(row,operational_fact=None)
    elif fault=='negative_paper':
        key='paper_reconciliation';row=replace(page.row(key),status=model.FAIL)
    elif fault=='expired':page=replace(page,now=fact.opening.deadline+timedelta(microseconds=1))
    else:
        name='plan_id' if fault=='foreign_plan' else 'cycle_id'
        row=replace(row,operational_fact=fact.model_copy(update={'opening':fact.opening.model_copy(update={name:'foreign'})}))
    page=replace(page,rows=[row if item.key==key else item for item in page.rows])
    assert not presentation._clean_skip_work_normal(page)
    assert not presentation._execution_work_normal(page)
    assert presentation.health_facts(page)!={'active':[],'warnings':[]}


def test_idle_candidate_alone_cannot_renew_the_saved_broker_observation():
    page=clean_skip_panel();rows=[replace(row,status=model.FAIL,recovery=None) if row.key=='paper_reconciliation'
        else replace(row,valid_until=NOW-timedelta(seconds=1)) if row.key=='broker' else row for row in page.rows]
    projected=model.project_opening_rows(rows,now=NOW)
    assert next(row for row in projected if row.key=='broker').is_stale(NOW)


def test_clean_skip_projection_is_idempotent_and_receipt_renewal_does_not_extend_retained_run_clock():
    page=clean_skip_panel();original=page.row('trading_run').valid_until
    assert model.project_opening_rows(page.rows,now=NOW)==page.rows
    paper=page.row('paper_reconciliation');deadline=paper.valid_until+timedelta(minutes=1)
    renewed=replace(paper,valid_until=deadline,recovery=replace(paper.recovery,deadline=deadline),
        operational_fact=paper.operational_fact.model_copy(update={'opening':paper.operational_fact.opening.model_copy(update={'deadline':deadline})}))
    page=replace(page,rows=model.project_opening_rows([renewed if row.key==paper.key else row for row in page.rows],now=NOW))
    assert page.row('trading_run').valid_until==original
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}


def test_stale_broker_green_guard_has_executed_falsifier(monkeypatch):
    source=inspect.getsource(presentation._green_eligible)
    guard="    if _execution_work_normal(panel) and not _current_health_fact(panel, 'broker'):\n        return False\n"
    assert source.count(guard)==1
    namespace=dict(vars(presentation));exec(compile(source.replace(guard,''),'<stale-broker-green>','exec'),namespace)
    monkeypatch.setattr(presentation,'_green_eligible',namespace['_green_eligible'])
    with pytest.raises(AssertionError):
        test_exact_execution_progress_is_ordinary_but_stale_broker_cannot_establish_green(True)


def test_signed_history_does_not_turn_bounded_progress_or_clean_skip_into_new_incidents(conn):
    from sentinel.panel import review
    owner=review.Recorder();page=executing_panel()
    observed=owner.observe(page,conn.info.dsn)
    baseline=owner.acknowledge(page,conn.info.dsn,observed.token,actor='private qualification operator')
    for page in (executing_panel(stale_broker=True, pending_transport=True),
                 executing_panel(pending_transport=True), clean_skip_panel()):
        result=owner.observe(page,conn.info.dsn)
        assert result.status=='CLEAN' and result.head==result.reviewed_head==baseline.head
        assert result.active==result.warnings==[]
        assert [event for event in result.events if event['sequence']>baseline.head]==[]
