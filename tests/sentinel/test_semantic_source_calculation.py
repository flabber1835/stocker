"""Pure AST reuse never retains source, baseline or identity authority."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import semantic_source_basis as basis


DECISION = b'''def data_semantics_source_identity() -> dict[str, object]:
    """Identity recipe."""
    from sentinel.semantic_source_basis import economic_sources
    return economic_sources(_DATA_SEMANTICS_MODULES, schema=DATA_SEMANTICS_IDENTITY_SCHEMA)

def economic_guard(value):
    return value + 1
'''
SEAM = b'''def target():
    x = 1
    return 2

def other():
    x = 1
    return 3
'''


@pytest.fixture(autouse=True)
def empty_calculation_cache():
    calculation = basis._masked_ast_calculation
    calculation.cache_clear()
    yield
    calculation.cache_clear()


def original_masked_ast(module, raw, *, baseline=False):
    """The pre-cache calculation, including its original global reads."""
    tree = ast.parse(raw)
    if module == 'sentinel.core.decision':
        recipe = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'data_semantics_source_identity')
        expected = ast.parse(basis.RECIPE_HEADER).body[0]
        header = lambda node: basis._ast_value([[name, value] for name, value in ast.iter_fields(node)
                                               if name != 'body' and not (name == 'type_params' and value == [])])
        if header(recipe) != header(expected):
            return None
        body = recipe.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if not baseline and ast.dump(ast.Module(body=body, type_ignores=[])) != ast.dump(ast.parse(basis.RECIPE)):
            return None
        tree.body.remove(recipe)
    elif module in basis.HOOKS and not baseline:
        function, text = basis.HOOKS[module]
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == function)
        offset = int(isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant))
        hook = ast.parse(text).body
        if ast.dump(ast.Module(body=node.body[offset:offset+len(hook)], type_ignores=[])) != ast.dump(ast.parse(text)):
            return None
        del node.body[offset:offset+len(hook)]
    return hashlib.sha256(json.dumps(basis._ast_value(tree), separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


@pytest.mark.parametrize('module', [*basis.HOOKS, 'sentinel.core.decision'])
@pytest.mark.parametrize('baseline', [False, True])
def test_real_sources_keep_exact_uncached_digest_and_none(module, baseline):
    import importlib
    raw = Path(importlib.import_module(module).__file__).read_bytes()
    expected = original_masked_ast(module, raw, baseline=baseline)
    assert basis.masked_ast(module, raw, baseline=baseline) == expected
    assert basis.masked_ast(module, raw.decode(), baseline=baseline) == expected


def _assert_warm_reuse(monkeypatch, *, invalid=False):
    calls = []
    parse = ast.parse
    monkeypatch.setattr(basis.ast, 'parse', lambda *a, **k: (calls.append(a[0]), parse(*a, **k))[1])
    raw = DECISION.replace(b'return economic_sources(', b'return changed(') if invalid else DECISION
    expected = basis.masked_ast('sentinel.core.decision', raw)
    assert (expected is None) == invalid
    count = len(calls)
    assert count > 0
    for _ in range(3):
        assert basis.masked_ast('sentinel.core.decision', raw) == expected
    assert len(calls) == count


@pytest.mark.parametrize('invalid', [False, True])
def test_warm_calculation_reuses_digest_or_nonmatching_none(monkeypatch, invalid):
    _assert_warm_reuse(monkeypatch, invalid=invalid)


def _assert_key_change(monkeypatch, component):
    module, raw, baseline = 'sentinel.core.decision', DECISION, False
    if component in {'baseline', 'hook_function', 'hook_text'}:
        module, raw = 'selected', SEAM
        monkeypatch.setattr(basis, 'HOOKS', {'selected': ('target', 'x = 1')})
    if component == 'module':
        module = 'ordinary'
    first = basis.masked_ast(module, raw, baseline=baseline)
    if component == 'raw':
        raw = raw.replace(b'return value + 1', b'return value + 2')
    elif component == 'module':
        module = 'sentinel.core.decision'
    elif component == 'baseline':
        baseline = True
    elif component == 'recipe':
        monkeypatch.setattr(basis, 'RECIPE', 'return {}')
    elif component == 'header':
        monkeypatch.setattr(basis, 'RECIPE_HEADER', 'def data_semantics_source_identity() -> changed: pass')
    elif component == 'hook_function':
        monkeypatch.setattr(basis, 'HOOKS', {'selected': ('other', 'x = 1')})
    elif component == 'hook_text':
        monkeypatch.setattr(basis, 'HOOKS', {'selected': ('target', 'x = 2')})
    expected = original_masked_ast(module, raw, baseline=baseline)
    assert expected != first
    assert basis.masked_ast(module, raw, baseline=baseline) == expected


@pytest.mark.parametrize('component', ['raw', 'module', 'baseline', 'recipe', 'header',
                                        'hook_function', 'hook_text'])
def test_every_fresh_calculation_input_invalidates(monkeypatch, component):
    _assert_key_change(monkeypatch, component)


def test_hook_presence_is_explicit_and_unrelated_hook_changes_do_not_miss(monkeypatch):
    monkeypatch.setattr(basis, 'HOOKS', {'selected': ('target', 'x = 1')})
    first = basis.masked_ast('selected', SEAM)
    before = basis._masked_ast_calculation.cache_info()
    monkeypatch.setitem(basis.HOOKS, 'unrelated', ('other', 'x = 2'))
    assert basis.masked_ast('selected', SEAM) == first
    assert basis._masked_ast_calculation.cache_info().hits == before.hits + 1
    monkeypatch.delitem(basis.HOOKS, 'selected')
    assert basis.masked_ast('selected', SEAM) == original_masked_ast('selected', SEAM)
    assert basis.masked_ast('selected', SEAM) != first


def test_bound_is_32_entries_and_eviction_recomputes(monkeypatch):
    calls = []
    parse = ast.parse
    monkeypatch.setattr(basis.ast, 'parse', lambda *a, **k: (calls.append(a[0]), parse(*a, **k))[1])
    expected = basis.masked_ast('ordinary', b'x = 0')
    for i in range(1, 33):
        basis.masked_ast('ordinary', ('x = %s' % i).encode())
    assert basis._masked_ast_calculation.cache_info().currsize == 32
    assert basis.masked_ast('ordinary', b'x = 0') == expected
    assert len(calls) == 34


@pytest.mark.parametrize('raw', [b'def broken(', b'x = 1'])
def test_exceptions_are_never_cached(monkeypatch, raw):
    calls = []
    parse = ast.parse
    monkeypatch.setattr(basis.ast, 'parse', lambda *a, **k: (calls.append(a[0]), parse(*a, **k))[1])
    expected = SyntaxError if raw.startswith(b'def') else StopIteration
    for _ in range(2):
        with pytest.raises(expected):
            basis.masked_ast('sentinel.core.decision', raw)
    assert len(calls) == 2
    assert basis._masked_ast_calculation.cache_info().currsize == 0


@pytest.mark.parametrize('hook', [None, [], ['target', 'x = 1'], ('target', []), ('missing', 'x = 1')])
def test_unusual_hook_configuration_keeps_original_value_or_exception(monkeypatch, hook):
    monkeypatch.setattr(basis, 'HOOKS', {'selected': hook})
    for _ in range(2):
        try:
            expected = original_masked_ast('selected', SEAM)
        except Exception as exc:
            with pytest.raises(type(exc), match='^' + __import__('re').escape(str(exc)) + '$'):
                basis.masked_ast('selected', SEAM)
        else:
            assert basis.masked_ast('selected', SEAM) == expected
    assert basis._masked_ast_calculation.cache_info().currsize == 0


def test_unhashable_source_and_configuration_take_original_uncached_path(monkeypatch):
    monkeypatch.setattr(basis, 'HOOKS', {'selected': ['target', 'x = 1']})
    raw = bytearray(SEAM)
    assert basis.masked_ast('selected', raw) == original_masked_ast('selected', raw)
    assert basis.masked_ast('selected', raw, baseline=[]) == original_masked_ast('selected', raw, baseline=[])
    assert basis._masked_ast_calculation.cache_info().currsize == 0
    # Malformed configuration must not hide an earlier source parser failure.
    monkeypatch.setattr(basis, 'RECIPE', [])
    monkeypatch.setattr(basis, 'HOOKS', None)
    with pytest.raises(SyntaxError):
        basis.masked_ast('selected', b'def broken(')


def test_empty_python312_type_params_keep_python38_representation():
    node = ast.parse('def example(): return 1').body[0]
    before = basis._ast_value(node)
    node.type_params = []
    assert basis._ast_value(node) == before
    if 'type_params' in node._fields:
        node.type_params = [ast.Name(id='Changed', ctx=ast.Load())]
        assert basis._ast_value(node) != before


@pytest.fixture
def economic_fixture(monkeypatch, tmp_path):
    module, raw = 'selected', SEAM + b'# old\n'
    monkeypatch.setattr(basis, 'HOOKS', {module: ('target', 'x = 1')})
    source = tmp_path/'source.py'
    source.write_bytes(raw)
    path = tmp_path/'basis.json'
    content = {'seams': {module: {'remaining_ast_sha256': original_masked_ast(module, raw),
                                 'source_sha256': '1' * 64}}}
    path.write_text(json.dumps(content))
    monkeypatch.setattr(basis, 'BASIS_PATH', path)
    monkeypatch.setattr(basis, 'BASIS_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(basis, 'importlib', SimpleNamespace(import_module=lambda name: SimpleNamespace(__file__=str(source))))
    return module, source, path


def test_economic_sources_reads_sources_and_basis_each_call_and_keeps_output(monkeypatch, economic_fixture):
    module, source, path = economic_fixture
    reads = []
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda p: (reads.append(p), read_bytes(p))[1])
    first = basis.economic_sources([module], schema='fixture')
    again = basis.economic_sources([module], schema='fixture')
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert reads.count(source) == reads.count(path) == 2
    # Recalculate through the unchanged body to compare all identity bytes.
    monkeypatch.setattr(basis, '_masked_ast_calculation', lambda module, raw, baseline, *configuration:
                        basis._masked_ast_uncached(module, raw, baseline=baseline,
                                                   _configuration=configuration))
    assert json.dumps(basis.economic_sources([module], schema='fixture'), sort_keys=True) == json.dumps(first, sort_keys=True)


def test_same_size_source_changes_are_observed_after_warm_cache(economic_fixture):
    module, source, _ = economic_fixture
    first = basis.economic_sources([module], schema='fixture')
    raw = source.read_bytes()
    source.write_bytes(raw.replace(b'# old', b'# new'))
    comments = basis.economic_sources([module], schema='fixture')
    assert comments['sha256'] == first['sha256']
    assert comments['administrative_source_basis'] != first['administrative_source_basis']
    source.write_bytes(raw.replace(b'return 2', b'return 4'))
    changed = basis.economic_sources([module], schema='fixture')
    assert changed['sha256'] != first['sha256']
    assert changed['files'][0]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize('change', ['bytes', 'pin', 'invalid_json'])
def test_warm_calculation_never_hides_changed_basis(monkeypatch, economic_fixture, change):
    module, _, path = economic_fixture
    basis.economic_sources([module], schema='fixture')
    if change == 'bytes':
        path.write_bytes(path.read_bytes() + b' ')
    elif change == 'pin':
        monkeypatch.setattr(basis, 'BASIS_SHA256', '0' * 64)
    else:
        path.write_bytes(b'{')
        monkeypatch.setattr(basis, 'BASIS_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(json.JSONDecodeError if change == 'invalid_json' else RuntimeError):
        basis.economic_sources([module], schema='fixture')


@pytest.mark.parametrize('component,index', [('raw', 1), ('module', 0), ('baseline', 2),
    ('recipe', 3), ('header', 4), ('hook_function', 6), ('hook_text', 6)])
def test_private_key_falsifier_detects_omitted_input(monkeypatch, component, index):
    original = basis._masked_ast_calculation
    first_value = {}

    def omitted(*args):
        key = args[:index] + args[index+1:]
        if key not in first_value:
            first_value[key] = original(*args)
        return first_value[key]

    monkeypatch.setattr(basis, '_masked_ast_calculation', omitted)
    with pytest.raises(AssertionError):
        _assert_key_change(monkeypatch, component)


def test_private_no_reuse_falsifier_detects_repeated_parse(monkeypatch):
    source = inspect.getsource(basis.masked_ast)
    source = source.replace('return _masked_ast_calculation(', 'return _masked_ast_calculation.__wrapped__(')
    local = {}
    exec(compile(source, '<private-no-ast-reuse>', 'exec'), basis.__dict__, local)
    monkeypatch.setattr(basis, 'masked_ast', local['masked_ast'])
    with pytest.raises(AssertionError):
        _assert_warm_reuse(monkeypatch)
