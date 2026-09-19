"""Source-bound terminal consideration for the immutable leadership witness."""
from fractions import Fraction
import math

from stock_strategy_shared.wealth_core.terminal import TerminalKind


def values(*, prior, published):
    selected = set(prior.median5['selected'])
    result = {}
    bars = {bar.security_id: bar for bar in published.bars}
    for terms in published.terminal_events:
        sid = terms.security_id
        if sid not in selected:
            continue
        if sid in result or terms.session != published.session or not terms.reference:
            raise ValueError('ambiguous or unbound leadership terminal: ' + sid)
        series = prior.feed['series'].get(sid, {})
        anchor = series.get('signal_basis_anchor')
        if not anchor or anchor[0] != prior.last_processed_session:
            raise ValueError('leadership terminal lacks prior price basis: ' + sid)
        raw, signal = map(lambda x: Fraction(str(x)), anchor[1:])
        if raw <= 0 or signal <= 0:
            raise ValueError('invalid leadership terminal price basis: ' + sid)
        if terms.kind is TerminalKind.WRITE_OFF:
            consideration = Fraction(0)
        elif terms.kind is TerminalKind.CASH_MERGER:
            if not terms.completeness(0)[0]:
                raise ValueError('incomplete leadership cash terminal: ' + sid)
            consideration = Fraction(str(terms.cash_per_share))
        elif terms.kind in (TerminalKind.CONVERSION, TerminalKind.CASH_PLUS_STOCK):
            # A price-return sensor holds a fractional notional unit, not a
            # broker lot; contractual exchange consideration is never rounded.
            if not terms.completeness(0)[0]:
                raise ValueError('incomplete leadership conversion: ' + sid)
            delivered = bars.get(terms.delivered_security_id)
            if (delivered is None or delivered.session != published.session
                    or delivered.raw_close is None or not math.isfinite(delivered.raw_close)
                    or delivered.raw_close <= 0):
                raise ValueError('leadership conversion lacks delivered close: ' + sid)
            consideration = Fraction(str(terms.exchange_ratio)) * Fraction(str(delivered.raw_close))
            if terms.kind is TerminalKind.CASH_PLUS_STOCK:
                consideration += Fraction(str(terms.cash_per_share))
        else:
            raise ValueError('unsupported leadership terminal: ' + sid)
        source = bars.get(sid)
        split = Fraction(str(source.split_ratio)) if source is not None else Fraction(1)
        if split <= 0 or (source is not None and source.session != published.session):
            raise ValueError('invalid leadership terminal split basis: ' + sid)
        result[sid] = float(consideration * split * signal / raw)
    return result
