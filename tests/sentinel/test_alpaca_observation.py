from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from sentinel.feed.alpaca_observation import (
    action_symbols, admissible_history, bar_page_rows, cash_dividend,
    paired_month, structural_action_date,
)
from sentinel.feed.alpaca_transport import AlpacaTransportRefused
from sentinel.feed.alpaca_source import AlpacaSource


AXIS = ["2026-09-28", "2026-09-29", "2026-09-30"]


def _bar(day, close=100):
    return {"t": day + "T04:00:00Z", "o": close, "c": close, "v": 1000}


def _row(symbol, day, close=100, adjusted=100):
    return {"ticker": symbol, "date": day, "closeunadj": close,
            "adjusted_close": adjusted}


def test_action_quarantine_includes_all_named_participants():
    pages = [{"name_changes": [{"id": "one", "process_date": AXIS[0],
                                 "old_symbol": "OLD", "new_symbol": "NEW"}],
              "cash_dividends": [{"id": "two", "process_date": AXIS[1],
                                  "symbol": "DIV"}]}]
    affected, proof = action_symbols(pages, start=AXIS[0], end=AXIS[-1])
    assert affected == {"OLD", "NEW", "DIV"}
    assert proof["actions"] == 2


@pytest.mark.parametrize("bad", [
    {"spin_offs": [{"id": "x", "process_date": AXIS[0]}]},
    {"cash_dividends": [{"id": "x", "process_date": "2026-10-10", "symbol": "A"}]},
])
def test_action_without_usable_identity_or_process_date_refuses(bad):
    with pytest.raises(AlpacaTransportRefused):
        action_symbols([bad], start=AXIS[0], end=AXIS[-1])


def test_structural_event_uses_economic_date_and_refuses_unknown_date():
    assert structural_action_date("forward_splits", {
        "process_date": AXIS[0], "ex_date": "2026-09-27"}) == "2026-09-27"
    assert structural_action_date("forward_splits", {
        "process_date": "2026-09-27", "ex_date": AXIS[0]}) == AXIS[0]
    assert structural_action_date("forward_splits", {
        "process_date": AXIS[0]}) is None
    assert structural_action_date("name_changes", {
        "process_date": "2026-09-27"}) == "2026-09-27"


def test_cash_dividend_maps_only_usable_usd_event():
    event = {"id": "event", "symbol": "A", "foreign": False,
             "ex_date": AXIS[1], "rate": 0.25}
    assert cash_dividend(event, axis=set(AXIS))["rate"] == "0.25"
    assert cash_dividend({**event, "foreign": True}, axis=set(AXIS))["rate"] == "0.25"
    with pytest.raises(AlpacaTransportRefused):
        cash_dividend({**event, "foreign": None}, axis=set(AXIS))
    with pytest.raises(AlpacaTransportRefused):
        cash_dividend({**event, "currency": "EUR"}, axis=set(AXIS))
    with pytest.raises(AlpacaTransportRefused):
        cash_dividend({**event, "rate": 0}, axis=set(AXIS))
    assert cash_dividend({**event, "foreign": True,
                          "ex_date": "2025-01-01", "rate": 0},
                         axis=set(AXIS)) is None


def test_pairing_and_no_action_contiguous_history():
    raw = {"A": [_bar(day) for day in AXIS], "B": [_bar(AXIS[-1])]}
    adjusted = {"A": [_bar(day, 95) for day in AXIS], "B": [_bar(AXIS[-1])]}
    rows, absent = paired_month(raw, adjusted, symbols={"A", "B"}, sessions=set(AXIS))
    assert not absent
    admitted, reasons = admissible_history(rows, axis=AXIS, symbols={"A", "B"},
                                          action_affected=frozenset(), pair_absent=set())
    assert admitted == {"A": AXIS[0], "B": AXIS[-1]}
    assert reasons == {}


