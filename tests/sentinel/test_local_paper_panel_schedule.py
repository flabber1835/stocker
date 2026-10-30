"""Only a proved future scheduled wait is neutral in local PAPER readiness."""
import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import textwrap

import pytest

from sentinel.panel import model

NOW = datetime(2026, 10, 21, 21, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 22, 13, 31, tzinfo=timezone.utc)


def panel(*, local=True, scheduled=True):
    rows = [model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN),
        model.Row('automation_step_open', 'Open', 'WAITING_OPEN', model.WARN),
        model.Row('shadow_verification', 'Book', 'VERIFIED', model.OK),
        model.Row('authority', 'Authority', 'PASS', model.OK),
        model.Row('alpaca_account', 'Account', 'ACTIVE', model.OK)]
    if scheduled:
        rows.append(model.paper_reconciliation_row(state='SCHEDULED',
            cycle_state='WAITING_OPEN', scheduled_until=OPEN, detail='proved future plan'))
    return model.Panel(rows=rows, now=NOW, local_paper_mode=local)


def test_local_ready_schedule_is_operational_green_without_claiming_execution():
    p = panel()
    assert p.operational == model.OK
    assert p.row('automation_cycle').value == 'WAITING_OPEN'
    assert p.row('automation_cycle').status == model.WARN
    assert 'NOT VERIFIED' in p.row('paper_reconciliation').value


def test_normal_mode_keeps_existing_readiness_policy():
    assert panel(local=False).operational == model.WARN


def test_scheduled_proof_is_required():
    assert panel(scheduled=False).operational == model.WARN


@pytest.mark.parametrize('defect,expected', [
    ('expired', model.FAIL), ('source', model.FAIL), ('account', model.FAIL),
    ('unknown', model.UNKNOWN), ('other_warning', model.WARN),
    ('source_error', model.FAIL), ('unexpected_wait', model.WARN),
    ('stale_wait', model.FAIL)])
def test_local_schedule_never_hides_current_errors(defect, expected):
    p = panel()
    if defect == 'expired':
        p = replace(p, now=OPEN + timedelta(seconds=1))
    elif defect == 'source':
        p.rows.append(model.Row('feed', 'Feed', 'REFUSED', model.FAIL))
    elif defect == 'account':
        p.rows.append(model.Row('broker', 'Broker', 'UNKNOWN OUTCOME', model.FAIL))
    elif defect == 'unknown':
        p.rows.append(model.Row('runtime_identity', 'Runtime', 'UNKNOWN', model.UNKNOWN))
    elif defect == 'other_warning':
        p.rows.append(model.Row('feed', 'Feed', 'PENDING', model.WARN))
    elif defect == 'source_error':
        p.source_errors.append('unreadable database')
    elif defect == 'unexpected_wait':
        p.rows[0] = model.Row('automation_cycle', 'Cycle', 'RETRY_WAIT', model.WARN)
    elif defect == 'stale_wait':
        p.rows[0] = model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN,
            required_current=True, valid_until=NOW-timedelta(seconds=1))
    assert p.operational == expected


def test_scheduled_proof_guard_falsifier(monkeypatch):
    tree = ast.parse(textwrap.dedent(inspect.getsource(model.Panel.operational.fget)))
    tree.body[0].decorator_list = []
    assignment = next(node for node in tree.body[0].body if isinstance(node, ast.Assign))
    assignment.value = ast.Constant(True)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, 'removed-local-scheduled-proof', 'exec'), vars(model), namespace)
    monkeypatch.setattr(model.Panel, 'operational', property(namespace['operational']))
    with pytest.raises(AssertionError):
        test_scheduled_proof_is_required()


