"""trade_type derived from ALPACA_BASE_URL — the paper/live gates must key off
the REAL endpoint, not a hardcoded label.

Previously every risk check sent trade_type='paper' regardless of endpoint, so
risk-service's LIVE_TRADING_ENABLED / PAPER_ONLY gates were decorative: pointing
ALPACA_BASE_URL at api.alpaca.markets traded real money straight through the
paper-labeled path. Now 'live' iff the host is the real Alpaca trading API —
going live requires flipping the risk-service gates too (a two-key turn).
"""
import re
from pathlib import Path

import pytest

from app.main import _current_trade_type, trade_type_for_base_url

MAIN_SRC = (Path(__file__).resolve().parents[2]
            / "services" / "trade-executor" / "app" / "main.py").read_text()


# ── the derivation rule ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://api.alpaca.markets",
    "https://api.alpaca.markets/",
    "https://api.alpaca.markets/v2",
    "HTTPS://API.ALPACA.MARKETS",           # case-insensitive host
])
def test_real_trading_endpoint_is_live(url):
    assert trade_type_for_base_url(url) == "live"


@pytest.mark.parametrize("url", [
    "https://paper-api.alpaca.markets",     # the default
    "http://alpaca-sim:8000",               # test-harness simulator
    "http://localhost:8006",
    "https://data.alpaca.markets",          # market-data host, not trading
    "",                                     # unset → executor no-ops anyway
    None,
])
def test_everything_else_is_paper(url):
    assert trade_type_for_base_url(url) == "paper"


def test_lookalike_hosts_are_not_live():
    # Only the exact host counts — a suffix/prefix lookalike must not flip the
    # gates open, and (more importantly) can't reach the real broker anyway.
    assert trade_type_for_base_url("https://api.alpaca.markets.evil.com") == "paper"
    assert trade_type_for_base_url("https://notapi.alpaca.markets") == "paper"


# ── env re-read per call (same philosophy as risk-service /check) ─────────────

def test_current_trade_type_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    assert _current_trade_type() == "paper"
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    assert _current_trade_type() == "live"
    monkeypatch.delenv("ALPACA_BASE_URL")
    assert _current_trade_type() == "paper"     # default is the paper endpoint


# ── source invariant: no risk payload may hardcode the label again ────────────

def test_no_hardcoded_trade_type_in_risk_payloads():
    assert '"trade_type": "paper"' not in MAIN_SRC
    assert '"trade_type": "live"' not in MAIN_SRC
    # both risk-check sites (immediate/deferred) go through the derivation
    assert len(re.findall(r'"trade_type": _current_trade_type\(\)', MAIN_SRC)) == 2
