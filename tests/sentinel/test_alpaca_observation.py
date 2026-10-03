from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from sentinel.feed.alpaca_observation import (
    action_symbols, admissible_history, bar_page_rows, cash_dividend,
    paired_month, structural_action_date, stock_split,
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
    source.action_affected,source.reset_after,source.splits = frozenset(),{},[]
    source.window = SimpleNamespace(
        start=date.fromisoformat(AXIS[0]), end=date.fromisoformat(AXIS[0]),
        sessions=[date.fromisoformat(AXIS[0])])
    calls = []

    def bars(symbols, first, last, adjustment):
        calls.append((symbols, first, last, adjustment))
        close = 105 if adjustment == "all" else 100
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
        ({"BIL"}, AXIS[0], AXIS[0], "split"),
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


@pytest.mark.parametrize('kind,old,new,ratio', [
    ('forward_splits', 1, 2, '2'), ('reverse_splits', 10, 1, '0.1'),
    ('forward_splits', 2, 3, '1.5')])
def test_split_terms_and_independent_prices_must_agree(kind, old, new, ratio):
    event = stock_split(kind, {'id':'split', 'symbol':'A', 'ex_date':AXIS[1],
        'old_rate':old, 'new_rate':new}, axis=set(AXIS))
    assert event['ratio'] == ratio
    multiplier = float(ratio)
    rows = [_row('A', AXIS[0], close=100, adjusted=100/multiplier),
            *[_row('A', day, close=100/multiplier, adjusted=100/multiplier)
              for day in AXIS[1:]]]
    kwargs = dict(axis=AXIS, symbols={'A'}, action_affected=frozenset(), pair_absent=set())
    assert admissible_history(rows, split_terms={('A',AXIS[1]):ratio}, **kwargs) == ({'A':AXIS[0]}, {})
    # Removing the action or corrupting its multiplier must fail corroboration.
    assert admissible_history(rows, **kwargs)[0] == {}
    assert admissible_history(rows, split_terms={('A',AXIS[1]):'4'}, **kwargs)[0] == {}


@pytest.mark.parametrize('terms', [
    {'old_rate':0,'new_rate':2}, {'old_rate':1,'new_rate':1},
    {'old_rate':2,'new_rate':1}, {'old_rate':1,'new_rate':'NaN'},
    {'old_rate':1}, {'old_rate':1,'new_rate':2,'new_symbol':'B'}])
def test_invalid_split_terms_are_never_guessed(terms):
    with pytest.raises(AlpacaTransportRefused):
        stock_split('forward_splits', {'id':'split','symbol':'A','ex_date':AXIS[1],**terms},
                    axis=set(AXIS))


def test_bil_split_price_domains_and_action_record_reach_execution():
    source = object.__new__(AlpacaSource)
    source.window = SimpleNamespace(start=date.fromisoformat(AXIS[0]),end=date.fromisoformat(AXIS[-1]),
        sessions=list(map(date.fromisoformat,AXIS)))
    source.action_affected,source.reset_after,source.tickers = frozenset(),{},[]
    source.splits = [{'id':'split','ticker':'BIL','date':AXIS[1],'ratio':'2'}]
    source.dividends = [{'id':'cash','ticker':'BIL','date':AXIS[-1],'rate':'0.25'}]
    def bars(symbols,first,last,adjustment):
        return {symbol:[_bar(day, 100 if adjustment=='raw' and day==AXIS[0] else
            52 if adjustment=='all' else 50) for day in AXIS] for symbol in symbols}, []
    source._bars = bars
    rows,*_ = source._benchmark_rows()
    bil = [row for row in rows if row['ticker']=='BIL']
    assert [row['close'] for row in bil] == [50,50,50]
    assert [row['closeunadj'] for row in bil] == [100,50,50]
    assert all(row['closeadj']==52 for row in bil)
    assert {event['action'] for event in source.reference_payload()['actions']} == {'split','dividend'}
    from decimal import Decimal
    from sentinel.execution.reconcile import reconcile_action_material
    events = reconcile_action_material(start=date.fromisoformat(AXIS[0]),
        end=date.fromisoformat(AXIS[-1]),
        action_rows=[(date.fromisoformat(AXIS[1]), '2', 'provider-split', 'split', 'BIL', None)],
        published_equity_rows=[], dispositions=[], equity_mapping=lambda *_:[],
        defensive_rows=[('SENTINEL:BIL',date.fromisoformat(row['date']),'BIL',
            row['close'],row['closeunadj'],date.fromisoformat(prior['date']),
            prior['close'],prior['closeunadj'],'run',1,'run',1)
            for prior,row in zip(bil,bil[1:])])
    assert events.events['SENTINEL:BIL'] == ((date.fromisoformat(AXIS[1]),Decimal('2.0')),)
    assert not events.unresolved_events
    source.splits = []
    with pytest.raises(AlpacaTransportRefused,match='corroborated'):
        source._benchmark_rows()
