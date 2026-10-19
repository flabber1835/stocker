"""Fresh installed identities reuse only immutable parsing of exact text."""
from __future__ import annotations

import importlib.metadata as md
from email.header import Header
import inspect
import os
import textwrap
import warnings

import pytest

from sentinel import identity as ident


@pytest.fixture(autouse=True)
def clear_pure_cache():
    ident._parse_metadata_text.cache_clear()
    yield
    ident._parse_metadata_text.cache_clear()


class TextDistribution(md.Distribution):
    def __init__(self, files):
        self.texts = files
        self.reads = []

    def read_text(self, name):
        self.reads.append(name)
        value = self.texts.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    def locate_file(self, path):
        raise NotImplementedError


def distribution(name='Demo_Package', version='1.0', **changes):
    files = {'METADATA': f'Name: {name}\nVersion: {version}\n\nDescription.\n'}
    files.update(changes)
    return TextDistribution(files)


def old_versions(names):
    values = {}
    for name in names:
        try:
            values[name] = md.version(name)
        except Exception:
            values[name] = None
    return values


def old_distributions():
    seen = {}
    for dist in md.distributions():
        try:
            name = (dist.metadata['Name'] or '').lower().replace('_', '-')
            version = dist.version or ''
        except Exception:
            continue
        if name:
            seen[name] = version if name not in seen else f'{seen[name]}|{version}'
    return [[name, seen[name]] for name in sorted(seen)]


def _compiled(function, before, after):
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = {}
    exec(compile(source.replace(before, after), '<private-metadata-falsifier>', 'exec'),
         inspect.unwrap(function).__globals__, namespace)
    return namespace[function.__name__]


def test_real_installed_records_match_original_calculations():
    pins = ident.pinned_requirements()
    assert ident.installed_versions(pins) == old_versions(pins)
    assert ident.installed_distributions() == old_distributions()


def test_whole_environment_matches_original_calculation():
    # The reference restores both original independent direct-pin lookups.
    source = textwrap.dedent(inspect.getsource(ident.environment)).replace(
        'pinned = pinned_requirements()\n    have = installed_versions(pinned)\n    drift = _pin_drift(pinned, have)',
        'drift = pin_drift()').replace('"packages": have,',
        '"packages": installed_versions(pinned_requirements()),')
    namespace = {}
    exec(compile(source, '<original-environment-calculation>', 'exec'), ident.__dict__, namespace)
    assert ident.environment() == namespace['environment']()


def test_environment_uses_one_local_snapshot_but_next_call_and_standalone_are_fresh(monkeypatch):
    calls = []
    version = ['1']
    def installed(names):
        calls.append(tuple(names))
        return {'demo': version[0]}
    monkeypatch.setattr(ident, 'pinned_requirements', lambda: {'demo': '1'})
    monkeypatch.setattr(ident, 'installed_versions', installed)
    first = ident.environment()
    assert first['packages'] == {'demo': '1'} and first['pin_drift'] == {}
    assert calls == [('demo',)]
    version[0] = '2'
    second = ident.environment()
    assert second['packages'] == {'demo': '2'}
    assert second['pin_drift'] == {'demo': {'pinned': '1', 'installed': '2'}}
    assert calls == [('demo',), ('demo',)]
    assert ident.pin_drift() == second['pin_drift']
    assert calls == [('demo',), ('demo',), ('demo',)]


def test_warm_parse_keeps_version_resolution_and_reads_fresh(monkeypatch):
    dist = distribution()
    lookups = []
    def resolve(name):
        lookups.append(name)
        return dist
    monkeypatch.setattr(md, 'distribution', resolve)
    for _ in range(5):
        assert ident.installed_versions(['demo']) == {'demo': '1.0'}
    assert lookups == ['demo']*5 and dist.reads == ['METADATA']*5
    assert ident._parse_metadata_text.cache_info().misses == 1
    assert ident._parse_metadata_text.cache_info().hits == 4
    result = ident._parse_metadata_text(dist.texts['METADATA'])
    assert type(result) is tuple and result == ('Demo_Package', '1.0')
    with pytest.raises(TypeError):
        result[0] = 'forged'


