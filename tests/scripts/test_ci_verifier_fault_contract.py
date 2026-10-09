"""Exact-source certification refusals, using unsigned fixtures and GET doubles.

These tests issue no certificate and grant no deployment or broker authority.
"""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import urllib.error
import urllib.request
import zipfile

import pytest

from scripts import sentinel_ci_certification_verify as verify
from tests.scripts import test_sentinel_ci_certification_verify as fixture


def refused(code, callback):
    with pytest.raises(verify.CertificationVerificationRefused) as result:
        callback()
    assert result.value.code == code
    return result.value


def repository():
    return {'id': verify.REPOSITORY_ID, 'full_name': verify.REPOSITORY}


def publication():
    return dict(fixture.PUBLICATION, workflow_id=verify.PUBLICATION_WORKFLOW_ID,
                path=verify.PUBLICATION_WORKFLOW_PATH+'@main', head_sha=fixture.COMMIT,
                head_branch='main', event='workflow_run', status='completed',
                conclusion='success', repository=repository(), head_repository=repository())


class Reader:
    def __init__(self):
        self.calls = []
        self.archive = fixture._archive()
        self.run = publication()
        self.artifact = {
            'name': 'sentinel-provenance-'+fixture.COMMIT, 'expired': False,
            'digest': 'sha256:'+hashlib.sha256(self.archive).hexdigest(),
            'archive_download_url': verify.API_ROOT+'/artifacts/1/zip',
            'workflow_run': {'id': fixture.PUBLICATION['id'],
                             'repository_id': verify.REPOSITORY_ID,
                             'head_repository_id': verify.REPOSITORY_ID,
                             'head_branch': 'main', 'head_sha': fixture.COMMIT}}
        self.jobs = [{'name': name, 'conclusion': 'success'} for name in verify.REQUIRED_JOBS]

    def json(self, path):
        self.calls.append(('GET JSON', path))
        if path.endswith('/actions/runs?head_sha='+fixture.COMMIT+'&per_page=100'):
            return {'workflow_runs': [self.run]}
        if path.endswith('/artifacts?per_page=100'):
            return {'artifacts': [self.artifact]}
        if path.endswith('/jobs?per_page=100'):
            return {'jobs': self.jobs}
        assert path.endswith('/actions/runs/7001'), path
        return fixture._SafetyClient(self.jobs).json(path)

    def bytes(self, url):
        self.calls.append(('GET BYTES', url))
        assert url == self.artifact['archive_download_url']
        return self.archive


def test_full_discovery_reobserves_exact_head_and_each_required_job(monkeypatch):
    identity = {'commit': fixture.COMMIT, 'tree': fixture.TREE}
    observations = []
    client = Reader()
    def current(root):
        observations.append(root)
        return dict(identity)
    monkeypatch.setattr(verify, 'current_identity', current)
    result = verify.verify_current(root=Path('/private/reviewed-source'), client=client)
    assert result['source_commit'] == fixture.COMMIT
    assert result['certified_image'] == fixture.SUBJECT+'@'+fixture.DIGEST
    assert result['test_workflow_run'] == 7001
    assert observations == [Path('/private/reviewed-source')]*2
    assert len(client.calls) == 5 and all(c[0].startswith('GET') for c in client.calls)


@pytest.mark.parametrize('mode', ['wrong-requested-head', 'changed-final-head'])
def test_discovery_never_relabels_another_or_changed_checkout(monkeypatch, mode):
    client = Reader()
    states = iter([{'commit': fixture.COMMIT, 'tree': fixture.TREE},
                   {'commit': 'f'*40, 'tree': fixture.TREE}])
    monkeypatch.setattr(verify, 'current_identity', lambda root: next(states))
    code = 'CERT_SOURCE_SHA_MISMATCH' if mode == 'wrong-requested-head' else 'CERT_CURRENT_HEAD_CHANGED'
    refused(code, lambda: verify.verify_current(client=client,
        commit='f'*40 if mode == 'wrong-requested-head' else fixture.COMMIT))
    assert len(client.calls) == (0 if mode == 'wrong-requested-head' else 5)


