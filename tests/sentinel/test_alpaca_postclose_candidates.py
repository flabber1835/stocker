"""Fail-closed Alpaca close/fill candidates pending real NAS acceptance."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution.alpaca import (
    ACCOUNT_LAST_EQUITY_SEMANTICS,
    ACCOUNT_LAST_EQUITY_SOURCE,
    ACCOUNT_LAST_EQUITY_TIMESTAMP_UNIT,
    ActivityCorrectionRequiresRecovery,
    AlpacaExecutionBroker,
    MalformedBrokerPayload,
)
from sentinel.execution.alpaca_remediation_final import (
    ACTIVITY_FILL_INTERVAL_SEMANTICS,
    ACTIVITY_FILL_INTERVAL_SOURCE,
)
from sentinel.execution.contract import Completeness
from sentinel.feed import calendar
from sentinel.trial_fills import FILL_INTERVAL_SEMANTICS


UTC = timezone.utc
PAPER = "https://paper-api.alpaca.markets"
SESSION = date(2026, 8, 20)
ACCOUNT_UUID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_NUMBER = "PA-ALPACA-1"
OBSERVED = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


class Response:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Httpx:
    def __init__(self, *, accounts, activity_events=()):
        self.accounts = list(accounts)
        self.activity_events = tuple(activity_events)
        self.calls = []
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, headers=None, params=None):
                del headers
                path = "/v2" + url.split("/v2", 1)[1]
                outer.calls.append((path, dict(params or {})))
                if path == "/v2/account":
                    if len(outer.accounts) > 1:
                        payload = outer.accounts.pop(0)
                    else:
                        payload = outer.accounts[0]
                    return Response(payload=payload)
                if path == "/v2beta1/events/activities":
                    text = "".join(
                        "data: " + json.dumps(event, sort_keys=True) + "\n\n"
                        for event in outer.activity_events)
                    return Response(text=text)
                raise AssertionError(path)

        self.AsyncClient = Client


def account(*, account_number=ACCOUNT_NUMBER, account_id=ACCOUNT_UUID,
            last_equity="100123.45"):
    return {
        "id": account_id,
        "account_number": account_number,
        "last_equity": last_equity,
    }


def trade_event(**changes):
    value = {
        "account_id": ACCOUNT_UUID,
        "at": "2026-08-20T19:15:00Z",
        "event_id": "01J5R000000000000000000001",
        "activity_type": "TRD",
        "activity_subtype": None,
        "ref_id": "22222222-2222-2222-2222-222222222222",
        "status": "executed",
        "executed_at": "2026-08-20T19:15:00Z",
        "settle_date": "2026-08-21",
        "qty": "2.5",
        "price": "100.25",
        "net_amount": "-250.625",
        "currency": "USD",
        "previous_id": None,
        "details": {
            "execution_type": "fill",
            "order_id": "order-1",
            "client_order_id": "sntl-0123456789abcdef0123",
            "asset_id": "asset-aapl",
            "symbol": "AAPL",
            "side": "buy",
        },
    }
    value.update(changes)
    return value


def adapter(http, *, observed=OBSERVED):
    return AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        http_provider=lambda: http,
        clock_provider=lambda: observed,
    )


def test_last_equity_candidate_maps_only_stable_t1_account_field():
    http = Httpx(accounts=[account(), account()])
    broker = adapter(http)

    result = run(broker.account_close_valuation(session=SESSION))
    _opened, official_close = calendar.session_window(SESSION)

    assert result.identity.account_id == ACCOUNT_NUMBER
    assert result.equity == Decimal("100123.45")
    assert result.valuation_at == official_close.astimezone(UTC)
    assert result.source_timestamp == int(official_close.timestamp())
    assert result.source_timestamp_unit == ACCOUNT_LAST_EQUITY_TIMESTAMP_UNIT
    assert result.source == ACCOUNT_LAST_EQUITY_SOURCE
    assert result.semantics == ACCOUNT_LAST_EQUITY_SEMANTICS
    assert result.raw["native_source_timestamp"] is None
    assert http.calls == [("/v2/account", {}), ("/v2/account", {})]
    assert broker.capabilities.account_close_valuation is False
    assert broker.candidate_previous_session_close_valuation is True
    assert broker.previous_session_close_nas_accepted is False


@pytest.mark.parametrize(
    ("observed", "message"),
    [
        (datetime(2026, 8, 21, 6, 59, tzinfo=UTC), "not mature"),
        (datetime(2026, 8, 21, 20, 0, tzinfo=UTC), "no longer has"),
    ],
)
def test_last_equity_candidate_refuses_outside_unambiguous_t1_window(
        observed, message):
    http = Httpx(accounts=[account(), account()])
    broker = adapter(http, observed=observed)

    with pytest.raises(MalformedBrokerPayload, match=message):
        run(broker.account_close_valuation(session=SESSION))
    assert http.calls == []


def test_last_equity_candidate_refuses_half_day_and_in_bracket_revision():
    half_day_http = Httpx(accounts=[account(), account()])
    half_day = adapter(
        half_day_http,
        observed=datetime(2026, 11, 30, 15, 0, tzinfo=UTC))
    with pytest.raises(MalformedBrokerPayload, match="half-day"):
        run(half_day.account_close_valuation(session=date(2026, 11, 27)))
    assert half_day_http.calls == []

    changed_http = Httpx(accounts=[
        account(last_equity="100123.45"),
        account(last_equity="100124.45"),
    ])
    with pytest.raises(MalformedBrokerPayload, match="changed inside"):
        run(adapter(changed_http).account_close_valuation(session=SESSION))


def test_activity_sse_candidate_is_complete_at_fixed_replayed_frontier():
    event = trade_event()
    http = Httpx(accounts=[account(), account(), account()],
                 activity_events=[event])
    broker = adapter(http)
    interval_start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    result = run(broker.candidate_fill_interval_evidence(
        session=SESSION, interval_start=interval_start))

    assert result.identity.account_id == ACCOUNT_NUMBER
    assert result.requested_session == SESSION
    assert result.interval_start == interval_start
    assert result.processed_through == OBSERVED
    assert result.completeness is Completeness.COMPLETE
    assert result.source == ACTIVITY_FILL_INTERVAL_SOURCE
    assert result.semantics == ACTIVITY_FILL_INTERVAL_SEMANTICS
    assert result.semantics != FILL_INTERVAL_SEMANTICS
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.activity_id == event["ref_id"]
    assert fill.broker_order_id == event["details"]["order_id"]
    assert fill.quantity == Decimal("2.5")
    assert fill.price == Decimal("100.25")
    assert fill.raw["event_id"] == event["event_id"]
    assert fill.raw["details"]["asset_id"] == "asset-aapl"
    assert result.raw["upper_event_id"] == event["event_id"]
    assert result.raw["fixed_frontier_replayed"] is True
    assert result.raw["late_publication_finality"] is False
    sse_calls = [call for call in http.calls
                 if call[0] == "/v2beta1/events/activities"]
    assert [call[1] for call in sse_calls] == [
        {"since": "1970-01-01T00:00:00+00:00",
         "until": OBSERVED.isoformat()},
        {"until_id": event["event_id"]},
    ]
    assert broker.capabilities.account_fill_interval_evidence is False
    assert broker.candidate_account_fill_interval_evidence is True
    assert broker.account_fill_interval_nas_accepted is False


@pytest.mark.parametrize(
    "changes",
    [
        {"previous_id": "11111111-2222-3333-4444-555555555555"},
        {"details": {
            **trade_event()["details"],
            "execution_type": "trade_bust",
        }},
    ],
)
def test_activity_sse_fill_candidate_refuses_correction_or_bust(changes):
    http = Httpx(accounts=[account(), account(), account()],
                 activity_events=[trade_event(**changes)])
    broker = adapter(http)

    with pytest.raises(ActivityCorrectionRequiresRecovery,
                       match="correction/bust"):
        run(broker.account_fill_interval_evidence(
            session=SESSION,
            interval_start=datetime(2026, 8, 20, 12, tzinfo=UTC)))


def test_activity_sse_fill_candidate_refuses_identity_flip():
    http = Httpx(accounts=[
        account(),
        account(),
        account(account_number="PA-OTHER", account_id="other-uuid"),
    ], activity_events=[trade_event()])
    broker = adapter(http)

    with pytest.raises(MalformedBrokerPayload, match="identity changed"):
        run(broker.account_fill_interval_evidence(
            session=SESSION,
            interval_start=datetime(2026, 8, 20, 12, tzinfo=UTC)))
