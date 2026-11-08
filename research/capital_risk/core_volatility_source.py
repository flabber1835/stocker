"""DATA-only, exact private P00 score compiler. Never imports financial code."""
import ast
import hashlib
import json
from pathlib import Path

from system_campaign_space import DEFAULT, digest
from system_campaign_variants import render as p00, bind_manifest

CORE = 'shared/stock_strategy_shared/wealth_core/'
RUNTIME = 'research/pooled_vacancy_funding/runtime.py'
PINS = {
    CORE + 'signals.py': 'c0c6d41517909580af76b41217a725720144edc7d191cf7ea32dbd393bde4960',
    CORE + 'median5.py': '47a538b6bcc23fcd1f08160123b0f3e4b69e59fef252f9e849cd57838dfcd01c',
    RUNTIME: 'edee8bdead3a4c847a214cec114d1d8c70ade61019b9204e6a493f8338c6ad24',
}
SITES = {
    CORE + 'signals.py': ('math.log1p(float(momentum)) / float(vol)',
                          'math.log1p(float(momentum)) / float(vol)**0.75'),
    CORE + 'median5.py': ('np.log1p(mom)/vol', 'np.log1p(mom)/vol**0.75'),
}
ARMS = {'CONTROL': 1.0, 'VOL075': 0.75}


def need(value, code):
    if not value:
        raise ValueError('REFUSED_CORE_VOLATILITY_' + code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def transform(raw, before, after):
    """Preserve all other bytes, prove one expression and exact inverse."""
    text = raw.decode()
    pattern = ast.dump(ast.parse(before, mode='eval').body)
    need(sum(ast.dump(n) == pattern for n in ast.walk(ast.parse(text))) == 1,
         'SINGLE_AST_SITE')
    need(text.count(before) == 1, 'SINGLE_SOURCE_SITE')
    changed = text.replace(before, after)
    need(changed.count(after) == 1, 'SINGLE_REPLACEMENT')
    need(changed.replace(after, before).encode() == raw, 'EXACT_SOURCE_INVERSE')
    tree = ast.parse(changed)
    target = ast.dump(ast.parse(after, mode='eval').body)
    need(sum(ast.dump(n) == target for n in ast.walk(tree)) == 1, 'CHANGED_AST_SITE')
    return changed.encode()


def identity(arm):
    need(arm in ARMS, 'REGISTERED_ARM')
    return {'schema': 'research.core-volatility-profile/1', 'arm': arm,
            'volatility_exponent': ARMS[arm], 'p00_parameters_sha256': digest(DEFAULT),
            'score_sites': {n: list(v) for n, v in SITES.items()}, 'parent_source_pins': PINS}


def apply(baseline, arm):
    spec = identity(arm)
    for name, expected in PINS.items():
        need(sha(baseline[name]) == expected, 'EXACT_PARENT:' + name)
    if arm == 'CONTROL':
        return dict(baseline)
    out = dict(baseline)
    for name, (before, after) in SITES.items():
        out[name] = transform(out[name], before, after)
    # Runtime identity binds this lineage without extending the old P00 schema.
    text = out[RUNTIME].decode()
    before = 'identity = {**identity,'
    need(text.count(before) == 1, 'RUNTIME_IDENTITY_SITE')
    out[RUNTIME] = text.replace(before, before + ' "research_core_volatility_sha256": "' + digest(spec) + '",').encode()
    ast.parse(out[RUNTIME])
    out = bind_manifest(out)
    allowed = set(SITES) | {RUNTIME, 'sentinel/economic-implementation-v2.json', 'sentinel/economic_manifest.py'}
    need(set(out) == set(baseline) and all(out[n] == baseline[n] for n in out if n not in allowed),
         'NO_UNRELATED_SOURCE_CHANGE')
    return out


def build(source, destination, arm):
    source, destination = Path(source), Path(destination)
    need(not destination.exists() and source.resolve() != destination.resolve(), 'NEW_PRIVATE_TREE')
    files = {p.relative_to(source).as_posix(): p.read_bytes()
             for p in source.rglob('*') if p.is_file()}
    need(len(files) == 514, 'FROZEN_SOURCE_COUNT')
    baseline = p00(files, DEFAULT)
    out = apply(baseline, arm)
    for name, raw in out.items():
        if name.endswith('.py'):
            ast.parse(raw, name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {'schema': 'research.core-volatility-source/1', 'parameters': DEFAULT,
            'experiment': identity(arm), 'experiment_sha256': digest(identity(arm)),
            'profile_sha256': digest(DEFAULT), 'original_files': 514, 'files': len(out),
            'baseline_sources': {n: sha(raw) for n, raw in baseline.items()},
            'all_sources': {n: sha(raw) for n, raw in out.items()},
            'experiment_changes': {n: {'before': sha(baseline[n]), 'after': sha(raw)}
                                   for n, raw in out.items() if raw != baseline[n]}}
