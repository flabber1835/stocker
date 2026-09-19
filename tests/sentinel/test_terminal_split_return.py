"""A prior notional share splits before terminal consideration is earned."""
from types import SimpleNamespace

import pytest

from sentinel.controller import terminal_returns
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


@pytest.mark.parametrize('split,cash,ratio', [(2, 50, .5), (.5, 200, 2)])
@pytest.mark.parametrize('kind', [TerminalKind.CASH_MERGER, TerminalKind.CONVERSION,
                                  TerminalKind.CASH_PLUS_STOCK])
def test_split_then_terminal_preserves_economic_value(split, cash, ratio, kind):
    prior = SimpleNamespace(median5={'selected': ['A']}, last_processed_session='2026-08-12',
        feed={'series': {'A': {'signal_basis_anchor': ['2026-08-12', 100, 120]}}})
    term = TerminalTerms('2026-08-13', 'A', kind, cash_per_share=cash,
        delivered_security_id='B', delivered_ticker='BBB', delivered_issuer_id='issuer-B',
        exchange_ratio=ratio, reference='split-then-terminal-contract')
    published = SimpleNamespace(session='2026-08-13', terminal_events=[term], bars=[
        SimpleNamespace(security_id='A', session='2026-08-13', split_ratio=split),
        SimpleNamespace(security_id='B', session='2026-08-13', raw_close=100, split_ratio=4)])
    # Each single-leg deal pays $100 per original share; mixed pays $200.
    # The retained price-return basis is 1.2 signal units per raw dollar.
    expected = 240 if kind is TerminalKind.CASH_PLUS_STOCK else 120
    assert terminal_returns.values(prior=prior, published=published) == {'A': expected}
