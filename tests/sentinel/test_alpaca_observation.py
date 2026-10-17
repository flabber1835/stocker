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


def test_cash_knowledge_keeps_native_processing_and_payment_dates():
    wire = {'id': 'renamed-native', 'symbol': 'UNRELATED', 'foreign': False,
            'ex_date': AXIS[0], 'process_date': AXIS[-1], 'payable_date': '2026-10-07',
            'record_date': AXIS[0], 'rate': '.205'}
    value = cash_dividend(wire, axis=set(AXIS))
    assert value['date'] == AXIS[0]
    assert value['process_date'] == AXIS[-1]
    assert value['payable_date'] == '2026-10-07'
    assert value['id'] == 'renamed-native' and len(value['terms_sha256']) == 64


@pytest.mark.parametrize('rate', ['1e500', '1e-500'])
def test_cash_rate_must_fit_canonical_shadow_domains(rate):
    wire = dict(id='cash-domain', symbol='UNRELATED', foreign=False,
                ex_date=AXIS[0], process_date=AXIS[-1], rate=rate)
    with pytest.raises(AlpacaTransportRefused):
        cash_dividend(wire, axis=set(AXIS))


@pytest.mark.parametrize('rate', [None, '1e500', 'NaN', '-0.2'])
def test_unresolved_cash_does_not_quarantine_valid_price_history(rate):
    source = object.__new__(AlpacaSource)
    # This parser fixture has no database or preceding publication. Complete
    # its explicitly isolated source context without weakening runtime lookup.
    source._previous_identity = lambda: None
    source.window = SimpleNamespace(start=date.fromisoformat(AXIS[0]), end=date.fromisoformat(AXIS[-1]),
                                    sessions=list(map(date.fromisoformat, AXIS)))
    source.selected = [{'ticker': 'RENAMED'}]
    wire = {'id': 'pending', 'symbol': 'RENAMED', 'foreign': False,
            'ex_date': AXIS[0], 'process_date': AXIS[-1], 'rate': rate}
    source.client = SimpleNamespace(pages=lambda *a, **kw: [({'cash_dividends': [wire]}, {})])
    result, *_ = source._action_rows()
    assert result['affected'] == [] and result['dividends'] == []
    assert result['pending_cash'][0]['id'] == 'pending'


def test_pairing_and_no_action_contiguous_history():
    raw = {"A": [_bar(day) for day in AXIS], "B": [_bar(AXIS[-1])]}
    adjusted = {"A": [_bar(day, 95) for day in AXIS], "B": [_bar(AXIS[-1])]}
    rows, absent = paired_month(raw, adjusted, symbols={"A", "B"}, sessions=set(AXIS))
    assert not absent
    admitted, reasons = admissible_history(rows, axis=AXIS, symbols={"A", "B"},
                                          action_affected=frozenset(), pair_absent=set())
    assert admitted == {"A": AXIS[0], "B": AXIS[-1]}
    assert reasons == {}


def test_old_gap_retains_only_clean_tail_and_never_fills_missing_prices():
    from sentinel.feed import calendar
    axis = calendar.previous_sessions('2026-09-30', 300)
    rows = [_row('A', day) for i, day in enumerate(axis) if i != 100]
    admitted, reasons = admissible_history(rows, axis=axis, symbols={'A'},
        action_affected=frozenset(), pair_absent=set())
    assert admitted == {'A': axis[101]} and reasons == {}
    assert len([row for row in rows if row['date'] >= admitted['A']]) == 199


def test_old_basis_break_retains_clean_candidate_tail():
    from sentinel.feed import calendar
    axis = calendar.previous_sessions('2026-09-30', 300)
    rows = [_row('A', day, adjusted=50 if i < 40 else 100)
            for i, day in enumerate(axis)]
    admitted, reasons = admissible_history(rows, axis=axis, symbols={'A'},
        action_affected=frozenset(), pair_absent=set())
    assert admitted == {'A': axis[40]} and reasons == {}
    assert len([row for row in rows if row['date'] >= admitted['A']]) == 260


