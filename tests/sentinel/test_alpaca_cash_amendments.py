"""Private cash-only replacement tests. No provider credentials or connections."""
import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from sentinel import binding, schema
from sentinel.execution import alpaca_cash_amendments as revisions, broker_cash
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import Completeness
from sentinel.feed import store as feed_store
from tests.sentinel.test_alpaca_boundary_overlay import Httpx, PAPER, Response, pg, sse
from tests.sentinel.live_authority_fixtures import live_fixture
from tests.support.postgres import drop_public_tables


ACCOUNT = "11111111-1111-1111-1111-111111111111"
DAY = date(2026, 8, 19)


def _event(n, amount, *, kind="CSD", predecessor=None, **fields):
    marker = f"33333333-3333-3333-3333-{n:012d}"
    return {"account_id": ACCOUNT, "ref_id": marker, "event_id": f"01J5R{n:021d}",
            "activity_type": kind, "activity_subtype": None, "status": "executed",
            "currency": "USD", "settle_date": str(DAY), "qty": "0", "net_amount": amount,
            "details": {}, "previous_id": predecessor["ref_id"] if predecessor else None,
            **fields}


@pytest.fixture(params=("alpaca", "alpaca-live"))
def scope(pg, request):
    with feed_store.connect(pg.sync_dsn) as conn:
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        broker = request.param
        account_id = "paper-account" if broker == "alpaca" else ACCOUNT
        binding.bind(conn, deployment_id="revision-tests", broker=broker, broker_account_id=account_id)
        yield conn, {"broker": broker, "account_id": account_id}


def _install_original(conn, scope, event):
    return broker_cash._insert_activity(conn, **scope, activity=broker_cash.BrokerCashActivity(
        activity_id=event["ref_id"], activity_type=event["activity_type"],
        activity_date=DAY, net_amount=Decimal(event["net_amount"]), raw=event))


def _stage(conn, scope, *pairs):
    return revisions.stage(conn, tuple(revisions.decode(*pair, native_account_uuid=ACCOUNT) for pair in pairs),
                           **scope, native_account_uuid=ACCOUNT,
                           replacement_contract=revisions.FULL_REPLACEMENT)


def test_documented_cash_replacement_preserves_exact_identity_and_value():
    original = _event(1, "1.125", details={"request_id": "known"})
    revised = _event(2, "0", predecessor=original, details={"request_id": "known"},
                     settle_date="2026-08-19T00:00:00Z")
    pair = revisions.decode(original, revised, native_account_uuid=ACCOUNT)
    assert pair.before.amount == Decimal("1.125")
    assert pair.after.amount == 0 and pair.after.settlement_day == DAY
    for altered in ({"account_id": "foreign"}, {"settle_date": "2026-08-20"},
                    {"details": {}}, {"activity_type": "CSW"},
                    {"net_amount": None}, {"qty": "1"}, {"event_id": original["event_id"]}):
        with pytest.raises(revisions.CashRevisionRefused):
            revisions.decode(original, dict(revised, **altered), native_account_uuid=ACCOUNT)
    share_event = dict(revised, activity_type="DIV", activity_subtype="SDIV")
    with pytest.raises(revisions.CashRevisionRefused, match="cash-only"):
        revisions.decode(original, share_event, native_account_uuid=ACCOUNT)


