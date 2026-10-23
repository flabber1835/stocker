"""Closed scheduling compatibility preserves the full signed economic strategy."""
import hashlib
import inspect
from pathlib import Path

import pytest

from sentinel import corpus_writer_source_basis as basis
from sentinel import semantic_source_basis as semantics
from sentinel import worker_notification_source_basis as diagnostics

EXPECTED_STRATEGY_SHA256 = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'


@pytest.fixture
def sources():
    from sentinel.feed import rolling_publisher
    current = Path(rolling_publisher.__file__).read_bytes()
    assert hashlib.sha256(current).hexdigest() == basis.REVIEWED_SHA256
    baseline = basis.normalize_reviewed_source(current)
    assert hashlib.sha256(baseline).hexdigest() == basis.BASE_SHA256
    return baseline, current


def test_exact_installed_source_and_complete_remaining_ast(sources):
    baseline, current = sources
    assert basis.BASE_REVISION == '131cc833923610d095492ca6b6890eadfbe8e163'
    assert basis.BASE_SHA256 == diagnostics.REVIEWED_SHA256
    assert basis.normalize_reviewed_source(baseline) is baseline
    assert basis.remaining_ast_sha256(baseline, baseline=True) == basis.BASE_AST_SHA256
    assert basis.remaining_ast_sha256(current) == basis.BASE_AST_SHA256
    assert diagnostics.contribution(basis.normalize_reviewed_source(current)) == diagnostics.BASE_SHA256
    assert diagnostics.remaining_ast_sha256(baseline) == diagnostics.BASE_AST_SHA256


@pytest.mark.parametrize('before,after', [
    (b'lease_seconds=600', b'lease_seconds=599'),
    (b'if not ready:', b'if False:'),
    (b'boundary.publish(conn, lease, request, producer=producer)',
     b'boundary.publish(conn, lease, request, producer={})'),
    (b'notices.capture_stage(exc, operation_stage)',
     b'notices.capture_stage(None, operation_stage)'),
    (b'writer_schedule.turn(conn, lease)', b'writer_schedule.turn(conn, None)'),
    (b'discard_connection = False', b'discard_connection = True'),
    (b'writer_schedule.connection_discarded(exc)', b'writer_schedule.connection_discarded(None)'),
    (b'not discard_connection and not conn.closed', b'not discard_connection or not conn.closed'),
    (b'from sentinel.feed import writer_schedule', b'from sentinel.feed import writer_schedule as other'),
])
def test_unknown_economics_diagnostics_and_scheduling_bytes_keep_actual_source(sources, before, after):
    _baseline, current = sources
    assert before in current
    changed = current.replace(before, after, 1)
    normalized = basis.normalize_reviewed_source(changed)
    assert normalized is changed
    assert diagnostics.contribution(normalized) == hashlib.sha256(changed).hexdigest()
    assert diagnostics.contribution(normalized) != diagnostics.BASE_SHA256
    try:
        remaining = basis.remaining_ast_sha256(changed)
    except ValueError:
        pass
    else:
        assert remaining != basis.BASE_AST_SHA256


def test_comments_missing_wrappers_and_other_unknown_bytes_are_not_normalized(sources):
    _baseline, current = sources
    changes = (
        current + b'\n# unknown scheduling bytes\n',
        current.replace(b'writer_schedule.turn(conn, lease), ', b'', 1),
        current.replace(b'from sentinel.feed import writer_schedule\n', b'', 1),
    )
    for changed in changes:
        assert basis.normalize_reviewed_source(changed) is changed
        assert diagnostics.contribution(changed) == hashlib.sha256(changed).hexdigest()
        assert diagnostics.contribution(changed) != diagnostics.BASE_SHA256


@pytest.mark.parametrize('extra', [
    b'\nwriter_schedule.turn(conn, lease)\n',
    b'\ndiscard_connection = False\n',
])
def test_no_scheduling_reference_outside_prepare_is_hidden(sources, extra):
    _baseline, current = sources
    changed = current + extra
    with pytest.raises(ValueError, match='unreviewed publisher scheduling reference'):
        basis.remaining_ast_sha256(changed)
    assert basis.normalize_reviewed_source(changed) is changed


def test_closed_normalizer_guard_has_behavioral_falsifier(sources, monkeypatch):
    source = inspect.getsource(basis.normalize_reviewed_source)
    needle = 'if hashlib.sha256(raw).hexdigest() != REVIEWED_SHA256:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'unrestricted-scheduling-normalizer', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'normalize_reviewed_source', namespace['normalize_reviewed_source'])
    with pytest.raises((AssertionError, ValueError)):
        test_comments_missing_wrappers_and_other_unknown_bytes_are_not_normalized(sources)


def test_scheduling_contribution_composes_with_original_diagnostic_mapping(sources):
    _baseline, current = sources
    value = semantics.economic_sources([basis.MODULE], schema='scheduling-source-pair-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': diagnostics.BASE_SHA256}]
    assert {'module': basis.MODULE, 'actual_sha256': hashlib.sha256(current).hexdigest(),
            'economic_sha256': diagnostics.BASE_SHA256} in value['administrative_source_basis']['observed_seams']


def test_unknown_source_in_real_semantic_bundle_remains_unknown(sources, monkeypatch):
    from sentinel.feed import rolling_publisher
    _baseline, current = sources
    publisher_path = Path(rolling_publisher.__file__)
    changed = current + b'\n# real semantic bundle unknown bytes\n'
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: changed
                        if path == publisher_path else original_read(path))
    value = semantics.economic_sources([basis.MODULE], schema='scheduling-source-pair-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': hashlib.sha256(changed).hexdigest()}]
    assert value['administrative_source_basis']['observed_seams'] == []


def test_real_production_strategy_matches_current_signed_policy():
    from sentinel.strategy import production_strategy
    from sentinel.feed.rolling_contract import digest
    _controller, strategy = production_strategy()
    assert digest(strategy) == EXPECTED_STRATEGY_SHA256


def test_real_strategy_detects_missing_scheduling_normalizer(monkeypatch):
    monkeypatch.setattr(basis, 'normalize_reviewed_source', lambda raw: raw)
    with pytest.raises(AssertionError):
        test_real_production_strategy_matches_current_signed_policy()


def test_real_strategy_still_detects_missing_original_diagnostic_mapping(monkeypatch):
    monkeypatch.setattr(diagnostics, 'contribution', lambda raw: hashlib.sha256(raw).hexdigest())
    with pytest.raises(AssertionError):
        test_real_production_strategy_matches_current_signed_policy()
