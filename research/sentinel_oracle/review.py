"""Independent hosted review of hindsight exposure paths and optimization proofs.

Only the immutable DATA reader is shared. Account equations, dynamic programming,
constraint reconstruction and numerical falsifiers below do not call worker code.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
from decimal import Decimal as D, localcontext
import hashlib
import importlib.abc
import itertools
import json
import math
import os
from pathlib import Path
import sys

LEVELS = (D(0), D('.55'), D(1))
COEFFICIENT_EPS = 1e-12
FORBIDDEN = ('GH_TOKEN', 'GITHUB_TOKEN', 'CAPITAL_RISK_RESEARCH_KEY_20261027',
             'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'APCA_API_KEY_ID',
             'APCA_API_SECRET_KEY', 'DATABASE_URL', 'PGPASSWORD',
             'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'OPENAI_API_KEY')


def need(value, code):
    if not value:
        raise ValueError(code)


def hosted():
    need(os.environ.get('SENTINEL_ORACLE_HOSTED') == '1', 'HOSTED_ORACLE_REVIEW_ONLY')
    need(Path(__file__).resolve() == Path('/current/research/sentinel_oracle/review.py'),
         'EXACT_REVIEW_SOURCE_PATH')
    need(not any(os.environ.get(name) for name in FORBIDDEN), 'NO_CREDENTIALS')
    route = Path('/proc/net/route')
    need(route.is_file() and not any(row.split()[0] != 'lo'
         for row in route.read_text().splitlines()[1:] if row.split()), 'NO_NETWORK_ROUTE')


class NoWorker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'worker',
                                'optimizer', 'account', 'research.pooled_')):
            raise AssertionError('FORBIDDEN_REVIEW_IMPORT:' + fullname)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def num(value):
    need(type(value) in (str, int, float, D), 'FINITE_SCALAR_TYPE')
    parsed = value if isinstance(value, D) else D(str(value))
    need(parsed.is_finite(), 'FINITE_SCALAR_VALUE')
    return parsed


def near(actual, expected, code, *, relative='1e-19', absolute='1e-24'):
    actual, expected = num(actual), num(expected)
    need(abs(actual - expected) <= max(D(absolute), abs(expected) * D(relative)), code)


def formed_factor(source):
    """The first real basket entry charges subtractive cost exactly once."""
    row = source['rows'][1]
    e = row['economics']
    packet = row['evidence']['research_entry_audit']['closing_accounting']
    quantities = {}
    for item in packet['wealth_core']['episodes'].values():
        sid = item['security_id']
        quantities[sid] = quantities.get(sid, D(0)) + num(item['current_shares'])
    marks = e['formed_startup_marks']
    need(set(marks) == set(quantities), 'FORMED_EXACT_PRICE_COVERAGE')
    with localcontext() as ctx:
        ctx.prec = 28
        opening, closing = num(e['parent_core_open_equity']), num(e['parent_core_close_equity'])
        notional = sum((q * num(marks[sid]) for sid, q in quantities.items()), D(0))
        need(D(0) <= notional <= opening, 'FORMED_LONG_ONLY_NOTIONAL')
        count = packet['ledger']['event_count']
        fees = sum((num(item['fees']) for item in source['events'][:count]
                    if item['session'] == row['session'] and item['event_type'] in ('BUY', 'SELL')), D(0))
        need(fees >= 0, 'FORMED_NONNEGATIVE_SOURCE_FEES')
        gross = (closing + fees) / opening
        turnover = notional / opening
        net = gross - D('.001') * turnover
        cost = net / gross
    need(net > 0, 'FORMED_POSITIVE_NET_FACTOR')
    return dict(net=str(net), gross=str(gross), cost=str(cost), turnover=str(turnover))


def ordinary_factor(previous, row, old, new):
    """Preserve the historical scalar's distinct carry and switch branches."""
    need(old in range(3) and new in range(3), 'THREE_LEVEL_EDGE')
    a, b = LEVELS[old], LEVELS[new]
    p, e = previous['economics'], row['economics']
    with localcontext() as ctx:
        ctx.prec = 28
        opening, closing, prior = (num(e['parent_core_open_equity']),
                                   num(e['parent_core_close_equity']),
                                   num(p['parent_core_close_equity']))
        bo, bc, bp = (num(e['bil_open_adjusted']), num(e['bil_close_adjusted']),
                       num(e['bil_previous_close_adjusted_current_publication']))
        need(min(opening, closing, prior, bo, bc, bp) > 0, 'POSITIVE_EDGE_INPUTS')
        turnover = abs(b-a)
        cost = 1-D('.001')*turnover
        if a == b:
            # Canonical ordering is significant at precision 28.
            gross = a*closing/prior+(1-a)*bc/bp
        else:
            gross = 1+a*(opening/prior-1)+(1-a)*(bo/bp-1)
            gross *= 1+b*(closing/opening-1)+(1-b)*(bc/bo-1)
        net = cost*gross
    need(net > 0 and gross > 0 and 0 < cost <= 1, 'POSITIVE_UNLEVERED_EDGE')
    return dict(net=str(net), gross=str(gross), cost=str(cost), turnover=str(turnover))


def independent_table(source):
    days = []
    for index in range(2, len(source['rows'])):
        row = source['rows'][index]
        fields = {key: [[None]*3 for _ in range(3)] for key in ('net', 'gross', 'cost', 'turnover')}
        for old, new in itertools.product(range(3), repeat=2):
            edge = ordinary_factor(source['rows'][index-1], row, old, new)
            for key in fields:
                fields[key][old][new] = edge[key]
        days.append(dict(session=row['session'], row_index=index, **fields))
    return dict(startup=dict(new_code=2, **formed_factor(source)), days=days)


def verify_table(actual, expected):
    need(len(actual['days']) == len(expected['days']) == 2154, 'ALL_ORDINARY_FACTOR_DAYS')
    need(actual['startup']['new_code'] == 2, 'FORCED_INITIAL_FULL')
    for name in ('net', 'gross', 'cost', 'turnover'):
        near(actual['startup'][name], expected['startup'][name], 'INDEPENDENT_FORMED_' + name,
             relative='1e-25', absolute='1e-26')
    for day, reference in zip(actual['days'], expected['days']):
        need(day['session'] == reference['session'] and day['row_index'] == reference['row_index'],
             'EXACT_FACTOR_DAY_AXIS')
        for old, new in itertools.product(range(3), repeat=2):
            for name in ('net', 'gross', 'cost', 'turnover'):
                near(day[name][old][new], reference[name][old][new],
                     'INDEPENDENT_EDGE:' + day['session'] + ':' + name,
                     relative='1e-25', absolute='1e-26')


def path_log(table, codes):
    need(len(codes) == len(table['days'])+1 and codes[0] == 2
         and all(type(code) is int and code in range(3) for code in codes), 'PATH_ALLOCATION_MENU')
    return math.log(float(num(table['startup']['net']))) + sum(
        math.log(float(num(day['net'][codes[i]][codes[i+1]])))
        for i, day in enumerate(table['days']))


def independent_dp(table, budget):
    """Forward exact-change-count Bellman recurrence, independent of worker."""
    need(type(budget) is int and budget >= 0, 'NONNEGATIVE_SWITCH_BUDGET')
    previous = [[-math.inf]*3 for _ in range(budget+1)]
    previous[0][2] = math.log(float(num(table['startup']['net'])))
    for day in table['days']:
        following = [[-math.inf]*3 for _ in range(budget+1)]
        for spent, old, new in itertools.product(range(budget+1), range(3), range(3)):
            used = spent + (old != new)
            if used <= budget and math.isfinite(previous[spent][old]):
                candidate = previous[spent][old] + math.log(float(num(day['net'][old][new])))
                following[used][new] = max(following[used][new], candidate)
        previous = following
    return dict(best_log_terminal=max(max(row) for row in previous),
                terminal_state_values=previous)


