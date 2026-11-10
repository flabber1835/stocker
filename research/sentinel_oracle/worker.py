"""Hosted-only hindsight exposure benchmark over the immutable original Core."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import sys


def need(value, code):
    if not value:
        raise ValueError(code)


def hosted():
    need(os.environ.get('SENTINEL_ORACLE_HOSTED') == '1'
         and Path(__file__).resolve() == Path('/current/research/sentinel_oracle/worker.py'),
         'HOSTED_SENTINEL_ORACLE_WORKER_ONLY')
    forbidden = ('GH_TOKEN','GITHUB_TOKEN','CAPITAL_RISK_RESEARCH_KEY_20261027',
        'ALPACA_API_KEY','ALPACA_SECRET_KEY','APCA_API_KEY_ID','APCA_API_SECRET_KEY',
        'DATABASE_URL','PGPASSWORD','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY')
    need(not any(os.environ.get(name) for name in forbidden), 'NO_FINANCIAL_CREDENTIALS')
    route = Path('/proc/net/route')
    need(route.is_file() and not any(line.split()[0] != 'lo' for line in
        route.read_text().splitlines()[1:] if line.split()), 'OFFLINE_ORACLE_CONTAINER_ONLY')


hosted()
from data import load_source, encoded, digest, file_sha
import account
import optimizer
from attribution import build_attribution


def save(path, value):
    path.write_bytes(encoded(value)+b'\n')


def failure_required(callback, label):
    try:
        callback()
    except (ValueError, KeyError, TypeError, AssertionError):
        return
    raise ValueError('UNDETECTED_ORACLE_FALSIFIER:'+label)


def compare_baseline(source, replay):
    need(len(replay['rows']) == len(source['rows']), 'COMPLETE_BASELINE_ROWS')
    for original, actual in zip(source['rows'], replay['rows']):
        e = original['economics']
        need(actual['session'] == original['session'] and Decimal(actual['nav']) == Decimal(e['strategy_nav'])
             and Decimal(actual['net_factor']) == Decimal(e['net_factor'])
             and Decimal(actual['gross_factor']) == Decimal(e['gross_factor'])
             and Decimal(actual['transaction_cost_factor']) == Decimal(e['transaction_cost_factor']),
             'EVERY_BASELINE_NAV_FACTOR_COST:'+original['session'])


def account_falsifiers(source, table, codes, baseline):
    """Actual canonical calls refuse forged factors; source timing is not a convention."""
    fixed = deepcopy(table)
    fixed['startup']['net'] = str(Decimal(fixed['startup']['net'])+Decimal('0.0001'))
    failure_required(lambda: account.replay(source,fixed,codes), 'FORMED_ENTRY_ALTERED')
    first_switch = next(t for t,(a,b) in enumerate(zip(codes,codes[1:])) if a != b)
    old,new = codes[first_switch:first_switch+2]
    fee_free = deepcopy(table)
    day = fee_free['days'][first_switch]
    day['net'][old][new] = str(Decimal(day['net'][old][new])/Decimal(day['cost'][old][new]))
    day['cost'][old][new] = '1'
    failure_required(lambda: account.replay(source,fee_free,codes), 'REMOVED_ORDINARY_ALLOCATION_FEE')
    wrong_gap = deepcopy(table)
    day = wrong_gap['days'][first_switch]
    # Change the old-exposure ownership edge while retaining the chosen new target.
    need(day['net'][old][new] != day['net'][new][new], 'SOURCE_GAP_OWNERSHIP_CANARY_NONVACUOUS')
    day['net'][old][new] = day['net'][new][new]
    failure_required(lambda: account.replay(source,wrong_gap,codes), 'WRONG_OLD_EXPOSURE_OVERNIGHT_EDGE')
    shifted = [2]+codes[:-1]
    shifted_path = account.replay(source,table,shifted)
    failure_required(lambda: compare_baseline(source,shifted_path), 'ONE_SESSION_TARGET_SHIFT')
    need(baseline['rows'][-1]['last_unexecuted_intent']
         and len(codes) == len(source['rows'])-1, 'FINAL_CLOSE_HAS_NO_INVENTED_FUTURE_FILL')
    return dict(status='PASSED', checks=['FORMED_ENTRY_ALTERED','REMOVED_ORDINARY_ALLOCATION_FEE',
        'WRONG_OLD_EXPOSURE_OVERNIGHT_EDGE','ONE_SESSION_TARGET_SHIFT','FINAL_UNEXECUTED_INTENT'])


def feasible_growth_result(dp, cap):
    return dict(schema=optimizer.SCHEMA, method='DP_UPPER_BOUND_ATTAINED_WITHIN_DRAWDOWN_CAP',
        hindsight_only=True, optimal=True, budget=dp['budget'], dd_cap=cap,
        codes=list(dp['codes']), used_switches=dp['used_switches'],
        best_log_terminal=dp['best_log_terminal'], primal_objective=dp['best_log_terminal'],
        dual_bound=dp['best_log_terminal'], relative_gap=0.,
        max_log_drawdown=dp['max_log_drawdown'], log_terminal=dp['best_log_terminal'],
        certificate='UNCONSTRAINED_SAME_BUDGET_BOUND_IS_ATTAINED_BY_A_RISK_FEASIBLE_PATH',
        numerical_log_tolerance=optimizer.LOG_TOL)


def optimize_growth(source, table, cap, dp, references, name, out):
    if dp['max_log_drawdown'] <= -math.log1p(-cap)+optimizer.LOG_TOL:
        return feasible_growth_result(dp,cap)
    feasible = [value for value in references.values()
                if float(value['metrics']['maximum_drawdown_fraction']) <= cap+1e-8
                and value['metrics']['ordinary_switches'] <= source['ordinary_switches']]
    warm = max(feasible,key=lambda value:value['metrics']['total_log_growth'])['codes'] if feasible else None
    return optimizer.solve(table,source['ordinary_switches'],'max_growth',dd_cap=cap,
        warm_codes=warm,proof_path=out/('optimization-'+name+'.json'))


def main():
    parser=argparse.ArgumentParser()
    for name in ('book','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    hosted()
    need(args.book == Path('/p00/book') and args.out == Path('/out/worker'), 'EXACT_WORKER_MOUNTS')
    need(not args.out.exists(), 'NEW_ORACLE_OUTPUT_ONLY')
    args.out.mkdir(parents=True)
    source=load_source(args.book)
    table=account.build_factor_table(source)
    save(args.out/'factor-table.json',table)
    print('ORACLE_SOURCE_AND_ALL_CANONICAL_EDGES_CALIBRATED',flush=True)
    count=len(source['baseline_codes'])
    reference_codes=dict(baseline=list(source['baseline_codes']), always_core=[2]*count,
        constant55=[2]+[1]*(count-1), defensive_after_initial=[2]+[0]*(count-1))
    references={name:account.replay(source,table,codes) for name,codes in reference_codes.items()}
    compare_baseline(source,references['baseline'])
    account_checks=account_falsifiers(source,table,reference_codes['baseline'],references['baseline'])
    fixture_checks=optimizer.fixture_checks()
    dp=optimizer.daily_dp(table,source['ordinary_switches'])
    unconstrained=account.replay(source,table,dp['codes'])
    need(abs(unconstrained['metrics']['total_log_growth']-dp['best_log_terminal']) <= 1e-8,
         'DIRECT_CANONICAL_PATH_ATTAINS_DP_BOUND')
    cap=float(references['baseline']['metrics']['maximum_drawdown_fraction'])
    print('ORACLE_DP_BOUND_COMPLETE',flush=True)
    primary=optimize_growth(source,table,cap,dp,references,'primary',args.out)
    half=optimize_growth(source,table,cap/2,dp,references,'half_drawdown',args.out)
    replayed=dict(references)
    replayed['daily_upper']=unconstrained
    for name,result in (('primary',primary),('half_drawdown',half)):
        replayed[name]=account.replay(source,table,result['codes'])
    floor=references['always_core']['metrics']['total_log_growth']
    warm_candidates=[(name,value) for name,value in replayed.items()
                     if value['metrics']['total_log_growth'] >= floor-1e-8
                     and value['metrics']['ordinary_switches'] <= source['ordinary_switches']]
    warm_name,warm_value=min(warm_candidates,key=lambda item:(
        float(item[1]['metrics']['maximum_drawdown_fraction']),
        -item[1]['metrics']['total_log_growth'],item[0]))
    matched=optimizer.solve(table,source['ordinary_switches'],'min_drawdown',log_growth_floor=floor,
        warm_codes=warm_value['codes'],proof_path=args.out/'optimization-matched_growth.json')
    optimization=dict(daily_upper=dp,primary=primary,half_drawdown=half,matched_growth=matched)
    replayed['matched_growth']=account.replay(source,table,matched['codes'])
    for name in optimization:
        need(replayed[name]['metrics']['ordinary_switches'] <= source['ordinary_switches'],
             'ALL_HINDSIGHT_PATHS_SHARE_CHANGE_BUDGET')
    for name,budget in (('primary',cap),('half_drawdown',cap/2)):
        need(float(replayed[name]['metrics']['maximum_drawdown_fraction']) <= budget+2e-6,
             'REPLAYED_HINDSIGHT_DRAWDOWN_CAP:'+name)
    need(replayed['matched_growth']['metrics']['total_log_growth'] >= floor-2e-6,
         'REPLAYED_MATCHED_GROWTH_FLOOR')
    paths={name:dict(codes=value['codes'],replay=value) for name,value in replayed.items()}
    attribution={name:build_attribution(source,table,reference_codes['baseline'],result['codes'])
                 for name,result in optimization.items()}
    report=dict(schema='research.sentinel-hindsight-oracle/1',status='SENTINEL_ORACLE_DIAGNOSTIC_COMPLETE',
        source_identity=source['identity'],account_domain='ORIGINAL_SCALAR_RESEARCH_WITH_FORMED_ENTRY',
        hindsight_only=True,training_labels='HINDSIGHT_DIAGNOSTIC_ONLY_NOT_CAUSAL_TRAINING_LABELS',
        calibration=table['proof'],budget=source['ordinary_switches'],
        factor_table_file='factor-table.json',factor_table_sha256=file_sha(args.out/'factor-table.json'),
        raw_core_reference=account.raw_core_reference(source),paths=paths,optimization=optimization,
        warm_start_selection=dict(matched_growth=warm_name),
        attribution=attribution,proofs=dict(account=account_checks,optimizer=fixture_checks),
        worker_source_sha256=file_sha(Path(__file__)),new_Core_steps=0,new_Sentinel_steps=0,
        limitations=['FULL_HISTORY_FUTURE_INFORMATION','ORIGINAL_SCALAR_RESEARCH_ACCOUNT',
            'NOT_PERSISTENT_WHOLE_SHARE_EXECUTION','NOT_A_UNIQUE_CORRECT_EXPOSURE',
            'NO_TRAINING_OR_PREDICTABILITY_CLAIM','TIMEOUT_IS_NOT_AN_OPTIMUM',
            'CLOSING_NOT_INTRADAY_DRAWDOWN','NO_PRODUCTION_POLICY_CHANGE'])
    save(args.out/'report.json',report)
    print('SENTINEL_ORACLE_DIAGNOSTIC_COMPLETE',flush=True)


if __name__ == '__main__':
    main()
