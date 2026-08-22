"""Durable command state, and reconciliation after a gap.

The two properties under test are the ones a restart depends on:

    a command's row is written BEFORE the network call, so recovery can find it;
    corporate actions are applied BEFORE anything is called foreign activity.

The second is easy to leave out and invisible when you do — the arithmetic still
works, it just accuses the market of trading the account. In a 25-name book that
would latch a re-risking block after most outages longer than a day.

Contract: docs/sentinel-execution-contract.md §6, §10.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
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
from sentinel.execution import (  # noqa: E402
    journal,
    recovery,
    reconcile as R,
    target_reprojection,
)
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, BrokerObservation, BrokerOrder,
    Completeness, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import FaultKind as F, SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as S, RuntimeState  # noqa: E402
from sentinel.feed import publication, store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
BBB = BrokerInstrument(security_id="SEC-BBB", symbol="BBB", broker_id="b-BBB")


def run(coro):
    return asyncio.run(coro)


def cmd(instrument=AAA, qty="10", side=Side.BUY, plan="plan-1", revision=0,
        state=S.PLANNED, filled="0"):
    return Command(
        identity=CommandIdentity(deployment=DEPLOY, plan_id=plan,
                                 security_id=instrument.security_id,
                                 revision=revision),
        instrument=instrument, side=side, quantity=Decimal(qty), state=state,
        filled_quantity=Decimal(filled))


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
    # The deterministic broker's complete terminal-recovery boundary is EPOCH.
    # Production can never observe broker history before its real binding time;
    # align this historical simulator fixture to the same invariant instead of
    # letting the wall-clock INSERT timestamp postdate every simulated read.
    with c.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_account_binding SET established_at=%s WHERE id=1",
            (SimulatedBroker().now,))
    c.commit()
    yield c
    c.close()


class TestCommandJournal:
    def test_a_command_round_trips_with_its_derived_key_intact(self, conn):
        journal.save_command(conn, cmd())
        loaded = journal.load_commands(conn, DEPLOY)
        assert len(loaded) == 1
        assert loaded[0].client_key == cmd().client_key
        assert loaded[0].quantity == Decimal(10)

    def test_average_fill_price_round_trips_as_decimal(self, conn):
        filled = replace(
            cmd(state=S.FILLED, filled="10"),
            broker_order_id="broker-filled-1",
            filled_average_price=Decimal("101.234567"))

        journal.save_command(conn, filled)
        loaded = journal.load_commands(conn, DEPLOY)[0]

        assert loaded.filled_average_price == Decimal("101.234567")
        assert isinstance(loaded.filled_average_price, Decimal)

    def test_a_prior_epoch_recomputes_under_its_STORED_minting_identity(
            self, conn):
        """Adoption fences NEW intent; it does not erase predecessor orders.

        The current binding may load an older epoch only because the row carries
        the exact identity that minted its key. Rebuilding that row under epoch
        two would produce a different key and strand both terminal history and
        any still-working broker obligation.
        """
        journal.save_command(conn, cmd())
        other = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 2)
        loaded = journal.load_commands(conn, other)
        assert loaded[0].identity.deployment == DEPLOY
        assert loaded[0].client_key == cmd().client_key

    def test_a_different_account_still_cannot_load_the_row(self, conn):
        journal.save_command(conn, cmd())
        other = DeploymentIdentity("nas-1", "sim", "OTHER", 2)
        with pytest.raises(journal.StoredKeyMismatch, match="not current"):
            journal.load_commands(conn, other)

    def test_every_transition_is_appended(self, conn):
        c = cmd()
        journal.save_command(conn, c)
        c2 = c.transition(S.SEND_PENDING)
        journal.save_command(conn, c2, previous=c.state)
        c3 = c2.transition(S.ACKNOWLEDGED, broker_order_id="sim-1")
        journal.save_command(conn, c3, previous=c2.state)

        history = journal.command_history(conn, c.client_key)
        assert [h["to"] for h in history] == ["PLANNED", "SEND_PENDING",
                                              "ACKNOWLEDGED"]
        assert history[-1]["from"] == "SEND_PENDING"

    def test_the_DATABASE_enforces_one_in_flight_command_per_security(self, conn):
        """`authorize` checks this too, but an application check can be bypassed
        by a bug or a second process. This one cannot."""
        journal.save_command(conn, cmd(state=S.ACKNOWLEDGED))
        with pytest.raises(Exception):
            journal.save_command(conn, cmd(revision=1, state=S.ACKNOWLEDGED))
        conn.rollback()

    def test_a_TERMINAL_command_frees_the_security_for_a_new_one(self, conn):
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        journal.save_command(conn, cmd(revision=1, state=S.ACKNOWLEDGED))
        assert len(journal.in_flight_commands(conn, DEPLOY)) == 1

    def test_in_flight_includes_UNKNOWN(self, conn):
        journal.save_command(conn, cmd(state=S.UNKNOWN))
        assert [c.state for c in journal.in_flight_commands(conn, DEPLOY)] \
            == [S.UNKNOWN]

    def test_fills_are_idempotent_across_a_re_read(self, conn):
        """A recovery that re-reads recent fills must not double-count them:
        the same fill twice inflates the believed position and generates a
        spurious sell."""
        b = SimulatedBroker()
        c = run(recovery.dispatch(b, recovery.prepare_send(cmd())))
        b.fill(c.client_key)
        fills = run(b.recent_fills(b.now))

        assert journal.record_fills(conn, fills) == 1
        assert journal.record_fills(conn, fills) == 0


class TestTerminalRecoveryWatermark:
    def test_first_checkpoint_falls_back_to_binding_establishment(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT established_at FROM sentinel_account_binding WHERE id=1")
            established = cur.fetchone()[0]

        assert journal.terminal_recovery_checkpoint(conn) == established
        assert journal.terminal_recovery_floor(conn) == (
            established - journal.TERMINAL_RECOVERY_OVERLAP)

    def test_raw_observation_never_advances_processed_history(self, conn):
        before = journal.terminal_recovery_checkpoint(conn)
        claimed = before + timedelta(hours=1)
        journal.record_observation(conn, BrokerObservation(
            observed_at=claimed,
            terminal_recovery_through=claimed,
            completeness=Completeness.COMPLETE))

        assert journal.terminal_recovery_checkpoint(conn) == before

    def test_processed_boundary_is_monotonic_and_account_scoped(self, conn):
        before = journal.terminal_recovery_checkpoint(conn)
        advanced = before + timedelta(hours=1)

        assert journal.advance_terminal_recovery_watermark(
            conn, advanced) == advanced
        assert journal.advance_terminal_recovery_watermark(
            conn, before) == advanced
        with conn.cursor() as cur:
            cur.execute(
                "SELECT broker, broker_account_id, processed_through"
                " FROM sentinel_terminal_recovery_watermark WHERE id=1")
            row = cur.fetchone()
        assert row == ("sim", "SIM-ACCOUNT", advanced)


class TestWriterLock:
    def test_a_second_writer_is_refused_rather_than_blocked(self, conn, pg):
        other = feed_store.connect(pg.sync_dsn)
        try:
            with journal.writer_lock(conn):
                with pytest.raises(journal.WriterLockUnavailable):
                    with journal.writer_lock(other):
                        pass                                  # pragma: no cover
        finally:
            other.close()

    def test_the_lock_is_released_afterwards(self, conn, pg):
        with journal.writer_lock(conn):
            pass
        other = feed_store.connect(pg.sync_dsn)
        try:
            with journal.writer_lock(other):
                pass
        finally:
            other.close()

    def test_an_exception_rolls_back_before_lock_cleanup_commits(self, conn):
        with pytest.raises(RuntimeError, match="abort"):
            with journal.writer_lock(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sentinel_execution_plans"
                        " (plan_id,decision_session,effective_session,"
                        " target_exposure,rollout_mode,rollout_version) VALUES"
                        " ('uncommitted','2026-08-10','2026-08-11',1,"
                        "  'PINNED_1_00',1)")
                raise RuntimeError("abort")

        assert journal.load_plan(conn, "uncommitted") is None


class TestPlans:
    def test_a_plan_round_trips_and_fingerprints_its_ECONOMIC_content(self, conn):
        plan = ExecutionPlan(
            plan_id="plan-1", decision_session=date(2026, 8, 10),
            effective_session=date(2026, 8, 11),
            target_exposure=Decimal("1.0"),
            target_basket={"SEC-AAA": Decimal(10)}, data_version=47)
        journal.save_plan(conn, plan)
        loaded = journal.load_plan(conn, "plan-1")
        assert loaded.target_basket == {"SEC-AAA": Decimal(10)}
        assert loaded.data_version == 47
        assert loaded.fingerprint() == plan.fingerprint()

    def test_every_production_plan_authority_round_trips(self, conn):
        """Column order/defaults cannot erase a production execution authority."""
        plan = ExecutionPlan(
            plan_id="plan-production-authorities",
            decision_session=date(2026, 8, 10),
            effective_session=date(2026, 8, 11),
            target_exposure=Decimal("0.55"),
            target_basket={
                "SEC-AAA": Decimal("17"),
                "SENTINEL:BIL": Decimal("43"),
            },
            data_version=47,
            shadow_snapshot_hash="shadow-state-sha256",
            sentinel_transition_hash="controller-transition-sha256",
            strategy_fingerprint="strategy-sha256",
            deployment_id="sentinel-paper-nas",
            broker="alpaca",
            broker_account_id="PA3ER-ACCOUNT",
            takeover_epoch=7,
            publication_fingerprint="publication-sha256",
            account_nav=Decimal("123456.78"),
            account_cash=Decimal("98765.43"),
            cash_residual=Decimal("4321.09"),
            unpriced_securities=("SEC-ZZZ", "SENTINEL:BIL"),
            defensive_security="SENTINEL:BIL",
            rollout_mode="CONTROLLER", rollout_version=4,
            rollout_certificate_sha256="certificate-sha256")

        journal.save_plan(conn, plan)
        loaded = journal.load_plan(conn, plan.plan_id)

        assert loaded == plan
        assert loaded.fingerprint() == plan.fingerprint()

    def test_the_fingerprint_ignores_the_handle_and_what_happened_after(self):
        base = dict(decision_session=date(2026, 8, 10),
                    effective_session=date(2026, 8, 11),
                    target_exposure=Decimal("1.0"),
                    target_basket={"SEC-AAA": Decimal(10)})
        a = ExecutionPlan(plan_id="plan-1", **base)
        b = ExecutionPlan(plan_id="plan-2", superseded_by="plan-3", **base)
        assert a.fingerprint() == b.fingerprint()

    def test_a_plan_records_the_corpus_version_it_consumed(self, conn):
        """Invariant #3. Without it a replay that disagrees with history cannot
        say whether the broker drifted or the corpus moved."""
        journal.save_plan(conn, ExecutionPlan(
            plan_id="p", decision_session=date(2026, 8, 10),
            effective_session=date(2026, 8, 11),
            target_exposure=Decimal(1), data_version=52))
        assert journal.load_plan(conn, "p").data_version == 52

    def test_supersession_is_recorded_not_destructive(self, conn):
        for pid in ("plan-1", "plan-2"):
            journal.save_plan(conn, ExecutionPlan(
                plan_id=pid, decision_session=date(2026, 8, 10),
                effective_session=date(2026, 8, 11),
                target_exposure=Decimal(1)))
        journal.supersede_plan(conn, "plan-1", "plan-2")
        assert journal.load_plan(conn, "plan-1").superseded_by == "plan-2"
        assert journal.load_plan(conn, "plan-2").superseded_by is None


class TestAgeBookThroughActions:
    def test_a_split_multiplies_the_expected_holding(self):
        aged = R.age_book_through_actions(
            {"SEC-AAA": Decimal(10)}, lambda _s: Decimal(2))
        assert aged == {"SEC-AAA": Decimal(20)}

    def test_no_action_leaves_the_holding_alone(self):
        aged = R.age_book_through_actions(
            {"SEC-AAA": Decimal(10)}, lambda _s: Decimal(1))
        assert aged == {"SEC-AAA": Decimal(10)}

    def test_an_unknown_ratio_is_treated_as_NO_action(self):
        """An unresolvable mapping must not silently HALVE a position. The
        unexplained quantity is caught as foreign activity instead, which is the
        safe direction."""
        aged = R.age_book_through_actions(
            {"SEC-AAA": Decimal(10)}, lambda _s: None)
        assert aged == {"SEC-AAA": Decimal(10)}


class TestReconciliation:
    def _broker(self):
        b = SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        return b

    def test_a_matching_book_reconciles_clean(self, conn):
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        b = self._broker()
        b.seed_position(AAA, "10")

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.clean and result.runtime_state is RuntimeState.RUNNING
        with conn.cursor() as cur:
            cur.execute(
                "SELECT runtime_state FROM sentinel_observations "
                "ORDER BY seq DESC LIMIT 1")
            assert cur.fetchone()[0] == RuntimeState.RUNNING.value

    def test_an_expected_holding_missing_from_broker_is_foreign(self, conn):
        """The comparison is a union; broker omission is not a clean flat."""
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        b = self._broker()

        result = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))

        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert result.foreign_positions == ("SEC-AAA",)

    def test_recognized_partial_fill_position_lag_is_amber_then_converges(
            self, conn):
        durable = replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="broker-partial")
        journal.save_command(conn, durable)
        b = self._broker()
        partial = BrokerOrder(
            broker_order_id="broker-partial",
            client_key=durable.client_key, instrument=AAA,
            side=Side.BUY, state=S.PARTIALLY_FILLED,
            quantity=Decimal(10), filled_quantity=Decimal(4),
            filled_average_price=Decimal(100), submitted_at=b.now)
        current_order = {"value": partial}
        current_positions = {"value": ()}

        async def snapshot(**_kwargs):
            return BrokerObservation(
                observed_at=b.now, orders=(current_order["value"],),
                positions=current_positions["value"],
                terminal_recovery_through=b.now,
                account_identity=b.account)

        b.observe_with_terminal_recovery = snapshot

        first = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert first.runtime_state is RuntimeState.RECONCILING
        assert first.foreign_positions == ()
        assert "position endpoint" in first.detail
        # A dual caller converts amber into a retryable exception inside its
        # writer lock, whose exception path rolls back. Fill progress and the
        # first-seen lag clock must already have crossed a durable boundary.
        conn.rollback()

        # The order endpoint may remain ahead for more than one poll.  The
        # immutable first-seen evidence keeps this amber briefly; it must not
        # depend on observing another fill delta on every poll.
        from sentinel.execution.contract import BrokerPosition
        current_positions["value"] = (
            BrokerPosition(instrument=AAA, quantity=Decimal(2)),)
        b.now += timedelta(seconds=30)
        second_stale = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert second_stale.runtime_state is RuntimeState.RECONCILING
        assert second_stale.foreign_positions == ()

        # The order endpoint can then move again while the position endpoint
        # remains at 2. The old 0->4 episode retains its unreflected remainder
        # and the new 4->6 generation contributes only its additional 2.
        current_order["value"] = replace(
            partial, filled_quantity=Decimal(6))
        b.now += timedelta(seconds=30)
        growing_fill = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert growing_fill.runtime_state is RuntimeState.RECONCILING
        assert growing_fill.foreign_positions == ()

        current_positions["value"] = (
            BrokerPosition(instrument=AAA, quantity=Decimal(6)),)
        b.now += timedelta(seconds=30)
        converged = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert converged.runtime_state is RuntimeState.RUNNING
        assert converged.foreign_positions == ()

        # The ambiguity cannot be renewed forever.  Once the same holding
        # disappears after the bounded endpoint window, it is manual/foreign
        # activity and must fence further risk.
        current_positions["value"] = ()
        b.now += timedelta(seconds=121)
        expired = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert expired.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert expired.foreign_positions == ("SEC-AAA",)

    def test_position_endpoint_may_lead_exact_working_order_briefly(self, conn):
        durable = replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="broker-leading")
        journal.save_command(conn, durable)
        b = self._broker()
        order = {"value": BrokerOrder(
            broker_order_id="broker-leading",
            client_key=durable.client_key, instrument=AAA,
            side=Side.BUY, state=S.ACKNOWLEDGED,
            quantity=Decimal(10), filled_quantity=Decimal(0),
            submitted_at=b.now)}
        from sentinel.execution.contract import BrokerPosition
        position = BrokerPosition(instrument=AAA, quantity=Decimal(4))

        async def snapshot(**_kwargs):
            return BrokerObservation(
                observed_at=b.now, orders=(order["value"],),
                positions=(position,), terminal_recovery_through=b.now,
                account_identity=b.account)

        b.observe_with_terminal_recovery = snapshot
        leading = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert leading.runtime_state is RuntimeState.RECONCILING
        assert leading.foreign_positions == ()

        order["value"] = replace(
            order["value"], state=S.PARTIALLY_FILLED,
            filled_quantity=Decimal(4),
            filled_average_price=Decimal(100))
        b.now += timedelta(seconds=30)
        caught_up = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert caught_up.runtime_state is RuntimeState.RUNNING
        assert caught_up.foreign_positions == ()

    def test_order_leading_position_lag_uses_post_split_share_units(self, conn):
        durable = replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="broker-split-fill")
        journal.save_command(conn, durable)
        b = self._broker()
        observed_order = BrokerOrder(
            broker_order_id="broker-split-fill",
            client_key=durable.client_key, instrument=AAA,
            side=Side.BUY, state=S.FILLED,
            quantity=Decimal(10), filled_quantity=Decimal(10),
            filled_average_price=Decimal(50), submitted_at=b.now)

        async def snapshot(**_kwargs):
            return BrokerObservation(
                observed_at=b.now, orders=(observed_order,), positions=(),
                terminal_recovery_through=b.now,
                account_identity=b.account)

        b.observe_with_terminal_recovery = snapshot
        result = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY,
            actions=lambda _sid, _since=None: Decimal(2)))
        assert result.expected == {"SEC-AAA": Decimal(20)}
        assert result.runtime_state is RuntimeState.RECONCILING
        assert result.foreign_positions == ()

    def test_position_leading_order_lag_uses_post_split_share_units(self, conn):
        durable = replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="broker-split-leading")
        journal.save_command(conn, durable)
        b = self._broker()
        observed_order = BrokerOrder(
            broker_order_id="broker-split-leading",
            client_key=durable.client_key, instrument=AAA,
            side=Side.BUY, state=S.ACKNOWLEDGED,
            quantity=Decimal(10), filled_quantity=Decimal(0),
            submitted_at=b.now)
        from sentinel.execution.contract import BrokerPosition
        post_split_position = BrokerPosition(
            instrument=AAA, quantity=Decimal(20))

        async def snapshot(**_kwargs):
            return BrokerObservation(
                observed_at=b.now, orders=(observed_order,),
                positions=(post_split_position,),
                terminal_recovery_through=b.now,
                account_identity=b.account)

        b.observe_with_terminal_recovery = snapshot
        result = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY,
            actions=lambda _sid, _since=None: Decimal(2)))
        assert result.runtime_state is RuntimeState.RECONCILING
        assert result.foreign_positions == ()

    def test_new_command_generation_does_not_reuse_expired_lag_episode(
            self, conn):
        b = self._broker()
        old = {
            "kind": "ORDER_LEADS_POSITION",
            "client_key": "sntl-old-generation",
            "generation": {
                "side": "BUY", "filled_before": "0", "filled_after": "4",
                "action_multiplier": "1"},
            "signed_capacity": Decimal(4),
        }
        first = R._live_position_lag_capacity(  # noqa: SLF001
            conn, deployment=DEPLOY, security_id="SEC-AAA",
            observed_at=b.now, new_episodes=(old,))
        assert first == (Decimal(4),)
        conn.commit()

        newer = {
            **old,
            "client_key": "sntl-new-generation",
        }
        later = R._live_position_lag_capacity(  # noqa: SLF001
            conn, deployment=DEPLOY, security_id="SEC-AAA",
            observed_at=b.now + timedelta(seconds=121),
            new_episodes=(newer,))
        assert later == (Decimal(4),)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_processed_sessions"
                " WHERE cursor_name LIKE 'broker-position-lag:v2:%'")
            assert cur.fetchone()[0] == 2

    def test_a_WRONG_ACCOUNT_is_refused_before_anything_is_compared(self, conn):
        b = SimulatedBroker(account=BrokerAccountIdentity("sim", "SOMEONE-ELSE"))
        with pytest.raises(B.AccountMismatch):
            run(R.reconcile(broker=b, conn=conn, binding=None,
                            deployment=DEPLOY))

    def test_a_broker_outage_yields_BROKER_DEGRADED_not_a_conclusion(self, conn):
        b = self._broker()
        b.schedule_observe(F.OUTAGE)
        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.BROKER_DEGRADED
        assert not result.foreign_positions, "no conclusions from no data"

    def test_an_INCOMPLETE_observation_cannot_conclude_anything(self, conn):
        b = self._broker()
        b.seed_position(AAA, "10")
        b.schedule_observe(F.TRUNCATED_ORDERS)
        checkpoint = journal.terminal_recovery_checkpoint(conn)
        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.RECONCILING
        assert not result.foreign_positions
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint

    def test_complete_processed_window_advances_even_with_foreign_activity(
            self, conn):
        checkpoint = journal.terminal_recovery_checkpoint(conn)
        b = self._broker()
        b.now = checkpoint + timedelta(hours=1)
        b.seed_position(BBB, "5")

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))

        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert journal.terminal_recovery_checkpoint(conn) == b.now

    def test_A_SPLIT_DURING_AN_OUTAGE_IS_NOT_FOREIGN_ACTIVITY(self, conn):
        """The step everyone omits, and the reason this module has an order.

        Sentinel believes it holds 10. A 2:1 split while it was down makes the
        broker report 20. Without ageing the book first, that is 'a quantity
        change no order explains' — and the appliance latches a re-risking block
        after an entirely ordinary corporate action.
        """
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        b = self._broker()
        b.seed_position(AAA, "10")
        b.apply_corporate_action("SEC-AAA", "2")

        naive = run(R.reconcile(broker=b, conn=conn, binding=None,
                                deployment=DEPLOY))
        assert naive.runtime_state is RuntimeState.FOREIGN_ACTIVITY, (
            "without the actions lookup this is what happens — pinned so the "
            "test proves the rule is load-bearing rather than decorative")

        aware = run(R.reconcile(broker=b, conn=conn, binding=None,
                                deployment=DEPLOY,
                                actions=lambda sid: Decimal(2)))
        assert aware.clean and aware.runtime_state is RuntimeState.RUNNING
        assert aware.corporate_actions == {"SEC-AAA": Decimal(2)}

    def test_a_broker_that_does_not_post_the_split_is_fenced_and_named(
            self, conn):
        """Alpaca paper may omit corporate actions; Sentinel does not forge it."""
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        broker = self._broker()
        broker.seed_position(AAA, "10")

        result = run(R.reconcile(
            broker=broker, conn=conn, binding=None, deployment=DEPLOY,
            actions=lambda sid: Decimal(2)))

        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert result.foreign_positions == ("SEC-AAA",)
        assert "broker environment did not post the corporate action" in \
            result.detail

    def test_a_genuinely_unexplained_position_IS_foreign(self, conn):
        b = self._broker()
        b.seed_position(BBB, "5")               # nobody bought this
        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert result.foreign_positions == ("SEC-BBB",)

    def test_an_order_with_no_key_of_ours_is_foreign(self, conn):
        b = self._broker()
        b.seed_foreign_order(AAA, side=Side.BUY, qty="5")
        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert len(result.foreign_orders) == 1

    def test_an_order_carrying_OUR_key_but_missing_locally_is_RECOVERED(self, conn):
        """A restored backup that predates the order. It is history to adopt,
        never a stranger's order and never something to duplicate."""
        b = self._broker()
        c = run(recovery.dispatch(b, recovery.prepare_send(cmd())))
        # ...and the journal knows nothing about it (the restore happened here).

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert [o.client_key for o in result.recovered_orders] == [c.client_key]
        assert not result.foreign_orders, "ours, not a stranger's"

    def test_an_UNKNOWN_command_is_resolved_during_reconciliation(self, conn):
        b = self._broker()
        b.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        c = run(recovery.dispatch(b, recovery.prepare_send(cmd())))
        assert c.state is S.UNKNOWN
        journal.save_command(conn, c)

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert not result.unresolved
        assert journal.load_commands(conn, DEPLOY)[0].state is S.ACKNOWLEDGED

    def test_positive_closed_evidence_beats_exact_absence_for_UNKNOWN(
            self, conn):
        class ExactAbsentSimulator(SimulatedBroker):
            async def find_by_client_key(self, client_key):
                self.calls.append(f"find:{client_key}:forced-absent")
                return None

        b = ExactAbsentSimulator(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        b.now = journal.terminal_recovery_checkpoint(conn) + timedelta(hours=1)
        b.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        unknown = run(recovery.dispatch(b, recovery.prepare_send(cmd())))
        journal.save_command(conn, unknown)
        b.fill(unknown.client_key)

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        persisted = journal.load_commands(conn, DEPLOY)[0]

        assert result.runtime_state is RuntimeState.RUNNING
        assert persisted.state is S.FILLED
        assert f"find:{unknown.client_key}:forced-absent" not in b.calls

    def test_exact_lookup_failure_does_not_advance_terminal_watermark(
            self, conn):
        class ExactFailureSimulator(SimulatedBroker):
            async def find_by_client_key(self, client_key):
                raise RuntimeError("exact lookup outage")

        journal.save_command(conn, replace(
            cmd(state=S.ACKNOWLEDGED),
            broker_order_id="broker-receipt"))
        checkpoint = journal.terminal_recovery_checkpoint(conn)
        b = ExactFailureSimulator(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
            now=checkpoint + timedelta(hours=1))

        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))

        assert result.runtime_state is RuntimeState.BROKER_DEGRADED
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint

    def test_acknowledged_fill_missing_from_open_set_uses_exact_evidence(
            self, conn):
        """Open-order silence is not terminal evidence; exact lookup is."""

        class OpenOnlySimulator(SimulatedBroker):
            async def observe(self):
                full = await super().observe()
                return replace(
                    full, orders=tuple(o for o in full.orders if o.is_working))

        broker = OpenOnlySimulator(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        acknowledged = run(recovery.dispatch(
            broker, recovery.prepare_send(cmd())))
        journal.save_command(conn, acknowledged)
        broker.fill(acknowledged.client_key)

        result = run(R.reconcile(
            broker=broker, conn=conn, binding=None, deployment=DEPLOY))
        persisted = journal.load_commands(conn, DEPLOY)[0]

        assert result.clean
        assert result.runtime_state is RuntimeState.RUNNING
        assert persisted.state is S.FILLED
        assert persisted.filled_quantity == Decimal(10)
        assert persisted.filled_average_price == Decimal(100)
        assert f"find:{acknowledged.client_key}" in broker.calls

    def test_missing_acknowledged_order_stays_unknown_not_terminal(self, conn):
        established = replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="broker-receipt-1")
        journal.save_command(conn, established)
        broker = self._broker()

        result = run(R.reconcile(
            broker=broker, conn=conn, binding=None, deployment=DEPLOY))
        persisted = journal.load_commands(conn, DEPLOY)[0]

        assert result.runtime_state is RuntimeState.RECONCILING
        assert persisted.state is S.UNKNOWN
        assert persisted.broker_order_id == "broker-receipt-1"
        assert result.unresolved == (persisted,)

    def test_exact_working_order_omitted_by_complete_open_read_is_inconsistent(
            self, conn):
        class OmittingSimulator(SimulatedBroker):
            async def observe(self):
                full = await super().observe()
                return replace(full, orders=())

        broker = OmittingSimulator(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        broker.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        unknown = run(recovery.dispatch(
            broker, recovery.prepare_send(cmd())))
        journal.save_command(conn, unknown)

        result = run(R.reconcile(
            broker=broker, conn=conn, binding=None, deployment=DEPLOY))

        assert result.runtime_state is RuntimeState.RECONCILING
        assert result.observation.completeness.value == "INCONSISTENT"
        assert journal.load_commands(conn, DEPLOY)[0].state is S.UNKNOWN

    def test_an_UNRESOLVABLE_command_keeps_the_appliance_RECONCILING(self, conn):
        journal.save_command(conn, cmd(state=S.UNKNOWN))
        b = self._broker()
        b.schedule_observe(F.TRUNCATED_ORDERS)
        result = run(R.reconcile(broker=b, conn=conn, binding=None,
                                 deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.RECONCILING

    def test_the_expected_book_comes_from_the_JOURNAL_not_the_broker(self, conn):
        """Seeding belief from the broker makes the comparison vacuous."""
        journal.save_command(conn, cmd(state=S.FILLED, filled="10"))
        journal.save_command(conn, cmd(instrument=BBB, side=Side.SELL,
                                       qty="4", state=S.FILLED, filled="4"))
        book = R.expected_book_from_commands(journal.load_commands(conn, DEPLOY))
        assert book == {"SEC-AAA": Decimal(10), "SEC-BBB": Decimal(-4)}

    def test_actions_age_each_fill_from_its_own_durable_boundary(self):
        """A later BUY must not inherit a split that aged an earlier BUY."""
        before = Command(
            **{**cmd(state=S.FILLED, filled="10").__dict__,
               "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)})
        after = Command(
            **{**cmd(qty="5", revision=1, state=S.FILLED,
                     filled="5").__dict__,
               "created_at": datetime(2026, 8, 6, tzinfo=timezone.utc)})

        def actions(_security_id, since=None):
            return Decimal(2) if since < date(2026, 8, 5) else Decimal(1)

        assert R.expected_book_from_commands(
            (before, after), actions=actions) == {"SEC-AAA": Decimal(25)}

    def test_recovered_fill_keeps_broker_submission_time_for_action_aging(
            self, conn):
        submitted = datetime(2026, 8, 1, 14, tzinfo=timezone.utc)
        order = BrokerOrder(
            broker_order_id="broker-recovered-1",
            client_key="sntl-recovered-before-split",
            instrument=AAA,
            side=Side.BUY,
            state=S.FILLED,
            quantity=Decimal(10),
            filled_quantity=Decimal(10),
            filled_average_price=Decimal(100),
            submitted_at=submitted)

        journal.adopt_recovered_order(conn, order, deployment=DEPLOY)
        recovered = journal.load_commands(conn, DEPLOY)

        assert len(recovered) == 1
        assert recovered[0].created_at == submitted
        assert recovered[0].filled_average_price == Decimal(100)

        def actions(_security_id, since=None):
            return Decimal(2) if since <= date(2026, 8, 1) else Decimal(1)

        assert R.expected_book_from_commands(
            recovered, actions=actions) == {"SEC-AAA": Decimal(20)}

    def test_overlap_economics_change_blocks_and_leaves_watermark(self, conn):
        b = self._broker()
        b.now = journal.terminal_recovery_checkpoint(conn) + timedelta(hours=1)
        sent = run(recovery.dispatch(b, recovery.prepare_send(cmd())))
        b.fill(sent.client_key)
        first = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))
        assert first.runtime_state is RuntimeState.RUNNING
        checkpoint = journal.terminal_recovery_checkpoint(conn)

        broker_order = b._by_key(sent.client_key)
        broker_order.side = Side.SELL
        second = run(R.reconcile(
            broker=b, conn=conn, binding=None, deployment=DEPLOY))

        assert second.runtime_state is RuntimeState.RECONCILING
        assert "changed durable side" in second.detail
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint


class TestTerminalRecoveryCrashBoundaries:
    @staticmethod
    def _filled_broker(conn, instruments=(AAA,)):
        checkpoint = journal.terminal_recovery_checkpoint(conn)
        broker = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
            now=checkpoint + timedelta(hours=1))
        commands = []
        for instrument in instruments:
            sent = run(recovery.dispatch(
                broker, recovery.prepare_send(cmd(instrument=instrument))))
            broker.fill(sent.client_key)
            commands.append(sent)
        return broker, tuple(commands), checkpoint

    def test_crash_after_observation_before_adoption_replays(self, conn,
                                                             monkeypatch):
        broker, commands, checkpoint = self._filled_broker(conn)
        original = journal.adopt_recovered_order

        def crash(*_args, **_kwargs):
            raise RuntimeError("crash before adoption")

        monkeypatch.setattr(journal, "adopt_recovered_order", crash)
        with pytest.raises(RuntimeError, match="before adoption"):
            run(R.reconcile(broker=broker, conn=conn, binding=None,
                            deployment=DEPLOY))
        assert journal.load_commands(conn, DEPLOY) == ()
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint

        monkeypatch.setattr(journal, "adopt_recovered_order", original)
        retry = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                deployment=DEPLOY))
        assert retry.runtime_state is RuntimeState.RUNNING
        assert {c.client_key for c in journal.load_commands(conn, DEPLOY)} == {
            commands[0].client_key}

    def test_crash_midway_through_multiple_adoptions_replays_only_missing(
            self, conn, monkeypatch):
        broker, commands, checkpoint = self._filled_broker(conn, (AAA, BBB))
        original = journal.adopt_recovered_order
        calls = {"n": 0}

        def crash_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("crash midway")
            return original(*args, **kwargs)

        monkeypatch.setattr(journal, "adopt_recovered_order", crash_second)
        with pytest.raises(RuntimeError, match="midway"):
            run(R.reconcile(broker=broker, conn=conn, binding=None,
                            deployment=DEPLOY))
        assert len(journal.load_commands(conn, DEPLOY)) == 1
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint

        monkeypatch.setattr(journal, "adopt_recovered_order", original)
        retry = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                deployment=DEPLOY))
        assert retry.runtime_state is RuntimeState.RUNNING
        assert {c.client_key for c in journal.load_commands(conn, DEPLOY)} == {
            c.client_key for c in commands}

    def test_crash_after_adoption_before_watermark_is_idempotent(
            self, conn, monkeypatch):
        broker, commands, checkpoint = self._filled_broker(conn)
        original = journal.advance_terminal_recovery_watermark

        def crash(*_args, **_kwargs):
            raise RuntimeError("crash before watermark")

        monkeypatch.setattr(
            journal, "advance_terminal_recovery_watermark", crash)
        with pytest.raises(RuntimeError, match="before watermark"):
            run(R.reconcile(broker=broker, conn=conn, binding=None,
                            deployment=DEPLOY))
        assert [c.client_key for c in journal.load_commands(conn, DEPLOY)] == [
            commands[0].client_key]
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_command_events"
                " WHERE detail LIKE 'recovered:%'")
            events_before = cur.fetchone()[0]

        monkeypatch.setattr(
            journal, "advance_terminal_recovery_watermark", original)
        retry = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                deployment=DEPLOY))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_command_events"
                " WHERE detail LIKE 'recovered:%'")
            events_after = cur.fetchone()[0]
        assert retry.runtime_state is RuntimeState.RUNNING
        assert events_after == events_before == 1
        assert journal.terminal_recovery_checkpoint(conn) == broker.now

    def test_restart_after_watermark_commit_is_a_noop_replay(self, conn):
        broker, commands, _checkpoint = self._filled_broker(conn)
        first = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                deployment=DEPLOY))
        watermark = journal.terminal_recovery_checkpoint(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_command_events")
            events = cur.fetchone()[0]

        second = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                 deployment=DEPLOY))
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_command_events")
            replay_events = cur.fetchone()[0]
        assert first.runtime_state is second.runtime_state is RuntimeState.RUNNING
        assert journal.terminal_recovery_checkpoint(conn) == watermark
        assert replay_events == events
        assert [c.client_key for c in journal.load_commands(conn, DEPLOY)] == [
            commands[0].client_key]

    def test_adoption_conflict_does_not_advance(self, conn):
        checkpoint = journal.terminal_recovery_checkpoint(conn)
        journal.save_command(conn, replace(
            cmd(state=S.ACKNOWLEDGED), broker_order_id="durable-aaa"))
        broker = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
            now=checkpoint + timedelta(hours=1))
        other = run(recovery.dispatch(
            broker, recovery.prepare_send(cmd(plan="other-plan"))))

        result = run(R.reconcile(broker=broker, conn=conn, binding=None,
                                 deployment=DEPLOY))

        assert result.runtime_state is RuntimeState.RECONCILING
        assert other.client_key in {o.client_key
                                    for o in result.recovered_orders}
        assert journal.terminal_recovery_checkpoint(conn) == checkpoint