def test_old_adjustment_anomaly_does_not_poison_tail_after_later_gap():
    rows = [_row('A', AXIS[0], adjusted=20), _row('A', AXIS[2])]
    assert admissible_history(rows, axis=AXIS, symbols={'A'},
        action_affected=frozenset(), pair_absent={('A', AXIS[0])}) == ({'A': AXIS[2]}, {})


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
    assert admitted == {'B': AXIS[2], 'C': AXIS[2]}
    assert reasons == {"reported_corporate_action": 1}


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
    assert admissible_history(rows, **kwargs)[0] == {'A': AXIS[1]}
    assert admissible_history(rows, split_terms={('A',AXIS[1]):'4'}, **kwargs)[0] == {}


@pytest.mark.parametrize('terms', [
    {'old_rate':0,'new_rate':2}, {'old_rate':1,'new_rate':1},
    {'old_rate':2,'new_rate':1}, {'old_rate':1,'new_rate':'NaN'},
    {'old_rate':1}, {'old_rate':1,'new_rate':2,'new_symbol':'B'}])
def test_invalid_split_terms_are_never_guessed(terms):
    with pytest.raises(AlpacaTransportRefused):
        stock_split('forward_splits', {'id':'split','symbol':'A','ex_date':AXIS[1],**terms},
                    axis=set(AXIS))


def test_cent_rounded_reverse_split_prices_keep_exact_terms_without_false_exclusion():
    rows = [_row('A',AXIS[0],close=.8665,adjusted=13.86),
            _row('A',AXIS[1],close=.6285,adjusted=10.06),
            _row('A',AXIS[2],close=10,adjusted=10)]
    kwargs = dict(axis=AXIS,symbols={'A'},action_affected=frozenset(),pair_absent=set())
    terms = {('A',AXIS[2]):'0.0625'}
    assert admissible_history(rows,split_terms=terms,**kwargs)[0] == {'A':AXIS[0]}
    assert admissible_history(rows,**kwargs)[0] == {'A': AXIS[2]}
    assert admissible_history(rows,split_terms={('A',AXIS[2]):'0.1'},**kwargs)[0] == {}
    rows[1]['adjusted_close'] += .02
    assert admissible_history(rows,split_terms=terms,**kwargs)[0] == {}


def test_rounding_cannot_hide_material_unknown_split_in_low_price_history():
    rows = [_row('A',AXIS[0],close=.001,adjusted=.01),
            _row('A',AXIS[1],close=.0005,adjusted=.01),
            _row('A',AXIS[2],close=.01,adjusted=.01)]
    assert admissible_history(rows,axis=AXIS,symbols={'A'},action_affected=frozenset(),
        pair_absent=set(),split_terms={('A',AXIS[2]):'0.1'})[0] == {}


def test_bil_split_price_domains_and_action_record_reach_execution():
    source = object.__new__(AlpacaSource)
    source.identity_bindings = []
    source.window = SimpleNamespace(start=date.fromisoformat(AXIS[0]),end=date.fromisoformat(AXIS[-1]),
        sessions=list(map(date.fromisoformat,AXIS)))
    source.action_affected,source.reset_after,source.tickers = frozenset(),{},[]
    source.splits = [{'id':'split','ticker':'BIL','date':AXIS[1],'ratio':'2'}]
    source.dividends = [{'id':'cash','ticker':'BIL','date':AXIS[-1],'rate':'0.25'}]
    source.pending_cash = []
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


def test_full_admission_renews_original_lease_before_long_pass_finishes(monkeypatch):
    from types import SimpleNamespace
    from sentinel.feed import calendar, rolling_builder, rolling_jobs, rolling_store, rolling_work

    axis = calendar.previous_sessions('2026-09-14', 20)
    lease = SimpleNamespace(job_id='paced-admission', owner='original-owner', fence=1)
    clock = [0]
    lease_until = [600]
    heartbeats = []

    def heartbeat(conn, current, *, lease_seconds):
        assert current is lease and current.owner == 'original-owner' and current.fence == 1
        assert lease_seconds == 600
        if clock[0] >= lease_until[0]:
            raise rolling_jobs.JobRefused('original lease expired during admission')
        assert clock[0] < 2000
        lease_until[0] = min(2000, clock[0] + lease_seconds)
        heartbeats.append(clock[0])

    def slow_rows(*args, **kwargs):
        for day in axis:
            clock[0] += 40
            yield {'ticker':'ABC', 'date':day, 'adjusted_close':10., 'closeunadj':10.}

    class AdmissionComplete(Exception):
        pass

    def complete(**counts):
        assert counts['selected'] == counts['admitted'] == 1
        heartbeat(None, lease, lease_seconds=600)
        raise AdmissionComplete

    source = SimpleNamespace(selected=[{'ticker':'ABC','asset_id':'permanent-id'}],
        identity_bindings=[], dividends=[], price_manifests={}, action_affected=frozenset(),
        pair_absent=set(), reset_after={}, split_terms=lambda:{})
    monkeypatch.setattr(rolling_builder, '_alpaca_rows', slow_rows)
    monkeypatch.setattr(rolling_builder, 'require_alpaca_population', complete)
    monkeypatch.setattr(rolling_jobs, 'heartbeat', heartbeat)
    monkeypatch.setattr(rolling_store, 'BATCH_SIZE', 5)
    with rolling_work.renewing(lambda:heartbeat(None, lease, lease_seconds=600)):
        with pytest.raises(AdmissionComplete):
            rolling_builder.build_alpaca(None, lease, SimpleNamespace(window=SimpleNamespace(sessions=axis)), source)
    assert clock[0] == 800 and len(heartbeats) >= 5
    assert max(b-a for a,b in zip(heartbeats,heartbeats[1:])) <= 200


