"""Known submitted commands are progress; uncertainty is never inferred away."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import ast
import inspect
import pytest

from sentinel.panel import model, retry_status, presentation

NOW = datetime(2026, 11, 4, 14, 35, tzinfo=timezone.utc)


def cycle():
    clean = dict(clean=True, runtime_state='RUNNING', unresolved=[],
                 foreign_orders=[], foreign_positions=[], restricted_securities={},
                 observation_id=334)
    return dict(cycle_id='synthetic-cycle', state='RECONCILING', plan_id='synthetic-plan',
        failure_code='COMMANDS_IN_FLIGHT', failure_detail='awaiting reconciliation',
        clean_reconciliation_id='334', updated_at=NOW-timedelta(seconds=30),
        execution_open_at=NOW-timedelta(minutes=5), execute_at=NOW-timedelta(minutes=4),
        execution_close_at=NOW+timedelta(hours=6), next_wake_at=NOW+timedelta(minutes=10),
        diagnostic={'paper_submission_authorized':True,'operator_attention_required':False,
            'plan':{'plan_id':'synthetic-plan'},'preflight':deepcopy(clean),
            'execution':{'runtime_state':'RUNNING','submitted':['synthetic-key'],
                'refused':{},'deferred':[],'restricted_securities':{},
                'reconciliation':deepcopy(clean)}})


def summary(c):
    fields=inspect.signature(model.automation_cycle_row).parameters
    return model.automation_cycle_row(installed=True,enabled=True,
        **{k:v for k,v in c.items() if k in fields})


def steps(c, *, submission=None):
    if submission is None:
        submission = c
    event={'from_state':'EXECUTING','to_state':'RECONCILING','at':submission['updated_at'],
        'detail':{'failure_code':submission['failure_code'],'failure_detail':submission['failure_detail'],
            'last_clean_reconciliation_id':submission['clean_reconciliation_id'],
            'next_wake_at':submission['next_wake_at'].isoformat(),'diagnostic':deepcopy(submission['diagnostic'])}}
    return model.automation_step_rows(installed=True,enabled=True,cycle=c,events=[event])


def test_reproduced_clean_submitted_cycle_is_not_a_failed_cycle():
    row=summary(cycle())
    assert row.status==row.effective_status(NOW)==model.WARN
    assert row.recovery.automatic and row.recovery.deadline==cycle()['execution_close_at']
    assert 'progress COMMANDS_IN_FLIGHT' in row.detail
    assert row.effective_status(row.recovery.deadline+timedelta(microseconds=1))==model.FAIL


def test_reproduced_clean_submission_is_not_interrupted_transport():
    rows={r.key:r for r in steps(cycle())}
    assert rows['automation_step_transport'].status==model.OK
    assert rows['automation_step_reconcile'].effective_status(NOW)==model.WARN
    assert 'INTERRUPTED' not in rows['automation_step_transport'].value


@pytest.mark.parametrize('adverse_history', [False, True])
def test_recovery_retry_cannot_rewrite_the_earlier_submission(adverse_history):
    submission = cycle()
    if adverse_history:
        submission['diagnostic']['callback_failure'] = 'TRANSIENT_INFRASTRUCTURE'
    current = dict(cycle(), state='RETRY_WAIT', retry_phase='RECOVER',
        failure_code='TransientInfrastructureFailure', callback_failure='TRANSIENT_INFRASTRUCTURE',
        exception_type='sentinel.automation.model.TransientInfrastructureFailure')
    rows = {row.key:row for row in steps(current, submission=submission)}
    transport = rows['automation_step_transport']
    if adverse_history:
        assert transport.status == model.FAIL and 'INTERRUPTED' in transport.value
    else:
        assert transport.status == model.OK and transport.value == 'COMPLETE'


@pytest.mark.parametrize('path,value', [
    (('state',),'EXECUTING'), (('failure_code',),'UNKNOWN'),
    (('plan_id',),'foreign-plan'), (('clean_reconciliation_id',),None),
    (('terminal_reason',),'FAILED'), (('callback_failure',),'TIMEOUT'),
    (('execution_close_at',),None), (('next_wake_at',),None),
    (('next_wake_at',),NOW-timedelta(minutes=1)),
    (('execution_open_at',),NOW.replace(tzinfo=None)),
    (('diagnostic','paper_submission_authorized'),False),
    (('diagnostic','operator_attention_required'),True),
    (('diagnostic','execution','runtime_state'),'BROKER_DEGRADED'),
    (('diagnostic','execution','submitted'),[]),
    (('diagnostic','execution','submitted'),['duplicate','duplicate']),
    (('diagnostic','execution','refused'),{'security':'refused'}),
    (('diagnostic','execution','deferred'),['security']),
    (('diagnostic','execution','restricted_securities'),{'security':'action'}),
    (('diagnostic','execution','reconciliation','clean'),False),
    (('diagnostic','execution','reconciliation','observation_id'),335),
    (('diagnostic','preflight','observation_id'),0),
    (('diagnostic','preflight','observation_id'),-1),
    (('diagnostic','execution','reconciliation','unresolved'),['unknown-key']),
    (('diagnostic','preflight','foreign_orders'),['foreign-key']),
    (('diagnostic','preflight','clean'),False),
])
def test_incomplete_or_adverse_progress_proof_still_fails(path,value):
    c=cycle();item=c
    for k in path[:-1]:item=item[k]
    item[path[-1]]=value
    assert not retry_status.submitted_commands_progress(c)
    assert summary(c).effective_status(NOW)==model.FAIL


def test_normal_progress_cannot_hide_current_unknown_broker_or_trading_outcome():
    c=cycle();rows=[summary(c),*steps(c)]
    rows.append(model.broker_row(available=True,positions=1,completeness='COMPLETE',
        runtime_state='RUNNING',uncertain_commands=1,as_of=NOW,
        valid_until=NOW+timedelta(seconds=30)))
    page=model.Panel(rows=rows,now=NOW)
    assert page.overall==model.FAIL
    assert 'broker' in presentation.health_facts(page)['active']


def test_removed_attention_guard_is_detected():
    fn=retry_status.submitted_commands_progress
    tree=ast.parse(inspect.getsource(fn));hits=[]
    class Remove(ast.NodeTransformer):
        def visit_Compare(self,node):
            if ast.unparse(node)=="diagnostic.get('operator_attention_required') is not False":
                hits.append(True);return ast.Constant(False)
            return self.generic_visit(node)
    tree=ast.fix_missing_locations(Remove().visit(tree));assert len(hits)==1
    scope=dict(retry_status.__dict__);exec(compile(tree,'<removed attention guard>','exec'),scope)
    c=cycle();c['diagnostic']['operator_attention_required']=True
    assert not fn(c) and scope[fn.__name__](c)