def test_default_read_client_uses_the_scoped_read_token_without_mutation_methods(monkeypatch):
    monkeypatch.setenv('SENTINEL_GITHUB_READ_TOKEN', 'synthetic-scoped-read-token')
    monkeypatch.setenv('GITHUB_TOKEN', 'synthetic-fallback-token')
    client, tokens = Reader(), []
    monkeypatch.setattr(verify, 'current_identity', lambda root:
                        {'commit': fixture.COMMIT, 'tree': fixture.TREE})
    def construct(token):
        tokens.append(token)
        return client
    monkeypatch.setattr(verify, 'GitHubReadClient', construct)
    assert verify.verify_current()['software_certification'] == 'VERIFIED'
    assert tokens == ['synthetic-scoped-read-token']


@pytest.mark.parametrize('raw', [b'\xff', b'{', b'[]', b'null', b'{"a":1,"a":2}',
                               b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}'])
def test_json_reader_refuses_invalid_encoding_type_and_duplicate_fields(raw):
    refused('CERT_GITHUB_RESPONSE_INVALID', lambda:
            verify._json_bytes(raw, 'CERT_GITHUB_RESPONSE_INVALID', 'fixture response'))


@pytest.mark.parametrize('code', [0, 1])
def test_git_observer_checks_exit_status_and_strips_only_output(monkeypatch, code):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=code, stdout='  '+fixture.COMMIT+'\n')
    monkeypatch.setattr(verify.subprocess, 'run', run)
    if code:
        refused('CERT_GIT_IDENTITY_UNAVAILABLE', lambda: verify._git(Path('/private'), 'rev-parse', 'HEAD'))
    else:
        assert verify._git(Path('/private'), 'rev-parse', 'HEAD') == fixture.COMMIT
    assert calls[0][0] == ['git', 'rev-parse', 'HEAD']
    assert calls[0][1]['cwd'] == '/private' and calls[0][1]['check'] is False


@pytest.mark.parametrize('head,tree', [('bad', fixture.TREE), (fixture.COMMIT, 'bad'),
                                     (fixture.COMMIT, fixture.TREE)])
def test_current_git_identity_requires_two_canonical_shas(monkeypatch, head, tree):
    values = iter([head, tree])
    monkeypatch.setattr(verify, '_git', lambda *a: next(values))
    if head == 'bad' or tree == 'bad':
        refused('CERT_GIT_IDENTITY_UNAVAILABLE', verify.current_identity)
    else:
        assert verify.current_identity() == {'commit': head, 'tree': tree}


@pytest.mark.parametrize('token', [None, 'synthetic-read-token'])
def test_read_client_sends_get_headers_and_validates_response(token):
    calls = []
    def opener(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(b'{"observed":"fixture"}')
    client = verify.GitHubReadClient(token=token, opener=opener)
    assert client.json('/fixture') == {'observed': 'fixture'}
    assert client.bytes(verify.API_ROOT+'/fixture') == b'{"observed":"fixture"}'
    assert all(r.get_method() == 'GET' and timeout == 30 for r,timeout in calls)
    assert calls[0][0].get_header('Authorization') == ('Bearer '+token if token else None)


@pytest.mark.parametrize('error', [OSError('private detail'), urllib.error.URLError('private detail')])
def test_get_failure_is_a_typed_refusal_without_leaking_transport_detail(error):
    def opener(*a, **k):
        raise error
    actual = refused('CERT_GITHUB_UNAVAILABLE', lambda:
                     verify.GitHubReadClient(opener=opener).bytes(verify.API_ROOT+'/fixture'))
    assert actual.detail == 'GitHub read failed'


def test_safe_opener_installs_the_authorization_stripping_handler(monkeypatch):
    observed = []
    request = urllib.request.Request(verify.API_ROOT+'/fixture')
    def build(handler):
        assert isinstance(handler, verify._AuthorizationStrippingRedirect)
        return SimpleNamespace(open=lambda actual, timeout:
            observed.append((actual, timeout)) or b'fixture response')
    monkeypatch.setattr(verify.urllib.request, 'build_opener', build)
    assert verify._safe_urlopen(request, timeout=7) == b'fixture response'
    assert observed == [(request, 7)]


def test_redirect_that_produces_no_request_does_not_create_one(monkeypatch):
    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, 'redirect_request', lambda *a: None)
    handler = verify._AuthorizationStrippingRedirect()
    assert handler.redirect_request(urllib.request.Request(verify.API_ROOT), None,
        302, 'fixture', {}, verify.API_ROOT+'/fixture') is None


