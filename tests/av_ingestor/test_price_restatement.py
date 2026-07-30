"""av-ingestor: `adjusted_close` is a VINTAGE, and history must be re-based.

AV re-derives a ticker's whole adjusted series on every split and dividend. The
ingestor only ever wrote each bar once, on the day it landed:

    new_rows = [r for r in rows if date.fromisoformat(r["date"]) > latest_in_db]

so the `ON CONFLICT ... adjusted_close=EXCLUDED.adjusted_close` in _upsert_prices —
which is perfectly capable of re-basing history — never saw an old row. Every bar
stayed frozen at its own vintage, and anything measured ACROSS a corporate action
read a phantom move:

  - a 2:1 split looks like a ~50% crash to a trailing peak (a full liquidation)
  - momentum / low_volatility / near_high stay quietly wrong for that ticker
  - a reverse split understates a peak ~10x, silently disarming a stop

The wind tunnel cannot reproduce this (Sharadar SEP is uniformly restated), and
the simulator's truncation-invariance property cannot catch it either — truncation
removes ROWS, not VALUES. So there was no existing test that could have failed.

`select_rows_to_upsert` compares the newest bar we already hold against what AV
serves for that same date; a mismatch means the series was restated, and the whole
returned window is re-upserted to restore one uniform vintage.
"""
from datetime import date

import pytest

from app.main import RESTATE_REL_TOLERANCE, select_rows_to_upsert


def _bar(d: str, close: float, adj: float | None = None) -> dict:
    return {
        "date": d, "open": close, "high": close, "low": close,
        "close": close, "adjusted_close": close if adj is None else adj,
        "volume": 1_000_000,
    }


# A ticker we hold through 2026-03-03, then a 2:1 split on 03-04 restates history.
_WINDOW = [
    _bar("2026-03-01", 100.0),
    _bar("2026-03-02", 102.0),
    _bar("2026-03-03", 104.0),
    _bar("2026-03-04", 53.0),
]
_RESTATED = [
    _bar("2026-03-01", 100.0, 50.0),
    _bar("2026-03-02", 102.0, 51.0),
    _bar("2026-03-03", 104.0, 52.0),
    _bar("2026-03-04", 53.0, 53.0),
]


class TestNormalEvening:
    """The common path must stay cheap — a compact fetch returns ~100 days and the
    universe is ~5,900 tickers, so re-writing identical rows nightly is ~590k
    pointless upserts on a job that already runs for hours."""

    def test_only_newer_rows_when_the_vintage_is_unchanged(self):
        rows, restated = select_rows_to_upsert(
            _WINDOW, date(2026, 3, 3), stored_adj=104.0)
        assert restated is False
        assert [r["date"] for r in rows] == ["2026-03-04"]

    def test_nothing_to_write_when_already_current(self):
        rows, restated = select_rows_to_upsert(
            _WINDOW, date(2026, 3, 4), stored_adj=53.0)
        assert restated is False
        assert rows == []

    def test_cold_start_writes_everything(self):
        rows, restated = select_rows_to_upsert(_WINDOW, None, stored_adj=None)
        assert restated is False
        assert len(rows) == len(_WINDOW)