def test_revision_chain_replay_rollback_and_restore(scope):
    conn, bound = scope
    initial = _event(1, "100")
    first = _event(2, "0", predecessor=initial)
    no_delta = _event(3, "0", predecessor=first)
    final = _event(4, "72.03", predecessor=no_delta)
    assert _install_original(conn, bound, initial)
    conn.commit()
    original = conn.execute("SELECT flow_id,session,amount,detail FROM sentinel_cash_flows").fetchone()
    all_pairs = ((initial, first), (first, no_delta), (no_delta, final))
    result = _stage(conn, bound, *all_pairs)
    assert result.accepted == 3
    assert [item.amount for item in result.differences] == [Decimal("-100"), Decimal("72.03")]
    assert all(broker_cash.broker_flow_is_external(item.flow_id, item.detail) for item in result.differences)
    assert all(";type=CORR;" in item.detail for item in result.differences)

    conn.rollback()
    revisions.verify_restored(conn, **bound, expected_commitment=None)
    assert conn.execute("SELECT flow_id,session,amount,detail FROM sentinel_cash_flows").fetchall() == [original]
    result = _stage(conn, bound, *all_pairs)
    conn.commit()
    assert conn.execute("SELECT sum(amount) FROM sentinel_cash_flows").fetchone() == (Decimal("72.03"),)
    replayed = _stage(conn, bound, *all_pairs)
    assert (replayed.accepted, replayed.differences, replayed.commitment) == (0, (), result.commitment)
    revisions.verify_restored(conn, **bound, expected_commitment=result.commitment)
    with pytest.raises(revisions.CashRevisionRefused, match="already consumed"):
        _stage(conn, bound, (initial, _event(5, "50", predecessor=initial)))
    with pytest.raises(revisions.CashRevisionRefused, match="changed"):
        _stage(conn, bound, (initial, dict(first, net_amount="1")))
    with pytest.raises(revisions.CashRevisionRefused, match="reordered"):
        _stage(conn, bound, *reversed(all_pairs))
    conn.execute("DELETE FROM sentinel_cash_flows WHERE flow_id=%s", (result.differences[-1].flow_id,))
    with pytest.raises(revisions.CashRevisionRefused, match="missing or conflicting cash difference"):
        revisions.verify_restored(conn, **bound, expected_commitment=result.commitment)
    conn.rollback()
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                 (revisions.PREFIX + "%:consumed:%",))
    with pytest.raises(revisions.CashRevisionRefused, match="disagree"):
        revisions.verify_restored(conn, **bound, expected_commitment=result.commitment)
    conn.rollback()


def test_internal_fee_revision_requires_qualified_amount_and_existing_zero_witness(scope):
    conn, bound = scope
    original = _event(1, "0", kind="FEE", activity_subtype="REG")
    amended = _event(2, "-1.01", kind="FEE", activity_subtype="REG", predecessor=original)
    pair = revisions.decode(original, amended, native_account_uuid=ACCOUNT)
    with pytest.raises(revisions.CashRevisionRefused, match="semantics are not qualified"):
        revisions.stage(conn, (pair,), **bound, native_account_uuid=ACCOUNT)
    with pytest.raises(revisions.CashRevisionRefused, match="retained ordinary"):
        _stage(conn, bound, (original, amended))
    assert not _install_original(conn, bound, original)
    result = _stage(conn, bound, (original, amended))
    effect, = result.differences
    assert effect.amount == Decimal("-1.01")
    assert not broker_cash.broker_flow_is_external(effect.flow_id, effect.detail)
    assert ";type=FEE;" not in effect.detail
    revisions.verify_restored(conn, **bound, expected_commitment=result.commitment)