@pytest.mark.parametrize('rows,code', [(None, 'CERT_GITHUB_RESPONSE_INVALID'),
                                      ([], 'CERT_NO_PUBLICATION'),
                                      (['not-a-run'], 'CERT_NO_PUBLICATION')])
def test_publication_discovery_cannot_admit_missing_or_malformed_inventory(rows, code):
    refused(code, lambda: verify._publication_run(SimpleNamespace(json=lambda _: {'workflow_runs': rows}), fixture.COMMIT))


def test_publication_discovery_selects_exact_source_and_actual_attempt():
    first, retry = publication(), publication()
    retry.update(id=8000, run_attempt=2)
    unrelated = dict(retry, head_sha='f'*40)
    client = SimpleNamespace(json=lambda _: {'workflow_runs': [unrelated, retry, first]})
    assert verify._publication_run(client, fixture.COMMIT) == retry


@pytest.mark.parametrize('section', ['repository', 'head_repository'])
@pytest.mark.parametrize('identity', [None, True, '1233957439', 1233957439.0])
def test_repository_identity_retains_its_integer_type(section, identity):
    row = publication()
    row[section]['id'] = identity
    assert verify._same_repo(row) is False


@pytest.mark.parametrize('field,value', [('id', 9001.0),
                                       ('repository_id', 1233957439.0),
                                       ('head_repository_id', 1233957439.0)])
def test_artifact_workflow_identity_is_not_numeric_equality_alone(field, value):
    client = Reader()
    client.artifact['workflow_run'][field] = value
    refused('CERT_ARTIFACT_BINDING_INVALID', lambda:
            verify._publication_artifact(client, fixture.PUBLICATION, fixture.COMMIT))


@pytest.mark.parametrize('field,value', [('id', '9001'), ('id', 9001.5),
                                       ('id', True), ('id', 0), ('run_attempt', '1'),
                                       ('run_attempt', 1.5), ('run_attempt', False)])
def test_publication_identity_never_coerces_untrusted_json_numbers(field, value):
    row = publication()
    row[field] = value
    refused('CERT_GITHUB_RESPONSE_INVALID', lambda:
        verify._publication_run(SimpleNamespace(json=lambda _: {'workflow_runs': [row]}), fixture.COMMIT))


@pytest.mark.parametrize('rows,code', [(None, 'CERT_GITHUB_RESPONSE_INVALID'),
                                      ([], 'CERT_ARTIFACT_MISSING'),
                                      (['not-an-artifact'], 'CERT_ARTIFACT_MISSING')])
def test_artifact_discovery_requires_exact_live_inventory(rows, code):
    refused(code, lambda: verify._publication_artifact(SimpleNamespace(json=lambda _: {'artifacts': rows}), fixture.PUBLICATION, fixture.COMMIT))


@pytest.mark.parametrize('mutation,code', [('digest', 'CERT_ARTIFACT_DIGEST_INVALID'),
                                         ('workflow', 'CERT_ARTIFACT_BINDING_INVALID'),
                                         ('expired', 'CERT_ARTIFACT_MISSING'),
                                         ('duplicate', 'CERT_ARTIFACT_MISSING')])
def test_artifact_metadata_cannot_escape_exact_workflow_binding(mutation, code):
    client = Reader()
    artifact = copy.deepcopy(client.artifact)
    if mutation == 'digest':
        artifact['digest'] = 'not-a-digest'
    elif mutation == 'workflow':
        artifact['workflow_run']['head_sha'] = 'f'*40
    elif mutation == 'expired':
        artifact['expired'] = True
    rows = [artifact, artifact] if mutation == 'duplicate' else [artifact]
    refused(code, lambda: verify._publication_artifact(SimpleNamespace(json=lambda _: {'artifacts': rows}), fixture.PUBLICATION, fixture.COMMIT))


