"""Hosted canonical timing measurement; no performance selection or scoring."""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import shutil
import time


def need(value, code):
    if not value:
        raise ValueError('REFUSED_FULL_SYSTEM_' + code)


def save(path, value):
    with path.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def wrap_call(original, label, stream, profile_at):
    """Return the exact call result, with timing-only observation around it."""
    ordinal = 0
    def timed(*args, **kwargs):
        nonlocal ordinal
        ordinal += 1
        profiler = cProfile.Profile() if ordinal == profile_at else None
        start, cpu = time.perf_counter(), time.process_time()
        try:
            if profiler is not None:
                profiler.enable()
            return original(*args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
            row = {'label': label, 'ordinal': ordinal,
                   'profiled': profiler is not None,
                   'wall_seconds': time.perf_counter()-start,
                   'cpu_seconds': time.process_time()-cpu}
            if profiler is not None:
                entries = []
                for (file, line, function), (primitive, calls, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
                    entries.append({'file': file, 'line': line, 'function': function,
                                    'primitive_calls': primitive, 'calls': calls,
                                    'own_seconds': own, 'cumulative_seconds': cumulative})
                row['profile'] = sorted(entries, key=lambda r: -r['cumulative_seconds'])[:100]
            stream.write(json.dumps(row, sort_keys=True)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
    return timed


def measure():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/fixed').is_dir()
         and str(Path(__file__).resolve()).startswith('/driver/'), 'HOSTED_ONLY')
    protocol_path = Path('/driver/full_system_protocol.json')
    protocol = json.loads(protocol_path.read_bytes())
    need(protocol['measurement_formation_transitions'] == 6
         and protocol['profile_ordinal'] == 6 and not protocol['performance_selection_started'], 'MEASUREMENT_SCOPE')
    from research.pooled_vacancy_funding import backtest, runtime
    from research.pooled_input_support.adapter import Buffer
    need(Path(backtest.__file__).resolve() == Path('/fixed/research/pooled_vacancy_funding/backtest.py'), 'CANONICAL_SOURCE')
    root = Path('/out')
    original_prepare, original_advance = Buffer.prepare, runtime.advance
    start = time.monotonic()
    try:
        with (root/'timings.jsonl').open('x', encoding='utf8') as stream:
            Buffer.prepare = wrap_call(original_prepare, 'input_prepare', stream, 6)
            runtime.advance = wrap_call(original_advance, 'canonical_advance', stream, 6)
            code = backtest.main(['--policy', protocol['canonical_policy'],
                '--bundle', '/frozen/bundle', '--archive', '/frozen/archive/corpus.zip',
                '--previous', '/frozen/references/owned55',
                '--compact', '/frozen/references/compact/champion-daily.csv',
                '--output', '/out/book', '--max-transitions', '6'])
    finally:
        Buffer.prepare, runtime.advance = original_prepare, original_advance
    save(root/'measurement.json', {'schema': 'research.full-system-timing/1',
        'canonical_exit_code': code, 'elapsed_seconds': time.monotonic()-start,
        'protocol_sha256': hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        'performance_scored': False, 'measurement_only': True})
    need(code == 0, 'CANONICAL_MEASUREMENT_REFUSED')


def review():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/evidence').is_dir(), 'HOSTED_REVIEW_ONLY')
    from research.pooled_vacancy_funding import backtest, runtime
    from research.pooled_vacancy_funding.journal import Journal, read_checkpoint
    from research.pooled_input_support import bundle
    actual, expected = Path('/evidence/book'), Path('/frozen/baseline-comparison')
    saved = read_checkpoint(actual/'checkpoint.json.gz')
    reference = read_checkpoint(expected/'checkpoint.json.gz')
    need(saved['base'] == reference['base'] and saved['completed'] == 0 and not saved['repairs'], 'EXACT_BASELINE_SOURCE_AND_INPUT')
    axis = bundle.axis()
    axis = axis[axis.index(backtest.START)-425:]
    backtest.validate_checkpoint(saved, saved['base'], axis)
    restored = runtime.restore(saved['run'], policy=saved['base']['policy'],
        input_sha256=backtest.input_hash(saved['base'], []))
    need(runtime.checkpoint(restored) == saved['run'], 'CANONICAL_ROUNDTRIP')
    count = 0
    with (actual/'formation.jsonl').open('rb') as a, (expected/'formation.jsonl').open('rb') as b:
        for raw in a:
            need(raw == b.readline(), 'EXACT_BASELINE_FORMATION_BYTES')
            need(json.loads(raw)['phase'] == 'FORMATION', 'FORMATION_ONLY')
            count += 1
    need(count == 6, 'COMPLETE_MEASUREMENT_PREFIX')
    scratch = Path('/out/journal-review'); scratch.mkdir(exist_ok=False)
    for name in saved['journals']:
        shutil.copyfile(actual/(name+'.jsonl'), scratch/(name+'.jsonl'))
    journal = Journal(scratch, resume=True)
    try:
        journal.verify(saved['journals'])
    finally:
        journal.close()
    for name, spec in saved['journals'].items():
        need((actual/(name+'.jsonl')).stat().st_size == spec['bytes'], 'ZERO_UNCOMMITTED_TAILS')
    rows = [json.loads(raw) for raw in Path('/evidence/timings.jsonl').read_text().splitlines()]
    summary = {}
    for label in ('input_prepare', 'canonical_advance'):
        values = [r for r in rows if r['label'] == label]
        need([r['ordinal'] for r in values] == list(range(1, 7))
             and [r['ordinal'] for r in values if r['profiled']] == [6], 'TIMING_AXIS')
        ordinary = [r['wall_seconds'] for r in values if not r['profiled']]
        summary[label] = {'ordinary_seconds': ordinary,
            'ordinary_mean_seconds': sum(ordinary)/len(ordinary),
            'profiled_seconds': values[-1]['wall_seconds'], 'hotspots': values[-1]['profile']}
    save(Path('/out/review.json'), {'schema': 'research.full-system-benchmark-review/1',
        'status': 'CANONICAL_MEASUREMENT_REVIEW_PASSED', 'formation_records': count,
        'measured_closes': 0, 'baseline_full_record_bytes_equal': True,
        'canonical_roundtrip': True, 'all_committed_prefixes_verified': True,
        'uncommitted_tails': 0, 'timings': summary, 'performance_scored': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args()
    review() if args.review else measure()