@pytest.mark.parametrize('files,reads', [
    ({'METADATA': 'Name: demo\nVersion: 1\n'}, ['METADATA']),
    ({'PKG-INFO': 'Name: demo\nVersion: 1\n'}, ['METADATA', 'PKG-INFO']),
    ({'METADATA': '', 'PKG-INFO': 'Name: demo\nVersion: 1\n'}, ['METADATA', 'PKG-INFO']),
    ({'': 'Name: demo\nVersion: 1\n'}, ['METADATA', 'PKG-INFO', '']),
])
def test_every_metadata_fallback_is_read_fresh(files, reads):
    dist = TextDistribution(files)
    for _ in range(3):
        assert ident._distribution_headers(dist) == ('demo', '1')
    assert dist.reads == reads*3


@pytest.mark.parametrize('text', [
    'nAmE: First_Name\nvErSiOn: 1\n',
    'Name: first\nName: second\nVersion: 1\nVersion: 2\n',
    'Name: first\n        continuation\nVersion: 1\n        continued\n',
    'Name:\nVersion:\n', 'Version: 1\n', 'Name: demo\n', '',
])
def test_header_semantics_match_standard_parser_and_original_apis(text, monkeypatch):
    dist = TextDistribution({'METADATA': text, '': ''})
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        assert ident.installed_versions(['demo']) == old_versions(['demo'])
        assert ident.installed_distributions() == old_distributions()


@pytest.mark.parametrize('text', ['Name: demo\n', 'Version: 1\n', ''])
def test_missing_headers_preserve_warning_as_error_behavior(text, monkeypatch):
    dist = TextDistribution({'METADATA': text, '': ''})
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        assert ident.installed_versions(['demo']) == old_versions(['demo'])
        assert ident.installed_distributions() == old_distributions()


def test_missing_or_unreadable_metadata_and_distribution_errors_match(monkeypatch):
    missing = TextDistribution({})
    failed = TextDistribution({'METADATA': OSError('fixture metadata refused')})
    def resolve(name):
        if name == 'absent':
            raise md.PackageNotFoundError(name)
        return {'missing': missing, 'failed': failed}[name]
    monkeypatch.setattr(md, 'distribution', resolve)
    monkeypatch.setattr(md, 'distributions', lambda: iter([missing, failed]))
    assert ident.installed_versions(['absent', 'missing', 'failed']) == old_versions(['absent', 'missing', 'failed'])
    assert ident.installed_distributions() == old_distributions() == []
    assert ident._parse_metadata_text(None) == (None, None)


def test_parser_exceptions_are_not_memoized(monkeypatch):
    calls = []
    def refused(text):
        calls.append(text)
        raise ValueError('fixture parse refusal')
    monkeypatch.setattr(ident, '_metadata_fields', refused)
    for _ in range(2):
        with pytest.raises(ValueError, match='parse refusal'):
            ident._parse_metadata_text('Name: demo\nVersion: 1\n')
    assert len(calls) == 2 and ident._parse_metadata_text.cache_info().currsize == 0


def test_enumeration_is_fresh_and_duplicate_order_is_preserved(monkeypatch):
    rows = [distribution('Zed', '1'), distribution('Demo_Name', '2'), distribution('demo-name', '1')]
    enumerations = []
    def discover():
        enumerations.append(1)
        return iter(rows)
    monkeypatch.setattr(md, 'distributions', discover)
    assert ident.installed_distributions() == [['demo-name', '2|1'], ['zed', '1']]
    rows.append(distribution('new', '3'))
    assert ident.installed_distributions() == old_distributions()
    rows.pop(1)
    assert ident.installed_distributions() == [['demo-name', '1'], ['new', '3'], ['zed', '1']]
    assert len(enumerations) == 4


