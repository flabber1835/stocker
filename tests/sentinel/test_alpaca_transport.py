"""Falsifiers for the GET-only bounded operational provider client."""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from sentinel.feed.alpaca_transport import (
    ACTION_URL, ASSETS, BAR_URL, AlpacaTransportRefused, Client,
)
from sentinel.feed.alpaca_source import _groups


class _Response(io.BytesIO):
    status = 200


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []
        self.methods = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        self.methods.append(request.get_method())
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return _Response(json.dumps(result).encode())


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")


def test_restricts_transport_to_fixed_get_only_data_endpoints():
    opener = _Opener([[]])
    client = Client(opener=opener)
    with pytest.raises(AlpacaTransportRefused, match="unsupported"):
        client.get("https://paper-api.alpaca.markets/v2/orders")
    assert not opener.urls
    value, proof = client.get(ASSETS, {"status": "active"})
    assert value == []
    assert proof["params"] == {"status": "active"}
    assert opener.methods == ["GET"]
    assert "test-key" not in repr(proof) and "test-secret" not in repr(proof)


def test_repeated_page_token_refuses_without_requerying_forever():
    opener = _Opener([
        {"bars": {"A": []}, "next_page_token": "same"},
        {"bars": {"A": []}, "next_page_token": "same"},
    ])
    with pytest.raises(AlpacaTransportRefused, match="repeated"):
        list(Client(opener=opener).pages(BAR_URL, {"symbols": "A"}, key="bars"))
    assert len(opener.urls) == 2


def test_retry_is_bounded_and_withholds_provider_body_and_credentials():
    error = HTTPError(BAR_URL, 503, "test-secret", {}, io.BytesIO(b"test-key"))
    opener = _Opener([error, error, error, error])
    with pytest.raises(AlpacaTransportRefused) as raised:
        Client(opener=opener, sleeper=lambda _delay: None).get(BAR_URL)
    assert len(opener.urls) == 4
    assert "test-secret" not in str(raised.value)
    assert "test-key" not in str(raised.value)


def test_action_pagination_accepts_distinct_pages():
    opener = _Opener([
        {"corporate_actions": {"cash_dividends": [{"symbol": "A"}]},
         "next_page_token": "next"},
        {"corporate_actions": {"cash_dividends": []}, "next_page_token": None},
    ])
    pages = list(Client(opener=opener).pages(
        ACTION_URL, {"limit": 1000}, key="corporate_actions"))
    assert len(pages) == 2
    assert pages[0][0]["cash_dividends"][0]["symbol"] == "A"


def test_basic_plan_requests_are_paced_and_429_retry_after_is_bounded():
    now, delays = [0.0], []
    def sleep(delay):
        delays.append(delay)
        now[0] += delay
    error = HTTPError(BAR_URL, 429, "rate limited", {"Retry-After": "3"},
                      io.BytesIO(b"hidden"))
    opener = _Opener([error, {"bars": {}, "next_page_token": None},
                      {"bars": {}, "next_page_token": None}])
    client = Client(opener=opener, sleeper=sleep, monotonic=lambda: now[0])
    client.get(BAR_URL)
    client.get(BAR_URL)
    assert delays == [3, 0.35]
    assert opener.methods == ["GET", "GET", "GET"]


def test_monthly_daily_bar_groups_fill_one_bounded_page_without_losing_symbols():
    symbols = {f"T{i:04d}" for i in range(801)}
    groups = list(_groups(symbols))
    assert [len(group) for group in groups] == [400, 400, 1]
    assert [symbol for group in groups for symbol in group] == sorted(symbols)
    assert max(len(group) * 23 for group in groups) <= 10000
