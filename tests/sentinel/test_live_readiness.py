"""Integrity checks are useful preparation, never live trading permission."""
from datetime import datetime, timedelta, timezone
import ast
import hashlib
import inspect
import json

import pytest
from pydantic import ValidationError

from sentinel import live_readiness as readiness
from scripts import sentinel_live_readiness as cli


NOW = datetime(2026, 10, 24, 15, tzinfo=timezone.utc)
RAW = b'{"original":"candidate evidence; claims are unaccepted"}\n'


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def subject(**changes):
    return readiness.CandidateSubject(**{
        'git_commit': hashlib.sha1(b'candidate commit').hexdigest(),
        'source_sha256': digest('source'), 'image_digest': 'sha256:' + digest('image'),
        'strategy_sha256': digest('strategy'), 'data_semantics_sha256': digest('data'),
        'execution_policy_sha256': digest('policy'), **changes})


def reference(gate=readiness.Gate.OPENING_TIMING, **changes):
    return readiness.EvidenceReference(**{
        'gate': gate, 'profile': readiness.PROFILES[gate], 'scope': readiness.Scope.PRIVATE,
        'subject': subject(), 'artifact': gate.value + '.json',
        'artifact_sha256': hashlib.sha256(RAW).hexdigest(),
        'observed_at': NOW - timedelta(minutes=1), 'expires_at': NOW + timedelta(hours=1),
        **changes})


def manifest(*references, **changes):
    return readiness.PreparationManifest(subject=subject(), evidence=references, **changes)


def assess(*references, artifacts=None, **changes):
    material = manifest(*references)
    raw = {item.artifact: RAW for item in references} if artifacts is None else artifacts
    return readiness.inventory(material, raw, now=NOW, **changes)


def assert_no_authority(result):
    assert result.status == 'NOT_QUALIFIED'
    assert result.live_authority_granted is False
    assert result.live_transport_permitted is False
    assert result.order_authority == 'NONE'
    assert result.provider_completeness_proven is False
    assert result.native_settlement_proven is False
    assert result.unproven_gates == tuple(readiness.Gate)


def test_missing_inventory_names_all_six_gates_and_remaining_work():
    result = assess()
    assert_no_authority(result)
    assert tuple(item.gate for item in result.gates) == tuple(readiness.Gate)
    assert all(item.status == 'MISSING' and item.remaining_work for item in result.gates)


def test_intact_private_evidence_never_becomes_a_certificate():
    result = assess(*(reference(gate) for gate in readiness.Gate))
    assert_no_authority(result)
    for gate in result.gates:
        item = gate.evidence[0]
        assert item.integrity_verified
        assert item.observed_at == NOW - timedelta(minutes=1)
        assert item.expires_at == NOW + timedelta(hours=1)
        assert item.status == ('REJECTED' if gate.gate in {
            readiness.Gate.LIVE_ACCOUNT_AUTHORITY, readiness.Gate.LIVE_PILOT} else 'REVIEW_REQUIRED')


@pytest.mark.parametrize('scope', [readiness.Scope.PRIVATE, readiness.Scope.PAPER])
@pytest.mark.parametrize('gate', [readiness.Gate.LIVE_ACCOUNT_AUTHORITY, readiness.Gate.LIVE_PILOT])
def test_paper_certificate_or_private_file_cannot_satisfy_native_gate(scope, gate):
    item = assess(reference(gate, scope=scope)).gates[list(readiness.Gate).index(gate)].evidence[0]
    assert item.status == 'REJECTED'
    assert 'PAPER_OR_PRIVATE_EVIDENCE_CANNOT_PROVE_LIVE_GATE' in item.reasons


@pytest.mark.parametrize('gate,scope', [
    (readiness.Gate.LIVE_ACCOUNT_AUTHORITY, readiness.Scope.LIVE_READ_ONLY),
    (readiness.Gate.LIVE_PILOT, readiness.Scope.LIVE_PILOT),
])
def test_named_live_evidence_still_needs_independent_acceptance(gate, scope):
    bound = subject(live_account_id='00000000-0000-0000-0000-000000000123')
    item = reference(gate, subject=bound, scope=scope)
    result = readiness.inventory(readiness.PreparationManifest(subject=bound, evidence=(item,)),
                                 {item.artifact: RAW}, now=NOW)
    assert_no_authority(result)
    entry = result.gates[list(readiness.Gate).index(gate)].evidence[0]
    assert entry.status == 'REVIEW_REQUIRED'
    assert entry.reasons == ('CLAIMS_AND_PROVENANCE_NOT_INDEPENDENTLY_ACCEPTED',)