@pytest.mark.parametrize('mutation,code', [('url', 'CERT_ARTIFACT_BINDING_INVALID'),
                                         ('digest', 'CERT_ARTIFACT_DIGEST_MISMATCH')])
def test_artifact_download_requires_api_origin_and_exact_bytes(mutation, code):
    client = Reader()
    if mutation == 'url':
        client.artifact['archive_download_url'] = 'https://api.github.com.evil/fixture'
    else:
        client.artifact['digest'] = 'sha256:'+'0'*64
    refused(code, lambda: verify._download_artifact(client, client.artifact))
    assert len(client.calls) == (0 if mutation == 'url' else 1)


@pytest.mark.parametrize('raw', [b'not ZIP', b'PK\x03\x04'])
def test_bundle_refuses_truncated_or_wrong_container_bytes(raw):
    refused('CERT_BUNDLE_SCHEMA_INVALID', lambda: verify._bundle_members(raw))


def test_bundle_requires_exact_members():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        bundle.writestr('unexpected.json', '{}')
    refused('CERT_BUNDLE_SCHEMA_INVALID', lambda: verify._bundle_members(stream.getvalue()))


@pytest.mark.parametrize('mode', ['encoding', 'row', 'duplicate', 'unknown', 'digest', 'incomplete'])
def test_checksum_manifest_cannot_omit_duplicate_or_relabel_payloads(mode):
    members = verify._bundle_members(fixture._archive())
    rows = members['SHA256SUMS'].decode().splitlines()
    if mode == 'encoding':
        members['SHA256SUMS'] = b'\xff'
    elif mode == 'row':
        members['SHA256SUMS'] = b'not a checksum\n'
    elif mode == 'duplicate':
        members['SHA256SUMS'] += (rows[0]+'\n').encode()
    elif mode == 'unknown':
        members['SHA256SUMS'] = ('0'*64+'  unknown.json\n').encode()
    elif mode == 'digest':
        members['certification.json'] += b' '
    else:
        members['SHA256SUMS'] = ('\n'.join(rows[:-1])+'\n').encode()
    refused('CERT_BUNDLE_INTEGRITY_INVALID', lambda: verify._verify_sums(members))


@pytest.mark.parametrize('payload', [None, [], False, 0, 'not a statement'])
def test_attestation_payload_requires_a_json_object(payload):
    bundle = fixture._attestation()
    bundle['dsseEnvelope']['payload'] = base64.b64encode(json.dumps(payload).encode()).decode()
    refused('CERT_ATTESTATION_BINDING_INVALID', lambda: verify._verify_attestation(bundle, fixture.DIGEST))


def test_attestation_payload_rejects_duplicate_binding_keys():
    raw = base64.b64decode(fixture._attestation()['dsseEnvelope']['payload'])
    duplicated = b'{"_type":"wrong",'+raw[1:]
    bundle = fixture._attestation()
    bundle['dsseEnvelope']['payload'] = base64.b64encode(duplicated).decode()
    refused('CERT_ATTESTATION_BINDING_INVALID', lambda: verify._verify_attestation(bundle, fixture.DIGEST))


@pytest.mark.parametrize('field,value', [('publication_workflow_run', '9001'),
                                       ('publication_workflow_run', 9001.5),
                                       ('test_workflow_run', '7001'),
                                       ('test_workflow_run', 7001.5)])
def test_provenance_workflow_identity_never_truncates_or_coerces(field, value):
    def mutate(provenance):
        provenance[field] = value
    refused('CERT_PROVENANCE_BINDING_INVALID', lambda:
            verify.verify_bundle(fixture._archive(provenance_mutator=mutate),
                                 fixture.COMMIT, fixture.TREE, fixture.PUBLICATION))


