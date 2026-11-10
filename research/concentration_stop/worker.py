"""Hosted-only concentrated-episode exit screen; never a strategy/account book."""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction as F
import importlib.abc
import json
import os
from pathlib import Path
import statistics
import sys

from data import load_book, encoded, digest, file_sha, need

FLOORS = ('0.30', '0.06', '0.10', '0.15', '0.20', '0.25')
BLOCKS = ('2018-20', '2021-23', '2024-26')


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_', 'numpy', 'pandas')):
            raise AssertionError('FORBIDDEN_DIAGNOSTIC_IMPORT:'+fullname)


def hosted():
    need(os.environ.get('CONCENTRATION_STOP_HOSTED') == '1'
         and Path(__file__).resolve() == Path('/current/research/concentration_stop/worker.py'),
         'HOSTED_STOP_DIAGNOSTIC_ONLY')
    forbidden = ('GH_TOKEN', 'GITHUB_TOKEN', 'CAPITAL_RISK_RESEARCH_KEY_20261027',
                 'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY',
                 'DATABASE_URL', 'PGPASSWORD', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'OPENAI_API_KEY')
    need(not any(os.environ.get(k) for k in forbidden), 'NO_FINANCIAL_CREDENTIALS')
    route = Path('/proc/net/route')
    need(route.is_file() and not any(line.split()[0] != 'lo' for line in
         route.read_text().splitlines()[1:] if line.split()), 'OFFLINE_CONTAINER_ONLY')


def fraction(value):
    need(type(value) in (str, int, float, F), 'SCALAR_NUMBER')
    return value if isinstance(value, F) else F(str(value))


def position_value(observation):
    hosted()
    need(observation['price_status'] == 'CURRENT' and observation['raw_close'] is not None,
         'CURRENT_RAW_CLOSE_REQUIRED')
    quantity, price = fraction(observation['episode']['current_shares']), fraction(observation['raw_close'])
    need(quantity > 0 and price > 0, 'POSITIVE_OWNED_STOCK')
    return quantity * price


def validate_episode(ep):
    hosted()
    observations = ep['observations']
    need(len(ep['sids']) == 1 and ep['endpoint_kind'] in ('SELL', 'END_MARK'),
         'ORDINARY_SINGLE_SECURITY_EPISODE_REQUIRED')
    initial = observations[0]['episode']
    unit = (fraction(initial['initial_shares']) * fraction(initial['entry_raw_open'])
            / fraction(initial['entry_split_adjusted_price']))
    need(unit > 0, 'POSITIVE_SOURCE_UNIT')
    for event in ep['source_events']:
        need(event['event_type'] in ('BUY', 'SELL', 'DIVIDEND_ACCRUED', 'DIVIDEND_PAID', 'SPLIT'),
             'NO_UNSUPPORTED_MATERIAL_ACTION')
        if event['event_type'] == 'SPLIT':
            need(initial['ticker'] == 'AGNT' and fraction(event['detail']['ratio']) == 2
                 and fraction(event['cash_delta']) == 0, 'ONLY_DECLARED_AGNT_PURE_SPLIT')
    prior = None
    for observation in observations:
        current = observation['episode']
        need(current['security_id'] == ep['sids'][0] and current['slot_id'] == ep['slot_id']
             and current['signal_date'] == ep['signal_date'] and current['entry_date'] == ep['entry_date'],
             'SOURCE_CAUSAL_IDENTITY')
        need(fraction(current['initial_shares']) * fraction(current['entry_raw_open'])
             / fraction(current['entry_split_adjusted_price']) == unit, 'FIXED_SOURCE_SHARE_UNIT')
        value = position_value(observation)
        peak = unit * fraction(current['episode_peak_split_adjusted_close'])
        need(peak > 0 and observation['own_dd'] is not None
             and abs(value / peak - 1 - fraction(observation['own_dd'])) <= F('0.000000000001'),
             'CANONICAL_PEAK_RAW_PRICE_DOMAIN_COHERENCE')
        quantity = fraction(current['current_shares'])
        if prior is not None and quantity != prior:
            splits = [e for e in ep['source_events'] if e['event_type'] == 'SPLIT'
                      and e['session'] == observation['session']]
            need(len(splits) == 1 and quantity == prior * fraction(splits[0]['detail']['ratio']),
                 'AUTHENTICATED_QUANTITY_CHANGE')
        prior = quantity
    if ep['endpoint_kind'] == 'SELL':
        sale = ep['original_sell']
        need(sale and sale['session'] == ep['endpoint_session'] and sale['reason'] == 'EXIT_TRAILING_STOP',
             'ORIGINAL_COMPLETED_STOP_ENDPOINT')
    return unit