@pytest.mark.parametrize('field,value', [
    ('git_commit', hashlib.sha1(b'other commit').hexdigest()),
    ('source_sha256', digest('different source')), ('image_digest', 'sha256:' + digest('different image')),
    ('strategy_sha256', digest('different strategy')), ('data_semantics_sha256', digest('different data')),
    ('execution_policy_sha256', digest('different policy')),
    ('live_account_id', '00000000-0000-0000-0000-000000000123'),
])
def test_runtime_economic_policy_and_account_identity_drift_refuses(field, value):
    entry = assess(reference(subject=subject(**{field: value}))).gates[0].evidence[0]
    assert entry.status == 'REJECTED' and 'EXACT_SUBJECT_MISMATCH' in entry.reasons


@pytest.mark.parametrize('observed,expires', [
    (NOW + timedelta(microseconds=1), NOW + timedelta(hours=1)),
    (NOW - timedelta(hours=1), NOW),
    (NOW - timedelta(hours=2), NOW - timedelta(microseconds=1)),
])
def test_future_expired_and_boundary_expired_evidence_is_retained_as_rejected(observed, expires):
    entry = assess(reference(observed_at=observed, expires_at=expires)).gates[0].evidence[0]
    assert entry.status == 'REJECTED' and 'STALE_OR_FUTURE_EVIDENCE' in entry.reasons


@pytest.mark.parametrize('raw', [None, b'', RAW + b'altered'])
def test_missing_empty_or_changed_artifact_never_gets_integrity_credit(raw):
    ref = reference()
    artifacts = {} if raw is None else {ref.artifact: raw}
    entry = assess(ref, artifacts=artifacts).gates[0].evidence[0]
    assert entry.status == 'REJECTED' and entry.integrity_verified is False


@pytest.mark.parametrize('changes', [
    {'profile': 'paper-certificate'}, {'accepted': True}, {'producer': 'trusted'},
    {'signature': digest('forged')}, {'observed_at': NOW.replace(tzinfo=None)},
    {'observed_at': 1}, {'expires_at': NOW - timedelta(minutes=1)},
    {'expires_at': NOW + timedelta(days=2)}, {'artifact': '../secret.env'},
    {'artifact': 'C:/secret.env'}, {'artifact': 'https://example.com/proof'},
    {'artifact_sha256': '0' * 64}, {'artifact_sha256': 'abcd' * 16},
])
def test_malformed_claims_paths_placeholders_and_extended_clocks_refuse(changes):
    with pytest.raises(ValidationError):
        reference(**changes)


@pytest.mark.parametrize('changes', [
    {'git_commit': 'a' * 40}, {'git_commit': 'ABCDEF1234' * 4},
    {'source_sha256': '0' * 64}, {'image_digest': 'sha256:' + 'b' * 64},
    {'image_digest': 'candidate:latest'}, {'live_account_id': 'PA-PAPER-ACCOUNT'},
    {'live_account_id': '00000000-0000-0000-0000-000000000000'},
    {'profile': 'LIVE_ENABLED'}, {'live_authority_granted': True},
])
def test_placeholder_or_enablement_subjects_refuse(changes):
    with pytest.raises(ValidationError):
        subject(**changes)


def test_duplicate_reference_and_untyped_or_naive_evaluation_refuse():
    with pytest.raises(ValidationError):
        manifest(reference(), reference())
    with pytest.raises(TypeError):
        readiness.inventory({}, {}, now=NOW)
    with pytest.raises(ValueError):
        readiness.inventory(manifest(), {}, now=NOW.replace(tzinfo=None))
    with pytest.raises(TypeError):
        readiness.inventory(manifest(), {'bad': 'text'}, now=NOW)


def test_aggregate_and_per_artifact_byte_bounds(monkeypatch):
    ref = reference()
    monkeypatch.setattr(readiness, 'MAX_ARTIFACT_BYTES', len(RAW) - 1)
    assert assess(ref).gates[0].evidence[0].status == 'REJECTED'
    monkeypatch.setattr(readiness, 'MAX_TOTAL_BYTES', len(RAW) - 1)
    with pytest.raises(ValueError, match='aggregate byte bound'):
        assess(ref)


