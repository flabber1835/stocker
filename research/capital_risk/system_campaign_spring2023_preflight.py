"""Ordinary collision checks after full validation of all four retained models."""
import ast
from collections import Counter
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest, sha
import system_campaign_action_preflight as ordinary

HERE = Path(__file__).resolve().parent
ALDER = 'research.leadership-uncertainty-input/1'
ZOGENIX = 'research.zogenix-leadership-uncertainty-input/1'
COMPLETION = 'research.guarded-completion-observation-input/1'
ABIOMED = 'research.abiomed-leadership-uncertainty-input/1'
MODELS = frozenset((ALDER, ZOGENIX, COMPLETION, ABIOMED))
ORDINARY = 'terminal-repair/1'


def binding(cp):
    return digest(cp)


def documents(root, cp):
    """Read and bind every real descriptor; never construct a projected CP."""
    need(cp['run']['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs'])),
         'SPRING2023_FULL_ACTUAL_INPUT_COMMITMENT')
    found = []
    for d in cp['repairs']:
        need(d['filename'] == d['sha256'] + '.json' and len(d['sha256']) == 64
             and all(c in '0123456789abcdef' for c in d['sha256']),
             'SPRING2023_EXACT_ORIGINAL_DESCRIPTOR_FILENAME')
        raw = (Path(root) / 'book/repairs' / d['filename']).read_bytes()
        need(sha(raw) == d['sha256'], 'SPRING2023_EVERY_ORIGINAL_DESCRIPTOR_BYTES')
        value = json.loads(raw)
        need(value['schema'] in MODELS | {ORDINARY}, 'SPRING2023_NO_UNDECLARED_SCHEMA')
        found.append((d, value))
    counts = Counter(v['schema'] for _, v in found)
    need(all(counts[s] == 1 for s in MODELS)
         and len({d['sha256'] for d, _ in found}) == len(found),
         'SPRING2023_EXACTLY_FOUR_DISTINCT_RETAINED_MODELS')
    return found


def validate_models(root, cp):
    # Original parsers verify each model's actual own predecessor, source/input
    # references and private payload. No descriptor is removed for any parser.
    original = documents(root, cp)
    from system_campaign_uncertainty_review import validate_input_commitment
    from system_campaign_zogenix_basis import validate as validate_zogenix
    from system_campaign_completion_basis import validate as validate_completion
    from system_campaign_abiomed_basis import validate as validate_abiomed
    alder = validate_input_commitment(root, cp)
    zogenix, = validate_zogenix(root, cp)
    completion, = validate_completion(root, cp)
    abiomed, = validate_abiomed(root, cp)
    hashes = {ALDER: alder, ZOGENIX: zogenix.sha256,
              COMPLETION: completion.sha256, ABIOMED: abiomed.sha256}
    need({v['schema']: d['sha256'] for d, v in original if v['schema'] in MODELS} == hashes,
         'SPRING2023_FOUR_ORIGINAL_PARSERS_MATCH_ALL_ACTUAL_DESCRIPTORS')
    # Includes ALL ordinary additions/suppressions carried by the guarded input,
    # rather than just its two unowned conditional-completion securities.
    body = completion.canonical_repair
    need(body['schema'] == ORDINARY, 'SPRING2023_VALIDATED_GUARDED_CANONICAL_BODY')
    return hashes, body


def compile_visitor(raw):
    contract = json.loads((HERE / 'system-campaign-completion-scope-contract.json').read_bytes())
    need(sha(raw) == contract['inherited_sources']['system_campaign_action_preflight.py'],
         'SPRING2023_EXACT_ORIGINAL_ORDINARY_VISITOR_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'analyze_new_catalog']
    loop, = [n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == 'descriptor']
    index, = [i for i, n in enumerate(loop.body) if isinstance(n, ast.Assign)
               and ast.unparse(n.targets[0]) == 'document']
    loop.body.insert(index + 1, ast.parse("if document['schema'] in VALIDATED_ADDITIONAL_SCHEMAS: continue").body[0])
    namespace = dict(vars(ordinary), VALIDATED_ADDITIONAL_SCHEMAS=MODELS - {ALDER})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<fully-validated-four-model-ordinary-collision-visitor>', 'exec'), namespace)
    return namespace['analyze_new_catalog']


def extra_collisions(catalog, guarded_body, model_ids):
    all_keys = {(v['session'], v['security_id']) for field in ('suppress', 'add')
                for v in guarded_body[field]}
    conflicts = []
    for t in catalog['terms']:
        sid = t['security_id']
        if sid in model_ids or t['added']['security_id'] in model_ids:
            conflicts.append(dict(ticker=t['ticker'], reason='VALIDATED_MODEL_IDENTITY_OVERLAP', security_id=sid))
        for field, key in (('suppress', (t['native_session'], sid)),
                           ('add', (t['added']['session'], t['added']['security_id']))):
            if key in all_keys:
                conflicts.append(dict(ticker=t['ticker'], reason='GUARDED_CANONICAL_BODY_KEY_ALREADY_PRESENT',
                                      field=field, session=key[0], security_id=key[1]))
    return conflicts


class FourModelCalendarPreflight:
    def __init__(self, cp, root):
        self.root = Path(root).resolve()
        self.binding = binding(cp)
        self.models, self.body = validate_models(self.root, cp)
        self.model_ids = {'941065113449292610', '732226698577723721', '1050970006012443443'} | {
            v['security_id'] for field in ('suppress', 'add') for v in self.body[field]}
        self.visit = compile_visitor(Path(ordinary.__file__).read_bytes())

    def analyze(self, cp, root, catalog):
        need(binding(cp) == self.binding and Path(root).resolve() == self.root,
             'SPRING2023_EXACT_FULL_VALIDATED_CHECKPOINT_AND_ROOT')
        # Recheck bytes at use time; an already validated model file must not be
        # replaceable between admission and ordinary collision classification.
        documents(self.root, cp)
        result = self.visit(cp, root, catalog)
        extra = extra_collisions(catalog, self.body, self.model_ids)
        need(not extra, 'SPRING2023_ALL_VALIDATED_MODEL_AND_GUARDED_BODY_KEYS_DISJOINT')
        result.update(validated_nonordinary_input_sha256=self.models,
                      guarded_canonical_keys_checked=sum(len(self.body[k]) for k in ('suppress', 'add')),
                      full_actual_input_commitment_verified=True,
                      descriptor_or_financial_checkpoint_projection=False)
        return result

    def __enter__(self):
        import system_campaign_cash_calendar as cash
        need(cash.analyze_new_catalog is ordinary.analyze_new_catalog,
             'SPRING2023_EXPECTED_ORIGINAL_CASH_VISITOR')
        self.cash, self.original = cash, cash.analyze_new_catalog
        cash.analyze_new_catalog = self.analyze
        return self

    def __exit__(self, *args):
        self.cash.analyze_new_catalog = self.original
