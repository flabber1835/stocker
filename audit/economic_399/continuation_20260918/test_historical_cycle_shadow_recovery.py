"""Audit-only real rolling/PAPER state with simulated broker transport.
Uses existing issuer/source/runtime/certificate fixtures; production source stays
unchanged. The gate under audit and SQL/rolling histories are real.
"""
from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from decimal import Decimal
from pathlib import Path
from sentinel import backup_runtime_authority

import pytest
from sentinel import rolling_runtime, dual_reconciliation, paper
from sentinel.execution import executor, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.guarded import AutomationExecutionGrant
from sentinel.execution.states import CommandState
from sentinel.paper import recovery
from sentinel.config import DEFAULT_BASE_URL
from tests.sentinel.test_rolling_paper_inputs import gateway, prepare
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh

@pytest.fixture(autouse=True)
def isolated_backup_policy(monkeypatch):
    monkeypatch.setattr(backup_runtime_authority,'POLICY_MARKER',Path('/audit/no-production-policy-for-isolated-economic-probe'))

@pytest.mark.parametrize('broker_fill', (False,True))
def test_new_shadow_close_blocks_old_cycle_before_order_reconciliation(
        conn,gateway,operational_source,monkeypatch,broker_fill):
    first_shadow,bound,broker=gateway
    plan=prepare(conn,broker).plan
    # A valid recorded economic intent under the original immutable plan.
    original=Command(identity=CommandIdentity(bound.identity,plan.plan_id,'1',0),
        instrument=BrokerInstrument('1','AAA'),side=Side.BUY,quantity=Decimal(10))
    sent=asyncio.run(executor._persist_and_send(conn,broker,original))
    assert sent.state is CommandState.ACKNOWLEDGED
    if broker_fill:broker.fill(sent.client_key)
    # The independent shadow worker can publish/attest the next close while
    # the execution worker has a pending recovery obligation.
    refresh(conn,operational_source,monkeypatch)
    later=rolling_runtime.advance(conn,through='2026-09-15',observation_id=OBS,starting_cash=100000)
    assert later.session>str(plan.decision_session)
    conn.rollback()
    assert journal.load_commands(conn,bound.identity)[0].state is CommandState.ACKNOWLEDGED
    conn.rollback()
    with pytest.raises(dual_reconciliation.DualReconciliationRefused,match='different decision closes'):
        dual_reconciliation.verified_shadow_intent(conn,decision_session=plan.decision_session,
            observation_id=OBS,starting_cash=100000)
    # Offline issuance/lease authorization are fixture boundaries. Keep actual
    # plan lookup, deterministic identity, shadow proof reader and recovery gate.
    cycle=SimpleNamespace(control_generation=1,plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(),decision_session=plan.decision_session,
        effective_session=plan.effective_session)
    grant=AutomationExecutionGrant('RECOVER','audit-historical-cycle',1,'test',1,
        'paper-fixture',bound.takeover_epoch,'CONTROLLER',2,'a'*64)
    monkeypatch.setattr(recovery,'_validate_automation_grant',lambda *_:(None,cycle))
    monkeypatch.setattr(recovery,'_guard_broker',lambda **kw:kw['broker'])
    before=len(broker.calls)
    with pytest.raises(paper.PaperActivationRefused,match='different decision closes'):
        asyncio.run(recovery.recover_automated_paper_cycle(conn=conn,broker=broker,
            base_url=DEFAULT_BASE_URL,grant=grant,automation_config_sha256='b'*64,
            dual_shadow_observation_id=OBS,dual_shadow_starting_cash=100000))
    attempts=broker.calls[before:]
    assert attempts==['account_snapshot']
    retained=journal.load_commands(conn,bound.identity)[0]
    assert retained.state is CommandState.ACKNOWLEDGED
    assert retained.filled_quantity==0
    actual=broker._by_key(sent.client_key)
    assert actual.filled==Decimal(10 if broker_fill else 0)
    assert sum(call.startswith('submit:') for call in broker.calls)==1

    # Control: the same durable obligation under a genuinely new generation
    # skips old target interpretation and reaches actual order reconciliation.
    broker.now=datetime.now(timezone.utc)
    current_grant=replace(grant,control_generation=2)
    before=len(broker.calls)
    recovered=asyncio.run(recovery.recover_automated_paper_cycle(conn=conn,broker=broker,
        base_url=DEFAULT_BASE_URL,grant=current_grant,automation_config_sha256='b'*64,
        dual_shadow_observation_id=OBS,dual_shadow_starting_cash=100000))
    assert recovered.observation is not None
    assert 'list_orders' in broker.calls[before:]
    settled=journal.load_commands(conn,bound.identity)[0]
    assert settled.state is (CommandState.FILLED if broker_fill else CommandState.ACKNOWLEDGED)
    assert settled.filled_quantity==Decimal(10 if broker_fill else 0)
    assert sum(call.startswith('submit:') for call in broker.calls)==1