@pytest.mark.parametrize('path,value,code', [
    (('certification_version',), 999, 'CERT_MANIFEST_SCHEMA_UNKNOWN'),
    (('certification_version',), True, 'CERT_MANIFEST_SCHEMA_UNKNOWN'),
    (('source',), None, 'CERT_MANIFEST_SCHEMA_UNKNOWN'),
    (('source', 'repository'), 'other/repository', 'CERT_SOURCE_SHA_MISMATCH'),
    (('runtime', 'docker_image_digest'), 'not-immutable', 'CERT_IMAGE_DIGEST_MISSING'),
    (('runtime', 'immutable_ref'), 'mutable:tag', 'CERT_IMAGE_BINDING_INVALID'),
    (('runtime', 'ci_local_image_id'), 'not-an-image', 'CERT_IMAGE_BINDING_INVALID'),
    (('runtime', 'runtime_capability_sha256'), None, 'CERT_RUNTIME_CAPABILITY_INVALID'),
    (('dependencies', 'lock_hashes'), None, 'CERT_DEPENDENCY_HASHES_INVALID'),
    (('dependencies', 'lock_hashes'), {}, 'CERT_DEPENDENCY_HASHES_INVALID'),
    (('dependencies', 'lock_hashes', 'tests/requirements.lock'), 'bad', 'CERT_DEPENDENCY_HASHES_INVALID'),
    (('tests', 'manifest_sha256'), 'bad', 'CERT_TEST_MANIFEST_INVALID'),
    (('tests', 'required_job_conclusions'), {}, 'CERT_REQUIRED_JOB_FAILED'),
    (('tests', 'adversarial_evidence'), None, 'CERT_EVIDENCE_INVALID'),
    (('tests', 'mutation_evidence', 'status'), 'FAIL', 'CERT_EVIDENCE_INVALID'),
    (('tests', 'mutation_evidence', 'sha256'), 'bad', 'CERT_EVIDENCE_INVALID'),
    (('ci', 'test_workflow_path'), 'other.yml', 'CERT_SAFETY_BINDING_INVALID'),
    (('ci', 'test_workflow_run'), 0, 'CERT_SAFETY_BINDING_INVALID'),
    (('ci', 'publication_workflow_run'), 9002, 'CERT_PUBLICATION_BINDING_INVALID'),
    (('ci', 'publication_workflow_attempt'), 2, 'CERT_PUBLICATION_BINDING_INVALID'),
    (('certified_at',), None, 'CERT_CERTIFIED_AT_INVALID'),
    (('certified_at',), 'not-a-dateZ', 'CERT_CERTIFIED_AT_INVALID'),
    (('certified_at',), '2026-10-09T00:00:00', 'CERT_CERTIFIED_AT_INVALID'),
])
def test_manifest_binding_refuses_independently_rehashed_wrong_fields(path, value, code):
    manifest = fixture._manifest()
    section = manifest
    for name in path[:-1]:
        section = section[name]
    section[path[-1]] = value
    fixture._rehash(manifest)
    refused(code, lambda: verify.verify_bundle(fixture._archive(manifest=manifest),
            fixture.COMMIT, fixture.TREE, fixture.PUBLICATION))


@pytest.mark.parametrize('mutation', ['v1-xfail', 'v2-missing', 'v2-wrong-type',
    'v2-wrong-suite', 'v2-wrong-inventory', 'v2-wrong-hash', 'unknown-version',
    'required-shape', 'required-noninteger', 'required-negative', 'required-zero',
    'required-xfail', 'suite-shape', 'suite-row-shape', 'suite-noninteger',
    'suite-zero', 'suite-xfail', 'mismatched-totals'])
