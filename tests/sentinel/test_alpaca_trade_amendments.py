from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

import pytest

from sentinel import binding, schema
from sentinel.execution import alpaca_trade_amendments as amendments, broker_cash, journal
from sentinel.execution.alpaca import AlpacaExecutionBroker, MalformedBrokerPayload
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from tests.sentinel.live_authority_fixtures import live_fixture
from tests.sentinel.test_alpaca_boundary_overlay import (
    ACCOUNT_NUMBER, ACCOUNT_UUID, PAPER, Httpx, Response,
    account_payload, activity_event, full_order, pg, sse)
from tests.support.postgres import drop_public_tables


ORDER = "33333333-3333-3333-3333-333333333333"
ASSET = "44444444-4444-4444-4444-444444444444"
START = datetime.fromisoformat("2026-08-19T17:00:00+00:00")
UPPER = START + timedelta(days=1)


@pytest.fixture
def conn(pg):
    with feed_store.connect(pg.sync_dsn) as database:
        drop_public_tables(database)
        schema.ensure_schema(database)
        binding.bind(database, deployment_id="amendment-test", broker="alpaca",
                     broker_account_id=ACCOUNT_NUMBER)
        yield database


def _trade(code, *, prior=None, price="100", key="owned-key"):
    return activity_event(
        event_id=f"01J5R{code:021d}",
        ref_id=f"22222222-2222-2222-2222-{code:012d}",
        previous_id=prior["ref_id"] if prior else None,
        activity_type="TRD", qty="1.125", price=price,
        executed_at=START.isoformat(), net_amount="-112.50",
        details={
            "execution_type": "fill" if prior is None else "trade_correct",
            "order_id": ORDER, "side": "buy", "client_order_id": key,
        }, asset={"id": ASSET})


def _bust(code, *, prior, key="owned-key"):
    row = _trade(code, prior=prior, key=key)
    row["details"]["execution_type"] = "trade_bust"
    return row


def test_exact_native_lineage_corrects_fractional_trade_then_busts_once():
    original = _trade(1)
    correction = _trade(2, prior=original, price="101")
    bust = _bust(3, prior=correction)
    opts = dict(account_uuid=ACCOUNT_UUID, decode_fill=AlpacaExecutionBroker._activity_execution_fill)
    replacement, = amendments.active_native_fills((original, correction), **opts)
    assert replacement.activity_id == correction["ref_id"]
    assert replacement.quantity == Decimal("1.125")
    assert replacement.price == Decimal("101")
    assert amendments.active_native_fills((original, correction, bust), **opts) == ()
    for invalid in ((correction,), (original, correction, _bust(4, prior=original))):
        with pytest.raises(MalformedBrokerPayload, match="active owned execution"):
            amendments.active_native_fills(invalid, **opts)
    correction["details"]["asset_id"] = ORDER
    with pytest.raises(MalformedBrokerPayload, match="contradictory asset IDs"):
        amendments.active_native_fills((original, correction), **opts)


def _adapter(*events, order=None, live=None):
    routes = {
        "/v2/account": dict(account_payload(), created_at="2026-08-01T00:00:00Z"),
        "/v2beta1/events/activities": Response(text=sse(*events)),
    }
    if order is not None:
        routes["/v2/orders:by_client_order_id"] = order
    http = Httpx(routes=routes)
    broker = AssetIdAlpacaExecutionBroker(
        api_key="test", secret_key="test", base_url=PAPER if live is None else live.subject.base_url,
        http_provider=lambda: http, live_admission=live.admission if live else None,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}")
    return broker, http


def test_selected_cash_adapter_hands_off_typed_revision_without_double_counting():
    original = _trade(1)
    correction = _trade(2, prior=original, price="101")
    broker, http = _adapter(original, correction)
    observed = asyncio.run(broker.account_cash_activities(after=START, through=UPPER))
    assert observed.last_event_id == correction["event_id"]
    assert observed.activities == ()
    assert observed.trade_amendments == (amendments.parse(correction, account_uuid=ACCOUNT_UUID),)
    assert all(method == "GET" for method, *_ in http.calls)


