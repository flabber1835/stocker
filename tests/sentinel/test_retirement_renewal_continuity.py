"""A fresh current check cannot reopen an immutable clean retirement."""
from dataclasses import replace
from datetime import datetime, timedelta
import inspect

import pytest

from sentinel.panel import model,presentation,serialization
from tests.sentinel.test_resolved_transport_history import (
    DAY_END,INTERRUPTED,RECONCILED,COMPLETED,recorded_interruption_panel)
from tests.sentinel.test_dashboard_review import conn,pg  # noqa: F401

START=datetime.fromisoformat('2026-11-10T17:42:30+00:00')
BROKER_AT=datetime.fromisoformat('2026-11-10T14:37:50.477990+00:00')
IDLE_DEADLINE=START.replace(hour=21,minute=0,second=0)
HISTORY_KEYS={'automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete'}


def renewal_panel(*,now=START,checking=True,project=True):
    page=recorded_interruption_panel(project=False)
    rows=[]
    for row in page.rows:
        if row.key in presentation._HISTORY_CURRENT_FACTS and row.key!='broker':
            row=replace(row,as_of=now,valid_until=now+timedelta(minutes=10),
                paper_account=row.paper_account.model_copy(update={'observed_at':now}) if row.paper_account else None)
        if row.key=='broker':
            row=replace(row,as_of=BROKER_AT,valid_until=BROKER_AT+timedelta(minutes=10),recovery=None,
                operational_fact=row.operational_fact.model_copy(update={'opening':
                    row.operational_fact.opening.model_copy(update={'deadline':IDLE_DEADLINE})}))
        if row.key=='paper_reconciliation':
            deadline=now+timedelta(minutes=5)
            if checking:
                row=model.Row(row.key,row.label,'CHECK IN PROGRESS',model.WARN,required_current=True,
                    valid_until=deadline,operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'),
                    recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline))
            else:
                row=replace(row,as_of=now,valid_until=deadline,recovery=replace(row.recovery,deadline=deadline),
                    operational_fact=row.operational_fact.model_copy(update={'opening':
                        row.operational_fact.opening.model_copy(update={'deadline':deadline})}))
        rows.append(row)
    return replace(page,now=now,rows=model.project_opening_rows(rows,now=now) if project else rows)


def test_full_collect_checking_and_positive_renewals_never_reopen_resolved_history():
    for seconds in range(0,331,5):
        now=START+timedelta(seconds=seconds)
        for checking in (True,False):
            page=renewal_panel(now=now,checking=checking)
            wire=serialization.public_payload(page)
            assert wire['dashboard_health']['color']=='green',(seconds,checking,wire['dashboard_health'])
            assert wire['dashboard_health']['active_conditions']==wire['dashboard_health']['review_conditions']==[]
            assert page.row('automation_step_transport').as_of==INTERRUPTED
            assert page.row('trading_run').trading_run.updated_at==COMPLETED
            assert page.row('broker').as_of==BROKER_AT and page.row('broker').valid_until==IDLE_DEADLINE
            if checking:
                assert page.row('trading_run').valid_until==DAY_END
                assert all(page.row(key).recovery is None and page.row(key).valid_until==DAY_END for key in HISTORY_KEYS)
                assert presentation._retired_check_work_normal(page)
            assert model.project_opening_rows(page.rows,now=now)==page.rows


@pytest.mark.parametrize('key',['paper_reconciliation','alpaca_account','authority','automation_leader',
    'shadow_worker','backup_restore','broker'])
@pytest.mark.parametrize('status',[model.FAIL,model.UNKNOWN])
def test_current_negative_never_borrows_history_and_does_not_reopen_it(key,status):
    page=renewal_panel(project=False)
    page=replace(page,rows=model.project_opening_rows([
        replace(row,status=status) if row.key==key else row for row in page.rows],now=page.now))
    facts=presentation.health_facts(page)
    assert key in facts['active']
    assert not HISTORY_KEYS.intersection(facts['active']+facts['warnings'])
    assert serialization.public_payload(page)['dashboard_health']['color']=='red'
    assert not presentation._retired_check_work_normal(page)


@pytest.mark.parametrize('fault',['foreign_candidate','missing_candidate','active_cycle','unresolved_transport',
    'history_expired','check_expired','authority_expired','account_expired','candidate_expired'])
