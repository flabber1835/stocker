"""Executor wiring uses exact protected terms, reconciliations and durable rows."""
import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import inspect

import pytest

from sentinel import binding
from sentinel.execution import commands, executor, journal, protected_limits, target_reprojection
from sentinel.execution.contract import BrokerAccountIdentity, BrokerOrder, OrderTerms, Side
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.paper import execution as paper_execution
from tests.sentinel.test_guarded_execution_broker import conn, pg  # noqa: F401
from tests.sentinel.test_opening_submit_freshness_boundary import instrument
from tests.sentinel.test_limit_day_sizing import references
from tests.v5.test_opening import case, base


DEPLOYMENT = DeploymentIdentity("protected-wiring", "sim", "SIM-ACCOUNT", 1)
LIMIT = OrderTerms(order_type="limit", limit_price=D(100))


@pytest.fixture(autouse=True)
def legacy_environment(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)


def select(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")


def delta():
    return commands.Delta(instrument().security_id, D(1), D(0), D(0), D(1),
                          commands.DeltaClass.ACTIONABLE)


def term_revisions(conn, plan_id):
    original, resumed = executor._command_for_delta(conn=conn, deployment=DEPLOYMENT,
        plan_id=plan_id, delta=delta(), instrument=instrument(), order_terms=LIMIT)
    assert not resumed
    journal.save_command(conn, original)
    unchanged, resumed = executor._command_for_delta(conn=conn, deployment=DEPLOYMENT,
        plan_id=plan_id, delta=delta(), instrument=instrument(), order_terms=LIMIT)
    assert resumed and unchanged.client_key == original.client_key
    changed, resumed = executor._command_for_delta(conn=conn, deployment=DEPLOYMENT,
        plan_id=plan_id, delta=delta(), instrument=instrument(),
        order_terms=replace(LIMIT, limit_price=D(101)))
    assert not resumed and changed.identity.revision == original.identity.revision + 1
    assert changed.client_key != original.client_key and changed.order_terms.limit_price == D(101)
    assert journal.load_commands(conn, DEPLOYMENT, plan_id=plan_id)[0].state is S.SUPERSEDED


def test_executor_resumes_only_identical_planned_terms_and_revises_changed_terms(conn):
    term_revisions(conn, "same-terms")


def test_removing_rebuilt_terms_binding_is_detected(conn, monkeypatch):
    source = inspect.getsource(executor._same_command_economics)
    needle = "        and left.order_terms == right.order_terms\n"
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, ""), "<private-rebuilt-terms>", "exec"),
         vars(executor), local)
    monkeypatch.setattr(executor, "_same_command_economics", local["_same_command_economics"])
    with pytest.raises(AssertionError):
        term_revisions(conn, "mutated-terms")




def test_public_executor_forwards_cohort_callback_under_actual_writer_lock(conn, monkeypatch):
    from sentinel.execution.plan import ExecutionPlan
    plan = ExecutionPlan("public-callback", date(2026, 8, 10), date(2026, 8, 11), D(1))
    journal.save_plan(conn, plan)
    # Publication/media verification belongs to other tests; retain actual SQL
    # writer ownership while isolating this public-to-locked API handoff.
    original_lock = journal.writer_lock
    monkeypatch.setattr(journal, "writer_lock",
                        lambda connection: original_lock(connection, recovery_only=True))
    monkeypatch.setattr(executor, "_INCREASE_FENCE_REASONS", [])
    async def cohort(rec):
        return None
    async def entered(**kwargs):
        assert kwargs["increase_reconciliation_authority"] is cohort
        assert conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
            " AND locktype='advisory' AND classid=0 AND objid=%s AND granted)",
            (journal.WRITER_LOCK_KEY,)).fetchone()[0] is True
        return "locked-boundary"
    monkeypatch.setattr(executor, "_execute_session_locked", entered)
    result = asyncio.run(executor.execute_session(
        broker=object(), conn=conn, deployment=DEPLOYMENT, plan=plan, instruments={},
        today=plan.effective_session, increase_reconciliation_authority=cohort))
    assert result == "locked-boundary"


class ReceiptBroker(SimulatedBroker):
    def __init__(self):
        super().__init__(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
                         equity=D(100000), cash=D(100000))
        self.capabilities = replace(self.capabilities, protected_limit_day=True)
        self.sent_terms = []

    async def submit(self, *, client_key, instrument, side, quantity, order_terms=OrderTerms()):
        result = await super().submit(client_key=client_key, instrument=instrument,
                                      side=side, quantity=quantity)
        self.sent_terms.append(order_terms)
        if result.state is S.ACKNOWLEDGED:
            receipt = BrokerOrder(result.broker_order_id, client_key, instrument, side,
                S.ACKNOWLEDGED, quantity, order_terms=order_terms)
            return replace(result, receipt=receipt)
        return result


