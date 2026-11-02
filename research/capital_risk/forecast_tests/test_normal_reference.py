"""Pure receipt-format successors; no hosted admission or financial replay."""
from copy import deepcopy
import ast
from pathlib import Path

import pytest

from forecast_tests.test_content_reference import fixture
import system_campaign_content_reference as original
import system_campaign_normal_reference as module


@pytest.mark.parametrize('schema', sorted(module.RECEIPTS))
def test_declared_format_preserves_complete_actual_spec_and_all_other_fields(schema):
    old = fixture();new = deepcopy(old);new['receipt_schema'] = schema;before = deepcopy(new)
    actual = module.reference(new);expected = original.reference(old)
    assert new == before
    assert actual['parent_spec_sha256'] == module.digest(new)
    assert actual['parent_spec_sha256'] != expected['parent_spec_sha256']
    expected['parent_spec_sha256'] = actual['parent_spec_sha256']
    assert actual == expected
    with pytest.raises(ValueError): original.reference(new)


@pytest.mark.parametrize('change', ['schema', 'arm', 'unknown', 'review', 'archive'])
def test_other_safety_guards_remain_effective(change):
    spec = fixture();spec['receipt_schema'] = 'research.system-p02-wwe-suffix-receipt/1'
    if change == 'schema': spec['receipt_schema'] = 'UNDECLARED'
    elif change == 'arm': spec['arm'] = 'P03'
    elif change == 'unknown': spec['inspections']['economic-worker-inspect.json']['exit_code'] = None
    elif change == 'review': spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code'] = 1
    else: spec['private_content_archive']['all_unique_content_and_older_opaque_evidence_verified'] = False
    with pytest.raises(ValueError): module.reference(spec)


def test_actual_scope_guard_removal_falsifier(monkeypatch):
    spec = fixture();spec['receipt_schema'] = 'UNDECLARED'
    with pytest.raises(ValueError): module.reference(spec)
    monkeypatch.setattr(module, 'RECEIPTS', module.RECEIPTS | {'UNDECLARED'})
    assert module.reference(spec)['parent_spec_sha256'] == module.digest(spec)


def test_original_source_identity_is_required(monkeypatch):
    spec = fixture();spec['receipt_schema'] = 'research.system-p02-wwe-suffix-receipt/1'
    monkeypatch.setattr(module, 'SOURCE_SHA', '0'*64)
    with pytest.raises(ValueError): module.reference(spec)
    tree = ast.parse(Path(module.__file__).read_bytes())
    fn, = [v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == 'source_bytes']
    guard, = [v for v in fn.body if isinstance(v, ast.Expr) and isinstance(v.value, ast.Call)
              and isinstance(v.value.func, ast.Name) and v.value.func.id == 'need']
    fn.body.remove(guard)
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-normal-reference-source-guard-removal>', 'exec'), namespace)
    assert namespace['source_bytes']() == Path(original.__file__).read_bytes()
