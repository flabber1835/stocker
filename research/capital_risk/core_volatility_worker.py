"""Hosted own-origin score experiment and unchanged original Sentinel account."""
import argparse
import ast
from contextlib import nullcontext
import json
import math
import os
from pathlib import Path
import shutil
import time
import types

from core_volatility_source import ARMS, need, transform, identity
from system_campaign_space import DEFAULT, digest
from full_system_core import arguments, hosted
from full_system_benchmark import save

PROFILE = 'wealth-core-v5-zero-share-fixed-2008-v1'


def copy_parent_book(previous, root):
    """Copy exact bytes from immutable evidence into this arm's writable book."""
    need(not root.exists() and not any(p.is_symlink() for p in previous.rglob('*')), 'EXACT_REGULAR_PARENT_BOOK')
    shutil.copytree(previous, root)
    os.chmod(root, 0o700)
    for p in root.rglob('*'):
        os.chmod(p, 0o700 if p.is_dir() else 0o600)


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


def run(arm, maximum, previous=None, aaap_model=False):
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
    observed = nullcontext()
    if previous is None:
        os.environ['FULL_SYSTEM_WARMUP_ONLY'] = '1'
        try:
            code = backtest.main(arguments(root))
        finally:
            os.environ.pop('FULL_SYSTEM_WARMUP_ONLY', None)
        need(code == 0, 'OWN_FEATURE_WARMUP')
        warmed = time.monotonic()
        overlay = facts(root)
        extra = ['--repair-overlay', str(overlay)]
        prior_completed = -126
    else:
        need(previous == Path('/previous') and not root.exists(), 'OWN_READONLY_PARENT_MOUNT')
        need(json.loads((previous/'source-bindings.json').read_bytes()) == binding, 'EXACT_OWN_SOURCE_BINDING')
        from system_campaign_readonly import review
        before = read_checkpoint(previous/'book/checkpoint.json.gz')
        review(previous/'book', Path('/out/parent-preflight.json'))
        proof = json.loads(Path('/out/parent-preflight.json').read_bytes())
        need(proof['checkpoint_sha256'] == before['sha256'] and proof['all_prefixes_verified']
             and proof['all_daily_factors_and_chains_verified'], 'OWN_CANONICAL_PARENT_PREFLIGHT')
        copy_parent_book(previous/'book', root)
        lineage = Path('/out/lineage')
        lineage.mkdir()
        shutil.copyfile(previous/'book/checkpoint.json.gz', lineage/'original-parent-checkpoint.json.gz')
        shutil.copyfile(previous/'source-bindings.json', lineage/'parent-source-bindings.json')
        shutil.copyfile(previous/'request.json', lineage/'parent-request.json')
        evidence = lineage/'parent-output-evidence'
        evidence.mkdir()
        statuses = lineage/'parent-book-status'
        statuses.mkdir()
        for item in (previous/'book').glob('*.json'):
            shutil.copyfile(item, statuses/item.name)
        for item in previous.iterdir():
            if item.name == 'book':
                continue
            target = evidence/item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copyfile(item, target)
        need(read_checkpoint(root/'checkpoint.json.gz') == before, 'EXACT_COPIED_PARENT_CHECKPOINT')
        prior_completed = before['completed']
        warmed = time.monotonic()
        from core_volatility_facts import prepare
        extra = prepare(before, Path('/out'))
        if aaap_model:
            from core_volatility_aaap import prepare as prepare_aaap, observer
            need(not extra, 'ONE_NEW_INPUT_SUCCESSOR_PER_CONTINUATION')
            extra, material = prepare_aaap(before, Path('/out'), arm)
            observed = observer(Path('/out'), before, material)
    financial = time.monotonic()
    with Execution('FAST', signal_closes=1) as execution:
        with observed:
            code = backtest.main(arguments(root, True, maximum) + extra)
    save(Path('/out/acceleration-proof.json'), execution.proof())
    cp = read_checkpoint(root/'checkpoint.json.gz')
    complete = cp['completed'] == 2156 and cp['source_cursor'] == '2026-07-31'
    if maximum == 134 and previous is None:
        need(code == 0 and cp['completed'] == 8 and cp['source_cursor'] == '2018-01-11', 'PILOT_AXIS')
    save(Path('/out/experiment-outcome.json'), {
        'arm': arm, 'complete': complete, 'completed': cp['completed'], 'session': cp['source_cursor'],
        'qualification_seconds': qualified-start, 'warmup_seconds': warmed-qualified,
        'financial_seconds': time.monotonic()-financial,
        'new_financial_transitions': cp['completed']-prior_completed, 'maximum_requested': maximum,
        'checkpoint_sha256': cp['sha256'], 'production_contacted': False})
    need(code == 0, 'FINANCIAL_REFUSAL_PRESERVED')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('economic', 'review'), required=True)
    p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--maximum', type=int, required=True)
    p.add_argument('--resume-root', type=Path)
    p.add_argument('--aaap-model', action='store_true')
    p.add_argument('--recover-prefix', action='store_true')
    a = p.parse_args()
    hosted()
    if a.recover_prefix:
        need(not a.aaap_model, 'RECOVERY_CANNOT_INSTALL_NEW_MODEL')
        from core_volatility_recovery import run as recover, review as recovery_review
        if a.mode == 'economic':
            recover(a.resume_root, a.arm, a.maximum)
        else:
            recovery_review(a.resume_root, Path('/evidence'), Path('/out'))
    elif a.mode == 'economic':
        run(a.arm, a.maximum, a.resume_root, a.aaap_model)
    else:
        from system_campaign_readonly import review
        review(Path('/evidence/book'), Path('/out/core-review.json'))
