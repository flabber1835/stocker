"""Hosted-only canonical scalar factors and account replay; no Core transition."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal as D, localcontext
import hashlib
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from data import LEVELS, digest, file_sha, need

FIXED_FILES = {
    'research/pooled_vacancy_funding/backtest.py':
        '0755b13777dc247fe3d112cd4f776329b44e47a8c97d3d524a968d8fbd970fe9',
    'sentinel/shadow_observation.py':
        '62266616d6f9a78d6ae9eab4d88ee2429d1ce4e08e003afcb6b60a3c2115b957',
    'sentinel/formed_economics.py':
        '34ce8061a3ebc53c208163f4f63049682f8ed9f5110413e0282d857d8fd84ef0',
}


def hosted():
    need(os.environ.get('SENTINEL_ORACLE_HOSTED') == '1'
         and Path(__file__).resolve() == Path('/current/research/sentinel_oracle/account.py'),
         'HOSTED_ORACLE_ACCOUNT_ONLY')
    need(not any(os.environ.get(key) for key in (
        'GH_TOKEN', 'GITHUB_TOKEN', 'CAPITAL_RISK_RESEARCH_KEY_20261027',
        'DATABASE_URL', 'PGPASSWORD', 'ALPACA_API_KEY', 'ALPACA_SECRET_KEY',
        'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY', 'OPENAI_API_KEY',
        'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')), 'NO_FINANCIAL_CREDENTIALS')
    route = Path('/proc/net/route')
    need(route.is_file() and not any(line.split()[0] != 'lo'
         for line in route.read_text().splitlines()[1:] if line.split()), 'OFFLINE_ACCOUNT_ONLY')


def canonical_account():
    hosted()
    for name, expected in FIXED_FILES.items():
        need(file_sha(Path('/fixed')/name) == expected, 'EXACT_FROZEN_CANONICAL_SOURCE:'+name)
    for path in reversed(('/fixed', '/fixed/shared')):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    from research.pooled_vacancy_funding.backtest import Account
    import sentinel.shadow_observation
    import sentinel.formed_economics
    import research.pooled_vacancy_funding.backtest
    for module, name in ((sentinel.shadow_observation, 'sentinel/shadow_observation.py'),
                         (sentinel.formed_economics, 'sentinel/formed_economics.py'),
                         (research.pooled_vacancy_funding.backtest,
                          'research/pooled_vacancy_funding/backtest.py')):
        need(Path(module.__file__).resolve() == Path('/fixed')/name,
             'CANONICAL_IMPORT_NAMESPACE:'+name)
    return Account


def _advance(Account, previous, row, target, events):
    closed = row['evidence']['research_entry_audit']['closing_accounting']
    state = SimpleNamespace(last_processed_session=row['session'],
        shadow_nav_history=[row['evidence']['observation']['shadow_nav']],
        last_evidence=row['evidence'], last_decision={**row['decision'], 'target_core_exposure':target},
        wealth_core=closed['wealth_core'])
    formed = previous['held_allocation'] is None and previous.get('research_entry_mode') == 'FORMED_BASKET'
    if formed:
        state.ledger = {**closed['ledger'], 'events':events[:closed['ledger']['event_count']]}
    with localcontext() as ctx:
        ctx.prec = 28
        result = Account(previous['starting_cash'], formed=formed).advance(
            previous=previous, state=state, strategy_prices=row['economics']['strategy_prices'],
            formed_startup_marks=row['economics'].get('formed_startup_marks') if formed else None)
    for key in ('research_entry_mode', 'measurement_anchor_session'):
        result[key] = previous[key]
    return result


def _entry_terms(source):
    row = source['rows'][1]
    e = row['economics']
    closed = row['evidence']['research_entry_audit']['closing_accounting']
    marks = e['formed_startup_marks']
    held = {}
    with localcontext() as ctx:
        ctx.prec = 28
        for episode in closed['wealth_core']['episodes'].values():
            sid = episode['security_id']
            held[sid] = held.get(sid, D(0)) + D(str(episode['current_shares']))
        need(set(marks) == set(held), 'EXACT_FORMED_STOCK_MARK_COVERAGE')
        notional = sum((q*D(str(marks[sid])) for sid, q in held.items()), D(0))
        events = source['events'][:closed['ledger']['event_count']]
        fees = sum((D(str(event['fees'])) for event in events
                    if event['session'] == row['session'] and event['event_type'] in ('BUY', 'SELL')), D(0))
    return notional, fees


def independent_edge(source, row_index, old_code, new_code):
    """Formula check only; all admitted factors still come from Account.advance."""
    hosted()
    row = source['rows'][row_index]
    e = row['economics']
    new = D(LEVELS[new_code])
    with localcontext() as ctx:
        ctx.prec = 28
        op, cl = D(e['parent_core_open_equity']), D(e['parent_core_close_equity'])
        bo, bc, bp = map(D, (e['bil_open_adjusted'], e['bil_close_adjusted'],
                            e['bil_previous_close_adjusted_current_publication']))
        if row_index == 1:
            notional, fees = _entry_terms(source)
            gross = 1 + new*((cl+fees)/op-1) + (1-new)*(bc/bo-1)
            turnover = new*notional/op + (1-new)
            net = gross-D('.001')*turnover
        else:
            old = D(LEVELS[old_code])
            pc = D(source['rows'][row_index-1]['economics']['parent_core_close_equity'])
            turnover = abs(new-old)
            gross = (new*cl/pc + (1-new)*bc/bp if new == old else
                     (old*op/pc+(1-old)*bo/bp)*(new*cl/op+(1-new)*bc/bo))
            net = gross*(1-D('.001')*turnover)
    return dict(net=net, gross=gross, turnover=turnover)


def _fields(economics):
    return dict(net=economics['net_factor'], gross=economics['gross_factor'],
                cost=economics['transaction_cost_factor'], turnover=economics['turnover'])


def build_factor_table(source):
    hosted()
    Account = canonical_account()
    rows, events = source['rows'], source['events']
    previous = deepcopy(rows[0]['economics'])
    original_verified = 1
    for row in rows[1:]:
        result = _advance(Account, previous, row, row['decision']['target_core_exposure'], events)
        if result != row['economics']:
            differing = sorted(key for key in set(result)|set(row['economics'])
                               if result.get(key) != row['economics'].get(key))
            raise ValueError('EXACT_ORIGINAL_ACCOUNT_CALIBRATION:'+row['session']+':'+','.join(differing))
        previous = result
        original_verified += 1
    startup = dict(row_index=1, session=rows[1]['session'], new_code=2, **_fields(rows[1]['economics']))
    first_expected = independent_edge(source, 1, None, 2)
    need(abs(D(startup['net'])-first_expected['net']) < D('1e-22'), 'INDEPENDENT_FORMED_ENTRY')
    days = []
    for i in range(2, len(rows)):
        day = dict(row_index=i, session=rows[i]['session'],
                   **{key:[[None]*3 for _ in range(3)] for key in ('net', 'gross', 'cost', 'turnover')})
        for old in range(3):
            for new in range(3):
                prior = {**rows[i-1]['economics'], 'strategy_nav':'50000',
                         'held_allocation':LEVELS[old], 'pending_allocation':LEVELS[new]}
                actual = _advance(Account, prior, rows[i], 0, events)
                expected = independent_edge(source, i, old, new)
                need(abs(D(actual['net_factor'])-expected['net']) < D('1e-22')
                     and abs(D(actual['gross_factor'])-expected['gross']) < D('1e-22')
                     and D(actual['turnover']) == expected['turnover'],
                     'EVERY_EDGE_INDEPENDENT_FORMULA:'+rows[i]['session'])
                for field, value in _fields(actual).items():
                    need(D(value).is_finite() and (D(value)>0 if field != 'turnover' else D(value)>=0),
                         'POSITIVE_FINITE_EDGE:'+field)
                    day[field][old][new] = value
        days.append(day)
    sys.path.insert(0, '/legacy/research/capital_risk')
    from owned_value import factor_dependency_guard
    dependency = factor_dependency_guard(Path('/fixed/sentinel/shadow_observation.py').read_bytes())
    proof = dict(original_complete_economic_rows_verified=original_verified,
        ordinary_edges_verified=len(days)*9, first_entry_verified=True,
        canonical_sources=FIXED_FILES, canonical_factor_dependency=dependency,
        account_model='ORIGINAL_SCALAR_RESEARCH_WITH_FORMED_ENTRY',
        Core_steps=0, Sentinel_steps=0, baseline_codes_sha256=digest(source['baseline_codes']))
    return dict(schema='research.sentinel-oracle-factors/1', levels=list(LEVELS),
        startup=startup, days=days, source_identity=source['identity'], proof=proof)


def edge_at(table, row_index, old_code, new_code):
    if row_index == 0:
        return dict(net='1', gross='1', cost='1', turnover='0')
    if row_index == 1:
        need(new_code == 2, 'COMMON_FIXED_FIRST_DEPLOYMENT')
        return {key:table['startup'][key] for key in ('net', 'gross', 'cost', 'turnover')}
    need(type(old_code) is int and type(new_code) is int
         and old_code in range(3) and new_code in range(3), 'EDGE_ALLOCATION_CODES')
    day = table['days'][row_index-2]
    need(day['row_index'] == row_index, 'EDGE_EXACT_DAILY_INDEX')
    return {key:day[key][old_code][new_code] for key in ('net', 'gross', 'cost', 'turnover')}


def replay(source, table, codes, *, verify_canonical=True):
    hosted()
    need(type(codes) is list and len(codes) == len(source['rows'])-1
         and codes[0] == 2 and all(type(code) is int and code in range(3) for code in codes),
         'EXACT_REALIZED_ALLOCATION_PATH')
    need(table['source_identity'] == source['identity'], 'FACTOR_SOURCE_IDENTITY')
    Account = canonical_account() if verify_canonical else None
    original = source['rows']
    nav, peak, worst = D('50000'), D('50000'), D(0)
    peak_day = worst_peak_day = worst_trough_day = original[0]['session']
    total_turnover = ordinary_turnover = D(0)
    cost_multiple = D(1)
    log_cost = 0.0
    underwater = switches = 0
    occupancy = {level:0 for level in LEVELS}
    daily = []
    previous = deepcopy(original[0]['economics'])
    previous['pending_allocation'] = LEVELS[codes[0]]
    for i, row in enumerate(original):
        code = None if i == 0 else codes[i-1]
        old = None if i < 2 else codes[i-2]
        edge = edge_at(table, i, old, code)
        switch = i >= 2 and old != code
        next_code = codes[i] if i < len(codes) else codes[-1]
        if i:
            with localcontext() as ctx:
                ctx.prec = 28
                nav *= D(edge['net'])
            if verify_canonical:
                actual = _advance(Account, previous, row, LEVELS[next_code], source['events'])
                need(D(actual['strategy_nav']) == nav and all(
                    actual[key] == edge[name] for name, key in (
                        ('net', 'net_factor'), ('gross', 'gross_factor'),
                        ('cost', 'transaction_cost_factor'), ('turnover', 'turnover'))),
                    'DIRECT_CANONICAL_PATH_REPLAY:'+row['session'])
                previous = actual
            occupancy[LEVELS[code]] += 1
        if nav > peak:
            peak, peak_day = nav, row['session']
        with localcontext() as ctx:
            ctx.prec = 50
            dd = nav/peak-1
            total_turnover += D(edge['turnover'])
            if i >= 2:
                ordinary_turnover += D(edge['turnover'])
            cost_multiple *= D(edge['cost'])
        if dd < worst:
            worst, worst_peak_day, worst_trough_day = dd, peak_day, row['session']
        underwater += int(nav < peak)
        switches += int(switch)
        log_cost -= math.log(float(edge['cost']))
        daily.append(dict(row_index=i, session=row['session'],
            decision_session=None if i == 0 else original[i-1]['session'],
            effective_code=code, effective_exposure=None if code is None else LEVELS[code],
            decision_exposure=LEVELS[next_code], last_unexecuted_intent=i == len(original)-1,
            nav=str(nav), high_water_mark=str(peak), drawdown_fraction=str(dd),
            net_factor=edge['net'], gross_factor=edge['gross'],
            transaction_cost_factor=edge['cost'], turnover=edge['turnover'],
            switch=switch, initial_deployment=i == 1))
    elapsed_days = (date.fromisoformat(original[-1]['session'])
                    - date.fromisoformat(original[0]['session'])).days
    with localcontext() as ctx:
        ctx.prec = 50
        multiple = nav/D('50000')
        total_return = multiple-1
    growth = math.log(float(multiple))
    metrics = dict(initial_nav='50000', final_nav=str(nav), multiple=str(multiple),
        total_return=str(total_return), total_log_growth=growth,
        cagr_pct=100*math.expm1(growth*365.2425/elapsed_days),
        maximum_drawdown_fraction=str(worst.copy_abs()), max_drawdown_pct=-100*float(worst),
        ordinary_switches=switches, underwater_closes=underwater,
        exposure_closes=occupancy, total_turnover=str(total_turnover),
        ordinary_turnover=str(ordinary_turnover), cost_multiple=str(cost_multiple),
        cost_log_drag=log_cost, peak_session=worst_peak_day, trough_session=worst_trough_day,
        calendar_days=elapsed_days, measured_closes=len(original),
        model='ORIGINAL_SCALAR_RESEARCH_WITH_FORMED_ENTRY')
    return dict(schema='research.sentinel-oracle-account-path/1', identity=source['identity'],
                codes=list(codes), rows=daily, metrics=metrics,
                canonical_direct_replay_verified=verify_canonical)


def raw_core_reference(source):
    """Recorded immutable Core reference; explicitly not a newly funded account."""
    hosted()
    rows = source['rows']
    initial = D(rows[0]['economics']['parent_core_close_equity'])
    peak = initial
    worst = D(0)
    with localcontext() as ctx:
        ctx.prec = 50
        for row in rows:
            nav = D(row['economics']['parent_core_close_equity'])
            peak = max(peak, nav)
            worst = min(worst, nav/peak-1)
        multiple = nav/initial
    days = (date.fromisoformat(rows[-1]['session'])-date.fromisoformat(rows[0]['session'])).days
    return dict(scope='RAW_CORE_REFERENCE_NOT_FUNDED_COMPARATOR',
        initial_nav=str(initial), final_nav=str(nav), multiple=str(multiple),
        cagr_pct=100*math.expm1(math.log(float(multiple))*365.2425/days),
        maximum_drawdown_fraction=str(worst.copy_abs()), max_drawdown_pct=-100*float(worst))