@pytest.mark.parametrize("busted", [False, True])
@pytest.mark.parametrize("cache_original,live_namespace", [(True, False), (False, False), (False, True)])
def test_cash_cursor_and_owned_execution_update_share_one_transaction(conn, busted, cache_original, live_namespace):
    live = live_fixture(operations=("READ", "ACTIVITY_READ"), account_id=ACCOUNT_UUID) if live_namespace else None
    if live:
        conn.execute("DELETE FROM sentinel_account_binding")
        owner = binding.bind(conn, deployment_id=live.subject.deployment_id,
                             broker="alpaca-live", broker_account_id=ACCOUNT_UUID)
    else:
        owner = binding.require(conn)
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1", (START,))
    instrument = BrokerInstrument("SEC-AAPL", "AAPL", ASSET)
    quantity = Decimal("1.125")
    command = Command(
        CommandIdentity(owner.identity, "private-amendment-test", instrument.security_id),
        instrument, Side.BUY, quantity, state=CommandState.FILLED, broker_order_id=ORDER,
        filled_quantity=quantity, filled_average_price=Decimal("100"))
    journal.save_command(conn, command)
    original = _trade(1, key=command.client_key)
    if cache_original:
        journal.record_fills(conn, (AlpacaExecutionBroker._activity_execution_fill(original),))
    correction = (_bust(2, prior=original, key=command.client_key) if busted else
                  _trade(2, prior=original, price="101", key=command.client_key))
    order = full_order(
        id=ORDER, asset_id=ASSET, client_order_id=command.client_key,
        submitted_at=START.isoformat(), qty=str(quantity),
        status="canceled" if busted else "filled", filled_qty="0" if busted else str(quantity),
        filled_avg_price=None if busted else "101")
    broker, http = _adapter(original, correction, order=order, live=live)

    def ingest():
        return asyncio.run(broker_cash.ingest_account_cash(
            conn, broker_adapter=broker, broker=owner.broker, account_id=owner.broker_account_id, through=UPPER))

    def read_cursor():
        return broker_cash.load_activity_state(conn, broker=owner.broker, account_id=owner.broker_account_id)

    correct_order = dict(order)
    # The same-order endpoint can temporarily lag the activity cursor.
    order.update(status="filled", filled_qty=str(quantity), filled_avg_price="999")
    with pytest.raises(amendments.TradeAmendmentPending):
        ingest()
    conn.rollback()
    assert read_cursor() is None
    assert conn.execute(f"SELECT count(*) FROM {journal.ACTIVE_FILLS} f").fetchone() == (int(cache_original),)
    order.update(correct_order)
    staged = ingest()
    assert staged.trade_amendments_applied and staged.balance_total == 0
    conn.rollback()
    assert read_cursor() is None
    assert journal.load_commands(conn, owner.identity)[0].filled_quantity == quantity
    staged = ingest()
    conn.commit()

    expected_active = [] if busted else [(quantity, Decimal("101"))]
    assert conn.execute(f"SELECT quantity,price FROM {journal.ACTIVE_FILLS} f").fetchall() == expected_active
    assert conn.execute("SELECT count(*) FROM sentinel_fills").fetchone() == (1 if busted else 2,)
    updated, = journal.load_commands(conn, owner.identity)
    assert updated.filled_quantity == (0 if busted else quantity)
    assert updated.filled_average_price == (None if busted else Decimal("101"))
    assert updated.state is (CommandState.CANCELLED if busted else CommandState.FILLED)
    restored = read_cursor()
    assert restored.last_event_id == correction["event_id"]
    assert restored.trade_amendment_commitment == staged.trade_amendment_commitment
    assert not asyncio.run(amendments.apply(
        conn, broker_adapter=broker, broker=owner.broker, account_id=owner.broker_account_id,
        amendments=(amendments.parse(correction, account_uuid=ACCOUNT_UUID),)))
    amendments.verify_restored(conn, expected_commitment=restored.trade_amendment_commitment)
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE %s", (amendments.PREFIX + "%",))
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="disagrees with the cash cursor"):
        read_cursor()
    conn.rollback()


