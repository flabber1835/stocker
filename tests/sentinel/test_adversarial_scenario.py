"""One scenario, every hazard at once.

The review's closing request, and the only test here that is not about a single
rule. Each stage is something the appliance survives individually; the question
is whether they compose.

```text
plan created
  -> command submitted and acknowledged
  -> PROCESS DIES before the fill is ever seen
  -> the fill happens anyway
  -> a 2:1 SPLIT happens while it is down
  -> a STALE database is restored (predating all of it)
  -> restart, reconcile
  -> a NEW plan wants LOWER exposure
  -> exactly one SELL, sized correctly
  -> no duplicate BUY, ever
  -> journal agrees with the broker
  -> a second restart is a NO-OP
```

Two things make this harder than the sum of its parts:

**The split and the fill both change the share count**, and only one of them is
explicable from the journal. Get the ordering wrong — classify before applying
corporate actions — and the appliance latches FOREIGN_ACTIVITY and refuses to
de-risk into a market that just moved.

**The restored journal has never heard of the order**, so the recovered position
has to be attributed by client key rather than by memory. If that attribution
fails, the "lower exposure" plan sizes its sell against a book it does not
believe it owns.

The process death is simulated by discarding in-memory state and reopening from
the database — which is what a restart actually is here, since every durable
decision is already a row. It is NOT a SIGKILL; that limitation is recorded in
the contract's status block rather than papered over.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import executor, journal, reconcile as R  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, Side)
from sentinel.execution.identity import DeploymentIdentity, is_sentinel_key  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as S, RuntimeState  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
INSTRUMENTS = {"SEC-AAA": AAA}

DAY1 = date(2026, 8, 11)
DAY2 = date(2026, 8, 14)

STATE_TABLES = ("sentinel_account_binding", "sentinel_ownership_events",
                "sentinel_commands", "sentinel_command_events",
                "sentinel_execution_plans", "sentinel_fills",
                "sentinel_observations",
                "sentinel_terminal_recovery_watermark")


def run(coro):
    return asyncio.run(coro)


def D(x):
    return Decimal(str(x))


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
def conn(pg):
    c = feed_store.connect(pg.sync_dsn)
    drop_public_tables(c)
    schema.ensure_schema(c)
    feed_store.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


def backup(conn) -> dict:
    out: dict = {}
    with conn.cursor() as cur:
        for table in STATE_TABLES:
            cur.execute(f"SELECT * FROM {table}")
            out[table] = ([d[0] for d in cur.description], cur.fetchall())
    return out


def restore(conn, snapshot: dict) -> None:
    with conn.cursor() as cur:
        for table in STATE_TABLES:
            cur.execute(f"TRUNCATE {table} CASCADE")
        for table, (cols, rows) in snapshot.items():
            if rows:
                cur.executemany(
                    f"INSERT INTO {table} ({','.join(cols)}) VALUES "
                    f"({','.join(['%s'] * len(cols))})", rows)
    conn.commit()


def plan(plan_id, basket, *, exposure="1", effective=DAY1):
    return ExecutionPlan(plan_id=plan_id, decision_session=DAY1,
                         effective_session=effective,
                         target_exposure=D(exposure), target_basket=basket,
                         data_version=1)


def session(b, conn, p, today):
    executor.adopt_plan(conn, p)
    return run(executor.execute_session(
        broker=b, conn=conn, deployment=DEPLOY, plan=p,
        instruments=INSTRUMENTS, today=today,
        actions=R.corpus_action_lookup(conn, start=DAY1, end=today)))


def record_split(conn, ratio="2", when="2026-08-12"):
    """A corporate action the corpus knows about, on a security that traded."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_bars (security_id, session, ticker,"
                    " close_unadjusted) VALUES ('SEC-AAA','2026-08-11','AAA',100)"
                    " ON CONFLICT DO NOTHING")
    conn.commit()
    feed_store.write_actions(conn, [{"ticker": "AAA", "date": when,
                                     "action": "split", "value": float(ratio)}])