class TestRestatementDetected:
    def test_a_split_re_bases_the_whole_window(self):
        """THE regression. We stored 104.00 for 03-03; AV now serves 52.00 for the
        same date. Without re-basing, a peak spanning the split reads 104 → 53 and
        a trailing stop liquidates a position that did not move."""
        rows, restated = select_rows_to_upsert(
            _RESTATED, date(2026, 3, 3), stored_adj=104.0)
        assert restated is True
        assert len(rows) == len(_RESTATED), (
            "a restatement must re-upsert the FULL returned window, not just new bars"
        )
        assert [r["date"] for r in rows] == [r["date"] for r in _RESTATED]

    def test_a_reverse_split_is_also_detected(self):
        """Understating the peak is the quieter failure — the stop just never fires."""
        reverse = [_bar(r["date"], r["close"], r["adjusted_close"] * 10) for r in _WINDOW]
        rows, restated = select_rows_to_upsert(
            reverse, date(2026, 3, 3), stored_adj=104.0)
        assert restated is True
        assert len(rows) == len(reverse)

    def test_a_dividend_sized_change_is_detected(self):
        """~0.3% — far smaller than a split, and the cumulative drift is what makes
        a '15% stop' not actually 15%."""
        divd = [_bar(r["date"], r["close"], r["adjusted_close"] * 0.997) for r in _WINDOW]
        rows, restated = select_rows_to_upsert(
            divd, date(2026, 3, 3), stored_adj=104.0)
        assert restated is True


class TestTolerance:
    def test_float_noise_is_not_a_restatement(self):
        """Prices are NUMERIC(14,4); a sub-quantum difference must not trigger a
        full re-upsert of every ticker every night."""
        noisy = [_bar(r["date"], r["close"], r["adjusted_close"] + 1e-7) for r in _WINDOW]
        rows, restated = select_rows_to_upsert(
            noisy, date(2026, 3, 3), stored_adj=104.0)
        assert restated is False
        assert [r["date"] for r in rows] == ["2026-03-04"]

    def test_just_over_tolerance_is_a_restatement(self):
        stored = 104.0
        served = stored * (1 + RESTATE_REL_TOLERANCE * 2)
        rows, restated = select_rows_to_upsert(
            [_bar("2026-03-03", 104.0, served), _bar("2026-03-04", 105.0)],
            date(2026, 3, 3), stored_adj=stored)
        assert restated is True


class TestDegradedInputs:
    """Fail toward the OLD behaviour (write only new rows) — never toward a
    spurious full re-upsert of the entire universe."""

    def test_no_stored_value_falls_back_to_newer_only(self):
        rows, restated = select_rows_to_upsert(
            _RESTATED, date(2026, 3, 3), stored_adj=None)
        assert restated is False
        assert [r["date"] for r in rows] == ["2026-03-04"]

    @pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), None, "104.0"])
    def test_unusable_stored_value_falls_back(self, bad):
        rows, restated = select_rows_to_upsert(
            _RESTATED, date(2026, 3, 3), stored_adj=bad)
        assert restated is False

    def test_missing_overlap_row_falls_back(self):
        """A compact window that no longer reaches our newest bar (long dormancy)
        gives nothing to compare against."""
        rows, restated = select_rows_to_upsert(
            _WINDOW, date(2025, 1, 15), stored_adj=90.0)
        assert restated is False
        assert len(rows) == len(_WINDOW)  # all four are newer than 2025-01-15

    @pytest.mark.parametrize("bad_date", ["not-a-date", "", None, "2026-13-45"])
    def test_unparseable_dates_are_dropped_not_fatal(self, bad_date):
        rows, restated = select_rows_to_upsert(
            [_bar("2026-03-04", 53.0), {"date": bad_date, "adjusted_close": 1.0}],
            date(2026, 3, 3), stored_adj=104.0)
        assert restated is False
        assert [r["date"] for r in rows] == ["2026-03-04"]

    def test_row_missing_adjusted_close_is_not_a_restatement(self):
        rows, restated = select_rows_to_upsert(
            [{"date": "2026-03-03", "close": 104.0}, _bar("2026-03-04", 105.0)],
            date(2026, 3, 3), stored_adj=104.0)
        assert restated is False
        assert [r["date"] for r in rows] == ["2026-03-04"]


def test_returned_list_is_a_copy():
    """The caller mutates nothing, but returning the caller's own list invites a
    later aliasing bug."""
    src = list(_RESTATED)
    rows, restated = select_rows_to_upsert(src, date(2026, 3, 3), stored_adj=104.0)
    assert restated is True
    assert rows is not src
