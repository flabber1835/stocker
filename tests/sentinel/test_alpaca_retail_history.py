from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution.alpaca_history import HistoryLimits, read_account_history
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.native_activity import NativeActivityRefused
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.trading_environment import TradingEnvironment
from pydantic import ValidationError


ACCOUNT = "11111111-1111-1111-1111-111111111111"
ORDER_ID = "22222222-2222-2222-2222-222222222222"
ASSET = "33333333-3333-3333-3333-333333333333"
AFTER = datetime(2026, 10, 15, tzinfo=timezone.utc)
THROUGH = datetime(2026, 10, 17, tzinfo=timezone.utc)


def subject(environment=TradingEnvironment.LIVE):
    return ExecutionSubject(deployment_id="isolated-native-test", account_id=ACCOUNT,
        takeover_epoch=1, environment=environment,
        base_url="https://api.alpaca.markets" if environment is TradingEnvironment.LIVE else "https://paper-api.alpaca.markets")


def cash(native_id="cash-1", **changes):
    return dict({"id": native_id, "activity_type": "DIV", "date": "2026-10-01",
        "net_amount": "1.25", "created_at": "2026-10-16T12:00:00Z"}, **changes)


def fill(native_id="fill-1", **changes):
    return dict({"id": native_id, "activity_type": "FILL", "order_id": ORDER_ID,
        "qty": "1", "price": "10", "transaction_time": "2026-10-15T13:30:01Z"}, **changes)


def order(**changes):
    return dict({"id": ORDER_ID, "asset_id": ASSET, "side": "buy", "filled_qty": "2",
        "filled_avg_price": "10", "submitted_at": "2026-10-15T13:30:00Z",
        "filled_at": "2026-10-15T13:30:02Z", "account_id": ACCOUNT}, **changes)


class Client:
    def __init__(self, pages, *, exact_order=None, final_account=ACCOUNT):
        self.subject = subject()
        self.pages = iter(pages)
        self.order = exact_order or order()
        self.final_account = final_account
        self.verifications = 0
        self.calls = []

    async def verify_account(self):
        self.verifications += 1
        account = ACCOUNT if self.verifications == 1 else self.final_account
        return BrokerAccountIdentity("alpaca", account, raw={"id": account, "account_number": "TEST"})

    async def get(self, path, params=None):
        self.calls.append((path, deepcopy(params)))
        value = next(self.pages) if path == "/v2/account/activities" else self.order
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


async def read(client, **kwargs):
    return await read_account_history(client, after=AFTER, through=THROUGH, **kwargs)


@pytest.mark.asyncio
async def test_tied_times_full_page_and_empty_terminal_page_are_bounded():
    client = Client([[cash("one"), cash("two")], []])
    batch = await read(client, limits=HistoryLimits(page_size=2))
    assert batch.traversal_exhausted and batch.termination == "EMPTY_PAGE" and batch.projection_ready
    assert len(batch.cash_activities) == 2 and client.verifications == 2
    assert client.calls[1][1]["page_token"] == "two"
    assert client.calls[0][1]["after"] == AFTER.isoformat()
    assert not any((batch.provider_finality_proven, batch.settlement_proven,
        batch.restore_grade_recovery_proven, batch.live_authority_granted))


@pytest.mark.asyncio
async def test_late_publication_uses_created_bounds_not_business_date():
    client = Client([[cash(date="2001-01-01")]])
    batch = await read(client)
    assert batch.projection_ready and batch.cash_activities[0].activity_date.year == 2001
    assert "date" not in client.calls[0][1]


@pytest.mark.asyncio
async def test_exact_order_is_cached_and_native_partial_fills_agree_with_order():
    client = Client([[fill(), fill("fill-2", transaction_time="2026-10-15T13:30:02Z")]])
    batch = await read(client)
    assert batch.projection_ready and len(batch.fills) == 2
    assert [path for path, _ in client.calls].count("/v2/orders/" + ORDER_ID) == 1
    assert all(item.asset_id == ASSET for item in batch.fills)
    assert any(item.path == "/v2/orders/" + ORDER_ID for item in batch.reads)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutated", [order(filled_qty="1"), order(filled_avg_price="9"),
    order(asset_id="bad"), order(account_id="other")])
async def test_exact_order_identity_and_aggregate_gross_falsifiers(mutated):
    batch = await read(Client([[fill(), fill("fill-2")]], exact_order=mutated))
    assert not batch.projection_ready and batch.quarantines
    assert not batch.fills and not batch.cash_activities


