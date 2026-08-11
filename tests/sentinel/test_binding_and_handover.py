"""Ownership is database state, and ordinary startup can no longer liquidate.

TWO CHANGES, and the second is the one that matters.

STORAGE. `ownership.jsonl` sat on a different Docker volume from PostgreSQL, so
a restore could recover the database and lose the file — after which the two
disagree about whether the account was migrated, and the file's ABSENCE is the
dangerous direction.

BEHAVIOUR. The old `establish-ownership` read that file and, when it said
nothing, classified whatever the account held as a legacy Stocker book and began
closing positions. A Wealth Core book's safety rested on a file existing. A
property that fails open when a file goes missing is not a property.

So: the binding lives in PostgreSQL, migration is an explicitly invoked
administrative command that REFUSES against a bound account, and ordinary
startup has no liquidation path to re-arm.

Contract: docs/sentinel-execution-contract.md §11.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from fakes import FakeBroker  # noqa: E402
from sentinel import binding as B, handover, schema  # noqa: E402
from sentinel.execution.contract import BrokerAccountIdentity  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402
from sentinel.ownership import OpenOrder, OwnershipState as S  # noqa: E402
from sentinel.store import (  # noqa: E402
    PostgresOwnershipStore, mirror_to_file, ownership_established)


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
        for t in ("sentinel_account_binding", "sentinel_ownership_events",
                  "sentinel_commands", "sentinel_command_events",
                  "sentinel_execution_plans", "sentinel_fills",
                  "sentinel_observations"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    yield c
    c.close()


class AccountBroker(FakeBroker):
    """FakeBroker that also reports an account id, as a real one does."""

    def __init__(self, *a, account_id="ACC-123", **kw):
        super().__init__(*a, **kw)
        self._account_id = account_id
        self.adapter = type("A", (), {"name": "sim"})()

    async def account(self):
        return BrokerAccountIdentity("sim", self._account_id)


def run(coro):
    return asyncio.run(coro)


async def _nosleep(_seconds):
    return None


class TestBinding:
    def test_an_unbound_appliance_REFUSES_rather_than_deciding(self, conn):
        assert B.load(conn) is None
        with pytest.raises(B.AccountNotBound):
            B.require(conn)

    def test_binding_is_ONE_row_enforced_by_the_schema(self, conn):
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        with pytest.raises(Exception):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_account_binding (id, deployment_id,"
                    " broker, broker_account_id, ownership_state)"
                    " VALUES (2,'nas-2','sim','ACC-999','SENTINEL_OWNED')")
        conn.rollback()

    def test_bind_is_NOT_an_upsert(self, conn):
        """Re-pointing an appliance at a different account is either an
        adoption or a mistake; an upsert would let a misconfigured restart do
        it silently."""
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        with pytest.raises(B.AlreadyBound):
            B.bind(conn, deployment_id="nas-1", broker="sim",
                   broker_account_id="ACC-999")

    def test_verify_accepts_the_bound_account(self, conn):
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        assert B.verify(conn, BrokerAccountIdentity("sim", "ACC-123"))

    def test_verify_REFUSES_a_different_account(self, conn):
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        with pytest.raises(B.AccountMismatch):
            B.verify(conn, BrokerAccountIdentity("sim", "SOMEONE-ELSE"))

    def test_verify_REFUSES_an_unreadable_account(self, conn):
        """'We could not tell' and 'it is the right account' are the same
        conflation UNKNOWN exists to prevent one layer down."""
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        with pytest.raises(B.AccountMismatch):
            B.verify(conn, None)

    def test_the_binding_yields_the_identity_commands_are_keyed_on(self, conn):
        """One object, two consumers: the fields that answer 'whose account is
        this' are the ones hashed into every client key."""
        bound = B.bind(conn, deployment_id="nas-1", broker="sim",
                       broker_account_id="ACC-123")
        assert bound.identity.broker_account_id == "ACC-123"
        assert bound.identity.takeover_epoch == 1

    def test_adoption_increments_the_epoch_and_disjoins_the_keyspace(self, conn):
        from sentinel.execution.identity import CommandIdentity
        before = B.bind(conn, deployment_id="nas-1", broker="sim",
                        broker_account_id="ACC-123")
        key_before = CommandIdentity(deployment=before.identity, plan_id="p",
                                     security_id="S").client_key

        after = B.adopt_restored(conn, notes="replacement host")
        key_after = CommandIdentity(deployment=after.identity, plan_id="p",
                                    security_id="S").client_key

        assert after.takeover_epoch == before.takeover_epoch + 1
        assert key_before != key_after


