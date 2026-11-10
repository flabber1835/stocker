"""A later decision cannot resurrect a proved safe retirement as an old failure."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest

from sentinel.panel import model, presentation, sources
from sentinel.paper_plan_preview import PlanPreview
from sentinel.execution import journal
from tests.sentinel.test_opening_health_continuity import NOW, clean_skip_panel
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel
from tests.sentinel.test_clean_cash_skip_provenance import case, conn, pg  # noqa: F401

NEXT=datetime(2026,11,10,22,15,tzinfo=timezone.utc)
NEXT_OPEN=datetime(2026,11,11,14,31,tzinfo=timezone.utc)
ROLL=datetime(2026,11,11,5,tzinfo=timezone.utc)-timedelta(microseconds=1)


def historical_row():
    current=clean_skip_panel().row('trading_run');run=current.trading_run
    fact=model.OperationalFact(kind='EXECUTION_HISTORY',state='SUPERSEDED',
        opening=model.OpeningEvidence(cycle_id=run.intent.cycle_id,plan_id=run.intent.plan_id,
            started_at=run.updated_at,deadline=ROLL,observation_id=396,
            terminal_reason='POST_PLAN_CASH_ACTIVITY_RECONCILED',
            reconciled_at=run.updated_at-timedelta(seconds=30)))
    return replace(current,status=model.WARN,recovery=None,valid_until=ROLL,operational_fact=fact,
        value='SKIPPED · CASH ACTIVITY RECONCILED')


def next_decision_panel(*,preparing=False):
    page=healthy_history_panel(now=NEXT,execute_at=NEXT_OPEN)
    plan=PlanPreview(cycle_id='following-cycle',plan_id='following-plan',decision_session=date(2026,11,10),
        effective_session=date(2026,11,11),execute_at=NEXT_OPEN,created_at=NEXT-timedelta(minutes=2),
        observation_at=NEXT-timedelta(minutes=3),legs=[])
    changed={
        'paper_plan':replace(page.row('paper_plan'),paper_plan=plan),
        'feed':replace(page.row('feed'),operational_fact=model.OperationalFact(kind='MARKET_DATA',state='READY',
            session=date(2026,11,10),sessions_behind=0)),
        'shadow_verification':replace(page.row('shadow_verification'),operational_fact=model.OperationalFact(
            kind='SHADOW_VERIFICATION',state='VERIFIED',session=date(2026,11,10))),
        'book':replace(page.row('book'),shadow_book=model.ShadowBook(session='2026-11-10',
            cash=Decimal(50000),receivables=Decimal(0),nav=Decimal(50000),pending_operations=0,holdings=[]))}
    if preparing:
        bound=NEXT_OPEN-timedelta(minutes=1)
        changed['paper_plan']=model.Row('paper_plan','Next','NOT PREPARED',model.PENDING)
        changed['paper_reconciliation']=model.Row('paper_reconciliation','Paper','CHECK IN PROGRESS',model.WARN,
            required_current=True,valid_until=NEXT+timedelta(minutes=5),
            recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=NEXT+timedelta(minutes=5)),
            operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'))
        changed['automation_cycle']=model.Row('automation_cycle','Cycle','PREPARING',model.WARN,
            as_of=NEXT-timedelta(minutes=2),required_current=True,
            recovery=model.RecoveryEvidence(phase='AUTOMATION_PREPARING',automatic=True,deadline=bound),
            operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='PREPARING'))
        changed['automation_step_open']=model.Row('automation_step_open','Open','NOT REACHED',model.PENDING)
    return replace(page,rows=[changed.get(row.key,row) for row in page.rows]+[historical_row()])


@pytest.mark.parametrize('preparing',[False,True])
def test_later_current_workflow_is_independent_of_the_retired_original_plan(preparing):
    page=next_decision_panel(preparing=preparing)
    assert presentation._historical_skip_record(page)
    assert (presentation._preparing_work_normal(page) if preparing else presentation._scheduled_work_normal(page))
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    assert presentation.dashboard_health(page)['color']=='green'
    assert page.row('trading_run').trading_run.intent.plan_id=='opening-plan'
    assert page.row('trading_run').trading_run.state=='SUPERSEDED'
    assert page.row('trading_run').recovery is None


def test_pending_new_context_cannot_use_historical_proof_to_establish_green_or_old_failure():
    page=next_decision_panel(preparing=True)
    page=replace(page,rows=[row for row in page.rows if not row.key.startswith('automation_step_') and row.key!='automation_cycle'])
    assert presentation._historical_skip_record(page)
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    assert presentation.dashboard_health(page)['color']=='amber'


@pytest.mark.parametrize('key,status',[('paper_reconciliation',model.UNKNOWN),('broker',model.FAIL),
    ('alpaca_account',model.FAIL),('authority',model.UNKNOWN)])
def test_current_negative_remains_its_own_condition_without_resurrecting_old_cycle(key,status):
    page=next_decision_panel(preparing=True)
    page=replace(page,rows=[replace(row,status=status) if row.key==key else row for row in page.rows])
    facts=presentation.health_facts(page)
    assert key in facts['active'] and 'trading_run' not in facts['active']
    assert presentation.dashboard_health(page)['color']=='red'


@pytest.mark.parametrize('fault',['foreign_plan','foreign_cycle','wrong_observation','missing_fact','genuine_failed_run'])
def test_foreign_or_genuinely_failed_history_does_not_get_retirement_classification(fault):
    page=next_decision_panel();row=page.row('trading_run')
    if fault=='missing_fact':row=replace(row,operational_fact=None)
    elif fault=='genuine_failed_run':row=replace(row,status=model.FAIL,
        trading_run=row.trading_run.model_copy(update={'state':'FAILED'}),operational_fact=None)
    else:
        field={'foreign_plan':'plan_id','foreign_cycle':'cycle_id','wrong_observation':'observation_id'}[fault]
        value=397 if field=='observation_id' else 'foreign'
        if field=='observation_id':
            # The historical marker alone cannot normalize a raw terminal fail.
            row=replace(row,status=model.FAIL)
        row=replace(row,operational_fact=row.operational_fact.model_copy(update={
            'opening':row.operational_fact.opening.model_copy(update={field:value})}))
    page=replace(page,rows=[row if item.key==row.key else item for item in page.rows])
    assert not presentation._historical_skip_record(page)
    assert 'trading_run' in (presentation.health_facts(page)['active'] if row.status==model.FAIL
                            else presentation.health_facts(page)['warnings'])


def test_original_market_day_boundary_remains_finite_and_selector_can_drop_the_old_record():
    page=next_decision_panel();page=replace(page,now=ROLL+timedelta(microseconds=1))
    assert not presentation._historical_skip_record(page)
    without=replace(page,rows=[row for row in page.rows if row.key!='trading_run'])
    assert 'trading_run' not in presentation.health_facts(without)['active']
    assert 'trading_run' not in presentation.health_facts(without)['warnings']


def test_removed_independent_current_workflow_guard_has_executed_falsifier(monkeypatch):
    source=inspect.getsource(presentation._green_eligible)
    guard=("    if (_historical_skip_record(panel) and not _clean_skip_work_normal(panel)\n"
        "            and not (_scheduled_work_normal(panel) or _preparing_work_normal(panel))):\n        return False\n")
    assert source.count(guard)==1
    namespace=dict(vars(presentation));exec(compile(source.replace(guard,''),'<history-as-current-authority>','exec'),namespace)
    monkeypatch.setattr(presentation,'_green_eligible',namespace['_green_eligible'])
    with pytest.raises(AssertionError):
        test_pending_new_context_cannot_use_historical_proof_to_establish_green_or_old_failure()


def test_native_historical_provenance_is_reused_once_inside_current_paper_proof(case,monkeypatch):
    calls=[];original=journal.load_observation_payload
    def load(conn,seq):calls.append(seq);return original(conn,seq)
    monkeypatch.setattr(journal,'load_observation_payload',load)
    run=case.current.trading_run
    fact=sources._historical_cash_skip_fact(case.conn,{'valid_until':ROLL+timedelta(microseconds=1)},run,
        (str(case.seq),'POST_PLAN_CASH_ACTIVITY_RECONCILED',case.cycle['diagnostic']))
    assert fact.kind=='EXECUTION_HISTORY' and fact.opening.observation_id==case.seq
    current=replace(case.current,status=model.WARN,operational_fact=fact)
    result=sources._clean_cash_supersession(case.conn,case.cycle,trading_row=current,now=NOW)
    assert result is not None and calls==[case.seq]


def test_current_awaiting_interface_is_preserved_when_the_run_also_carries_history():
    page=clean_skip_panel()
    rows=model.project_opening_rows([historical_row() if row.key=='trading_run' else row for row in page.rows],now=NOW)
    page=replace(page,rows=rows)
    assert page.row('trading_run').status==model.WARN
    assert page.row('trading_run').trading_run.state=='SUPERSEDED'
    assert page.row('trading_run').recovery.phase=='AWAITING_NEXT_DECISION'
    assert presentation._clean_skip_work_normal(page)
    assert presentation.dashboard_health(page)['color']=='green'


def test_historical_record_cannot_be_produced_from_changed_native_provenance(case):
    case.conn.execute('ALTER TABLE sentinel_observation_provenance DISABLE TRIGGER USER')
    case.conn.execute("UPDATE sentinel_observation_provenance SET broker_account_id='foreign' WHERE observation_seq=%s",(case.seq,))
    case.conn.execute('ALTER TABLE sentinel_observation_provenance ENABLE TRIGGER USER')
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        sources._historical_cash_skip_fact(case.conn,{'valid_until':ROLL+timedelta(microseconds=1)},
            case.current.trading_run,(str(case.seq),'POST_PLAN_CASH_ACTIVITY_RECONCILED',case.cycle['diagnostic']))


def test_removed_historical_native_guard_has_executed_falsifier(case,monkeypatch):
    source=inspect.getsource(sources._historical_cash_skip_fact)
    guard='    payload = journal.load_observation_payload(conn, int(clean))'
    assert source.count(guard)==1
    namespace=dict(vars(sources));exec(compile(source.replace(guard,"    payload = {'completeness':'COMPLETE'}"),
        '<historical-provenance-omitted>','exec'),namespace)
    monkeypatch.setattr(sources,'_historical_cash_skip_fact',namespace['_historical_cash_skip_fact'])
    with pytest.raises(pytest.fail.Exception):
        test_historical_record_cannot_be_produced_from_changed_native_provenance(case)
