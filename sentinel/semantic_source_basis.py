"""Deterministic economic contributions for reviewed administrative seams."""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import importlib
import json
from pathlib import Path

BASIS_PATH = Path(__file__).with_name('semantic-source-basis.json')
# Populated from the reviewed baseline by the generation tool, never at runtime.
BASIS_SHA256 = '73ab1b931d0b264a124972fd356448b28e5920a87e2efb5b23b87a61c1d77f84'

HOOKS = {
    'sentinel.rolling_checkpoint': ('restore_observer', '''from sentinel.runtime_admission import bind_context
context = dict(observation_id=observation_id, starting_cash=starting_cash, controller=controller, strategy=strategy, runtime=runtime)
bind_context(conn, context)
runtime = context['runtime']'''),
    'sentinel.rolling_daily_checkpoint': ('load', '''from sentinel.runtime_admission import bind_context
bind_context(conn, context)'''),
}
RECIPE = '''from sentinel.semantic_source_basis import economic_sources
return economic_sources(_DATA_SEMANTICS_MODULES, schema=DATA_SEMANTICS_IDENTITY_SCHEMA)'''
RECIPE_HEADER = 'def data_semantics_source_identity() -> dict[str, object]: pass'


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _ast_value(value):
    # Empty type_params was added to AST records in Python 3.12. It carries no
    # semantics, unlike a nonempty parameter list. Keep CI's 3.8 scanner and the
    # certified interpreter on the same deterministic representation.
    if isinstance(value, ast.AST):
        return [type(value).__name__, [[name, _ast_value(item)] for name, item in ast.iter_fields(value)
                                      if not (name == 'type_params' and item == [])]]
    if isinstance(value, list):
        return [_ast_value(item) for item in value]
    if value is Ellipsis or isinstance(value, (bytes, complex)):
        return [type(value).__name__, repr(value)]
    return value


def basis():
    raw = BASIS_PATH.read_bytes()
    if _sha(raw) != BASIS_SHA256:
        raise RuntimeError('economic source baseline changed')
    return json.loads(raw)


def _masked_ast_uncached(module, raw, *, baseline=False, _configuration=None):
    tree = ast.parse(raw)
    if module == 'sentinel.core.decision':
        recipe = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'data_semantics_source_identity')
        expected = ast.parse(RECIPE_HEADER if _configuration is None else _configuration[1]).body[0]
        header = lambda node: _ast_value([[name, value] for name, value in ast.iter_fields(node)
                                         if name != 'body' and not (name == 'type_params' and value == [])])
        if header(recipe) != header(expected):
            return None
        body = recipe.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if not baseline and ast.dump(ast.Module(body=body, type_ignores=[])) != ast.dump(
                ast.parse(RECIPE if _configuration is None else _configuration[0])):
            return None
        tree.body.remove(recipe)
    elif (module in HOOKS if _configuration is None else _configuration[2]) and not baseline:
        function, text = HOOKS[module] if _configuration is None else _configuration[3]
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == function)
        offset = int(isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant))
        hook = ast.parse(text).body
        if ast.dump(ast.Module(body=node.body[offset:offset+len(hook)], type_ignores=[])) != ast.dump(ast.parse(text)):
            return None
        del node.body[offset:offset+len(hook)]
    return _sha(json.dumps(_ast_value(tree), separators=(',', ':'), ensure_ascii=True).encode())


@lru_cache(maxsize=32)
def _masked_ast_calculation(module, raw, baseline, recipe, header, hook_present, hook):
    return _masked_ast_uncached(module, raw, baseline=baseline,
                                _configuration=(recipe, header, hook_present, hook))


def masked_ast(module, raw, *, baseline=False):
    """Remove only the exact admitted hook, never an economic function body."""
    # Retain only immutable calculation inputs/results. Unusual inputs keep the
    # original parser/configuration behavior, including its exception order.
    if (type(module) is not str or type(raw) not in (bytes, str)
            or type(baseline) is not bool or type(RECIPE) is not str
            or type(RECIPE_HEADER) is not str or type(HOOKS) is not dict):
        return _masked_ast_uncached(module, raw, baseline=baseline)
    hook_present = module in HOOKS
    hook = HOOKS[module] if hook_present else None
    if hook_present and (type(hook) is not tuple or len(hook) != 2
                         or any(type(item) is not str for item in hook)):
        return _masked_ast_uncached(module, raw, baseline=baseline)
    return _masked_ast_calculation(module, raw, baseline, RECIPE, RECIPE_HEADER,
                                   hook_present, hook)


def canonical_contribution(module, raw):
    actual = _sha(raw)
    known = basis()['seams'].get(module)
    if known and masked_ast(module, raw) == known['remaining_ast_sha256']:
        return known['source_sha256']
    return actual


def economic_sources(modules, *, schema):
    files, observed = [], []
    for name in modules:
        module = importlib.import_module(name)
        raw = Path(module.__file__).resolve().read_bytes()
        actual = _sha(raw)
        contribution = canonical_contribution(name, raw) if name in (*HOOKS, 'sentinel.core.decision') else actual
        if name == 'sentinel.feed.rolling_publisher':
            from sentinel.worker_notification_source_basis import contribution as publisher_contribution
            from sentinel.corpus_writer_source_basis import normalize_reviewed_source
            contribution = publisher_contribution(normalize_reviewed_source(raw))
        files.append({'module': name, 'sha256': contribution})
        if contribution != actual:
            observed.append({'module': name, 'actual_sha256': actual, 'economic_sha256': contribution})
    payload = {'schema': schema, 'files': files}
    digest = _sha(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode())
    return {**payload, 'sha256': digest,
            'administrative_source_basis': {'schema': 'sentinel.economic-source-basis/1',
                'basis_sha256': BASIS_SHA256, 'observed_seams': observed}}