def verify_dp(actual, table, budget, codes):
    solved = independent_dp(table, budget)
    near(actual['best_log_terminal'], solved['best_log_terminal'], 'INDEPENDENT_DP_OPTIMUM',
         relative='1e-10', absolute='1e-10')
    near(path_log(table, codes), solved['best_log_terminal'], 'DP_SELECTED_PATH_REACHES_BOUND',
         relative='1e-10', absolute='1e-10')
    need(sum(a != b for a, b in zip(codes, codes[1:])) <= budget, 'DP_SWITCH_BUDGET')
    terminal = actual['terminal_state_values']
    need(len(terminal) == 3 and all(len(row) == budget+1 for row in terminal),
         'DP_COMPLETE_TERMINAL_CERTIFICATE')
    for state, spent in itertools.product(range(3), range(budget+1)):
        expected = solved['terminal_state_values'][spent][state]
        if math.isfinite(expected):
            near(terminal[state][spent], expected, 'DP_EVERY_TERMINAL_STATE',
                 relative='1e-10', absolute='1e-10')
        else:
            need(terminal[state][spent] is None, 'DP_UNREACHABLE_STATE_REMAINS_UNREACHABLE')
    return solved


def independent_replay(source, table, codes):
    need(len(codes) == len(source['rows'])-1 and codes[0] == 2
         and all(type(code) is int and code in range(3) for code in codes), 'EXACT_EFFECTIVE_PATH')
    nav = high = D(50000)
    peak_day = source['axis'][0]
    worst, worst_peak, worst_trough = D(0), peak_day, peak_day
    turnover, ordinary_turnover, cost_product = D(0), D(0), D(1)
    cost_logs, underwater, changes = [], 0, 0
    occupancy = {str(level): 0 for level in LEVELS}
    rows = []
    for index, day in enumerate(source['axis']):
        effective = None if index == 0 else codes[index-1]
        if index == 0:
            edge = dict(net='1', gross='1', cost='1', turnover='0')
        elif index == 1:
            edge = table['startup']
        else:
            old, new = codes[index-2:index]
            edge = {name: table['days'][index-2][name][old][new]
                    for name in ('net', 'gross', 'cost', 'turnover')}
        with localcontext() as ctx:
            ctx.prec = 28
            nav *= num(edge['net'])
        if nav > high:
            high, peak_day = nav, day
        with localcontext() as ctx:
            ctx.prec = 50
            drawdown = nav/high-1
            turnover += num(edge['turnover'])
            if index > 1:
                ordinary_turnover += num(edge['turnover'])
            cost_product *= num(edge['cost'])
        if drawdown < 0:
            underwater += 1
        if -drawdown > worst:
            worst, worst_peak, worst_trough = -drawdown, peak_day, day
        switched = index > 1 and codes[index-2] != codes[index-1]
        changes += switched
        if effective is not None:
            occupancy[str(LEVELS[effective])] += 1
        cost_logs.append(math.log(float(num(edge['cost']))))
        # The last intent is an explicitly unexecuted carry placeholder.
        decision = codes[index] if index < len(codes) else codes[-1]
        rows.append(dict(row_index=index, session=day,
            decision_session=None if not index else source['axis'][index-1],
            effective_code=effective,
            effective_exposure=None if effective is None else str(LEVELS[effective]),
            decision_exposure=str(LEVELS[decision]), last_unexecuted_intent=index == len(source['axis'])-1,
            nav=str(nav), high_water_mark=str(high), drawdown_fraction=str(drawdown),
            net_factor=str(num(edge['net'])), gross_factor=str(num(edge['gross'])),
            transaction_cost_factor=str(num(edge['cost'])), turnover=str(num(edge['turnover'])),
            switch=bool(switched), initial_deployment=index == 1))
    with localcontext() as ctx:
        ctx.prec = 50
        multiple = nav/D(50000)
        total_return = multiple-1
    days = (date.fromisoformat(source['axis'][-1])-date.fromisoformat(source['axis'][0])).days
    log_growth = math.log(float(multiple))
    metrics = dict(final_nav=str(nav), initial_nav='50000', multiple=str(multiple),
        total_return=str(total_return), total_log_growth=log_growth,
        cagr_pct=100*math.expm1(log_growth*365.2425/days),
        maximum_drawdown_fraction=str(worst), max_drawdown_pct=float(worst)*100,
        ordinary_switches=changes, underwater_closes=underwater, exposure_closes=occupancy,
        total_turnover=str(turnover), ordinary_turnover=str(ordinary_turnover),
        cost_multiple=str(cost_product), cost_log_drag=-sum(cost_logs),
        peak_session=worst_peak, trough_session=worst_trough)
    return dict(identity=source['identity'], codes=codes, rows=rows, metrics=metrics)


def verify_replay(actual, expected, name):
    need(actual['identity'] == expected['identity'] and actual['codes'] == expected['codes'],
         'REPLAY_IDENTITY_AND_CODES:' + name)
    need(len(actual['rows']) == len(expected['rows']) == 2156, 'REPLAY_ALL_CLOSES:' + name)
    decimal_fields = ('nav', 'high_water_mark', 'drawdown_fraction', 'net_factor', 'gross_factor',
                      'transaction_cost_factor', 'turnover')
    exact_fields = ('row_index', 'session', 'decision_session', 'effective_code',
                   'effective_exposure', 'decision_exposure', 'last_unexecuted_intent',
                   'switch', 'initial_deployment')
    for row, reference in zip(actual['rows'], expected['rows']):
        for field in decimal_fields:
            near(row[field], reference[field], 'INDEPENDENT_PATH:' + name + ':' + field)
        for field in exact_fields:
            need(row[field] == reference[field], 'INDEPENDENT_TIMING:' + name + ':' + field)
    metrics, reference = actual['metrics'], expected['metrics']
    for field in ('final_nav', 'initial_nav', 'multiple', 'total_return',
                  'maximum_drawdown_fraction', 'total_turnover', 'ordinary_turnover', 'cost_multiple'):
        near(metrics[field], reference[field], 'INDEPENDENT_METRIC:' + name + ':' + field)
    for field in ('total_log_growth', 'cagr_pct', 'max_drawdown_pct', 'cost_log_drag'):
        near(metrics[field], reference[field], 'INDEPENDENT_FLOAT_METRIC:' + name + ':' + field,
             relative='1e-9', absolute='1e-9')
    for field in ('ordinary_switches', 'underwater_closes', 'exposure_closes', 'peak_session', 'trough_session'):
        need(metrics[field] == reference[field], 'INDEPENDENT_DISCRETE_METRIC:' + name + ':' + field)


def matrix_terms(model, row):
    begin, end = model['row_starts'][row:row+2]
    indices, values = model['row_indices'][begin:end], model['row_values'][begin:end]
    need(len(set(indices)) == len(indices) and indices == sorted(indices), 'UNIQUE_SORTED_ROW_COLUMNS')
    need(all(type(i) is int and 0 <= i < model['columns'] for i in indices), 'VALID_MATRIX_COLUMN')
    need(all(math.isfinite(value) and value != 0 for value in values), 'FINITE_NONZERO_MATRIX')
    return dict(zip(indices, values))