def test_test_counts_cannot_authorize_missing_or_fabricated_evidence(mutation):
    tests = fixture._manifest()['tests']
    version = 1
    if mutation.startswith('v2-'):
        version = 2
        tests['expected_xfails'] = {}
    if mutation == 'v1-xfail':
        tests['expected_xfails'] = {}
    elif mutation == 'v2-missing':
        del tests['expected_xfails']
    elif mutation == 'v2-wrong-type':
        tests['expected_xfails'] = []
    elif mutation == 'v2-wrong-suite':
        tests['expected_xfails'] = {'sentinel': {}}
    elif mutation == 'v2-wrong-inventory':
        tests['expected_xfails'] = {'wealth_core_boundary': {'nodeids': [], 'junit_sha256': '6'*64}}
    elif mutation == 'v2-wrong-hash':
        tests['expected_xfails'] = {'wealth_core_boundary': {
            'nodeids': sorted(verify.WEALTH_EXPECTED_XFAILS), 'junit_sha256': 'bad'}}
    elif mutation == 'unknown-version':
        version = 3
    elif mutation == 'required-shape':
        tests['required_counts'] = {}
    elif mutation == 'required-noninteger':
        tests['required_counts']['passed'] = True
    elif mutation == 'required-negative':
        tests['required_counts']['passed'] = -1
    elif mutation == 'required-zero':
        tests['required_counts']['passed'] = 0
    elif mutation == 'required-xfail':
        tests['required_counts']['xfailed'] = 1
    elif mutation == 'suite-shape':
        tests['suite_counts'] = {}
    elif mutation == 'suite-row-shape':
        tests['suite_counts']['sentinel'] = []
    elif mutation == 'suite-noninteger':
        tests['suite_counts']['sentinel']['passed'] = True
    elif mutation == 'suite-zero':
        tests['suite_counts']['sentinel']['passed'] = 0
    elif mutation == 'suite-xfail':
        tests['suite_counts']['sentinel']['xfailed'] = 1
    else:
        tests['required_counts']['passed'] += 1
    refused('CERT_TEST_COUNTS_INVALID', lambda: verify._verify_counts(tests, version))


@pytest.mark.parametrize('payload', [{}, {'dsseEnvelope': None},
                                    {'dsseEnvelope': {'signatures': []}},
                                    {'dsseEnvelope': {'signatures': [{}], 'payload': '!bad!'}}])
def test_attestation_must_have_a_readable_nonempty_envelope(payload):
    refused('CERT_ATTESTATION_BINDING_INVALID', lambda:
            verify._verify_attestation(payload, fixture.DIGEST))


@pytest.mark.parametrize('mutation,code', [('run', 'CERT_SAFETY_BINDING_INVALID'),
    ('attempt', 'CERT_SAFETY_BINDING_INVALID'), ('jobs', 'CERT_GITHUB_RESPONSE_INVALID'),
    ('duplicate', 'CERT_REQUIRED_JOB_DUPLICATE')])
def test_reobserved_safety_run_and_jobs_cannot_change_the_receipt(mutation, code):
    client = Reader()
    original = client.json
    def response(path):
        value = original(path)
        if path.endswith('/actions/runs/7001'):
            if mutation == 'run':
                value['head_sha'] = 'f'*40
            elif mutation == 'attempt':
                value['run_attempt'] = '1'
        elif path.endswith('/jobs?per_page=100'):
            if mutation == 'jobs':
                value['jobs'] = None
            elif mutation == 'duplicate':
                value['jobs'].append(dict(value['jobs'][0]))
        return value
    client.json = response
    refused(code, lambda: verify._verify_safety_run(client, fixture._result()))


def test_unrelated_safety_rows_cannot_count_as_required_jobs():
    client = Reader()
    client.jobs += [None, {'name': 'unrelated', 'conclusion': 'failure'}]
    verify._verify_safety_run(client, fixture._result())
    assert len(client.calls) == 2


def test_v2_with_no_authorized_expected_failures_keeps_all_counts_clean():
    manifest = fixture._manifest()
    manifest.update(schema=verify.CERTIFICATION_SCHEMA_V2, certification_version=2)
    manifest['tests']['expected_xfails'] = {}
    fixture._rehash(manifest)
    result = verify.verify_bundle(fixture._archive(manifest=manifest),
        fixture.COMMIT, fixture.TREE, fixture.PUBLICATION)
    assert result['schema'] == verify.CERTIFICATION_SCHEMA_V2
    assert result['required_ci_jobs'] == 'PASS'
    assert manifest['tests']['required_counts']['xfailed'] == 0


def test_unknown_test_evidence_fields_cannot_extend_the_certificate_schema():
    manifest = fixture._manifest()
    manifest['tests']['unknown_authority'] = 'not admitted'
    fixture._rehash(manifest)
    refused('CERT_MANIFEST_SCHEMA_UNKNOWN', lambda: verify.verify_bundle(
        fixture._archive(manifest=manifest), fixture.COMMIT, fixture.TREE, fixture.PUBLICATION))


