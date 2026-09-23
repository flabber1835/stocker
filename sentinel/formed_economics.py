"""One funded entry into a mature shadow book; no broker or Core mutation."""
from decimal import Decimal as D


def opening_marks(state, published):
    held = {e['security_id'] for e in state.wealth_core['episodes'].values()}
    marks = {}
    for bar in published.bars:
        if bar.security_id in held:
            if bar.security_id in marks:
                raise ValueError('FORMED_ENTRY_DUPLICATE_OPEN')
            marks[bar.security_id] = str(bar.raw_open)
    return marks


def entry(state, marks, *, parent_open, parent_close, allocation, bil_intraday):
    """Independent cash/notional equation, charged once at the first live open."""
    held = {}
    for episode in state.wealth_core['episodes'].values():
        sid = episode['security_id']
        held[sid] = held.get(sid, D(0)) + D(str(episode['current_shares']))
    if not isinstance(marks, dict) or set(marks) != set(held):
        raise ValueError('FORMED_ENTRY_OPEN_COVERAGE_CHANGED')
    prices = {sid: D(str(price)) for sid, price in marks.items()}
    if any(not p.is_finite() or p <= 0 for p in prices.values()):
        raise ValueError('FORMED_ENTRY_POSITIVE_OPENS_REQUIRED')
    notional = sum((held[sid] * prices[sid] for sid in held), D(0))
    if not D(0) <= notional <= parent_open:
        raise ValueError('FORMED_ENTRY_UNLEVERED_NOTIONAL_REQUIRED')
    fees = sum((D(str(e['fees'])) for e in state.ledger['events']
                if e['session'] == state.last_processed_session and e['event_type'] in {'BUY', 'SELL'}), D(0))
    if not fees.is_finite() or fees < 0:
        raise ValueError('FORMED_ENTRY_INVALID_CANONICAL_FEES')
    # Core's canonical closing NAV includes its own hypothetical opening trades.
    # The newly funded account instead buys the resulting composition once.
    core_gross = (parent_close + fees) / parent_open - 1
    gross = 1 + allocation * core_gross + (1 - allocation) * bil_intraday
    turnover = allocation * notional / parent_open + (1 - allocation)
    cost = D('.001') * turnover
    if gross <= cost:
        raise ValueError('FORMED_ENTRY_NONPOSITIVE_ECONOMICS')
    return dict(core_intraday=core_gross, gross_factor=gross, net_factor=gross-cost,
                turnover=turnover, transaction_cost_factor=(gross-cost)/gross,
                marks=dict(marks))