def test_same_size_restored_mtime_edit_is_visible_and_lookup_can_move(tmp_path, monkeypatch):
    first, second = tmp_path/'first.dist-info', tmp_path/'second.dist-info'
    first.mkdir(); second.mkdir()
    target = first/'METADATA'
    target.write_text('Name: demo\nVersion: 1\n')
    (second/'METADATA').write_text('Name: demo\nVersion: 3\n')
    selected = [first]
    monkeypatch.setattr(md, 'distribution', lambda _: md.Distribution.at(selected[0]))
    monkeypatch.setattr(md, 'distributions', lambda: (
        md.Distribution.at(path) for path in sorted(tmp_path.glob('*.dist-info'))))
    monkeypatch.setattr(ident, 'pinned_requirements', lambda: {'demo': '1'})
    assert ident.installed_versions(['demo']) == {'demo': '1'}
    original = ident.rehearsal_identity()
    before = target.stat()
    target.write_text('Name: demo\nVersion: 2\n')
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert target.stat().st_size == before.st_size and target.stat().st_mtime_ns == before.st_mtime_ns
    assert ident.installed_versions(['demo']) == {'demo': '2'}
    changed = ident.rehearsal_identity()
    assert changed['identity_hash'] != original['identity_hash']
    assert changed['environment']['pin_drift'] == {'demo': {'pinned': '1', 'installed': '2'}}
    selected[0] = second
    assert ident.installed_versions(['demo']) == {'demo': '3'}


@pytest.mark.parametrize('override', ['metadata', 'version'])
def test_custom_distribution_overrides_keep_original_access(override, monkeypatch):
    class Custom(TextDistribution):
        pass
    state = ['original']
    if override == 'metadata':
        Custom.metadata = property(lambda self: {'Name': 'custom', 'Version': state[0]})
    else:
        Custom.version = property(lambda self: state[0])
    dist = Custom({'METADATA': 'Name: custom\nVersion: original\n'})
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    assert ident.installed_versions(['custom']) == old_versions(['custom']) == {'custom': 'original'}
    state[0] = 'changed'
    assert ident.installed_versions(['custom']) == {'custom': 'changed'}
    assert ident.installed_distributions() == old_distributions() == [['custom', 'changed']]
    assert ident._parse_metadata_text.cache_info().currsize == 0


def test_custom_getattribute_keeps_original_effective_version_access(monkeypatch):
    class Dynamic(TextDistribution):
        def __getattribute__(self, name):
            if name == 'version':
                return self.selected_version
            return super().__getattribute__(name)
    dist = Dynamic({'METADATA': 'Name: custom\nVersion: disk-value\n'})
    dist.selected_version = 'first'
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    assert ident.installed_versions(['custom']) == old_versions(['custom']) == {'custom': 'first'}
    dist.selected_version = 'second'
    assert ident.installed_versions(['custom']) == {'custom': 'second'}
    assert ident.installed_distributions() == old_distributions() == [['custom', 'second']]
    assert ident._parse_metadata_text.cache_info().currsize == 0


def test_custom_getattr_keeps_original_property_failure_fallback(monkeypatch):
    class Dynamic(TextDistribution):
        def __getattr__(self, name):
            if name == 'metadata':
                return {'Name': 'custom', 'Version': self.selected_version}
            raise AttributeError(name)
    dist = Dynamic({'METADATA': AttributeError('fixture parser lookup')})
    dist.selected_version = 'first'
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    assert ident.installed_versions(['custom']) == old_versions(['custom']) == {'custom': 'first'}
    dist.selected_version = 'second'
    assert ident.installed_distributions() == old_distributions() == [['custom', 'second']]
    assert ident._parse_metadata_text.cache_info().currsize == 0


@pytest.mark.parametrize('text', [[], {}, b'Name: demo\nVersion: 1\n'])
def test_unusual_metadata_input_retains_original_failure_without_hashing(text, monkeypatch):
    dist = TextDistribution({'METADATA': text, '': text})
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    assert ident.installed_versions(['demo']) == old_versions(['demo'])
    assert ident.installed_distributions() == old_distributions()
    assert ident._parse_metadata_text.cache_info().misses == 0


