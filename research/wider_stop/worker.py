"""Hosted-only paired exit diagnostic, never a strategy or account replay."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.abc
import json
import math
import os
from pathlib import Path
import sys


def need(condition, code):
    if not condition:
        raise ValueError(code)


def hosted():
    need(os.environ.get('WIDER_STOP_HOSTED') == '1'
         and Path(__file__).resolve() == Path('/current/research/wider_stop/worker.py'),
         'HOSTED_WIDER_STOP_DIAGNOSTIC_ONLY')
    forbidden = ('GH_TOKEN', 'GITHUB_TOKEN', 'CAPITAL_RISK_RESEARCH_KEY_20261027',
        'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY',
        'DATABASE_URL', 'PGPASSWORD', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'OPENAI_API_KEY')
    need(not any(os.environ.get(key) for key in forbidden), 'NO_FINANCIAL_CREDENTIALS')
    route = Path('/proc/net/route')
    need(route.is_file() and not any(line.split()[0] != 'lo' for line in
        route.read_text().splitlines()[1:] if line.split()), 'OFFLINE_CONTAINER_ONLY')


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_', 'numpy', 'pandas')):
            raise AssertionError('FORBIDDEN_DIAGNOSTIC_IMPORT:'+fullname)


hosted()
sys.meta_path.insert(0, NoCanonical())
from fractions import Fraction as F
from data import load_original, load_corpus, encoded, digest, file_sha

ARMS = ('0.30', '0.35', '0.40')


def number(value):
    need(type(value) in (str, int, float, F), 'FINITE_NUMERIC_SCALAR')
    return value if isinstance(value, F) else F(str(value))


def csv_number(value):
    parsed = float(value)
    need(math.isfinite(parsed), 'FINITE_SOURCE_BINARY64')
    return F(str(parsed))


def value(point):
    need(point['price_status'] == 'CURRENT', 'CURRENT_ORIGINAL_CLOSE')
    return number(point['episode']['current_shares']) * number(point['raw_close'])


def activation(ep):
    return next((point for point in ep['observations']
                 if value(point)/number(point['nav']) >= F('0.10')), None)


def calibrate(ep, axis):
    need(len(ep['sids']) == len(ep['tickers']) == 1, 'ORDINARY_SINGLE_SECURITY')
    first = ep['observations'][0]['episode']
    unit = number(first['initial_shares'])*number(first['entry_raw_open'])/number(first['entry_split_adjusted_price'])
    need(unit > 0, 'POSITIVE_SOURCE_UNIT')
    previous_q, previous_peak, signal = None, None, None
    for point in ep['observations']:
        item = point['episode']
        peak = unit*number(item['episode_peak_split_adjusted_close'])
        q = number(item['current_shares'])
        need(item['security_id'] == ep['sids'][0] and item['slot_id'] == ep['slot_id']
             and item['signal_date'] == ep['signal_date'] and item['entry_date'] == ep['entry_date'],
             'EXACT_SOURCE_LINEAGE')
        need(number(item['initial_shares'])*number(item['entry_raw_open'])
             /number(item['entry_split_adjusted_price']) == unit, 'FIXED_SPLIT_ADJUSTED_SHARE_UNIT')
        current = value(point)
        need(q > 0 and current > 0 and number(point['nav']) > 0 and peak > 0,
             'POSITIVE_ORIGINAL_STOCK_AND_NAV')
        need(previous_peak is None or peak >= previous_peak, 'MONOTONE_ORIGINAL_PEAK')
        need(abs(current/peak-1-number(point['own_dd'])) <= F('0.000000000001'),
             'CANONICAL_RAW_PEAK_DOMAIN_COHERENCE')
        if previous_q is not None and q != previous_q:
            splits = [event for event in ep['source_events']
                if event['event_type'] == 'SPLIT' and event['session'] == point['session']]
            need(len(splits) == 1 and q == previous_q*number(splits[0]['detail']['ratio']),
                 'AUTHENTICATED_SPLIT_QUANTITY_CONTINUITY')
        if signal is None and current <= peak*F('0.70'):
            signal = point['session']
        previous_q, previous_peak = q, peak
    need(all(event['event_type'] in ('BUY', 'SELL', 'SPLIT', 'DIVIDEND_ACCRUED', 'DIVIDEND_PAID')
             for event in ep['source_events']), 'SUPPORTED_ORIGINAL_ACTIONS_ONLY')
    sale = ep['original_sell']
    if sale is None:
        need(ep['endpoint_kind'] == 'END_MARK' and ep['endpoint_session'] == axis[-1]
             and (signal is None or signal == axis[-1]), 'ORIGINAL_OPEN_REFERENCE')
    else:
        need(sale['reason'] == 'EXIT_TRAILING_STOP' and signal is not None
             and axis[axis.index(signal)+1] == sale['session'] == ep['endpoint_session'],
             'EXACT_ORIGINAL_30_SIGNAL_FILL')
        opens = [p for p in ep['openings'] if p['session'] == sale['session']]
        need(len(opens) == 1 and opens[0]['price_status'] == 'RAW_OPEN'
             and number(opens[0]['raw_open']) == number(sale['price'])
             and number(opens[0]['episode']['current_shares']) == -number(sale['shares_delta']),
             'EXACT_ORIGINAL_RAW_OPEN_QUANTITY')
        gross = -number(sale['shares_delta'])*number(sale['price'])
        need(abs(gross/1000-number(sale['fees'])) <= F('0.0000001')
             and abs(gross*F('0.999')-number(sale['cash_delta'])) <= F('0.0000001'),
             'ORIGINAL_10BP_SALE_FEE')
    return unit


def dividends(ep):
    claims = [event for event in ep['source_events'] if event['event_type'] == 'DIVIDEND_ACCRUED']
    need(len({(event['session'], event['security_id']) for event in claims}) == len(claims),
         'NO_DUPLICATED_ORIGINAL_DIVIDEND')
    for event in claims:
        amount = number(event['detail']['amount'])
        need(amount >= 0 and abs(amount-number(event['price'])*number(event['detail']['shares']))
             <= F('0.0000001'), 'ORIGINAL_ENTITLEMENT_CORROBORATION')
    return sum((number(event['detail']['amount']) for event in claims), F(0))


def extension(ep, corpus, axis):
    sale = ep['original_sell']
    if sale is None:
        return [], axis[-1], False
    start = axis.index(sale['session'])
    complete = start+60 < len(axis)
    end = min(start+60, len(axis)-1)
    days, sid = axis[start:end+1], ep['sids'][0]
    quotes = corpus['quotes'][sid]
    need(csv_number(quotes[axis[start-1]]['raw_close']) == number(ep['observations'][-1]['raw_close']),
         'ORIGINAL_LAST_HELD_CLOSE_RAW_BRIDGE')
    actions = [row for row in corpus['actions'] if row['security_id'] == sid
               and days[0] <= row['effective_session'] <= days[-1]]
    need(not [row for row in corpus['terminals'] if row['security_id'] == sid
              and days[0] <= row['effective_session'] <= days[-1]], 'NO_UNSUPPORTED_TERMINAL')
    need(len({(row['effective_session'], row['action']) for row in actions}) == len(actions),
         'UNIQUE_ACTION_IDENTITY')
    q = number(ep['observations'][-1]['episode']['current_shares'])
    points = []
    for day in days:
        row = quotes[day]
        need(row['session'] == day and row['security_id'] == sid
             and row['tradeable'] in ('1', 'True', 'true'), 'EXACT_TRADEABLE_QUOTE')
        opening, closing = csv_number(row['raw_open']), csv_number(row['raw_close'])
        split, dividend = csv_number(row['split_ratio']), csv_number(row['dividend_per_share'])
        need(opening > 0 and closing > 0 and split == 1 and dividend >= 0,
             'POSITIVE_RAW_QUOTE_NO_UNQUALIFIED_EXTENSION_SPLIT')
        effective = [action for action in actions if action['effective_session'] == day]
        for action in effective:
            need(action['known_by'] <= day and action['action'] == 'dividend'
                 and csv_number(action['canonical_value']) > 0, 'KNOWN_SUPPORTED_ACTION')
            if action['action'] == 'dividend':
                need(action['disposition'] == 'RAW_SHARE_DOMAIN_CONVERTED'
                     and action['authority'] == 'PIT_ACTIONS_PLUS_SAME_SESSION_PRICE_DOMAIN'
                     and csv_number(action['canonical_value']) == dividend, 'QUALIFIED_RAW_SHARE_DIVIDEND')
            else:
                need(csv_number(action['canonical_value']) == split, 'QUALIFIED_EFFECTIVE_SPLIT')
        need((split == 1) == (not any(a['action'] == 'split' for a in effective))
             and (dividend == 0) == (not any(a['action'] == 'dividend' for a in effective)),
             'NO_UNEXPLAINED_ACTION_OR_PRICE_DOMAIN')
        q *= split
        points.append(dict(session=day, index=axis.index(day), shares=q,
                           raw_open=opening, raw_close=closing, dividend=dividend))
    need(points[0]['shares'] == -number(sale['shares_delta'])
         and points[0]['raw_open'] == number(sale['price']), 'ARCHIVE_ORIGINAL_RAW_SALE_CORROBORATION')
    window = corpus['windows'][ep['key']]
    need(window['sessions'] == days and window['complete_followup'] == complete
         and window['endpoint_session'] == axis[end], 'FIXED_60_SOURCE_SESSION_WINDOW')
    return points, axis[end], complete


def source_scan(ep, distance, unit, active):
    level, signal, peak, armed = None, None, None, False
    trace = []
    for point in ep['observations']:
        peak = unit*number(point['episode']['episode_peak_split_adjusted_close'])
        if point['session'] == active['session']:
            armed, level = True, None
        proposed = peak*(1-(distance if armed else F('0.30')))
        level = proposed if level is None else max(level, proposed)
        breach = value(point) <= level
        trace.append(dict(session=point['session'], phase='CLOSE',
            shares=str(number(point['episode']['current_shares'])), raw_price=str(number(point['raw_close'])),
            peak_value=str(peak), stop_value_floor=str(level), signal=breach))
        if breach:
            signal = point['session']
            break
    return peak, level, signal, trace


def evaluate(ep, corpus, axis, distance, episodes):
    distance = number(distance)
    need(distance in map(number, ARMS), 'THREE_PREDECLARED_ARMS')
    unit, active = calibrate(ep, axis), activation(ep)
    need(active is not None, 'ELIGIBLE_CONCENTRATED_SOURCE_EPISODE')
    common, sale = dividends(ep), ep['original_sell']
    points, endpoint, complete = extension(ep, corpus, axis)
    peak, level, signal, trace = source_scan(ep, distance, unit, active)
    fill, held, extra_div = None, [], F(0)
    worst, minimum_return, stock_return = None, None, None
    if sale is None:
        need(signal is None or signal == axis[-1], 'NO_EARLIER_OPEN_REFERENCE_EXIT')
        signal = None
        last = ep['observations'][-1]
        q, raw = number(last['episode']['current_shares']), number(last['raw_close'])
        gross, fee, original_fee = q*raw, F(0), F(0)
        base_net = gross
        reason, classification = 'OPEN_REFERENCE', 'OPEN_REFERENCE'
    else:
        original_gross = -number(sale['shares_delta'])*number(sale['price'])
        original_fee = original_gross/1000
        base_net = original_gross-original_fee
        for point in points:
            day = point['session']
            if day > sale['session']:
                extra_div += point['shares']*point['dividend']
            if signal is not None:
                need(point['index'] == axis.index(signal)+1, 'AUTHENTICATED_NEXT_OPEN_ONLY')
                fill, reason = point, 'TRAILING_STOP'
                break
            if complete and day == endpoint:
                fill, reason = point, 'FORCED_HORIZON'
                break
            close = point['shares']*point['raw_close']
            peak = max(peak, close)
            level = max(level, peak*(1-distance))
            held.append(point)
            current_dd, relative = close/peak-1, close/original_gross-1
            worst = current_dd if worst is None else min(worst, current_dd)
            minimum_return = relative if minimum_return is None else min(minimum_return, relative)
            breach = close <= level
            trace.append(dict(session=day, phase='CLOSE', shares=str(point['shares']),
                raw_price=str(point['raw_close']), peak_value=str(peak),
                stop_value_floor=str(level), signal=breach))
            if breach:
                signal = day
        classification = 'COMPLETE' if complete else 'CENSORED'
        if fill is None:
            need(not complete, 'FULL_HORIZON_MUST_LIQUIDATE_AT_OPEN')
            last = points[-1]
            q, raw, fee, reason = last['shares'], last['raw_close'], F(0), 'CENSORED_MARK'
        else:
            q, raw = fill['shares'], fill['raw_open']
            fee = q*raw/1000
        gross = q*raw
        stock_return = gross/original_gross-1
    terminal, baseline = gross-fee+common+extra_div, base_net+common
    delta = terminal-baseline
    if distance == F('0.30'):
        need(delta == 0 and (sale is None or fill is not None and fill['session'] == sale['session']),
             'ORIGINAL_30_CONTROL_EXACT_ZERO:'+ep['key'])
    result = dict(key=ep['key'], ticker=ep['tickers'][0], security_id=ep['sids'][0], slot_id=ep['slot_id'],
        signal_date=ep['signal_date'], entry_date=ep['entry_date'], anchor_held=ep['anchor_held'],
        activation_session=active['session'], activation_nav=str(number(active['nav'])),
        original_signal_session=ep['observations'][-1]['session'] if sale else None,
        original_sale_session=sale['session'] if sale else None,
        original_sale_shares=str(-number(sale['shares_delta'])) if sale else None,
        original_sale_raw_open=str(number(sale['price'])) if sale else None,
        classification=classification, complete_followup=complete,
        followup_sessions_available=len(points)-1 if sale else 0,
        endpoint_session=endpoint, endpoint_phase='OPEN' if complete else 'CLOSE',
        signal_session=signal, fill_session=fill['session'] if fill else None, exit_reason=reason,
        exit_shares=str(q), exit_raw_price=str(raw), exit_gross_value=str(gross), exit_fee=str(fee),
        original_exit_fee=str(original_fee), original_dividends=str(common),
        post_original_exit_dividends=str(extra_div), candidate_dividends=str(common+extra_div),
        baseline_terminal_value=str(baseline), terminal_value=str(terminal), net_difference=str(delta),
        normalized_difference=str(delta/number(active['nav'])), additional_occupied_sessions=len(held),
        max_close_drawdown_fraction=str(worst) if worst is not None else None,
        minimum_close_return_from_original_sale=str(minimum_return) if minimum_return is not None else None,
        stock_gross_return_from_original_sale_to_exit=str(stock_return) if stock_return is not None else None,
        trace=trace, trace_sha256=digest(trace))
    replacements = []
    if sale and held:
        last_held = held[-1]['session']
        replacements = [dict(key=other['key'], ticker=other['tickers'][0], entry_date=other['entry_date'])
            for other in episodes.values() if other['slot_id'] == ep['slot_id']
            and other['key'] != ep['key'] and sale['session'] <= other['entry_date'] <= last_held]
    result['replacement_opportunity'] = dict(status='UNAVAILABLE' if replacements else 'NO_DIRECT_REPLACEMENT',
        identities=sorted(replacements, key=lambda item: (item['entry_date'], item['key'])),
        reason='PAIRED_RETURNS_UNAVAILABLE' if replacements else 'NO_ENTRY_DURING_DELAY')
    return result


def stats(records):
    changes = [number(row['net_difference']) for row in records]
    scores = sorted(number(row['normalized_difference']) for row in records)
    count = len(scores)
    median = (scores[count//2] if count % 2 else (scores[count//2-1]+scores[count//2])/2) if count else None
    return dict(count=count, wins=sum(v > 0 for v in changes), losses=sum(v < 0 for v in changes),
        ties=sum(v == 0 for v in changes), total_net_difference=str(sum(changes, F(0))),
        mean_normalized_difference=str(sum(scores, F(0))/count) if count else None,
        median_normalized_difference=str(median) if median is not None else None)


def summary(records):
    complete = [row for row in records if row['classification'] == 'COMPLETE']
    output = dict(complete=stats(complete), censored=stats([r for r in records if r['classification']=='CENSORED']),
        open_reference=stats([r for r in records if r['classification']=='OPEN_REFERENCE']), all_episodes=stats(records))
    output['complete']['blocks'] = {label: stats([row for row in complete if low <= row['original_sale_session'] <= high])
        for label, low, high in [('2018-20','2018-01-01','2020-12-31'),
                                ('2021-23','2021-01-01','2023-12-31'), ('2024-26','2024-01-01','2026-12-31')]}
    best = max(complete, key=lambda r: (number(r['normalized_difference']), r['key']))
    rest = [row for row in complete if row['key'] != best['key']]
    remaining = stats(rest)
    output['complete']['leave_best_out'] = dict(omitted_key=best['key'],
        omitted_normalized_difference=best['normalized_difference'], count=len(rest),
        mean_normalized_difference=remaining['mean_normalized_difference'],
        total_net_difference=remaining['total_net_difference'])
    return output


def failure_required(call, name):
    try:
        call()
    except (ValueError, KeyError, TypeError, AssertionError):
        return
    raise ValueError('UNDETECTED_FALSIFIER:'+name)


def synthetics(selected, corpus, axis, source):
    ep = next(item for item in selected if item['original_sell'])
    altered = deepcopy(ep)
    altered['original_sell']['price'] = str(number(altered['original_sell']['price'])+1)
    failure_required(lambda: calibrate(altered, axis), 'ALTERED_RECORDED_FILL')
    altered = deepcopy(ep)
    altered['observations'][0]['episode']['entry_split_adjusted_price'] = '1'
    failure_required(lambda: calibrate(altered, axis), 'WRONG_RAW_ADJUSTED_SPLIT_UNIT')
    missing = deepcopy(corpus)
    del missing['quotes'][ep['sids'][0]][ep['endpoint_session']]
    failure_required(lambda: evaluate(ep, missing, axis, '0.35', source['episodes']), 'MISSING_NEXT_OPEN')
    future = deepcopy(corpus)
    future['quotes'][ep['sids'][0]][ep['endpoint_session']]['session'] = axis[-1]+'FUTURE'
    failure_required(lambda: extension(ep, future, axis), 'FUTURE_OPEN_SUBSTITUTION')
    dividend_ep = next(item for item in selected if any(a['security_id'] == item['sids'][0]
                        and a['action']=='dividend' for a in corpus['actions']))
    malformed = deepcopy(corpus)
    next(a for a in malformed['actions'] if a['security_id']==dividend_ep['sids'][0]
         and a['action']=='dividend')['canonical_value'] = '999'
    failure_required(lambda: extension(dividend_ep, malformed, axis), 'UNQUALIFIED_DIVIDEND')
    fixture_checks()
    return dict(status='PASSED', source_falsifiers=5,
        fixture_falsifiers=['retained_30_cap','same_original_open_breach','post_exit_peak_ratchet',
            'sale_ex_date_dividend','forced_open_phase','insufficient_followup','split_unit_continuity'])


def fixture_checks():
    axis = ['2020-01-'+str(i).zfill(2) for i in range(1,66)]
    def point(day, raw, peak, q=1, split_entry=100, own_dd=None):
        item = dict(security_id='SID', ticker='TEST', slot_id='SLOT', signal_date=axis[0], entry_date=axis[0],
            current_shares=q, initial_shares=1, entry_raw_open=100, entry_split_adjusted_price=split_entry,
            episode_peak_split_adjusted_close=peak)
        return dict(session=day, index=axis.index(day), episode=item, price_status='CURRENT',
            raw_close=raw, nav=500, own_dd=str(F(str(q))*number(raw)/(100/number(split_entry)*number(peak))-1)
                if own_dd is None else own_dd)
    observations = [point(axis[0],100,100), point(axis[1],69,100)]
    observations[0]['nav'] = 2000
    sale = dict(session=axis[2], reason='EXIT_TRAILING_STOP', price=70, shares_delta=-1,
        fees='0.07', cash_delta='69.93')
    opening = dict(session=axis[2], price_status='RAW_OPEN', raw_open=70,
        episode=deepcopy(observations[-1]['episode']))
    ep = dict(key='SLOT|'+axis[0],slot_id='SLOT',signal_date=axis[0],entry_date=axis[0],sids=['SID'],
        tickers=['TEST'],anchor_held=False, observations=observations, openings=[opening],
        source_events=[],original_sell=sale,endpoint_session=axis[2],endpoint_kind='SELL')
    quotes = {axis[1]:dict(session=axis[1],security_id='SID',tradeable='1',raw_close='69')}
    for day in axis[2:63]:
        quotes[day] = dict(session=day,security_id='SID',tradeable='1',raw_open='80',raw_close='80',
                           split_ratio='1',dividend_per_share='0')
    quotes[axis[2]]['raw_open'] = '70'
    corpus = dict(quotes={'SID':quotes},actions=[],terminals=[],windows={ep['key']:dict(
        sessions=axis[2:63],complete_followup=True,endpoint_session=axis[62])})
    mapping = {ep['key']:ep}
    a = evaluate(ep,corpus,axis,'0.35',mapping)
    need(a['fill_session']==axis[62] and a['exit_reason']=='FORCED_HORIZON'
         and a['additional_occupied_sessions']==60 and number(a['exit_raw_price'])==80,
         'FIXTURE_RETAINED_30_CAP_OR_ENDPOINT')
    capped = deepcopy(ep)
    capped['observations'][1] = point(axis[1],64,100)
    same = deepcopy(corpus)
    same['quotes']['SID'][axis[1]]['raw_close'] = '64'
    b = evaluate(capped,same,axis,'0.35',{capped['key']:capped})
    need(b['fill_session']==axis[2] and number(b['net_difference'])==0, 'FIXTURE_SAME_OPEN_WIDER_BREACH')
    ratchet = deepcopy(corpus)
    ratchet['quotes']['SID'][axis[2]]['raw_close'] = '200'
    ratchet['quotes']['SID'][axis[3]]['raw_close'] = '129'
    ratchet['quotes']['SID'][axis[4]]['raw_open'] = '125'
    claim = dict(effective_session=axis[4],security_id='SID',action='dividend',canonical_value='2',
        known_by=axis[4],disposition='RAW_SHARE_DOMAIN_CONVERTED',authority='PIT_ACTIONS_PLUS_SAME_SESSION_PRICE_DOMAIN')
    ratchet['actions'] = [claim]
    ratchet['quotes']['SID'][axis[4]]['dividend_per_share'] = '2'
    c = evaluate(ep,ratchet,axis,'0.35',mapping)
    need(c['signal_session']==axis[3] and c['fill_session']==axis[4]
         and number(c['post_original_exit_dividends'])==2 and c['additional_occupied_sessions']==2,
         'FIXTURE_POST_EXIT_PEAK_OR_SALE_EX_DATE')
    endpoint = deepcopy(corpus)
    endpoint['quotes']['SID'][axis[62]]['raw_close'] = '1'
    d = evaluate(ep,endpoint,axis,'0.40',mapping)
    need(d['exit_reason']=='FORCED_HORIZON' and number(d['exit_raw_price'])==80,
         'FIXTURE_FORCED_OPEN_BEFORE_ENDPOINT_CLOSE')
    short_axis = axis[:7]
    short = deepcopy(corpus)
    short['windows'][ep['key']] = dict(sessions=short_axis[2:],complete_followup=False,endpoint_session=short_axis[-1])
    short['quotes']['SID'][short_axis[-1]]['raw_close'] = '60'
    e = evaluate(ep,short,short_axis,'0.35',mapping)
    need(e['classification']=='CENSORED' and e['exit_reason']=='CENSORED_MARK'
         and e['fill_session'] is None and number(e['exit_fee'])==0
         and e['signal_session']==short_axis[-1], 'FIXTURE_LAST_CLOSE_NO_FUTURE_FILL')
    split = deepcopy(ep)
    split['observations'][0] = point(axis[0],50,100,q=2,split_entry=100)
    split['observations'][1] = point(axis[1],F('34.5'),100,q=2,split_entry=100)
    split['openings'][0]['episode']['current_shares'] = 2
    split['openings'][0]['raw_open'] = 35
    split['original_sell'].update(price=35,shares_delta=-2)
    need(calibrate(split,axis)==1, 'FIXTURE_RAW_SPLIT_UNIT_VALUE')
    mutant = deepcopy(split)
    mutant['observations'][1]['episode']['current_shares'] = 1
    mutant['observations'][1]['own_dd'] = str(F('34.5')/100-1)
    failure_required(lambda: calibrate(mutant,axis), 'UNAUTHENTICATED_SPLIT_CHANGE')


def main():
    parser = argparse.ArgumentParser()
    for name in ('book','archive','bundle','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    hosted()
    source = load_original(args.book)
    axis = [row['session'] for row in source['rows']]
    selected = [ep for ep in source['episodes'].values() if activation(ep) is not None]
    selected.sort(key=lambda ep:ep['key'])
    need(len(selected)==17, 'FIXED_17_CONCENTRATED_SOURCE_EPISODES')
    corpus = load_corpus(args.archive,args.bundle,source,[ep['key'] for ep in selected])
    proofs = synthetics(selected,corpus,axis,source)
    arms = {}
    for label in ARMS:
        outcomes = [evaluate(ep,corpus,axis,label,source['episodes']) for ep in selected]
        arms[label] = dict(stop_distance=label,episodes=outcomes,summary=summary(outcomes))
    counts = arms['0.30']['summary']
    need(counts['complete']['count']==13 and counts['censored']['count']==3
         and counts['open_reference']['count']==1, 'FROZEN_FOLLOWUP_COVERAGE_13_3_1')
    ranking = sorted(ARMS,key=lambda label:(-number(arms[label]['summary']['complete']['mean_normalized_difference']),
                                          number(label)))
    report = dict(status='WIDER_STOP_DIAGNOSTIC_COMPLETE',identity=source['identity'],
        corpus_identity=corpus['corpus_identity'],source_sha256=file_sha(Path(__file__)),
        arms=arms,ranking=list(ranking),best_in_this_screen=ranking[0],proofs=proofs,
        limitations=['FIXED_CONCENTRATED_COHORT','NO_PORTFOLIO_CAGR_OR_DRAWDOWN',
            'NO_REPLACEMENT_CAPITAL_REPLAY','CENSORED_NOT_PRIMARY','NO_OPTIMUM_OR_DEPLOYMENT_CLAIM'])
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'report.json').write_bytes(encoded(report))
    (args.out/'source-inventory.json').write_bytes(encoded(dict(windows=corpus['windows'],
        quotes=corpus['quotes'],actions=corpus['actions'],terminals=corpus['terminals'],
        identity=corpus['corpus_identity'])))
    print('WIDER_STOP_DIAGNOSTIC_COMPLETE')


if __name__ == '__main__':
    main()
