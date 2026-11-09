"""Fixed-entry staged-budget diagnostics; no portfolio or canonical imports."""
from fractions import Fraction
import gzip
import json
import math
import os
from pathlib import Path

import core_entry_stop_diagnostic as reader
from core_volatility_source import need, sha

READER_SHA = '4ea4915fc2229d11315be41e6b7e0a485fa9d40324e2a25b4ed7ecfb66b18976'
STATUS = 'SIZING_DIAGNOSTIC_ONLY_NO_FINANCIAL_AUTHORITY'
F = reader.number


def staged_trade(*, entry, notional, buy_fee, raw_entry, closes, openings,
                 terminal_ratio, exit_fee_rate, dividends, owned_days, exit_day=None):
    """Synthetic-testable arithmetic on one already specified holding window."""
    notional, buy_fee, raw_entry = F(notional), F(buy_fee), F(raw_entry)
    terminal_ratio, exit_fee_rate = F(terminal_ratio), F(exit_fee_rate)
    budget = notional+buy_fee
    need(notional > 0 and buy_fee >= 0 and raw_entry > 0 and terminal_ratio >= 0
         and 0 <= exit_fee_rate < 1, 'VALID_SIZING_DIAGNOSTIC_ECONOMICS')
    need(owned_days and entry == owned_days[0] and owned_days == sorted(set(owned_days)), 'ORDERED_OWNED_BUDGET_SESSIONS')
    need([d for d, _ in closes] == sorted({d for d, _ in closes})
         and [d for d, _, _ in openings] == sorted({d for d, _, _ in openings}), 'ORDERED_SIZING_PRICE_OBSERVATIONS')
    tranches = [dict(fraction=Fraction('.20'), day=entry, ratio=Fraction(1),
                     raw_price=raw_entry, signal_day=None, gate=None)]
    unfilled = []
    for gain, fraction in ((Fraction('.10'), Fraction('.30')), (Fraction('.20'), Fraction('.50'))):
        signal = next(((d, F(v)) for d, v in closes if F(v) >= 1+gain), None)
        fill = next(((d, F(v), F(raw)) for d, v, raw in openings
                     if signal and d > signal[0] and (exit_day is None or d < exit_day)), None)
        if fill:
            need(fill[0] in owned_days and fill[1] > 0 and fill[2] > 0, 'OBSERVED_CAUSAL_SIZING_FILL')
            tranches.append(dict(fraction=fraction, day=fill[0], ratio=fill[1], raw_price=fill[2],
                                 signal_day=signal[0], gate=gain))
        else:
            unfilled.append(dict(fraction=fraction, gate=gain, signal_day=signal[0] if signal else None))
    invested = sum((t['fraction'] for t in tranches), Fraction(0))
    units = sum((t['fraction']/t['ratio'] for t in tranches), Fraction(0))
    need(Fraction('.20') <= invested <= 1, 'ORIGINAL_ENTRY_BUDGET_CAP')
    baseline_dividends, staged_dividends = Fraction(0), Fraction(0)
    for ex_day, amount in dividends:
        amount = F(amount)
        need(amount >= 0 and entry < ex_day and (exit_day is None or ex_day <= exit_day), 'OWNED_ORIGINAL_DIVIDEND_RIGHT')
        held_units = sum((t['fraction']/t['ratio'] for t in tranches if t['day'] < ex_day), Fraction(0))
        baseline_dividends += amount
        staged_dividends += amount*held_units
    original_gross = notional*terminal_ratio
    staged_gross = original_gross*units
    baseline_profit = original_gross*(1-exit_fee_rate)+baseline_dividends-budget
    staged_profit = staged_gross*(1-exit_fee_rate)+staged_dividends-budget*invested
    capital_days = budget*sum((t['fraction']*sum(day >= t['day'] for day in owned_days)
                              for t in tranches), Fraction(0))
    baseline_capital_days = budget*len(owned_days)
    need(0 < capital_days <= baseline_capital_days, 'NO_EXTRA_CAPITAL_OR_BORROWING')
    return dict(budget=budget, invested_fraction=invested, terminal_units=units,
        baseline_profit=baseline_profit, staged_profit=staged_profit,
        difference=staged_profit-baseline_profit,
        baseline_price_profit=original_gross-notional,
        staged_price_profit=staged_gross-notional*invested,
        baseline_dividends=baseline_dividends, staged_dividends=staged_dividends,
        baseline_buy_fee=buy_fee, staged_buy_fee=buy_fee*invested,
        baseline_sell_fee=original_gross*exit_fee_rate, staged_sell_fee=staged_gross*exit_fee_rate,
        unused_budget=budget*(1-invested), baseline_capital_days=baseline_capital_days,
        staged_capital_days=capital_days, tranches=tranches, unfilled=unfilled,
        one_share_unaffordable=sum(t['fraction']*notional < t['raw_price'] for t in tranches),
        starter_one_share_unaffordable=Fraction('.20')*notional < raw_entry)