def test_report_cannot_accept_authority_fields():
    result = assess().model_dump()
    for key, value in {'status': 'QUALIFIED', 'live_authority_granted': True,
                       'live_transport_permitted': True, 'order_authority': 'LIVE',
                       'native_settlement_proven': True, 'provider_completeness_proven': True}.items():
        with pytest.raises(ValidationError):
            readiness.PreparationInventory.model_validate({**result, key: value})
    for key in ('gates', 'unproven_gates'):
        with pytest.raises(ValidationError):
            readiness.PreparationInventory.model_validate({**result, key: ()})


def test_file_only_cli_returns_nonqualified_and_preserves_original_files(tmp_path, capsys):
    ref = reference(observed_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    path = tmp_path / 'manifest.json'
    source = manifest(ref).model_dump_json(by_alias=True).encode()
    path.write_bytes(source)
    artifact = tmp_path / ref.artifact
    artifact.write_bytes(RAW)
    assert cli.main(['--manifest', str(path), '--evidence-dir', str(tmp_path)]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'NOT_QUALIFIED' and result['live_authority_granted'] is False
    assert result['gates'][0]['status'] == 'REVIEW_REQUIRED'
    assert path.read_bytes() == source and artifact.read_bytes() == RAW


@pytest.mark.parametrize('raw', [b'{"subject":{},"subject":{}}', b'{"evidence":NaN}', b'not-json'])
def test_cli_rejects_duplicate_nonfinite_and_invalid_json_without_echoing_content(tmp_path, capsys, raw):
    path = tmp_path / 'manifest.json'
    path.write_bytes(raw)
    assert cli.main(['--manifest', str(path), '--evidence-dir', str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert not captured.out and json.loads(captured.err)['status'] == 'INVALID_INPUT'
    assert raw.decode() not in captured.err


def test_cli_rejects_deep_json_with_a_sanitized_error(tmp_path, capsys):
    path = tmp_path / 'nested.json'
    raw = b'[' * 20000 + b'0' + b']' * 20000
    path.write_bytes(raw)
    assert cli.main(['--manifest', str(path), '--evidence-dir', str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {'status': 'INVALID_INPUT', 'error': 'RecursionError'}


def test_cli_rejects_symlink_artifact(tmp_path):
    target = tmp_path / 'original.json'
    target.write_bytes(RAW)
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='regular evidence file'):
        cli._read(link, 1000)


def test_import_boundaries_are_file_only_and_have_no_runtime_wiring():
    allowed = {'__future__', 'datetime', 'enum', 'hashlib', 're', 'typing', 'uuid',
               'pydantic', 'argparse', 'json', 'pathlib', 'sys', 'sentinel.live_readiness'}
    for module in (readiness, cli):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed


def test_subject_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(readiness.inventory)
    needle = 'if reference.subject != manifest.subject:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'subject-guard-falsifier', 'exec'),
         readiness.__dict__, namespace)
    monkeypatch.setattr(readiness, 'inventory', namespace['inventory'])
    with pytest.raises(AssertionError):
        test_runtime_economic_policy_and_account_identity_drift_refuses('source_sha256', digest('different source'))


def test_original_clock_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(readiness.inventory)
    needle = 'if not reference.observed_at <= now < reference.expires_at:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'clock-guard-falsifier', 'exec'),
         readiness.__dict__, namespace)
    monkeypatch.setattr(readiness, 'inventory', namespace['inventory'])
    with pytest.raises(AssertionError):
        test_future_expired_and_boundary_expired_evidence_is_retained_as_rejected(
            NOW + timedelta(microseconds=1), NOW + timedelta(hours=1))


def test_artifact_integrity_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(readiness.inventory)
    needle = 'hashlib.sha256(raw).hexdigest() == reference.artifact_sha256'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'artifact-guard-falsifier', 'exec'),
         readiness.__dict__, namespace)
    monkeypatch.setattr(readiness, 'inventory', namespace['inventory'])
    with pytest.raises(AssertionError):
        test_missing_empty_or_changed_artifact_never_gets_integrity_credit(RAW + b'altered')


def test_native_scope_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(readiness.inventory)
    needle = 'if reference.scope is not expected_scope:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'native-scope-falsifier', 'exec'),
         readiness.__dict__, namespace)
    monkeypatch.setattr(readiness, 'inventory', namespace['inventory'])
    with pytest.raises(AssertionError):
        test_paper_certificate_or_private_file_cannot_satisfy_native_gate(
            readiness.Scope.PAPER, readiness.Gate.LIVE_ACCOUNT_AUTHORITY)
