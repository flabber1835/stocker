"""Missing historical fill detail cannot certify P/L or stop a clean mirror."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import paper_performance, trial
from sentinel.execution import journal, fill_integrity
from sentinel.execution.states import CommandState
from sentinel.execution.contract import BrokerFill
from tests.support import native_fill_fixture as fixture
from tests.sentinel.test_rolling_snapshot_publisher import pg, conn  # noqa: F401


def filled_command(conn):
    owner, command, *_ = fixture.fixture(conn, native_quantities=())
    command = replace(command, state=CommandState.FILLED, filled_quantity=D(10),
                      filled_average_price=D(100), broker_order_id="order-1")
    journal.save_command(conn, command)
    conn.commit()
    return owner, command


def scan(conn, owner, informational):
    return paper_performance.scan_entitlements(
        conn, binding=owner.to_dict(), through=fixture.FILL.date(),
        account=SimpleNamespace(cash=D(9000), equity=D(10000)),
        informational_only=informational)


def test_missing_native_rows_are_reported_without_inventing_cash_or_fills(conn):
    owner, command = filled_command(conn)
    with pytest.raises(trial.TrialEvidenceRefused, match="complete native fills"):
        scan(conn, owner, False)
    conn.rollback()
    assert scan(conn, owner, True) is None
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        assert scan(restarted, owner, True) is None
        assert restarted.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 0
        assert restarted.execute("SELECT COUNT(*) FROM sentinel_cash_flows").fetchone()[0] == 0
        gaps = restarted.execute("SELECT state FROM sentinel_processed_sessions "
                                 "WHERE cursor_name LIKE 'paper-entitlement-gap:v1:%'").fetchall()
        assert len(gaps) == 1
        assert gaps[0][0]["performance_valid"] is False
        assert gaps[0][0]["synthetic_adjustment"] is None
        assert paper_performance.load(restarted, owner.to_dict()) is None
    # Later authoritative fill detail earns coverage; the gap record survives.
    journal.record_fills(conn, [BrokerFill(command.client_key, "order-1", D(10), D(100), fixture.FILL)])
    assert fill_integrity.require_durable_coverage(conn, owner.to_dict(), allow_incomplete=True)


@pytest.mark.parametrize("quantity,price", [("6", "100"), ("0.5", "50")])
def test_strictly_partial_coherent_history_is_pending(conn, quantity, price):
    owner, command = filled_command(conn)
    journal.record_fills(conn, [BrokerFill(command.client_key, "order-1", D(quantity), D(price), fixture.FILL)])
    assert fill_integrity.require_durable_coverage(conn, owner.to_dict(), allow_incomplete=True) is False
    assert scan(conn, owner, True) is None


@pytest.mark.parametrize("quantity,price", [("11", "100"), ("10", "101"), ("5", "200"), ("5", "201")])
def test_contradictory_native_economics_still_refuse_informational_mode(conn, quantity, price):
    owner, command = filled_command(conn)
    journal.record_fills(conn, [BrokerFill(command.client_key, "order-1", D(quantity), D(price), fixture.FILL)])
    with pytest.raises(trial.TrialEvidenceRefused):
        scan(conn, owner, True)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions "
                        "WHERE cursor_name LIKE 'paper-entitlement-gap:v1:%'").fetchone()[0] == 0


def test_unresolved_commands_remain_a_refusal(conn):
    owner, *_ = fixture.fixture(conn, native_quantities=())
    with pytest.raises(trial.TrialEvidenceRefused, match="unresolved commands"):
        scan(conn, owner, True)


def test_incomplete_first_command_cannot_hide_later_contradiction():
    class Rows:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, *_): pass
        def fetchall(self):
            return [("missing", "FILLED", D(10), D(100), D(0), D(0)),
                    ("bad", "FILLED", D(10), D(100), D(11), D(1100))]
    with pytest.raises(trial.TrialEvidenceRefused):
        fill_integrity.require_durable_coverage(SimpleNamespace(cursor=Rows),
            {"broker": "alpaca", "broker_account_id": "test"}, allow_incomplete=True)
