"""A stop must not close the episode before the sale is confirmed.

THE DEFECT. On a stop the pipeline set `closed_on` immediately, but the sell is
submitted for the NEXT OPEN. If that order is rejected, cancelled or partially
filled, the broker still holds the position while Stocker believes the episode
ended. The position then re-appears at the next sync, a NEW episode opens with a
fresh `opened_on` and a peak reset to the current price — and the stop is
silently looser than configured. A risk control failing toward less protection,
with nothing in the logs.

The fix: mark `pending_close_since` and leave `closed_on` NULL. The episode
closes through the normal two-sync confirmation once the position is really gone.

The subtlety that made the original shortcut tempting, and that these tests pin:
the re-entry block must STILL arm immediately. If it waited for the close, the
next build could re-buy the name the stop just sold. Both queries therefore key
on `COALESCE(closed_on, pending_close_since)`.
"""
from __future__ import annotations

import inspect
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _src(*parts) -> str:
    return open(os.path.join(ROOT, *parts)).read()


def _stop_write() -> str:
    """The UPDATE the stop path issues."""
    s = _src("services", "pipeline", "app", "main.py")
    i = s.index("for ticker, peak in sorted(plan.stopped.items()):")
    return s[i:i + 1400]


class TestTheStopDoesNotClose:
    def test_it_marks_pending_not_closed(self):
        w = _stop_write()
        assert "pending_close_since" in w, "the stop no longer marks a pending close"
        assert not re.search(r"SET\s+closed_on\s*=", w), (
            "the stop sets closed_on directly — a rejected sell then leaves the "
            "broker holding a position whose episode Stocker believes ended, and "
            "the re-opened episode resets the peak")

    def test_it_still_records_the_peak_that_triggered(self):
        """Without stop_peak there is nothing for the re-entry gate to read."""
        assert "stop_peak" in _stop_write()

    def test_it_still_records_the_reason(self):
        assert "trailing_stop" in _stop_write()


class TestTheBlockStillArmsImmediately:
    """The reason the shortcut was taken. If the block waited for the close, the
    next build could re-buy the name the stop just sold."""

    def test_the_pipeline_block_query_reads_pending_stops(self):
        s = _src("services", "pipeline", "app", "main.py")
        assert "COALESCE(closed_on, pending_close_since)" in s

    def test_the_builder_block_query_reads_pending_stops(self):
        s = _src("services", "portfolio-builder", "app", "main.py")
        assert "COALESCE(closed_on, pending_close_since)" in s

    def test_neither_query_requires_a_closed_episode(self):
        """`closed_on IS NOT NULL` was correct while the stop closed the episode
        and became a bug the moment it stopped doing so — the block would not arm
        until the sale confirmed."""
        for parts in (("services", "pipeline", "app", "main.py"),
                      ("services", "portfolio-builder", "app", "main.py")):
            s = _src(*parts)
            i = s.find("close_reason = 'trailing_stop'")
            assert i != -1, parts
            window = s[i:i + 400]
            assert "closed_on IS NOT NULL" not in window, (
                f"{parts[1]} still requires a CLOSED episode to arm the re-entry "
                f"block — a pending stop would leave the name buyable")
