"""Exit-only price diagnostics. No portfolio, strategy imports or new book."""
from collections import Counter
from fractions import Fraction
import gzip
import json
import math
import os
from pathlib import Path
import statistics

from core_volatility_admit import digest
from core_volatility_source import need, sha

PARENT = '376b422e09e8cf01c682b674dfee80d5ff483c0b4a7fab6ddbf78472642b84af'
STATUS = 'EXIT_DIAGNOSTIC_ONLY_NO_FINANCIAL_AUTHORITY'


def number(value):
    need(not isinstance(value, bool) and math.isfinite(float(value)), 'FINITE_DIAGNOSTIC_VALUE')
    return Fraction(str(value))


def stop_signal(closes, staged):
    peak, floor, widths = None, None, []
    for day, value in closes:
        value = number(value) if not isinstance(value, Fraction) else value
        need(value > 0, 'POSITIVE_DIAGNOSTIC_PRICE')
        if floor is not None and value <= floor:
            return dict(day=day, price=value, floor=floor, peak=peak, widths=widths)
        peak = value if peak is None else max(peak, value)
        width = (Fraction('.30') if not staged or peak >= Fraction('1.20')
                 else Fraction('.20') if peak >= Fraction('1.10') else Fraction('.10'))
        if not widths or widths[-1]['width'] != width:
            widths.append(dict(day=day, width=width))
        candidate = peak*(1-width)
        floor = candidate if floor is None else max(floor, candidate)
    return None


def next_open(signal, openings):
    if signal is None:
        return None
    return next(((day, value) for day, value in openings if day > signal['day']), None)


def position_value(snapshot, buy, *, opening=False, allow_carried=False):
    sid = buy['security_id']
    episodes = [e for e in snapshot['wealth_core']['episodes'].values()
                if e['security_id'] == sid and e['entry_date'] == buy['session']]
    need(len(episodes) <= 1, 'UNIQUE_ORDINARY_DIAGNOSTIC_EPISODE')
    if not episodes:
        return None
    mark = snapshot['prices'].get(sid)
    allowed = ('RAW_OPEN',) if opening else ('CURRENT', 'CARRIED', 'TERMINAL_CARRY') if allow_carried else ('CURRENT',)
    if not mark or mark['status'] not in allowed or mark['raw_price'] is None:
        return None
    denominator = number(buy['shares_delta'])*number(buy['price'])
    need(denominator > 0 and number(episodes[0]['current_shares']) > 0, 'LONG_ONLY_OBSERVED_DIAGNOSTIC_POSITION')
    return number(episodes[0]['current_shares'])*number(mark['raw_price'])/denominator


def committed(book, cp, name):
    expected = cp['journals'][name]
    with (book/(name+'.jsonl')).open('rb') as f:
        raw = f.read(expected['bytes'])
    need(len(raw) == expected['bytes'] and sha(raw) == expected['prefix_sha256'], 'DIAGNOSTIC_COMMITTED_PREFIX')
    return [json.loads(line) for line in raw.splitlines()]


def summarize(records):
    if not records:
        return dict(count=0)
    total = math.fsum(r['entry_notional'] for r in records)
    return dict(count=len(records), earlier_exits=sum(r['earlier_exit'] for r in records),
        improved=sum(r['price_return_difference_pp'] > 1e-9 for r in records),
        worsened=sum(r['price_return_difference_pp'] < -1e-9 for r in records),
        unchanged=sum(abs(r['price_return_difference_pp']) <= 1e-9 for r in records),
        mean_trade_price_return_difference_pp=statistics.mean(r['price_return_difference_pp'] for r in records),
        median_trade_price_return_difference_pp=statistics.median(r['price_return_difference_pp'] for r in records),
        original_entry_dollar_weighted_price_return_difference_pp=math.fsum(
            r['entry_notional']*r['price_return_difference_pp'] for r in records)/total,
        fixed_entry_normalized_price_pnl_difference=math.fsum(r['fixed_entry_normalized_price_pnl_difference'] for r in records))


