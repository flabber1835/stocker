"""Planless recovery ages the durable command book through retained actions."""
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

import pytest

from sentinel import binding, schema
from sentinel.paper.targets import _action_lookup
from sentinel.execution import journal, reconcile
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.execution.simulator import SimulatedBroker
from tests.sentinel.test_rolling_history_retention import conn, pg, source, operational_source, aged


@pytest.mark.parametrize('security,symbol', [('1', 'AAA'), ('SENTINEL:BIL', 'BIL')])
@pytest.mark.parametrize('exited', [False, True])
def test_planless_retired_history_preserves_held_and_exited_units(conn, aged, security, symbol, exited):
    schema.ensure_schema(conn)
    bound = binding.bind(conn, deployment_id='planless', broker='sim', broker_account_id='SIM-ACCOUNT')
    old = datetime(2024,12,13,15,tzinfo=timezone.utc)
    now = datetime(2026,9,14,20,tzinfo=timezone.utc)
    instrument = BrokerInstrument(security, symbol)
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s', (old,))
    conn.commit()
    for key, side, quantity, stamp in ([('buy', Side.BUY, 10, old)] +
            ([('sell', Side.SELL, 60, now)] if exited else [])):
        command = Command(identity=CommandIdentity(bound.identity, key, security), instrument=instrument,
            side=side, quantity=Decimal(quantity), filled_quantity=Decimal(quantity),
            filled_average_price=Decimal(100), state=CommandState.FILLED, broker_order_id=key,
            created_at=stamp)
        journal.save_command(conn, command)
        conn.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s', (stamp, command.client_key))
        conn.commit()
    actions = _action_lookup(conn, None, now.date())
    assert actions(security) == 6
    broker = SimulatedBroker(now=now)
    if not exited:
        broker.seed_position(instrument, '60')
    result = asyncio.run(reconcile.reconcile(broker=broker, conn=conn, binding=bound,
                                             deployment=bound.identity, actions=actions))
    assert result.runtime_state is RuntimeState.RUNNING and result.clean
    assert not any(call.startswith(('submit:', 'cancel:')) for call in broker.calls)

__all__ = ['aged', 'conn', 'operational_source', 'pg', 'source']