def coefficient_row(actual, expected, label):
    expected = {column: value for column, value in expected.items() if value != 0}
    need(set(actual) == set(expected), 'SEMANTIC_MATRIX_SPARSITY:' + label)
    for column in expected:
        need(abs(actual[column]-expected[column]) <= 2e-12,
             'SEMANTIC_MATRIX_COEFFICIENT:' + label)


def independent_coefficient_policy(table):
    """Reconstruct explicit MILP-only omissions; source/DP factors stay intact."""
    import numpy as np
    need(np.__version__ == '2.4.6', 'PINNED_LOG_COEFFICIENT_NUMERICS')
    raw = np.log(np.asarray([day['net'] for day in table['days']], dtype=np.float64))
    numerical = raw.copy()
    omitted, per_day = [], []
    for t in range(len(raw)):
        largest = 0.
        for old, new in itertools.product(range(3), repeat=2):
            value = float(raw[t, old, new])
            if abs(value) <= COEFFICIENT_EPS:
                numerical[t, old, new] = 0.
                if value != 0:
                    omitted.append(dict(day=t, old=old, new=new, value=value))
                    largest = max(largest, abs(value))
        per_day.append(largest)
    error = math.fsum(per_day)
    need(2*error < 1e-8, 'MILP_OMISSION_ERROR_WITHIN_FROZEN_LOG_TOLERANCE')
    return dict(raw_logs=raw.tolist(), numerical_logs=numerical.tolist(), omitted=omitted,
                per_day_maximum=per_day, log_wealth_error=error, log_drawdown_error=2*error,
                raw_sha256=hashlib.sha256(encoded(raw.tolist())).hexdigest(),
                numerical_sha256=hashlib.sha256(encoded(numerical.tolist())).hexdigest())


def verify_model(model, table, budget, mode, dd_cap, growth_floor, *, zero_threshold=COEFFICIENT_EPS):
    """Reconstruct every semantic row and bound without importing the builder."""
    n = len(table['days'])
    edges, wealth, peak = n*9, n*9, n*10
    risk_column = n*11 if mode == 'min_drawdown' else None
    columns = n*11+(mode == 'min_drawdown')
    start = math.log(float(num(table['startup']['net'])))
    initial_peak = max(0., start)
    policy = independent_coefficient_policy(table)
    need(zero_threshold in (0., COEFFICIENT_EPS), 'FROZEN_MODEL_COEFFICIENT_POLICY')
    raw_logs = policy['raw_logs']
    logs = raw_logs if zero_threshold == 0 else policy['numerical_logs']
    omissions = [] if zero_threshold == 0 else [dict(day=item['day'], old=item['old'], new=item['new'],
        source_log_coefficient=item['value']) for item in policy['omitted']]
    expected_zeroing = dict(threshold=zero_threshold, omissions=omissions,
        per_day_maximum_removed=[0.]*n if zero_threshold == 0 else policy['per_day_maximum'],
        source_path_log_wealth_error_bound=0. if zero_threshold == 0 else policy['log_wealth_error'],
        source_path_log_drawdown_error_bound=0. if zero_threshold == 0 else policy['log_drawdown_error'],
        original_source_factors_and_dp_unchanged=True)
    need(model['coefficient_zeroing'] == expected_zeroing
         and model['logs_sha256'] == policy['raw_sha256'],
         'EXACT_INDEPENDENT_COEFFICIENT_OMISSIONS_AND_ERROR_BOUNDS')
    need(model['mode'] == mode and model['days'] == n and model['budget'] == budget,
         'FROZEN_MILP_QUESTION')
    need(model['columns'] == columns and model['edge_columns'] == edges
         and model['wealth_start'] == wealth and model['peak_start'] == peak
         and model['risk_column'] == risk_column, 'INDEPENDENT_MILP_LAYOUT')
    near(model['initial_log_wealth'], start, 'MILP_FORMED_START', relative='1e-12', absolute='1e-12')
    near(model['initial_log_peak'], initial_peak, 'MILP_FORMED_PEAK', relative='1e-12', absolute='1e-12')
    need(model['dd_cap'] == dd_cap and model['log_growth_floor'] == growth_floor,
         'NO_RETUNED_MILP_RISK_OR_GROWTH_TARGET')
    without_hash = {key: value for key, value in model.items() if key != 'definition_sha256'}
    need(hashlib.sha256(encoded(without_hash)).hexdigest() == model['definition_sha256'],
         'EXACT_MODEL_DEFINITION_COMMITMENT')
    fields = ('col_lower', 'col_upper', 'col_cost', 'integrality')
    need(all(len(model[field]) == columns for field in fields), 'ALL_MODEL_COLUMNS')
    expected_cost = [0.]*columns
    expected_cost[risk_column if risk_column is not None else wealth+n-1] = 1.
    need(model['col_cost'] == expected_cost
         and model['integrality'] == [1]*edges+[0]*(columns-edges)
         and model['objective_sense'] == ('MINIMIZE' if risk_column is not None else 'MAXIMIZE'),
         'FROZEN_OBJECTIVE_AND_INTEGER_EXPOSURES')
    need(model['col_lower'][:edges] == [0.]*edges and model['col_upper'][:edges] == [1.]*edges,
         'UNLEVERED_BINARY_FLOW_BOUNDS')
    low, high, highest = start, start, initial_peak
    for t, day in enumerate(raw_logs):
        low += min(min(row) for row in day)
        high += max(max(row) for row in day)
        highest = max(highest, high)
        for actual, expected in ((model['col_lower'][wealth+t], low-1e-8),
                                 (model['col_upper'][wealth+t], high+1e-8),
                                 (model['col_lower'][peak+t], initial_peak),
                                 (model['col_upper'][peak+t], highest+1e-8)):
            near(actual, expected, 'SAFE_PATH_INDEPENDENT_LOG_BOUND', relative='1e-10', absolute='1e-10')
    if risk_column is not None:
        need(abs(model['col_lower'][risk_column]-max(0., initial_peak-start)) <= 1e-10,
             'FORMED_LOSS_INCLUDED_IN_DRAWDOWN')
        expected_upper = max(model['col_upper'][peak+t]-model['col_lower'][wealth+t] for t in range(n))+1.
        near(model['col_upper'][risk_column], expected_upper, 'SAFE_RISK_VARIABLE_UPPER_BOUND',
             relative='1e-10', absolute='1e-10')
    else:
        need(0 <= dd_cap < 1 and initial_peak-start <= -math.log1p(-dd_cap)+1e-8,
             'FORMED_START_WITHIN_DECLARED_CAP')
    rows = n*8+1+(mode == 'min_drawdown')
    need(len(model['row_labels']) == len(model['row_lower']) == len(model['row_upper']) == rows
         and len(set(model['row_labels'])) == rows, 'EXACT_SEMANTIC_ROW_INVENTORY')
    need(len(model['row_starts']) == rows+1 and model['row_starts'][0] == 0
         and model['row_starts'][-1] == len(model['row_indices']) == len(model['row_values'])
         and model['row_starts'] == sorted(model['row_starts']), 'COMPLETE_SPARSE_MATRIX')
    labels = {label: row for row, label in enumerate(model['row_labels'])}
    edge = lambda t, old, new: t*9+old*3+new
    def verify(label, terms, lower=-1e30, upper=1e30):
        need(label in labels, 'REQUIRED_SEMANTIC_ROW:' + label)
        row = labels[label]
        coefficient_row(matrix_terms(model, row), terms, label)
        near(model['row_lower'][row], lower, 'ROW_LOWER:' + label, relative='1e-12', absolute='1e-12')
        near(model['row_upper'][row], upper, 'ROW_UPPER:' + label, relative='1e-12', absolute='1e-12')
    for t in range(n):
        verify(f'one_edge:{t}', {edge(t,a,b): 1. for a,b in itertools.product(range(3), repeat=2)}, 1., 1.)
        for state in range(3):
            terms = {edge(t,state,new): 1. for new in range(3)}
            if t:
                terms.update({edge(t-1,old,state): -1. for old in range(3)})
                target = 0.
            else:
                target = float(state == 2)
            verify(f'flow:{t}:{state}', terms, target, target)
        terms = {edge(t,a,b): -logs[t][a][b] for a,b in itertools.product(range(3), repeat=2)}
        terms[wealth+t] = 1.
        if t:
            terms[wealth+t-1] = -1.
        verify(f'wealth:{t}', terms, start if t == 0 else 0., start if t == 0 else 0.)
        verify(f'peak_above_wealth:{t}', {peak+t: 1., wealth+t: -1.}, 0.)
        terms = {peak+t: 1.}
        if t:
            terms[peak+t-1] = -1.
        verify(f'peak_nondecreasing:{t}', terms, 0. if t else initial_peak)
        terms = {peak+t: 1., wealth+t: -1.}
        if risk_column is not None:
            terms[risk_column] = -1.
        verify(f'drawdown:{t}', terms,
               upper=0. if risk_column is not None else -math.log1p(-dd_cap))
    verify('switch_budget', {edge(t,a,b): 1. for t in range(n)
           for a,b in itertools.product(range(3), repeat=2) if a != b}, upper=float(budget))
    if risk_column is not None:
        verify('growth_floor', {wealth+n-1: 1.}, growth_floor)
    return dict(days=n, rows=rows, columns=columns, nonzeros=len(model['row_values']))


