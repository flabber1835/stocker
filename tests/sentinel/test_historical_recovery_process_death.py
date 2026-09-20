"""One compound recovery sequence across process death and shadow advancement."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import multiprocessing
import os
from pathlib import Path
import pickle
import signal
import sys
from types import SimpleNamespace

import pytest

from sentinel import backup_runtime_authority, rolling_runtime
from sentinel.config import DEFAULT_BASE_URL
from sentinel.execution import executor, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import AutomationExecutionGrant
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import store as feed_store
from sentinel.paper import recovery
from sentinel.paper.model import PaperRetryableRefused
from tests.sentinel.test_rolling_daily import refresh
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_paper_inputs import gateway, prepare
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source


def _send_and_die(dsn, broker, command, evidence_path, boundary):
    """Only the sender dies; its accepted broker state is retained externally."""
    connection = feed_store.connect(dsn)
    real_submit = broker.submit

    async def submit(**kwargs):
        outcome = await real_submit(**kwargs)
        # Persist only transport state, never local monkeypatches or credentials.
        state = {name: getattr(broker, name) for name in (
            "_orders", "_positions", "_fills", "_seq", "cash", "calls")}
        with evidence_path.open("wb") as output:
            pickle.dump(state, output)
            output.flush()
            os.fsync(output.fileno())
        if boundary == "accepted_before_ack_commit":
            os.kill(os.getpid(), signal.SIGKILL)
        return outcome

    broker.submit = submit
    with journal.writer_lock(connection):
        asyncio.run(executor._persist_and_send(connection, broker, command))
    os.kill(os.getpid(), signal.SIGKILL)


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux SIGKILL boundary")
@pytest.mark.parametrize("advanced", [False, True], ids=["same-close", "new-close"])
@pytest.mark.parametrize("boundary", [
    "accepted_before_ack_commit", "ack_committed_before_result"])
def test_killed_sender_absence_and_late_fill_keep_original_identity(
        conn, gateway, operational_source, monkeypatch, tmp_path,
        advanced, boundary):
    monkeypatch.setattr(backup_runtime_authority, "POLICY_MARKER",
                        Path("/audit/no-production-policy-for-isolated-probe"))
    _, bound, original_broker = gateway
    plan = prepare(conn, original_broker).plan
    original = Command(
        identity=CommandIdentity(bound.identity, plan.plan_id, "1", 0),
        instrument=BrokerInstrument("1", "AAA"), side=Side.BUY,
        quantity=Decimal(10))
    conn.commit()
    dsn = conn.info.dsn
    evidence_path = tmp_path / "accepted-broker-state.pickle"
    sender = multiprocessing.get_context("fork").Process(
        target=_send_and_die,
        args=(dsn, original_broker, original, evidence_path, boundary))
    sender.start()
    try:
        sender.join(timeout=20)
        assert not sender.is_alive(), "sender failed to reach its death boundary"
        assert sender.exitcode == -signal.SIGKILL
    finally:
        if sender.is_alive():
            sender.kill()
            sender.join(timeout=5)

    with feed_store.connect(dsn) as reopened:
        retained = journal.load_commands(reopened, bound.identity)
        assert len(retained) == 1, "durable command must precede broker acceptance"
        expected = (CommandState.SEND_PENDING
                    if boundary == "accepted_before_ack_commit"
                    else CommandState.ACKNOWLEDGED)
        assert retained[0].state is expected
        assert retained[0].identity == original.identity
        assert retained[0].quantity == Decimal(10)

    # This is a newly constructed broker object, not the sender's memory.
    broker = SimulatedBroker(account=original_broker.account,
                             equity=Decimal(250000), cash=Decimal(250000))
    # The file contains only this test's trusted, locally generated fixture.
    for name, value in pickle.loads(evidence_path.read_bytes()).items():
        setattr(broker, name, value)
    assert len(broker._orders) == 1
    assert broker.cash == Decimal(250000)
    if advanced:
        refresh(conn, operational_source, monkeypatch)
        later = rolling_runtime.advance(
            conn, through="2026-09-15", observation_id=OBS, starting_cash=100000)
        assert later.session > str(plan.decision_session)
        conn.rollback()

    class RecoveryClock(datetime):
        @classmethod
        def now(cls, tz=None):
            day = 16 if advanced else 15
            return datetime(2026, 9, day, 14, tzinfo=timezone.utc).astimezone(tz)

    broker.now = RecoveryClock.now(timezone.utc)
    cycle = SimpleNamespace(
        control_generation=1, plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(), decision_session=plan.decision_session,
        effective_session=plan.effective_session)
    grant = AutomationExecutionGrant(
        "RECOVER", "compound-death", 1, "test", 1, "paper-fixture",
        bound.takeover_epoch, "CONTROLLER", 2, "a" * 64)
    # Same explicit authority boundaries as test_historical_cycle_recovery.
    monkeypatch.setattr(recovery, "_validate_automation_grant", lambda *_: (None, cycle))
    monkeypatch.setattr(recovery, "_guard_broker", lambda **kw: kw["broker"])
    monkeypatch.setattr(recovery, "datetime", RecoveryClock)

    def recover(connection):
        return asyncio.run(recovery.recover_automated_paper_cycle(
            conn=connection, broker=broker, base_url=DEFAULT_BASE_URL,
            grant=grant, automation_config_sha256="b" * 64,
            dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000))

    exact_lookup = broker.find_by_client_key
    observation = broker.observe_with_terminal_recovery

    async def absent_key(key):
        return replace(await exact_lookup(key), order=None)

    async def absent_observation(**kwargs):
        return replace(await observation(**kwargs), orders=(), positions=())

    with monkeypatch.context() as hidden:
        hidden.setattr(broker, "find_by_client_key", absent_key)
        hidden.setattr(broker, "observe_with_terminal_recovery", absent_observation)
        for _ in range(3):
            with feed_store.connect(dsn) as reopened:
                with pytest.raises(PaperRetryableRefused, match="RECONCILING"):
                    recover(reopened)
                durable = journal.load_commands(reopened, bound.identity)
                assert len(durable) == 1
                assert durable[0].state is CommandState.UNKNOWN
                assert durable[0].client_key == original.client_key
        # An independently specified share target reaches the public executor's
        # recovery barrier without borrowing the old plan's opening-price proof.
        # This is execution-contract input, not a substitute strategy decision.
        successor = ExecutionPlan(
            plan_id="successor-contract-probe", decision_session=plan.decision_session,
            effective_session=plan.effective_session, target_exposure=Decimal(1),
            target_basket={"1": Decimal(20)}, data_version=plan.data_version)
        with feed_store.connect(dsn) as reopened:
            executor.adopt_plan(reopened, successor)
            blocked = asyncio.run(executor.execute_session(
                conn=reopened, broker=broker, deployment=bound.identity,
                plan=successor, instruments={"1": original.instrument},
                today=successor.effective_session))
            assert blocked.runtime_state is RuntimeState.RECONCILING
            assert blocked.submitted == ()
            assert sum(call.startswith("submit:") for call in broker.calls) == 1

    # Independent economic oracle: stipulated ten shares at $100, once only.
    # A successor control generation may observe the predecessor's obligation,
    # but must not reinterpret its superseded target as new trading authority.
    grant = replace(grant, control_generation=2)
    broker.fill(original.client_key)
    assert broker.cash == Decimal(249000)
    for _ in range(2):
        with feed_store.connect(dsn) as reopened:
            result = recover(reopened)
            assert result.runtime_state is RuntimeState.RUNNING and result.clean
            assert result.expected == result.observed == {"1": Decimal(10)}
            durable = journal.load_commands(reopened, bound.identity)
            assert len(durable) == 1
            assert durable[0].identity == original.identity
            assert durable[0].client_key == original.client_key
            assert durable[0].state is CommandState.FILLED
            assert durable[0].quantity == durable[0].filled_quantity == Decimal(10)
            assert durable[0].filled_average_price == Decimal(100)
    assert broker.cash == Decimal(249000)
    assert len(broker._orders) == len(broker._fills) == 1
    assert sum(call.startswith("submit:") for call in broker.calls) == 1
    assert not any(call.startswith("cancel:") for call in broker.calls)


__all__ = ["conn", "pg", "gateway", "issuer_source", "published", "ready",
           "operational_source", "source"]