def test_benchmark_wire_uses_total_return_only_for_spy_and_bil():
    source = object.__new__(AlpacaSource)
    source.window = SimpleNamespace(
        start=date.fromisoformat(AXIS[0]), end=date.fromisoformat(AXIS[0]),
        sessions=[date.fromisoformat(AXIS[0])])
    calls = []

    def bars(symbols, first, last, adjustment):
        calls.append((symbols, first, last, adjustment))
        close = 100 if adjustment == "raw" else 105
        return {symbol: [_bar(AXIS[0], close)] for symbol in symbols}, []

    source._bars = bars
    rows, _, _, count = source._benchmark_rows()
    assert count == 2
    assert {row["ticker"] for row in rows} == {"SPY", "BIL"}
    assert all(row["close"] == 100 and row["closeunadj"] == 100
               and row["closeadj"] == 105 for row in rows)
    assert calls == [
        ({"SPY", "BIL"}, AXIS[0], AXIS[0], "raw"),
        ({"SPY", "BIL"}, AXIS[0], AXIS[0], "all"),
    ]


def test_retained_price_rows_are_globally_session_then_symbol_ordered():
    raw = {symbol: [_bar(day) for day in AXIS[:2]] for symbol in ("A", "B")}
    rows, absent = paired_month(raw, raw, symbols={"A", "B"}, sessions=set(AXIS[:2]))
    assert not absent
    assert [(row["date"], row["ticker"]) for row in rows] == [
        (AXIS[0], "A"), (AXIS[0], "B"), (AXIS[1], "A"), (AXIS[1], "B")]


def test_price_gaps_actions_and_adjustment_changes_exclude_security():
    rows = [_row("A", AXIS[0]), _row("B", AXIS[0]), _row("C", AXIS[0]),
            _row("A", AXIS[1]), _row("C", AXIS[1], adjusted=99),
            _row("A", AXIS[2]), _row("B", AXIS[2]), _row("C", AXIS[2])]
    admitted, reasons = admissible_history(rows, axis=AXIS, symbols={"A", "B", "C"},
                                          action_affected=frozenset({"A"}), pair_absent=set())
    assert admitted == {}
    assert reasons == {"adjustment_discontinuity": 1,
                       "noncontiguous_or_stale_prices": 1,
                       "reported_corporate_action": 1}


def test_price_page_refuses_duplicate_and_foreign_bars():
    with pytest.raises(AlpacaTransportRefused):
        bar_page_rows({"A": [_bar(AXIS[0]), _bar(AXIS[0])]},
                      symbols={"A"}, sessions=set(AXIS))
    with pytest.raises(AlpacaTransportRefused):
        bar_page_rows({"B": [_bar(AXIS[0])]}, symbols={"A"}, sessions=set(AXIS))


def test_raw_adjusted_missing_key_excludes_only_affected_symbol():
    rows, absent = paired_month({"A": [_bar(AXIS[0])], "B": [_bar(AXIS[0])]},
                                {"A": [_bar(AXIS[0])], "B": []},
                                symbols={"A", "B"}, sessions=set(AXIS))
    assert len(rows) == 1
    assert absent == {("B", AXIS[0])}


def test_post_event_history_resets_without_crossing_action():
    rows = [_row("A", day, adjusted=90 if day == AXIS[0] else 100)
            for day in AXIS]
    admitted, reasons = admissible_history(
        rows, axis=AXIS, symbols={"A"}, action_affected=frozenset(),
        pair_absent={("A", AXIS[0])}, reset_after={"A": AXIS[0]})
    assert admitted == {"A": AXIS[1]}
    assert reasons == {}
    admitted, reasons = admissible_history(
        rows, axis=AXIS, symbols={"A"}, action_affected=frozenset(),
        pair_absent={("A", AXIS[1])}, reset_after={"A": AXIS[0]})
    assert admitted == {}
    assert reasons == {"raw_adjusted_key_mismatch": 1}
