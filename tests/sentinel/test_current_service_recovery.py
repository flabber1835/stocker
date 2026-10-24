"""All-hour process ownership and positive order-evidence falsifiers.

The real-session composition is owned by the finite manual registry, not this
complete all-hour CI owner. No runtime or native authority is substituted here.
"""
from __future__ import annotations

import ast
import inspect
import os

import pytest

from tests.support.current_service_faults import assert_owned_worker


def _require_final_order_witness(ordinary_sequences, exact_sequences):
    """Positive canonical evidence is required; its lookup route is incidental."""
    sequences = set(ordinary_sequences) | set(exact_sequences)
    assert sequences, 'final positive order witness is missing from both canonical routes'
    return sequences


@pytest.mark.parametrize('ordinary,exact', [([3], []), ([], [3]), ([3], [4])])
def test_final_order_witness_accepts_either_existing_canonical_route(ordinary, exact):
    assert _require_final_order_witness(ordinary, exact) == set(ordinary) | set(exact)


def test_final_order_witness_refuses_missing_both_routes():
    with pytest.raises(AssertionError, match='missing from both'):
        _require_final_order_witness([], [])


def test_final_order_witness_falsifier_observes_removed_positive_evidence_guard(monkeypatch):
    test_final_order_witness_refuses_missing_both_routes()
    tree = ast.parse(inspect.getsource(_require_final_order_witness))
    function = tree.body[0]
    guards = [node for node in function.body if isinstance(node, ast.Assert)]
    assert len(guards) == 1
    function.body.remove(guards[0])
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<final-order-evidence-mutant>', 'exec'), namespace)
    monkeypatch.setitem(globals(), '_require_final_order_witness', namespace['_require_final_order_witness'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_final_order_witness_refuses_missing_both_routes()


@pytest.mark.parametrize('changed', [
    {'pid': 1}, {'parent_pid': 1}, {'state': 'Z'}, {'state': 'X'},
    {'start_ticks': 0}, {'start_ticks': 2},
])
def test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed):
    parent = os.getpid()
    child = parent + 1000000
    material = {'pid': child, 'parent_pid': parent, 'state': 'S', 'start_ticks': 1}
    assert_owned_worker(material, expected_parent_pid=parent, expected_pid=child, expected_start_ticks=1)
    if 'parent_pid' in changed:
        # pytest is PID 1 in the isolated test image. A literal 1 is therefore
        # not necessarily a mismatched parent; derive a different identity.
        changed = {**changed, 'parent_pid': parent + 1}
    with pytest.raises(AssertionError):
        assert_owned_worker({**material, **changed}, expected_parent_pid=parent, expected_pid=child,
            expected_start_ticks=1)


def test_private_worker_signal_owner_refuses_test_process():
    own = os.getpid()
    with pytest.raises(AssertionError):
        assert_owned_worker({'pid': own, 'parent_pid': own, 'state': 'S', 'start_ticks': 1},
            expected_parent_pid=own, expected_pid=own, expected_start_ticks=1)


@pytest.mark.parametrize('boundary,changed', [
    ("identity['parent_pid'] == expected_parent_pid", {'parent_pid': 1}),
    ("identity['start_ticks'] == expected_start_ticks", {'start_ticks': 2}),
])
def test_private_worker_signal_ownership_falsifier_observes_removed_boundary(
        monkeypatch, boundary, changed):
    """The same public refusal assertion must fail with each guard removed.

    Mutate only an in-memory copied function. Never rewrite source or replace
    production process supervision while the composed campaign is running.
    """
    original = assert_owned_worker
    test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed)
    tree = ast.parse(inspect.getsource(original))
    function = tree.body[0]
    matches = [node for node in function.body if isinstance(node, ast.Assert)
        and ast.unparse(node.test) == boundary]
    assert len(matches) == 1, 'the exact owned-signal boundary must exist'
    function.body.remove(matches[0])
    namespace = {'os': os}
    exec(compile(ast.fix_missing_locations(tree), '<owned-signal-boundary-mutant>', 'exec'), namespace)
    monkeypatch.setitem(globals(), 'assert_owned_worker', namespace['assert_owned_worker'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed)
