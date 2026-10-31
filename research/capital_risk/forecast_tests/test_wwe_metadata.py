"""Factual and dispatch guards only; no canonical or financial execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import system_campaign_wwe_facts as facts
import system_campaign_registry_extension as registry
import system_campaign_six_model_preflight as six

HERE = Path(facts.__file__).parent


def catalog():
    return json.loads((HERE / facts.CATALOG).read_bytes())


def test_exact_primary_common_terms_preserve_separate_dividend_and_frozen_identity():
    value = catalog(); before = deepcopy(value)
    assert facts.validate(value) is value and value == before
    assert value['terms'][0]['added']['exchange_ratio'] == 1.0
    assert value['terms'][0]['added']['cash_per_share'] is None
    assert value['separate_dividend']['new_dividend_or_merger_cash_added'] is False


@pytest.mark.parametrize('change', ['ratio', 'cash', 'date', 'security', 'issuer', 'dividend'])
def test_changed_economics_clock_or_identity_refuses(change):
    value = catalog(); term = value['terms'][0]
    if change == 'ratio': term['added']['exchange_ratio'] = 2.0
    elif change == 'cash': term['added']['cash_per_share'] = 3.86
    elif change == 'date': term['added']['session'] = '2023-09-13'
    elif change == 'security': term['added']['delivered_security_id'] = '123'
    elif change == 'issuer': term['added']['delivered_issuer_id'] = 'SEC_CIK:1973266'
    else: value['separate_dividend']['new_dividend_or_merger_cash_added'] = True
    with pytest.raises(ValueError): facts.validate(value)


def test_actual_factual_ratio_guard_removal_falsifier():
    value = catalog(); value['terms'][0]['added']['exchange_ratio'] = 2.0
    fn, = [n for n in ast.parse(Path(facts.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'validate']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant)
                      and a.value == 'WWE_EXACT_COMMON_SHARE_RATIO_CLOCK_AND_FROZEN_DELIVERY_IDENTITY'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(facts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-WWE-ratio-guard-removal>', 'exec'), namespace)
    with pytest.raises(ValueError): facts.validate(value)
    assert namespace['validate'](value) is value


def registry_root(tmp_path):
    for name in (registry.FILE, registry.original.REGISTRY):
        (tmp_path / name).write_bytes((HERE / name).read_bytes())
    return tmp_path


def test_registry_adds_one_group_and_does_not_rewrite_existing_groups(tmp_path):
    root = registry_root(tmp_path)
    old = registry.original.registrations(root)
    obj = registry.RegistryExtension(root)
    all_groups = obj.registrations(root)
    assert all_groups[:-1] == old and all_groups[-1] == catalog()['commitment_group']
    assert registry.original.registrations(root) == old


def test_changed_base_registry_or_unsafe_new_file_refuses(tmp_path):
    root = registry_root(tmp_path)
    raw = (root / registry.original.REGISTRY).read_bytes()
    (root / registry.original.REGISTRY).write_bytes(raw + b' ')
    with pytest.raises(ValueError): registry.RegistryExtension(root)
    (root / registry.original.REGISTRY).write_bytes(raw)
    value = json.loads((root / registry.FILE).read_bytes())
    value['groups'][0]['private_file'] = '../escape.json'
    (root / registry.FILE).write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ValueError): registry.RegistryExtension(root)


def test_actual_six_schema_admission_guard_removal_falsifier(tmp_path, monkeypatch):
    all_schemas = six.prior.MODELS | {six.CHINOOK, six.OUTCOME}
    missing = {k: '1'*64 for k in all_schemas if k != six.OUTCOME}
    # This tests only the schema dispatch guard. Actual typed validation is
    # separately mandatory in the hosted run; no financial parser is called.
    monkeypatch.setattr(six, 'validate_all', lambda root, cp: (missing, {'suppress': [], 'add': []}))
    with pytest.raises(ValueError, match='ALL_ACTUAL_TYPED_INPUTS_VALIDATED'):
        six.SixModelPreflight({}, tmp_path)
    cls, = [n for n in ast.parse(Path(six.__file__).read_bytes()).body
            if isinstance(n, ast.ClassDef) and n.name == 'SixModelPreflight']
    fn, = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SIX_MODEL_ALL_ACTUAL_TYPED_INPUTS_VALIDATED'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(six))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-six-schema-guard-removal>', 'exec'), namespace)
    probe = SimpleNamespace()
    namespace['__init__'](probe, {}, tmp_path)
    assert probe.models == missing
