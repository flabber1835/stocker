"""Six typed inputs on the complete checkpoint, with unchanged event semantics."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_outcome_facts import CONTRACT, common_semantics, document, retained
from system_campaign_outcome_input import SCHEMA
import system_campaign_chinook_basis as previous


def require_sources():
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name, expected in contract['inherited_sources'].items():
        need(sha((Path(__file__).parent / name).read_bytes()) == expected,
             'OUTCOME_ALL_ADOPTED_EVENT_AND_SEMANTIC_SOURCES_UNCHANGED')


def documents(root, cp):
    require_sources()
    models = previous.original_preflight.MODELS | {previous.SCHEMA}
    if document(root, cp):
        models |= {SCHEMA}
    function = previous.original_preflight.documents
    need(function.__closure__ is None, 'OUTCOME_ORIGINAL_DESCRIPTOR_CHECKS_WITHOUT_CLOSURE')
    checked = FunctionType(function.__code__, dict(function.__globals__, MODELS=models),
                           function.__name__, function.__defaults__)
    return checked(root, cp)


def validate_all(root, cp):
    actual = documents(root, cp)
    function = previous.original_preflight.validate_models
    need(function.__closure__ is None, 'OUTCOME_ORIGINAL_FOUR_PARSERS_WITHOUT_CLOSURE')
    checked = FunctionType(function.__code__, dict(function.__globals__, documents=documents),
                           function.__name__, function.__defaults__)
    first, body = checked(root, cp)
    chinook, = previous.validate(root, cp)
    model, _ = retained(root, cp)
    expected = {**first, previous.SCHEMA: chinook.sha256}
    if model is not None:
        expected[SCHEMA] = model.sha256
    typed = {value['schema']: descriptor['sha256'] for descriptor, value in actual
             if value['schema'] != 'terminal-repair/1'}
    need(typed == expected, 'OUTCOME_ALL_SIX_ORIGINAL_TYPED_PARSERS_MATCH_FULL_INPUT_SET')
    return expected, body


def original_semantic_visitor():
    source = previous.inherited.inherited.inherited.old
    raw = Path(source.__file__).read_bytes()
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    need(sha(raw) == contract['inherited_sources']['system_campaign_uncertainty_basis.py'],
         'OUTCOME_EXACT_ORIGINAL_FACTUAL_SEMANTIC_VISITOR')
    function, = [node for node in ast.parse(raw).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'basis']
    loop, = [node for node in function.body if isinstance(node, ast.For)
             and ast.unparse(node.target) == 'descriptor']
    index, = [i for i, node in enumerate(loop.body) if isinstance(node, ast.Assign)
              and ast.unparse(node.targets[0]) == 'document']
    loop.body.insert(index + 1, ast.parse(
        "if document['schema'] in ADDITIONAL_SCHEMAS: continue").body[0])
    additional = (previous.original_preflight.MODELS - {previous.original_preflight.ALDER}) | {
        previous.SCHEMA, SCHEMA}
    namespace = dict(vars(source), ADDITIONAL_SCHEMAS=additional)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<six-fully-validated-model-semantic-visitor>', 'exec'), namespace)
    return namespace['basis']


def basis(root, cp, *, amendment):
    require_sources()
    validate_all(root, cp)
    model, _ = retained(root, cp)
    function = previous.basis
    need(function.__closure__ is None, 'OUTCOME_PRIOR_FIVE_MODEL_BODY_WITHOUT_CLOSURE')
    checked = FunctionType(function.__code__, dict(function.__globals__,
        validate_all=validate_all, original_semantic_visitor=original_semantic_visitor),
        function.__name__, function.__defaults__)
    checked.__kwdefaults__ = function.__kwdefaults__
    _, old = checked(root, cp, amendment=amendment)
    if model is None:
        return digest(old), old
    value = deepcopy(old)
    value['schema'] = 'research.system-campaign-common-controller-outcome-basis/1'
    value['model_semantics'].append(common_semantics(model))
    return digest(value), value


def require_exact_delta(before, after, model):
    expected = deepcopy(before)
    expected['schema'] = 'research.system-campaign-common-controller-outcome-basis/1'
    expected['model_semantics'].append(common_semantics(model))
    need(after == expected, 'OUTCOME_ONLY_PROOF_MODEL_ALL_FIVE_EVENT_SEMANTICS_UNCHANGED')
    return True