def verify_native_log(record, evidence):
    filename = record['file']
    need(type(filename) is str and Path(filename).name == filename, 'NATIVE_LOG_BASENAME_ONLY')
    path = evidence/filename
    need(path.resolve().parent == evidence.resolve() and path.is_file(), 'NATIVE_LOG_INSIDE_EVIDENCE')
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == record['sha256']
         and raw.decode(errors='replace') == record['text'], 'EXACT_PRESERVED_NATIVE_SOLVER_LOG')
    return record['text']


def expected_model_entries(model):
    return [[row, column, value] for row in range(len(model['row_labels']))
            for column, value in matrix_terms(model, row).items()]


def verify_retained_lp(model, retained, threshold):
    entries = expected_model_entries(model)
    expected = [entry for entry in entries if abs(entry[2]) > threshold]
    omitted = [entry for entry in entries if abs(entry[2]) <= threshold]
    need(retained['entries'] == expected, 'NATIVE_RETAINED_MATRIX_EQUALS_DECLARED_COEFFICIENTS')
    need(retained['columns'] == model['columns'] and retained['rows'] == len(model['row_labels'])
         and retained['col_cost'] == model['col_cost']
         and retained['integrality'] == model['integrality']
         and retained['objective_sense'] == model['objective_sense']
         and retained['objective_offset'] == 0, 'NATIVE_RETAINED_OBJECTIVE_AND_INTEGRALITY')
    def native_bound(value):
        value = float(value)
        return ('INF' if value > 0 else '-INF') if abs(value) >= 1e20 else value
    for name in ('col_lower', 'col_upper', 'row_lower', 'row_upper'):
        need(retained[name] == [native_bound(value) for value in model[name]],
             'NATIVE_RETAINED_BOUND_NORMALIZATION:' + name)
    return omitted


def verify_loading(proof, table, budget, mode, dd_cap, growth_floor, evidence):
    audit = proof['model_loading']
    need(audit['schema'] == 'research.sentinel-oracle-model-loading/1'
         and audit['numerical_model_only_optimized'] is True,
         'ORIGINAL_WARNING_MODEL_IS_DIAGNOSTIC_ONLY')
    original = audit['original_model']
    verify_model(original, table, budget, mode, dd_cap, growth_floor, zero_threshold=0.)
    source = audit['source_load']
    need(source['status'] in ('HighsStatus.kOk', 'HighsStatus.kWarning') and source['solved'] is False,
         'SOURCE_MODEL_NOT_SOLVED_AFTER_WARNING')
    threshold = source['default_small_matrix_value']
    need(type(threshold) is float and math.isfinite(threshold) and 0 < threshold < 1,
         'ACTUAL_NATIVE_DEFAULT_SMALL_MATRIX_THRESHOLD')
    omissions = verify_retained_lp(original, source['retained_lp'], threshold)
    need(source['omissions'] == omissions, 'NATIVE_ORIGINAL_COEFFICIENT_OMISSION_INVENTORY')
    source_text = verify_native_log(source['native_log'], evidence)
    warnings = [line for line in source_text.splitlines() if 'WARNING' in line.upper()]
    if source['status'] == 'HighsStatus.kWarning':
        need(omissions and warnings and all('matrix packed' in line.lower()
             and 'less than or equal to' in line.lower() and 'ignored' in line.lower() for line in warnings),
             'ONLY_NATIVE_TINY_MATRIX_OMISSION_WARNING_ALLOWED_AS_DIAGNOSIS')
    else:
        need(not omissions and not warnings, 'CLEAN_SOURCE_LOAD_HAS_NO_SILENT_TRANSFORMATION')
    final = audit['numerical_load']
    need(final['status'] == 'HighsStatus.kOk' and final['small_matrix_value'] == COEFFICIENT_EPS,
         'REPAIRED_NUMERICAL_LOAD_MUST_SUCCEED_WITHOUT_WARNING')
    need(not verify_retained_lp(proof['model'], final['retained_lp'], 0.),
         'FINAL_RETAINED_MODEL_HAS_NO_UNDECLARED_OMISSIONS')
    final_text = verify_native_log(final['native_log'], evidence)
    need('WARNING' not in final_text.upper(), 'NO_NUMERICAL_MODEL_LOADING_WARNINGS')
    return dict(original_status=source['status'], original_omission_count=len(omissions),
                numerical_status=final['status'], original_warning_model_solved=False,
                source_path_log_wealth_error_bound=proof['model']['coefficient_zeroing'][
                    'source_path_log_wealth_error_bound'],
                source_path_log_drawdown_error_bound=proof['model']['coefficient_zeroing'][
                    'source_path_log_drawdown_error_bound'])