def test_original_subjects_and_deadlines_remain_required(fault):
    page=renewal_panel(project=False);changed={}
    if fault in {'foreign_candidate','missing_candidate','candidate_expired'}:
        row=page.row('broker');fact=row.operational_fact
        if fault=='missing_candidate':fact=None
        else:
            update={'plan_id':'foreign'} if fault=='foreign_candidate' else {'deadline':page.now}
            fact=fact.model_copy(update={'opening':fact.opening.model_copy(update=update)})
        changed[row.key]=replace(row,operational_fact=fact)
    elif fault=='active_cycle':
        row=page.row('automation_cycle');changed[row.key]=replace(row,value='EXECUTING',
            operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='EXECUTING'))
    elif fault=='unresolved_transport':
        row=page.row('automation_step_transport');changed[row.key]=replace(row,as_of=RECONCILED+timedelta(seconds=1))
    elif fault=='history_expired':page=replace(page,now=DAY_END)
    else:
        key={'check_expired':'paper_reconciliation','authority_expired':'authority','account_expired':'alpaca_account'}[fault]
        row=page.row(key);changed[key]=replace(row,valid_until=page.now,
            recovery=replace(row.recovery,deadline=page.now) if row.recovery else None)
    page=replace(page,rows=model.project_opening_rows([changed.get(row.key,row) for row in page.rows],now=page.now))
    assert not presentation._retired_check_work_normal(page)
    assert serialization.public_payload(page)['dashboard_health']['color']!='green'


def test_current_check_uses_its_original_deadline_not_historical_lifetime():
    page=renewal_panel();deadline=page.row('paper_reconciliation').valid_until
    page=replace(page,now=deadline+timedelta(microseconds=1))
    assert presentation._historical_skip_record(page)
    assert page.row('automation_step_transport').valid_until==DAY_END
    assert not presentation._retired_check_work_normal(page)
    assert 'paper_reconciliation' in presentation.health_facts(page)['active']


def test_expired_prior_paper_bound_cannot_expire_independent_original_history():
    page=renewal_panel(project=False)
    page=replace(page,rows=[replace(row,valid_until=START-timedelta(seconds=1))
        if row.key=='trading_run' else row for row in page.rows])
    page=replace(page,rows=model.project_opening_rows(page.rows,now=page.now))
    assert page.row('trading_run').valid_until==DAY_END
    assert page.row('trading_run').operational_fact.opening.deadline==DAY_END
    assert page.row('paper_reconciliation').valid_until==START+timedelta(minutes=5)
    assert serialization.public_payload(page)['dashboard_health']['color']=='green'
    expired=replace(page,now=DAY_END)
    assert not model.historical_skip_subject(expired.row('trading_run'),now=expired.now)
    assert not presentation._retired_check_work_normal(expired)


@pytest.mark.parametrize('fault',['negative','unknown','later_capture'])
def test_history_cannot_extend_negative_or_unrelated_broker_evidence(fault):
    page=renewal_panel(project=False);broker=page.row('broker')
    if fault=='later_capture':broker=replace(broker,as_of=COMPLETED+timedelta(seconds=1))
    else:broker=replace(broker,status=model.FAIL if fault=='negative' else model.UNKNOWN)
    old=broker.valid_until
    page=replace(page,rows=model.project_opening_rows([broker if row.key=='broker' else row for row in page.rows],now=page.now))
    assert page.row('broker').valid_until==old
    assert not presentation._retired_check_work_normal(page)


@pytest.mark.parametrize('guard,fault',[
    ('broker.status == OK','negative'),
    ('broker.as_of <= history.started_at','later_capture'),
])
def test_broker_clock_bridge_guards_have_executed_falsifiers(monkeypatch,guard,fault):
    text=inspect.getsource(model.project_retirement_history)
    assert text.count(guard)==1
    replacement='broker.as_of <= now' if fault=='later_capture' else 'True'
    namespace=dict(vars(model));exec(text.replace(guard,replacement),namespace)
    monkeypatch.setattr(model,'project_retirement_history',namespace['project_retirement_history'])
    with pytest.raises(AssertionError):test_history_cannot_extend_negative_or_unrelated_broker_evidence(fault)


def test_signed_routine_renewals_add_no_historical_review_or_failure_events(conn):
    from sentinel.panel import review
    owner=review.Recorder();page=renewal_panel(checking=False)
    observed=owner.observe(page,conn.info.dsn)
    baseline=owner.acknowledge(page,conn.info.dsn,observed.token,actor='private renewal qualification')
    for seconds in range(0,331,30):
        for checking in (True,False):
            page=renewal_panel(now=START+timedelta(seconds=seconds),checking=checking)
            current=owner.observe(page,conn.info.dsn)
            assert current.status=='CLEAN' and current.head==current.reviewed_head==baseline.head
            assert current.active==current.warnings==[]


def test_historical_projection_omission_reproduces_the_renewal_failure(monkeypatch):
    monkeypatch.setattr(model,'project_retirement_history',lambda rows,**kwargs:rows)
    page=renewal_panel()
    assert HISTORY_KEYS.issubset(presentation.health_facts(page)['active'])
    assert 'broker' in presentation.health_facts(page)['active']
    with pytest.raises(AssertionError):test_full_collect_checking_and_positive_renewals_never_reopen_resolved_history()


