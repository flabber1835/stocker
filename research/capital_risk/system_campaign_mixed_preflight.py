"""Read-only ordinary collision analysis alongside two strictly validated models."""
import ast
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest, sha
import system_campaign_action_preflight as ordinary
from system_campaign_uncertainty_review import validate_input_commitment
from system_campaign_zogenix_basis import validate as validate_zogenix
from system_campaign_zogenix_input import SCHEMA as ZSCHEMA, SID as ZSID


HERE = Path(__file__).resolve().parent
ALDER_SID = '941065113449292610'
EQUIVALENCE = 'system-campaign-p02-october-unadvanced-equivalence.json'


def verify_unchanged_attempt(root, spec, request):
    raw = (HERE / EQUIVALENCE).read_bytes()
    need(sha(raw) == request['prior_unadvanced_equivalence_sha256'],
         'MIXED_PREFLIGHT_AUTHENTICATED_FAILURE_RECORD_BYTES')
    proof = json.loads(raw)
    need(proof['status'] == 'EXACT_SAME_FINANCIAL_PARENT_NO_REPLAY_ENTRY'
         and proof['failed_run_id'] == 41161666450
         and proof['failed_head'] == '451223a43676be660497520fadf1bd6205bfa2eb'
         and proof['actual_worker_exit_code'] == proof['actual_reviewer_exit_code'] == 1
         and proof['all_108_inventory_members_authenticated'] is True
         and proof['actual_stopped_fences_verified'] is True
         and proof['financial_entry_not_reached'] is True and proof['new_model_not_adopted'] is True
         and proof['financial_parent_run_id'] == spec['run_id'] == 41151496224
         and proof['financial_parent_outer_sha256'] == spec['outer_sha256']
         and proof['financial_parent_session'] == spec['selected_session'] == '2022-09-30'
         and proof['measured_closes'] == 1196 and proof['retained_input_descriptors'] == 27,
         'MIXED_PREFLIGHT_EXACT_UNADVANCED_FINANCIAL_AUTHORITY')
    expected = proof['exact_unchanged_members']
    need(set(expected) == {'book/checkpoint.json.gz', 'book/identity.json', 'source-bindings.json',
                           *(f'book/{n}.jsonl' for n in ('formation', 'daily', 'monthly', 'watch'))}
         and expected['book/checkpoint.json.gz'] == spec['selected_file'],
         'MIXED_PREFLIGHT_COMPLETE_FINANCIAL_AND_UNSENT_TAIL_MEMBER_SET')
    for name, wanted in expected.items():
        count = 0; h = hashlib.sha256()
        with (root / name).open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk); h.update(chunk)
        need(dict(bytes=count, sha256=h.hexdigest()) == wanted,
             'MIXED_PREFLIGHT_ACTUAL_SOURCE_EQUALS_FAILED_FINANCIAL_PREFIX')
    return proof


def binding(cp):
    return digest(dict(outer=cp['sha256'], cursor=cp['source_cursor'], base=cp['base'],
                       repairs=cp['repairs'], input_sha256=cp['run']['input_sha256']))


def validate_models(root, cp):
    need(cp['run']['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs'])),
         'MIXED_PREFLIGHT_FULL_ACTUAL_INPUT_COMMITMENT')
    alder = validate_input_commitment(root, cp)
    zogenix, = validate_zogenix(root, cp)
    need(zogenix.security_id == ZSID and alder != zogenix.sha256,
         'MIXED_PREFLIGHT_TWO_DISTINCT_EXACT_MODEL_INPUTS')
    return [(alder, ALDER_SID), (zogenix.sha256, ZSID)]


def compile_visitor(raw):
    c = json.loads((HERE / 'system-campaign-completion-scope-contract.json').read_bytes())
    need(sha(raw) == c['inherited_sources']['system_campaign_action_preflight.py'],
         'MIXED_PREFLIGHT_EXACT_ORIGINAL_VISITOR_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'analyze_new_catalog']
    loop, = [n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == 'descriptor']
    site, = [i for i, n in enumerate(loop.body)
             if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'document']
    loop.body.insert(site + 1, ast.parse("if document['schema'] == VALIDATED_ADDITIONAL_SCHEMA: continue").body[0])
    namespace = dict(vars(ordinary), VALIDATED_ADDITIONAL_SCHEMA=ZSCHEMA)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<validated-retained-model-collision-visitor>', 'exec'), namespace)
    return namespace['analyze_new_catalog']


class MixedCalendarPreflight:
    def __init__(self, cp, root):
        self.binding = binding(cp)
        self.root = Path(root).resolve()
        self.models = validate_models(self.root, cp)
        self.visit = compile_visitor(Path(ordinary.__file__).read_bytes())

    def analyze(self, cp, root, catalog):
        need(binding(cp) == self.binding and Path(root).resolve() == self.root,
             'MIXED_PREFLIGHT_EXACT_VALIDATED_ACTUAL_CHECKPOINT_AND_ROOT')
        modeled = {sid for _, sid in self.models}
        need(all(t['security_id'] not in modeled and t['added']['security_id'] not in modeled
                 for t in catalog['terms']), 'MIXED_PREFLIGHT_NO_MODELED_SECURITY_OVERLAP')
        result = self.visit(cp, root, catalog)
        result.update(validated_nonordinary_input_sha256=[h for h, _ in self.models],
                      validated_modeled_security_ids=sorted(modeled),
                      full_actual_input_commitment_verified=True,
                      descriptor_or_financial_checkpoint_projection=False)
        return result

    def __enter__(self):
        import system_campaign_cash_calendar as cash
        need(cash.analyze_new_catalog is ordinary.analyze_new_catalog,
             'MIXED_PREFLIGHT_EXPECTED_ORIGINAL_CASH_VISITOR')
        self.cash = cash
        self.original = cash.analyze_new_catalog
        cash.analyze_new_catalog = self.analyze
        return self

    def __exit__(self, *args):
        self.cash.analyze_new_catalog = self.original