def weight(observation):
    hosted()
    nav = fraction(observation['nav'])
    need(nav > 0, 'POSITIVE_SOURCE_NAV')
    return position_value(observation) / nav


def first_activation(ep):
    hosted()
    return next((ob for ob in ep['observations'] if weight(ob) >= F('0.10')), None)


def original_endpoint(ep):
    hosted()
    if ep['endpoint_kind'] == 'SELL':
        sale = ep['original_sell']
        quantity, price = -fraction(sale['shares_delta']), fraction(sale['price'])
        need(quantity > 0 and price > 0, 'SOURCE_ORIGINAL_SALE')
        gross = quantity * price
        fee = gross / 1000
        need(abs(fee - fraction(sale['fees'])) <= F('0.0000001')
             and abs(gross-fee-fraction(sale['cash_delta'])) <= F('0.0000001'),
             'ORIGINAL_TEN_BP_EXIT_COST_CORROBORATION')
        return gross-fee, fee, gross
    gross = position_value(ep['observations'][-1])
    return gross, F(0), gross


def dividend_records(ep):
    hosted()
    accruals = [e for e in ep['source_events'] if e['event_type'] == 'DIVIDEND_ACCRUED']
    need(len({(e['session'], e['security_id']) for e in accruals}) == len(accruals),
         'UNIQUE_SOURCE_DIVIDEND_ENTITLEMENT')
    for event in accruals:
        need(fraction(event['detail']['amount']) >= 0, 'NONNEGATIVE_SOURCE_DIVIDEND')
    return accruals


def scan(ep, floor, unit):
    hosted()
    floor = fraction(floor)
    activation, level, armed = first_activation(ep), None, False
    trace = []
    signal = None
    for observation in ep['observations']:
        value = position_value(observation)
        peak = unit * fraction(observation['episode']['episode_peak_split_adjusted_close'])
        if activation is not None and observation['session'] >= activation['session']:
            armed = True
        distance = F('0.30')
        if armed and floor < F('0.30'):
            distance = min(F('0.30'), max(floor, F('0.015') / weight(observation)))
        candidate = peak * (1 - distance)
        level = max(candidate, peak * F('0.70'), level if level is not None else F(0))
        trace.append(dict(session=observation['session'], current_value=str(value), peak_value=str(peak),
                          weight=str(weight(observation)), armed=armed, distance=str(distance),
                          stop_value_floor=str(level)))
        if value <= level:
            signal = observation
            break
    return signal, level if signal is not None else None, trace


def fill_after(ep, signal, rows):
    hosted()
    if signal is None or signal['index'] == len(rows)-1:
        return None
    expected = rows[signal['index']+1]['session']
    need(expected > signal['session'] and expected <= ep['endpoint_session'], 'NEXT_SOURCE_SESSION_ONLY')
    matches = [ob for ob in ep['openings'] if ob['session'] == expected]
    need(len(matches) == 1 and matches[0]['price_status'] == 'RAW_OPEN'
         and matches[0]['raw_open'] is not None, 'MISSING_AUTHENTICATED_NEXT_RAW_OPEN')
    opening = matches[0]
    quantity, price = fraction(opening['episode']['current_shares']), fraction(opening['raw_open'])
    need(quantity > 0 and price > 0, 'POSITIVE_EFFECTIVE_OPEN_FILL')
    gross = quantity * price
    return dict(session=expected, quantity=quantity, price=price, gross=gross, fee=gross/1000)