def replay(book):
    from probe import check_context
    check_context(os.environ)
    book = Path(book)
    cp = json.loads(gzip.decompress((book/'checkpoint.json.gz').read_bytes()))
    need(cp['sha256'] == PARENT == digest({k: v for k, v in cp.items() if k != 'sha256'})
         and cp['completed'] == 1196 and cp['source_cursor'] == '2022-09-30', 'EXACT_STOP_DIAGNOSTIC_PARENT')
    formation, daily = committed(book, cp, 'formation'), committed(book, cp, 'daily')
    need(len(formation) == 126 and len(daily) == 1196 and daily[0]['session'] == '2018-01-02'
         and daily[-1]['session'] == '2022-09-30', 'EXACT_STOP_DIAGNOSTIC_WINDOW')
    features, plans = {}, {}
    for row in formation+daily:
        audit = row['evidence']['research_entry_audit']
        for fill in audit['fills']:
            if fill['operation'] == 'OPEN_SLOT_POSITION':
                features[fill['security_id'], row['session']] = plans.pop(fill['security_id'])['detail']
        for op in audit['operations']:
            if op['operation'] == 'OPEN_SLOT_POSITION':
                plans[op['security_id']] = op
    events = cp['run']['state']['ledger']['events']
    active, exits, excluded = {}, {}, set()
    for event in events:
        sid = event['security_id']
        child = event['detail'].get('delivered_security_id')
        if child and number(event['detail'].get('shares_delivered', 0)) > 0:
            excluded.update((sid, child))
        if event['event_type'] == 'BUY':
            active[sid] = sid, event['session']
        elif event['event_type'] in ('SELL', 'CASH_MERGER') and sid in active:
            exits[active.pop(sid)] = event
    buys = [e for e in events if e['event_type'] == 'BUY' and '2018-01-02' <= e['session'] <= '2022-09-30']
    need(len(buys) == 155, 'ALL_RECORDED_MEASURED_ENTRY_COVERAGE')
    axis = {row['session']: i for i, row in enumerate(daily)}
    anchor = number(daily[0]['economics']['parent_core_close_equity'])
    records, coverage, discrepancies = [], Counter(), []
    for buy in buys:
        sid, start = buy['security_id'], buy['session']
        if sid in excluded:
            coverage['stock_delivery_lineage_excluded'] += 1
            continue
        ending = exits.get((sid, start))
        boundary = ending['session'] if ending else cp['source_cursor']
        closes, openings = [], []
        for row in daily[axis[start]:axis[boundary]+1]:
            audit = row['evidence']['research_entry_audit']
            if row['session'] > start:
                value = position_value(audit['opening_accounting'], buy, opening=True)
                if value is not None:
                    openings.append((row['session'], value))
            if not ending or row['session'] < boundary:
                value = position_value(audit['closing_accounting'], buy)
                if value is not None:
                    closes.append((row['session'], value))
        need(closes and closes[0][0] == start, 'OBSERVED_FIRST_OWNED_CLOSE')
        entry_notional = number(buy['shares_delta'])*number(buy['price'])
        if ending:
            baseline = (number(-ending['shares_delta'])*number(ending['price'])/entry_notional
                        if ending['event_type'] == 'SELL' else number(ending['cash_delta'])/entry_notional)
            state = 'closed_sell' if ending['event_type'] == 'SELL' else 'closed_cash'
        else:
            baseline = position_value(daily[-1]['evidence']['research_entry_audit']['closing_accounting'], buy, allow_carried=True)
            need(baseline is not None, 'OBSERVED_OPEN_CUTOFF_MARK')
            state = 'open_marked'
        original_signal = stop_signal(closes, False)
        original_fill = next_open(original_signal, openings)
        original_stop = ending and ending['event_type'] == 'SELL' and ending['reason'] == 'EXIT_TRAILING_STOP'
        if original_stop:
            if original_fill is None or original_fill[0] != boundary or abs(float(original_fill[1]-baseline)) > 1e-9:
                discrepancies.append(dict(ticker=buy['ticker'], entry=start, reason='ORIGINAL_STOP_DATE_OR_PRICE',
                                          expected=boundary, observed=original_fill[0] if original_fill else None))
        elif original_fill is not None and (state != 'closed_cash' or original_fill[0] < boundary):
            discrepancies.append(dict(ticker=buy['ticker'], entry=start, reason='UNEXPECTED_EARLIER_BASELINE_STOP'))
        signal = stop_signal(closes, True)
        fill = next_open(signal, openings)
        alternative = fill[1] if fill else baseline
        difference = alternative-baseline
        coverage[state] += 1
        records.append(dict(ticker=buy['ticker'], security_id=sid, entry=start, original_boundary=boundary,
            original_reason=ending['reason'] if ending else 'OPEN_AT_CUTOFF', state=state,
            entry_volatility=features[sid, start]['volatility'], entry_notional=float(entry_notional),
            baseline_price_return_pct=100*float(baseline-1), alternative_price_return_pct=100*float(alternative-1),
            price_return_difference_pp=100*float(difference),
            fixed_entry_normalized_price_pnl_difference=float(entry_notional*difference*50000/anchor),
            stop_signal_day=signal['day'] if signal else None,
            new_exit_day=fill[0] if fill else None,
            earlier_exit=bool(fill and (not ending or fill[0] < boundary)),
            signal_without_observed_sale=bool(signal and not fill),
            floor_at_signal=float(signal['floor']) if signal else None,
            stage_width_at_signal=float(signal['widths'][-1]['width']) if signal else None,
            sessions_to_new_exit=axis[fill[0]]-axis[start] if fill else None))
    need(not discrepancies, 'ORIGINAL_30_PERCENT_EXIT_CALIBRATION:'+json.dumps(discrepancies[:8], sort_keys=True))
    summaries = {}
    for name, selected in (('all_supported', records), ('entry_volatility_at_least_50pct', [r for r in records if r['entry_volatility'] >= .5])):
        summaries[name] = {group: summarize([r for r in selected if predicate(r)]) for group, predicate in (
            ('all', lambda r: True), ('closed_price_losers', lambda r: r['state'] == 'closed_sell' and r['baseline_price_return_pct'] < 0),
            ('closed_price_winners', lambda r: r['state'] == 'closed_sell' and r['baseline_price_return_pct'] > 0),
            ('open_marked', lambda r: r['state'] == 'open_marked'), ('closed_cash', lambda r: r['state'] == 'closed_cash'))}
    return dict(schema='research.core-entry-stop-diagnostic/1', status=STATUS, diagnostic_only=True,
        financial_continuation_authorized=False, canonical_runtime_executed=False, new_core_books=0,
        parent_checkpoint_sha256=PARENT, through=cp['source_cursor'], measured_entries=len(buys),
        rule=dict(widths=['0.10', '0.20', '0.30'], peak_gain_gates=['0.10', '0.20'], floor_never_decreases=True,
                  first_owned_close_arming=True, causal_next_available_open=True),
        coverage=dict(coverage), original_30pct_exit_calibration_passed=True,
        original_trailing_sales_calibrated=sum(r['original_reason'] == 'EXIT_TRAILING_STOP' for r in records),
        summaries=summaries, largest_differences=sorted(records, key=lambda r: -abs(r['fixed_entry_normalized_price_pnl_difference']))[:15],
        records=records, limitations=['Fixed original entries and notionals; no new portfolio, replacement, re-entry or cash/reinvestment accounting.',
            'Price-only returns exclude dividends and fees. Dollar sums use original entry notionals and are not recoverable portfolio profit or CAGR.',
            'Open entries are right-censored at September30,2022. Stock-delivery lineages are excluded explicitly.',
            'Illustrative fixed gain gates were not optimized; this known history is not unseen validation.'])
