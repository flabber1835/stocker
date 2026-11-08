"""Hosted own-origin score experiment and unchanged original Sentinel account."""
import argparse
import ast
import json
import math
import os
from pathlib import Path
import time
import types

from core_volatility_source import ARMS, need, transform, identity
from system_campaign_space import DEFAULT, digest
from full_system_core import arguments, hosted
from full_system_benchmark import save

PROFILE = 'wealth-core-v5-zero-share-fixed-2008-v1'


def qualify(arm):
    hosted()
    import system_campaign_qualify as original
    raw = Path(original.__file__).read_bytes()
    if arm == 'VOL075':
        raw = transform(raw, 'math.log1p(momentum)/vol', 'math.log1p(momentum)/vol**0.75')
    module = types.ModuleType('_research_score_qualification')
    exec(compile(raw, '<unchanged-configuration-cases-with-declared-score>', 'exec'), module.__dict__)
    result = module.qualify(DEFAULT, PROFILE)
    from stock_strategy_shared.wealth_core import signals, median5
    from stock_strategy_shared.wealth_core.feed import SecuritySeries
    from types import SimpleNamespace as DTO
    exponent = ARMS[arm]
    for momentum, volatility in ((math.expm1(.4), .1), (math.expm1(1.), .3)):
        need(signals.durable_score(momentum, volatility) == math.log1p(momentum)/volatility**exponent,
             'ACTUAL_SCALAR_SCORE')
    a = signals.durable_score(math.expm1(.4), .1)
    b = signals.durable_score(math.expm1(1.), .3)
    need((a > b) == (arm == 'CONTROL'), 'ACTUAL_ORDERING_FALSIFIER')
    from stock_strategy_shared.wealth_core.engine import SecurityBar, score_universe
    from stock_strategy_shared.wealth_core import v5
    candidates = [('L', math.expm1(.4), .1), ('H', math.expm1(1.), .3)]
    candidates += [('S'+str(i), (i+1)/1000., 50.) for i in range(98)]
    bars = [SecurityBar(sid, sid, 'SID:'+sid, [100.]*127, 100., True, '',
                        (mom, .01, vol, signals.durable_score(mom, vol))) for sid, mom, vol in candidates]
    scored = score_universe(bars, v5.research_config(PROFILE))
    expected_pool = {r[0] for r in sorted(candidates, key=lambda r: -r[1])[:25]}
    need({s.security_id for s in scored if s.in_top_decile} == expected_pool,
         'ACTUAL_RAW_MOMENTUM_LEADERSHIP_UNCHANGED')
    ranked = median5.rank(scored, median5.fresh())
    need(ranked[0].security_id == ('L' if arm == 'CONTROL' else 'H'), 'ACTUAL_MEDIAN5_ORDERING_FLIP')
    series = SecuritySeries('S', 'S', 'SID:S')
    feed = DTO(series={'S': series}, _session_index=-1)
    state = median5.fresh()
    last = None
    for index in range(130):
        close = 100. + index*.12 + (index % 3)*.013
        series.session_indices.append(index)
        series.signal_closes.append(close)
        series.raw_closes.append(close)
        series.volumes.append(10000000.)
        feed._session_index = index
        bar = DTO(security_id='S', ticker='S', session='2026-01-05', raw_close=close)
        meta = DTO(first_session='2000-01-03', category='Domestic Common Stock')
        last = median5.advance_signals(feed, [bar], {'S': meta}, state)[0]
    need(last.eligible and last.certified_signals is not None, 'ACTUAL_VECTOR_ELIGIBLE')
    momentum, recent, vol, score = last.certified_signals
    need(math.isclose(score, math.log1p(momentum)/vol**exponent, rel_tol=2e-15, abs_tol=0.),
         'ACTUAL_VECTOR_SCORE')
    result.update(experiment=identity(arm), scalar_and_vector_cases_passed=True,
                  scalar_ordering_flipped=arm == 'VOL075', original_sentinel_unchanged=True)
    return result


def run(arm, maximum):
    hosted()
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.journal import read_checkpoint
    from system_campaign_baseline import facts
    from system_campaign_acceleration import Execution
    root = Path('/out/book')
    binding = json.loads(Path('/out/source-bindings.json').read_bytes())
    need(binding['experiment'] == identity(arm) and binding['parameters'] == DEFAULT
         and binding['experiment_sha256'] == digest(identity(arm)), 'BOUND_EXPERIMENT')
    start = time.monotonic()
    save(Path('/out/canonical-qualification.json'), qualify(arm))
    qualified = time.monotonic()
    os.environ['FULL_SYSTEM_WARMUP_ONLY'] = '1'
    try:
        code = backtest.main(arguments(root))
    finally:
        os.environ.pop('FULL_SYSTEM_WARMUP_ONLY', None)
    need(code == 0, 'OWN_FEATURE_WARMUP')
    warmed = time.monotonic()
    overlay = facts(root)
    financial = time.monotonic()
    with Execution('FAST', signal_closes=1) as execution:
        code = backtest.main(arguments(root, True, maximum) + ['--repair-overlay', str(overlay)])
    save(Path('/out/acceleration-proof.json'), execution.proof())
    cp = read_checkpoint(root/'checkpoint.json.gz')
    complete = cp['completed'] == 2156 and cp['source_cursor'] == '2026-07-31'
    if maximum == 134:
        need(code == 0 and cp['completed'] == 8 and cp['source_cursor'] == '2018-01-11', 'PILOT_AXIS')
    save(Path('/out/experiment-outcome.json'), {
        'arm': arm, 'complete': complete, 'completed': cp['completed'], 'session': cp['source_cursor'],
        'qualification_seconds': qualified-start, 'warmup_seconds': warmed-qualified,
        'financial_seconds': time.monotonic()-financial, 'formation_and_measured_transitions': maximum,
        'checkpoint_sha256': cp['sha256'], 'production_contacted': False})
    need(code == 0, 'FINANCIAL_REFUSAL_PRESERVED')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('economic', 'review'), required=True)
    p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--maximum', type=int, required=True)
    a = p.parse_args()
    hosted()
    if a.mode == 'economic':
        run(a.arm, a.maximum)
    else:
        from system_campaign_readonly import review
        review(Path('/evidence/book'), Path('/out/core-review.json'))
