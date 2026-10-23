"""Exact operational diagnostics cannot change the signed economic strategy."""
import ast
import hashlib
from pathlib import Path

import pytest

from sentinel import semantic_source_basis as semantics
from sentinel import worker_notification_source_basis as basis

EXPECTED_STRATEGY_SHA256 = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'


@pytest.fixture
def sources():
    from sentinel.feed import rolling_publisher
    current = Path(rolling_publisher.__file__).read_bytes()
    # Reconstruct the independently pinned Git-object witness by removing only
    # the exact twelve added source lines. Its byte hash must match that object.
    additions = {f"operation_stage = '{stage}'".encode() for stage in basis.STAGE_SEQUENCE}
    additions.update((basis.DIAGNOSTIC_IMPORT.encode(), basis.DIAGNOSTIC_CALL.encode()))
    baseline = b''.join(line for line in current.splitlines(keepends=True) if line.strip() not in additions)
    assert hashlib.sha256(current).hexdigest() == basis.REVIEWED_SHA256
    assert hashlib.sha256(baseline).hexdigest() == basis.BASE_SHA256
    return baseline, current


def test_exact_git_source_pair_and_complete_remaining_ast(sources):
    baseline, current = sources
    assert basis.BASE_REVISION == '596e8496bb0028498847f8e8a4afb26df3f786ba'
    assert basis.REVIEWED_REVISION == '49faad3aa8cbb815b26f5fad3fc85e57588943db'
    assert basis.contribution(baseline) == basis.BASE_SHA256
    assert basis.contribution(current) == basis.BASE_SHA256
    assert basis.remaining_ast_sha256(baseline, baseline=True) == basis.BASE_AST_SHA256
    assert basis.remaining_ast_sha256(current) == basis.BASE_AST_SHA256


@pytest.mark.parametrize('before,after', [
    (b'lease_seconds=600', b'lease_seconds=599'),
    (b'if not ready:', b'if False:'),
    (b'boundary.publish(conn, lease, request, producer=producer)', b'boundary.publish(conn, lease, request, producer={})'),
    (b'notices.capture_stage(exc, operation_stage)', b'notices.capture_stage(None, operation_stage)'),
    (b"operation_stage = 'PUBLICATION'", b"operation_stage = 'PRIVATE_STAGE'"),
    (b'from sentinel import shadow_dependency_notifications as notices', b'from sentinel import shadow_dependency_notifications as other'),
])
def test_neighbor_economics_hook_and_stage_mutations_use_actual_source(sources, before, after):
    _baseline, current = sources
    assert before in current
    changed = current.replace(before, after, 1)
    assert basis.contribution(changed) == hashlib.sha256(changed).hexdigest()
    assert basis.contribution(changed) != basis.BASE_SHA256
    try:
        remaining = basis.remaining_ast_sha256(changed)
    except ValueError:
        pass
    else:
        assert remaining != basis.BASE_AST_SHA256


def test_missing_diagnostics_and_unknown_comment_bytes_are_not_admitted(sources):
    _baseline, current = sources
    for changed in (current.replace(b'        notices.capture_stage(exc, operation_stage)\n', b'', 1),
                    current + b'\n# unreviewed source bytes\n',
                    current.replace(b"    operation_stage = 'SHADOW_ADVANCE'\n", b'', 1)):
        assert basis.contribution(changed) == hashlib.sha256(changed).hexdigest()
        assert basis.contribution(changed) != basis.BASE_SHA256
    with pytest.raises(ValueError, match='hook changed'):
        basis.remaining_ast_sha256(current.replace(b'        notices.capture_stage(exc, operation_stage)\n', b'', 1))


def test_no_diagnostic_outside_prepare_is_stripped(sources):
    _baseline, current = sources
    changed = current + b"\noperation_stage = 'SHADOW_ADVANCE'\n"
    with pytest.raises(ValueError, match='unreviewed publisher diagnostic reference'):
        basis.remaining_ast_sha256(changed)
    assert basis.contribution(changed) != basis.BASE_SHA256


def test_closed_mapping_guard_has_behavioral_falsifier(sources, monkeypatch):
    import inspect
    source = inspect.getsource(basis.contribution)
    needle = 'actual in {BASE_SHA256, REVIEWED_SHA256}'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'unrestricted-source-mapping', 'exec'), basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'contribution', namespace['contribution'])
    with pytest.raises(AssertionError):
        test_neighbor_economics_hook_and_stage_mutations_use_actual_source(
            sources, b'lease_seconds=600', b'lease_seconds=599')


def test_exact_publisher_contribution_flows_through_real_semantic_bundle(sources):
    _baseline, current = sources
    value = semantics.economic_sources([basis.MODULE], schema='source-pair-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': basis.BASE_SHA256}]
    assert {'module': basis.MODULE, 'actual_sha256': hashlib.sha256(current).hexdigest(),
            'economic_sha256': basis.BASE_SHA256} in value['administrative_source_basis']['observed_seams']


def test_real_production_strategy_still_matches_installed_signed_policy():
    from sentinel.strategy import production_strategy
    from sentinel.feed.rolling_contract import digest
    _controller, strategy = production_strategy()
    assert digest(strategy) == EXPECTED_STRATEGY_SHA256


def test_real_strategy_detects_missing_publisher_mapping(monkeypatch):
    monkeypatch.setattr(basis, 'contribution', lambda raw: hashlib.sha256(raw).hexdigest())
    with pytest.raises(AssertionError):
        test_real_production_strategy_still_matches_installed_signed_policy()
