"""Canonical noncash dividend assets must reconcile without becoming cash."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel.panel import authority_reader, model, render, sources


SESSION = '2026-10-22'
NAV = Decimal('49899.610639800005')
CASH = Decimal('14069.250639800004')


@pytest.fixture
def canonical_book_state():
    # Bounded read-only production witness. Permanent ids are replaced by
    # tickers; only the 14 held quantities, exact-session marks and claim remain.
    held = (
        ('CORT', '20', '107.5'), ('ATEX', '23', '73.16'),
        ('PBR', '120', '25.62'), ('TRGP', '10', '289.54'),
        ('DAR', '42', '55.64'), ('PBR.A', '132', '22.9'),
        ('ATI', '15', '161.84'), ('DELL', '5', '452.95'),
        ('ETON', '51', '50.02'), ('PANW', '6', '354.92'),
        ('VOYA', '24', '98.42'), ('NAT', '415', '7.54'),
        ('ECPG', '26', '100.36'), ('HNGE', '29', '109.93'),
    )
    return {
        'wealth_core': {
            'cash': str(CASH),
            'episodes': {str(slot): dict(security_id=ticker, ticker=ticker,
                                        current_shares=quantity)
                         for slot, (ticker, quantity, _) in enumerate(held)},
        },
        'feed': {'series': {ticker: dict(sessions=[SESSION], raw_closes=[mark])
                            for ticker, _, mark in held}},
        'ledger': {'receivables': [dict(security_id='ANDE', ticker='ANDE',
            amount='6.8', accrued_session='2026-10-01', due_in=0)]},
        'pending': [],
    }


def test_sold_issuer_receivable_reconciles_real_shaped_book_and_observer(canonical_book_state):
    original = deepcopy(canonical_book_state)
    book = sources._shadow_holdings(canonical_book_state, SESSION, NAV)
    assert canonical_book_state == original
    assert len(book.holdings) == 14
    assert all(item.security_id != 'ANDE' for item in book.holdings)
    assert book.cash == CASH and book.receivables == Decimal('6.8')
    held_value = sum((item.value for item in book.holdings), Decimal(0))
    assert held_value + book.cash == Decimal('49892.810639800004')
    assert abs(held_value + book.cash + book.receivables - book.nav) < Decimal('1e-10')

    row = authority_reader._row_from_observation(dict(key='book', label='Book',
        value='canonical', status=model.OK, shadow_book=book.model_dump(mode='json')))
    assert row.shadow_book.receivables == Decimal('6.8')
    html = render._holdings_html(row, datetime.now(timezone.utc))
    assert 'Dividend receivables (not cash)' in html and '$6.80' in html
    assert '$14,069.25' in html and '$49,899.61' in html


def test_settled_receivable_moves_to_cash_once(canonical_book_state):
    canonical_book_state['ledger']['receivables'] = []
    canonical_book_state['wealth_core']['cash'] = str(CASH + Decimal('6.8'))
    book = sources._shadow_holdings(canonical_book_state, SESSION, NAV)
    assert book.cash == CASH + Decimal('6.8') and book.receivables == 0


@pytest.mark.parametrize('claims', [None, {}, ['6.8'], [{}], [{'amount': True}],
    [{'amount': '-1'}, {'amount': '7.8'}], [{'amount': 'NaN'}],
    [{'amount': 'Infinity'}], [{'amount': '0.0000000000000000000000000000001'}]])
def test_malformed_receivables_never_become_a_valid_total(canonical_book_state, claims):
    canonical_book_state['ledger']['receivables'] = claims
    with pytest.raises(ValueError):
        sources._shadow_holdings(canonical_book_state, SESSION, NAV)


def test_negative_claim_cancellation_guard_has_a_falsifier(canonical_book_state):
    canonical_book_state['ledger']['receivables'] = [dict(amount='-1'), dict(amount='7.8')]
    with pytest.raises(ValueError, match='canonical dividend receivable is invalid'):
        sources._shadow_holdings(canonical_book_state, SESSION, NAV)
    body = textwrap.dedent(inspect.getsource(sources._shadow_holdings))
    broken = body.replace('if not amount.is_finite() or amount < 0:', 'if False:')
    assert broken != body
    namespace = dict(vars(sources))
    exec(compile(broken, 'negative-receivable-falsifier', 'exec'), namespace)
    assert namespace['_shadow_holdings'](canonical_book_state, SESSION, NAV).receivables == Decimal('6.8')


def test_receivable_does_not_relax_nav_arithmetic_or_hide_missing_payload(canonical_book_state):
    with pytest.raises(ValueError, match='disagree with book value'):
        sources._shadow_holdings(canonical_book_state, SESSION, NAV + Decimal('0.021'))
    book = sources._shadow_holdings(canonical_book_state, SESSION, NAV).model_dump(mode='json')
    for missing_or_wrong in (None, '0', '7'):
        bad = deepcopy(book)
        if missing_or_wrong is None:
            del bad['receivables']
        else:
            bad['receivables'] = missing_or_wrong
        with pytest.raises(ValueError):
            authority_reader._row_from_observation(dict(key='book', label='Book',
                value='canonical', status=model.OK, shadow_book=bad))


def test_missing_ledger_is_unknown_instead_of_assumed_zero(canonical_book_state):
    del canonical_book_state['ledger']
    with pytest.raises(KeyError, match='ledger'):
        sources._shadow_holdings(canonical_book_state, SESSION, NAV)