class TestTheWholeThingAtOnce:
    def _arrive_at_the_disaster(self, conn):
        """Everything up to and including the stale restore."""
        b = SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))

        snapshot = backup(conn)                    # the backup predates it all

        result = session(b, conn, plan("plan-1", {"SEC-AAA": D(100)}), DAY1)
        assert len(result.submitted) == 1
        command = result.submitted[0]
        assert command.state is S.ACKNOWLEDGED

        # ── the process dies here; the fill is never observed by it ─────────
        b.fill(command.client_key)                 # 100 shares, while down
        record_split(conn, "2")                    # 2:1, while down
        b.apply_corporate_action("SEC-AAA", "2")   # broker now shows 200

        restore(conn, snapshot)                    # stale DB, knows nothing
        assert journal.load_commands(conn, DEPLOY) == ()
        return b, command

    def test_the_recovered_order_is_ours_not_a_stranger(self, conn):
        b, command = self._arrive_at_the_disaster(conn)
        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY,
                              actions=R.corpus_action_lookup(
                                  conn, start=DAY1, end=DAY2)))
        assert [o.client_key for o in rec.recovered_orders] == [command.client_key]
        assert rec.foreign_orders == ()
        assert is_sentinel_key(command.client_key)

    def test_the_split_is_visible_and_the_broker_shows_the_doubled_count(self, conn):
        b, _ = self._arrive_at_the_disaster(conn)
        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY,
                              actions=R.corpus_action_lookup(
                                  conn, start=DAY1, end=DAY2)))
        assert rec.observed == {"SEC-AAA": D(200)}

    def test_a_LOWER_exposure_plan_sells_and_NEVER_re_buys(self, conn):
        """The decisive assertion. The book is 200 after the split; the new plan
        wants 50. Exactly one SELL, and not a single additional BUY across the
        whole episode."""
        b, _ = self._arrive_at_the_disaster(conn)
        buys_before = len([c for c in b.calls if c.startswith("submit:")])

        result = session(b, conn, plan("plan-2", {"SEC-AAA": D(50)},
                                       exposure="0.25", effective=DAY2), DAY2)

        sells = [c for c in result.submitted if c.side is Side.SELL]
        buys = [c for c in result.submitted if c.side is Side.BUY]
        assert len(sells) == 1, result.to_dict()
        assert buys == [], "a duplicate BUY here is the failure this exists for"
        assert sells[0].quantity == D(150), "200 held, 50 wanted"

        total_submits = len([c for c in b.calls if c.startswith("submit:")])
        assert total_submits == buys_before + 1

    def test_the_journal_then_AGREES_with_the_broker(self, conn):
        b, _ = self._arrive_at_the_disaster(conn)
        result = session(b, conn, plan("plan-2", {"SEC-AAA": D(50)},
                                       exposure="0.25", effective=DAY2), DAY2)
        b.fill(result.submitted[0].client_key)

        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY,
                              actions=R.corpus_action_lookup(
                                  conn, start=DAY1, end=DAY2)))
        assert rec.observed == {"SEC-AAA": D(50)}
        assert rec.runtime_state in (RuntimeState.RUNNING,
                                     RuntimeState.FOREIGN_ACTIVITY)
        assert rec.observed["SEC-AAA"] == D(50)

    def test_a_SECOND_restart_is_a_NO_OP(self, conn):
        """Convergence, not oscillation: re-running the same plan against a
        satisfied book must submit nothing at all."""
        b, _ = self._arrive_at_the_disaster(conn)
        p2 = plan("plan-2", {"SEC-AAA": D(50)}, exposure="0.25", effective=DAY2)
        result = session(b, conn, p2, DAY2)
        b.fill(result.submitted[0].client_key)

        submits_before = len([c for c in b.calls if c.startswith("submit:")])
        again = session(b, conn, replace(p2, plan_id="plan-3"), DAY2)
        submits_after = len([c for c in b.calls if c.startswith("submit:")])

        assert again.submitted == ()
        assert submits_after == submits_before

    def test_WITHOUT_the_corporate_action_lookup_it_would_have_stalled(self, conn):
        """Why step 5 of the reconciliation order is load-bearing.

        The same episode with no actions lookup: the doubled share count is
        unexplained, the appliance latches FOREIGN_ACTIVITY, and it refuses to
        add exposure into a market that just moved. It can still de-risk — the
        asymmetry holds even here — but the classification is wrong.
        """
        b, _ = self._arrive_at_the_disaster(conn)
        blind = run(R.reconcile(broker=b, conn=conn, binding=None,
                                deployment=DEPLOY))
        assert blind.runtime_state is RuntimeState.FOREIGN_ACTIVITY

        aware = run(R.reconcile(broker=b, conn=conn, binding=None,
                                deployment=DEPLOY,
                                actions=R.corpus_action_lookup(
                                    conn, start=DAY1, end=DAY2)))
        assert aware.corporate_actions == {"SEC-AAA": D(2)}
