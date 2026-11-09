"""Execute host validators against strict and human-only post-trade publications."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest

from tests.scripts.test_sentinel_local_delivery_operator_review import (
    scheduled_page,keyed,execute_reader,checks,
)
from tests.scripts.test_install_unified_readiness import run_child,readiness,checking,starting


def completed_page(*,clean=False,notices=True,legacy=False):
    page,expected=scheduled_page(history=True,notices=notices,clean=clean)
    now=datetime.now(timezone.utc)
    intent=deepcopy(keyed(page,'paper_plan')['paper_plan'])
    intent.update(effective_session=now.date().isoformat(),
        execute_at=(now-timedelta(minutes=30)).isoformat())
    expected.update(effective=intent['effective_session'],handoff_mode='POST_TRADE')
    for row in page['rows']:
        if row['key']=='paper_plan':
            row.update(value='NOT PREPARED',status='pending',original_status='pending',color='amber',
                required_current=False,paper_plan=None,as_of=None,valid_until=None)
        elif row['key']=='paper_reconciliation':
            row.update(value='PAPER NOT VERIFIED · PENDING',paper_alignment='COMPLETED_WITH_HISTORY',
                as_of=now.isoformat(),valid_until=(now+timedelta(minutes=10)).isoformat(),recovery=None)
        elif row['key']=='automation_cycle' or row['key'].startswith('automation_step_'):
            row.update(value='SUCCEEDED',status='ok',original_status='ok',color='green',
                operational_fact={'kind':'AUTOMATION_CYCLE','state':'SUCCEEDED'},recovery=None,
                as_of=(now-timedelta(minutes=5)).isoformat(),valid_until=None)
    run=deepcopy(keyed(page,'automation_cycle'))
    run.update(key='trading_run',label='Today',value='SUCCEEDED',required_current=True,
        trading_run=dict(state='SUCCEEDED',intent=intent),
        valid_until=(now+timedelta(hours=1)).isoformat())
    page['rows'].append(run)
    page['dashboard_health'].update(label='Healthy · Today’s trading complete' if clean else 'Needs review',
        status='ok' if clean else 'warn',color='green' if clean else 'amber')
    if legacy:page['observation'].pop('strict_current',None)
    return page,expected


@pytest.mark.parametrize('legacy',[False,True])
def test_posttrade_resolved_notification_review_finishes_software_only_without_ack(monkeypatch,legacy):
    page,expected=completed_page(legacy=legacy)
    original=deepcopy(page)
    result=execute_reader(monkeypatch,page,expected)
    assert page==original and result['operator_review']['status']=='REVIEW'
    assert result['installation_review_pending'] is True and result['operational_ready'] is False
    assert result['installation_scope']=='POST_TRADE_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW'
    assert result['alerts']['status']=='warn' and result['sender']['status']=='ok'
    assert 'token' not in result['operator_review']


def test_posttrade_clean_publication_needs_no_future_plan_or_review_override(monkeypatch):
    page,expected=completed_page(clean=True,notices=False)
    assert keyed(page,'paper_plan')['paper_plan'] is None
    result=execute_reader(monkeypatch,page,expected)
    assert result['cycle']=='SUCCEEDED' and result['plan']['plan_id']==expected['plan']
    assert 'installation_review_pending' not in result


@pytest.mark.parametrize('fault',[
    'strict_false','legacy_false','active','warnings','sender_failed','financial_failed',
    'required_notice','stale_notice','future_notice','source','foreign_plan','incomplete',
    'missing_capability','expired_observation','expired_health','duplicate','unknown_finance',
    'pending_notice','notice_dlq','notice_recovery','notice_shape',
])
def test_posttrade_review_never_waives_current_negatives_or_original_bounds(monkeypatch,fault):
    page,expected=completed_page()
    past=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    if fault=='strict_false':page['observation']['strict_current']=False
    elif fault=='legacy_false':
        page['observation'].pop('strict_current',None);page['observation']['current']=False
    elif fault=='active':page['operator_review']['active']=['broker']
    elif fault=='warnings':page['operator_review']['warnings']=['book']
    elif fault=='sender_failed':keyed(page,'alert_dispatcher').update(status='fail',color='red')
    elif fault in {'financial_failed','unknown_finance'}:
        keyed(page,'paper_reconciliation').update(status='fail' if fault=='financial_failed' else 'unknown',color='red')
    elif fault=='required_notice':keyed(page,'automation_alerts')['required_current']=True
    elif fault=='stale_notice':keyed(page,'automation_alerts')['stale']=True
    elif fault=='future_notice':keyed(page,'automation_alerts')['future']=True
    elif fault=='pending_notice':keyed(page,'automation_alerts')['value']='1 pending · 0 DLQ · 1 unacked'
    elif fault=='notice_dlq':keyed(page,'automation_alerts')['value']='0 pending · 1 DLQ · 1 unacked'
    elif fault=='notice_recovery':keyed(page,'automation_alerts')['recovery']={'phase':'ALERT_DELIVERY','automatic':True}
    elif fault=='notice_shape':keyed(page,'automation_alerts')['value']='unclassified notification state'
    elif fault=='source':page['source_errors']=['unavailable']
    elif fault=='foreign_plan':keyed(page,'trading_run')['trading_run']['intent']['plan_id']='foreign'
    elif fault=='incomplete':keyed(page,'trading_run')['trading_run']['state']='RECONCILING'
    elif fault=='missing_capability':page['rows'].remove(keyed(page,'broker'))
    elif fault=='expired_observation':page['observation']['valid_until']=past
    elif fault=='expired_health':page['dashboard_health']['valid_until']=past
    else:page['rows'].append(deepcopy(keyed(page,'feed')))
    with pytest.raises((AssertionError,ValueError,KeyError,TypeError)):
        execute_reader(monkeypatch,page,expected)


def human_only(page):
    page=deepcopy(page)
    page['observation'].update(current=True,strict_current=False,display_current=True,
        changed_scopes=['PAPER'],revalidated_keys=['paper_reconciliation'])
    page['operator_review']=None
    return page


def test_human_current_strict_false_waits_then_validates_one_strict_posttrade_page(monkeypatch):
    page,expected=completed_page()
    pending=human_only(page);original=deepcopy(pending)
    from sentinel.panel import delivery
    monkeypatch.setattr(delivery,'row_current',lambda *_:pytest.fail('host waiter used private runtime models'))
    result,calls,diagnostic,elapsed=run_child(monkeypatch,[pending,page],expected)
    assert len(calls)==2 and elapsed==5 and pending==original
    assert result['installation_review_pending'] is True
    assert result['installation_panel_valid_until']==page['dashboard_health']['valid_until']
    assert 'dashboard_subject_revalidation' in diagnostic


def test_posttrade_normal_financial_startup_and_sender_startup_are_bounded_waits(monkeypatch):
    page,expected=completed_page()
    result,calls,_,elapsed=run_child(monkeypatch,[checking(page),starting(page),page],expected)
    assert len(calls)==3 and elapsed==10 and result['readiness_observations']==3
    assert result['installation_review_pending'] is True


@pytest.mark.parametrize('kind',['sender','financial'])
def test_human_only_wait_never_hides_a_current_negative(monkeypatch,kind):
    page,expected=completed_page()
    pending=human_only(page)
    key='alert_dispatcher' if kind=='sender' else 'paper_reconciliation'
    keyed(pending,key).update(status='fail',original_status='fail',color='red')
    audit={}
    with pytest.raises(AssertionError,match='NONSTARTUP_READINESS_FAILURE'):
        run_child(monkeypatch,[pending,page],expected,audit=audit)
    assert len(audit['calls'])==1 and not audit['out'].getvalue()


def test_perpetual_human_only_posttrade_view_cannot_extend_the_installation_clock(monkeypatch):
    page,expected=completed_page()
    audit={}
    with pytest.raises(AssertionError,match='APPLICATION_READINESS_DEADLINE'):
        run_child(monkeypatch,[human_only(page)],expected,seconds=10,audit=audit)
    assert len(audit['calls'])==2 and not audit['out'].getvalue()


def test_preopen_contract_and_original_scope_remain_selected(monkeypatch):
    page,expected=scheduled_page(history=True,notices=True)
    result=execute_reader(monkeypatch,page,expected)
    assert result['installation_scope']=='PRE_OPEN_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW'
    assert 'installation_review_pending' not in result


def test_explicit_strict_gate_has_an_executed_human_current_falsifier(monkeypatch):
    guard=" if 'strict_current' in observation: assert observation['strict_current'] is True\n"
    assert checks.PANEL.count(guard)==1
    monkeypatch.setattr(checks,'PANEL',checks.PANEL.replace(guard,''))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_posttrade_review_never_waives_current_negatives_or_original_bounds(monkeypatch,'strict_false')


def test_notification_history_guard_has_an_executed_pending_delivery_falsifier(monkeypatch):
    guard="      assert re.fullmatch(r'0 pending · 0 DLQ · [1-9][0-9]* unacked',fact['value'])\n"
    assert checks.PANEL.count(guard)==1
    monkeypatch.setattr(checks,'PANEL',checks.PANEL.replace(guard,''))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_posttrade_review_never_waives_current_negatives_or_original_bounds(monkeypatch,'pending_notice')
