"""Append one validated model without changing any prior composition body."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_chinook_input import SCHEMA, parse
from system_campaign_chinook_facts import CONTRACT, evidence
import system_campaign_abiomed_basis as inherited
import system_campaign_spring2023_preflight as original_preflight


def require_inherited_sources():
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name, expected in contract['inherited_sources'].items():
        need(sha((Path(__file__).parent / name).read_bytes()) == expected,
             'CHINOOK_ALL_ORIGINAL_COMPOSITION_SOURCES_UNCHANGED')


def documents(root, cp):
    """Identical original descriptor checks with the explicit fifth schema."""
    require_inherited_sources()
    fn = original_preflight.documents
    need(fn.__closure__ is None, 'CHINOOK_NO_HIDDEN_DOCUMENT_CLOSURE')
    checked = FunctionType(fn.__code__,
        dict(fn.__globals__, MODELS=original_preflight.MODELS | {SCHEMA}),
        fn.__name__, fn.__defaults__)
    need(checked.__code__ is fn.__code__, 'CHINOOK_UNCHANGED_ALL_DESCRIPTOR_CHECKS')
    return checked(root, cp)


def validate(root, cp):
    from research.pooled_vacancy_funding import backtest
    need(cp['run']['input_sha256'] == backtest.input_hash(cp['base'], cp['repairs']),
         'CHINOOK_FULL_ACTUAL_INPUT_COMMITMENT')
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    found = []
    for descriptor in cp['repairs']:
        path = root / 'book/repairs' / descriptor['filename']
        raw = path.read_bytes()
        need(descriptor['filename'] == descriptor['sha256'] + '.json'
             and sha(raw) == descriptor['sha256'], 'CHINOOK_ALL_RETAINED_INPUT_BYTES')
        if json.loads(raw)['schema'] != SCHEMA:
            continue
        obj = parse(path, resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
            expected_evidence=evidence(root), native_sha256=contract['native_term_sha256'])
        need(obj.sha256 == descriptor['sha256'], 'CHINOOK_EXACT_ADDITIONAL_DESCRIPTOR')
        found.append(obj)
    need(len(found) <= 1, 'CHINOOK_ONLY_ONE_ADDITIONAL_EVENT')
    return found


def validate_all(root, cp):
    actual = documents(root, cp)
    fn = original_preflight.validate_models
    need(fn.__closure__ is None, 'CHINOOK_NO_HIDDEN_ORIGINAL_PARSER_CLOSURE')
    old = FunctionType(fn.__code__, dict(fn.__globals__, documents=documents),
                       fn.__name__, fn.__defaults__)
    need(old.__code__ is fn.__code__, 'CHINOOK_UNCHANGED_FOUR_ORIGINAL_PARSERS')
    previous, body = old(root, cp)
    model, = validate(root, cp)
    expected = {**previous, SCHEMA: model.sha256}
    typed = {value['schema']: descriptor['sha256'] for descriptor, value in actual
             if value['schema'] != 'terminal-repair/1'}
    need(typed == expected, 'CHINOOK_ALL_FIVE_ORIGINAL_TYPED_PARSERS_MATCH')
    return expected, body


def original_semantic_visitor():
    source_module = inherited.inherited.inherited.old
    raw = Path(source_module.__file__).read_bytes()
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    need(sha(raw) == contract['inherited_sources']['system_campaign_uncertainty_basis.py'],
         'CHINOOK_EXACT_ORIGINAL_SEMANTIC_VISITOR')
    function, = [node for node in ast.parse(raw).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'basis']
    loop, = [node for node in function.body if isinstance(node, ast.For)
             and ast.unparse(node.target) == 'descriptor']
    site, = [i for i, node in enumerate(loop.body) if isinstance(node, ast.Assign)
             and ast.unparse(node.targets[0]) == 'document']
    loop.body.insert(site + 1, ast.parse(
        "if document['schema'] in ADDITIONAL_SCHEMAS: continue").body[0])
    schemas = (original_preflight.MODELS - {original_preflight.ALDER}) | {SCHEMA}
    namespace = dict(vars(source_module), ADDITIONAL_SCHEMAS=schemas)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<five-fully-validated-model-semantic-classification>', 'exec'), namespace)
    return namespace['basis']


def basis(root, cp, *, amendment):
    require_inherited_sources()
    models = validate(root, cp)
    if not models:
        original_preflight.validate_models(root, cp)
        return inherited.basis(root, cp, amendment=amendment)
    validate_all(root, cp)
    fn = inherited.basis
    need(fn.__closure__ is None, 'CHINOOK_NO_HIDDEN_PRIOR_COMPOSITION_CLOSURE')
    prior_basis = FunctionType(fn.__code__,
        dict(fn.__globals__, original_semantic_visitor=original_semantic_visitor),
        fn.__name__, fn.__defaults__)
    prior_basis.__kwdefaults__ = fn.__kwdefaults__
    need(prior_basis.__code__ is fn.__code__, 'CHINOOK_UNCHANGED_PRIOR_COMPOSITION_BODY')
    _, previous = prior_basis(root, cp, amendment=amendment)
    model = models[0].model_dump(by_alias=True)
    model.pop('predecessor_checkpoint_sha256')
    value = dict(schema='research.system-campaign-common-four-sensor-completion-basis/1',
        factual_semantics_sha256=previous['factual_semantics_sha256'],
        factual_semantics=deepcopy(previous['factual_semantics']),
        model_semantics=[*deepcopy(previous['model_semantics']), model],
        price_or_probability_estimate_selected=False, independent_uncertainty_assumption=False)
    return digest(value), value


def require_exact_delta(before, after, new_model):
    expected = deepcopy(before)
    expected['schema'] = 'research.system-campaign-common-four-sensor-completion-basis/1'
    expected['model_semantics'].append(deepcopy(new_model))
    need(after == expected, 'CHINOOK_ONLY_NEW_MODEL_ALL_PRIOR_SEMANTICS_UNCHANGED')
    return True
