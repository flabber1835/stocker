"""The stale-plan check must be true FOR the session, not before it.

## The interleaving

`execute_session` proved the plan was current and then took the writer lock.
Between those two statements another writer can do its whole job:

```text
executor                          catch-up
--------                          --------
assert plan A is current   ok
                                  acquire writer lock
                                  create plan B, supersede A
                                  release
acquire writer lock
execute A                         <- the database knew. Nobody asked again
```

The database was right the entire time. Execution simply never asked a second
time, so an obsolete intention could still reach the broker — which is the
exact failure `_assert_current_plan` was written to prevent, arrived at through
timing rather than through a caller holding a stale object.

`docs/sentinel-execution-contract.md` §13.1a says historical sessions advance
deterministic state and historical execution intent is never replayed. A check
that is only true at an instant before the lock does not make that a property
of the system; it makes it a property of the schedule.

## Why it is deterministic here rather than threaded

`journal.writer_lock` uses `pg_try_advisory_lock`, so a real second writer
holding the lock makes the executor REFUSE rather than wait — there is no
window to race into. The window is between the pre-lock assert and acquisition,
and a thread would have to hit it by luck.

So the supersession is injected AT that moment: `writer_lock` is wrapped so a
second connection supersedes the plan as the lock is being taken. That is
faithful — it is what a concurrent catch-up does — and it fires every run
instead of one in a thousand.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import executor as E  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument  # noqa: E402
from sentinel.execution.identity import DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

D = Decimal
TODAY = dt.date(2026, 8, 11)
DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA")
INSTRUMENTS = {"SEC-AAA": AAA}


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conns(pg):
    """TWO real connections. One connection could not express the race: the
    advisory lock is re-entrant per session, so a single connection would
    happily supersede while holding its own lock."""
    a = feed_store.connect(pg.sync_dsn)
    with a.cursor() as cur:
        for t in ("sentinel_account_binding", "sentinel_ownership_events",
                  "sentinel_commands", "sentinel_command_events",
                  "sentinel_execution_plans", "sentinel_fills",
                  "sentinel_observations"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    a.commit()
    schema.ensure_schema(a)
    B.bind(a, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    b = feed_store.connect(pg.sync_dsn)
    yield a, b
    a.close()
    b.close()


def a_plan(pid, basket):
    return ExecutionPlan(plan_id=pid, decision_session=TODAY,
                         effective_session=TODAY, target_exposure=D(1),
                         target_basket={k: D(v) for k, v in basket.items()},
                         data_version=1)


class TestSupersessionDuringLockAcquisition:
    def test_a_plan_superseded_while_the_lock_is_taken_SUBMITS_NOTHING(
            self, conns, monkeypatch):
        """The falsifier. Zero broker submissions is the whole assertion —
        `StalePlanRefused` is the mechanism, but an executor that raised AFTER
        sending an order would satisfy the exception and fail the account."""
        exec_conn, other = conns
        plan_a = a_plan("plan-A", {"SEC-AAA": 100})
        journal.save_plan(exec_conn, plan_a)
        exec_conn.commit()

        sim = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))

        real_writer_lock = journal.writer_lock
        fired = []

        import contextlib

        @contextlib.contextmanager
        def racing_writer_lock(conn):
            # THE MOMENT THAT MATTERS. A concurrent catch-up creates its own
            # plan and supersedes ours, on its OWN connection, exactly while we
            # are taking the lock. With the check above the `with`, it has
            # already passed and this is invisible.
            if not fired:
                fired.append(True)
                plan_b = a_plan("plan-B", {"SEC-AAA": 0})
                journal.save_plan(other, plan_b)
                journal.supersede_all_but(other, plan_b.plan_id)
                other.commit()
            with real_writer_lock(conn):
                yield

        monkeypatch.setattr(journal, "writer_lock", racing_writer_lock)

        with pytest.raises(E.StalePlanRefused):
            asyncio.run(E.execute_session(
                broker=sim, conn=exec_conn, deployment=DEPLOY, plan=plan_a,
                instruments=INSTRUMENTS, today=TODAY, actions=None,
                min_increment=D(1)))

        assert fired, ("the supersession never ran, so this test proved "
                       "nothing about the race")
        assert not sim._orders, (
            f"an obsolete plan reached the broker: {list(sim._orders)}")

    def test_the_check_is_INSIDE_the_lock_in_the_source(self):
        """Belt and braces on the ORDERING itself.

        The behavioural test above depends on a monkeypatched context manager;
        a refactor that inlined the lock would make it vacuous while leaving
        the race in place. This reads the source and is immune to that."""
        import inspect
        src = inspect.getsource(E.execute_session)
        body = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        lock_at = body.index("with journal.writer_lock(conn)")
        assert "_assert_current_plan" in body
        assert body.index("_assert_current_plan(conn, plan)") > lock_at, (
            "the currency check runs BEFORE the writer lock is held, so "
            "another writer can supersede the plan in between and the "
            "executor will never ask again")

    def test_an_UNRACED_current_plan_still_executes(self, conns):
        """The guard must not simply refuse everything. Without this, deleting
        the executor's body would pass the falsifier above."""
        exec_conn, _ = conns
        plan = a_plan("plan-solo", {"SEC-AAA": 100})
        journal.save_plan(exec_conn, plan)
        exec_conn.commit()
        sim = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        res = asyncio.run(E.execute_session(
            broker=sim, conn=exec_conn, deployment=DEPLOY, plan=plan,
            instruments=INSTRUMENTS, today=TODAY, actions=None,
            min_increment=D(1)))
        assert res is not None
        assert sim._orders, "a current plan submitted nothing"