def plain(value):
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def summarize(records):
    if not records:
        return dict(count=0)
    baseline = math.fsum(r['baseline_normalized_profit'] for r in records)
    staged = math.fsum(r['staged_normalized_profit'] for r in records)
    capital = math.fsum(r['baseline_budget_session_dollars'] for r in records)
    deployed = math.fsum(r['staged_budget_session_dollars'] for r in records)
    return dict(count=len(records), baseline_normalized_profit=baseline, staged_normalized_profit=staged,
        normalized_profit_difference=staged-baseline,
        normalized_price_only_difference=math.fsum(r['normalized_price_only_difference'] for r in records),
        improved=sum(r['normalized_profit_difference'] > 1e-9 for r in records),
        worsened=sum(r['normalized_profit_difference'] < -1e-9 for r in records),
        unchanged=sum(abs(r['normalized_profit_difference']) <= 1e-9 for r in records),
        net_winners_turned_losers=sum(r['baseline_normalized_profit'] > 0 and r['staged_normalized_profit'] < 0 for r in records),
        baseline_budget_session_dollars=capital, staged_budget_session_dollars=deployed,
        relative_budget_deployment=deployed/capital, relative_budget_left_unused=1-deployed/capital,
        starter_one_share_unaffordable=sum(r['starter_one_share_unaffordable'] for r in records),
        executed_tranches_one_share_unaffordable=sum(r['one_share_unaffordable'] for r in records),
        final_stage_counts={str(k): sum(r['funded_stages'] == k for r in records) for k in (1, 2, 3)})


