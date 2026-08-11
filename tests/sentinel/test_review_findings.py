"""Falsifiers for the seven defects found in external review of 17de309.

Each class below pins ONE finding. They live together rather than being scattered
into the suites they touch because they share a property worth keeping visible:
every one of them was green before, and green for the same reason — the contract
abstractions were tested thoroughly while the BOUNDARIES between them were not.

    R1  `stopped` mapped to REJECTED. Alpaca defines it as a GUARANTEED trade
        that has not happened yet, so terminal-and-free let a second command in
        alongside a fill that was certain to land.
    R2  reconcile only synced UNKNOWN commands, so a normal asynchronous fill
        made Sentinel's own position read as FOREIGN_ACTIVITY — the appliance
        could make its first trade and then quarantine itself over it.
    R3  the executor took `plan` and `desired` independently, so a client key
        could assert "plan P, security S" while executing a quantity P never
        said. The upsert then never rechecked it.
    R4  `compute_delta` accepted a negative desired quantity and produced an
        opening SHORT. Alpaca supports shorting and would not refuse it for us.
    R5  the writer lock was documented as the caller's duty, and the only public
        entry point did not take it.
    R6  the corporate-action join resolved a ticker to EVERY security that ever
        held it.
    R7  "binding and events in ONE transaction" was written in a docstring while
        both writers committed separately.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import (  # noqa: E402
    commands as C, executor, journal, reconcile as R, recovery)
from sentinel.execution import alpaca as ALP  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerFill, BrokerInstrument, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.execution.states import (  # noqa: E402
    CommandState as S, RuntimeState, blocks_overlapping)
from sentinel.feed import store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
TODAY = date(2026, 8, 11)


def run(coro):
    return asyncio.run(coro)


def D(x):
    return Decimal(str(x))


def plan(plan_id="plan-1", basket=None, exposure="1", effective=TODAY):
    return ExecutionPlan(plan_id=plan_id, decision_session=date(2026, 8, 10),
                         effective_session=effective,
                         target_exposure=D(exposure),
                         target_basket=basket or {}, data_version=1)


# ===========================================================================
# R1 — a status that can still trade must never be terminal
# ===========================================================================

class TestR1StoppedIsNotARejection:
    def test_stopped_does_NOT_free_the_security(self):
        """Alpaca: `stopped` means the trade is GUARANTEED, usually at a stated
        price or better, but has not yet occurred. Mapped to REJECTED it was
        terminal, which released the security for a second command — and the
        guaranteed trade then landed alongside it."""
        state = ALP.map_status("stopped")
        assert state is not S.REJECTED
        assert blocks_overlapping(state), (
            "a certain, pending fill must block an overlapping command")

    @pytest.mark.parametrize("raw", [
        "stopped",            # guaranteed trade, not yet occurred
        "calculated",         # complete for the day, settlement pending
        "done_for_day",       # no more execution TODAY; remainder still open
        "pending_replace",    # externally altered, replacement may fill
        "replaced",           # ditto
        "new", "accepted", "pending_new", "accepted_for_bidding",
        "held", "suspended", "partially_filled", "pending_cancel",
    ])
    def test_every_status_that_can_still_trade_BLOCKS(self, raw):
        """The classifying question is not 'does this sound finished?' but
        'can a trade still occur?'. A wrongly-terminal status doubles a
        position; a wrongly-in-flight one stalls one security visibly. Those
        costs are not symmetric, so neither is the default."""
        assert blocks_overlapping(ALP.map_status(raw)), raw

    @pytest.mark.parametrize("raw", ["filled", "canceled", "expired", "rejected"])
    def test_only_genuinely_settled_statuses_are_terminal(self, raw):
        assert not blocks_overlapping(ALP.map_status(raw)), raw

    def test_external_replacement_is_flagged_as_anomalous(self):
        """Sentinel never issues a replace, so seeing one means our order was
        altered from outside. It blocks like any working order AND is surfaced —
        a silent block would look like an ordinary slow fill."""
        assert ALP.is_anomalous_status("replaced")
        assert not ALP.is_anomalous_status("new")


# ===========================================================================
# Database-backed fixtures
# ===========================================================================

STATE_TABLES = ("sentinel_account_binding", "sentinel_ownership_events",
                "sentinel_commands", "sentinel_command_events",
                "sentinel_execution_plans", "sentinel_fills",
                "sentinel_observations")


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
    with c.cursor() as cur:
        for t in STATE_TABLES + ("sentinel_bars", "sentinel_actions"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    feed_store.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


def broker():
    return SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))


def go(b, conn, basket, *, p=None, today=TODAY):
    return run(executor.execute_session(
        broker=b, conn=conn, deployment=DEPLOY,
        plan=replace(p or plan(), target_basket=basket),
        instruments={"SEC-AAA": AAA}, today=today))


# ===========================================================================
# R2 — a normal asynchronous fill must not read as foreign activity
# ===========================================================================

class TestR2FillsAreSynchronised:
    def test_an_ACKNOWLEDGED_command_that_FILLS_is_not_foreign_activity(self, conn):
        """THE QUARANTINE BUG. A market order need not come back filled;
        `new`/`accepted` followed by a fill is ordinary. Reconciling only the
        UNKNOWNs left the journal at filled=0 while the broker held the
        position, so the appliance's OWN trade was unexplained."""
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        assert result.submitted[0].state is S.ACKNOWLEDGED

        b.fill(result.submitted[0].client_key)               # async, later

        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY))
        assert rec.runtime_state is RuntimeState.RUNNING, (
            "Sentinel's own filled order must explain its own position")
        assert rec.foreign_positions == ()
        assert rec.expected == {"SEC-AAA": D(10)}

    def test_the_sync_is_PERSISTED_not_only_in_memory(self, conn):
        """An in-memory sync would be forgotten by the next restart and the
        accusation would come back."""
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        b.fill(result.submitted[0].client_key)
        run(R.reconcile(broker=b, conn=conn, binding=None, deployment=DEPLOY))

        stored = journal.load_commands(conn, DEPLOY)[0]
        assert stored.state is S.FILLED
        assert stored.filled_quantity == D(10)

    def test_a_PARTIAL_fill_is_synced_and_still_blocks(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        b.fill(result.submitted[0].client_key, "4")

        run(R.reconcile(broker=b, conn=conn, binding=None, deployment=DEPLOY))
        stored = journal.load_commands(conn, DEPLOY)[0]
        assert stored.state is S.PARTIALLY_FILLED
        assert stored.filled_quantity == D(4)
        assert recovery.blocked_securities([stored]) == {"SEC-AAA"}

    def test_a_growing_PARTIAL_is_persisted_even_though_the_state_is_unchanged(
            self, conn):
        """The persist condition has to watch the quantity, not only the state —
        two successive partials are both progress."""
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        key = result.submitted[0].client_key

        b.fill(key, "3")
        run(R.reconcile(broker=b, conn=conn, binding=None, deployment=DEPLOY))
        b.fill(key, "3")
        run(R.reconcile(broker=b, conn=conn, binding=None, deployment=DEPLOY))

        assert journal.load_commands(conn, DEPLOY)[0].filled_quantity == D(6)

    def test_the_book_converges_and_the_next_session_does_nothing(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        b.fill(result.submitted[0].client_key)

        again = go(b, conn, {"SEC-AAA": D(10)}, p=plan("plan-2"))
        assert again.runtime_state is RuntimeState.RUNNING
        assert again.submitted == () and not again.refused


# ===========================================================================
# R3 — the key must determine the economics
# ===========================================================================

class TestR3EconomicsAreBoundToThePlan:
    def test_the_executor_has_no_independent_desired_argument(self):
        """Removing the parameter rather than validating it: a check can be
        skipped by a future call site, an absent parameter cannot."""
        import inspect
        params = inspect.signature(executor.execute_session).parameters
        assert "desired" not in params
        assert "plan" in params

    def test_the_quantity_comes_from_the_PLAN(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(7)})
        assert result.submitted[0].quantity == D(7)

    def test_a_key_rebuilt_with_DIFFERENT_economics_is_REFUSED(self, conn):
        """The upsert deliberately does not rewrite quantity, so without this
        the database could hold X while the wire carried Y under one identity —
        and 'deterministic key -> deterministic side effect' would be false."""
        identity = CommandIdentity(deployment=DEPLOY, plan_id="plan-1",
                                   security_id="SEC-AAA")
        journal.save_command(conn, C.Command(
            identity=identity, instrument=AAA, side=Side.BUY, quantity=D(100)))

        with pytest.raises(journal.CommandEconomicsChanged, match="quantity"):
            journal.save_command(conn, C.Command(
                identity=identity, instrument=AAA, side=Side.BUY,
                quantity=D(200)))

    def test_a_flipped_SIDE_under_one_key_is_refused_too(self, conn):
        identity = CommandIdentity(deployment=DEPLOY, plan_id="plan-1",
                                   security_id="SEC-AAA")
        journal.save_command(conn, C.Command(
            identity=identity, instrument=AAA, side=Side.BUY, quantity=D(10)))
        with pytest.raises(journal.CommandEconomicsChanged, match="side"):
            journal.save_command(conn, C.Command(
                identity=identity, instrument=AAA, side=Side.SELL,
                quantity=D(10)))

    def test_an_IDENTICAL_rebuild_is_fine_because_restarts_do_that(self, conn):
        identity = CommandIdentity(deployment=DEPLOY, plan_id="plan-1",
                                   security_id="SEC-AAA")
        cmd = C.Command(identity=identity, instrument=AAA, side=Side.BUY,
                        quantity=D(10))
        journal.save_command(conn, cmd)
        journal.save_command(conn, cmd.transition(S.SEND_PENDING),
                             previous=S.PLANNED)
        assert journal.load_commands(conn, DEPLOY)[0].state is S.SEND_PENDING

    def test_new_intent_needs_a_NEW_identity(self, conn):
        """`superseding()` is the sanctioned route, and it exists so the old
        promise — which the broker may already have acted on — stays intact."""
        identity = CommandIdentity(deployment=DEPLOY, plan_id="plan-1",
                                   security_id="SEC-AAA")
        journal.save_command(conn, C.Command(
            identity=identity, instrument=AAA, side=Side.BUY, quantity=D(100),
            state=S.FILLED, filled_quantity=D(100)))
        journal.save_command(conn, C.Command(
            identity=identity.superseding(), instrument=AAA, side=Side.BUY,
            quantity=D(200)))
        assert len(journal.load_commands(conn, DEPLOY)) == 2


# ===========================================================================
# R4 — the long-only envelope
# ===========================================================================

class TestR4RiskEnvelope:
    def test_a_NEGATIVE_target_quantity_is_refused(self, conn):
        """`compute_delta` turns desired −100 against a flat book into SELL 100,
        which is an OPENING SHORT. Alpaca supports shorting and runs its own
        buying-power check, so the broker will not refuse it on our behalf."""
        b = broker()
        with pytest.raises(executor.RiskEnvelopeViolation, match="SHORT"):
            go(b, conn, {"SEC-AAA": D(-100)})
        assert not [c for c in b.calls if c.startswith("submit:")]

    @pytest.mark.parametrize("exposure", ["-0.1", "1.5"])
    def test_exposure_outside_0_1_is_refused(self, conn, exposure):
        b = broker()
        with pytest.raises(executor.RiskEnvelopeViolation, match=r"\[0, 1\]"):
            go(b, conn, {"SEC-AAA": D(10)},
               p=plan(exposure=exposure))

    def test_the_gate_runs_BEFORE_the_broker_is_touched(self, conn):
        b = broker()
        with pytest.raises(executor.RiskEnvelopeViolation):
            go(b, conn, {"SEC-AAA": D(-1)})
        assert b.calls == [], "not even an observation"

    def test_a_normal_long_plan_passes(self, conn):
        assert go(broker(), conn, {"SEC-AAA": D(10)}).submitted


# ===========================================================================
# R5 — the writer lock is structural, not documentary
# ===========================================================================

class TestR5WriterLockIsTakenInside:
    def test_execute_session_holds_the_lock(self, conn, pg):
        """`reconcile` says the caller must hold it across the session. A
        prerequisite stated in a docstring is one a future controller forgets."""
        other = feed_store.connect(pg.sync_dsn)
        held = {}

        class Watcher(SimulatedBroker):
            async def observe(self):
                with other.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(%s)",
                                (journal.WRITER_LOCK_KEY,))
                    got = bool(cur.fetchone()[0])
                held["free"] = got
                if got:
                    with other.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)",
                                    (journal.WRITER_LOCK_KEY,))
                return await super().observe()

        try:
            go(Watcher(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT")),
               conn, {"SEC-AAA": D(10)})
        finally:
            other.close()
        assert held["free"] is False, (
            "the lock must already be held while the session runs")

    def test_a_concurrent_session_is_REFUSED_not_silently_interleaved(self, conn, pg):
        other = feed_store.connect(pg.sync_dsn)
        try:
            with journal.writer_lock(other):
                with pytest.raises(journal.WriterLockUnavailable):
                    go(broker(), conn, {"SEC-AAA": D(10)})
        finally:
            other.close()

    def test_the_lock_is_released_when_the_session_ends(self, conn, pg):
        go(broker(), conn, {"SEC-AAA": D(10)})
        other = feed_store.connect(pg.sync_dsn)
        try:
            with journal.writer_lock(other):
                pass
        finally:
            other.close()


# ===========================================================================
# R7 — transactionality, and fill identity
# ===========================================================================

class TestR7Transactionality:
    def test_the_ownership_store_can_DEFER_its_commit(self, conn):
        """Committing inside `append` made a single-transaction handover
        impossible, which quietly falsified `migrate_account`'s own claim."""
        from sentinel.ownership import OwnershipState as OS
        from sentinel.store import PostgresOwnershipStore, record

        deferred = PostgresOwnershipStore(conn, autocommit=False)
        record(deferred, OS.FLAT_CONFIRMED, reason="deferred")
        conn.rollback()
        assert PostgresOwnershipStore(conn).events() == [], (
            "an uncommitted event must not survive a rollback")

    def test_binding_and_events_ROLL_BACK_TOGETHER(self, conn):
        """The property `migrate_account` claims. Both writers now defer, so a
        crash between them cannot leave SENTINEL_OWNERSHIP_ESTABLISHED with no
        binding row."""
        from sentinel.ownership import OwnershipState as OS
        from sentinel.store import PostgresOwnershipStore, record

        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_account_binding")
        conn.commit()

        deferred = PostgresOwnershipStore(conn, autocommit=False)
        record(deferred, OS.SENTINEL_OWNERSHIP_ESTABLISHED, reason="x")
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="SIM-ACCOUNT", commit=False)
        conn.rollback()

        assert B.load(conn) is None
        assert PostgresOwnershipStore(conn).events() == []


