"""Independent, fixture-scoped accounting for formed-book restore witnesses.

Trade choices are inputs, not an alpha oracle. All expected money comes from
published raw prices, fixed fixture capital and the documented ten-basis-point
fee. No production accounting or state decoder is called.
"""
from collections import defaultdict
from decimal import Decimal as D


EPSILON = D('0.00000001')


def _near(actual, expected, label):
    assert abs(D(str(actual)) - expected) < EPSILON, (label, actual, str(expected))


def _record(conn, observation_id, session):
    name = f'shadow-observation:v1:{observation_id}:session:{session}'
    row = conn.execute(
        "SELECT state#>'{state,wealth_core}', state#>'{state,ledger}', "
        "state#>'{state,shadow_nav_history}', state#>'{state,last_decision}', "
        "state->'strategy_economics', "
        "state#>>'{publication,publication,evidence,rolling_snapshot,candidate_id}' "
        'FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
    assert row is not None, 'missing accounting observation'
    return row


def check(conn, *, observation_id, session, previous_session, formation_candidate,
          starting_cash=D(100000)):
    book, ledger, navs, _, econ, candidate = _record(conn, observation_id, session)
    prior_book, _, _, prior_decision, prior_econ, _ = _record(
        conn, observation_id, previous_session)
    prices = {}
    for sid, day, opened, closed, split, dividend in conn.execute(
            'SELECT security_id, session, open_unadjusted::text, close_unadjusted::text, '
            'split_ratio::text, dividend_per_share::text FROM sentinel_snapshot_bars '
            'WHERE candidate_id=ANY(%s::uuid[]) ORDER BY session,security_id',
            ([str(formation_candidate), str(candidate)],)).fetchall():
        key = (sid, str(day))
        price = tuple(D(v) for v in (opened, closed, split, dividend))
        assert key not in prices or prices[key] == price, 'overlapping price revision'
        prices[key] = price

    events = ledger['events']
    assert events and min(e['session'] for e in events) < previous_session
    assert not ledger['receivables'], 'oracle scope excludes receivables'
    assert not any(e['session'] == session for e in events), 'funded fixture must not rotate'
    first_trade = {}
    for event in events:
        sid, day = event['security_id'], event['session']
        first_trade[sid] = min(first_trade.get(sid, day), day)
    for (sid, day), (_, _, split, dividend) in prices.items():
        if sid in first_trade and first_trade[sid] <= day <= session:
            assert split == 1 and dividend == 0, 'oracle scope excludes corporate actions'
    cash, fees = starting_cash, D(0)
    quantities = defaultdict(D)
    for event in events:
        kind, sid, day = event['event_type'], event['security_id'], event['session']
        assert kind in {'BUY', 'SELL'}, 'oracle scope excludes corporate actions'
        delta = D(str(event['shares_delta']))
        assert delta == int(delta) and delta != 0, 'whole-share trade required'
        assert (delta > 0) == (kind == 'BUY'), 'trade direction mismatch'
        opened, _, split, dividend = prices[(sid, day)]
        assert opened > 0 and split == 1 and dividend == 0
        fee = abs(delta) * opened * D('.001')
        _near(event['price'], opened, 'trade price mismatch')
        _near(event['fees'], fee, 'trade fee mismatch')
        _near(event['cash_before'], cash, 'pre-trade cash mismatch')
        change = -delta * opened - fee
        _near(event['cash_delta'], change, 'trade cash mismatch')
        cash += change
        fees += fee
        quantities[sid] += delta
        assert quantities[sid] >= 0 and cash >= 0, 'unlevered long-only book required'
        _near(event['cash_after'], cash, 'post-trade cash mismatch')

    held = defaultdict(D)
    for episode in book['episodes'].values():
        held[episode['security_id']] += D(str(episode['current_shares']))
        entry_open = prices[(episode['security_id'], episode['entry_date'])][0]
        _near(episode['entry_raw_open'], entry_open, 'historical entry mismatch')
    assert dict(held) == {sid: q for sid, q in quantities.items() if q}, 'holdings mismatch'
    assert len(book['episodes']) == 20, 'fixture requires twenty occupied slots'
    lots = lambda value: {slot: (e['security_id'], e['current_shares'])
                          for slot, e in value['episodes'].items()}
    assert lots(book) == lots(prior_book), 'flat funded session changed holdings'
    _near(prior_book['cash'], cash, 'prior cash mismatch')
    _near(book['cash'], cash, 'cash mismatch')
    marked = D(0)
    for sid, quantity in held.items():
        opened, closed, split, dividend = prices[(sid, session)]
        assert split == 1 and dividend == 0, 'funded fixture must be action-free'
        _near(opened, closed, 'funded fixture must be flat')
        _near(closed, prices[(sid, previous_session)][1], 'funded fixture must be flat')
        marked += quantity * closed
    core_nav = cash + marked
    _near(navs[-1], core_nav, 'Core NAV mismatch')

    # A new account buys only its allocated fraction of the formed stock book;
    # internal Core cash costs nothing to hold. BIL is the other purchased leg.
    allocation = D(str(prior_decision['target_core_exposure']))
    assert 0 <= allocation <= 1
    assert prior_econ['held_allocation'] is None and econ['initial_deployment'] is True
    _near(prior_econ['strategy_nav'], starting_cash, 'funding baseline mismatch')
    bil = conn.execute(
        'SELECT bil_open_signal::text,bil_close_signal::text '
        'FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s',
        (candidate, session)).fetchone()
    assert bil is not None and D(bil[0]) > 0 and D(bil[1]) > 0, 'positive BIL marks required'
    stock_purchase = starting_cash * allocation * marked / core_nav
    bil_purchase = starting_cash * (1-allocation)
    bil_pnl = bil_purchase * (D(bil[1])/D(bil[0])-1)
    entry_fee = (stock_purchase + bil_purchase) * D('.001')
    expected_nav = starting_cash + bil_pnl - entry_fee
    _near(econ['held_allocation'], allocation, 'allocation mismatch')
    _near(econ['strategy_nav'], expected_nav, 'funded NAV mismatch')
    return dict(scope='SYNTHETIC_FORMED_ACCOUNTING_ONLY', positions=len(book['episodes']),
                expected_cash=str(cash), expected_core_nav=str(core_nav),
                historical_fees=str(fees), funded_entry_fee=str(entry_fee),
                funded_bil_pnl=str(bil_pnl), expected_nav=str(expected_nav))