def test_independent_current_capability_guard_has_executed_falsifier(monkeypatch):
    text=inspect.getsource(presentation._retired_current_capabilities)
    guard='_opening_capabilities(panel,maintenance=True)'
    assert text.count(guard)==1
    namespace=dict(vars(presentation));exec(text.replace(guard,'True'),namespace)
    monkeypatch.setattr(presentation,'_retired_current_capabilities',namespace['_retired_current_capabilities'])
    page=renewal_panel();page=replace(page,rows=[replace(row,status=model.FAIL) if row.key=='authority'
        else row for row in page.rows])
    with pytest.raises(AssertionError):assert not presentation._retired_check_work_normal(page)


@pytest.mark.parametrize('checking',[True,False])
@pytest.mark.parametrize('fault',[None,'expired','negative','unknown','wrong_phase','manual'])
def test_normal_backup_maintenance_intersection_uses_only_original_typed_admission(checking,fault):
    page=renewal_panel(checking=checking);bound=START+timedelta(minutes=2)
    backup=replace(page.row('backup_restore'),status=model.WARN,value='BACKUP CHECK IN PROGRESS',
        valid_until=bound,required_current=True,recovery=model.RecoveryEvidence(
            phase='BACKUP_MAINTENANCE',automatic=True,deadline=bound))
    if fault=='expired':page=replace(page,now=bound+timedelta(microseconds=1))
    elif fault in {'negative','unknown'}:backup=replace(backup,status=model.FAIL if fault=='negative' else model.UNKNOWN)
    elif fault=='wrong_phase':backup=replace(backup,recovery=replace(backup.recovery,phase='FINANCIAL_VERIFICATION'))
    elif fault=='manual':backup=replace(backup,recovery=replace(backup.recovery,automatic=False,operator_required=True))
    page=replace(page,rows=[backup if row.key=='backup_restore' else row for row in page.rows])
    facts=presentation.health_facts(page)
    assert not HISTORY_KEYS.intersection(facts['active']+facts['warnings'])
    if fault is None:
        assert serialization.public_payload(page)['dashboard_health']['color']=='green'
        assert facts=={'active':[],'warnings':[]}
    else:
        assert 'backup_restore' in facts['active']+facts['warnings']
        assert serialization.public_payload(page)['dashboard_health']['color']!='green'


def test_partial_human_current_does_not_promote_strict_financial_authority():
    from sentinel.panel import delivery
    page=renewal_panel();page=replace(page,observation_current=False,observation_changed_scopes=('PAPER',),
        observation_display_current=True,observation_display_keys=delivery.display_keys(page),
        observation_revalidated_keys=('paper_reconciliation',),observation_valid_until=page.now+timedelta(seconds=10))
    wire=serialization.public_payload(page)
    assert wire['observation']['current'] is True and wire['observation']['strict_current'] is False
    assert wire['operational']==model.UNKNOWN
    assert wire['dashboard_health']['color']=='green'


def test_normal_backup_intersection_guard_has_executed_falsifier(monkeypatch):
    monkeypatch.setattr(presentation,'_backup_maintenance_normal',lambda *args:True)
    with pytest.raises(AssertionError):
        test_normal_backup_maintenance_intersection_uses_only_original_typed_admission(True,'wrong_phase')


def test_current_candidate_history_contradiction_guard_has_executed_falsifier(monkeypatch):
    from tests.sentinel.test_resolved_transport_history import test_unresolved_or_foreign_interruption_keeps_its_negative
    text=inspect.getsource(model.project_retirement_history)
    guard='or candidate is not None and not idle_subject'
    assert text.count(guard)==1
    namespace=dict(vars(model));exec(text.replace(guard,''),namespace)
    monkeypatch.setattr(model,'project_retirement_history',namespace['project_retirement_history'])
    with pytest.raises(AssertionError):
        test_unresolved_or_foreign_interruption_keeps_its_negative('wrong_observation')


@pytest.mark.parametrize('checking',[True,False])
@pytest.mark.parametrize('key',['authority','broker','backup_restore'])
def test_one_current_fault_does_not_invent_a_paper_or_historical_incident(checking,key):
    page=renewal_panel(checking=checking,project=False)
    page=replace(page,rows=model.project_opening_rows([replace(row,status=model.FAIL)
        if row.key==key else row for row in page.rows],now=page.now))
    assert presentation.health_facts(page)=={'active':[key],'warnings':[]}
    assert serialization.public_payload(page)['dashboard_health']['color']=='red'
    assert not presentation._retired_check_work_normal(page)
    assert not presentation._clean_skip_work_normal(page)


def test_coupling_paper_row_attribution_to_headline_capabilities_is_detected(monkeypatch):
    original=presentation._positive_retirement_paper
    monkeypatch.setattr(presentation,'_positive_retirement_paper',lambda panel,row:
        original(panel,row) and presentation._retired_current_capabilities(panel))
    with pytest.raises(AssertionError):
        test_one_current_fault_does_not_invent_a_paper_or_historical_incident(False,'authority')
