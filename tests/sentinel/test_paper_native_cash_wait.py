"""Published cash cannot be stamped into a fresh plan before balance coherence."""
import ast
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel import binding
from sentinel.execution import broker_cash
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerObservation
from sentinel.execution.plan import ExecutionPlan
from sentinel.paper import cash
from sentinel.paper.model import PaperActivationRefused, PaperRetryableRefused
from tests.sentinel.test_paper_current_cash_acceptance import conn, pg, selected, NOW, ACCOUNT_NUMBER


@pytest.fixture
def case(conn):
    empty, _ = selected(events='')
    initial = asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=empty,
        broker='alpaca', account_id=ACCOUNT_NUMBER, through=NOW))
    bound = binding.require(conn)
    plan = ExecutionPlan('already-anchored-plan', date(2026, 8, 19), date(2026, 8, 20),
        Decimal(0), deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        account_cash=Decimal('11079.88'), account_nav=Decimal('30000'))
    baseline = broker_cash.record_plan_baseline(conn, plan_id=plan.plan_id,
        decision_session=plan.decision_session, activity_state=initial)
    conn.commit()
    broker, _ = selected()
    state = asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker,
        broker='alpaca', account_id=ACCOUNT_NUMBER, through=NOW + timedelta(hours=1)))
    identity = BrokerAccountIdentity('alpaca', ACCOUNT_NUMBER)
    return dict(plan=plan, deployment=bound.identity, baseline=baseline, cash_broker=broker,
        account=BrokerAccountSnapshot(identity=identity, cash=plan.account_cash,
            equity=plan.account_nav, multiplier=Decimal(1), status='ACTIVE'),
        observation=BrokerObservation(observed_at=NOW + timedelta(hours=1), account_identity=identity),
        activity_state=state)


def check(conn, case, **changes):
    values = {key: value for key, value in case.items() if key not in {'baseline', 'cash_broker'}}
    return cash._cash_authority_or_refuse(conn, **dict(values, **changes))


def require_wait(conn, case):
    try:
        check(conn, case, permit_new_activity=True)
    except PaperRetryableRefused:
        return
    except PaperActivationRefused:
        pytest.fail('known native cash gap permanently blocked read-only preparation')
    pytest.fail('cash authorized before the native credit reached account cash')


def test_known_credit_waits_without_reanchoring_or_renewing_generic_grace(conn, case):
    for hours in (1, 2, 14):
        case['activity_state'] = asyncio.run(broker_cash.ingest_account_cash(conn,
            broker_adapter=case['cash_broker'], broker='alpaca', account_id=ACCOUNT_NUMBER,
            through=NOW + timedelta(hours=hours)))
        case['observation'] = replace(case['observation'], observed_at=NOW + timedelta(hours=hours))
        require_wait(conn, case)
        assert broker_cash.load_plan_baseline(conn, plan_id=case['plan'].plan_id) == case['baseline']
        assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-account-lag:v1:%'").fetchone()[0] == 0
    credited = replace(case['account'], cash=Decimal('11155.77'))
    assert check(conn, case, account=credited, permit_new_activity=True) is True
    assert broker_cash.load_plan_baseline(conn, plan_id=case['plan'].plan_id) == case['baseline']


def test_pending_credit_never_authorizes_current_plan_execution(conn, case):
    with pytest.raises(PaperActivationRefused) as refused:
        check(conn, case, permit_new_activity=False)
    assert not isinstance(refused.value, PaperRetryableRefused)


@pytest.mark.parametrize('value', ['11077.88', '11081.88', '11157.77'])
def test_other_cash_differences_do_not_earn_known_credit_wait(conn, case, value):
    with pytest.raises(PaperActivationRefused) as refused:
        check(conn, case, account=replace(case['account'], cash=Decimal(value)), permit_new_activity=True)
    assert not isinstance(refused.value, PaperRetryableRefused)


def test_missing_baseline_still_refuses_instead_of_waiting_or_backfilling(conn, case):
    conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id,))
    with pytest.raises(PaperActivationRefused, match='cannot be backfilled') as refused:
        check(conn, case, permit_new_activity=True)
    assert not isinstance(refused.value, PaperRetryableRefused)


def test_removed_pending_classification_is_detected(conn, case, monkeypatch):
    tree = ast.parse(textwrap.dedent(inspect.getsource(cash._cash_authority_or_refuse)))
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.If)
        and 'permit_new_activity and activity_state is not None' in ast.unparse(n.test)]
    assert len(matches) == 1
    matches[0].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-native-cash-wait>', 'exec'), vars(cash), namespace)
    monkeypatch.setattr(cash, '_cash_authority_or_refuse', namespace['_cash_authority_or_refuse'])
    with pytest.raises(pytest.fail.Exception): require_wait(conn, case)
