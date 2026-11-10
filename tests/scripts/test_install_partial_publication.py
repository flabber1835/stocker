"""Actual public partial delivery settles inside one unchanged install budget."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from textwrap import dedent
import inspect

import pytest

from tests.scripts.test_install_unified_readiness import (
    run_child,checking,readiness,scheduled_page,keyed,operation,coordinator,host_module,model)


@pytest.mark.parametrize('scopes',[('SHADOW',),('PAPER',),('SHADOW','PAPER')])
def test_actual_withheld_plan_and_review_settle_in_one_child(monkeypatch,scopes):
    partial,expected=scheduled_page(clean=True,changed_scopes=scopes)
    current,_=scheduled_page(clean=True)
    original=deepcopy(partial)
    assert partial['operator_review'] is None
    assert keyed(partial,'paper_plan')['paper_plan'] is None
    result,calls,diagnostic,elapsed=run_child(monkeypatch,[checking(current),partial,current],expected)
    assert result['readiness_observations']==3 and len(calls)==3 and elapsed==10
    assert result['color']=='green' and partial==original
    assert 'dashboard_subject_revalidation' in diagnostic
    assert result['installation_panel_valid_until']==current['dashboard_health']['valid_until']


def test_restoring_the_old_eager_plan_assertion_reproduces_the_recorded_failure(monkeypatch):
    fix=(" if header=='PARTIAL':\n  return partial_wait(page,rows,checking,workflows,retiring)\n"
         " if strict is False:\n  return partial_wait(page,rows,checking,workflows,retiring)\n")
    assert readiness.PANEL_WAIT.count(fix)==1
    monkeypatch.setattr(readiness,'PANEL_WAIT',readiness.PANEL_WAIT.replace(fix,''))
    with pytest.raises(AssertionError):
        test_actual_withheld_plan_and_review_settle_in_one_child(monkeypatch,('SHADOW','PAPER'))


@pytest.mark.parametrize('key',['book','shadow_verification','authority','broker'])
@pytest.mark.parametrize('status',['fail','unknown'])
def test_withdrawal_cannot_hide_an_original_negative(monkeypatch,key,status):
    partial,expected=scheduled_page(clean=True,changed_scopes=('SHADOW','PAPER'))
    current,_=scheduled_page(clean=True)
    row=keyed(partial,key)
    assert row['current'] is False and row['status']=='pending' and row['color']=='neutral'
    row['original_status']=status
    audit={}
    with pytest.raises(AssertionError,match='NONSTARTUP_READINESS_FAILURE'):
        run_child(monkeypatch,[partial,current],expected,audit=audit)
    assert len(audit['calls'])==1 and audit['out'].getvalue()==''


def test_original_negative_guard_has_executed_falsifier(monkeypatch):
    guard=" assert negatives<=startup|retiring|unavailable,'NONSTARTUP_READINESS_FAILURE'\n"
    assert readiness.PANEL_WAIT.count(guard)==1
    monkeypatch.setattr(readiness,'PANEL_WAIT',readiness.PANEL_WAIT.replace(guard,''))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_withdrawal_cannot_hide_an_original_negative(monkeypatch,'book','fail')


@pytest.mark.parametrize('fault',['unknown_scope','empty_scope','duplicate_scope','wrong_revalidation',
    'current_flag','status','retained_payload','review','missing_plan','plan_not_ok','source_error',
    'independent_failure','unexpected_warning','future_publication','unbounded_publication'])
def test_partial_is_a_narrow_wait_not_a_malformed_or_failed_readiness_escape(monkeypatch,fault):
    partial,expected=scheduled_page(clean=True,changed_scopes=('SHADOW','PAPER'))
    row=keyed(partial,'paper_plan');observation=partial['observation']
    if fault=='unknown_scope':observation['changed_scopes']=['FOREIGN']
    elif fault=='empty_scope':observation['changed_scopes']=[]
    elif fault=='duplicate_scope':observation['changed_scopes']=['SHADOW','SHADOW']
    elif fault=='wrong_revalidation':observation['revalidated_keys']=['paper_plan']
    elif fault=='current_flag':row['current']=True
    elif fault=='status':row['status']='ok'
    elif fault=='retained_payload':row['paper_plan']={'plan_id':expected['plan']}
    elif fault=='review':partial['operator_review']={'status':'CLEAN'}
    elif fault=='missing_plan':partial['rows'].remove(row)
    elif fault=='plan_not_ok':row['original_status']='warn'
    elif fault=='source_error':partial['source_errors']=['source unavailable']
    elif fault=='independent_failure':keyed(partial,'backup_restore').update(original_status='fail',status='fail',color='red')
    elif fault=='unexpected_warning':partial['dashboard_health']['review_conditions'].append('foreign')
    elif fault=='future_publication':partial['as_of']=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()
    else:observation['valid_until']=(datetime.fromisoformat(partial['as_of'])+timedelta(seconds=31)).isoformat()
    audit={}
    with pytest.raises((AssertionError,KeyError,ValueError)):
        run_child(monkeypatch,[partial],expected,audit=audit)
    assert len(audit['calls'])==1 and audit['out'].getvalue()==''


@pytest.mark.parametrize('fault',['plan','review','financial'])
def test_partial_wait_cannot_change_final_positive_requirements(monkeypatch,fault):
    partial,expected=scheduled_page(clean=True,changed_scopes=('PAPER',))
    current,_=scheduled_page(clean=True)
    if fault=='plan':keyed(current,'paper_plan')['paper_plan']['plan_id']='foreign'
    elif fault=='review':current['operator_review']=None
    else:keyed(current,'shadow_verification').update(status='fail',original_status='fail',color='red')
    audit={}
    with pytest.raises((AssertionError,KeyError,ValueError)):
        run_child(monkeypatch,[partial,current],expected,audit=audit)
    assert len(audit['calls'])==2 and audit['out'].getvalue()==''


def test_perpetual_partial_stops_at_original_deadline_without_success_or_log_spam(monkeypatch):
    partial,expected=scheduled_page(clean=True,changed_scopes=('SHADOW',))
    original=deepcopy(partial);audit={}
    with pytest.raises(AssertionError,match='APPLICATION_READINESS_DEADLINE'):
        run_child(monkeypatch,[partial],expected,seconds=10,audit=audit)
    assert len(audit['calls'])==2 and audit['out'].getvalue()==''
    assert audit['err'].getvalue().count('PENDING')==1 and partial==original


def test_one_actual_advance_completes_all_stages_through_real_partial_wait(operation,monkeypatch):
    host,journal,delivery=operation
    partial,expected=scheduled_page(clean=True,changed_scopes=('SHADOW','PAPER'))
    current,_=scheduled_page(clean=True)
    preserved=deepcopy(host.state);observations=[]
    migrate=coordinator.evidence.migrate_operational_schema
    def paged(*args,**kwargs):
        result=migrate(*args,**kwargs)
        return {**result,'complete':host.migration_count>=3}
    monkeypatch.setattr(coordinator.evidence,'migrate_operational_schema',paged)
    def observe(*_,**options):
        result,calls,_,elapsed=run_child(monkeypatch,[checking(current),partial,current],expected)
        host.clock+=elapsed;observations.append((result,len(calls),options['wait_until']))
        return result
    monkeypatch.setattr(coordinator.evidence,'panel',observe)
    receipt=delivery.advance()
    assert receipt['stage']=='VERIFIED' and host.state==preserved
    assert len(observations)==1 and observations[0][1]==3
    starts=[call for call in host.calls if isinstance(call,tuple) and call[0]=='up']
    assert len(starts)==2  # One shadow start and one remaining-role group start.
    assert host.migration_count==3 and host.canonical_count==2
    assert 'verification_recovery' not in receipt['artifacts']
    assert len([event for event in receipt['history'] if event['stage']=='START_REQUESTED'])==1
    assert set(receipt['artifacts']['started_applications'])==set(host_module.SERVICES)


def test_expired_preflight_cannot_promote_a_just_completed_schema_page(operation,monkeypatch):
    _,journal,delivery=operation
    while journal.read()['stage']!='SCHEMA_INSTALL_REQUESTED':delivery.step()
    original=coordinator.evidence.migrate_operational_schema
    expires=datetime.fromisoformat(journal.read()['artifacts']['preflight_at'])+timedelta(seconds=901)
    def delayed(*args,**kwargs):
        result=original(*args,**kwargs)
        monkeypatch.setattr(coordinator,'utcnow',lambda:expires)
        return result
    monkeypatch.setattr(coordinator.evidence,'migrate_operational_schema',delayed)
    with pytest.raises(model.DeliveryRefused,match='PROOF_HANDOFF_INTERVAL_EXPIRED'):
        delivery.step()
    assert journal.read()['stage']=='SCHEMA_INSTALL_REQUESTED'


def test_schema_post_work_freshness_guard_has_executed_falsifier(operation,monkeypatch):
    source=dedent(inspect.getsource(coordinator.Delivery.step))
    guard="        self._fresh(artifacts['preflight_at'])\n"
    anchor='        migration=evidence.migrate_operational_schema(self.host,candidate)\n'
    assert source.count(anchor+guard)==1
    namespace={}
    exec(compile(source.replace(anchor+guard,anchor),'removed-post-page-freshness','exec'),coordinator.__dict__,namespace)
    monkeypatch.setattr(coordinator.Delivery,'step',namespace['step'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_expired_preflight_cannot_promote_a_just_completed_schema_page(operation,monkeypatch)


def test_schema_page_limit_has_an_executed_falsifier(operation,monkeypatch):
    host,_,delivery=operation
    original=coordinator.evidence.migrate_operational_schema
    def endless(*args,**kwargs):
        result=original(*args,**kwargs)
        assert host.migration_count<=12,'schema page limit was removed'
        return {**result,'complete':False}
    monkeypatch.setattr(coordinator.evidence,'migrate_operational_schema',endless)
    original_require=coordinator.require
    monkeypatch.setattr(coordinator,'require',lambda ok,reason:
        None if reason=='OPERATIONAL_BOOTSTRAP_PAGE_LIMIT' else original_require(ok,reason))
    with pytest.raises(AssertionError,match='schema page limit was removed'):
        delivery.advance()
