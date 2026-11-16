"""Explicit, reversible research overlay on the single canonical Core engine.

No production file is changed and no second book is implemented. Exact source
matches fence the few whole-entry assumptions that this experiment changes.
"""
from contextlib import ExitStack, contextmanager
from fractions import Fraction
import hashlib
import inspect
import math
from unittest.mock import patch

PROFILE = 'wealth-core-fractional-entry-research-v1'
ORIGINAL_PROFILE = 'wealth-core-v5-total-cash-open-sizing-v2'
QUANTUM = Fraction(1, 10**12)


def affordable_quantity(cash, price, cost_bps):
    """Exact decimal economics, with a downward fixed-precision share bound."""
    if (not all(math.isfinite(float(x)) for x in (cash, price, cost_bps))
            or cash <= 0 or price <= 0 or cost_bps < 0):
        return 0
    from stock_strategy_shared.wealth_core.shares import traded_cash
    budget = Fraction(str(cash))
    unit = Fraction(str(price)) * (1 + Fraction(str(cost_bps))/10000)
    ticks = (budget/unit) // QUANTUM
    quantity = float(ticks * QUANTUM)
    # Decimal-to-float conversion must not reintroduce an over-budget fill.
    while quantity > 0 and (Fraction(str(quantity))*unit > budget
                            or traded_cash(quantity, price, cost_bps, buy=True) > cash):
        ticks -= 1
        quantity = float(ticks * QUANTUM)
    return quantity


def transform(function, replacements):
    original = inspect.getsource(function)
    changed = original
    for before, after, count in replacements:
        if changed.count(before) != count:
            raise ValueError('fractional source seam changed: '+function.__qualname__)
        changed = changed.replace(before, after)
    namespace = {}
    exec(compile(changed, '<fractional-research:'+function.__name__+'>', 'exec'),
         function.__globals__, namespace)
    hashes = dict(module=function.__module__, function=function.__name__,
        original_sha256=hashlib.sha256(original.encode()).hexdigest(),
        transformed_sha256=hashlib.sha256(changed.encode()).hexdigest())
    return namespace[function.__name__], hashes


@contextmanager
def activate():
    from stock_strategy_shared.wealth_core import adapter, engine, run, terminal, v5
    if v5.PROFILE != ORIGINAL_PROFILE:
        raise ValueError('fractional overlay requires the pinned original profile')
    admission, a = transform(v5.admission, [(
        '    if cash + EPSILON < price * (1 + cost_bps / 10_000):\n'
        '        return None, "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE"\n', '', 1)])
    entry, b = transform(engine.apply_entry, [('int(op.shares)', '_shares_json(op.shares)', 3)])
    step, c = transform(adapter.step_session, [('po.shares = int(po.shares)',
                                               'po.shares = _as_json(po.shares)', 1)])
    conversion, d = transform(terminal._apply_conversion, [(
        'ep.initial_shares = max(1, int(round(ep.initial_shares * ratio)))',
        'ep.initial_shares = _as_json(Fraction(str(ep.initial_shares)) * Fraction(str(terms.exchange_ratio)))', 1)])
    with ExitStack() as stack:
        changes = ((v5, 'PROFILE', PROFILE), (v5, 'admission', admission),
            (v5, 'affordable_whole_shares', affordable_quantity),
            (engine, 'affordable_whole_shares', affordable_quantity),
            (engine, 'apply_entry', entry), (adapter, 'apply_entry', entry),
            (adapter, 'step_session', step), (run, 'step_session', step),
            (terminal, '_apply_conversion', conversion))
        for module, name, value in changes:
            stack.enter_context(patch.object(module, name, value))
        yield dict(profile=PROFILE, share_decimal_places=12, fractionability='ALL_ELIGIBLE_SECURITIES',
                   fill_model='NEXT_SESSION_RAW_OPEN', transaction_cost_bps=10,
                   transformations=[a,b,c,d])