@pytest.mark.parametrize('local,proof,defect,expected', [
    (True, True, 'unstamped', model.OK),
    (False, True, 'unstamped', model.WARN),
    (True, False, 'unstamped', model.WARN),
    (True, True, 'mismatch', model.FAIL),
    (True, True, 'global_mismatch', model.FAIL),
    (True, True, 'global_history', model.WARN),
    (True, False, 'global_history', model.FAIL),
    (True, True, 'history_bool', model.FAIL),
    (True, True, 'history_zero', model.FAIL),
    (True, True, 'integrity_refusal', model.FAIL),
    (True, True, 'stamped_history', model.WARN),
    (True, False, 'stamped_history', model.FAIL),
    (True, True, 'stamped_history_no_count', model.FAIL),
    (True, True, 'stamped_history_bool', model.FAIL),
    (True, True, 'stamped_history_zero', model.FAIL),
    (True, True, 'stamped_current_mismatch', model.FAIL),
])
def test_future_unstamped_plan_requires_bound_local_scheduled_proof(
        monkeypatch, local, proof, defect, expected):
    from types import SimpleNamespace
    from sentinel import informational_paper_mirror as mirror, local_paper
    from sentinel.feed import readers as publication
    from sentinel.panel import sources

    monkeypatch.setattr(sources, '_informational_mirror_count', lambda _: 1)
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda _: {
        'state': 'WAITING_OPEN', 'plan_id': 'current', 'plan_fingerprint': 'a'*64})
    monkeypatch.setattr(publication, 'current', lambda _: SimpleNamespace(version=4))
    monkeypatch.setattr(publication, 'frontier', lambda *_: '2026-10-21')
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _: local)
    scheduled_calls = []
    def scheduled(*_):
        scheduled_calls.append(True)
        return (model.paper_reconciliation_row(state='SCHEDULED',
            cycle_state='WAITING_OPEN', scheduled_until=OPEN) if proof else None)
    monkeypatch.setattr(sources, '_scheduled_preopen_mirror', scheduled)

    def transport(*_, **__):
        if defect.startswith('stamped_'):
            return {'status': mirror.MISMATCH, 'historical_mismatch_count':
                {'stamped_history':1, 'stamped_history_no_count':None,
                 'stamped_history_bool':True, 'stamped_history_zero':0,
                 'stamped_current_mismatch':1}[defect]}
        if defect == 'integrity_refusal':
            raise mirror.InformationalPaperMirrorRefused('authenticated mirror coverage changed')
        if defect in {'global_history', 'history_bool', 'history_zero'}:
            return {'status': mirror.MISMATCH, 'historical_mismatch_count':
                {'global_history':1, 'history_bool':True, 'history_zero':0}[defect]}
        if defect == 'global_mismatch':
            return {'status': mirror.MISMATCH}
        return {'status': mirror.NO_UNIT_CHANGE}
    def current(*_, **__):
        if defect in {'mismatch', 'stamped_current_mismatch'}:
            raise mirror.InformationalPaperMirrorMismatch('current mismatch')
        if defect.startswith('stamped_'):
            return {'status':mirror.PENDING}
        raise mirror.InformationalPaperMirrorUnstamped('future plan not transported')
    monkeypatch.setattr(mirror, 'require_transport_permitted', transport)
    monkeypatch.setattr(mirror, 'require_current_plan_status', current)
    row = sources._dual_paper_row(object(), informational_paper_mirror=mirror,
        publication=publication, feed_store=None)
    assert row.status == expected
    assert bool(scheduled_calls) == (local and defect in {'unstamped','global_history','stamped_history'})
    if expected == model.OK:
        assert 'SCHEDULED' in row.value and 'NOT VERIFIED' in row.value
    if defect in {'global_history','stamped_history'} and proof:
        assert row.paper_alignment == 'SCHEDULED_WITH_HISTORY'
        assert row.effective_status(NOW) == model.WARN
        assert row.effective_status(OPEN) == model.FAIL
        assert 'HISTORICAL MIRROR WARNING' in row.value and 'BLOCKED' not in row.value
        assert 'earlier transported plans' in row.detail


def test_removing_local_account_guard_breaks_normal_mode_regression(monkeypatch):
    from sentinel.panel import sources
    tree = ast.parse(inspect.getsource(sources._dual_paper_row))
    guard = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
        and 'local_paper.require_bound_account(conn)' in ast.unparse(node.test))
    guard.test = ast.Constant(True)
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), 'removed-local-account-guard', 'exec'),
        vars(sources), namespace)
    monkeypatch.setattr(sources, '_dual_paper_row', namespace['_dual_paper_row'])
    with pytest.raises(AssertionError):
        test_future_unstamped_plan_requires_bound_local_scheduled_proof(
            monkeypatch, False, True, 'unstamped', model.WARN)