class TestRecoveredOrderAdoption:
    """Adoption is what makes recovery converge — and it has to fail safely."""

    def test_a_recovered_order_is_written_into_the_journal(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        key = result.submitted[0].client_key

        with conn.cursor() as cur:                 # the stale restore, minimally
            cur.execute("DELETE FROM sentinel_commands")
        conn.commit()

        run(R.reconcile(broker=b, conn=conn, binding=None, deployment=DEPLOY))
        stored = journal.load_commands(conn, DEPLOY)
        assert [c.client_key for c in stored] == [key]
        assert stored[0].is_recovered
        assert stored[0].identity.plan_id == journal.RECOVERED_PLAN_ID, (
            "a real plan id would be a lie — the plan is what the restore lost")

    def test_a_CONFLICTING_recovered_order_does_not_poison_the_transaction(
            self, conn):
        """`ON CONFLICT (client_key)` covers a repeat adoption; it does NOT
        cover the partial unique index on in-flight security_id. Two live
        Sentinel-keyed orders for one security is a condition for a human, and a
        raised constraint violation mid-reconcile would fail the rest of the
        pass with an error about the wrong thing."""
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})   # broker order #1, in journal

        # A SECOND Sentinel-keyed working order for the same security, which the
        # journal has never seen. Only reachable if something outside this
        # appliance placed it.
        from sentinel.execution.simulator import _Resting
        b._orders["sim-rogue"] = _Resting(
            broker_order_id="sim-rogue",
            client_key="sntl-0000000000000000rogue",
            instrument=AAA, side=Side.BUY, quantity=D(5))

        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY))

        # The reconciliation COMPLETED rather than raising, and the original
        # command survived intact.
        assert rec.observation is not None
        assert result.submitted[0].client_key in {
            c.client_key for c in journal.load_commands(conn, DEPLOY)}
        # And the connection is still usable — the savepoint did its job.
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1


class TestR7FillIdentity:
    def _fill(self, qty="4", price="100", oid="o-1"):
        return BrokerFill(client_key="sntl-k", broker_order_id=oid,
                          quantity=D(qty), price=D(price),
                          filled_at=datetime(2026, 8, 11, tzinfo=timezone.utc))

    def test_the_same_fill_re_read_is_not_double_counted(self, conn):
        assert journal.record_fills(conn, [self._fill()]) == 1
        assert journal.record_fills(conn, [self._fill()]) == 0

    def test_identity_does_NOT_depend_on_position_in_the_response(self, conn):
        """The old key was the fill's ordinal in whatever list came back, so a
        query over a different window gave the same fill a different key — and
        could give a DIFFERENT fill one already used, which ON CONFLICT DO
        NOTHING then silently discarded."""
        a, b = self._fill(qty="4"), self._fill(qty="6")
        assert journal.record_fills(conn, [a, b]) == 2
        assert journal.record_fills(conn, [b, a]) == 0, "order must not matter"

    def test_two_genuinely_different_fills_both_land(self, conn):
        assert journal.record_fills(
            conn, [self._fill(qty="4"), self._fill(qty="6")]) == 2
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_fills")
            assert cur.fetchone()[0] == 2
