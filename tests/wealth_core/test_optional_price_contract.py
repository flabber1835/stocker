from __future__ import annotations

from typing import get_args, get_type_hints

from stock_strategy_shared.wealth_core.engine import (
    SecurityBar,
    WealthCoreConfig,
    score_universe,
)
from stock_strategy_shared.wealth_core.feed import Feed, FeedError


def test_security_bar_declares_missing_source_observations():
    annotation = get_type_hints(SecurityBar)["closes"]
    element_type, = get_args(annotation)
    assert type(None) in get_args(element_type)


def test_optional_prices_are_rejected_at_every_signal_boundary():
    closes: list[float | None] = [100.0 + index for index in range(127)]
    closes[0] = None
    scored = score_universe(
        [SecurityBar("SEC", "SEC", "ISSUER", closes)], WealthCoreConfig())
    assert scored[0].momentum is None
    assert scored[0].volatility is None
    assert scored[0].score is None


def test_feed_monotonicity_does_not_scan_accumulated_sessions():
    class NoScanDict(dict):
        def __iter__(self):
            raise AssertionError("session history was scanned")

    feed = Feed({})
    feed._seen_sessions = NoScanDict({"2026-08-19": 0})
    feed._session_index = 0
    feed._last_session = "2026-08-19"
    feed._advance_session("2026-08-20")
    try:
        feed._advance_session("2026-08-19")
    except FeedError as exc:
        assert "duplicate" in str(exc)
    else:  # pragma: no cover - safety assertion
        raise AssertionError("duplicate session was accepted")