def replay(book):
    from probe import check_context
    check_context(os.environ)
    need(sha(Path(reader.__file__).read_bytes()) == READER_SHA, 'UNCHANGED_ADMITTED_PRICE_READER')
    book = Path(book)
    reference = reader.replay(book)
    cp = json.loads(gzip.decompress((book/'checkpoint.json.gz').read_bytes()))
    daily = reader.committed(book, cp, 'daily')
    events = cp['run']['state']['ledger']['events']
    need(not cp['run']['state']['ledger']['receivables'], 'NO_UNRESOLVED_DIVIDEND_RIGHT_ZEROING')
    buys = {(e['security_id'], e['session']): e for e in events if e['event_type'] == 'BUY'}
    active, exits = {}, {}
    for event in events:
        if event['event_type'] == 'BUY':
            active[event['security_id']] = event['security_id'], event['session']
        elif event['event_type'] in ('SELL', 'CASH_MERGER') and event['security_id'] in active:
            exits[active.pop(event['security_id'])] = event
    paid = [e for e in events if e['event_type'] == 'DIVIDEND_PAID']
    axis = {row['session']: i for i, row in enumerate(daily)}
    anchor = F(daily[0]['economics']['parent_core_close_equity'])
    scale = 50000/anchor
    records = []
    for old in reference['records']:
        sid, start, boundary = old['security_id'], old['entry'], old['original_boundary']
        buy = buys[sid, start]
        ending = exits.get((sid, start))
        notional = F(buy['shares_delta'])*F(buy['price'])
        buy_fee = F(buy['fees'])
        need(abs(float(notional+buy_fee+F(buy['cash_delta']))) < 1e-7
             and math.isclose(float(buy_fee/notional), .001, abs_tol=1e-12), 'ORIGINAL_RECORDED_BUY_FEE_CALIBRATION')
        closes, openings, owned_days = [], [], []
        for row in daily[axis[start]:axis[boundary]+1]:
            day, audit = row['session'], row['evidence']['research_entry_audit']
            if day > start and (not ending or day < boundary):
                value = reader.position_value(audit['opening_accounting'], buy, opening=True)
                if value is not None:
                    openings.append((day, value, F(audit['opening_accounting']['prices'][sid]['raw_price'])))
            if not ending or day < boundary:
                owned_days.append(day)
                value = reader.position_value(audit['closing_accounting'], buy)
                if value is not None:
                    closes.append((day, value))
        if ending:
            exit_fee = F(ending['fees'])
            gross = (F(-ending['shares_delta'])*F(ending['price']) if ending['event_type'] == 'SELL'
                     else F(ending['cash_delta'])+exit_fee)
            need(gross > 0 and abs(float(gross-exit_fee-F(ending['cash_delta']))) < 1e-7, 'ORIGINAL_EXIT_LEDGER_CALIBRATION')
            exit_rate = exit_fee/gross
            actual_end_value = F(ending['cash_delta'])
        else:
            ratio = reader.position_value(daily[-1]['evidence']['research_entry_audit']['closing_accounting'], buy, allow_carried=True)
            need(ratio is not None, 'ORIGINAL_OPEN_END_MARK')
            gross, exit_rate = notional*ratio, Fraction(0)
            actual_end_value = gross
        terminal_ratio = gross/notional
        need(abs(100*float(terminal_ratio-1)-old['baseline_price_return_pct']) < 1e-8, 'UNCHANGED_REFERENCE_TERMINAL_PRICE')
        need(not any(e['security_id'] == sid and e['detail']['accrued_session'] == start for e in paid),
             'NO_AMBIGUOUS_ENTRY_DAY_DIVIDEND_RIGHT')
        dividends = [(e['detail']['accrued_session'], F(e['cash_delta'])) for e in paid
                     if e['security_id'] == sid and start < e['detail']['accrued_session'] <= boundary]
        calc = staged_trade(entry=start, notional=notional, buy_fee=buy_fee, raw_entry=buy['price'],
            closes=closes, openings=openings, terminal_ratio=terminal_ratio,
            exit_fee_rate=exit_rate, dividends=dividends, owned_days=owned_days,
            exit_day=boundary if ending else None)
        actual_profit = actual_end_value+sum((amount for _, amount in dividends), Fraction(0))+F(buy['cash_delta'])
        need(abs(float(calc['baseline_profit']-actual_profit)) < 1e-7, 'FULL_SIZE_ORIGINAL_CASH_DIVIDEND_FEE_RECONCILIATION')
        records.append(dict(ticker=old['ticker'], security_id=sid, entry=start, original_boundary=boundary,
            state=old['state'], entry_volatility=old['entry_volatility'], original_all_in_budget=float(calc['budget']),
            baseline_normalized_profit=float(calc['baseline_profit']*scale),
            staged_normalized_profit=float(calc['staged_profit']*scale),
            normalized_profit_difference=float(calc['difference']*scale),
            normalized_price_only_difference=float((calc['staged_price_profit']-calc['baseline_price_profit'])*scale),
            baseline_net_return_pct=100*float(calc['baseline_profit']/calc['budget']),
            staged_net_return_pct=100*float(calc['staged_profit']/calc['budget']),
            baseline_budget_session_dollars=float(calc['baseline_capital_days']),
            staged_budget_session_dollars=float(calc['staged_capital_days']),
            baseline_dividends=float(calc['baseline_dividends']*scale),
            staged_dividends=float(calc['staged_dividends']*scale),
            unused_budget=float(calc['unused_budget']*scale),
            funded_stages=len(calc['tranches']), one_share_unaffordable=calc['one_share_unaffordable'],
            starter_one_share_unaffordable=calc['starter_one_share_unaffordable'],
            tranches=plain(calc['tranches']), unfilled=plain(calc['unfilled'])))
    need(len(records) == 153, 'COMPLETE_SAME_SUPPORTED_ENTRY_COHORT')
    summaries = {}
    for name, chosen in (('all_supported', records), ('entry_volatility_at_least_50pct', [r for r in records if r['entry_volatility'] >= .5])):
        summaries[name] = {group: summarize([r for r in chosen if predicate(r)]) for group, predicate in (
            ('all', lambda r: True), ('closed_net_losers', lambda r: r['state'] == 'closed_sell' and r['baseline_normalized_profit'] < 0),
            ('closed_net_winners', lambda r: r['state'] == 'closed_sell' and r['baseline_normalized_profit'] > 0),
            ('open_marked', lambda r: r['state'] == 'open_marked'), ('closed_cash', lambda r: r['state'] == 'closed_cash'))}
    blocks = {name: summarize([r for r in records if begin <= r['entry'] <= end]) for name, begin, end in (
        ('entries_2018_2020', '2018-01-01', '2020-12-31'), ('entries_2021_to_cutoff', '2021-01-01', '2022-09-30'))}
    return dict(schema='research.core-staged-sizing-diagnostic/1', status=STATUS, diagnostic_only=True,
        financial_continuation_authorized=False, canonical_runtime_executed=False, new_core_books=0,
        parent_checkpoint_sha256=reader.PARENT, through=cp['source_cursor'], measured_entries=155,
        coverage=reference['coverage'], original_30pct_exit_calibration_passed=True,
        original_trailing_sales_calibrated=reference['original_trailing_sales_calibrated'],
        original_cash_fee_dividend_endpoints_calibrated=len(records), original_exits_unchanged=True,
        rule=dict(cumulative_budget_fractions=['0.20', '0.50', '1.00'], gain_gates=['0.10', '0.20'],
                  trailing_stop_unchanged='0.30', next_available_open=True, no_exit_day_adds=True,
                  fractional_units=True, unused_cash_interest=0),
        summaries=summaries, entry_date_blocks=blocks,
        largest_differences=sorted(records, key=lambda r: -abs(r['normalized_profit_difference']))[:15],
        records=records, limitations=['Fixed original entries/budgets/exit dates; no portfolio replacement, reinvestment, changed future sizing or re-entry.',
            'Observed dividends and recorded proportional transaction fees included; all unused budget earns zero.',
            'Fractional economic units; whole-share affordability is disclosed but not enforced.',
            'Dollar sums normalize original entries to a50000 anchor, not a counterfactual final NAV or CAGR.',
            'Capital-duration fractions are relative to these original holding windows, not portfolio exposure.',
            'Open holdings are censored at September30,2022; two stock-delivery lineages excluded; known-history exploratory study.'])
