"""One separately admitted parent with original failed and new passed reviews."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import FunctionType
import zipfile

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_financial_review_repair as quarantine

FLAG = 'root_requalified_failed_review_parent'
CATALOG = 'system-campaign-p07-requalified-review-transport.json'
CATALOG_SHA = '48b9993c84484b264fb2740692faa71c900a8f81ef7910c5b5aaaf747a06e7a2'
QUARANTINE_SHA = '485b3c13e3c911690efc3500e1e50cf778f8c3a50f14fe90609793bb9c9b32aa'
STATUS = 'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def applies(spec):
    return isinstance(spec, dict) and spec.get(FLAG) is True


def transport():
    raw = (Path(__file__).parent/CATALOG).read_bytes()
    need(sha(raw) == CATALOG_SHA, 'REQUALIFIED_EXACT_REVIEW_TRANSPORT_CATALOG')
    value = json.loads(raw)
    need((value['arm'], value['run_id'], value['head'], value['artifact_id'], value['zip_sha256']) ==
         ('P07', 42078149007, '554095dbe35cc76d114cc6b6fce20c63dd99a8d8', 13439737997,
          '3ef67ccbd507c56915e09a118f741a40b9d981ecded13d8d14dfedaf94941e49')
         and value['quarantine_target_sha256'] == QUARANTINE_SHA,
         'REQUALIFIED_ONLY_EXACT_SUCCESSFUL_REVIEW300')
    return value


def validated(spec):
    import system_campaign_financial_partial as partial
    need(applies(spec) and spec.get('qualified_review_transport_sha256') == CATALOG_SHA
         and quarantine.FLAG not in spec and 'root_admission' in spec, 'REQUALIFIED_SEPARATE_ADMITTED_ROOT_REQUIRED')
    partial.validate_root_spec(spec)
    target = {k:deepcopy(v) for k,v in spec.items() if k not in
              (FLAG, 'qualified_review_transport_sha256', 'root_admission', 'root_admission_sha256')}
    target[quarantine.FLAG] = True
    need(sha(encoded(target)) == QUARANTINE_SHA, 'REQUALIFIED_ORIGINAL_QUARANTINE_TARGET_UNCHANGED')
    quarantine.validate_target(target)
    review = transport()
    proof = spec['root_admission']['failed_review_requalification']
    need(proof['review_transport_sha256'] == CATALOG_SHA
         and proof['original_quarantine_target_sha256'] == QUARANTINE_SHA
         and proof['core_review_sha256'] == review['core_review_sha256']
         and proof['branch_review_sha256'] == review['branch_review_sha256']
         and proof['independent_validation_sha256'] == '3eb2e4182f5ff02d406d1477be44faedb0c7642c4ee9b21351a6e74ac1b21470'
         and proof['independent_review_sha256'] == 'dd1a0a1d5deb2fce3181baabecaab738d2c9ad00dacd7c8148b94de67201c533'
         and proof['original_failed_stops_preserved'] is True
         and type(proof['financial_transitions_reexecuted']) is int and proof['financial_transitions_reexecuted'] == 0,
         'REQUALIFIED_EXACT_SEPARATE_DATA_AND_ORIGINAL_REVIEW_AUTHORITY')
    return target, review


def accounting_review(spec):
    _, review = validated(spec)
    return 'stopped-review/core-review.json', review['core_review_sha256']


def public_names(spec, archive):
    import system_campaign_financial_partial as partial
    need(spec == transport(), 'REQUALIFIED_EXACT_PUBLIC_REVIEW_SCOPE')
    fn, = [n for n in ast.parse(Path(partial.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'public_names']
    status, = [n for n in fn.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'status']
    status.value = ast.Constant(STATUS)
    namespace = dict(vars(partial))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<all-original-public-guards-positive-readonly-review>', 'exec'), namespace)
    result = namespace['public_names'](spec, archive)
    receipt = json.loads(archive.read(spec['receipt_name']))
    need(receipt['financial_resume_authorized'] is False and receipt['readonly_partial_review'] is True
         and receipt['readonly_source_witnesses'] is False and 'worker' not in receipt and 'reviewer' not in receipt
         and all(receipt[role]['stopped'] is True and type(receipt[role]['exit_code']) is int
                 and receipt[role]['exit_code'] == 0 and receipt[role]['oom_killed'] is False
                 for role in ('preflight','repair_reviewer')), 'REQUALIFIED_POSITIVE_READONLY_ONLY_STOPS')
    return result


def review_admission_tree():
    """Keep every original extraction/inspection/source guard; no book in this archive."""
    import system_campaign_financial_partial as partial
    fn = partial.admission_tree()
    site, = [i for i,n in enumerate(fn.body) if isinstance(n, ast.If)
             and ast.unparse(n.test) == "spec.get('unadvanced_qualification_failure')"]
    need(isinstance(fn.body[site-1], ast.Expr) and 'FACTUAL_OLD_SOURCE_REVIEW' in ast.unparse(fn.body[site-1]),
         'REQUALIFIED_STOP_ONLY_AFTER_ALL_AUTHENTICATION_AND_SOURCE_GUARDS')
    fn.body = fn.body[:site] + [ast.Return(ast.Name(id='dest', ctx=ast.Load()))]
    return ast.fix_missing_locations(fn)


def authenticate_review(spec, root, key, inspector):
    import system_campaign_financial_partial as partial
    namespace = dict(vars(partial.crypto), public_names=public_names)
    exec(compile(ast.Module(body=[review_admission_tree()], type_ignores=[]),
                 '<original-authenticated-readonly-review-archive-prefix>', 'exec'), namespace)
    result = namespace['admit'](spec, root, key, max_zip_bytes=512*1024**2)
    for name, expected in spec['inspections'].items():
        partial.archived_inspection(spec, expected, json.loads((result/name).read_bytes()), inspector)
    raw = (result/'request.json').read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['original_request_member']
         and sha(raw) == spec['request_sha256'], 'REQUALIFIED_ACTUAL_ORIGINAL_READONLY_REQUEST')
    request = json.loads(raw)
    need(request['arms'] == ['P07'] and request['financial_resume_authorized'] is False
         and request['maximum_parallel_financial_workers'] == 0
         and request['maximum_parallel_readonly_workers'] == 1
         and request['readonly_partial_review'] is True, 'REQUALIFIED_NO_ORIGINAL_FINANCIAL_WORKER')
    from ephemeral_runner_capacity import validate_prepared_receipt
    with zipfile.ZipFile(result.parent/'predecessor.zip') as archive:
        capacity = json.loads(archive.read('ephemeral-runner-capacity.json'))
    validate_prepared_receipt(capacity, head=spec['head'], run_id=str(spec['run_id']),
        source_sha256=request['sources']['ephemeral_runner_capacity.py'])
    return result


def qualified_view(financial, reviewed, view, target, review):
    proof = quarantine.require_requalified_review(reviewed/'requalified-review', target)
    need(json.loads((reviewed/'failed-review-requalification.json').read_bytes()) == proof
         and proof['core_review_sha256'] == review['core_review_sha256']
         and proof['branch_review_sha256'] == review['branch_review_sha256'], 'REQUALIFIED_EXACT_STOPPED_CANONICAL_PROOFS')
    shutil.copytree(financial, view)
    provenance = view/'lineage/root-review-requalification'
    provenance.mkdir(parents=True)
    replacements = {'uncertainty-certificate-review.json':'uncertainty-certificate-review.json',
                    'stopped-review/uncertainty-certificate-review.json':'uncertainty-certificate-review.json',
                    'stopped-review/core-review.json':'core-review.json'}
    supplied = {}
    for name, source in replacements.items():
        destination = view/name
        if destination.exists():
            backup = provenance/('original-'+name.replace('/','--'))
            shutil.copyfile(destination, backup)
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = (reviewed/'requalified-review'/source).read_bytes()
        destination.write_bytes(raw); supplied[name] = sha(raw)
    original_book = {p.relative_to(financial/'book').as_posix():sha(p.read_bytes())
                     for p in (financial/'book').rglob('*') if p.is_file()}
    actual_book = {p.relative_to(view/'book').as_posix():sha(p.read_bytes())
                   for p in (view/'book').rglob('*') if p.is_file()}
    need(actual_book == original_book and 'checkpoint.json.gz' in original_book,
         'REQUALIFIED_EVERY_FINANCIAL_BOOK_BYTE_UNCHANGED')
    receipt = dict(schema='research.root-requalified-original-input-view/1', original_quarantine_target_sha256=QUARANTINE_SHA,
        review_transport_sha256=CATALOG_SHA, original_failed_stops_preserved=True, all_book_files=original_book,
        supplied_external_review_files=supplied, financial_transitions_reexecuted=0)
    (provenance/'receipt.json').write_bytes(encoded(receipt))
    return view


def admit(spec, root, key, inspector):
    target, review = validated(spec)
    def rooted_request(request, actual):
        need(actual == target, 'REQUALIFIED_ROOT_AUTHORITY_ONLY_FOR_EXACT_ORIGINAL_TRANSPORT')
    original = quarantine.admit
    need(original.__closure__ is None, 'REQUALIFIED_ORIGINAL_QUARANTINE_HAS_NO_HIDDEN_CLOSURE')
    authenticate = FunctionType(original.__code__, dict(original.__globals__, request_only_readonly=rooted_request),
                                original.__name__, original.__defaults__)
    financial = authenticate(target, root, key, inspector)
    reviewed = authenticate_review(review, Path(root).with_name(Path(root).name+'-qualified-review'), key, inspector)
    need((financial/'source-bindings.json').read_bytes() == (reviewed/'source-bindings.json').read_bytes()
         and json.loads((reviewed/'spec.json').read_bytes()) == target, 'REQUALIFIED_SAME_EXACT_FINANCIAL_SOURCE_AND_TARGET')
    return qualified_view(financial, reviewed, Path(root)/'qualified-input-view', target, review)