def verify_solution(model, solution):
    need(len(solution) == model['columns'] and all(math.isfinite(value) for value in solution),
         'FINITE_PRIMAL_SOLUTION')
    residual = 0.
    for column, value in enumerate(solution):
        residual = max(residual, model['col_lower'][column]-value, value-model['col_upper'][column])
        if model['integrality'][column]:
            residual = max(residual, abs(value-round(value)))
    for row in range(len(model['row_labels'])):
        activity = math.fsum(value*solution[column] for column, value in matrix_terms(model, row).items())
        residual = max(residual, model['row_lower'][row]-activity, activity-model['row_upper'][row])
    need(residual <= 2e-6, 'INDEPENDENT_PRIMAL_CONSTRAINT_RESIDUAL:' + str(residual))
    codes = [2]
    for t in range(model['days']):
        chosen = [edge for edge, value in enumerate(solution[t*9:t*9+9]) if value > .5]
        need(len(chosen) == 1 and chosen[0]//3 == codes[-1], 'CONNECTED_INTEGER_EXPOSURE_PATH')
        codes.append(chosen[0] % 3)
    return codes, residual


def verify_milp(proof, result, table, budget, mode, dd_cap, growth_floor, codes, evidence):
    model, solution, archived = proof['model'], proof['solution'], proof['result']
    definition = verify_model(model, table, budget, mode, dd_cap, growth_floor)
    loading = verify_loading(proof, table, budget, mode, dd_cap, growth_floor, evidence)
    need(all(result.get(key) == value for key, value in archived.items()), 'EXACT_ARCHIVED_SOLVER_RESULT')
    selected, residual = verify_solution(model, solution)
    need(selected == codes == result['codes'], 'SOLVER_PATH_AND_ACCOUNT_PATH_AGREE')
    need(result['solver_version'] == '1.15.1'
         and result['method'] == 'DAILY_THREE_STATE_MIXED_INTEGER_LOG_WEALTH'
         and result['options'] == dict(threads=2, random_seed=0, mip_rel_gap=1e-7,
                                     time_limit=1800., output_flag=True, log_to_console=False,
                                     small_matrix_value=COEFFICIENT_EPS)
         and result['optimality_scope'] == 'DECLARED_NUMERICAL_MILP_NOT_AN_EXACT_SOURCE_COEFFICIENT_OPTIMUM'
         and result['coefficient_zeroing'] == model['coefficient_zeroing'],
         'PINNED_SOLVER_AND_FROZEN_OPTIONS')
    verify_native_log(result['solver_native_log'], evidence)
    need(result['status'] in ('HighsModelStatus.kOptimal', 'HighsModelStatus.kTimeLimit')
         and result['optimal'] == (result['status'] == 'HighsModelStatus.kOptimal')
         and result['hindsight_only'] is True, 'HONEST_SOLVER_STOP_AND_OPTIMALITY_STATUS')
    need(result['model_definition_sha256'] == model['definition_sha256']
         and result['model_columns'] == definition['columns']
         and result['model_rows'] == definition['rows']
         and result['model_nonzeros'] == definition['nonzeros'], 'ACTUAL_SOLVED_MODEL_DIMENSIONS')
    need(sum(a != b for a,b in zip(codes, codes[1:])) <= budget, 'SOLVER_REALIZED_SWITCH_BUDGET')
    wealth = math.log(float(num(table['startup']['net'])))
    peak, worst = max(0., wealth), max(0., -wealth)
    for t, day in enumerate(table['days']):
        wealth += math.log(float(num(day['net'][codes[t]][codes[t+1]])))
        peak = max(peak, wealth)
        worst = max(worst, peak-wealth)
    objective = worst if mode == 'min_drawdown' else wealth
    near(result['primal_objective'], objective, 'INDEPENDENT_MILP_SELECTED_OBJECTIVE',
         relative='1e-8', absolute='3e-6')
    near(result['independently_scored_objective'], objective, 'INDEPENDENT_PATH_OBJECTIVE',
         relative='1e-8', absolute='3e-6')
    dot = math.fsum(c*v for c,v in zip(model['col_cost'], solution))
    near(dot, result['primal_objective'], 'SOLVER_ACTUAL_LINEAR_OBJECTIVE', relative='1e-8', absolute='3e-6')
    bound, gap = float(result['dual_bound']), float(result['relative_gap'])
    need(math.isfinite(bound) and math.isfinite(gap) and gap >= 0, 'FINITE_SOLVER_BOUND_AND_GAP')
    need((bound <= objective+3e-6 if mode == 'min_drawdown' else bound >= objective-3e-6),
         'INDEPENDENT_BOUND_DIRECTION')
    if result['optimal']:
        need(gap <= 1e-7+1e-9, 'OPTIMAL_STATUS_WITHIN_FROZEN_RELATIVE_GAP')
        need(abs(bound-float(result['primal_objective'])) <=
             max(3e-6, 1.01e-7*abs(float(result['primal_objective']))),
             'OPTIMAL_BOUND_COINCIDES_WITH_INCUMBENT_WITHIN_TOLERANCE')
    if mode == 'min_drawdown':
        need(wealth >= growth_floor-2e-6, 'INDEPENDENT_MATCHED_GROWTH_FLOOR')
    else:
        need(worst <= -math.log1p(-dd_cap)+2e-6, 'INDEPENDENT_DRAWDOWN_CAP')
    return dict(**definition, primal_objective=objective, dual_bound=bound,
                relative_gap=gap, primal_constraint_residual=residual,
                model_loading=loading,
                full_problem_resolved_independently=False,
                bound_scope='SOURCE_ATTESTED_PINNED_SOLVER_BOUND')


def cycles(codes, axis, *, zero=False):
    """Independent interval scan; effective-open indices have exclusive ends."""
    intervals = []
    start = None
    for position in range(len(codes)+1):
        active = position < len(codes) and (codes[position] == 0 if zero else codes[position] < 2)
        if active and start is None:
            start = position+1
        elif not active and start is not None:
            end = position+1 if position < len(codes) else None
            intervals.append((start, end))
            start = None
    output = []
    for identifier, (start, end) in enumerate(intervals):
        last = (end if end is not None else len(axis))-1
        output.append(dict(id=identifier, start_index=start, end_index=end,
            start_session=axis[start], reduction_decision_session=axis[start-1],
            restore_session=None if end is None else axis[end],
            restore_decision_session=None if end is None else axis[end-1],
            last_reduced_session=axis[last], sessions=last-start+1, censored=end is None))
    return output


def independent_attribution(source, table, baseline, candidate):
    axis = source['axis']
    levels = (0., .55, 1.)
    buckets = {key: dict(sessions=0, log_advantage=0., gross_log_advantage=0., cost_log_advantage=0.)
               for key in ('LOWER_AFTER_OPEN', 'HIGHER_AFTER_OPEN', 'SAME_AFTER_OPEN')}
    switching = {key: dict(sessions=0, log_advantage=0.) for key in ('ANY_SWITCH', 'NO_SWITCH')}
    days = []
    for index in range(1, len(axis)):
        old_a, old_b = (baseline[index-2], candidate[index-2]) if index > 1 else (2,2)
        a,b = baseline[index-1], candidate[index-1]
        if index == 1:
            ea = eb = table['startup']
        else:
            day = table['days'][index-2]
            ea = {name:day[name][old_a][a] for name in ('net','gross','cost')}
            eb = {name:day[name][old_b][b] for name in ('net','gross','cost')}
        advantage = math.log(float(num(eb['net'])))-math.log(float(num(ea['net'])))
        gross = math.log(float(num(eb['gross'])))-math.log(float(num(ea['gross'])))
        label = 'LOWER_AFTER_OPEN' if b < a else 'HIGHER_AFTER_OPEN' if b > a else 'SAME_AFTER_OPEN'
        bucket = buckets[label]
        bucket['sessions'] += 1
        bucket['log_advantage'] += advantage
        bucket['gross_log_advantage'] += gross
        bucket['cost_log_advantage'] += advantage-gross
        changed = index > 1 and (a != old_a or b != old_b)
        switch = switching['ANY_SWITCH' if changed else 'NO_SWITCH']
        switch['sessions'] += 1;switch['log_advantage'] += advantage
        days.append(dict(session=axis[index], decision_session=axis[index-1],
            baseline_old=levels[old_a] if index > 1 else None,
            baseline_effective=levels[a], oracle_old=levels[old_b] if index > 1 else None,
            oracle_effective=levels[b], bucket=label, any_switch=changed,
            log_advantage=advantage, gross_log_advantage=gross, cost_log_advantage=advantage-gross))
    original, oracle = cycles(baseline, axis), cycles(candidate, axis)
    pairs = {base['id']: [other['id'] for other in oracle
             if max(base['start_index'], other['start_index']) <
                min(base['end_index'] or len(axis), other['end_index'] or len(axis))]
             for base in original}
    reverse = {other['id']: [identifier for identifier, ids in pairs.items() if other['id'] in ids]
               for other in oracle}
    matches, uniquely_matched = [], set()
    for base in original:
        ids = pairs[base['id']]
        if len(ids) != 1 or len(reverse[ids[0]]) != 1:
            matches.append(dict(baseline_cycle=base['id'], oracle_cycles=ids, status='UNMATCHED_OR_MIXED'))
            continue
        other = oracle[ids[0]]
        uniquely_matched.add(other['id'])
        reduction = other['start_index']-base['start_index']
        restore = (other['end_index']-base['end_index']
                   if other['end_index'] is not None and base['end_index'] is not None else None)
        timing = lambda value: 'EARLIER' if value < 0 else 'LATER' if value > 0 else 'SAME'
        matches.append(dict(baseline_cycle=base['id'], oracle_cycles=ids, status='UNIQUE_OVERLAP',
            reduction_shift_sessions=reduction, reduction_timing=timing(reduction),
            restore_shift_sessions=restore, restore_timing=None if restore is None else timing(restore)))
    windows = cycles(baseline, axis, zero=True)
    for window in windows:
        start, end = window['start_index'], window['end_index'] or len(axis)
        window['oracle_exposure_sessions'] = {str(levels[code]):sum(candidate[index-1] == code
            for index in range(start,end)) for code in range(3)}
        window['log_advantage'] = sum(day['log_advantage'] for day in days[start-1:end-1])
    return dict(scope='HINDSIGHT_DIAGNOSTIC_ONLY', training_eligible=False,
        exposure_buckets=buckets, switch_buckets=switching,
        total_log_advantage=sum(day['log_advantage'] for day in days), days=days,
        baseline_defensive_cycles=original, oracle_defensive_cycles=oracle,
        unique_overlap_event_matches=matches,
        unmatched_oracle_cycle_ids=[item['id'] for item in oracle if item['id'] not in uniquely_matched],
        original_zero_windows=windows)


def recursive_equal(actual, expected, label):
    if isinstance(expected, dict):
        need(isinstance(actual, dict), 'REVIEW_MAPPING:' + label)
        for key, value in expected.items():
            need(key in actual, 'REVIEW_FIELD:' + label + ':' + key)
            recursive_equal(actual[key], value, label + ':' + key)
    elif isinstance(expected, list):
        need(isinstance(actual, list) and len(actual) == len(expected), 'REVIEW_LIST:' + label)
        for index, (a,b) in enumerate(zip(actual, expected)):
            recursive_equal(a,b,label + ':' + str(index))
    elif type(expected) is float:
        near(actual, expected, 'REVIEW_FLOAT:' + label, relative='1e-9', absolute='1e-9')
    else:
        need(actual == expected, 'REVIEW_VALUE:' + label)


def path_constraints(replayed, budget, *, cap=None, growth_floor=None):
    metrics = replayed['metrics']
    need(metrics['ordinary_switches'] <= budget, 'INDEPENDENT_PATH_BUDGET')
    if cap is not None:
        need(float(num(metrics['maximum_drawdown_fraction'])) <= cap+2e-6, 'INDEPENDENT_PATH_RISK_CAP')
    if growth_floor is not None:
        need(metrics['total_log_growth'] >= growth_floor-2e-6, 'INDEPENDENT_PATH_GROWTH_FLOOR')


def scope_check(report):
    need(report['status'] == 'SENTINEL_ORACLE_DIAGNOSTIC_COMPLETE'
         and report['account_domain'] == 'ORIGINAL_SCALAR_RESEARCH_WITH_FORMED_ENTRY'
         and report['hindsight_only'] is True
         and report['training_labels'] == 'HINDSIGHT_DIAGNOSTIC_ONLY_NOT_CAUSAL_TRAINING_LABELS'
         and report['new_Core_steps'] == report['new_Sentinel_steps'] == 0,
         'HINDSIGHT_ONLY_ACCOUNT_SCOPE_NO_CAUSAL_TRAINING_CLAIM')


def failure_required(callback, name):
    try:
        callback()
    except (ValueError, KeyError, TypeError, AssertionError):
        return
    raise ValueError('UNDETECTED_FALSIFIER:' + name)


def numerical_checks(source, table, report, expected, proofs, evidence):
    checks = []
    def refuses(name, callback):
        failure_required(callback, name);checks.append(name)
    # Known independent arithmetic distinguishes old overnight ownership from
    # the newly selected intraday sleeve, and the canonical unchanged55 branch.
    previous = dict(economics=dict(parent_core_close_equity='100'))
    row = dict(economics=dict(parent_core_open_equity='80', parent_core_close_equity='100',
        bil_open_adjusted='1', bil_close_adjusted='1',
        bil_previous_close_adjusted_current_publication='1'))
    edge = ordinary_factor(previous, row, 2, 0)
    need(num(edge['net']) == D('.7992') and num(edge['cost']) == D('.999'),
         'CANARY_OLD_EXPOSURE_OWNS_GAP_AND_PAYS_FEE')
    need(num(ordinary_factor(previous, row, 1, 1)['net']) == 1,
         'CANARY_UNCHANGED55_IS_NOT_OPEN_REBALANCE_PRODUCT')
    checks.extend(('OLD_EXPOSURE_OVERNIGHT', 'ALLOCATION_FEE', 'UNCHANGED55_BRANCH'))
    altered = {**table, 'startup': {**table['startup'], 'net': str(num(table['startup']['net'])+D('.0001'))}}
    refuses('FORMED_ENTRY_TAMPERING', lambda: verify_table(altered, table))
    raw = {**row, 'economics': {**row['economics'], 'parent_core_open_equity': 'NaN'}}
    refuses('NONFINITE_SOURCE_PRICE', lambda: ordinary_factor(previous, raw, 2, 0))
    actual = report['paths']['baseline']['replay']
    shifted_rows = list(actual['rows'])
    shifted_rows[3] = {**shifted_rows[3], 'decision_session': source['axis'][3]}
    refuses('ONE_SESSION_DECISION_SHIFT', lambda: verify_replay(
        {**actual, 'rows': shifted_rows}, expected['baseline'], 'SHIFTED'))
    final_rows = list(actual['rows'])
    final_rows[-1] = {**final_rows[-1], 'last_unexecuted_intent': False}
    refuses('INVENTED_LAST_CLOSE_EXECUTION', lambda: verify_replay(
        {**actual, 'rows': final_rows}, expected['baseline'], 'LAST_INTENT'))
    violated = {**expected['baseline'], 'metrics': {**expected['baseline']['metrics'], 'ordinary_switches': 20}}
    refuses('SWITCH_BUDGET_VIOLATION', lambda: path_constraints(violated, 19))
    cap = float(num(expected['baseline']['metrics']['maximum_drawdown_fraction']))
    violated = {**expected['baseline'], 'metrics': {**expected['baseline']['metrics'],
        'maximum_drawdown_fraction': str(cap+.01)}}
    refuses('DRAWDOWN_CAP_VIOLATION', lambda: path_constraints(violated, 19, cap=cap))
    violated = {**expected['always_core'], 'metrics': {**expected['always_core']['metrics'],
        'total_log_growth': expected['always_core']['metrics']['total_log_growth']-.01}}
    floor = expected['always_core']['metrics']['total_log_growth']
    refuses('MATCHED_GROWTH_VIOLATION', lambda: path_constraints(violated, 19, growth_floor=floor))
    wrong_rows = list(actual['rows'])
    trough = source['axis'].index(expected['baseline']['metrics']['trough_session'])
    wrong_rows[trough] = {**wrong_rows[trough], 'high_water_mark': wrong_rows[trough]['nav']}
    refuses('PEAK_MEMORY_REMOVED', lambda: verify_replay(
        {**actual, 'rows': wrong_rows}, expected['baseline'], 'LOST_PEAK'))
    changed_scope = {**report, 'training_labels': 'CAUSAL_TRAINING_LABELS'}
    refuses('HINDSIGHT_LABELS_MISREPRESENTED', lambda: scope_check(changed_scope))
    changed_identity = {**actual, 'identity': {**actual['identity'], 'daily_sha256': '0'*64}}
    refuses('SOURCE_IDENTITY_TAMPERING', lambda: verify_replay(changed_identity, expected['baseline'], 'IDENTITY'))
    # Matched-growth always has an archived full MILP proof.
    proof = proofs['matched_growth']
    model = proof['model']
    fractional = list(proof['solution'])
    chosen = next(index for index, value in enumerate(fractional[:model['edge_columns']]) if value > .5)
    fractional[chosen] = .5
    refuses('FRACTIONAL_OR_INFEASIBLE_INCUMBENT', lambda: verify_solution(model, fractional))
    relaxed = {**model, 'row_upper': list(model['row_upper'])}
    position = model['row_labels'].index('switch_budget')
    relaxed['row_upper'][position] = 20.
    relaxed['definition_sha256'] = hashlib.sha256(encoded(
        {key: value for key, value in relaxed.items() if key != 'definition_sha256'})).hexdigest()
    refuses('RELAXED_MODEL_CHANGE_BUDGET', lambda: verify_model(
        relaxed, table, 19, 'min_drawdown', None, floor))
    zeroing = model['coefficient_zeroing']
    need(zeroing['omissions'] and zeroing['source_path_log_wealth_error_bound'] > 0,
         'ACTUAL_SOURCE_TINY_COEFFICIENT_CANARY_IS_NONVACUOUS')
    wrong_policy = {**model, 'coefficient_zeroing': {**zeroing, 'threshold': 1e-9}}
    refuses('UNDECLARED_COEFFICIENT_ZEROING_THRESHOLD', lambda: verify_model(
        wrong_policy, table, 19, 'min_drawdown', None, floor))
    understated = {**model, 'coefficient_zeroing': {**zeroing,
        'source_path_log_wealth_error_bound': 0., 'source_path_log_drawdown_error_bound': 0.}}
    refuses('UNDERSTATED_SOURCE_COEFFICIENT_ERROR', lambda: verify_model(
        understated, table, 19, 'min_drawdown', None, floor))
    loading = proof['model_loading']
    warned = {**proof, 'model_loading': {**loading, 'numerical_load': {
        **loading['numerical_load'], 'status': 'HighsStatus.kWarning'}}}
    refuses('WARNING_ACCEPTED_AS_NUMERICAL_LOAD_SUCCESS', lambda: verify_loading(
        warned, table, 19, 'min_drawdown', None, floor, evidence))
    solved_source = {**proof, 'model_loading': {**loading, 'source_load': {
        **loading['source_load'], 'solved': True}}}
    refuses('ORIGINAL_WARNING_MODEL_SOLVED', lambda: verify_loading(
        solved_source, table, 19, 'min_drawdown', None, floor, evidence))
    retained = loading['numerical_load']['retained_lp']
    wrong_entries = list(retained['entries'])
    wrong_entries[0] = list(wrong_entries[0])
    wrong_entries[0][2] += .001
    refuses('UNDECLARED_NATIVE_RETAINED_MATRIX_TRANSFORMATION', lambda: verify_retained_lp(
        model, {**retained, 'entries': wrong_entries}, 0.))
    from review_synthetics import run_checks
    tiny = run_checks(independent_dp)
    return dict(status='PASSED', negative_checks=checks, independent_tiny_optimization=tiny)


def review(args):
    hosted()
    need(args.book == Path('/p00/book') and args.evidence == Path('/evidence/worker')
         and args.out == Path('/out/review'), 'EXACT_REVIEW_MOUNTS')
    sys.meta_path.insert(0, NoWorker())
    import data
    need(Path(data.__file__).resolve() == Path('/current/research/sentinel_oracle/data.py'), 'EXACT_DATA_READER')
    source = data.load_source(args.book)
    report_path = args.evidence/'report.json'
    report = json.loads(report_path.read_bytes())
    scope_check(report)
    need(report['source_identity'] == source['identity'] and report['budget'] == 19
         and source['ordinary_switches'] == 19, 'SOURCE_AND_POLICY_CLASS_IDENTITIES')
    need(report['worker_source_sha256'] == file_sha(Path('/current/research/sentinel_oracle/worker.py')),
         'EXACT_FROZEN_WORKER_SOURCE')
    need(report['factor_table_file'] == 'factor-table.json'
         and report['factor_table_sha256'] == file_sha(args.evidence/'factor-table.json'),
         'SOURCE_BOUND_FACTOR_TABLE')
    table = json.loads((args.evidence/'factor-table.json').read_bytes())
    need(table['source_identity'] == source['identity']
         and report['calibration'] == table['proof'], 'EXACT_FACTOR_SOURCE_AND_CALIBRATION')
    need(table['proof']['original_complete_economic_rows_verified'] == 2156
         and table['proof']['ordinary_edges_verified'] == 2154*9
         and table['proof']['first_entry_verified'] is True
         and table['proof']['Core_steps'] == table['proof']['Sentinel_steps'] == 0,
         'COMPLETE_CANONICAL_SOURCE_CALIBRATION')
    independent = independent_table(source)
    verify_table(table, independent)
    names = ('baseline', 'always_core', 'constant55', 'defensive_after_initial',
             'daily_upper', 'primary', 'half_drawdown', 'matched_growth')
    need(set(report['paths']) == set(names), 'EXACT_REFERENCE_AND_ORACLE_PATHS')
    count = len(source['baseline_codes'])
    fixed = dict(baseline=source['baseline_codes'], always_core=[2]*count,
                 constant55=[2]+[1]*(count-1), defensive_after_initial=[2]+[0]*(count-1))
    expected = {}
    for name in names:
        path = report['paths'][name]
        codes = path['codes']
        if name in fixed:
            need(codes == fixed[name], 'FROZEN_REFERENCE_ALLOCATION:' + name)
        expected[name] = independent_replay(source, independent, codes)
        verify_replay(path['replay'], expected[name], name)
        path_constraints(expected[name], 19)
        need(path['replay']['canonical_direct_replay_verified'] is True,
             'CANONICAL_DECIMAL_DIRECT_REPLAY_REQUIRED:' + name)
    for row, original in zip(expected['baseline']['rows'], source['rows']):
        for field, source_field in (('nav', 'strategy_nav'), ('net_factor', 'net_factor'),
                                    ('gross_factor', 'gross_factor'),
                                    ('transaction_cost_factor', 'transaction_cost_factor'), ('turnover', 'turnover')):
            near(row[field], original['economics'][source_field], 'EVERY_ORIGINAL_BASELINE:' + field,
                 relative='1e-24', absolute='1e-24')
    optimization = report['optimization']
    need(set(optimization) == {'daily_upper','primary','half_drawdown','matched_growth'},
         'EXACT_FROZEN_OPTIMIZATION_QUESTIONS')
    dp = optimization['daily_upper']
    need(dp['method'] == 'EXACT_DAILY_FINITE_STATE_DYNAMIC_PROGRAMMING'
         and dp['optimal'] is True and dp['hindsight_only'] is True
         and dp['codes'] == report['paths']['daily_upper']['codes'], 'HINDSIGHT_DP_CERTIFICATE_SCOPE')
    dp_review = verify_dp(dp, independent, 19, dp['codes'])
    near(dp['max_log_drawdown'], -math.log1p(-float(num(
        expected['daily_upper']['metrics']['maximum_drawdown_fraction']))),
        'INDEPENDENT_DP_PATH_DRAWDOWN', relative='1e-10', absolute='1e-10')
    need(dp['used_switches'] == expected['daily_upper']['metrics']['ordinary_switches'],
         'INDEPENDENT_DP_USED_CHANGE_COUNT')
    cap = float(num(expected['baseline']['metrics']['maximum_drawdown_fraction']))
    floor = expected['always_core']['metrics']['total_log_growth']
    proofs, solver_checks = {}, {}
    for name in ('primary', 'half_drawdown', 'matched_growth'):
        result, codes = optimization[name], report['paths'][name]['codes']
        question_cap = cap if name == 'primary' else cap/2 if name == 'half_drawdown' else None
        question_floor = floor if name == 'matched_growth' else None
        mode = 'min_drawdown' if name == 'matched_growth' else 'max_growth'
        need(result['codes'] == codes and result['budget'] == 19
             and result['hindsight_only'] is True, 'EXACT_OPTIMIZER_PATH:' + name)
        path_constraints(expected[name], 19, cap=question_cap, growth_floor=question_floor)
        if result['method'] == 'DP_UPPER_BOUND_ATTAINED_WITHIN_DRAWDOWN_CAP':
            need(name != 'matched_growth' and result['optimal'] is True and result['relative_gap'] == 0.
                 and result['dd_cap'] == question_cap and codes == dp['codes'], 'VALID_DP_RISK_FEASIBILITY_CERTIFICATE')
            need(dp['max_log_drawdown'] <= -math.log1p(-question_cap)+1e-8,
                 'DP_PATH_WITHIN_RISK_CAP')
            for field in ('primal_objective', 'dual_bound', 'best_log_terminal'):
                near(result[field], dp_review['best_log_terminal'], 'DP_RISK_OBJECTIVE_MATCHES_GLOBAL_BOUND',
                     relative='1e-10', absolute='1e-10')
            solver_checks[name] = dict(method='INDEPENDENT_DP_GLOBAL_BOUND_AND_FEASIBLE_PATH')
        else:
            filename = 'optimization-' + name + '.json'
            need(result['proof_file'] == filename and result['proof_sha256'] == file_sha(args.evidence/filename),
                 'EXACT_ARCHIVED_MILP_PROOF:' + name)
            proof = json.loads((args.evidence/filename).read_bytes())
            proofs[name] = proof
            solver_checks[name] = verify_milp(proof, result, independent, 19, mode,
                                               question_cap, question_floor, codes, args.evidence)
    need(set(report['attribution']) == set(optimization), 'ALL_ORACLE_ATTRIBUTIONS_VISIBLE')
    expected_windows = [('2018-12-21','2019-02-04',29), ('2020-02-28','2020-04-28',42),
                        ('2022-06-17','2022-08-10',37), ('2024-08-08','2024-10-08',43),
                        ('2025-04-08','2025-05-14',26)]
    for name in optimization:
        attributed = independent_attribution(source, independent, source['baseline_codes'],
                                               report['paths'][name]['codes'])
        recursive_equal(report['attribution'][name], attributed, 'ATTRIBUTION:' + name)
        near(attributed['total_log_advantage'], expected[name]['metrics']['total_log_growth']
             -expected['baseline']['metrics']['total_log_growth'], 'ATTRIBUTION_TELESCOPES:' + name,
             relative='1e-9', absolute='1e-9')
        actual_windows = [(window['start_session'],window['last_reduced_session'],window['sessions'])
                          for window in attributed['original_zero_windows']]
        need(actual_windows == expected_windows, 'FIVE_ORIGINAL_ZERO_EXPOSURE_WINDOWS')
    with localcontext() as ctx:
        ctx.prec = 50
        core_initial = num(source['rows'][0]['economics']['parent_core_close_equity'])
        high, worst = core_initial, D(0)
        for row in source['rows']:
            core_final = num(row['economics']['parent_core_close_equity'])
            high = max(high, core_final)
            worst = min(worst, core_final/high-1)
        multiple = core_final/core_initial
    raw = report['raw_core_reference']
    need(raw['scope'] == 'RAW_CORE_REFERENCE_NOT_FUNDED_COMPARATOR', 'DISTINCT_RAW_CORE_SCOPE')
    for field, value in (('initial_nav',core_initial), ('final_nav',core_final), ('multiple',multiple),
                         ('maximum_drawdown_fraction',-worst)):
        near(raw[field],value,'INDEPENDENT_RAW_CORE:' + field)
    days = (date.fromisoformat(source['axis'][-1])-date.fromisoformat(source['axis'][0])).days
    near(raw['cagr_pct'],100*math.expm1(math.log(float(multiple))*365.2425/days),
         'INDEPENDENT_RAW_CORE_CAGR', relative='1e-9', absolute='1e-9')
    near(raw['max_drawdown_pct'], -100*float(worst), 'INDEPENDENT_RAW_CORE_DRAWDOWN_PCT',
         relative='1e-9', absolute='1e-9')
    need(report['proofs']['account']['status'] == report['proofs']['optimizer']['status'] == 'PASSED',
         'WORKER_NUMERICAL_FALSIFIERS_PASSED')
    checks = numerical_checks(source, independent, report, expected, proofs, args.evidence)
    need(not args.out.exists(), 'NEW_REVIEW_OUTPUT')
    args.out.mkdir(parents=True)
    verdict = dict(status='SENTINEL_ORACLE_DIAGNOSTIC_REVIEW_PASSED', source_identity=source['identity'],
        account_domain='ORIGINAL_SCALAR_RESEARCH_WITH_FORMED_ENTRY', hindsight_only=True,
        training_labels='HINDSIGHT_DIAGNOSTIC_ONLY_NOT_CAUSAL_TRAINING_LABELS',
        canonical_ordinary_edges_independently_checked=2154*9, baseline_closes=2156,
        paths_verified=len(names), path_close_comparisons=len(names)*2156,
        dp_global_bound_independently_recomputed=dp_review['best_log_terminal'],
        solver_verification=solver_checks, numerical_checks=checks,
        limitations=['FULL_MILP_BOUNDS_SOURCE_ATTESTED_NOT_INDEPENDENTLY_RESOLVED',
                     'DECLARED_NUMERICAL_MILP_OPTIMALITY_WITH_SEPARATE_SOURCE_REPLAY',
                     'NO_PREDICTABILITY_OR_TRAINING_CLAIM','NOT_PERSISTENT_WHOLE_SHARE_EXECUTION'],
        report_sha256=file_sha(report_path), review_source_sha256=file_sha(Path(__file__)),
        new_Core_steps=0, new_Sentinel_steps=0, production_contacted=False,
        portfolio_performance_admitted=False)
    (args.out/'independent-review.json').write_bytes(encoded(verdict)+b'\n')
    print(json.dumps(dict(status=verdict['status'], paths=len(names), closes=2156)), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ('book', 'out', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    hosted()
    review(args)


if __name__ == '__main__':
    main()
