"""Independent tiny oracle MILPs and exhaustive path checks, hosted only."""
import itertools
import math
import os
from pathlib import Path

if (os.environ.get('SENTINEL_ORACLE_HOSTED') != '1'
        or Path(__file__).resolve() != Path('/current/research/sentinel_oracle/review_synthetics.py')):
    raise ValueError('HOSTED_ORACLE_SYNTHETICS_ONLY')

import numpy as np
import highspy


def require(value, code):
    if not value:
        raise ValueError(code)


def score(table, codes):
    wealth = math.log(float(table['startup']['net']))
    peak, worst = max(0., wealth), max(0., -wealth)
    for t, day in enumerate(table['days']):
        wealth += math.log(float(day['net'][codes[t]][codes[t+1]]))
        peak = max(peak, wealth)
        worst = max(worst, peak-wealth)
    return wealth, worst, sum(a != b for a,b in zip(codes, codes[1:]))


def fixture():
    levels = (0., .55, 1.)
    days = []
    for move in (.18, -.14, .18, -.14, .18):
        values = [[str((1+levels[new]*move+(1-levels[new])*.001)
                       *(1-.001*abs(levels[new]-levels[old]))) for new in range(3)]
                  for old in range(3)]
        days.append(dict(net=values))
    return dict(startup=dict(new_code=2, net='0.999'), days=days)


