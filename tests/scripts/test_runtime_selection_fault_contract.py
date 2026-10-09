"""Read-only runtime reports and private atomic selector faults.

Docker/Git/Compose replies are synthetic. No image, financial database,
certificate, real runtime selector or production service is changed.
"""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
SOURCE = ROOT / 'scripts/sentinel_runtime_selection.py'
spec = importlib.util.spec_from_file_location('runtime_selection_fault_contract', SOURCE)
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)
SHA = '1' * 40
ID = 'sha256:' + '2' * 64
REF = 'ghcr.io/example/sentinel@' + ID


def reply(value='', code=0):
    return subprocess.CompletedProcess([], code, value, '')


def image():
    return {'Id': ID, 'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}


def test_host_runner_forwards_narrowed_environment_and_root(monkeypatch, tmp_path):
    seen = []
    environment = {'REVIEWED': '1'}
    monkeypatch.setattr(selection, 'ROOT', tmp_path)
    monkeypatch.setattr(selection, 'run_host_command',
        lambda argv, **kwargs: seen.append((argv, kwargs)) or reply('captured'))
    assert selection._run(['read', 'only'], env=environment).stdout == 'captured'
    assert selection._run(['default']).returncode == 0
    assert seen == [(['read', 'only'], {'cwd': tmp_path, 'env': environment}),
                    (['default'], {'cwd': tmp_path, 'env': None})]


def test_git_result_and_fetch_failure_remain_typed(monkeypatch):
    seen = []
    monkeypatch.setattr(selection, '_run',
        lambda argv: seen.append(argv) or reply('  ' + SHA + '\n'))
    assert selection._git('rev-parse', 'HEAD') == SHA
    selection._refresh_origin_main()
    assert seen == [['git', 'rev-parse', 'HEAD'], ['git', 'fetch', '--quiet', 'origin', 'main']]
    monkeypatch.setattr(selection, '_run', lambda argv: reply(code=128))
    with pytest.raises(selection.RuntimeSelectionRefused, match='git rev-parse HEAD failed'):
        selection._git('rev-parse', 'HEAD')
    with pytest.raises(selection.RuntimeSelectionRefused, match='refresh origin/main'):
        selection._refresh_origin_main()


def test_literal_environment_uses_canonical_refusal(monkeypatch, tmp_path):
    path = tmp_path / 'private.env'
    path.write_text('SENTINEL_RUNTIME_IMAGE_REF=' + ID + '\n', encoding='utf-8')
    assert selection._load_dotenv_literal(path)['SENTINEL_RUNTIME_IMAGE_REF'] == ID
    def refused(*args, **kwargs):
        raise selection.sentinel_env.EnvRefused('invalid literal fixture')
    monkeypatch.setattr(selection.sentinel_env, 'load', refused)
    with pytest.raises(selection.RuntimeSelectionRefused, match='invalid literal fixture'):
        selection._load_dotenv_literal(path)


@pytest.mark.parametrize('value,valid', [
    (ID, True), (REF, True), ('sha256:' + 'A' * 64, False),
    ('sha256:' + '2' * 63, False), ('sentinel:latest', False),
    ('other.invalid/image@' + ID, False), (REF + '\nextra', False), ('', False),
])
def test_only_exact_immutable_runtime_references_are_selectors(value, valid):
    assert selection._valid_reference(value) is valid


@pytest.mark.parametrize('reference', [ID, REF])
def test_pointer_roundtrip_is_one_exact_assignment(tmp_path, reference):
    path = tmp_path / 'selector.env'
    assert selection._pointer_digest(path) is None
    path.write_text('SENTINEL_RUNTIME_IMAGE_REF=' + reference + '\n', encoding='ascii')
    assert selection._pointer_digest(path) == reference


@pytest.mark.parametrize('content', ['', 'OTHER=' + ID,
    'SENTINEL_RUNTIME_IMAGE_REF=' + ID + '\nSECOND=1\n',
    'SENTINEL_RUNTIME_IMAGE_REF=latest\n',
    'SENTINEL_RUNTIME_IMAGE_REF=sha256:broken\n', 'snowman\N{SNOWMAN}'])
def test_pointer_cannot_accept_extra_lines_mutable_refs_or_unicode(tmp_path, content):
    path = tmp_path / 'selector.env'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._pointer_digest(path)


def test_pointer_read_failure_is_distinct_from_absence(monkeypatch, tmp_path):
    path = tmp_path / 'selector.env'
    path.write_text('existing')
    original = Path.read_text
    def fail(candidate, *args, **kwargs):
        if candidate == path:
            raise OSError('injected unreadable pointer')
        return original(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', fail)
    with pytest.raises(selection.RuntimeSelectionRefused, match='unreadable'):
        selection._pointer_digest(path)


@pytest.mark.parametrize('pointer', [None, REF])
def test_environment_precedence_preserves_literal_then_process_then_pointer(monkeypatch, pointer):
    monkeypatch.setattr(selection, '_load_dotenv_literal', lambda: {'FROM_FILE': 'literal'})
    merged = {'FROM_FILE': 'process', 'SENTINEL_RUNTIME_IMAGE_REF': ID}
    def merge(values, environment):
        assert values == {'FROM_FILE': 'literal'} and environment is os.environ
        return dict(merged)
    monkeypatch.setattr(selection.sentinel_env, 'merge', merge)
    monkeypatch.setattr(selection, '_pointer_digest', lambda: pointer)
    result = selection._merged_environment()
    assert result == dict(merged, SENTINEL_RUNTIME_IMAGE_REF=pointer or ID)
    def refused(*args):
        raise selection.sentinel_env.EnvRefused('invalid inherited environment')
    monkeypatch.setattr(selection.sentinel_env, 'merge', refused)
    with pytest.raises(selection.RuntimeSelectionRefused, match='invalid inherited environment'):
        selection._merged_environment()


@pytest.mark.parametrize('fault,expected', [
    ('none', None), ('head', 'exact commit'), ('branch', 'branch main'),
    ('dirty', 'clean worktree'), ('origin', 'freshly fetched'),
])
def test_clean_main_identity_refuses_stale_or_modified_source(monkeypatch, fault, expected):
    values = {('rev-parse', 'HEAD'): SHA,
        ('symbolic-ref', '--quiet', '--short', 'HEAD'): 'main',
        ('status', '--porcelain=v1', '--untracked-files=all'): '',
        ('rev-parse', 'origin/main'): SHA}
    key = {'head': ('rev-parse', 'HEAD'),
        'branch': ('symbolic-ref', '--quiet', '--short', 'HEAD'),
        'dirty': ('status', '--porcelain=v1', '--untracked-files=all'),
        'origin': ('rev-parse', 'origin/main')}.get(fault)
    if key:
        values[key] = {'head': 'not-sha', 'branch': 'feature', 'dirty': ' M source.py',
                       'origin': '3' * 40}[fault]
    monkeypatch.setattr(selection, '_git', lambda *args: values[args])
    if expected:
        with pytest.raises(selection.RuntimeSelectionRefused, match=expected):
            selection._clean_main_head()
    else:
        assert selection._clean_main_head() == SHA


@pytest.mark.parametrize('stdout', ['{', 'null', '{}', '[]', '[null]', '[{},{}]'])
def test_docker_inspection_requires_one_exact_image(monkeypatch, stdout):
    monkeypatch.setattr(selection, '_run', lambda argv: reply(stdout))
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._inspect(REF)


def test_docker_inspection_failure_never_claims_an_image(monkeypatch):
    monkeypatch.setattr(selection, '_run', lambda argv: reply(code=1))
    with pytest.raises(selection.RuntimeSelectionRefused, match='not locally inspectable'):
        selection._inspect(REF)


@pytest.mark.parametrize('field,value', [
    ('Id', None), ('Id', 'sha256:broken'), ('Id', True),
    ('Config', None), ('Config', []), ('Config', {'Labels': None}),
    ('Config', {'Labels': []}), ('Config', {'Labels': {}}),
    ('Config', {'Labels': {'org.opencontainers.image.revision': int(SHA)}}),
    ('Config', {'Labels': {'org.opencontainers.image.revision': 'A' * 40}}),
])
def test_docker_identity_fields_retain_json_types(monkeypatch, field, value):
    value_image = image()
    value_image[field] = value
    monkeypatch.setattr(selection, '_run', lambda argv: reply(json.dumps([value_image])))
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._inspect(REF)


@pytest.mark.parametrize('suffix', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_docker_reply_refuses_nonfinite_json_even_outside_identity(monkeypatch, suffix):
    raw = json.dumps([image()])[:-2] + ',"Unrelated":' + suffix + '}]'
    monkeypatch.setattr(selection, '_run', lambda argv: reply(raw))
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._inspect(REF)


def test_duplicate_docker_revision_cannot_overwrite_a_source_identity(monkeypatch):
    raw = '[{"Id":"' + ID + '","Config":{"Labels":{' + \
        '"org.opencontainers.image.revision":"' + '3' * 40 + '",' + \
        '"org.opencontainers.image.revision":"' + SHA + '"}}}]'
    monkeypatch.setattr(selection, '_run', lambda argv: reply(raw))
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._inspect(REF)


def test_valid_docker_reply_preserves_exact_source_without_promotion(monkeypatch):
    seen = []
    payload = image()
    payload['Finite'] = 1.25
    monkeypatch.setattr(selection, '_run',
        lambda argv: seen.append(argv) or reply(json.dumps([payload])))
    assert selection._inspect(REF) == (ID, SHA)
    assert seen == [['docker', 'image', 'inspect', REF]]


@pytest.mark.parametrize('raw', [b'\xff', None, 17])
def test_host_reply_invalid_encoding_or_type_is_a_typed_refusal(raw):
    with pytest.raises(selection.RuntimeSelectionRefused, match='invalid JSON'):
        selection._json_value(raw, label='fixture host reply')


def test_host_reply_utf8_bytes_and_finite_float_preserve_values():
    assert selection._json_value(b'{"value":1.25}', label='fixture host reply') == {'value': 1.25}


@pytest.mark.parametrize('stage,stdout,code', [
    ('explain', '', 2), ('explain', '"unterminated', 0),
    ('compose', '', 1), ('compose', '{', 0), ('compose', 'null', 0),
    ('compose', '{"services":[]}', 0), ('compose', '{}', 0),
    ('compose', '{"services":{"sentinel":{"image":null}}}', 0),
    ('compose', '{"services":{"sentinel":{"image":17}}}', 0),
    ('compose', '{"services":{"sentinel":{"image":" "}}}', 0),
])
def test_compose_refusal_keeps_configuration_errors_distinct(monkeypatch, stage, stdout, code):
    calls = []
    env = {'NARROWED': '1'}
    def run(argv, *, env):
        calls.append(argv)
        assert env == {'NARROWED': '1'}
        if len(calls) == 1:
            return reply(stdout, code) if stage == 'explain' else reply('-f fixture.yml')
        return reply(stdout, code)
    monkeypatch.setattr(selection, '_run', run)
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._compose_selected_image(env)
    assert len(calls) == (1 if stage == 'explain' else 2)


def test_compose_selected_image_uses_explained_graph_and_exact_environment(monkeypatch):
    calls = []
    env = {'NARROWED': '1'}
    def run(argv, **kwargs):
        assert kwargs['env'] is env
        calls.append(argv)
        return reply("-f 'fixture space.yml'") if len(calls) == 1 else reply(
            json.dumps({'services': {'sentinel': {'image': '  ' + REF + '  '}}}))
    monkeypatch.setattr(selection, '_run', run)
    assert selection._compose_selected_image(env) == REF
    assert calls == [['bash', 'scripts/sentinel-compose.sh', '--explain'],
        ['docker', 'compose', '-f', 'fixture space.yml', '--profile', 'cli', 'config', '--format', 'json']]


@pytest.mark.parametrize('raw', [
    '{"services":{"sentinel":{"image":"old","image":"new"}}}',
    '{"services":{"sentinel":{"image":"new"}},"note":NaN}',
    '{"services":{"sentinel":{"image":"new"}},"note":1e999}',
])
def test_ambiguous_compose_json_cannot_select_a_runtime(monkeypatch, raw):
    calls = []
    monkeypatch.setattr(selection, '_run', lambda argv, **kwargs:
        calls.append(argv) or reply('-f fixture.yml' if len(calls) == 1 else raw))
    with pytest.raises(selection.RuntimeSelectionRefused):
        selection._compose_selected_image({})


@pytest.mark.parametrize('condition', ['bad-head', 'configuration', 'unavailable', 'match', 'stale'])
def test_preflight_reports_status_without_writing_or_promoting(monkeypatch, capsys, condition):
    monkeypatch.setattr(selection, '_git', lambda *args: 'bad' if condition == 'bad-head' else SHA)
    monkeypatch.setattr(selection, '_merged_environment', lambda: {'NARROWED': '1'})
    seen = []
    def selected(env):
        if condition == 'configuration':
            raise selection.RuntimeSelectionRefused('invalid fixture environment')
        return REF
    def inspect(reference):
        seen.append(reference)
        if condition == 'unavailable':
            raise selection.RuntimeSelectionRefused('no fixture image')
        return ID, SHA if condition == 'match' else '3' * 40
    monkeypatch.setattr(selection, '_compose_selected_image', selected)
    monkeypatch.setattr(selection, '_inspect', inspect)
    monkeypatch.setattr(selection, '_write_pointer', lambda *a: pytest.fail('preflight wrote selector'))
    result = selection.preflight()
    output = capsys.readouterr()
    if condition in {'bad-head', 'configuration'}:
        assert result == 2 and 'REFUSED' in output.err and not seen
    else:
        assert result == 0 and seen == [REF]
        assert condition.upper() in output.out


@pytest.mark.parametrize('reference', [ID, REF])
def test_atomic_pointer_replacement_retains_private_permissions(monkeypatch, tmp_path, reference):
    path = tmp_path / 'state' / 'selector.env'
    monkeypatch.setattr(selection, 'POINTER', path)
    selection._write_pointer(reference)
    assert path.read_bytes() == ('SENTINEL_RUNTIME_IMAGE_REF=' + reference + '\n').encode('ascii')
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob('.validated-runtime-*'))
    selection._write_pointer(ID)
    assert path.read_text() == 'SENTINEL_RUNTIME_IMAGE_REF=' + ID + '\n'


def test_mutable_pointer_refusal_never_creates_its_directory(monkeypatch, tmp_path):
    path = tmp_path / 'never-created' / 'selector.env'
    monkeypatch.setattr(selection, 'POINTER', path)
    with pytest.raises(selection.RuntimeSelectionRefused, match='non-immutable'):
        selection._write_pointer('sentinel:latest')
    assert not path.parent.exists()


@pytest.mark.parametrize('fault', ['permission', 'file-sync', 'replace', 'directory-open', 'directory-sync'])
def test_pointer_storage_fault_preserves_old_value_or_committed_selector(monkeypatch, tmp_path, fault):
    path = tmp_path / 'selector.env'
    path.write_text('old selector\n')
    monkeypatch.setattr(selection, 'POINTER', path)
    original_open, original_sync = selection.os.open, selection.os.fsync
    directory_descriptors = set()
    def opened(candidate, flags, *args, **kwargs):
        if str(candidate) == str(path.parent):
            if fault == 'directory-open':
                raise OSError('injected directory open')
            fd = original_open(candidate, flags, *args, **kwargs)
            directory_descriptors.add(fd)
            return fd
        return original_open(candidate, flags, *args, **kwargs)
    def synced(fd):
        if fault == ('directory-sync' if fd in directory_descriptors else 'file-sync'):
            raise OSError('injected sync')
        return original_sync(fd)
    monkeypatch.setattr(selection.os, 'open', opened)
    monkeypatch.setattr(selection.os, 'fsync', synced)
    if fault == 'permission':
        monkeypatch.setattr(selection.os, 'fchmod',
            lambda *a: (_ for _ in ()).throw(OSError('injected permission')))
    if fault == 'replace':
        monkeypatch.setattr(selection.os, 'replace',
            lambda *a: (_ for _ in ()).throw(OSError('injected replace')))
    if fault in {'directory-open', 'directory-sync'}:
        selection._write_pointer(ID)
        assert path.read_text() == 'SENTINEL_RUNTIME_IMAGE_REF=' + ID + '\n'
    else:
        with pytest.raises(OSError, match='injected'):
            selection._write_pointer(ID)
        assert path.read_text() == 'old selector\n'
    assert not list(tmp_path.glob('.validated-runtime-*'))


@pytest.mark.parametrize('fault', ['permission', 'stream-open'])
def test_pre_stream_failure_closes_the_owned_descriptor(monkeypatch, tmp_path, fault):
    path = tmp_path / 'selector.env'
    path.write_text('old selector\n')
    monkeypatch.setattr(selection, 'POINTER', path)
    original = selection.tempfile.mkstemp
    owned = []
    def create(*args, **kwargs):
        descriptor, name = original(*args, **kwargs)
        owned.append(descriptor)
        return descriptor, name
    monkeypatch.setattr(selection.tempfile, 'mkstemp', create)
    target = 'fchmod' if fault == 'permission' else 'fdopen'
    monkeypatch.setattr(selection.os, target,
        lambda *a, **k: (_ for _ in ()).throw(OSError('injected pre-stream failure')))
    with pytest.raises(OSError, match='injected pre-stream failure'):
        selection._write_pointer(ID)
    assert len(owned) == 1 and path.read_text() == 'old selector\n'
    assert not list(tmp_path.glob('.validated-runtime-*'))
    with pytest.raises(OSError):
        os.fstat(owned[0])


@pytest.mark.parametrize('args,result', [([], 2), (['--input', 'fixture.json'], 0),
    (['--input=fixture.json'], 0), (['--unrelated'], 2)])
def test_generic_promotion_remains_disabled_except_development_noop(monkeypatch, capsys, args, result):
    monkeypatch.setattr(selection, '_write_pointer', lambda *a: pytest.fail('generic promotion wrote selector'))
    assert selection.promote(args) == result
    output = capsys.readouterr()
    assert ('SKIPPED' in output.out) if result == 0 else ('disabled' in output.err)


@pytest.mark.parametrize('args,expected', [(['preflight'], 7), (['promote'], []),
    (['promote', '--', '--input', 'fixture.json'], ['--input', 'fixture.json']),
    (['promote', 'fixture'], ['fixture'])])
def test_cli_dispatch_keeps_development_arguments_and_preflight_exit(monkeypatch, args, expected):
    monkeypatch.setattr(selection, 'preflight', lambda: 7)
    monkeypatch.setattr(selection, 'promote', lambda value: value)
    assert selection.main(args) == expected


def test_actual_script_entrypoint_is_read_only(monkeypatch, tmp_path):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        if argv[:2] == ['git', 'rev-parse']:
            return reply(SHA)
        if argv[:2] == ['bash', 'scripts/sentinel-compose.sh']:
            return reply('-f fixture.yml')
        if argv[:2] == ['docker', 'compose']:
            return reply(json.dumps({'services': {'sentinel': {'image': REF}}}))
        assert argv == ['docker', 'image', 'inspect', REF]
        return reply(json.dumps([image()]))
    monkeypatch.setattr(sys.modules['sentinel_host_command'], 'run', run)
    monkeypatch.setattr(selection.sentinel_env, 'load', lambda *a, **k: {})
    monkeypatch.setattr(selection.sentinel_env, 'merge', lambda *a: {})
    original_is_file = Path.is_file
    pointer = SOURCE.parent.parent / 'artifacts/sentinel/deployment/validated-runtime.env'
    monkeypatch.setattr(Path, 'is_file', lambda candidate:
        False if candidate == pointer else original_is_file(candidate))
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), 'preflight'])
    with pytest.raises(SystemExit) as completed:
        runpy.run_path(str(SOURCE), run_name='__main__')
    assert completed.value.code == 0
    assert len(commands) == 4
    assert commands[-1] == ['docker', 'image', 'inspect', REF]