def protected_projection(*, missing=False, plan_id="cohort"):
    state, plan = case(entries=1, exposure="0.55")
    plan = replace(plan, plan_id=plan_id, deployment_id=DEPLOYMENT.deployment_id,
                   broker="sim", broker_account_id="SIM-ACCOUNT", takeover_epoch=1)
    projection = base(state, plan)
    refs = references(plan, projection)
    if missing:
        refs = replace(refs, prices={sid: price for sid, price in refs.prices.items()
                                    if sid != "SEC-AAA"})
    return state, plan, protected_limits.resolve_protected(
        state, plan, projection, refs, protected_limits.ProtectedLimitPolicy(100))


async def execute_locked(conn, monkeypatch, *, rejected=False, missing=False, plan_id="cohort"):
    select(monkeypatch)
    binding.bind(conn, deployment_id=DEPLOYMENT.deployment_id, broker="sim",
                 broker_account_id="SIM-ACCOUNT")
    _state, plan, projection = protected_projection(missing=missing, plan_id=plan_id)
    target_reprojection.record_projection(conn, projection)
    journal.save_plan(conn, plan)
    broker = ReceiptBroker()
    observed = await broker.observe()
    rec = ReconciliationResult(runtime_state=RuntimeState.RUNNING, observation=observed,
        expected={}, observed={}, observation_id=1)
    async def reconcile(**kwargs):
        return rec
    monkeypatch.setattr(executor.R, "reconcile", reconcile)
    calls = []
    async def cohort(current):
        assert current is rec and current.observation is observed
        assert not journal.load_commands(conn, DEPLOYMENT, plan_id=plan.plan_id)
        held = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
            " AND locktype='advisory' AND classid=0 AND objid=%s AND granted)",
            (journal.WRITER_LOCK_KEY,)).fetchone()[0]
        assert held is True
        calls.append(current)
        if rejected:
            raise ValueError("funding basis is unavailable")
    instruments = {"SEC-AAA": await broker.resolve_instrument(security_id="SEC-AAA", symbol="AAA")}
    # The locked executor is tested with real writer/journal SQL; separately
    # tested source/observation proofs are the only mocked external boundary.
    with journal.writer_lock(conn, recovery_only=True):
        result = await executor._execute_session_locked(
            broker=broker, conn=conn, deployment=DEPLOYMENT, plan=plan,
            instruments=instruments, today=plan.effective_session, actions=None,
            target_projection=projection, min_increment=D(1),
            increase_reconciliation_authority=cohort)
    return broker, result, calls, projection


@pytest.mark.parametrize("rejected", [False, True])
def test_executor_earns_exact_reconciliation_cohort_before_any_protected_promise(conn, monkeypatch, rejected):
    broker, result, calls, projection = asyncio.run(execute_locked(conn, monkeypatch, rejected=rejected))
    assert len(calls) == 1
    if rejected:
        assert not broker.sent_terms and not result.submitted and result.deferred == ("SEC-AAA",)
        assert "funding basis is unavailable" in result.detail
    else:
        assert len(result.submitted) == 1
        sent = result.submitted[0]
        assert sent.state is S.ACKNOWLEDGED and sent.order_terms == broker.sent_terms[0]
        assert sent.order_terms == protected_limits.order_terms_for(projection, sent.security_id)
        assert [row["to"] for row in journal.command_history(conn, sent.client_key)] == [
            "PLANNED", "SEND_PENDING", "ACKNOWLEDGED"]


def test_unavailable_opening_reference_is_deferred_even_when_projected_quantity_is_zero(conn, monkeypatch):
    broker, result, calls, _projection = asyncio.run(execute_locked(conn, monkeypatch, missing=True))
    assert not broker.sent_terms and not result.submitted and not calls
    assert result.deferred == ("SEC-AAA",)
    assert "REFERENCE_UNAVAILABLE" in result.deferral_reasons["SEC-AAA"]


def test_removing_executor_cohort_callback_is_detected(conn, monkeypatch):
    source = inspect.getsource(executor._execute_session_locked)
    needle = "await increase_reconciliation_authority(rec)"
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, "pass"), "<private-executor-cohort>", "exec"),
         vars(executor), local)
    monkeypatch.setattr(executor, "_execute_session_locked", local["_execute_session_locked"])
    with pytest.raises(AssertionError):
        test_executor_earns_exact_reconciliation_cohort_before_any_protected_promise(conn, monkeypatch, False)


@pytest.mark.parametrize("selected", [False, True])
def test_paper_opening_evidence_uses_separate_historical_route_without_quote_get(monkeypatch, selected):
    calls = []
    evidence = object()
    async def prices(*args, **kwargs):
        calls.append(kwargs)
        return evidence
    if selected:
        select(monkeypatch)
    monkeypatch.setattr("sentinel.execution.opening_sizing.prices_for_plan", prices)
    result = asyncio.run(paper_execution._opening_prices_or_retry(
        None, state=object(), plan=object(), broker=object()))
    assert result is (None if selected else evidence)
    assert len(calls) == (not selected)
