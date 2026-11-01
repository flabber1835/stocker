"""Indexed reverse lookup preserves dated symbol ambiguity and bounded work."""
import inspect
import textwrap

import pytest

from sentinel.feed import universe


def scanned_symbol(resolver, security_id, session):
    """Independent predecessor algorithm retained only as a differential oracle."""
    symbols = {ticker for ticker, listings in resolver._by_ticker.items()
               if any(item.permaticker == security_id and item.covers(session)
                      for item in listings)}
    if len(symbols) != 1:
        return None
    symbol = next(iter(symbols))
    return symbol if resolver.resolve(symbol, session) == security_id else None


def test_reverse_index_matches_predecessor_symbols_and_refusal_counts():
    listings = [
        universe.Listing('1', 'old', '2000-01-01', '2010-01-01'),
        universe.Listing('1', 'NEW', '2010-01-02', None),
        universe.Listing('2', 'OLD', '2011-01-01', None),
        universe.Listing('3', 'DUP', None, None),
        universe.Listing('4', 'DUP', '2009-01-01', '2015-01-01'),
        universe.Listing('5', 'ONE', None, None),
        universe.Listing('5', 'TWO', '2012-01-01', None),
        universe.Listing('6', 'SAME', None, None),
        universe.Listing('6', 'same', None, None),
    ]
    indexed = universe.IdentityResolver(iter(listings))
    predecessor = universe.IdentityResolver(iter(listings))
    for day in ('1999-12-31', '2000-01-01', '2009-01-01', '2010-01-01',
                '2010-01-02', '2011-01-01', '2012-01-01', '2015-01-01', '2015-01-02'):
        for sid in ('1', '2', '3', '4', '5', '6', 'missing'):
            assert indexed.ticker_for_security(sid, day) == scanned_symbol(predecessor, sid, day)
    assert indexed.unresolved == predecessor.unresolved


def test_reverse_lookup_does_not_compare_unrelated_security_identities():
    comparisons = []

    class CountedIdentity(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            comparisons.append((str(self), other))
            return str.__eq__(self, other)

    listings = [universe.Listing(CountedIdentity(str(index)), f'S{index}')
                for index in range(2048)]
    resolver = universe.IdentityResolver(listings)
    comparisons.clear()
    assert resolver.ticker_for_security('1000', '2026-10-30') == 'S1000'
    assert len(comparisons) < 16


def test_reverse_lookup_still_refuses_forward_symbol_ambiguity():
    resolver = universe.IdentityResolver([
        universe.Listing('1', 'SHARED'), universe.Listing('2', 'SHARED')])
    assert resolver.ticker_for_security('1', '2026-10-30') is None
    assert resolver.unresolved == {'ambiguous_listing': 1}


def test_restoring_whole_universe_scan_is_detected(monkeypatch):
    monkeypatch.setattr(universe.IdentityResolver, 'ticker_for_security', scanned_symbol)
    with pytest.raises(AssertionError):
        test_reverse_lookup_does_not_compare_unrelated_security_identities()


def test_removed_forward_ambiguity_guard_is_detected(monkeypatch):
    source = textwrap.dedent(inspect.getsource(universe.IdentityResolver.ticker_for_security))
    guard = 'return symbol if self.resolve(symbol, session) == security_id else None'
    assert guard in source
    namespace = {}
    exec(compile(source.replace(guard, 'return symbol'), 'reverse-identity-falsifier', 'exec'),
         universe.__dict__, namespace)
    monkeypatch.setattr(universe.IdentityResolver, 'ticker_for_security', namespace['ticker_for_security'])
    with pytest.raises(AssertionError):
        test_reverse_lookup_still_refuses_forward_symbol_ambiguity()
