"""Calendar-time returns and daily high-water drawdown, independent of strategy."""
from datetime import date
from decimal import Decimal
import math


def measure(previous, session, value):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError('NAV must be finite and positive')
    if previous is None:
        previous = dict(start=session, last=None, base=str(value), peak=str(value),
                        maxdd='0', sessions=0)
    if previous['last'] is not None and session <= previous['last']:
        raise ValueError('metric sessions must advance')
    days = (date.fromisoformat(session) - date.fromisoformat(previous['start'])).days
    peak = max(value, Decimal(previous['peak']))
    maxdd = max(Decimal(previous['maxdd']), 1 - value / peak)
    multiple = value / Decimal(previous['base'])
    state = {**previous, 'last': session, 'peak': str(peak), 'maxdd': str(maxdd),
             'sessions': previous['sessions'] + 1}
    return state, dict(nav=str(value), multiple=str(multiple), maxdd=str(maxdd),
                       cagr=math.expm1(math.log(float(multiple))*365.2425/days) if days else None)
