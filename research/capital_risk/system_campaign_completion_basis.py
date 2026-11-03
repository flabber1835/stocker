"""Full real input validation and explicit guarded numerical/model semantics."""
import ast
from copy import deepcopy
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_completion_scope import SCHEMA, SCOPE, parse
from system_campaign_completion_facts import contract, evidence, expected_repair, CATALOG, HERE
import system_campaign_zogenix_basis as inherited
from system_campaign_zogenix_input import SCHEMA as ZOGENIX_SCHEMA


def validate(root, cp):
    from research.pooled_vacancy_funding import backtest
    need(cp['run']['input_sha256'] == backtest.input_hash(cp['base'], cp['repairs']),
         'COMPLETION_BASIS_ACTUAL_FULL_INPUT_COMMITMENT')
    found = []
    for descriptor in cp['repairs']:
        path = root / 'book/repairs' / descriptor['filename']; raw = path.read_bytes()
        need(descriptor['filename'] == descriptor['sha256'] + '.json'
             and sha(raw) == descriptor['sha256'], 'COMPLETION_BASIS_ALL_ACTUAL_INPUT_BYTES')
        if json.loads(raw)['schema'] != SCHEMA:
            continue
        obj = parse(path, resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
                    expected_repair=expected_repair(root, descriptor['predecessor_checkpoint_sha256']),
                    expected_evidence=evidence(root))
        need(obj.sha256 == descriptor['sha256'], 'COMPLETION_BASIS_EXACT_TYPED_DESCRIPTOR')
        found.append(obj)
    need(len(found) <= 1, 'COMPLETION_BASIS_ONLY_ONE_ADDITIONAL_SCOPE')
    return found


def inherited_visitor():
    """Only schema classification changes in a hash-bound semantic visitor."""
    c = contract(); raw = Path(inherited.old.__file__).read_bytes()
    need(sha(raw) == c['inherited_sources']['system_campaign_uncertainty_basis.py'],
         'COMPLETION_BASIS_EXACT_INHERITED_VISITOR')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'basis']
    loop, = [n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == 'descriptor']
    site, = [i for i, n in enumerate(loop.body)
             if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'document']
    loop.body.insert(site + 1, ast.parse("if document['schema'] in ADDITIONAL_SCHEMAS: continue").body[0])
    namespace = dict(vars(inherited.old), ADDITIONAL_SCHEMAS={ZOGENIX_SCHEMA, SCHEMA})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<validated-guarded-completion-semantic-visitor>', 'exec'), namespace)
    return namespace['basis']


def merge_semantics(prior, body, commitments):
    value = deepcopy(prior)
    for key in ('suppress', 'add'):
        terms = {(v['session'], v['security_id']): v for v in value[key]}
        need(len(terms) == len(value[key]), 'COMPLETION_BASIS_ORIGINAL_UNIQUE_SEMANTICS')
        for term in body[key]:
            identity = term['session'], term['security_id']
            need(identity not in terms, 'COMPLETION_BASIS_NO_DUPLICATE_OR_CONFLICTING_NEW_EVENT')
            terms[identity] = deepcopy(term)
        value[key] = [terms[k] for k in sorted(terms)]
    refs = value['declared_fact_compilers']
    need(not set(refs) & set(commitments), 'COMPLETION_BASIS_NO_REDEFINED_COMPILER')
    refs.update(commitments)
    return value


def basis(root, cp, *, amendment):
    models = validate(root, cp)
    if not models:
        return inherited.basis(root, cp, amendment=amendment)
    zogenix, = inherited.validate(root, cp)
    _, prior = inherited_visitor()(root, cp, amendment=amendment)
    obj, = models
    refs = {v['reference']: v['sha256'] for v in evidence(root)}
    catalog = json.loads((HERE / CATALOG).read_bytes()); stem = catalog['commitment_group']['reference_stem']
    ordinary = [v for v in obj.canonical_repair['source_evidence'] if v['reference'].startswith(stem)]
    need(len(ordinary) == 3 and {v['reference'] for v in ordinary} ==
         {stem + k for k in ('catalog', 'loader', 'private')}, 'COMPLETION_BASIS_THREE_ORDINARY_COMMITMENTS')
    refs.update({v['reference']: v['sha256'] for v in ordinary})
    factual = merge_semantics(prior['factual_semantics'], obj.canonical_repair, refs)
    zmodel = zogenix.model_dump(by_alias=True); zmodel.pop('predecessor_checkpoint_sha256')
    c = contract()
    scope = dict(schema=SCHEMA, scope=SCOPE, require_unowned_and_unordered=True,
                 morning_settlement_claimed=False, source_evidence=evidence(root),
                 events=[{k: e[k] for k in ('security_id', 'native_session', 'session',
                     'filing_accepted_utc', 'following_open_new_york', 'primary_source')}
                         for e in c['scoped_events']])
    value = dict(schema='research.system-campaign-common-guarded-completion-basis/1',
                 factual_semantics_sha256=digest(factual), factual_semantics=factual,
                 model_semantics=[deepcopy(prior['model_semantics']), zmodel, scope],
                 price_or_probability_estimate_selected=False,
                 independent_uncertainty_assumption=False)
    return digest(value), value