def put_bar(conn, security_id, session, ticker, *, split_ratio="1"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id, session, ticker,"
            " close_signal,close_unadjusted,split_ratio)"
            " VALUES (%s,%s,%s,10,10,%s)"
            " ON CONFLICT (security_id, session) DO NOTHING",
            (security_id, session, ticker, split_ratio))
    conn.commit()


def put_defensive_bar(conn, session, *, close_signal, close_unadjusted):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_defensive_bars"
            " (session,close_signal,close_unadjusted) VALUES (%s,%s,%s)",
            (session, close_signal, close_unadjusted))
    conn.commit()


class TestCorpusActionLookup:
    def test_it_compounds_splits_over_the_gap(self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="2")
        put_bar(conn, "SEC-AAA", "2026-08-07", "AAA", split_ratio="3")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 2.0},
            {"ticker": "AAA", "date": "2026-08-07", "action": "split",
             "value": 3.0}])

        lookup = R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                        end=date(2026, 8, 10))
        assert lookup("SEC-AAA") == pytest.approx(Decimal(6))
        assert lookup("SEC-AAA", date(2026, 8, 6)) \
            == pytest.approx(Decimal(3))

    def test_distinct_split_siblings_refuse_instead_of_multiplying(self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="2")
        run = feed_store.IngestRun(conn, "ambiguous-splits")
        with feed_store.corpus_write_lock(conn):
            feed_store.write_actions(conn, [
                {"ticker": "AAA", "date": "2026-08-05", "action": "split",
                 "value": 2.0, "contraticker": None},
                {"ticker": "AAA", "date": "2026-08-05", "action": "split",
                 "value": None, "contraticker": "SIBLING"},
            ], run_id=run.progress.run_id,
                window_start="2026-08-05", window_end="2026-08-05")
            run.finish("success")
            publication.publish(conn, run_id=run.progress.run_id)
        with pytest.raises(ValueError, match="ambiguous split ACTIONS multiplicity"):
            R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                   end=date(2026, 8, 10))

    def test_a_RECYCLED_ticker_does_not_inherit_the_other_company_split(self, conn):
        """R6. Tickers are reused, and resolving one to EVERY security that ever
        held it applies one company's split to another's holding — multiplying
        the wrong expected quantity before deciding whether the broker looks
        foreign.

        Strange defect to ship in this package in particular: the ingest refuses
        to fall back to the ticker precisely because reuse splices unrelated
        companies. The same rule has to hold on the way out.
        """
        put_bar(conn, "SEC-OLD", "2011-06-01", "XYZ")     # the first company
        put_bar(conn, "SEC-OLD", "2011-06-02", "XYZ", split_ratio="2")
        put_bar(conn, "SEC-NEW", "2026-08-05", "XYZ")     # inherited the symbol
        feed_store.write_actions(conn, [
            {"ticker": "XYZ", "date": "2011-06-02", "action": "split",
             "value": 2.0}])

        # The 2011 split, looked up over a 2011 gap, belongs to SEC-OLD only.
        old_gap = R.corpus_action_lookup(conn, start=date(2011, 1, 1),
                                         end=date(2011, 12, 31))
        assert old_gap("SEC-OLD") == pytest.approx(Decimal(2))
        assert old_gap("SEC-NEW") == Decimal(1), (
            "SEC-NEW did not exist under this ticker in 2011 and must not "
            "inherit its split")

    def test_a_WEEKEND_ex_date_still_resolves(self, conn):
        """`sentinel_actions.session` holds the vendor's EX-DATE, a CALENDAR
        date that can fall on a non-session. An exact-session join would drop
        it, and a dropped split reconciles the book against the wrong share
        count."""
        put_bar(conn, "SEC-AAA", "2026-08-07", "AAA")     # Friday
        put_bar(conn, "SEC-AAA", "2026-08-10", "AAA",     # effective Monday
                split_ratio="2")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-08", "action": "split",
             "value": 2.0}])                              # Saturday ex-date

        lookup = R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                        end=date(2026, 8, 10))
        assert lookup("SEC-AAA") == pytest.approx(Decimal(2))
        assert lookup("SEC-AAA", date(2026, 8, 9)) == Decimal(2)
        assert lookup("SEC-AAA", date(2026, 8, 10)) == Decimal(1)

    def test_a_REVERSE_split_is_supported(self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="0.1")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 0.1}])
        lookup = R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                        end=date(2026, 8, 10))
        assert lookup("SEC-AAA") == pytest.approx(Decimal("0.1"))

    def test_reverse_split_denominator_uses_published_canonical_ratio(self, conn):
        """ACTIONS 30 can mean 1-for-30; raw multiplication is 900x wrong."""
        canonical = Decimal(1) / Decimal(30)
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA",
                split_ratio=canonical)
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 30}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SEC-AAA") == pytest.approx(canonical)
        assert lookup("SEC-AAA") != Decimal(30)
        scalar = lookup.scalar_evidence_for({"SEC-AAA"})[0]
        assert scalar.value == 30
        evidence = (scalar.to_dict(),)
        assert evidence[0]["canonical_multiplier"] != "30"

        projected = target_reprojection.project_target(
            ExecutionPlan(
                plan_id="reverse-denominator", decision_session=date(2026, 8, 1),
                effective_session=date(2026, 8, 10),
                target_exposure=Decimal(1),
                target_basket={"SEC-AAA": Decimal(300)}),
            through_session=date(2026, 8, 10),
            action_multipliers={"SEC-AAA": lookup("SEC-AAA")},
            action_evidence=evidence,
            minimum_quantity_increment=Decimal(1))
        assert projected.target_basket == {"SEC-AAA": Decimal(10)}

    def test_ADR_ratio_split_uses_the_published_canonical_ratio(self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="0.5")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05",
             "action": "adrratiosplit", "value": 2}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SEC-AAA") == Decimal("0.5")
        assert lookup.scalar_evidence_for({"SEC-AAA"})[0].action \
            == "adrratiosplit"

    def test_published_derived_only_split_ages_book_and_target_without_ACTIONS(
            self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="2")

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        before = Command(
            **{**cmd(state=S.FILLED, filled="10").__dict__,
               "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)})
        assert R.expected_book_from_commands(
            (before,), actions=lookup) == {"SEC-AAA": Decimal(20)}
        scalar = lookup.scalar_evidence_for({"SEC-AAA"})[0]
        assert scalar.evidence_kind == "published_equity_bar"
        projected = target_reprojection.project_target(
            ExecutionPlan(
                plan_id="derived-only", decision_session=date(2026, 8, 1),
                effective_session=date(2026, 8, 10),
                target_exposure=Decimal(1),
                target_basket={"SEC-AAA": Decimal(10)}),
            through_session=date(2026, 8, 10),
            action_multipliers={"SEC-AAA": lookup("SEC-AAA")},
            action_evidence=(scalar.to_dict(),),
            minimum_quantity_increment=Decimal(1))
        assert projected.target_basket == {"SEC-AAA": Decimal(20)}

    def test_active_split_disagreement_refuses_stale_preserved_bar_ratio(
            self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="2")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 3}])
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_corpus_anomalies"
                " (kind,ticker,session,detail) VALUES"
                " ('SPLIT_DISAGREEMENT','AAA','2026-08-05','2 versus 3')")
        conn.commit()

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SEC-AAA") == Decimal(1)
        material = lookup.material_events_for(security_ids={"SEC-AAA"})
        assert len(material) == 1
        assert "SPLIT_DISAGREEMENT" in material[0].reason

    def test_execution_uses_published_repair_and_ignores_unpublished_candidate(
            self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA", split_ratio="2")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 30}])
        canonical = Decimal(1) / Decimal(30)
        published = feed_store.IngestRun(conn, "published-execution-repair")
        with feed_store.corpus_write_lock(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_bar_split_repairs"
                    " (security_id,session,split_ratio,prior_split_ratio,"
                    " last_written_run_id) VALUES (%s,%s,%s,2,%s)",
                    ("SEC-AAA", "2026-08-05", canonical,
                     published.progress.run_id))
            conn.commit()
            published.finish("success")
            publication.publish(conn, run_id=published.progress.run_id)

        unpublished = feed_store.IngestRun(conn, "unpublished-execution-repair")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bar_split_repairs"
                " (security_id,session,split_ratio,prior_split_ratio,"
                " last_written_run_id) VALUES (%s,%s,0.5,%s,%s)",
                ("SEC-AAA", "2026-08-05", canonical,
                 unpublished.progress.run_id))
        conn.commit()

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SEC-AAA") == pytest.approx(canonical)
        scalar = lookup.scalar_evidence_for({"SEC-AAA"})[0]
        assert scalar.publication_run_id == str(published.progress.run_id)

    def test_BIL_denominator_is_resolved_from_consecutive_price_domains(
            self, conn):
        put_defensive_bar(
            conn, "2026-08-04", close_signal="100", close_unadjusted="100")
        # before=1 and after=3, so the independent share multiplier is 1/3.
        put_defensive_bar(
            conn, "2026-08-05", close_signal="100", close_unadjusted="300")
        feed_store.write_actions(conn, [
            {"ticker": "BIL", "date": "2026-08-05", "action": "split",
             "value": 3}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SENTINEL:BIL") == pytest.approx(Decimal(1) / Decimal(3))
        assert lookup.material_events_for(
            security_ids={"SENTINEL:BIL"}) == ()

    def test_BIL_domain_discontinuity_without_ACTIONS_is_explicitly_blocking(
            self, conn):
        put_defensive_bar(
            conn, "2026-08-04", close_signal="100", close_unadjusted="100")
        put_defensive_bar(
            conn, "2026-08-05", close_signal="100", close_unadjusted="50")

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SENTINEL:BIL") == Decimal(1)
        material = lookup.material_events_for(
            security_ids={"SENTINEL:BIL"})
        assert len(material) == 1
        assert material[0].evidence_kind == \
            "published_defensive_domains_unmatched"

    def test_BIL_orientation_does_not_bridge_a_missing_exchange_session(
            self, conn):
        put_defensive_bar(
            conn, "2026-08-03", close_signal="100", close_unadjusted="100")
        put_defensive_bar(
            conn, "2026-08-05", close_signal="100", close_unadjusted="300")
        feed_store.write_actions(conn, [
            {"ticker": "BIL", "date": "2026-08-05", "action": "split",
             "value": 3}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup("SENTINEL:BIL") == Decimal(1)
        material = lookup.material_events_for(
            security_ids={"SENTINEL:BIL"})
        assert len(material) == 1
        assert "immediately consecutive" in material[0].reason

    def test_a_SPINOFF_is_NOT_silently_treated_as_a_multiplier(self, conn):
        """Scope honesty. A spinoff is not expressible as a share-count scalar,
        so it is left to foreign-activity handling — visible and blocking —
        rather than approximated. The prose describes spinoffs; this is what is
        IMPLEMENTED."""
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "spinoff",
             "value": 2.0}])
        lookup = R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                        end=date(2026, 8, 10))
        assert lookup("SEC-AAA") == Decimal(1)
        assert "spinoff" not in R.SUPPORTED_ACTIONS
        assert [event.action for event in lookup.material_events_for(
            security_ids={"SEC-AAA"})] == ["spinoff"]

    def test_dividend_and_acquirer_side_rows_do_not_fence_the_held_book(
            self, conn):
        put_bar(conn, "SEC-AAA", "2026-08-05", "AAA")
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "dividend",
             "value": 0.25},
            {"ticker": "AAA", "date": "2026-08-05",
             "action": "spinoffdividend", "value": 0.1},
            {"ticker": "AAA", "date": "2026-08-06",
             "action": "acquisitionof", "value": None,
             "contraticker": "VICTIM"}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        assert lookup.material_events_for(security_ids={"SEC-AAA"}) == ()

    def test_unmapped_target_split_is_retained_as_blocking_evidence(self, conn):
        feed_store.write_actions(conn, [
            {"ticker": "AAA", "date": "2026-08-05", "action": "split",
             "value": 2}])

        lookup = R.corpus_action_lookup(
            conn, start=date(2026, 8, 1), end=date(2026, 8, 10))

        events = lookup.material_events_for(symbols={"AAA"})
        assert len(events) == 1
        assert events[0].reason == (
            "scalar action has absent published effective-session security mapping")

    def test_an_unmapped_security_returns_1_rather_than_raising(self, conn):
        lookup = R.corpus_action_lookup(conn, start=date(2026, 8, 1),
                                        end=date(2026, 8, 10))
        assert lookup("SEC-NOPE") == Decimal(1)