def solve_tiny(table, budget, *, cap=None, floor=None):
    """A separate direct dense-row formulation, never the worker's builder."""
    require(Path(highspy.__file__).resolve().is_relative_to(Path('/solver'))
            and highspy.Highs().version() == '1.15.1' and np.__version__ == '2.4.6',
            'INDEPENDENT_PINNED_NUMERICAL_RUNTIME')
    n = len(table['days'])
    e, w, h = n*9, n*9, n*10
    b = n*11 if floor is not None else None
    size = n*11+(b is not None)
    lowers, uppers, objective = [0.]*size, [1.]*e+[1e30]*(size-e), [0.]*size
    for column in range(w, h):
        lowers[column] = -1e30
    objective[b if b is not None else w+n-1] = 1.
    start = math.log(float(table['startup']['net']))
    initial_peak = max(0., start)
    if b is not None:
        lowers[b] = initial_peak-start
    rows, lo, up = [], [], []
    def add(terms, lower=-1e30, upper=1e30):
        row = [0.]*size
        for column, value in terms:
            row[column] += value
        rows.append(row);lo.append(lower);up.append(upper)
    edge = lambda t, a, z: t*9+a*3+z
    for t in range(n):
        add([(edge(t,a,z),1.) for a,z in itertools.product(range(3), repeat=2)], 1., 1.)
        for state in range(3):
            terms = [(edge(t,state,z),1.) for z in range(3)]
            if t:
                terms.extend((edge(t-1,a,state),-1.) for a in range(3))
            target = float(state == 2) if not t else 0.
            add(terms, target, target)
        terms = [(w+t,1.)]+[(edge(t,a,z),-math.log(float(table['days'][t]['net'][a][z])))
                               for a,z in itertools.product(range(3), repeat=2)]
        if t:
            terms.append((w+t-1,-1.))
        target = start if not t else 0.
        add(terms, target, target)
        add([(h+t,1.),(w+t,-1.)], 0.)
        add([(h+t,1.)]+([(h+t-1,-1.)] if t else []), 0. if t else initial_peak)
        terms = [(h+t,1.),(w+t,-1.)]+([(b,-1.)] if b is not None else [])
        add(terms, upper=0. if b is not None else -math.log1p(-cap))
    add([(edge(t,a,z),1.) for t in range(n) for a,z in itertools.product(range(3), repeat=2)
         if a != z], upper=budget)
    if b is not None:
        add([(w+n-1,1.)], floor)
    engine = highspy.Highs()
    for key, value in dict(threads=2, random_seed=0, mip_rel_gap=1e-9, time_limit=20.,
                           output_flag=False, log_to_console=False).items():
        require(engine.setOptionValue(key, value) == highspy.HighsStatus.kOk, 'INDEPENDENT_SOLVER_OPTION')
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = size, len(rows)
    lp.col_cost_ = np.asarray(objective, dtype=np.float64)
    lp.col_lower_ = np.asarray(lowers, dtype=np.float64)
    lp.col_upper_ = np.asarray(uppers, dtype=np.float64)
    lp.row_lower_ = np.asarray(lo, dtype=np.float64)
    lp.row_upper_ = np.asarray(up, dtype=np.float64)
    lp.integrality_ = [highspy.HighsVarType.kInteger]*e+[highspy.HighsVarType.kContinuous]*(size-e)
    starts, indices, values = [0], [], []
    for row in rows:
        for column, value in enumerate(row):
            if value:
                indices.append(column);values.append(value)
        starts.append(len(indices))
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_ = np.asarray(starts, dtype=np.int32)
    lp.a_matrix_.index_ = np.asarray(indices, dtype=np.int32)
    lp.a_matrix_.value_ = np.asarray(values, dtype=np.float64)
    lp.sense_ = highspy.ObjSense.kMinimize if b is not None else highspy.ObjSense.kMaximize
    require(engine.passModel(lp) == highspy.HighsStatus.kOk, 'INDEPENDENT_TINY_MODEL_ACCEPTED')
    require(engine.run() == highspy.HighsStatus.kOk
            and engine.getModelStatus() == highspy.HighsModelStatus.kOptimal,
            'INDEPENDENT_TINY_OPTIMUM')
    info, result = engine.getInfo(), engine.getSolution()
    require(result.value_valid and math.isfinite(info.objective_function_value), 'INDEPENDENT_TINY_PRIMAL')
    selected = [2]
    for t in range(n):
        chosen = [i for i,v in enumerate(result.col_value[t*9:t*9+9]) if v > .5]
        require(len(chosen) == 1 and chosen[0]//3 == selected[-1], 'INDEPENDENT_TINY_CONNECTED_FLOW')
        selected.append(chosen[0] % 3)
    return dict(codes=selected, objective=float(info.objective_function_value),
                dual_bound=float(info.mip_dual_bound), relative_gap=float(info.mip_gap))


def run_checks(dp_callback):
    table = fixture()
    paths = []
    for tail in itertools.product(range(3), repeat=len(table['days'])):
        codes = [2]+list(tail)
        wealth, risk, changes = score(table, codes)
        if changes <= 2:
            paths.append((codes, wealth, risk))
    best = max(wealth for _,wealth,_ in paths)
    dp = dp_callback(table, 2)
    require(abs(dp['best_log_terminal']-best) <= 1e-10, 'INDEPENDENT_DP_EXHAUSTIVE_PATHS')
    cap = .065
    feasible = [(codes,wealth,risk) for codes,wealth,risk in paths if risk <= -math.log1p(-cap)+1e-10]
    require(feasible and max(wealth for _,wealth,_ in feasible) < best-1e-6,
            'INDEPENDENT_DRAWDOWN_CAP_IS_BINDING')
    capped = solve_tiny(table, 2, cap=cap)
    require(abs(capped['objective']-max(wealth for _,wealth,_ in feasible)) <= 1e-8,
            'INDEPENDENT_CAPPED_MILP_EQUALS_EXHAUSTIVE')
    growth_feasible = [(codes,wealth,risk) for codes,wealth,risk in paths if wealth >= best-1e-10]
    require(min(risk for _,_,risk in growth_feasible) > min(risk for _,_,risk in paths)+1e-6,
            'INDEPENDENT_MATCHED_GROWTH_IS_BINDING')
    matched = solve_tiny(table, 2, floor=best)
    require(abs(matched['objective']-min(risk for _,_,risk in growth_feasible)) <= 1e-8,
            'INDEPENDENT_MATCHED_MILP_EQUALS_EXHAUSTIVE')
    return dict(status='PASSED', enumerated_feasible_paths=len(paths),
                capped=capped, matched=matched,
                checks=['INDEPENDENT_DP_BRUTE_FORCE', 'BINDING_DRAWDOWN_MILP_BRUTE_FORCE',
                        'BINDING_MATCHED_GROWTH_MILP_BRUTE_FORCE'])