def evaluate(ep, floor, rows):
    hosted()
    unit = validate_episode(ep)
    activation = first_activation(ep)
    need(activation is not None, 'ELIGIBLE_EPISODE_ACTIVATION')
    signal, level, trace = scan(ep, floor, unit)
    fill = fill_after(ep, signal, rows)
    original_value, original_fee, original_gross = original_endpoint(ep)
    early = fill is not None and (fill['session'] < ep['endpoint_session']
        or ep['endpoint_kind'] == 'END_MARK' and fill['session'] == ep['endpoint_session'])
    dividends = dividend_records(ep)
    original_dividend = sum((fraction(e['detail']['amount']) for e in dividends), F(0))
    candidate_dividend = sum((fraction(e['detail']['amount']) for e in dividends
                              if not early or e['session'] <= fill['session']), F(0))
    exit_value = fill['gross']-fill['fee'] if fill is not None else original_value
    exit_fee = fill['fee'] if fill is not None else original_fee
    delta = exit_value+candidate_dividend-original_value-original_dividend
    if not early:
        need(delta == 0, 'NO_DIFFERENCE_WITHOUT_EARLIER_EXIT:'+ep['key']+':'+str(floor)+':'+str(delta))
    peak_after = None
    foregone = F(0)
    if early:
        later = [position_value(ob) for ob in ep['observations'] if ob['session'] >= fill['session']]
        peak_after = max([fill['gross'], original_gross] + later)
        foregone = max(F(0), peak_after/fill['gross']-1)
    largest = max(ep['observations'], key=weight)
    result = dict(key=ep['key'], ticker=ep['tickers'][-1], security_id=ep['sids'][0],
        slot_id=ep['slot_id'], signal_date=ep['signal_date'], entry_date=ep['entry_date'], anchor_held=ep['anchor_held'],
        activation_session=activation['session'], activation_nav=str(fraction(activation['nav'])),
        max_weight=str(weight(largest)), max_weight_session=largest['session'],
        endpoint_session=ep['endpoint_session'], endpoint_kind=ep['endpoint_kind'],
        original_signal_session=ep['observations'][-1]['session'] if ep['endpoint_kind']=='SELL' else None,
        signal_session=None if signal is None else signal['session'],
        fill_session=None if fill is None else fill['session'], early_exit=early,
        unexecuted_signal=signal is not None and fill is None,
        fill_shares=None if fill is None else str(fill['quantity']),
        fill_raw_open=None if fill is None else str(fill['price']),
        fill_gross_value=None if fill is None else str(fill['gross']),
        exit_value=str(exit_value), original_terminal_value=str(original_value), exit_fee=str(exit_fee),
        original_exit_fee=str(original_fee), original_dividends=str(original_dividend),
        candidate_dividends=str(candidate_dividend), net_difference=str(delta),
        normalized_difference=str(delta/fraction(activation['nav'])),
        floor_at_signal=None if level is None else str(level), source_unit_multiplier=str(unit),
        price_peak_after_exit=None if peak_after is None else str(peak_after),
        peak_position_value_after_exit=None if peak_after is None else str(peak_after),
        forgone_upside_fraction=str(foregone), trace_sha256=digest(trace), trace=trace)
    if fraction(floor) == F('0.30'):
        need(delta == 0 and not early, 'ZERO_INCREMENTAL_ORIGINAL_CONTROL')
        if ep['endpoint_kind'] == 'SELL':
            need(signal is not None and signal['session'] == result['original_signal_session']
                 and fill is not None and fill['session'] == ep['endpoint_session']
                 and fill['gross'] == original_gross, 'ORIGINAL_STOP_SIGNAL_FILL_CALIBRATION')
    return result


def stats(results):
    hosted()
    values = [fraction(r['normalized_difference']) for r in results]
    return dict(count=len(results), early_exits=sum(r['early_exit'] for r in results),
                wins=sum(fraction(r['net_difference']) > 0 for r in results),
                losses=sum(fraction(r['net_difference']) < 0 for r in results),
                ties=sum(fraction(r['net_difference']) == 0 for r in results),
                total_net_difference=str(sum((fraction(r['net_difference']) for r in results), F(0))),
                mean_normalized_difference=None if not values else str(sum(values,F(0))/len(values)),
                median_normalized_difference=None if not values else str(statistics.median(values)))


def summary(results):
    hosted()
    closed = [r for r in results if r['endpoint_kind']=='SELL']
    opened = [r for r in results if r['endpoint_kind']=='END_MARK']
    aggregate = stats(closed)
    aggregate['blocks'] = {}
    for block in BLOCKS:
        selected = [r for r in closed if ('2018-20' if r['endpoint_session'][:4]<='2020' else
                    '2021-23' if r['endpoint_session'][:4]<='2023' else '2024-26') == block]
        aggregate['blocks'][block] = stats(selected)
    best = max(closed, key=lambda r: (fraction(r['normalized_difference']), r['key']))
    excluded = [r for r in closed if r['key'] != best['key']]
    aggregate['leave_best_out'] = dict(omitted_key=best['key'],
        omitted_normalized_difference=best['normalized_difference'], count=len(excluded),
        mean_normalized_difference=stats(excluded)['mean_normalized_difference'],
        total_net_difference=stats(excluded)['total_net_difference'])
    return dict(closed=aggregate, open_marked=stats(opened), all_episodes=stats(results))