def _mixed_order(conn, *, live_namespace, cache_original, known_filled=Decimal(4)):
    live = live_fixture(operations=("READ", "ACTIVITY_READ"), account_id=ACCOUNT_UUID) if live_namespace else None
    if live:
        conn.execute("DELETE FROM sentinel_account_binding")
        owner = binding.bind(conn, deployment_id=live.subject.deployment_id,
                             broker="alpaca-live", broker_account_id=ACCOUNT_UUID)
    else:
        owner = binding.require(conn)
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1", (START,))
    instrument = BrokerInstrument("SEC-AAPL", "AAPL", ASSET)
    state = CommandState.PARTIALLY_FILLED if known_filled else CommandState.ACKNOWLEDGED
    average = Decimal(100) if known_filled else None
    command = Command(CommandIdentity(owner.identity, "mixed-prefix", instrument.security_id),
        instrument, Side.BUY, Decimal(10), state=state,
        broker_order_id=ORDER, filled_quantity=known_filled, filled_average_price=average)
    journal.save_command(conn, command)
    original = _quantity(_trade(1, key=command.client_key), "4")
    if cache_original:
        journal.record_fills(conn, (AlpacaExecutionBroker._activity_execution_fill(original),))
    order = full_order(id=ORDER, asset_id=ASSET, client_order_id=command.client_key, qty="10",
        submitted_at=START.isoformat(), status="partially_filled" if known_filled else "new",
        filled_qty=str(known_filled), filled_avg_price=str(average) if average else None)
    broker, http = _adapter(order=order, live=live)
    scope = {"broker": owner.broker, "account_id": owner.broker_account_id}
    return owner, command, broker, http, scope, order, original


def _quantity(event, value):
    event.update(qty=value, net_amount=str(-Decimal(value) * Decimal(event["price"])))
    return event


def _visible_rows(rows, params):
    after = params.get("since_id")
    through = params.get("until_id")
    return tuple(event for event in rows if (after is None or event["event_id"] >= after)
                 and (through is None or event["event_id"] <= through))


@pytest.mark.parametrize("live_namespace", [False, True])
@pytest.mark.parametrize("cache_original", [False, True])
def test_owned_ordinary_fills_before_and_after_correction_converge_atomically(conn, live_namespace, cache_original):
    owner, command, broker, http, scope, order, original = _mixed_order(
        conn, live_namespace=live_namespace, cache_original=cache_original)
    key = command.client_key
    earlier = _quantity(_trade(2, key=key), "2")
    revision = _quantity(_trade(3, key=key, prior=original), "3")
    later = _quantity(_trade(4, key=key), "4")
    source = [original]
    http.routes["/v2beta1/events/activities"] = lambda params: Response(text=sse(*_visible_rows(source, params)))

    def ingest(upper):
        return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker, through=upper, **scope))

    original_cursor = ingest(UPPER)
    conn.commit()
    assert original_cursor.last_event_id == original["event_id"]
    source.extend((earlier, revision, later))
    order["filled_qty"] = "9"
    state = ingest(UPPER + timedelta(seconds=1))
    assert state.trade_amendments_applied
    assert state.last_event_id == later["event_id"]
    conn.commit()

    assert conn.execute(f"SELECT quantity FROM {journal.ACTIVE_FILLS} active ORDER BY quantity").fetchall() == [
        (Decimal(2),), (Decimal(3),), (Decimal(4),)]
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (4,)
    revised, = journal.load_commands(conn, owner.identity)
    assert revised.filled_quantity == Decimal(9) and revised.state is CommandState.PARTIALLY_FILLED
    with feed_store.connect(conn.info.dsn) as restarted:
        saved = broker_cash.load_activity_state(restarted, **scope)
        assert saved.last_event_id == later["event_id"]
        assert saved.trade_amendment_commitment == state.trade_amendment_commitment
        amendments.verify_restored(restarted, expected_commitment=saved.trade_amendment_commitment)
    assert not ingest(UPPER + timedelta(seconds=2)).trade_amendments_applied
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (4,)


def test_predecessor_history_may_not_add_an_ordinary_fill_beyond_the_accepted_prefix(conn):
    owner, command, broker, http, scope, order, original = _mixed_order(
        conn, live_namespace=False, cache_original=True)
    revision = _quantity(_trade(2, key=command.client_key, prior=original), "3")
    later = _quantity(_trade(3, key=command.client_key), "6")
    source = [original]

    def stream(params):
        visible = _visible_rows(source, params)
        if params.get("until_id") == revision["event_id"] and later not in source:
            source.append(later)
        return Response(text=sse(*visible))

    http.routes["/v2beta1/events/activities"] = stream

    def ingest(upper):
        return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker, through=upper, **scope))

    old = ingest(UPPER)
    conn.commit()
    source.append(revision)
    order["filled_qty"] = "9"
    with pytest.raises(amendments.TradeAmendmentPending, match="await concordant exact order"):
        ingest(UPPER + timedelta(seconds=1))
    conn.commit()
    assert later in source
    assert broker_cash.load_activity_state(conn, **scope) == old
    assert journal.load_commands(conn, owner.identity)[0].filled_quantity == Decimal(4)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (1,)

    accepted = ingest(UPPER + timedelta(seconds=2))
    assert accepted.last_event_id == later["event_id"]
    assert journal.load_commands(conn, owner.identity)[0].filled_quantity == Decimal(9)
    assert conn.execute(f"SELECT quantity FROM {journal.ACTIVE_FILLS} active ORDER BY quantity").fetchall() == [
        (Decimal(3),), (Decimal(6),)]


