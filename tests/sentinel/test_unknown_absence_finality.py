"""Empty reads cannot finalize a timed-out request; a late fill remains learnable."""
from dataclasses import replace

from sentinel.execution import recovery, reconcile, journal
from sentinel.execution.simulator import SimulatedBroker, FaultKind
from sentinel.execution.states import CommandState, RuntimeState
from tests.sentinel.test_journal_and_reconcile import pg, conn, cmd, DEPLOY, run


def test_unknown_survives_absence_then_recovers_original_late_fill(conn):
    class Lagged(SimulatedBroker):
        hidden = True
        async def observe_with_terminal_recovery(self, **kwargs):
            found = await super().observe_with_terminal_recovery(**kwargs)
            return replace(found, orders=(), positions=()) if self.hidden else found
        async def find_by_client_key(self, key):
            found = await super().find_by_client_key(key)
            return replace(found, order=None) if self.hidden else found
    broker = Lagged()
    broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
    original = run(recovery.dispatch(broker, recovery.prepare_send(cmd())))
    assert original.state is CommandState.UNKNOWN
    journal.save_command(conn, original)
    for _ in range(3):
        result = run(reconcile.reconcile(broker=broker, conn=conn, binding=None, deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.RECONCILING
        assert journal.load_commands(conn, DEPLOY)[0].state is CommandState.UNKNOWN
    broker.fill(original.client_key)
    broker.hidden = False
    result = run(reconcile.reconcile(broker=broker, conn=conn, binding=None, deployment=DEPLOY))
    assert result.clean
    assert journal.load_commands(conn, DEPLOY)[0].state is CommandState.FILLED
    assert sum(call.startswith('submit:') for call in broker.calls) == 1

__all__ = ['conn', 'pg']