def synthetic_tests():
    hosted()
    checks=[]
    def test(name, value):
        need(value, 'SYNTHETIC_'+name);checks.append(name)
    def refuse(name, callback):
        try: callback()
        except (ValueError, KeyError, ZeroDivisionError):checks.append(name);return
        raise ValueError('SYNTHETIC_NOT_REFUSED_'+name)
    # Independent scalar examples pin the concentration curve and ratchet.
    test('REFERENCE_BUDGET_25PCT_WEIGHT', min(F('.30'),max(F('.06'),F('.015')/F('.25'))) == F('.06'))
    test('MODERATE_FLOOR_OVERRIDES_BUDGET', max(F('.15'),F('.015')/F('.25')) == F('.15'))
    levels=[F(70),F(90),F(85)];ratcheted=[]
    for candidate in levels:ratcheted.append(max(candidate,ratcheted[-1] if ratcheted else 0))
    test('NONDECREASING_VALUE_FLOOR', ratcheted == [70,90,90])
    refuse('REMOVED_RATCHET_MUTANT', lambda:need(levels==ratcheted,'RATCHET_CHANGED'))
    test('PURE_SPLIT_VALUE_UNIT', F(85)*F(100) == F(170)*F(50))
    test('EX_DATE_OPEN_SELL_RETAINS_DIVIDEND', '2020-02-03' <= '2020-02-03')
    test('NEXT_EX_DATE_DIVIDEND_FORFEITED', not '2020-02-04' <= '2020-02-03')
    # Exercise the actual scanner/fill/terminal functions, not only formulas.
    common=dict(slot_id=1,signal_date='2018-01-01',entry_date='2018-01-02',security_id='TEST',
                ticker='TEST',initial_shares=1,current_shares=1,entry_raw_open=100,
                entry_split_adjusted_price=100,episode_peak_split_adjusted_close=100)
    rows=[dict(session=s) for s in ('2018-01-02','2018-01-03','2018-01-04','2018-01-05')]
    episode=dict(key='1|2018-01-01',slot_id=1,signal_date='2018-01-01',entry_date='2018-01-02',
        sids=['TEST'],tickers=['TEST'],anchor_held=False,endpoint_kind='SELL',endpoint_session='2018-01-05',
        observations=[dict(index=i,session=rows[i]['session'],episode=dict(common),raw_close=p,
                           price_status='CURRENT',nav=1000,own_dd=dd)
                      for i,p,dd in ((0,100,0),(1,85,-.15),(2,70,-.30))],
        openings=[dict(index=2,session='2018-01-04',episode=dict(common),raw_open=90,price_status='RAW_OPEN'),
                  dict(index=3,session='2018-01-05',episode=dict(common),raw_open=69,price_status='RAW_OPEN')],
        source_events=[dict(event_type='DIVIDEND_ACCRUED',session='2018-01-04',security_id='TEST',
                            detail={'amount':1}),
                       dict(event_type='DIVIDEND_ACCRUED',session='2018-01-05',security_id='TEST',
                            detail={'amount':2})],
        original_sell=dict(event_type='SELL',session='2018-01-05',security_id='TEST',reason='EXIT_TRAILING_STOP',
                           shares_delta=-1,price=69,fees=.069,cash_delta=68.931))
    control=evaluate(episode,'.30',rows)
    test('ACTUAL_CONTROL_ZERO_DELTA',control['net_difference']=='0' and control['fill_session']=='2018-01-05')
    alternate=evaluate(episode,'.10',rows)
    test('ACTUAL_NEXT_OPEN_NOT_THRESHOLD_FILL',alternate['signal_session']=='2018-01-03'
         and alternate['fill_session']=='2018-01-04' and fraction(alternate['fill_raw_open'])==90)
    test('ACTUAL_EX_DATE_SALE_ENTITLEMENT',fraction(alternate['candidate_dividends'])==1
         and fraction(alternate['original_dividends'])==3)
    test('ACTUAL_NET_TERMINAL_ARITHMETIC',fraction(alternate['net_difference'])==F('18.979'))
    marked=deepcopy(episode)
    marked.update(endpoint_kind='END_MARK',endpoint_session='2018-01-04',original_sell=None)
    marked['source_events']=[e for e in marked['source_events'] if e['session'] <= marked['endpoint_session']]
    marked['openings']=[p for p in marked['openings'] if p['session'] <= marked['endpoint_session']]
    marked_exit=evaluate(marked,'.10',rows[:3])
    test('END_DATE_OPEN_PRECEDES_CLOSING_MARK',marked_exit['early_exit']
         and marked_exit['fill_session']==marked_exit['endpoint_session']
         and fraction(marked_exit['net_difference'])==F('19.91')
         and fraction(marked_exit['candidate_dividends'])==1)
    marked_control=evaluate(marked,'.30',rows[:3])
    test('FINAL_CLOSE_SIGNAL_UNEXECUTED_CONTROL_ZERO',marked_control['unexecuted_signal']
         and marked_control['fill_session'] is None and fraction(marked_control['net_difference'])==0)
    broken=deepcopy(episode);broken['openings']=[x for x in broken['openings'] if x['session']!='2018-01-04']
    refuse('MISSING_OPEN_NO_FUTURE_SUBSTITUTION',lambda:evaluate(broken,'.10',rows))
    broken_units=deepcopy(episode)
    for point in broken_units['observations']:
        point['episode']['entry_split_adjusted_price']=50
    refuse('WRONG_SPLIT_ADJUSTED_PEAK_UNIT',lambda:evaluate(broken_units,'.10',rows))
    # Removing the actual floor-memory operand changes the first signal.
    import ast,inspect
    tree=ast.parse(inspect.getsource(scan))
    assignment=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='level' for t in n.targets)
                    and isinstance(n.value,ast.Call))
    assignment.value.args.pop();ast.fix_missing_locations(tree)
    namespace={};exec(compile(tree,'<hosted-removed-ratchet>','exec'),globals(),namespace)
    mutated,_,_=namespace['scan'](episode,'.10',F(1))
    refuse('ACTUAL_REMOVED_RATCHET_MUTANT',lambda:need(mutated['session']==alternate['signal_session'], 'MUTANT_SIGNAL_CHANGED'))
    import tempfile,shutil
    with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
        fake=Path(temporary)
        shutil.copyfile('/p00/book/checkpoint.json.gz',fake/'checkpoint.json.gz')
        (fake/'daily.jsonl').write_bytes(b'changed-input\n')
        refuse('ALTERED_SOURCE_INPUT_BYTES',lambda:load_book(fake))
    return dict(status='PASS', checks=checks, financial_tests_hosted_only=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--book',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    hosted()
    sys.meta_path.insert(0, NoCanonical())
    need(args.book == Path('/p00/book') and args.out == Path('/out/worker'), 'EXACT_RESEARCH_MOUNTS')
    source=load_book(args.book)
    eligible=[ep for ep in source['episodes'].values() if first_activation(ep) is not None]
    eligible.sort(key=lambda ep:ep['key'])
    need(len(eligible)==17 and sum(ep['endpoint_kind']=='SELL' for ep in eligible)==16
         and [ep['tickers'][-1] for ep in eligible if ep['endpoint_kind']=='END_MARK']==['CRS'],
         'ALL_17_PREDECLARED_ELIGIBLE_EPISODES')
    arms={}
    for floor in FLOORS:
        results=[evaluate(ep,floor,source['rows']) for ep in eligible]
        arms[floor]=dict(minimum_distance=floor,episodes=results,summary=summary(results))
    ranking=sorted(FLOORS,
                   key=lambda f:(fraction(arms[f]['summary']['closed']['mean_normalized_difference']),fraction(f)),reverse=True)
    proof=dict(status='COMPLETE_REVIEW_REQUIRED',identity=source['identity'],eligible_keys=[ep['key'] for ep in eligible],
               arms=arms,ranking=ranking,best_in_this_screen=ranking[0],synthetic=synthetic_tests(),
               worker_sha256=file_sha(Path(__file__)),data_sha256=file_sha(Path(__file__).with_name('data.py')),
               new_Core_steps=0,new_Sentinel_steps=0,portfolio_CAGR_or_drawdown_claim=False,
               performance_admitted=False)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'report.json').write_bytes(encoded(proof)+b'\n')
    print(json.dumps(dict(status='COMPLETE_REVIEW_REQUIRED',eligible_episodes=len(eligible),arms=len(arms),
                          performance_admitted=False)),flush=True)


if __name__=='__main__':
    main()