@pytest.mark.asyncio
async def test_one_bad_event_prevents_partial_cash_or_fill_projection():
    batch = await read(Client([[cash(), fill(), cash("unknown", activity_type="NEW_ACTION", net_amount="0")]]))
    assert batch.traversal_exhausted and not batch.projection_ready
    assert len(batch.events) == 3 and len(batch.evidence) == 3
    assert not batch.cash_activities and not batch.fills
    assert batch.quarantines[0].reason_code == "UNSUPPORTED_NATIVE_ACTIVITY"


@pytest.mark.asyncio
async def test_restart_replay_does_not_reproject_and_changed_id_is_append_only():
    first = await read(Client([[cash()]]))
    restarted = await read(Client([[cash()]]), prior_evidence=first.evidence)
    assert restarted.projection_ready and restarted.replayed_native_ids
    assert not restarted.cash_activities and restarted.evidence == first.evidence
    changed = await read(Client([[cash(net_amount="2")]]), prior_evidence=first.evidence)
    assert not changed.projection_ready and len(changed.evidence) == 2
    assert changed.evidence[0] == first.evidence[0]
    assert any(item.reason_code == "CHANGED_NATIVE_ACTIVITY_ID" for item in changed.quarantines)


@pytest.mark.asyncio
async def test_prior_quarantine_survives_empty_restart_traversal():
    first = await read(Client([[cash(activity_type="NEW_ACTION", net_amount="0")]]))
    restarted = await read(Client([[]]), prior_evidence=first.evidence)
    assert restarted.traversal_exhausted and restarted.quarantines and not restarted.projection_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("pages,limits,termination", [
    ([[cash("one"), cash("two")]], HistoryLimits(page_size=2, max_pages=1), "PAGE_LIMIT"),
    ([[cash("one"), cash("two")], [cash("one"), cash("two")]], HistoryLimits(page_size=2), "REPEATED_ACTIVITY_CURSOR"),
    ([[cash(), cash()]], HistoryLimits(page_size=2), "REPEATED_ACTIVITY_CURSOR"),
    ([[cash(), cash("two")]], HistoryLimits(page_size=2, max_rows=1), "HISTORY_ROW_LIMIT"),
    ([{"unexpected": "object"}], HistoryLimits(), "MALFORMED_ACTIVITY_PAGE"),
    ([[cash()]], HistoryLimits(max_bytes=1), "HISTORY_BYTE_LIMIT"),
    ([RuntimeError("PRIVATE PROVIDER ERROR")], HistoryLimits(), "NATIVE_HISTORY_READ_REFUSED"),
])
async def test_incomplete_or_failed_traversal_never_projects(pages, limits, termination):
    client = Client(pages)
    batch = await read(client, limits=limits)
    assert batch.termination == termination and not batch.projection_ready
    assert not batch.fills and not batch.cash_activities
    assert "PRIVATE" not in batch.model_dump_json()
    assert client.verifications == 2


@pytest.mark.asyncio
async def test_changed_final_subject_refuses_all_projection():
    batch = await read(Client([[cash()]], final_account="44444444-4444-4444-4444-444444444444"))
    assert batch.termination == "CROSS_SUBJECT_ACCOUNT" and not batch.traversal_exhausted
    assert not batch.projection_ready and not batch.cash_activities


@pytest.mark.asyncio
async def test_cross_environment_prior_evidence_refuses_before_any_read():
    first = await read(Client([[cash()]]))
    client = Client([[]])
    client.subject = subject(TradingEnvironment.PAPER)
    with pytest.raises(NativeActivityRefused, match="CROSS_SUBJECT_EVIDENCE"):
        await read(client, prior_evidence=first.evidence)
    assert client.verifications == 0 and not client.calls


@pytest.mark.asyncio
async def test_expired_deadline_does_not_collect_or_project():
    client = Client([[cash()]])
    ticks = iter([0, 2, 2])
    batch = await read(client, limits=HistoryLimits(max_seconds=1.0), clock=lambda: next(ticks))
    assert batch.termination == "HISTORY_DEADLINE" and not batch.projection_ready
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("value,code", [("not-a-time", "INVALID_NATIVE_PUBLICATION_TIME"),
    ("2026-10-14T12:00:00Z", "PUBLICATION_TIME_OUTSIDE_REQUEST")])
async def test_publication_clock_guards_retain_quarantine(value, code):
    batch = await read(Client([[cash(created_at=value)]]))
    assert not batch.projection_ready and batch.quarantines[0].reason_code == code
    assert batch.evidence


