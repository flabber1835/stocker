"""Exact test-only predecessor reconstruction for the Alpaca coverage changes."""
import hashlib
import json
from pathlib import Path


BASE_REVISION = '2adeda3b18e9323827e9d12e8782034c3ecc3e55'
BASE_STRATEGY = '421a1697353ced9bdb0efba82150e900265c8f1bb7e296dbb7f6423b40a6cc81'
BASE_DATA_SEMANTICS = '4e0527eb06780b744fefeadc47e2b18c2cdaacfa77ffa24946a569c5e59b0b1b'
CURRENT_STRATEGY = 'dd92db0ef465e62b3d8e18d1b70d562a611c3c4efe67528f48a87ad143ccc13e'
CURRENT_DATA_SEMANTICS = 'c9ea97a11425abc316466f6397fe03cdd881a2c2c979d8ba7eefeb751185bcb9'
CHANGED_COMPILERS = frozenset({
    'sentinel.core.window_continuity', 'sentinel.execution.reconcile',
    'sentinel.feed.operational_snapshot',
})
_FIXTURE = Path(__file__).with_name('alpaca-coverage-2adeda3-compilers.json')
_FIXTURE_SHA = '6b5a5f4849de1d08b66d4151b9ea9165be59f98aa4fc9e28a811b617c9e63271'
PAPER_OWNERS = frozenset({'cash', 'execution', 'targets'})
_PAPER_FIXTURE = Path(__file__).with_name('alpaca-coverage-2adeda3-paper.json')
_PAPER_FIXTURE_SHA = 'c76f5cee6d30e2e37cc40159afa5c84a074aa646b363dd2fd5f4505a2da622c2'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def predecessor(module, raw):
    """Undo only the exact successor to recover independently pinned Git bytes."""
    return _reverse(module, raw, path=_FIXTURE, fixture_sha=_FIXTURE_SHA,
                    kind='compiler', members=CHANGED_COMPILERS)


def paper_predecessor(module, raw):
    return _reverse(module, raw, path=_PAPER_FIXTURE, fixture_sha=_PAPER_FIXTURE_SHA,
                    kind='paper', members=PAPER_OWNERS)


def _reverse(module, raw, *, path, fixture_sha, kind, members):
    fixture = path.read_bytes()
    assert _sha(fixture) == fixture_sha
    value = json.loads(fixture)
    assert value['schema'] == f'sentinel.alpaca-coverage-{kind}-fixture/1'
    assert value['base_revision'] == BASE_REVISION
    assert set(value['files']) == members
    record = value['files'][module]
    assert _sha(raw) == record['after_sha256'], 'source is not the reviewed Alpaca successor'
    for pair in record['edits']:
        before, after = pair['before'].encode(), pair['after'].encode()
        assert before and after and before != after and raw.count(after) == 1
        raw = raw.replace(after, before, 1)
    assert _sha(raw) == record['before_sha256'], 'Git predecessor did not reconstruct exactly'
    return raw


def predecessor_reader(read):
    """Keep historical architecture checks on their original exact compiler set."""
    previous = {name: predecessor(name, read(name)) for name in CHANGED_COMPILERS}
    return lambda name: previous[name] if name in previous else read(name)
