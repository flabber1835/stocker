"""Additive timing/cost attribution without changing the underlying Core path."""
from collections import defaultdict
from decimal import Decimal as D
import math

from .accounting import performance


def compact(path: dict) -> dict:
    return {k:v for k,v in path.items() if k not in {
        'nav', 'exposure', 'drawdown', 'gross_log', 'cost_log'}}


def limiting_mechanism(decision: dict, exposure: float) -> str:
    native = decision.get('native_target_core_exposure',decision['target_core_exposure'])
    recovery = decision.get('ldrc',{})
    owned = decision.get('owned_impairment',{})
    if exposure == 0:
        return 'native_severe' if float(native) == 0 else 'recovery_wait'
    if exposure == .55:
        divergence = recovery.get('desired_allocation') == .55
        if owned.get('active') and divergence:
            return 'owned_and_divergence_55'
        return 'owned_impairment_55' if owned.get('active') else 'divergence_55'
    return 'full_exposure'


def attribution(rows: list[dict], actual: dict, ideal: dict) -> dict:
    daily, grouped = [], {key:defaultdict(list) for key in ('reason', 'year', 'direction', 'mechanism')}
    for i, row in enumerate(rows[1:]):
        a, b = actual['exposure'][i], ideal['exposure'][i]
        gross = ideal['gross_log'][i]-actual['gross_log'][i]
        cost = ideal['cost_log'][i]-actual['cost_log'][i]
        direction = 'less_core_than_oracle' if a < b else ('more_core_than_oracle' if a > b else 'same_open_exposure')
        decision = rows[i]['decision']
        recovery_reason = decision.get('ldrc',{}).get('reason','')
        reason = decision['reason']+('|RECOVERY:'+recovery_reason if recovery_reason else '')
        previous_actual = rows[i]['economics']['held_allocation']
        item = dict(session=row['session'], decision_session=rows[i]['session'],
            actual_exposure=a, oracle_exposure=b,
            actual_overnight_exposure=float(previous_actual) if previous_actual is not None else None,
            oracle_overnight_exposure=ideal['exposure'][i-1] if i else (float(previous_actual) if previous_actual is not None else None),
            actual_reason=reason, actual_native_reason=decision['reason'],
            actual_recovery_reason=recovery_reason,
            actual_owned_reason=decision.get('owned_impairment',{}).get('reason',''),
            mechanism=limiting_mechanism(decision,a), direction=direction,
            gross_log_gap=gross, cost_log_gap=cost, net_log_gap=gross+cost)
        daily.append(item)
        grouped['reason'][item['actual_reason']].append(item)
        grouped['year'][row['session'][:4]].append(item)
        grouped['direction'][direction].append(item)
        grouped['mechanism'][item['mechanism']].append(item)
    gross = sum(x['gross_log_gap'] for x in daily)
    costs = sum(x['cost_log_gap'] for x in daily)
    ratio = D(ideal['multiple'])/D(actual['multiple'])
    if abs(gross+costs-math.log(float(ratio))) > 1e-10:
        raise ValueError('growth attribution does not reconcile')
    groups = {}
    for kind, values in grouped.items():
        groups[kind] = [dict(label=label, days=len(items),
            gross_log_gap=sum(x['gross_log_gap'] for x in items),
            cost_log_gap=sum(x['cost_log_gap'] for x in items),
            net_log_gap=sum(x['net_log_gap'] for x in items)) for label,items in sorted(values.items())]
    episodes, begin = [], None
    for i in range(len(daily)+1):
        defensive = i < len(daily) and daily[i]['actual_exposure'] < 1
        if defensive and begin is None:
            begin = i
        if not defensive and begin is not None:
            items = daily[begin:i]
            episodes.append(dict(start=items[0]['session'], end=items[-1]['session'],
                baseline=rows[begin]['session'], days=len(items),
                first_full_session=daily[i]['session'] if i < len(daily) else None,
                actual_mean_exposure=sum(x['actual_exposure'] for x in items)/len(items),
                oracle_mean_exposure=sum(x['oracle_exposure'] for x in items)/len(items),
                oracle_days_at_0=sum(x['oracle_exposure'] == 0 for x in items),
                oracle_days_at_55=sum(x['oracle_exposure'] == .55 for x in items),
                oracle_days_at_100=sum(x['oracle_exposure'] == 1 for x in items),
                actual_return=float(D(actual['nav'][i])/D(actual['nav'][begin])-1),
                oracle_return=float(D(ideal['nav'][i])/D(ideal['nav'][begin])-1),
                core_return=float(D(rows[i]['core']['nav'])/D(rows[begin]['core']['nav'])-1),
                reasons=sorted({x['actual_reason'] for x in items}),
                gross_log_gap=sum(x['gross_log_gap'] for x in items),
                cost_log_gap=sum(x['cost_log_gap'] for x in items),
                net_log_gap=sum(x['net_log_gap'] for x in items)))
            begin = None
    counts = {name:{str(a):path['exposure'].count(a) for a in (0., .55, 1.)}
              for name,path in (('actual',actual),('oracle',ideal))}
    return dict(daily=daily, gross_log_gap=gross, cost_log_gap=costs,
                net_log_gap=gross+costs, wealth_ratio=str(ratio),
                differing_days=sum(x['actual_exposure'] != x['oracle_exposure'] for x in daily),
                exposure_counts=counts, groups=groups, defensive_episodes=episodes)


def monthly(rows: list[dict], paths: dict[str, dict]) -> list[dict]:
    result, previous_end = [], 0
    dates = [r['session'] for r in rows]
    for i in range(1,len(rows)):
        if i+1 < len(rows) and dates[i][:7] == dates[i+1][:7]:
            continue
        series = {}
        for name,path in paths.items():
            values = [D(x) for x in path['nav'][:i+1]]
            metrics = performance(values, dates[:i+1])
            metrics.pop('drawdown')
            metrics['period_return'] = float(values[-1]/values[previous_end]-1)
            series[name] = metrics
        result.append(dict(session=dates[i], period_end=i == len(rows)-1, series=series))
        previous_end = i
    return result