class TestPostgresOwnershipStore:
    def test_events_round_trip_in_order(self, conn):
        from sentinel.store import record
        store = PostgresOwnershipStore(conn)
        record(store, S.ACCOUNT_INSPECTED, reason="looked")
        record(store, S.FLAT_CONFIRMED, reason="empty")
        assert [e.state for e in store.events()] == [S.ACCOUNT_INSPECTED,
                                                     S.FLAT_CONFIRMED]
        assert store.events()[0].detail == {"reason": "looked"}

    def test_ownership_established_reads_the_whole_history(self, conn):
        from sentinel.store import record
        store = PostgresOwnershipStore(conn)
        assert not ownership_established(store)
        record(store, S.SENTINEL_OWNERSHIP_ESTABLISHED, reason="done")
        record(store, S.ACCOUNT_INSPECTED, reason="a later, lesser event")
        assert ownership_established(store), (
            "a decision that was taken cannot become untaken by a later event")

    def test_the_file_is_AUDIT_evidence_and_flows_one_way(self, conn, tmp_path):
        from sentinel.store import FileOwnershipStore, record
        store = PostgresOwnershipStore(conn)
        record(store, S.FLAT_CONFIRMED, reason="empty")

        path = tmp_path / "ownership.jsonl"
        assert mirror_to_file(store, path) == 1
        assert mirror_to_file(store, path) == 0, "idempotent"
        assert [e.state for e in FileOwnershipStore(path).events()] == \
            [S.FLAT_CONFIRMED]


class TestMigrationCannotReArm:
    def test_a_bound_account_REFUSES_migration_before_touching_the_broker(self, conn):
        """The de-arming, and the ordering matters: the refusal happens before
        any broker call, so a command that could liquidate never reaches one."""
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        broker = AccountBroker(positions={"AAPL": 10})

        with pytest.raises(handover.MigrationRefused, match="already bound"):
            run(handover.migrate_account(
                broker=broker, conn=conn, deployment_id="nas-1",
                expected_account=None, sleep=_nosleep))

        assert broker.closes == [], "no liquidation was even attempted"

    def test_ordinary_startup_has_no_legacy_path(self, conn):
        B.bind(conn, deployment_id="nas-1", broker="sim",
               broker_account_id="ACC-123")
        assert handover.assert_no_legacy_path(conn).is_owned

    def test_ordinary_startup_on_an_UNBOUND_appliance_refuses(self, conn):
        """It does not decide for itself what the positions it can see must be."""
        with pytest.raises(B.AccountNotBound):
            handover.assert_no_legacy_path(conn)

    def test_a_wrong_account_is_refused_before_liquidating(self, conn):
        broker = AccountBroker(positions={"AAPL": 10}, account_id="ACC-OTHER")
        with pytest.raises(handover.MigrationRefused, match="expected"):
            run(handover.migrate_account(
                broker=broker, conn=conn, deployment_id="nas-1",
                expected_account="ACC-123", sleep=_nosleep))
        assert broker.closes == []


class TestMigrationRequiresStableFlatness:
    def test_a_clean_handover_binds_the_account(self, conn):
        broker = AccountBroker(positions={"AAPL": 10}, fills_after=0)
        result = run(handover.migrate_account(
            broker=broker, conn=conn, deployment_id="nas-1",
            expected_account="ACC-123", sleep=_nosleep))

        assert broker.closes == ["AAPL"]
        assert result.binding.broker_account_id == "ACC-123"
        assert B.require(conn).is_owned
        assert ownership_established(PostgresOwnershipStore(conn))

    def test_ONE_flat_read_is_not_enough(self, conn):
        """Ownership is irreversible, so it is not recorded from a single
        observation. A position appearing on the second read — a fill, or a
        foreign order — is exactly what it is for."""
        broker = AccountBroker(positions={}, fills_after=0)

        calls = {"n": 0}
        original = broker.observe

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 2:
                broker.positions["SURPRISE"] = 5.0
            return await original()

        broker.observe = flaky
        with pytest.raises(handover.MigrationRefused, match="two consecutive"):
            run(handover.migrate_account(
                broker=broker, conn=conn, deployment_id="nas-1",
                expected_account="ACC-123", sleep=_nosleep))
        assert B.load(conn) is None, "nothing was bound"

    def test_a_resting_order_on_the_second_read_also_blocks(self, conn):
        broker = AccountBroker(positions={}, fills_after=0)
        original = broker.observe
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 2:
                broker.orders.append(OpenOrder("late-1", "GHOST", "buy"))
            return await original()

        broker.observe = flaky
        with pytest.raises(handover.MigrationRefused):
            run(handover.migrate_account(
                broker=broker, conn=conn, deployment_id="nas-1",
                expected_account=None, sleep=_nosleep))

    def test_binding_and_events_land_together(self, conn):
        broker = AccountBroker(positions={}, fills_after=0)
        run(handover.migrate_account(
            broker=broker, conn=conn, deployment_id="nas-1",
            expected_account=None, sleep=_nosleep))
        assert B.load(conn) is not None
        assert ownership_established(PostgresOwnershipStore(conn))


class TestTheRetiredCommand:
    def test_establish_ownership_refuses_and_says_what_to_run(self, capsys):
        from sentinel.__main__ import main
        import os
        os.environ.setdefault("ALPACA_API_KEY", "k")
        os.environ.setdefault("ALPACA_SECRET_KEY", "s")
        assert main(["establish-ownership"]) != 0
        err = capsys.readouterr().err
        assert "retired" in err.lower()
        assert "migrate-account" in err, (
            "an argparse error with no replacement named is how a stale runbook "
            "turns into an outage on the one command that could liquidate")