@pytest.mark.parametrize('field,value,code', [
    ('schema', 'unsupported', 'CERT_PROVENANCE_SCHEMA_INVALID'),
    ('commit', 'f'*40, 'CERT_PROVENANCE_BINDING_INVALID'),
    ('publication_workflow_run', 9002, 'CERT_PROVENANCE_BINDING_INVALID'),
    ('test_workflow_run', 7002, 'CERT_PROVENANCE_BINDING_INVALID'),
    ('certification_manifest_sha256', '0'*64, 'CERT_PROVENANCE_BINDING_INVALID'),
])
def test_provenance_cannot_replace_commit_run_or_manifest_hash(field, value, code):
    refused(code, lambda: verify.verify_bundle(fixture._archive(
        provenance_mutator=lambda row: row.update({field: value})),
        fixture.COMMIT, fixture.TREE, fixture.PUBLICATION))


def test_timestamp_parser_without_a_timezone_cannot_authorize_the_manifest(monkeypatch):
    from datetime import datetime
    # A defensive dependency boundary: no naive parser result can pass even
    # when the untrusted textual timestamp has the required Z suffix.
    monkeypatch.setattr(verify, 'datetime', SimpleNamespace(
        fromisoformat=lambda text: datetime(2026, 10, 9)))
    refused('CERT_CERTIFIED_AT_INVALID', lambda: verify.verify_bundle(
        fixture._archive(), fixture.COMMIT, fixture.TREE, fixture.PUBLICATION))


def test_cli_without_a_requested_file_does_not_write_one(monkeypatch, capsys):
    monkeypatch.setattr(verify, 'verify_current', lambda **kwargs:
        {'certified_image': fixture.SUBJECT+'@'+fixture.DIGEST})
    assert verify.main([]) == 0
    output = capsys.readouterr()
    assert output.err == '' and fixture.DIGEST in output.out


def test_real_cli_entrypoint_refuses_absent_git_identity_before_network(monkeypatch, capsys):
    calls = []
    def unavailable(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout='', stderr='synthetic unavailable Git identity')
    monkeypatch.setattr(verify.subprocess, 'run', unavailable)
    monkeypatch.setattr(sys, 'argv', [verify.__file__])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(verify.__file__, run_name='__main__')
    output = capsys.readouterr()
    assert result.value.code == 2 and output.out == ''
    assert calls == [['git', 'rev-parse', 'HEAD']]
    assert output.err.startswith('REFUSED: CERT_GIT_IDENTITY_UNAVAILABLE [detail_sha256=')


def test_terminal_refusal_keeps_its_python_exception_context():
    error = OSError('private fixture detail')
    def failed_read(*a, **k):
        raise error
    actual = refused('CERT_GITHUB_UNAVAILABLE', lambda:
        verify.GitHubReadClient(opener=failed_read).bytes(verify.API_ROOT+'/fixture'))
    assert actual.__context__ is error


@pytest.mark.parametrize('failure', [False, True])
def test_cli_emits_verified_identity_or_only_a_hashed_refusal(monkeypatch, tmp_path, capsys, failure):
    calls = []
    def current(**kwargs):
        calls.append(kwargs)
        if failure:
            raise verify.CertificationVerificationRefused('CERT_FIXTURE_REFUSED', 'private fixture detail')
        return {'certified_image': fixture.SUBJECT+'@'+fixture.DIGEST, 'source_commit': fixture.COMMIT}
    monkeypatch.setattr(verify, 'verify_current', current)
    output = tmp_path / 'nested' / 'certification.json'
    code = verify.main(['--commit', fixture.COMMIT, '--output', str(output)])
    captured = capsys.readouterr()
    assert calls == [{'commit': fixture.COMMIT}]
    if failure:
        assert code == 2 and not output.exists() and captured.out == ''
        assert 'private fixture detail' not in captured.err
        assert hashlib.sha256(b'private fixture detail').hexdigest() in captured.err
    else:
        assert code == 0 and captured.err == ''
        assert json.loads(output.read_bytes())['source_commit'] == fixture.COMMIT
        assert captured.out.startswith('software certification: VERIFIED ')