@pytest.mark.parametrize('refusal', ('fence', 'deadline'))
def test_admission_pacing_preserves_fence_deadline_and_transaction(monkeypatch, refusal):
    from types import SimpleNamespace
    from sentinel.feed import calendar, rolling_builder, rolling_jobs, rolling_store

    axis = calendar.previous_sessions('2026-09-14', 20)
    lease = SimpleNamespace(job_id='guarded-admission', owner='original-owner', fence=1)
    clock = [0]
    current_fence = [1]
    closed = []
    commits = []
    checked = []
    conn = SimpleNamespace(commit=lambda:commits.append(True))

    def heartbeat(connection, supplied, *, lease_seconds):
        assert connection is conn and supplied is lease and lease_seconds == 600
        checked.append(clock[0])
        if supplied.fence != current_fence[0]:
            raise rolling_jobs.JobRefused('worker fence lost')
        if refusal == 'deadline' and clock[0] >= 500:
            raise rolling_jobs.JobDeadlineExceeded('original deadline exhausted')

    def slow_rows(*args, **kwargs):
        try:
            for index, day in enumerate(axis):
                clock[0] += 40
                if refusal == 'fence' and index == 5:
                    current_fence[0] = 2
                yield {'ticker':'ABC','date':day,'adjusted_close':10.,'closeunadj':10.}
        finally:
            closed.append(True)

    source = SimpleNamespace(selected=[{'ticker':'ABC','asset_id':'permanent-id'}],
        identity_bindings=[], dividends=[], price_manifests={}, action_affected=frozenset(),
        pair_absent=set(), reset_after={}, split_terms=lambda:{})
    monkeypatch.setattr(rolling_builder, '_alpaca_rows', slow_rows)
    monkeypatch.setattr(rolling_builder, 'require_alpaca_population', lambda **_:pytest.fail('admission advanced after lost authority'))
    monkeypatch.setattr(rolling_jobs, 'heartbeat', heartbeat)
    monkeypatch.setattr(rolling_store, 'BATCH_SIZE', 5)
    error = rolling_jobs.JobRefused if refusal == 'fence' else rolling_jobs.JobDeadlineExceeded
    with pytest.raises(error):
        rolling_builder.build_alpaca(conn, lease, SimpleNamespace(window=SimpleNamespace(sessions=axis)), source)
    assert clock[0] == (400 if refusal == 'fence' else 600)
    assert checked and not commits and closed == [True]


def test_admission_error_closes_underlying_price_cursor_without_commit(monkeypatch):
    from types import SimpleNamespace
    from sentinel.feed import alpaca_observation, rolling_builder, rolling_jobs

    closed = []
    commits = []
    def rows(*args, **kwargs):
        try:
            yield {'ticker':'ABC','date':'2026-09-14','adjusted_close':10.,'closeunadj':10.}
        finally:
            closed.append(True)
    def consume(rows, **kwargs):
        next(rows)
        raise ValueError('inconsistent observed price')
    source = SimpleNamespace(selected=[{'ticker':'ABC','asset_id':'permanent-id'}],
        identity_bindings=[], dividends=[], price_manifests={}, action_affected=frozenset(),
        pair_absent=set(), reset_after={}, split_terms=lambda:{})
    monkeypatch.setattr(rolling_builder, '_alpaca_rows', rows)
    monkeypatch.setattr(alpaca_observation, 'admissible_history', consume)
    monkeypatch.setattr(rolling_jobs, 'heartbeat', lambda *args, **kwargs:None)
    with pytest.raises(ValueError) as retained_traceback:
        rolling_builder.build_alpaca(SimpleNamespace(commit=lambda:commits.append(True)),
            SimpleNamespace(job_id='failed-admission'),
            SimpleNamespace(window=SimpleNamespace(sessions=['2026-09-14'])), source)
    assert retained_traceback.value and closed == [True] and not commits


