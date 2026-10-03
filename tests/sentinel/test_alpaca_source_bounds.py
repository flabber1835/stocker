"""Daily timestamp filters must work with free delayed SIP access."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from sentinel.feed.alpaca_source import AlpacaSource, _bounds


@pytest.mark.parametrize("first,last,start,end", [
    ("2026-10-02", "2026-10-02", "2026-10-02T00:00:00-04:00", "2026-10-02T00:00:00-04:00"),
    ("2026-01-02", "2026-01-05", "2026-01-02T00:00:00-05:00", "2026-01-05T00:00:00-05:00"),
    ("2026-03-06", "2026-03-09", "2026-03-06T00:00:00-05:00", "2026-03-09T00:00:00-04:00"),
    ("2026-10-30", "2026-11-02", "2026-10-30T00:00:00-04:00", "2026-11-02T00:00:00-05:00"),
])
def test_daily_bounds_use_inclusive_labels_with_each_sessions_offset(first, last, start, end):
    assert _bounds(first, last) == (start, end)


@pytest.mark.parametrize("adjustment", ["raw", "split", "all"])
def test_source_final_acquisition_includes_final_bar_without_recent_sip_request(monkeypatch, adjustment):
    # A source-final operation at 23:45 must not request the future 23:59:59.
    now = datetime.fromisoformat("2026-10-02T23:45:00-04:00")
    final_bar = {"t": "2026-10-02T04:00:00Z", "o": 100, "c": 101, "v": 1000}

    class DelayedSip:
        def pages(self, url, params, *, key):
            end = datetime.fromisoformat(params["end"])
            assert end <= now - timedelta(minutes=15), "recent SIP interval requested"
            assert params["feed"] == "sip" and params["timeframe"] == "1Day"
            assert params["adjustment"] == adjustment
            assert datetime.fromisoformat(params["start"]) <= datetime.fromisoformat(final_bar["t"]) <= end
            yield {"A": [final_bar]}, {"status": 200}

    monkeypatch.setattr("sentinel.feed.alpaca_source.jobs.heartbeat", lambda *args, **kwargs: None)
    source = object.__new__(AlpacaSource)
    source.window = SimpleNamespace(end="2026-10-02")
    source.client, source.conn, source.lease = DelayedSip(), None, None
    bars, _ = source._bars({"A"}, "2026-10-01", "2026-10-02", adjustment)
    assert bars == {"A": [final_bar]}
