"""Decision-neutral measurements of an already advanced canonical shadow."""
from decimal import Decimal
import math

from sentinel.controller.median5_breadth import breadth
from sentinel.core.session import _feed_from_dict
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState


def assert_nav(state, marks):
    """Independent cash + current ownership + receivables arithmetic."""
    book = PortfolioState.from_dict(state.wealth_core)
    ledger = Ledger.from_dict(state.ledger)
    value = Decimal(str(book.cash)) + Decimal(str(ledger.receivable_total()))
    value += sum((Decimal(str(ep.current_shares)) * Decimal(str(marks[ep.security_id]))
                  for ep in book.episodes.values()), Decimal(0))
    recorded = Decimal(str(state.last_evidence['observation']['shadow_nav']))
    assert abs(value - recorded) < Decimal('0.000001'), (value, recorded)
    return float(value)


def attribution(previous, current):
    if previous is None:
        return None
    p, c = set(previous), set(current)
    n0, n1 = len(p), len(c)
    base = n0 or n1 or 1
    same = sum(int(current[s]) - int(previous[s]) for s in p & c) / base
    entered = sum(current[s] for s in c - p) / base
    exited = -sum(previous[s] for s in p - c) / base
    denominator = sum(current.values()) * (1/n1 - 1/base) if n1 else 0.
    actual = (sum(current.values())/n1 if n1 else 0.) - (sum(previous.values())/n0 if n0 else 0.)
    assert math.isclose(same+entered+exited+denominator, actual, abs_tol=1e-12)
    return dict(continuing_label_change=same, entries=entered, exits=exited,
                denominator=denominator, observed_change=actual)


def measure(state, published, previous_labels=None):
    book = PortfolioState.from_dict(state.wealth_core)
    feed = _feed_from_dict(state.feed, published.meta, EligibilityConfig())
    b, _ = breadth(book, feed, state.median5['spy_history'], state.median5['peer_keys'])
    obs = state.last_evidence['observation']
    assert b.damaged_breadth == obs['damaged_breadth']
    marks = {bar.security_id: bar.raw_close for bar in published.bars}
    nav = assert_nav(state, marks)
    labels = {ep.security_id: b.labels[i].amber for i, (_, ep) in enumerate(sorted(book.episodes.items()))}
    values = {ep.security_id: float(ep.current_shares)*marks[ep.security_id] for ep in book.episodes.values()}
    stocks = sum(values.values())
    damaged = sum(v for sid, v in values.items() if labels[sid])
    weights = [v/stocks for v in values.values()] if stocks else []
    decision = state.last_decision
    return {
        'session': published.session, 'nav': nav, 'cash': book.cash,
        'receivables': Ledger.from_dict(state.ledger).receivable_total(),
        'stock_value': stocks, 'stock_fraction': stocks/nav,
        'held': len(values), 'damaged_stock_fraction': damaged/stocks if stocks else 0.,
        'damaged_nav_fraction': damaged/nav,
        'largest_stock_weight': max(weights, default=0.),
        'effective_stock_count': 1/sum(w*w for w in weights) if weights else 0.,
        'core_multiplier': decision['target_core_exposure'],
        'native_multiplier': decision['native_target_core_exposure'],
        'implied_stock_target_at_close_marks': decision['target_core_exposure']*stocks/nav,
        'recovery_reason': decision['ldrc']['reason'],
        'native_evidence': state.last_evidence['native_controller']['evidence'],
        'events': [e.to_dict() for e in Ledger.from_dict(state.ledger).events if e.session == published.session],
        'holding_quantities': {ep.security_id: float(ep.current_shares) for ep in book.episodes.values()},
        'observation': obs, 'leadership': state.last_evidence['recent_leadership'],
        'damage_change': attribution(previous_labels, labels),
        'labels': labels, 'holding_values': values,
    }


def probe_tuple(row):
    o = row['observation']
    return tuple(o[k] for k in (
        'shadow_drawdown', 'shadow_r5', 'shadow_r10', 'shadow_r20', 'shadow_r40',
        'damaged_breadth', 'green_breadth', 'damaged_breadth_delta5', 'spy_r20',
        'spy_vol_ratio', 'stops20', 'shadow_nav'))
