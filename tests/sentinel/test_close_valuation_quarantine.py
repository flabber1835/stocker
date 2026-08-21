"""Quarantined broker-close valuation seam; no production promotion."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution.alpaca import (
    AlpacaExecutionBroker,
    MalformedBrokerPayload,
    PORTFOLIO_HISTORY_QUARANTINE_SEMANTICS,
    parse_portfolio_history_close,
)
from sentinel.execution import authority_gate
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.guarded import (
    BrokerOperation,
    ExecutionBrokerGuard,
    GuardedExecutionBroker,
    PaperPreparationGrant,
)
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import calendar


SESSION = date(2026, 8, 20)
STARTED = datetime(2026, 8, 21, 2, 1, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 8, 21, 2, 1, 1, tzinfo=timezone.utc)
IDENTITY = BrokerAccountIdentity("alpaca", "PA-1")
QUERY = (("cashflow_types", "ALL"), ("timeframe", "1D"))


def run(coro):
    return asyncio.run(coro)


def history_payload(timestamp=1_775_700_600, equity="100123.45"):
    return {
        "timestamp": [timestamp],
        "equity": [equity],
        "profit_loss": ["123.45"],
        "profit_loss_pct": ["0.0012"],
        "base_value": "100000.00",
        "timeframe": "1D",
    }


@pytest.mark.parametrize("wire_timestamp", [1_775_700_600, 1_775_700_600_000])
def test_parser_preserves_ambiguous_timestamp_without_guessing(wire_timestamp):
    result = parse_portfolio_history_close(
        history_payload(timestamp=wire_timestamp), identity=IDENTITY,
        requested_session=SESSION, request_started_at=STARTED,
        request_completed_at=COMPLETED, query=QUERY)

    assert result.equity == Decimal("100123.45")
    assert result.source_timestamp == wire_timestamp
    assert result.source_timestamp_unit is None
    assert result.valuation_at is None
    assert result.requested_session == SESSION
    assert result.semantics == PORTFOLIO_HISTORY_QUARANTINE_SEMANTICS


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must be an object"),
        ({**history_payload(), "timeframe": "15Min"}, "exactly '1D'"),
        ({**history_payload(), "timestamp": "1775700600"}, "must be arrays"),
        ({**history_payload(), "timestamp": []}, "exactly one"),
        ({**history_payload(), "timestamp": [True]}, "opaque integer"),
        ({**history_payload(), "equity": ["NaN"]}, "not finite"),
        ({**history_payload(), "equity": ["0"]}, "must be positive"),
        ({**history_payload(), "profit_loss": []}, "parallel"),
        ({**history_payload(), "profit_loss_pct": [False]}, "not a number"),
    ],
)
def test_parser_refuses_malformed_or_ambiguous_shapes(payload, message):
    with pytest.raises(MalformedBrokerPayload, match=message):
        parse_portfolio_history_close(
            payload, identity=IDENTITY, requested_session=SESSION,
            request_started_at=STARTED, request_completed_at=COMPLETED,
            query=QUERY)


def test_parser_refuses_invalid_request_bracket_and_query_identity():
    with pytest.raises(MalformedBrokerPayload, match="begins after"):
        parse_portfolio_history_close(
            history_payload(), identity=IDENTITY, requested_session=SESSION,
            request_started_at=COMPLETED, request_completed_at=STARTED,
            query=QUERY)
    with pytest.raises(MalformedBrokerPayload, match="unique"):
        parse_portfolio_history_close(
            history_payload(), identity=IDENTITY, requested_session=SESSION,
            request_started_at=STARTED, request_completed_at=COMPLETED,
            query=(("timeframe", "1D"), ("timeframe", "1D")))


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class _Http:
    def __init__(self, *, accounts, history):
        self.accounts = list(accounts)
        self.history = history
        self.calls = []
        owner = self

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
                owner.calls.append((path, dict(params or {})))
                if path == "/v2/account":
                    return _Response(owner.accounts.pop(0))
                if path == "/v2/account/portfolio/history":
                    return _Response(owner.history)
                raise AssertionError(path)

        self.AsyncClient = Client


def account(account_number="PA-1"):
    return {"account_number": account_number}


def alpaca(http):
    return AlpacaExecutionBroker(
        api_key="k", secret_key="s",
        base_url="https://paper-api.alpaca.markets",
        http_provider=lambda: http)


@pytest.mark.parametrize("session", [SESSION, date(2026, 11, 27)])
def test_alpaca_uses_exact_query_and_identity_sandwich(session):
    http = _Http(
        accounts=[account(), account()], history=history_payload())
    broker = alpaca(http)

    result = run(broker.account_close_valuation(session=session))

    opened, closed = calendar.session_window(session)
    assert http.calls == [
        ("/v2/account", {}),
        ("/v2/account/portfolio/history", {
            "start": opened.isoformat(),
            "end": closed.isoformat(),
            "timeframe": "1D",
            "intraday_reporting": "market_hours",
            "cashflow_types": "ALL",
        }),
        ("/v2/account", {}),
    ]
    assert result.identity.account_id == "PA-1"
    assert result.query == tuple(sorted(
        (key, str(value)) for key, value in http.calls[1][1].items()))
    assert result.request_started_at.tzinfo is not None
    assert result.request_started_at <= result.request_completed_at


def test_alpaca_refuses_account_flip_around_history_read():
    http = _Http(
        accounts=[account("PA-A"), account("PA-B")],
        history=history_payload())
    broker = alpaca(http)

    with pytest.raises(MalformedBrokerPayload, match="identity changed"):
        run(broker.account_close_valuation(session=SESSION))


def test_alpaca_parser_exists_but_guarded_production_capability_is_false():
    http = _Http(
        accounts=[account(), account()], history=history_payload())
    broker = alpaca(http)
    events = []

    async def before(_grant, operation):
        events.append(("before", operation))

    async def after(_grant, operation, _result):
        events.append(("after", operation))

    wrapped = GuardedExecutionBroker(
        inner=broker,
        grant=PaperPreparationGrant(
            expected_account="PA-1", decision_session=SESSION),
        guard=ExecutionBrokerGuard(
            before_read=before, after_read=after, before_mutation=before))

    assert broker.capabilities.account_close_valuation is False
    assert wrapped.supports_account_close_valuation is False
    with pytest.raises(AttributeError, match="no certified close valuation"):
        run(wrapped.account_close_valuation(session=SESSION))
    assert events == []
    assert http.calls == []


def test_authority_gate_classifies_close_valuation_as_account_bound_read():
    grant = PaperPreparationGrant(
        expected_account="PA-1", decision_session=SESSION)
    result = parse_portfolio_history_close(
        history_payload(), identity=IDENTITY, requested_session=SESSION,
        request_started_at=STARTED, request_completed_at=COMPLETED,
        query=QUERY)

    assert authority_gate._authority_operation(  # noqa: SLF001
        grant, BrokerOperation.ACCOUNT_CLOSE_VALUATION) == "PREPARE_READ"
    assert authority_gate._result_account(result) is IDENTITY  # noqa: SLF001


def test_simulator_exposes_only_explicit_deterministic_close_points():
    broker = SimulatedBroker()
    broker.seed_close_valuation(SESSION, "101234.56")
    events = []

    async def before(_grant, operation):
        events.append(("before", operation))

    async def after(_grant, operation, result):
        events.append(("after", operation, result.identity.account_id))

    wrapped = GuardedExecutionBroker(
        inner=broker,
        grant=PaperPreparationGrant(
            expected_account="SIM-ACCOUNT", decision_session=SESSION),
        guard=ExecutionBrokerGuard(
            before_read=before, after_read=after, before_mutation=before))

    result = run(wrapped.account_close_valuation(session=SESSION))

    _opened, closed = calendar.session_window(SESSION)
    assert result.equity == Decimal("101234.56")
    assert result.source_timestamp_unit == "epoch_seconds"
    assert result.valuation_at == closed
    assert events == [
        ("before", BrokerOperation.ACCOUNT_CLOSE_VALUATION),
        ("after", BrokerOperation.ACCOUNT_CLOSE_VALUATION, "SIM-ACCOUNT"),
    ]