@pytest.mark.asyncio
async def test_native_decimal_response_evidence_and_restart_remain_exact():
    payload = cash(net_amount=Decimal("1.250000000000000000001"))
    first = await read(Client([[payload]]))
    assert first.projection_ready
    assert first.cash_activities[0].net_amount == payload["net_amount"]
    restarted = await read(Client([[payload]]), prior_evidence=first.evidence)
    assert restarted.projection_ready and not restarted.cash_activities


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_deadline_configuration_refuses(value):
    with pytest.raises(ValidationError):
        HistoryLimits(max_seconds=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("ticks,code", [([0, float("nan"), float("nan")], "INVALID_HISTORY_CLOCK"),
    ([0, -1, -1], "HISTORY_CLOCK_REGRESSED")])
async def test_nonfinite_or_regressed_clock_cannot_collect(ticks, code):
    client = Client([[cash()]])
    values = iter(ticks)
    batch = await read(client, clock=lambda: next(values))
    assert batch.termination == code and not batch.projection_ready and not client.calls


@pytest.mark.asyncio
async def test_oversized_prior_evidence_refuses_before_network():
    first = await read(Client([[cash()]]))
    client = Client([[]])
    with pytest.raises(NativeActivityRefused, match="PRIOR_EVIDENCE_BYTE_LIMIT"):
        await read(client, prior_evidence=first.evidence, limits=HistoryLimits(max_bytes=1))
    assert client.verifications == 0 and not client.calls


@pytest.mark.asyncio
async def test_wrapper_account_label_cannot_hide_different_native_uuid():
    class RelabeledClient(Client):
        async def verify_account(self):
            self.verifications += 1
            return BrokerAccountIdentity("alpaca", ACCOUNT,
                raw={"id": "44444444-4444-4444-4444-444444444444"})
    client = RelabeledClient([[cash()]])
    batch = await read(client)
    assert batch.termination == "CROSS_SUBJECT_NATIVE_ACCOUNT" and not batch.projection_ready
    assert not client.calls and not batch.cash_activities


@pytest.mark.asyncio
async def test_mid_read_environment_change_refuses_projection():
    class ChangedClient(Client):
        async def get(self, path, params=None):
            value = await super().get(path, params)
            self.subject = subject(TradingEnvironment.PAPER)
            return value
    batch = await read(ChangedClient([[cash()]]))
    assert batch.termination == "SUBJECT_CHANGED_DURING_HISTORY" and not batch.projection_ready


@pytest.mark.asyncio
async def test_restart_native_order_identity_cannot_change_under_identical_activity():
    first = await read(Client([[fill()]]))
    assert first.projection_ready and first.evidence[0].order_identity_sha256
    changed = await read(Client([[fill()]], exact_order=order(
        asset_id="44444444-4444-4444-4444-444444444444")), prior_evidence=first.evidence)
    assert not changed.projection_ready and not changed.fills
    assert any(item.reason_code == "CHANGED_NATIVE_ORDER_IDENTITY" for item in changed.quarantines)
    assert changed.evidence[0] == first.evidence[0] and len(changed.evidence) == 2


@pytest.mark.asyncio
async def test_later_cumulative_order_updates_preserve_native_fill_identity():
    first = await read(Client([[fill()]], exact_order=order(filled_qty="1")))
    second = await read(Client([[fill()]], exact_order=order(filled_qty="2")), prior_evidence=first.evidence)
    assert first.projection_ready and second.projection_ready
    assert second.evidence == first.evidence and not second.fills


@pytest.mark.asyncio
async def test_giant_exact_order_average_refuses_before_fraction_arithmetic(monkeypatch):
    import sentinel.execution.alpaca_history as history
    def forbidden(*args):
        raise AssertionError("unbounded order average reached Fraction arithmetic")
    monkeypatch.setattr(history, "gross_matches_serialized_average", forbidden)
    monkeypatch.setattr(history, "partial_gross_leaves_positive_notional", forbidden)
    batch = await read(Client([[fill()]], exact_order=order(
        filled_qty="1", filled_avg_price="1E+1000000000")))
    assert not batch.projection_ready and not batch.fills
    assert any(item.reason_code == "FILL_ORDER_GROSS_MISMATCH" for item in batch.quarantines)


@pytest.mark.asyncio
async def test_aggregate_validation_time_is_inside_original_deadline(monkeypatch):
    import sentinel.execution.alpaca_history as history
    now = [0.0]
    original = history.gross_matches_serialized_average
    def slow_validation(*args):
        result = original(*args)
        now[0] = 2.0
        return result
    monkeypatch.setattr(history, "gross_matches_serialized_average", slow_validation)
    batch = await read(Client([[fill()]], exact_order=order(filled_qty="1")),
        limits=HistoryLimits(max_seconds=1.0), clock=lambda: now[0])
    assert batch.termination == "HISTORY_DEADLINE" and not batch.projection_ready
    assert not batch.fills