def test_unhashable_text_subclass_parses_without_becoming_a_cache_key(monkeypatch):
    class UnhashableText(str):
        __hash__ = None
    dist = TextDistribution({'METADATA': UnhashableText('Name: demo\nVersion: 1\n')})
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    assert ident.installed_versions(['demo']) == old_versions(['demo']) == {'demo': '1'}
    assert ident.installed_distributions() == old_distributions() == [['demo', '1']]
    assert ident._parse_metadata_text.cache_info().currsize == 0


def test_metadata_warmth_keeps_source_lock_and_artifact_reads_fresh(tmp_path, monkeypatch):
    package = tmp_path/'package'
    package.mkdir()
    source = package/'code.py'
    source.write_text('value=1\n')
    lock = tmp_path/'requirements.lock'
    lock.write_text('lock-one\n')
    monkeypatch.setattr(ident, '_imported_package_root', lambda _: package)
    monkeypatch.setattr(ident, '_IMAGE_REQ_DIR', tmp_path)
    first = ident.rehearsal_identity()
    source.write_text('value=2\n')
    lock.write_text('lock-two\n')
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'f'*40)
    second = ident.rehearsal_identity()
    assert second['identity_hash'] != first['identity_hash']
    assert second['environment']['sentinel_source']['hash'] != first['environment']['sentinel_source']['hash']
    assert second['environment']['image_lock_sha256'] != first['environment']['image_lock_sha256']
    assert second['deployment_artifacts']['git_commit'] == 'f'*40


def test_parse_cache_is_bounded_to_128_immutable_field_pairs():
    for index in range(150):
        assert ident._parse_metadata_text(f'Name: demo\nVersion: {index}\n') == ('demo', str(index))
    info = ident._parse_metadata_text.cache_info()
    assert info.maxsize == info.currsize == 128


@pytest.mark.parametrize('field', ['Name', 'Version'])
def test_mutable_standard_header_is_never_memoized(field, monkeypatch):
    text = ('Name: \udcff\nVersion: 1\n' if field == 'Name'
            else 'Name: demo\nVersion: \udcff\n')
    dist = TextDistribution({'METADATA': text})
    assert isinstance(dist.metadata[field], Header)
    monkeypatch.setattr(md, 'distribution', lambda _: dist)
    monkeypatch.setattr(md, 'distributions', lambda: iter([dist]))
    first = ident.installed_versions(['demo'])['demo']
    if field == 'Version':
        assert isinstance(first, Header)
        first.append('caller mutation')
        second = ident.installed_versions(['demo'])['demo']
        assert isinstance(second, Header) and second is not first
        assert str(second) == str(md.version('demo'))
    assert ident.installed_distributions() == old_distributions()
    assert ident._parse_metadata_text.cache_info().currsize == 0


def test_mutable_header_falsifier_detects_removed_result_guard(monkeypatch):
    monkeypatch.setattr(ident, '_parse_metadata_text', _compiled(ident._parse_metadata_text,
        'if any(value is not None and type(value) is not str for value in fields):',
        'if False:'))
    with pytest.raises(AssertionError):
        test_mutable_standard_header_is_never_memoized('Version', monkeypatch)


def test_fresh_read_falsifier_detects_retained_file_contents(tmp_path, monkeypatch):
    original = ident._distribution_headers
    retained = {}
    def stale(dist):
        name = str(dist._path)
        if name not in retained:
            retained[name] = original(dist)
        return retained[name]
    monkeypatch.setattr(ident, '_distribution_headers', stale)
    with pytest.raises(AssertionError):
        test_same_size_restored_mtime_edit_is_visible_and_lookup_can_move(tmp_path, monkeypatch)


def test_duplicate_falsifier_detects_collapsing_multiple_installs(monkeypatch):
    monkeypatch.setattr(ident, 'installed_distributions', _compiled(ident.installed_distributions,
        'else f"{seen[name]}|{version}"', 'else version'))
    with pytest.raises(AssertionError):
        test_enumeration_is_fresh_and_duplicate_order_is_preserved(monkeypatch)
