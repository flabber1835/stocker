"""Explicit historical hash records for admission-matrix fixtures only.

These marker files are not historical executable source. The named fixture
adapter projects authenticated historical hashes; the production reader and
current candidate-image tests always hash actual executable bytes.
"""
import hashlib
from functools import lru_cache
import json
from pathlib import Path

from sentinel import transition_registry
from tests.support.publisher_source_proofs import baseline_catalog


@lru_cache(maxsize=1)
def _authenticated():
    known = {name: {sha} for name, sha in baseline_catalog()['files'].items()}
    profiles = transition_registry.load_profiles()
    for value in profiles.values():
        for name, record in value['files'].items():
            known.setdefault(name, set()).update((*record['before'], record['after']))
        for name, sha in value.get('additions', {}).items():
            known.setdefault(name, set()).add(sha)
    for witness in profiles['protected_cohort']['predecessor_witnesses']:
        raw = (_fixtures() / (witness['revision'][:8] + '.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == witness['manifest_sha256']
        for name, sha in json.loads(raw)['files'].items():
            known.setdefault(name, set()).add(sha)
    return known, profiles


def _fixtures():
    return Path(__file__).parents[1] / 'sentinel/fixtures/retained-source-history'


def manifest(revision):
    """Read one manifest authenticated by the immutable successor policy."""
    _known, profiles = _authenticated()
    witnesses = [item for item in profiles['protected_cohort']['predecessor_witnesses']
                 if item['revision'] == revision or item['revision'][:8] == revision]
    assert len(witnesses) == 1, 'fixture must name an authenticated historical revision'
    witness = witnesses[0]
    raw = (_fixtures() / (witness['revision'][:8] + '.json')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == witness['manifest_sha256']
    value = json.loads(raw)
    assert value['revision'] == witness['revision']
    return value


def profile(module):
    """Current registry validation of one immutable historical descriptor."""
    checker = module.__name__.removeprefix('sentinel.')
    spec = next(item for item in transition_registry.PROFILES if item.checker == checker)
    return transition_registry.load_profiles()[spec.key]


def source_allowed(module, name, previous, actual):
    checker = module.__name__.removeprefix('sentinel.')
    key = next(item.key for item in transition_registry.PROFILES if item.checker == checker)
    return transition_registry.load().source_allowed(name, previous, actual, (key,))


def additions_allowed(module, actual):
    checker = module.__name__.removeprefix('sentinel.')
    key = next(item.key for item in transition_registry.PROFILES if item.checker == checker)
    return transition_registry.load().additions_allowed(actual)[key]


def copy_registry_root(root):
    """Plain isolated profile/checker fixture, never production state."""
    names = set()
    for spec in transition_registry.PROFILES:
        names.update((spec.filename, spec.checker + '.py'))
        value = json.loads((transition_registry.ROOT / spec.filename).read_bytes())
        names.update(value.get('retained_profiles', {}))
    names.update(('core/cash_distributions.py', 'economic_migration.py'))
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((transition_registry.ROOT / name).read_bytes())
    return root


def complete_target(root):
    """The protected-cohort historical target, based on its pinned main base.

    Later owner-local repairs are current-executable tests, not inputs to this
    historical transition proof. The original seam sources remain real bytes.
    """
    _known, profiles = _authenticated()
    protected = profiles['protected_cohort']
    witness = next(item for item in protected['predecessor_witnesses']
                   if item['revision'] == protected['base_revision'])
    raw = (_fixtures() / (witness['revision'][:8] + '.json')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == witness['manifest_sha256']
    manifest = json.loads(raw)
    files = dict(manifest['files'])
    files.update({name: record['after'] for name, record in protected['files'].items()})
    files.update(protected['additions'])
    spec = next(item for item in transition_registry.PROFILES if item.key == 'protected_cohort')
    files[spec.checker + '.py'] = spec.checker_sha256
    if root.exists():
        assert source_files(root) == files
        return files
    root.mkdir()
    for name, sha in files.items():
        raw_seam = manifest.get('seam_sources', {}).get(name)
        if raw_seam is not None and hashlib.sha256(raw_seam.encode()).hexdigest() == sha:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw_seam.encode())
        else:
            write(root, name, expected=sha)
    assert source_files(root) == files
    return files


def target():
    """Latest explicitly declared historical target, without current repairs."""
    _known, profiles = _authenticated()
    actual = {}
    for value in profiles.values():
        actual.update(value.get('additions', {}))
        actual.update({name: record['after'] for name, record in value['files'].items()})
    for spec in transition_registry.PROFILES:
        if spec.key in {'autonomy', 'native_read', 'clock_sampling', 'idle_leader',
                        'opening_latency', 'protected_cohort'}:
            actual[spec.checker + '.py'] = spec.checker_sha256
    return actual


def _marker(name, sha):
    result = ('# Named historical hash fixture; complete executable source is not present.\n'
              f'# path={name}\n# sha256={sha}\n').encode()
    if name == 'paper/preparation.py' and sha == '63db97a452c0115f5248fbf45182e04b161dbed751b7f16aa458fa1ddcdc5a20':
        # Plain 11-line guard witness from Git1e447868, used only by the
        # neighboring-command-guard mutation case. It is not a module image.
        path = Path(__file__).with_name('simplification_baseline') / 'paper_preparation_guard.txt'
        guard = path.read_bytes()
        if hashlib.sha256(guard).hexdigest() != '71a611a70a84f210bda8fee9148c8d7c1b6707fce89a3d7b87db17b40e09614a':
            raise ValueError('historical command guard witness changed')
        result += b'\n# Original guard excerpt; this fixture is not executed.\n' + guard
    return result


def write(root, name, expected=None):
    known, _profiles = _authenticated()
    sha = expected if expected is not None else target().get(name, baseline_catalog()['files'].get(name))
    assert sha in known[name], 'fixture must name an authenticated historical hash'
    actual_path = transition_registry.ROOT / name
    raw = actual_path.read_bytes()
    # Real plain bytes are retained where they independently match the named
    # historical record, allowing guard-mutation falsifiers to remain concrete.
    if hashlib.sha256(raw).hexdigest() != sha:
        raw = _marker(name, sha)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def source_files(root):
    known, _profiles = _authenticated()
    files = {}
    for path in root.rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        name, raw = path.relative_to(root).as_posix(), path.read_bytes()
        files[name] = hashlib.sha256(raw).hexdigest()
        for sha in known.get(name, ()):
            if raw == _marker(name, sha):
                files[name] = sha
                break
    return files
