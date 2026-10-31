"""Full seven-input admission and exact guarded closing-fact semantics."""
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_close_scope import SCHEMA, SCOPE, parse
from system_campaign_close_facts import contract, evidence, expected_repair
from system_campaign_completion_basis import merge_semantics
import system_campaign_outcome_basis as previous
import system_campaign_six_model_preflight as six


def sources():
    value = contract()
    need(sha(Path(previous.__file__).read_bytes())
         == value['inherited_sources']['system_campaign_outcome_basis.py'],
         'CLOSE_BASIS_EXACT_ADOPTED_SIX_MODEL_COMPOSITION')
    return value


def documents(root, cp):
    sources()
    present = []
    for descriptor in cp['repairs']:
        need(descriptor['filename'] == descriptor['sha256'] + '.json'
             and len(descriptor['sha256']) == 64
             and all(v in '0123456789abcdef' for v in descriptor['sha256']),
             'CLOSE_BASIS_EXACT_DESCRIPTOR_FILENAME_BEFORE_READ')
        raw = (Path(root) / 'book/repairs' / descriptor['filename']).read_bytes()
        need(sha(raw) == descriptor['sha256'],
             'CLOSE_BASIS_EVERY_ACTUAL_DESCRIPTOR_BYTES')
        if json.loads(raw)['schema'] == SCHEMA: present.append(descriptor)
    need(len(present) <= 1, 'CLOSE_BASIS_ONLY_ONE_CLOSING_SCOPE')
    fn = previous.previous.original_preflight.documents
    need(fn.__closure__ is None, 'CLOSE_BASIS_ORIGINAL_FULL_DESCRIPTOR_VALIDATION')
    models = previous.previous.original_preflight.MODELS | {previous.previous.SCHEMA, previous.SCHEMA}
    if present: models |= {SCHEMA}
    checked = FunctionType(fn.__code__, dict(fn.__globals__, MODELS=models), fn.__name__, fn.__defaults__)
    return checked(root, cp)


def validate(root, cp):
    need(cp['run']['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs'])),
         'CLOSE_BASIS_FULL_ACTUAL_INPUT_COMMITMENT')
    found = []
    for descriptor, value in documents(root, cp):
        if value['schema'] != SCHEMA: continue
        obj = parse(Path(root) / 'book/repairs' / descriptor['filename'],
            resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
            expected_repair=expected_repair(root, descriptor['predecessor_checkpoint_sha256']),
            expected_evidence=evidence(root))
        need(obj.sha256 == descriptor['sha256'], 'CLOSE_BASIS_EXACT_TYPED_CLOSING_DESCRIPTOR')
        found.append(obj)
    return found


def validate_all(root, cp):
    actual = documents(root, cp)
    fn = previous.previous.original_preflight.validate_models
    need(fn.__closure__ is None, 'CLOSE_BASIS_UNCHANGED_ORIGINAL_FOUR_PARSERS')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, documents=documents), fn.__name__, fn.__defaults__)
    first, body = checked(root, cp)
    chinook, = previous.previous.validate(root, cp)
    outcome, _ = previous.retained(root, cp)
    need(outcome is not None, 'CLOSE_BASIS_RETAINED_COMPLETE_OUTCOME_PROOF_REQUIRED')
    expected = {**first, previous.previous.SCHEMA: chinook.sha256, previous.SCHEMA: outcome.sha256}
    closing = validate(root, cp)
    if closing: expected[SCHEMA] = closing[0].sha256
    typed = {value['schema']: descriptor['sha256'] for descriptor, value in actual
             if value['schema'] != 'terminal-repair/1'}
    need(typed == expected, 'CLOSE_BASIS_ALL_ACTUAL_SIX_OR_SEVEN_TYPED_PARSERS_MATCH')
    return expected, body


def semantic_visitor():
    sources()
    fn = previous.original_semantic_visitor()
    need(fn.__closure__ is None and 'ADDITIONAL_SCHEMAS' in fn.__globals__,
         'CLOSE_BASIS_ONE_EXPLICIT_VALIDATED_SCHEMA_CLASSIFICATION')
    checked = FunctionType(fn.__code__, dict(fn.__globals__,
        ADDITIONAL_SCHEMAS=set(fn.__globals__['ADDITIONAL_SCHEMAS']) | {SCHEMA}), fn.__name__, fn.__defaults__)
    checked.__kwdefaults__ = fn.__kwdefaults__
    return checked


