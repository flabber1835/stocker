"""Exact host image/closure identities and atomic-record failure boundaries.

All image replies, Git identities and file records are disposable fixtures.
No image is pulled, signature issued, financial state accessed or service started.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
SOURCE = ROOT / 'scripts/sentinel_certification_state.py'
spec = importlib.util.spec_from_file_location('certification_state_fault_contract', SOURCE)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)
SHA = '1' * 40
RUNTIME = 'registry.invalid/sentinel:runtime'
TEST = 'registry.invalid/sentinel:test'
RUNTIME_DIGEST = 'registry.invalid/sentinel@sha256:' + '4' * 64
TEST_DIGEST = 'registry.invalid/sentinel@sha256:' + '5' * 64


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def image(kind='runtime'):
    return {'Id': 'sha256:' + ('2' if kind == 'runtime' else '3') * 64,
            'Config': {'Labels': {'org.opencontainers.image.revision': SHA}},
            'RepoDigests': [RUNTIME_DIGEST if kind == 'runtime' else TEST_DIGEST]}


def invoke_images(replies=None):
    calls = []
    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv[:3] == ['docker', 'image', 'inspect']
        kind = 'test' if argv[3] in {TEST, TEST_DIGEST} else 'runtime'
        value = deepcopy((replies or {}).get(argv[3], image(kind)))
        return subprocess.CompletedProcess(argv, 0, json.dumps([value]).encode(), b'')
    return invoke, calls


def build(tmp_path):
    invoke, calls = invoke_images()
    record = state.build_record(git_commit=SHA, runtime_ref=RUNTIME, test_ref=TEST, invoke=invoke)
    path = write(tmp_path / 'build.json', record)
    assert len(calls) == 2
    return path, record


def promotion(tmp_path):
    path, _ = build(tmp_path)
    invoke, _ = invoke_images()
    record = state.promotion_record(build_path=path, runtime_tag=RUNTIME, test_tag=TEST, invoke=invoke)
    return write(tmp_path / 'promotion.json', record), record


def closure(tmp_path, changed=False):
    lock = tmp_path / 'requirements.lock'
    lock.write_bytes(b'synthetic dependency closure\n')
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    baseline = write(tmp_path / 'manifest-original.json', {
        'schema': 'sentinel.certification_manifest/2', 'lifecycle': 'FINALIZED',
        'verdict': 'PASS', 'failures': [], 'git_tree_clean': True, 'git_commit': SHA,
        'distributions_hash': '6' * 64, 'requirements_lock_sha256': digest})
    identity = write(tmp_path / 'identity.json', {'environment': {
        'image_lock_sha256': digest, 'distributions_hash': ('7' if changed else '6') * 64}})
    args = dict(art=tmp_path, identity_path=identity, lock_path=lock, git_commit=SHA)
    return baseline, args


@pytest.mark.parametrize('raw', [b'null', b'[]', b'1', b'true', b'"scalar"', b'{', b'\xff'])
def test_json_refuses_malformed_or_nonobject_documents(raw):
    with pytest.raises(state.CertificationStateRefused):
        state._json_object(raw, label='record')


@pytest.mark.parametrize('raw', [b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                                b'{"nested":{"x":1e999}}'])
def test_json_refuses_every_nonfinite_number(raw):
    with pytest.raises(state.CertificationStateRefused, match='finite'):
        state._json_object(raw, label='record')


def test_duplicate_keys_cannot_overwrite_an_identity():
    with pytest.raises(state.CertificationStateRefused, match='duplicate'):
        state._json_object(b'{"outer":{"commit":"a","commit":"b"}}', label='record')
    assert state._json_object(b'{"number":1.25,"text":"x"}', label='record') == {'number': 1.25, 'text': 'x'}
    with pytest.raises(ValueError):
        state.canonical_bytes({'number': float('nan')})
    assert state.canonical_bytes({'b': 2, 'a': '\u00e9'}) == '{"a":"\u00e9","b":2}'.encode()


@pytest.mark.parametrize('value', [None, 1, True, 'a' * 63, 'A' * 64, 'sha256:' + 'a' * 64])
def test_canonical_digest_refuses_type_length_case_and_prefix(value):
    with pytest.raises(state.CertificationStateRefused, match='canonical'):
        state._digest(value, label='digest')


@pytest.mark.parametrize('value', [[], None, False, 'record'])
def test_mapping_refuses_nonobject(value):
    with pytest.raises(state.CertificationStateRefused, match='object'):
        state._mapping(value, label='record')


def test_mapping_exact_fields():
    with pytest.raises(state.CertificationStateRefused, match='exact schema'):
        state._mapping({'extra': 1}, label='record', fields={'required'})
    assert state._mapping({'required': 1}, label='record', fields={'required'}) == {'required': 1}


@pytest.mark.parametrize('stdout', [b'{', b'\xff', b'{}', b'[]', b'[{},{}]', b'[null]'])
def test_docker_inspection_refuses_malformed_single_image(stdout):
    with pytest.raises(state.CertificationStateRefused):
        state._docker_inspect(RUNTIME, invoke=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=stdout))


@pytest.mark.parametrize('field,value', [
    ('Id', None), ('Id', 'sha256:broken'), ('Id', 'sha256:' + 'A' * 64),
    ('Config', ['wrong']), ('Config', False), ('Config', None),
    ('RepoDigests', 'wrong'), ('RepoDigests', False), ('RepoDigests', [None])])
def test_docker_inspection_rejects_invalid_identity_shapes(field, value):
    reply = image()
    reply[field] = value
    invoke, _ = invoke_images({RUNTIME: reply})
    with pytest.raises(state.CertificationStateRefused):
        state._docker_inspect(RUNTIME, invoke=invoke)


@pytest.mark.parametrize('value', [[], False, 'wrong', None])
def test_docker_inspection_refuses_invalid_labels(value):
    reply = image()
    reply['Config']['Labels'] = value
    invoke, _ = invoke_images({RUNTIME: reply})
    with pytest.raises(state.CertificationStateRefused):
        state._docker_inspect(RUNTIME, invoke=invoke)


def test_docker_duplicate_revision_is_not_an_identity():
    reply = json.dumps([image()]).replace('"org.opencontainers.image.revision":',
        '"org.opencontainers.image.revision":"foreign", "org.opencontainers.image.revision":')
    with pytest.raises(state.CertificationStateRefused, match='duplicate'):
        state._docker_inspect(RUNTIME, invoke=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=reply.encode()))


@pytest.mark.parametrize('failure', [OSError('unavailable'), subprocess.CalledProcessError(1, ['docker'])])
def test_docker_failure_is_a_typed_refusal(failure):
    def invoke(*_a, **_k):
        if isinstance(failure, subprocess.CalledProcessError):
            return SimpleNamespace(returncode=failure.returncode, stdout=b'')
        raise failure
    with pytest.raises(state.CertificationStateRefused, match='Docker could not inspect'):
        state._docker_inspect(RUNTIME, invoke=invoke)


@pytest.mark.parametrize('tag', ['', '@bad', 'registry.invalid/path@sha256:' + 'a' * 64])
def test_promotion_repository_refuses_bad_tag(tag):
    with pytest.raises(state.CertificationStateRefused, match='tag'):
        state._repository(tag)


def test_repository_port_and_untagged_path():
    assert state._repository('registry.invalid:5000/path:tag') == 'registry.invalid:5000/path'
    assert state._repository('registry.invalid:5000/path') == 'registry.invalid:5000/path'


@pytest.mark.parametrize('digests', [[], ['elsewhere.invalid/image@sha256:' + '4' * 64],
    [RUNTIME_DIGEST, 'registry.invalid/sentinel@sha256:' + '6' * 64],
    ['registry.invalid/sentinel@sha256:broken']])
def test_promotion_requires_one_matching_canonical_digest(digests):
    reply = image()
    reply['RepoDigests'] = digests
    invoke, _ = invoke_images({RUNTIME: reply})
    with pytest.raises(state.CertificationStateRefused):
        state._promoted_identity(RUNTIME, invoke=invoke)


def test_build_and_promotion_roundtrip_reobserves_both_images(tmp_path):
    path, record = build(tmp_path)
    invoke, calls = invoke_images()
    assert state.verify_build(path, invoke=invoke) == record
    assert [args[3] for args, _ in calls] == [RUNTIME, TEST]
    promoted, record = promotion(tmp_path)
    invoke, calls = invoke_images()
    assert state.verify_promotion(promoted, git_commit=SHA, invoke=invoke) == record
    assert [args[3] for args, _ in calls] == [RUNTIME_DIGEST, TEST_DIGEST]


@pytest.mark.parametrize('kind', ['runtime', 'test', 'identical'])
def test_build_refuses_wrong_revision_or_identical_images(kind):
    replies = {RUNTIME: image(), TEST: image('test')}
    if kind == 'identical':
        replies[TEST]['Id'] = replies[RUNTIME]['Id']
    else:
        replies[RUNTIME if kind == 'runtime' else TEST]['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
    invoke, _ = invoke_images(replies)
    with pytest.raises(state.CertificationStateRefused):
        state.build_record(git_commit=SHA, runtime_ref=RUNTIME, test_ref=TEST, invoke=invoke)


@pytest.mark.parametrize('field,value', [('schema', 'foreign'), ('git_commit', False),
    ('runtime_image', None), ('test_image', {}), ('extra', 1)])
def test_build_record_rejects_corrupt_outer_schema(tmp_path, field, value):
    path, record = build(tmp_path)
    record[field] = value
    write(path, record)
    with pytest.raises(state.CertificationStateRefused):
        state.load_build(path)


@pytest.mark.parametrize('field,value', [('source_revision', 'f' * 40), ('id', None),
    ('id', 'sha256:broken'), ('ref', None), ('repo_digests', False), ('repo_digests', [None])])
def test_build_record_rejects_corrupt_nested_identity(tmp_path, field, value):
    path, record = build(tmp_path)
    record['runtime_image'][field] = value
    write(path, record)
    with pytest.raises(state.CertificationStateRefused):
        state.load_build(path)


@pytest.mark.parametrize('defect', ['id', 'revision', 'same-digest'])
def test_promotion_reobserves_frozen_roles_after_initial_build_verification(tmp_path, defect):
    path, _ = build(tmp_path)
    invoke, _ = invoke_images()
    count = 0
    def changed(argv, **kwargs):
        nonlocal count
        count += 1
        if count < 3:
            return invoke(argv, **kwargs)
        reply = image('test' if argv[-1] == TEST else 'runtime')
        if defect == 'id': reply['Id'] = 'sha256:' + 'a' * 64
        elif defect == 'revision': reply['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
        else: reply['RepoDigests'] = [RUNTIME_DIGEST]
        return subprocess.CompletedProcess(argv, 0, json.dumps([reply]).encode(), b'')
    with pytest.raises(state.CertificationStateRefused):
        state.promotion_record(build_path=path, runtime_tag=RUNTIME, test_tag=TEST, invoke=changed)


@pytest.mark.parametrize('field', ['Id', 'revision'])
def test_verify_build_refuses_moved_local_image(tmp_path, field):
    path, _ = build(tmp_path)
    reply = image()
    if field == 'Id': reply['Id'] = 'sha256:' + 'a' * 64
    else: reply['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
    invoke, _ = invoke_images({RUNTIME: reply})
    with pytest.raises(state.CertificationStateRefused, match='moved after build'):
        state.verify_build(path, invoke=invoke)


@pytest.mark.parametrize('field', ['schema', 'revision', 'digest', 'build-missing', 'build-hash', 'build-commit', 'path-type', 'id'])
def test_promotion_record_refuses_malformed_binding(tmp_path, field):
    path, record = promotion(tmp_path)
    if field == 'schema': record['schema'] = 'foreign'
    elif field == 'revision': record['runtime_image']['source_revision'] = 'f' * 40
    elif field == 'digest': record['runtime_image']['repo_digest'] = 'sha256:broken'
    elif field == 'build-missing': record['build_record']['path'] += '.absent'
    elif field == 'build-hash': record['build_record']['sha256'] = '0' * 64
    elif field == 'path-type': record['build_record']['path'] = None
    elif field == 'id': record['runtime_image']['id'] = 'sha256:broken'
    else: record['git_commit'] = 'f' * 40
    write(path, record)
    with pytest.raises(state.CertificationStateRefused):
        state.load_promotion(path)


@pytest.mark.parametrize('defect', ['other-build-id', 'same-digest', 'same-build-id'])
def test_loaded_records_preserve_distinct_frozen_image_roles(tmp_path, defect):
    path, record = promotion(tmp_path)
    if defect == 'other-build-id':
        record['runtime_image']['id'] = 'sha256:' + 'a' * 64
    elif defect == 'same-digest':
        record['test_image']['repo_digest'] = record['runtime_image']['repo_digest']
    else:
        build_path = Path(record['build_record']['path'])
        built = json.loads(build_path.read_bytes())
        built['test_image']['id'] = built['runtime_image']['id']
        write(build_path, built)
        with pytest.raises(state.CertificationStateRefused):
            state.load_build(build_path)
        return
    write(path, record)
    with pytest.raises(state.CertificationStateRefused):
        state.load_promotion(path)


@pytest.mark.parametrize('defect', ['commit', 'id', 'revision', 'repodigest'])
def test_verify_promotion_refuses_any_moved_identity(tmp_path, defect):
    path, _ = promotion(tmp_path)
    reply = image()
    commit = SHA
    if defect == 'commit': commit = 'f' * 40
    elif defect == 'id': reply['Id'] = 'sha256:' + 'a' * 64
    elif defect == 'revision': reply['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
    else: reply['RepoDigests'] = [TEST_DIGEST]
    invoke, _ = invoke_images({RUNTIME_DIGEST: reply})
    with pytest.raises(state.CertificationStateRefused):
        state.verify_promotion(path, git_commit=commit, invoke=invoke)


@pytest.mark.parametrize('field,value', [('schema', 'foreign'), ('lifecycle', 'OPEN'),
    ('verdict', 'FAIL'), ('failures', ['failure']), ('git_tree_clean', 1),
    ('git_commit', 'wrong'), ('distributions_hash', None), ('requirements_lock_sha256', 'wrong')])
def test_baseline_requires_clean_finalized_pass_and_canonical_bindings(tmp_path, field, value):
    path, _ = closure(tmp_path)
    record = json.loads(path.read_text())
    record[field] = value
    write(path, record)
    with pytest.raises(state.CertificationStateRefused):
        state.baseline_binding(path)


def test_closure_requires_explicit_existing_baseline_and_reviewed_change(tmp_path):
    baseline, args = closure(tmp_path, changed=True)
    with pytest.raises(state.CertificationStateRefused, match='name --certified-baseline'):
        state.validate_closure_context(**args)
    with pytest.raises(state.CertificationStateRefused, match='reviewed transition'):
        state.validate_closure_context(**args, baseline_path=baseline)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = state.review_transition(baseline_path=baseline, identity_path=args['identity_path'],
        lock_path=args['lock_path'], git_commit=SHA, reviewer=' reviewer ', reason=' dependency upgrade ', reviewed_at=timestamp)
    assert record['review'] == {'reviewer': 'reviewer', 'reason': 'dependency upgrade', 'reviewed_at_utc': '2026-01-01T00:00:00Z'}
    transition = write(tmp_path / 'transition.json', record)
    accepted = state.validate_closure_context(**args, baseline_path=baseline, transition_path=transition)
    assert accepted['baseline']['sha256'] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert accepted['transition']['sha256'] == hashlib.sha256(transition.read_bytes()).hexdigest()
    record['target']['git_commit'] = 'f' * 40
    write(transition, record)
    with pytest.raises(state.CertificationStateRefused, match='does not bind'):
        state.validate_closure_context(**args, baseline_path=baseline, transition_path=transition)


def test_unchanged_closure_and_no_baseline_are_distinct(tmp_path):
    baseline, args = closure(tmp_path)
    assert state.validate_closure_context(**args, baseline_path=baseline)['transition'] is None
    with pytest.raises(state.CertificationStateRefused, match='not applicable'):
        state.validate_closure_context(**args, baseline_path=baseline, transition_path='anything')
    with pytest.raises(state.CertificationStateRefused, match='did not change'):
        state.review_transition(baseline_path=baseline, identity_path=args['identity_path'],
            lock_path=args['lock_path'], git_commit=SHA, reviewer='reviewer', reason='reason')
    baseline.unlink()
    write(tmp_path / 'manifest-bad.json', {'verdict': 'FAIL'})
    assert state.validate_closure_context(**args)['baseline'] is None
    with pytest.raises(state.CertificationStateRefused, match='without a certified baseline'):
        state.validate_closure_context(**args, transition_path='anything')


def test_target_requires_actual_lock_hash(tmp_path):
    _baseline, args = closure(tmp_path)
    args['lock_path'].write_text('changed bytes')
    with pytest.raises(state.CertificationStateRefused, match='lock differs'):
        state.validate_closure_context(**args)


@pytest.mark.parametrize('reviewer,reason', [('', 'reason'), ('reviewer', ' ')])
def test_transition_requires_human_review_identity(tmp_path, reviewer, reason):
    baseline, args = closure(tmp_path, changed=True)
    with pytest.raises(state.CertificationStateRefused, match='reviewer and reason'):
        state.review_transition(baseline_path=baseline, identity_path=args['identity_path'],
            lock_path=args['lock_path'], git_commit=SHA, reviewer=reviewer, reason=reason)


@pytest.mark.parametrize('defect', ['schema', 'status', 'reviewer', 'reason', 'time', 'fields'])
def test_transition_reader_refuses_incomplete_review(tmp_path, defect):
    baseline, args = closure(tmp_path, changed=True)
    record = state.review_transition(baseline_path=baseline, identity_path=args['identity_path'],
        lock_path=args['lock_path'], git_commit=SHA, reviewer='reviewer', reason='reason')
    if defect == 'schema': record['schema'] = 'foreign'
    elif defect == 'status': record['status'] = 'UNREVIEWED'
    elif defect == 'fields': record['review']['extra'] = 1
    else: record['review'][{'time': 'reviewed_at_utc'}.get(defect, defect)] = None
    path = write(tmp_path / 'transition.json', record)
    with pytest.raises(state.CertificationStateRefused):
        state.transition_binding(path)


def test_atomic_records_cannot_clobber_and_identical_retry_is_idempotent(tmp_path):
    path = tmp_path / 'nested' / 'record.json'
    state.write_no_clobber({'identity': 'original'}, path)
    original = path.read_bytes()
    inode = path.stat().st_ino
    state.write_no_clobber({'identity': 'original'}, path)
    assert path.stat().st_ino == inode
    with pytest.raises(state.CertificationStateRefused, match='already exists'):
        state.write_no_clobber({'identity': 'replacement'}, path)
    assert path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('stage', ['write-fsync', 'link', 'directory-fsync'])
def test_atomic_failure_leaves_no_success_record_or_temporary(tmp_path, monkeypatch, stage):
    directory = tmp_path / 'atomic-records'
    directory.mkdir()
    path = directory / 'record.json'
    def fail(*_a, **_k): raise OSError('synthetic storage fault')
    if stage == 'write-fsync': monkeypatch.setattr(state.os, 'fsync', fail)
    elif stage == 'link': monkeypatch.setattr(state.os, 'link', fail)
    else: monkeypatch.setattr(state, '_fsync_directory', fail)
    with pytest.raises(OSError, match='storage fault'):
        state.write_no_clobber({'identity': 'original'}, path)
    assert not path.exists()
    assert list(directory.iterdir()) == []


def test_no_clobber_detects_racing_publisher(tmp_path, monkeypatch):
    directory = tmp_path / 'atomic-records'
    directory.mkdir()
    path = directory / 'record.json'
    link = state.os.link
    def raced(source, target):
        Path(target).write_bytes(b'competitor')
        return link(source, target)
    monkeypatch.setattr(state.os, 'link', raced)
    with pytest.raises(FileExistsError):
        state.write_no_clobber({'identity': 'new'}, path)
    assert path.read_bytes() == b'competitor'
    assert list(directory.iterdir()) == [path]


def test_windows_directory_sync_does_not_attempt_posix_open(monkeypatch):
    monkeypatch.setattr(state, 'os', SimpleNamespace(name='nt'))
    assert state._fsync_directory(Path('synthetic-windows-directory')) is None


def test_fsync_failure_preserved_if_rollback_cannot_remove_record(tmp_path, monkeypatch):
    directory = tmp_path / 'atomic-records'
    directory.mkdir()
    path = directory / 'record.json'
    unlink = Path.unlink
    fault = OSError('original durability fault')
    def fail_sync(_path): raise fault
    def fail_rollback(target, *args, **kwargs):
        if target == path: raise PermissionError('rollback denied')
        return unlink(target, *args, **kwargs)
    monkeypatch.setattr(state, '_fsync_directory', fail_sync)
    monkeypatch.setattr(Path, 'unlink', fail_rollback)
    with pytest.raises(OSError) as caught:
        state.write_no_clobber({'identity': 'original'}, path)
    assert caught.value is fault
    assert path.is_file()  # Failure remains a failure even if private cleanup is denied.
    assert list(directory.iterdir()) == [path]


def test_already_removed_temporary_is_benign_after_atomic_link(tmp_path, monkeypatch):
    directory = tmp_path / 'atomic-records'
    directory.mkdir()
    path = directory / 'record.json'
    link = state.os.link
    def linked_then_removed(source, target):
        link(source, target)
        Path(source).unlink()
    monkeypatch.setattr(state.os, 'link', linked_then_removed)
    state.write_no_clobber({'identity': 'original'}, path)
    assert json.loads(path.read_bytes()) == {'identity': 'original'}
    assert list(directory.iterdir()) == [path]


@pytest.mark.parametrize('operation', ['capture-build', 'verify-build', 'capture-promotion',
                                      'resolve-promotion', 'check-closure', 'review-transition'])
def test_actual_cli_dispatches_readers_and_canonical_records(tmp_path, monkeypatch, capsys, operation):
    original = state._docker_inspect
    invoke, calls = invoke_images()
    def inspect(ref, **kwargs):
        reader = kwargs.get('invoke')
        if reader is None or reader is subprocess.run:
            reader = invoke
        return original(ref, invoke=reader)
    monkeypatch.setattr(state, '_docker_inspect', inspect)
    monkeypatch.setattr(state, '_git_commit', lambda: SHA)
    output = tmp_path / 'output.json'
    if operation == 'capture-build':
        args = ['--git-commit', SHA, '--runtime-ref', RUNTIME, '--test-ref', TEST, '--output', str(output)]
    elif operation == 'verify-build':
        path, _ = build(tmp_path)
        args = ['--record', str(path)]
    elif operation in {'capture-promotion', 'resolve-promotion'}:
        path, _ = build(tmp_path) if operation == 'capture-promotion' else promotion(tmp_path)
        args = (['--build-record', str(path), '--runtime-tag', RUNTIME, '--test-tag', TEST, '--output', str(output)]
            if operation == 'capture-promotion' else ['--record', str(path), '--git-commit', SHA, '--kind', 'runtime'])
    else:
        baseline, closure_args = closure(tmp_path, changed=operation == 'review-transition')
        args = ['--identity', str(closure_args['identity_path']), '--lock', str(closure_args['lock_path'])]
        args += (['--art', str(tmp_path), '--git-commit', SHA, '--baseline', str(baseline)] if operation == 'check-closure'
            else ['--baseline', str(baseline), '--reviewer', 'reviewer', '--reason', 'reason', '--output', str(output)])
    assert state.main([operation] + args) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    if operation in {'capture-build', 'capture-promotion', 'review-transition'}:
        record = json.loads(output.read_bytes())
        assert output.read_bytes() == state.canonical_bytes(record) + b'\n'
    elif operation == 'resolve-promotion': assert captured.out.strip() == RUNTIME_DIGEST
    elif operation == 'check-closure': assert captured.out.startswith('closure_context:')


def test_cli_refusal_does_not_write_output(tmp_path, capsys):
    output = tmp_path / 'output.json'
    assert state.main(['capture-build', '--git-commit', 'bad', '--runtime-ref', RUNTIME,
        '--test-ref', TEST, '--output', str(output)]) == 1
    assert 'CERTIFICATION STATE REFUSED' in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize('failure', [OSError('missing git'), subprocess.CalledProcessError(1, ['git'])])
def test_git_reader_preserves_failure_context(monkeypatch, failure):
    def invoke(*_a, **_k): raise failure
    monkeypatch.setattr(state.subprocess, 'run', invoke)
    with pytest.raises(state.CertificationStateRefused, match='unavailable') as caught:
        state._git_commit()
    assert caught.value.__cause__ is failure


def test_git_reader_and_actual_module_entrypoint_refuse_invalid_commit(monkeypatch, capsys):
    calls = []
    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv == ['git', 'rev-parse', 'HEAD']
        return SimpleNamespace(stdout=SHA + '\n')
    monkeypatch.setattr(state.subprocess, 'run', invoke)
    assert state._git_commit() == SHA
    assert calls[0][1]['check'] is True
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), 'capture-build', '--git-commit', 'bad',
        '--runtime-ref', RUNTIME, '--test-ref', TEST, '--output', '/tmp/never-created-state-test.json'])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(SOURCE), run_name='__main__')
    assert caught.value.code == 1
    assert len(calls) == 1  # Refused before any Docker/Git subprocess.
    assert 'REFUSED' in capsys.readouterr().err
