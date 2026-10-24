"""The fixed economic pipeline is an exact extraction, not a source wildcard."""
import ast
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

import pytest

from sentinel import publisher_pipeline_source_basis as basis
from sentinel import semantic_source_basis as semantics
from sentinel.feed import publisher_pipeline as pipeline, rolling_publisher as lifecycle
from tests.support.publisher_source_proofs import publisher_baseline

EXPECTED_STRATEGY = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'
HELPERS = ('ComparisonRefused', '_operational_source', '_latest', '_legacy_version',
           'published', 'freeze', 'publish', '_checkpoint')


def _definition(tree, name):
    return next(node for node in tree.body if getattr(node, 'name', None) == name)


def _dump(value):
    return ast.dump(value, include_attributes=False)


def _restore_contexts_and_observations(body):
    class Restore(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == 'observer' and call.func.attr == 'stage'):
                assert len(call.args) == 1 and not call.keywords
                return ast.Assign(targets=[ast.Name(id='operation_stage', ctx=ast.Store())],
                                  value=call.args[0])
            return self.generic_visit(node)

        def visit_With(self, node):
            self.generic_visit(node)
            if len(node.items) != 1:
                return node
            call = node.items[0].context_expr
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == 'observer'):
                return node
            assert node.items[0].optional_vars is None
            if call.func.attr == 'acquisition':
                assert not call.args and not call.keywords
                old = 'with writer_schedule.turn(conn, lease), store.acquisition_write_lock(conn):\n    pass'
            else:
                assert _dump(call) == _dump(ast.parse('observer.publication(phase, job_id)').body[0].value)
                old = ('with progress.phase(phase, job_id=job_id), writer_schedule.turn(conn, lease), '
                       'store.corpus_write_lock(conn):\n    pass')
            node.items = ast.parse(old).body[0].items
            return node
    return Restore().visit(ast.Module(body=deepcopy(body), type_ignores=[]))


def _assert_complete_pipeline(baseline_raw, pipeline_raw):
    old, new = ast.parse(baseline_raw), ast.parse(pipeline_raw)
    for name in HELPERS:
        assert _dump(_definition(old, name)) == _dump(_definition(new, name)), name
    original = _definition(old, '_prepare')
    original_try = next(node for node in original.body if isinstance(node, ast.Try))
    run = _definition(new, 'run')
    assert ast.get_docstring(run) == 'Run the fixed pipeline under an already claimed owned job.'
    assert _dump(run.body[1]) == _dump(ast.parse('from sentinel.feed import operational_snapshot').body[0])
    assert _dump(_restore_contexts_and_observations(run.body[2:])) == _dump(
        ast.Module(body=original_try.body, type_ignores=[]))
    # No other economic function can appear outside the exactly compared set.
    assert {n.name for n in new.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} == {
        *HELPERS, 'Observer', 'run'}


def test_complete_economic_pipeline_ast_matches_independent_installed_git_witness():
    _assert_complete_pipeline(publisher_baseline(), Path(pipeline.__file__).read_bytes())


@pytest.mark.parametrize('before,after', [
    (b'if not ready:', b'if False:'),
    (b'boundary.publish(conn, lease, request, producer=producer)',
     b'boundary.publish(conn, lease, request, producer={})'),
    (b'rolling_builder.build(conn, lease, request, source)',
     b'rolling_builder.build(conn, lease, request, None)'),
    (b'source.corroborate()', b'source.preflight()'),
    (b'with observer.acquisition():', b'with observer.publication(phase, job_id):'),
    (b'if _legacy_version(conn) != request.expected_publication_version:', b'if False:'),
])
def test_economic_neighbor_edits_fail_full_ast_and_contribute_actual_hash(before, after):
    current = Path(pipeline.__file__).read_bytes()
    assert before in current
    changed = current.replace(before, after, 1)
    assert basis.contribution(changed) == hashlib.sha256(changed).hexdigest()
    assert basis.contribution(changed) != basis.BASE_SHA256
    with pytest.raises(AssertionError):
        _assert_complete_pipeline(publisher_baseline(), changed)


def test_lifecycle_retains_original_failure_and_cleanup_ast():
    old = ast.parse(publisher_baseline())
    new = ast.parse(Path(lifecycle.__file__).read_bytes())
    for name in ('prepare', '_record_failure'):
        assert _dump(_definition(old, name)) == _dump(_definition(new, name))
    old_prepare = _definition(old, '_prepare')
    new_prepare = _definition(new, '_prepare')
    old_try = next(n for n in old_prepare.body if isinstance(n, ast.Try))
    new_try = next(n for n in new_prepare.body if isinstance(n, ast.Try))
    # Only stage storage moved from a local variable to the observer.
    handlers = deepcopy(new_try.handlers)
    for node in ast.walk(handlers[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'capture_stage'):
            node.args[1] = ast.Name(id='operation_stage', ctx=ast.Load())
    assert _dump(ast.Module(body=handlers, type_ignores=[])) == _dump(
        ast.Module(body=old_try.handlers, type_ignores=[]))
    assert _dump(ast.Module(body=new_try.finalbody, type_ignores=[])) == _dump(
        ast.Module(body=old_try.finalbody, type_ignores=[]))
    assert _dump(new_try.body[0].value) == _dump(ast.parse(
        'publisher_pipeline.run(conn, job_id, operational=operational, '
        'boundary=boundary, lease=lease, observer=observer)').body[0].value)
    restored = deepcopy(new_prepare)
    observer_initialization = ast.parse('observer = PublicationObserver(conn, lease)').body[0]
    replacements = [index for index, node in enumerate(restored.body)
                    if _dump(node) == _dump(observer_initialization)]
    assert len(replacements) == 1
    restored.body[replacements[0]] = ast.parse("operation_stage = 'SHADOW_ADVANCE'").body[0]
    restored_try = next(n for n in restored.body if isinstance(n, ast.Try))
    restored_try.body = deepcopy(old_try.body)
    restored_try.handlers = handlers
    assert _dump(restored) == _dump(old_prepare)


def test_current_logical_slot_uses_fixed_pipeline_bytes():
    raw = Path(pipeline.__file__).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == basis.PIPELINE_SHA256
    value = semantics.economic_sources([basis.MODULE], schema='pipeline-boundary-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': basis.BASE_SHA256}]
    assert {'module': basis.MODULE, 'actual_sha256': basis.PIPELINE_SHA256,
            'economic_sha256': basis.BASE_SHA256} in value['administrative_source_basis']['observed_seams']


def test_unknown_pipeline_bytes_reach_real_economic_bundle(monkeypatch):
    path = Path(pipeline.__file__).resolve()
    original = Path.read_bytes
    changed = original(path) + b'\n# unknown economic bytes\n'
    monkeypatch.setattr(Path, 'read_bytes', lambda p: changed if p == path else original(p))
    value = semantics.economic_sources([basis.MODULE], schema='pipeline-boundary-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': hashlib.sha256(changed).hexdigest()}]


def test_economic_identity_matches_current_signed_strategy():
    from sentinel.strategy import production_strategy
    from sentinel.feed.rolling_contract import digest
    assert digest(production_strategy()[1]) == EXPECTED_STRATEGY


def test_closed_pipeline_mapping_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.contribution)
    needle = 'actual == PIPELINE_SHA256'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'unclosed-pipeline', 'exec'), basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'contribution', namespace['contribution'])
    with pytest.raises(AssertionError):
        test_economic_neighbor_edits_fail_full_ast_and_contribute_actual_hash(
            b'if not ready:', b'if False:')