@pytest.mark.parametrize('start,reset,absences', [
    (0,None,[-1]), (0,None,[1,4]), (0,None,[12]),
    (3,None,[1,2]), (3,None,[1,7]),
    (5,4,[1,4]), (5,4,[1,5]), (5,4,[12]),
    (None,None,[-1]), (None,None,[2]),
])
def test_absence_index_matches_original_scan_across_tail_and_reset_boundaries(start, reset, absences):
    from datetime import date,timedelta
    from sentinel.feed import calendar
    from sentinel.feed.alpaca_observation import admissible_history

    axis = calendar.previous_sessions('2026-09-14', 12)
    date_for = lambda index: ((date.fromisoformat(axis[0])-timedelta(days=1)).isoformat()
        if index == -1 else (date.fromisoformat(axis[-1])+timedelta(days=1)).isoformat()
        if index == 12 else axis[index])
    pairs = {('ABC',date_for(index)) for index in absences} | {('OTHER',axis[-1])}
    reset_day = axis[reset] if reset is not None else ''
    first = axis[start] if start is not None else axis[0]
    original_scan = any(symbol == 'ABC' and day >= first and day > reset_day for symbol,day in pairs)
    rows = [] if start is None else [
        {'ticker':'ABC','date':day,'adjusted_close':10.,'closeunadj':10.} for day in axis[start:]]
    admitted,reasons = admissible_history(rows,axis=axis,symbols={'ABC'},action_affected=frozenset(),
        pair_absent=pairs,reset_after={'ABC':reset_day} if reset_day else {})
    assert reasons == ({'raw_adjusted_key_mismatch':1} if original_scan else
                       {'no_prices':1} if start is None else {})
    assert admitted == ({} if original_scan or start is None else {'ABC':first})


@pytest.mark.parametrize('missing_index', (2, 7))
def test_absence_index_respects_actual_clean_basis_tail(missing_index):
    from sentinel.feed import calendar

    axis = calendar.previous_sessions('2026-09-14', 12)
    rows = [{'ticker':'ABC','date':day,'adjusted_close':10.,
             'closeunadj':10. if index < 3 else 20.}
            for index,day in enumerate(axis)]
    pairs = {('ABC', axis[missing_index])}
    original_scan = any(symbol == 'ABC' and day >= axis[3] and day > ''
                        for symbol,day in pairs)
    admitted,reasons = admissible_history(rows,axis=axis,symbols={'ABC'},
        action_affected=frozenset(),pair_absent=pairs)
    assert admitted == ({} if original_scan else {'ABC':axis[3]})
    assert reasons == ({'raw_adjusted_key_mismatch':1} if original_scan else {})


def test_absence_index_avoids_symbols_times_absences_scan():
    from sentinel.feed.alpaca_observation import admissible_history

    class CountedAbsences(set):
        visits = 0
        def __iter__(self):
            for value in super().__iter__():
                self.visits += 1
                yield value

    symbols = {f'S{index:04}' for index in range(2000)}
    pairs = CountedAbsences((symbol,'2026-09-10') for symbol in symbols)
    axis = ['2026-09-11','2026-09-14']
    rows = [{'ticker':symbol,'date':day,'adjusted_close':10.,'closeunadj':10.}
            for day in axis for symbol in sorted(symbols)]
    for symbol in symbols:
        assert not any(pair_symbol == symbol and day >= axis[0] and day > '' for pair_symbol,day in pairs)
    original_visits = pairs.visits
    pairs.visits = 0
    admitted,reasons = admissible_history(rows,axis=axis,symbols=symbols,
        action_affected=frozenset(),pair_absent=pairs)
    assert len(admitted) == len(symbols) and not reasons
    assert original_visits == len(symbols)*len(pairs)
    assert pairs.visits == len(pairs)