def test_replayed_ordinary_fill_cannot_change_its_archived_native_cash(conn):
    owner, command, broker, http, scope, order, original = _mixed_order(
        conn, live_namespace=False, cache_original=True)
    revision = _quantity(_trade(2, key=command.client_key, prior=original), "3")
    source = [original]
    http.routes["/v2beta1/events/activities"] = lambda params: Response(text=sse(*_visible_rows(source, params)))

    def ingest(upper):
        return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker, through=upper, **scope))

    old = ingest(UPPER)
    conn.commit()
    # Both amounts fit rounding around the gross execution principal. Once
    # posted, the old exact cash amount is immutable.
    source[:] = [dict(original, net_amount="-399.999"), revision]
    order["filled_qty"] = "3"
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="changed a retained fill cash posting"):
        ingest(UPPER + timedelta(seconds=1))
    conn.commit()
    assert broker_cash.load_activity_state(conn, **scope) == old
    assert journal.load_commands(conn, owner.identity)[0].filled_quantity == Decimal(4)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (1,)


@pytest.mark.parametrize("live_namespace", [False, True])
@pytest.mark.parametrize("unreferenced_old_fill", [False, True])
def test_prior_cursor_history_can_supply_only_an_explicitly_consumed_ordinary_fill(
        conn, live_namespace, unreferenced_old_fill):
    owner, command, broker, http, scope, order, original = _mixed_order(
        conn, live_namespace=live_namespace, cache_original=False, known_filled=Decimal(0))
    older_unreferenced = _quantity(_trade(2, key=command.client_key), "1")
    watermark = activity_event(
        event_id=f"01J5R{3:021d}", ref_id="55555555-5555-5555-5555-555555555555",
        activity_type="CSD", net_amount="7")
    revision = _quantity(_trade(4, key=command.client_key, prior=original), "3")
    later = _quantity(_trade(5, key=command.client_key), "6")
    source = [original]
    if unreferenced_old_fill:
        source.append(older_unreferenced)
    source.append(watermark)
    cursored_reads = []

    def stream(params):
        visible = _visible_rows(source, params)
        if "since_id" in params:
            cursored_reads.extend(event["ref_id"] for event in visible)
        return Response(text=sse(*visible))

    http.routes["/v2beta1/events/activities"] = stream

    def ingest(upper):
        return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker, through=upper, **scope))

    old = ingest(UPPER)
    conn.commit()
    assert old.last_event_id == watermark["event_id"]
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (0,)
    source.extend((revision, later))
    order.update(status="filled" if unreferenced_old_fill else "partially_filled",
                 filled_qty="10" if unreferenced_old_fill else "9", filled_avg_price="100")
    if unreferenced_old_fill:
        with pytest.raises(amendments.TradeAmendmentPending, match="await concordant exact order"):
            ingest(UPPER + timedelta(seconds=1))
        conn.commit()
        assert broker_cash.load_activity_state(conn, **scope) == old
        assert journal.load_commands(conn, owner.identity)[0].filled_quantity == 0
        assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (0,)
    else:
        accepted = ingest(UPPER + timedelta(seconds=1))
        conn.commit()
        assert accepted.last_event_id == later["event_id"]
        assert journal.load_commands(conn, owner.identity)[0].filled_quantity == Decimal(9)
        assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone() == (3,)
        assert conn.execute(f"SELECT quantity FROM {journal.ACTIVE_FILLS} active ORDER BY quantity").fetchall() == [
            (Decimal(3),), (Decimal(6),)]
        amendments.verify_restored(conn, expected_commitment=accepted.trade_amendment_commitment)
    assert revision["ref_id"] in cursored_reads and original["ref_id"] not in cursored_reads