def test_selected_activity_sse_applies_cash_replacement_and_publishes_cursor(scope):
    conn, bound = scope
    start = datetime.fromisoformat("2026-08-19T16:00:00+00:00")
    through = start + timedelta(days=1)
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1", (start,))
    ordinary = _event(1, "100", at=start.isoformat(), executed_at=start.isoformat())
    correction = _event(2, "97.25", predecessor=ordinary,
                        at=start.isoformat(), executed_at=start.isoformat())
    rows = [ordinary, correction]

    def activity(params):
        floor = params.get("since_id")
        ceiling = params.get("until_id")
        selected = [event for event in rows
                    if (floor is None or event["event_id"] >= floor)
                    and (ceiling is None or event["event_id"] <= ceiling)]
        return Response(text=sse(*selected))

    http = Httpx(routes={
        "/v2/account": {"id": ACCOUNT, "account_number": bound["account_id"],
                        "created_at": "2026-08-01T00:00:00Z"},
        "/v2beta1/events/activities": activity,
    })
    live = (live_fixture(operations=("READ", "ACTIVITY_READ"), account_id=ACCOUNT,
                         deployment_id="revision-tests") if bound["broker"] == "alpaca-live" else None)
    broker = AssetIdAlpacaExecutionBroker(api_key="offline-test", secret_key="offline-test",
        base_url=live.subject.base_url if live else PAPER, http_provider=lambda: http,
        live_admission=live.admission if live else None)
    result = asyncio.run(broker_cash.ingest_account_cash(
        conn, **bound, broker_adapter=broker, through=through))
    conn.commit()
    assert result.balance_total == Decimal("97.25")
    assert result.last_event_id == correction["event_id"]
    assert result.cash_revision_commitment
    assert dict(broker_cash.capture_activity_membership(conn, activity_state=result)).keys() == {
        broker_cash.broker_flow_id(**bound, activity_id=row["ref_id"]) for row in (ordinary, correction)
    }
    correction_two = _event(3, "98", predecessor=correction, at=start.isoformat(), executed_at=start.isoformat())
    rows.append(correction_two)
    next_state = asyncio.run(broker_cash.ingest_account_cash(
        conn, **bound, broker_adapter=broker, through=through + timedelta(seconds=1)))
    conn.commit()
    assert next_state.balance_total == Decimal("98")
    assert next_state.last_event_id == correction_two["event_id"]
    assert next_state.cash_revision_commitment != result.cash_revision_commitment
    assert broker_cash.load_activity_state(conn, **bound) == next_state
    revisions.verify_restored(conn, **bound, expected_commitment=next_state.cash_revision_commitment)
    assert all(method == "GET" for method, *_ in http.calls)


def test_refused_intake_rolls_back_staged_receipts_before_caller_commits_other_work(scope):
    conn, bound = scope
    start = datetime.fromisoformat("2026-08-19T16:00:00+00:00")
    through = start + timedelta(days=1)
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1", (start,))
    conn.commit()
    earlier = _event(1, "100")
    ordinary = _event(2, "5")
    valid = _event(3, "98", predecessor=earlier)
    bad_fork = _event(4, "97", predecessor=earlier)

    class CashReader:
        financial_activity_sse = True
        later = False

        async def account_cash_activities(self, *, after, through, since_event_id=None):
            event = ordinary if self.later else earlier
            pairs = ((earlier, valid), (earlier, bad_fork)) if self.later else ()
            return broker_cash.BrokerCashActivityBatch(
                activities=(broker_cash.BrokerCashActivity(event["ref_id"], "CSD", DAY,
                                                            Decimal(event["net_amount"]), event),),
                processed_through=through, completeness=Completeness.COMPLETE,
                last_activity_id=event["ref_id"],
                last_event_id=bad_fork["event_id"] if self.later else earlier["event_id"],
                native_account=(bound["broker"], bound["account_id"], ACCOUNT),
                cash_revisions=tuple(revisions.decode(*pair, native_account_uuid=ACCOUNT) for pair in pairs))

    broker = CashReader()

    def ingest(upper):
        return asyncio.run(broker_cash.ingest_account_cash(conn, **bound, broker_adapter=broker, through=upper))

    assert ingest(through).balance_total == Decimal("100")
    conn.rollback()
    assert broker_cash.load_activity_state(conn, **bound) is None
    assert conn.execute("SELECT COUNT(*) FROM sentinel_cash_flows").fetchone() == (0,)
    original = ingest(through)
    conn.commit()
    broker.later = True
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                 " VALUES ('test:unrelated-update',%s,'{}'::jsonb)", (DAY,))
    with pytest.raises(revisions.CashRevisionRefused, match="already consumed"):
        ingest(through + timedelta(seconds=1))
    conn.commit()
    assert conn.execute("SELECT 1 FROM sentinel_processed_sessions"
                        " WHERE cursor_name='test:unrelated-update'").fetchone() == (1,)
    assert broker_cash.load_activity_state(conn, **bound) == original
    assert conn.execute("SELECT amount FROM sentinel_cash_flows").fetchall() == [(Decimal("100"),)]
    revisions.verify_restored(conn, **bound, expected_commitment=None)
