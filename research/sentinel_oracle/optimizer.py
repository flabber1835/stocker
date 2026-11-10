"""Hosted-only finite-state hindsight optimization; never an online controller."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time


def need(value, code):
    if not value:
        raise ValueError(code)


need(os.environ.get('SENTINEL_ORACLE_HOSTED') == '1'
     and Path(__file__).resolve() == Path('/current/research/sentinel_oracle/optimizer.py'),
     'HOSTED_ORACLE_OPTIMIZER_ONLY')

import numpy as np
import highspy

need(Path(highspy.__file__).resolve().is_relative_to(Path('/solver')),
     'EXACT_READ_ONLY_SOLVER_EXTENSION')

SCHEMA = 'research.sentinel-hindsight-optimizer/2'
INF = 1e30
LOG_TOL = 1e-8
ZERO_THRESHOLD = 1e-12
_LOAD_SEQUENCE = 0


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def log_factors(table):
    values = np.asarray([day['net'] for day in table['days']], dtype=np.float64)
    need(values.ndim == 3 and values.shape[1:] == (3, 3)
         and np.isfinite(values).all() and (values > 0).all(), 'NINE_FINITE_POSITIVE_EDGES')
    start = math.log(float(table['startup']['net']))
    need(math.isfinite(start) and table['startup']['new_code'] == 2, 'FIXED_FULL_FORMED_START')
    return start, np.log(values)


def selected_log_path(table, codes):
    start, logs = log_factors(table)
    need(len(codes) == len(logs) + 1 and codes[0] == 2
         and all(type(code) is int and 0 <= code < 3 for code in codes), 'EXACT_DAILY_CODE_PATH')
    wealth, peak, worst, switches = start, max(0., start), max(0., -start), 0
    history, peaks = [], []
    for t, (old, new) in enumerate(zip(codes, codes[1:])):
        switches += old != new
        wealth += float(logs[t, old, new])
        peak = max(peak, wealth)
        worst = max(worst, peak - wealth)
        history.append(wealth)
        peaks.append(peak)
    return dict(log_terminal=wealth, max_log_drawdown=worst, ordinary_switches=switches,
                log_wealth=history, log_peaks=peaks)


def daily_dp(table, budget):
    """Exact Bellman recurrence on (day, allocation, changes used), in log units."""
    need(type(budget) is int and budget >= 0, 'INTEGER_CHANGE_BUDGET')
    start, logs = log_factors(table)
    count = len(logs)
    need(count > 0 and budget <= count, 'FINITE_DP_HORIZON')
    values = np.full((3, budget + 1), -np.inf)
    values[2, 0] = start
    parents = np.full((count, 3, budget + 1), -1, dtype=np.int8)
    for t in range(count):
        following = np.full_like(values, -np.inf)
        # Holding the current allocation is considered first for exact ties.
        for change in (0, 1):
            for old in (2, 1, 0):
                for new in (2, 1, 0):
                    if (old != new) != bool(change):
                        continue
                    size = budget + 1 - change
                    candidate = values[old, :size] + logs[t, old, new]
                    destination = following[new, change:]
                    better = candidate > destination
                    destination[better] = candidate[better]
                    parents[t, new, change:][better] = old
        values = following
    choices = [(float(values[code, changes]), -changes, code)
               for changes in range(budget + 1) for code in range(3)
               if math.isfinite(float(values[code, changes]))]
    best, negative_changes, code = max(choices)
    changes = -negative_changes
    selected = [code]
    k = changes
    for t in range(count - 1, -1, -1):
        old = int(parents[t, code, k])
        need(old >= 0, 'COMPLETE_DP_BACKPOINTER')
        k -= old != code
        code = old
        selected.append(old)
    selected.reverse()
    path = selected_log_path(table, selected)
    need(code == 2 and k == 0 and path['ordinary_switches'] == changes
         and abs(path['log_terminal'] - best) <= LOG_TOL, 'DP_PATH_ATTAINS_BELLMAN_BOUND')
    terminal = [[None if not math.isfinite(float(v)) else float(v) for v in row] for row in values]
    return dict(schema=SCHEMA, method='EXACT_DAILY_FINITE_STATE_DYNAMIC_PROGRAMMING',
        hindsight_only=True, optimal=True, budget=budget, codes=selected,
        best_log_terminal=best, used_switches=changes,
        terminal_state_values=terminal, logs_sha256=digest(logs.tolist()),
        numerical_log_tolerance=LOG_TOL, max_log_drawdown=path['max_log_drawdown'])


class Rows:
    def __init__(self):
        self.lower, self.upper, self.starts = [], [], [0]
        self.indices, self.values, self.labels = [], [], []

    def add(self, label, terms, lower=-INF, upper=INF):
        merged = {}
        for column, value in terms:
            if value:
                merged[column] = merged.get(column, 0.) + float(value)
        for column in sorted(merged):
            if merged[column]:
                self.indices.append(int(column))
                self.values.append(float(merged[column]))
        self.starts.append(len(self.indices))
        self.lower.append(float(lower)); self.upper.append(float(upper)); self.labels.append(label)


def build_model(table, budget, mode, *, dd_cap=None, log_growth_floor=None,
                zero_threshold=ZERO_THRESHOLD):
    """Daily flow MILP with exact scalar edge log factors and closing high-water marks."""
    need(mode in ('max_growth', 'min_drawdown'), 'FROZEN_OPTIMIZATION_MODE')
    start, logs = log_factors(table)
    n = len(logs)
    need(zero_threshold in (0.,ZERO_THRESHOLD), 'FROZEN_COEFFICIENT_ZEROING_THRESHOLD')
    numerical_logs = logs.copy()
    omissions, per_day_error = [], []
    for t in range(n):
        removed=[]
        for a in range(3):
            for b in range(3):
                coefficient=float(logs[t,a,b])
                if coefficient != 0 and abs(coefficient) <= zero_threshold:
                    numerical_logs[t,a,b]=0.
                    removed.append(abs(coefficient))
                    omissions.append(dict(day=t,old=a,new=b,source_log_coefficient=coefficient))
        per_day_error.append(max(removed,default=0.))
    error_bound=math.fsum(per_day_error)
    need(2*error_bound < LOG_TOL, 'COEFFICIENT_ZEROING_BELOW_FROZEN_LOG_TOLERANCE')
    need(n > 0 and type(budget) is int and 0 <= budget <= n, 'FINITE_MILP_BUDGET')
    edge_count = n * 9
    w0, h0 = edge_count, edge_count + n
    b_column = edge_count + 2*n if mode == 'min_drawdown' else None
    columns = edge_count + 2*n + (b_column is not None)
    lower, upper, costs = [0.]*columns, [1.]*edge_count + [0.]*(columns-edge_count), [0.]*columns
    integrality = [1]*edge_count + [0]*(columns-edge_count)
    prefix_low, prefix_high, highest = start, start, max(0., start)
    initial_peak = highest
    for t in range(n):
        prefix_low += float(np.min(logs[t]))
        prefix_high += float(np.max(logs[t]))
        highest = max(highest, prefix_high)
        lower[w0+t], upper[w0+t] = prefix_low-LOG_TOL, prefix_high+LOG_TOL
        lower[h0+t], upper[h0+t] = initial_peak, highest+LOG_TOL
    if mode == 'max_growth':
        need(type(dd_cap) in (int, float) and 0 <= dd_cap < 1, 'FINITE_DRAWDOWN_CAP')
        risk = -math.log1p(-dd_cap)
        need(initial_peak-start <= risk+LOG_TOL, 'FORMED_START_WITHIN_RISK_CAP')
        costs[w0+n-1] = 1.
    else:
        need(type(log_growth_floor) in (int, float) and math.isfinite(log_growth_floor),
             'FINITE_MATCHED_GROWTH_FLOOR')
        risk = None
        lower[b_column] = max(0., initial_peak-start)
        upper[b_column] = max(upper[h0+t]-lower[w0+t] for t in range(n)) + 1.
        costs[b_column] = 1.
    rows = Rows()
    edge = lambda t, old, new: t*9 + old*3 + new
    for t in range(n):
        rows.add(f'one_edge:{t}', [(edge(t,a,b),1) for a in range(3) for b in range(3)], 1, 1)
        for state in range(3):
            terms = [(edge(t,state,b),1) for b in range(3)]
            if t:
                terms += [(edge(t-1,a,state),-1) for a in range(3)]
                rows.add(f'flow:{t}:{state}', terms, 0, 0)
            else:
                fixed = int(state == 2)
                rows.add(f'flow:{t}:{state}', terms, fixed, fixed)
        terms = [(w0+t,1)] + [(edge(t,a,b),-float(numerical_logs[t,a,b])) for a in range(3) for b in range(3)]
        if t:
            terms.append((w0+t-1,-1))
        rows.add(f'wealth:{t}', terms, start if t == 0 else 0, start if t == 0 else 0)
        rows.add(f'peak_above_wealth:{t}', [(h0+t,1),(w0+t,-1)], 0)
        if t:
            rows.add(f'peak_nondecreasing:{t}', [(h0+t,1),(h0+t-1,-1)], 0)
        else:
            rows.add(f'peak_nondecreasing:{t}', [(h0+t,1)], initial_peak)
        terms = [(h0+t,1),(w0+t,-1)]
        if b_column is not None:
            terms.append((b_column,-1))
        rows.add(f'drawdown:{t}', terms, upper=0 if b_column is not None else risk)
    rows.add('switch_budget', [(edge(t,a,b),1) for t in range(n) for a in range(3)
                              for b in range(3) if a != b], upper=budget)
    if b_column is not None:
        rows.add('growth_floor', [(w0+n-1,1)], log_growth_floor)
    model = dict(schema='research.sentinel-hindsight-milp/1', mode=mode,
        days=n, budget=budget, initial_log_wealth=start, initial_log_peak=initial_peak,
        dd_cap=dd_cap, log_growth_floor=log_growth_floor,
        columns=columns, edge_columns=edge_count, wealth_start=w0, peak_start=h0, risk_column=b_column,
        col_lower=lower, col_upper=upper, col_cost=costs, integrality=integrality,
        row_lower=rows.lower, row_upper=rows.upper, row_starts=rows.starts,
        row_indices=rows.indices, row_values=rows.values, row_labels=rows.labels,
        objective_sense='MAXIMIZE' if mode == 'max_growth' else 'MINIMIZE',
        logs_sha256=digest(logs.tolist()),
        coefficient_zeroing=dict(threshold=zero_threshold,omissions=omissions,
            per_day_maximum_removed=per_day_error,
            source_path_log_wealth_error_bound=error_bound,
            source_path_log_drawdown_error_bound=2*error_bound,
            original_source_factors_and_dp_unchanged=True))
    model['definition_sha256'] = digest(model)
    return model


def vector_for_codes(table, model, codes):
    path = selected_log_path(table, codes)
    values = [0.]*model['columns']
    for t, (old,new) in enumerate(zip(codes,codes[1:])):
        values[t*9+old*3+new] = 1.
        values[model['wealth_start']+t] = path['log_wealth'][t]
        values[model['peak_start']+t] = path['log_peaks'][t]
    if model['risk_column'] is not None:
        values[model['risk_column']] = path['max_log_drawdown']
    return values


def check_vector(model, values, tolerance=2e-6):
    need(len(values) == model['columns'] and all(math.isfinite(v) for v in values), 'FINITE_MILP_SOLUTION')
    residual = 0.
    for i, value in enumerate(values):
        residual = max(residual, model['col_lower'][i]-value, value-model['col_upper'][i])
        if model['integrality'][i]:
            residual = max(residual, abs(value-round(value)))
    for row in range(len(model['row_lower'])):
        begin,end = model['row_starts'][row:row+2]
        activity = math.fsum(model['row_values'][j]*values[model['row_indices'][j]] for j in range(begin,end))
        residual = max(residual, model['row_lower'][row]-activity, activity-model['row_upper'][row])
    need(residual <= tolerance, 'MILP_SOLUTION_CONSTRAINT_RESIDUAL:'+str(residual))
    return residual


def finite_or_none(value):
    value = float(value)
    return value if math.isfinite(value) else None


def _lp_for_model(model):
    lp=highspy.HighsLp()
    lp.num_col_=model['columns']; lp.num_row_=len(model['row_lower'])
    lp.col_cost_=np.asarray(model['col_cost'],dtype=np.float64)
    lp.col_lower_=np.asarray(model['col_lower'],dtype=np.float64)
    lp.col_upper_=np.asarray(model['col_upper'],dtype=np.float64)
    lp.row_lower_=np.asarray(model['row_lower'],dtype=np.float64)
    lp.row_upper_=np.asarray(model['row_upper'],dtype=np.float64)
    lp.integrality_=[highspy.HighsVarType.kInteger if flag else highspy.HighsVarType.kContinuous
                     for flag in model['integrality']]
    lp.a_matrix_.format_=highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_=np.asarray(model['row_starts'],dtype=np.int32)
    lp.a_matrix_.index_=np.asarray(model['row_indices'],dtype=np.int32)
    lp.a_matrix_.value_=np.asarray(model['row_values'],dtype=np.float64)
    lp.sense_=highspy.ObjSense.kMaximize if model['mode']=='max_growth' else highspy.ObjSense.kMinimize
    return lp


def _model_entries(model):
    return [[row,model['row_indices'][j],model['row_values'][j]]
        for row in range(len(model['row_lower']))
        for j in range(model['row_starts'][row],model['row_starts'][row+1])]


def _bound(value):
    value=float(value)
    return ('INF' if value>0 else '-INF') if abs(value)>=1e20 else value


def _retained_lp(lp):
    matrix=lp.a_matrix_
    starts,indices,values=list(matrix.start_),list(matrix.index_),list(matrix.value_)
    entries=[]
    if matrix.format_==highspy.MatrixFormat.kRowwise:
        major=lp.num_row_; rowwise=True
    else:
        need(matrix.format_==highspy.MatrixFormat.kColwise,'KNOWN_RETAINED_MATRIX_FORMAT')
        major=lp.num_col_; rowwise=False
    need(len(starts)==major+1 and starts[-1]==len(indices)==len(values),'COMPLETE_RETAINED_SPARSE_MATRIX')
    for i in range(major):
        for j in range(starts[i],starts[i+1]):
            row,column=(i,int(indices[j])) if rowwise else (int(indices[j]),i)
            entries.append([row,column,float(values[j])])
    entries.sort()
    return dict(columns=lp.num_col_,rows=lp.num_row_,entries=entries,
        col_cost=[float(v) for v in lp.col_cost_],
        col_lower=[_bound(v) for v in lp.col_lower_],col_upper=[_bound(v) for v in lp.col_upper_],
        row_lower=[_bound(v) for v in lp.row_lower_],row_upper=[_bound(v) for v in lp.row_upper_],
        integrality=[int(v==highspy.HighsVarType.kInteger) for v in lp.integrality_],
        objective_sense='MAXIMIZE' if lp.sense_==highspy.ObjSense.kMaximize else 'MINIMIZE',
        objective_offset=float(lp.offset_))


def _verify_retained(model, retained, threshold):
    intended=_model_entries(model)
    expected=[entry for entry in intended if abs(entry[2])>threshold]
    omitted=[entry for entry in intended if abs(entry[2])<=threshold]
    need(retained['entries']==expected,'ONLY_DECLARED_SMALL_MATRIX_VALUES_MAY_BE_OMITTED')
    need(retained['columns']==model['columns'] and retained['rows']==len(model['row_lower'])
         and retained['col_cost']==model['col_cost']
         and retained['integrality']==model['integrality']
         and retained['objective_sense']==model['objective_sense'] and retained['objective_offset']==0,
         'RETAINED_OBJECTIVE_VARIABLES_AND_INTEGRALITY')
    for key in ('col_lower','col_upper','row_lower','row_upper'):
        need(retained[key]==[_bound(v) for v in model[key]],'RETAINED_BOUNDS_UNCHANGED:'+key)
    return omitted


def _configure(options, log_path):
    engine=highspy.Highs()
    need(engine.version()=='1.15.1','PINNED_HIGHS_VERSION')
    for key,value in {**options,'log_file':str(log_path)}.items():
        need(engine.setOptionValue(key,value)==highspy.HighsStatus.kOk,'EXACT_SOLVER_OPTION:'+key)
    return engine


def _close_native_log(engine, path):
    need(engine.setOptionValue('log_file','')==highspy.HighsStatus.kOk,'CLOSE_NATIVE_LOAD_LOG')
    need(path.is_file(),'NATIVE_LOAD_LOG_PRESERVED')
    raw=path.read_bytes()
    return dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest(),text=raw.decode(errors='replace'))


def _load_audit(table,budget,mode,dd_cap,log_growth_floor,model,options,proof_path):
    """Diagnose the original load without solving it, then require the repaired LP verbatim."""
    global _LOAD_SEQUENCE
    _LOAD_SEQUENCE+=1
    folder=Path(proof_path).parent if proof_path is not None else Path('/tmp')
    prefix=Path(proof_path).stem if proof_path is not None else 'oracle-fixture-'+str(_LOAD_SEQUENCE)
    source_log=folder/(prefix+'-source-load.log')
    numerical_log=folder/(prefix+'-numerical-load.log')
    original=build_model(table,budget,mode,dd_cap=dd_cap,log_growth_floor=log_growth_floor,zero_threshold=0.)
    diagnostic=_configure(options,source_log)
    option_status,default_threshold=diagnostic.getOptionValue('small_matrix_value')
    need(option_status==highspy.HighsStatus.kOk and math.isfinite(float(default_threshold))
         and float(default_threshold)>0,'ACTUAL_NATIVE_SMALL_MATRIX_THRESHOLD')
    raw_status=diagnostic.passModel(_lp_for_model(original))
    native=_close_native_log(diagnostic,source_log)
    need(raw_status in (highspy.HighsStatus.kOk,highspy.HighsStatus.kWarning),
         'SOURCE_MODEL_LOAD_NOT_AN_ERROR:'+str(raw_status)+':native_log='+source_log.name)
    retained=_retained_lp(diagnostic.getLp())
    omissions=_verify_retained(original,retained,float(default_threshold))
    warnings=[line for line in native['text'].splitlines() if 'WARNING' in line.upper()]
    if raw_status==highspy.HighsStatus.kWarning:
        need(bool(omissions) and bool(warnings) and all('matrix packed' in line.lower()
             and 'less than or equal to' in line.lower() and 'ignored' in line.lower() for line in warnings),
             'WARNING_IS_EXCLUSIVELY_NATIVE_SMALL_COEFFICIENT_OMISSION')
    else:
        need(not omissions and not warnings,'CLEAN_ORIGINAL_MODEL_LOAD_HAS_NO_SILENT_OMISSIONS')
    source_audit=dict(status=str(raw_status),default_small_matrix_value=float(default_threshold),
        native_log=native,retained_lp=retained,omissions=omissions,solved=False)
    diagnostic.clear()
    numerical_options={**options,'small_matrix_value':ZERO_THRESHOLD}
    engine=_configure(numerical_options,numerical_log)
    numerical_option_status,numerical_threshold=engine.getOptionValue('small_matrix_value')
    need(numerical_option_status==highspy.HighsStatus.kOk
         and float(numerical_threshold)==ZERO_THRESHOLD,'ACTUAL_NUMERICAL_SMALL_MATRIX_THRESHOLD')
    numeric_status=engine.passModel(_lp_for_model(model))
    numerical_native=_close_native_log(engine,numerical_log)
    need(numeric_status==highspy.HighsStatus.kOk,
         'PASS_EXACT_NUMERICAL_HINDSIGHT_MODEL:'+str(numeric_status)+':native_log='+numerical_log.name)
    numerical_retained=_retained_lp(engine.getLp())
    need(not _verify_retained(model,numerical_retained,0.),'NUMERICAL_MODEL_HAS_NO_FURTHER_OMISSIONS')
    need('WARNING' not in numerical_native['text'].upper(),'NUMERICAL_LOAD_HAS_NO_WARNINGS')
    audit=dict(schema='research.sentinel-oracle-model-loading/1',
        original_model=original,source_load=source_audit,
        numerical_load=dict(status=str(numeric_status),small_matrix_value=float(numerical_threshold),
            native_log=numerical_native,retained_lp=numerical_retained),
        numerical_model_only_optimized=True)
    solve_log=folder/(prefix+'-solver.log')
    need(engine.setOptionValue('log_file',str(solve_log))==highspy.HighsStatus.kOk,'PRESERVE_NATIVE_SOLVE_LOG')
    return engine,audit,numerical_options,solve_log


def solve(table, budget, mode, *, dd_cap=None, log_growth_floor=None, warm_codes=None,
          time_limit=1800., proof_path=None):
    model = build_model(table,budget,mode,dd_cap=dd_cap,log_growth_floor=log_growth_floor)
    options = dict(threads=2, random_seed=0, mip_rel_gap=1e-7, time_limit=float(time_limit),
                   output_flag=True, log_to_console=False)
    engine,load_audit,options,solve_log=_load_audit(table,budget,mode,dd_cap,log_growth_floor,
                                                 model,options,proof_path)
    warm_status = None
    if warm_codes is not None:
        warm_values = vector_for_codes(table,model,warm_codes)
        check_vector(model,warm_values)
        initial = highspy.HighsSolution()
        initial.col_value = warm_values
        initial.value_valid = True
        warm_status = str(engine.setSolution(initial))
        need(warm_status == str(highspy.HighsStatus.kOk), 'FEASIBLE_WARM_START_ADMITTED')
    began = time.monotonic()
    run_status = engine.run()
    elapsed = time.monotonic()-began
    status, info, solution = engine.getModelStatus(), engine.getInfo(), engine.getSolution()
    need(run_status in (highspy.HighsStatus.kOk, highspy.HighsStatus.kWarning), 'SOLVER_RETURN_STATUS')
    need(status in (highspy.HighsModelStatus.kOptimal, highspy.HighsModelStatus.kTimeLimit),
         'POSITIVE_OPTIMAL_OR_BOUNDED_TIMEOUT_STATUS:'+str(status))
    need(solution.value_valid, 'FEASIBLE_SOLVER_INCUMBENT_REQUIRED')
    values = [float(v) for v in solution.col_value]
    residual = check_vector(model,values)
    codes = [2]
    for t in range(model['days']):
        selected = [i for i,v in enumerate(values[t*9:t*9+9]) if v > 0.5]
        need(len(selected) == 1 and selected[0]//3 == codes[-1], 'UNIQUE_CONNECTED_DAILY_FLOW')
        codes.append(selected[0]%3)
    path = selected_log_path(table,codes)
    need(path['ordinary_switches'] <= budget, 'RETURNED_PATH_CHANGE_BUDGET')
    if mode == 'max_growth':
        need(path['max_log_drawdown'] <= -math.log1p(-dd_cap)+2e-6, 'RETURNED_PATH_DRAWDOWN_CAP')
        actual_objective = path['log_terminal']
    else:
        need(path['log_terminal'] >= log_growth_floor-2e-6, 'RETURNED_PATH_MATCHED_GROWTH')
        actual_objective = path['max_log_drawdown']
    objective = float(info.objective_function_value)
    need(abs(objective-actual_objective) <= 3e-6, 'PATH_OBJECTIVE_MATCHES_SOLVER')
    bound = finite_or_none(info.mip_dual_bound)
    gap = finite_or_none(info.mip_gap)
    need(bound is not None and gap is not None and gap >= 0, 'FINITE_OBJECTIVE_BOUND_AND_GAP')
    if mode == 'max_growth':
        need(bound+3e-6 >= objective, 'UPPER_BOUND_ORIENTATION')
    else:
        need(bound-3e-6 <= objective, 'LOWER_BOUND_ORIENTATION')
    result = dict(schema=SCHEMA, method='DAILY_THREE_STATE_MIXED_INTEGER_LOG_WEALTH',
        hindsight_only=True, optimal=status == highspy.HighsModelStatus.kOptimal,
        status=str(status), run_status=str(run_status), solver_version=engine.version(),
        mode=mode, budget=budget, dd_cap=dd_cap, log_growth_floor=log_growth_floor,
        options=options, wall_seconds=elapsed, codes=codes, used_switches=path['ordinary_switches'],
        primal_objective=objective, independently_scored_objective=actual_objective,
        dual_bound=bound, relative_gap=gap, node_count=int(info.mip_node_count),
        model_columns=model['columns'], model_rows=len(model['row_lower']),
        model_nonzeros=len(model['row_values']), model_definition_sha256=model['definition_sha256'],
        max_constraint_residual=residual, warm_start_status=warm_status,
        numerical_log_tolerance=3e-6,
        max_log_drawdown=path['max_log_drawdown'], log_terminal=path['log_terminal'],
        optimality_scope='DECLARED_NUMERICAL_MILP_NOT_AN_EXACT_SOURCE_COEFFICIENT_OPTIMUM',
        coefficient_zeroing=model['coefficient_zeroing'],
        solver_native_log=_close_native_log(engine,solve_log))
    if proof_path is not None:
        proof = dict(model=model, solution=values, result=result,model_loading=load_audit)
        Path(proof_path).write_bytes(encoded(proof)+b'\n')
        result['proof_file'] = Path(proof_path).name
        result['proof_sha256'] = hashlib.sha256(Path(proof_path).read_bytes()).hexdigest()
    return result


def fixture_checks():
    """Small financial-path checks run only inside the approved hosted container."""
    import itertools
    steps = [.15,-.12,.15,-.12,.15]
    levels = (0.,.55,1.)
    days = []
    for t, stock_return in enumerate(steps):
        factors = []
        for old in range(3):
            row=[]
            for new in range(3):
                gross = 1+levels[new]*stock_return+(1-levels[new])*.001
                row.append(str(gross*(1-.001*abs(levels[new]-levels[old]))))
            factors.append(row)
        days.append(dict(session='S'+str(t),net=factors))
    table = dict(startup=dict(new_code=2,net='0.999'),days=days)
    candidates=[]
    for tail in itertools.product(range(3),repeat=len(days)):
        codes=[2]+list(tail)
        path=selected_log_path(table,codes)
        if path['ordinary_switches']<=2:
            candidates.append((codes,path))
    brute=max(p['log_terminal'] for _,p in candidates)
    dp=daily_dp(table,2)
    need(abs(dp['best_log_terminal']-brute)<=LOG_TOL, 'DP_EQUALS_EXHAUSTIVE_TINY_ENUMERATION')
    cap=.06
    need(dp['max_log_drawdown'] > -math.log1p(-cap)+LOG_TOL,
         'TINY_FIXTURE_DRAWDOWN_CAP_MUST_BIND')
    feasible=[(c,p) for c,p in candidates if p['max_log_drawdown']<=-math.log1p(-cap)+LOG_TOL]
    warm=max(feasible,key=lambda pair:pair[1]['log_terminal'])[0]
    maximum=solve(table,2,'max_growth',dd_cap=cap,warm_codes=warm,time_limit=15.)
    need(maximum['optimal'] and abs(maximum['primal_objective']-max(p['log_terminal'] for _,p in feasible))<LOG_TOL,
         'MILP_RISK_CAP_EQUALS_EXHAUSTIVE_ENUMERATION')
    # A sufficiently demanding tiny-fixture floor is essential: the actual
    # study's always-Core floor can be slack in this deliberately small toy.
    floor=dp['best_log_terminal']
    growth_feasible=[(c,p) for c,p in candidates if p['log_terminal']>=floor-LOG_TOL]
    minimum=solve(table,2,'min_drawdown',log_growth_floor=floor,
                  warm_codes=dp['codes'],time_limit=15.)
    need(minimum['optimal'] and abs(minimum['primal_objective']-min(p['max_log_drawdown'] for _,p in growth_feasible))<LOG_TOL,
         'MILP_MATCHED_GROWTH_EQUALS_EXHAUSTIVE_ENUMERATION')
    need(minimum['primal_objective'] > min(p['max_log_drawdown'] for _,p in candidates)+LOG_TOL,
         'TINY_FIXTURE_GROWTH_FLOOR_MUST_BIND')
    altered=vector_for_codes(table,build_model(table,2,'max_growth',dd_cap=cap),warm)
    altered[0]=.5
    try:
        check_vector(build_model(table,2,'max_growth',dd_cap=cap),altered)
    except ValueError:
        pass
    else:
        raise ValueError('INFEASIBLE_FRACTIONAL_SOLUTION_NOT_REJECTED')
    return dict(status='PASSED', exhaustive_paths=len(candidates),
        checks=['DP_EXHAUSTIVE','MAX_GROWTH_DRAWDOWN_EXHAUSTIVE','MIN_DRAWDOWN_GROWTH_EXHAUSTIVE',
                'CONNECTED_FLOW','SWITCH_BUDGET','INFEASIBLE_FRACTIONAL_INCUMBENT'])
