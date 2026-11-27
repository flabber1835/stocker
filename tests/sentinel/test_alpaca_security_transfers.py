from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from uuid import UUID

import pytest

from sentinel.execution import alpaca_security_transfers as transfers
from sentinel.execution.contract import BrokerInstrument, BrokerObservation, BrokerPosition
from sentinel.execution.states import CommandState


NOW = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)
ACCOUNT = str(UUID(int=1))
ASSET = str(UUID(int=2))
OTHER = str(UUID(int=3))
FIRST_REF = str(UUID(int=4))
INSTRUMENT = BrokerInstrument(security_id="sec-1", symbol="TEST", broker_id=ASSET)


def fixture(*, actual, expected, command=None, action=False, prior_fills=True, movements=()):
    observation = BrokerObservation(NOW, positions=(
        BrokerPosition(INSTRUMENT, Decimal(actual)),
        BrokerPosition(BrokerInstrument(security_id="unrelated", symbol="OTHER", broker_id=OTHER),
                       Decimal("5.25")),
    ))
    actions = SimpleNamespace(scalar_evidence_for=lambda ids: (SimpleNamespace(session=NOW.date()),)
                              if action else (), material_events_for=lambda **kwargs: ())
    return transfers.explain(transfers=movements, commands=(command,) if command else (),
        expected={"sec-1": Decimal(expected), "unrelated": Decimal(5)},
        observation=observation, eligible={"sec-1", "unrelated"}, actions=actions,
        prior_fills=lambda commands, cutoff: prior_fills)


@pytest.mark.parametrize("expected,actual,delta", [("0", "2.125", "2.125"), ("4.125", "2", "-2.125")])
def test_exact_fractional_transfer_restricts_only_the_affected_security(expected, actual, delta):
    event = transfers.Transfer(ASSET, Fraction(Decimal(delta)), NOW - timedelta(days=1))
    command = SimpleNamespace(instrument=INSTRUMENT, security_id="sec-1", state=CommandState.FILLED,
                              created_at=NOW - timedelta(days=2)) if expected != "0" else None
    assert fixture(actual=actual, expected=expected, command=command,
                   movements=(event,)).keys() == {"sec-1"}
    assert fixture(actual=actual, expected=expected, command=command,
                   movements=(replace(event, asset=OTHER),)) == {}


@pytest.mark.parametrize("fault", ["short", "amount", "late_order", "working", "linked_action", "late_fill"])
def test_in_kind_evidence_never_explains_an_unordered_or_conflicting_book(fault):
    event = transfers.Transfer(ASSET, Fraction(-1, 2), NOW - timedelta(days=1))
    expected = "2" if fault != "short" else "0.25"
    actual = "1.5" if fault != "amount" else "1.75"
    command = SimpleNamespace(instrument=INSTRUMENT, security_id="sec-1",
        state=CommandState.UNKNOWN if fault == "working" else CommandState.FILLED,
        created_at=NOW if fault == "late_order" else NOW - timedelta(days=2))
    assert fixture(actual=actual, expected=expected, command=command, movements=(event,),
                   action=fault == "linked_action", prior_fills=fault != "late_fill") == {}


def _native(kind="ACATS", **changes):
    return {"activity_type": kind, "ref_id": FIRST_REF, "event_id": "01" + "0" * 24,
            "status": "executed", "currency": "USD", "asset": {"id": ASSET},
            "qty": "0.125", "net_amount": "0", "settle_date": "2026-11-19",
            "executed_at": "2026-11-19T16:00:00Z", **changes}


@pytest.mark.parametrize("kind", sorted(transfers.KINDS))
def test_native_wire_requires_actual_zero_cash_and_exact_bound_identity(kind):
    day, at, qty = transfers.validate_event(_native(kind), native_account=ACCOUNT)
    assert at.date() == day and qty == Fraction(1, 8)
    for changes in ({"net_amount": "1"}, {"account_id": OTHER}, {"previous_id": OTHER},
                    {"qty": "0"}, {"status": "pending"}, {"ref_id": "unverified"}):
        with pytest.raises(transfers.SecurityTransferRefused):
            transfers.validate_event(_native(kind, **changes), native_account=ACCOUNT)


@pytest.mark.parametrize("broker", ["alpaca", "alpaca-live"])
def test_receipt_commitment_survives_restart_and_rejects_partial_restore(broker):
    import shutil

    import psycopg

    from sentinel import schema
    from tests.support.postgres import _EphemeralPostgres

    if not shutil.which("initdb"):
        pytest.skip("requires disposable PostgreSQL")
    pg = _EphemeralPostgres()
    try:
        pg.start()
        subject = broker, ACCOUNT, ACCOUNT
        with psycopg.connect(pg.sync_dsn) as conn:
            schema.ensure_schema(conn)
            first = transfers.record(conn, broker=broker, account_id=ACCOUNT,
                                     prior=None, native_account=subject, events=(_native(),))
        state = SimpleNamespace(broker=broker, account_id=ACCOUNT, security_transfer_commitment=first)
        with psycopg.connect(pg.sync_dsn) as conn:
            transfers.verify_restored(conn, state=state)
            assert transfers.record(conn, broker=broker, account_id=ACCOUNT, prior=first,
                                    native_account=subject, events=(_native(),)) == first
            with pytest.raises(transfers.SecurityTransferRefused, match="changed under its native reference"):
                transfers.record(conn, broker=broker, account_id=ACCOUNT, prior=first,
                                 native_account=subject, events=(_native(qty="2"),))
            conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                         (transfers.PREFIX + "%",))
            with pytest.raises(transfers.SecurityTransferRefused, match="disagree"):
                transfers.verify_restored(conn, state=state)
    finally:
        pg.stop()