def common_scope(root):
    value = contract();event = value['event']
    return dict(schema=SCHEMA, scope=SCOPE, require_unowned_and_unordered=True,
        require_no_entry_intents=True, morning_settlement_claimed=False, source_evidence=evidence(root),
        event={k: event[k] for k in ('security_id', 'native_session', 'session',
            'tender_expiration_new_york', 'filing_accepted_new_york', 'close_new_york', 'primary_source')})


def append_semantics(before, obj, refs, scope):
    value = deepcopy(before)
    value['schema'] = 'research.system-campaign-common-guarded-close-basis/1'
    value['factual_semantics'] = merge_semantics(before['factual_semantics'], obj.canonical_repair, refs)
    value['factual_semantics_sha256'] = digest(value['factual_semantics'])
    value['model_semantics'].append(deepcopy(scope))
    return value


def basis(root, cp, *, amendment):
    models = validate(root, cp)
    if not models: return previous.basis(root, cp, amendment=amendment)
    validate_all(root, cp)
    fn = previous.basis
    need(fn.__closure__ is None, 'CLOSE_BASIS_UNCHANGED_PRIOR_COMPOSITION_BODY')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, validate_all=validate_all,
        original_semantic_visitor=semantic_visitor), fn.__name__, fn.__defaults__)
    checked.__kwdefaults__ = fn.__kwdefaults__
    _, old = checked(root, cp, amendment=amendment)
    obj, = models
    value = append_semantics(old, obj, {v['reference']: v['sha256'] for v in evidence(root)}, common_scope(root))
    return digest(value), value


def require_exact_delta(before, after, obj, root):
    expected = append_semantics(before, obj,
        {v['reference']: v['sha256'] for v in evidence(root)}, common_scope(root))
    need(after == expected, 'CLOSE_BASIS_ONLY_NEW_CLOSING_FACT_AND_SCOPE_ALL_SIX_PRIOR_MODELS_UNCHANGED')
    return True


class SevenModelPreflight:
    """Future ordinary inputs must validate the full seventh guarded input too."""
    def __init__(self, cp, root):
        self.root = Path(root).resolve();self.binding = digest(cp)
        self.models, self.body = validate_all(self.root, cp)
        self.close, = validate(self.root, cp)
        need(set(self.models) == six.prior.MODELS | {six.CHINOOK, six.OUTCOME, SCHEMA},
             'CLOSE_PREFLIGHT_ALL_SEVEN_ACTUAL_INPUTS_REQUIRED')
        self.model_ids = {'941065113449292610', '732226698577723721',
            '1050970006012443443', '47247117758471252', '533554648046407798'}
        for body in (self.body, self.close.canonical_repair):
            self.model_ids.update(v['security_id'] for k in ('suppress', 'add') for v in body[k])
        fn = six.prior.compile_visitor(Path(six.prior.ordinary.__file__).read_bytes())
        self.visit = FunctionType(fn.__code__, dict(fn.__globals__,
            VALIDATED_ADDITIONAL_SCHEMAS=(six.prior.MODELS - {six.prior.ALDER}) | {six.CHINOOK, six.OUTCOME, SCHEMA}),
            fn.__name__, fn.__defaults__)

    def analyze(self, cp, root, catalog):
        need(digest(cp) == self.binding and Path(root).resolve() == self.root,
             'CLOSE_PREFLIGHT_EXACT_FULL_VALIDATED_CHECKPOINT_AND_ROOT')
        documents(self.root, cp)
        value = self.visit(cp, root, catalog)
        extra = [item for body in (self.body, self.close.canonical_repair)
                 for item in six.prior.extra_collisions(catalog, body, self.model_ids)]
        need(not extra, 'CLOSE_PREFLIGHT_ALL_TYPED_AND_BOTH_GUARDED_KEY_SETS_DISJOINT')
        value.update(validated_nonordinary_input_sha256=self.models,
            guarded_canonical_keys_checked=sum(len(v[k]) for v in (self.body, self.close.canonical_repair)
                                               for k in ('suppress', 'add')),
            full_actual_input_commitment_verified=True, descriptor_or_financial_checkpoint_projection=False)
        return value
