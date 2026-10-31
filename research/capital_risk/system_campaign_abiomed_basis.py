"""Validate the full actual inputs; append one independently typed sensor model."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_abiomed_input import SCHEMA, parse
from system_campaign_abiomed_facts import CONTRACT, evidence
import system_campaign_completion_basis as inherited


def validate(root, cp):
    from research.pooled_vacancy_funding import backtest
    need(cp['run']['input_sha256'] == backtest.input_hash(cp['base'], cp['repairs']),
         'ABIOMED_FULL_ACTUAL_INPUT_COMMITMENT')
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    found = []
    for descriptor in cp['repairs']:
        path = root / 'book/repairs' / descriptor['filename']
        raw = path.read_bytes()
        need(descriptor['filename'] == descriptor['sha256'] + '.json'
             and sha(raw) == descriptor['sha256'], 'ABIOMED_ALL_RETAINED_INPUT_BYTES')
        if json.loads(raw)['schema'] != SCHEMA:
            continue
        obj = parse(path, resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
                    expected_evidence=evidence(root), native_sha256=contract['native_term_sha256'])
        need(obj.sha256 == descriptor['sha256'], 'ABIOMED_EXACT_ADDITIONAL_DESCRIPTOR')
        found.append(obj)
    need(len(found) <= 1, 'ABIOMED_ONLY_ONE_ADDITIONAL_EVENT')
    return found


def original_semantic_visitor():
    """Classification-only recognition after full independent typed validation."""
    source_module = inherited.inherited.old
    raw = Path(source_module.__file__).read_bytes()
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    need(sha(raw) == contract['inherited_sources']['system_campaign_uncertainty_basis.py'],
         'ABIOMED_EXACT_INHERITED_SEMANTIC_VISITOR')
    function, = [node for node in ast.parse(raw).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'basis']
    loop, = [node for node in function.body if isinstance(node, ast.For)
             and ast.unparse(node.target) == 'descriptor']
    site, = [i for i, node in enumerate(loop.body) if isinstance(node, ast.Assign)
             and ast.unparse(node.targets[0]) == 'document']
    loop.body.insert(site + 1, ast.parse("if document['schema'] in ADDITIONAL_SCHEMAS: continue").body[0])
    schemas = {inherited.ZOGENIX_SCHEMA, inherited.SCHEMA, SCHEMA}
    namespace = dict(vars(source_module), ADDITIONAL_SCHEMAS=schemas)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<validated-third-sensor-semantic-classification>', 'exec'), namespace)
    return namespace['basis']


def basis(root, cp, *, amendment):
    models = validate(root, cp)
    if not models:
        return inherited.basis(root, cp, amendment=amendment)
    need(len(inherited.validate(root, cp)) == 1 and len(inherited.inherited.validate(root, cp)) == 1,
         'ABIOMED_EXACT_RETAINED_COMPLETION_AND_ZOGENIX_MODELS')
    # The old composition body is byte-for-byte unchanged. Only its semantic
    # visitor classifies the separately validated additional input schema.
    function = inherited.basis
    need(function.__closure__ is None, 'ABIOMED_NO_HIDDEN_BASIS_CLOSURE')
    prior_basis = FunctionType(function.__code__,
                              dict(function.__globals__, inherited_visitor=original_semantic_visitor),
                              function.__name__, function.__defaults__)
    prior_basis.__kwdefaults__ = function.__kwdefaults__
    need(prior_basis.__code__ is function.__code__, 'ABIOMED_UNCHANGED_PRIOR_COMPOSITION_CODE')
    _, prior = prior_basis(root, cp, amendment=amendment)
    model = models[0].model_dump(by_alias=True)
    model.pop('predecessor_checkpoint_sha256')
    value = dict(schema='research.system-campaign-common-three-sensor-completion-basis/1',
        factual_semantics_sha256=prior['factual_semantics_sha256'],
        factual_semantics=deepcopy(prior['factual_semantics']),
        model_semantics=[*deepcopy(prior['model_semantics']), model],
        price_or_probability_estimate_selected=False, independent_uncertainty_assumption=False)
    return digest(value), value
