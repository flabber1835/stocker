"""Past-triggered, coherent additional opening losses."""
from dataclasses import replace

MODES = ("control", "relapse", "overnight_gap", "changing_holdings")


def multipliers(mode, day, event_day, all_ids, event_holdings):
    if event_day is None or day < event_day or mode == "control":
        return {}, 1.
    if mode == "relapse" and day < event_day + 10:
        return {sid:.97 for sid in all_ids}, .995
    if mode == "overnight_gap" and day == event_day:
        return {sid:.80 for sid in all_ids}, .94
    if mode == "changing_holdings" and day == event_day:
        return {sid:.65 for sid in sorted(event_holdings)[:len(event_holdings)//2]}, .97
    return {}, 1.


def apply_opening_loss(publication, market, stock_factors, spy_factor):
    bars = []
    for bar in publication.bars:
        factor = stock_factors.get(bar.security_id, 1.)
        market.prices[bar.security_id] *= factor
        bars.append(replace(bar, raw_open=bar.raw_open*factor, raw_close=bar.raw_close*factor,
                            signal_close=bar.signal_close*factor))
    market.spy[-1] *= spy_factor
    spy = list(publication.spy_closeadj)
    spy[-1] *= spy_factor
    return replace(publication, bars=bars, spy_closeadj=spy)
