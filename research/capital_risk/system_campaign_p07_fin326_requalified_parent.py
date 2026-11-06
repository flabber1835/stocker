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
import system_campaign_p07_readonly_review_recovery as quarantine

FLAG = 'root_requalified_fin326_failed_review_parent'
CATALOG = 'system-campaign-p07-fin326-requalified-review-transport.json'
CATALOG_SHA = '28ea72e665ed42fecc7439a30bcf5f7858e917075408c3ace0ca7ac6427b1c9d'
QUARANTINE_SHA = '4e894728900896e3e1fb36c9ef5fc6a0dda9eaedbd9917bb645827ac97d51b41'
ROOT_SHA = 'd9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b'
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
         ('P07', 42178048589, '5c22eb3ea156cabcbb723a3ddc67d680d3128bc0', 13484691480,
          'bf6eb592c65070eeb0536dd842f78ff13dfb6a8c5330f23c176f99af193d6834')
         and value['quarantine_target_sha256'] == QUARANTINE_SHA,
         'REQUALIFIED_ONLY_EXACT_SUCCESSFUL_REVIEW332')
    return value


def validated(spec):
    require_closed_binding(spec)
    import system_campaign_financial_partial as partial
    need(applies(spec) and spec.get('qualified_review_transport_sha256') == CATALOG_SHA
         and quarantine.FLAG not in spec and quarantine.MARKER not in spec and 'root_admission' in spec, 'REQUALIFIED_SEPARATE_ADMITTED_ROOT_REQUIRED')
    partial.validate_root_spec(spec)
    target = {k:deepcopy(v) for k,v in spec.items() if k not in
              (FLAG, 'qualified_review_transport_sha256', 'root_admission', 'root_admission_sha256')}
    target[quarantine.FLAG] = True
    target[quarantine.MARKER] = True
    need(sha(encoded(target)) == QUARANTINE_SHA, 'REQUALIFIED_ORIGINAL_QUARANTINE_TARGET_UNCHANGED')
    quarantine.validate_target(target)
    review = transport()
    proof = spec['root_admission']['failed_review_requalification']
    need(proof['review_transport_sha256'] == CATALOG_SHA
         and proof['original_quarantine_target_sha256'] == QUARANTINE_SHA
         and proof['core_review_sha256'] == review['core_review_sha256']
         and proof['branch_review_sha256'] == review['branch_review_sha256']
         and proof['independent_validation_sha256'] == '74762af37dd69927a58fad586665ba8be4cd06f120c085e1c008a7167a52cfd8'
         and proof['independent_review_sha256'] == '4399ca8407933809db82c0d994721baf4664443203b5ff074c0e7e904f05ede1'
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
    quarantine.launcher_guard()
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
    quarantine.launcher_guard()
    target, review = validated(spec)
    def rooted_request(request, actual):
        need(actual == target, 'REQUALIFIED_ROOT_AUTHORITY_ONLY_FOR_EXACT_ORIGINAL_TRANSPORT')
        request_only_source(request,spec)
    original = quarantine.bound('admit')
    need(original.__closure__ is None, 'REQUALIFIED_ORIGINAL_QUARANTINE_HAS_NO_HIDDEN_CLOSURE')
    authenticate = FunctionType(original.__code__, dict(original.__globals__, request_only_readonly=rooted_request),
                                original.__name__, original.__defaults__)
    financial = authenticate(target, root, key, inspector)
    reviewed = authenticate_review(review, Path(root).with_name(Path(root).name+'-qualified-review'), key, inspector)
    need((financial/'source-bindings.json').read_bytes() == (reviewed/'source-bindings.json').read_bytes()
         and json.loads((reviewed/'spec.json').read_bytes()) == target, 'REQUALIFIED_SAME_EXACT_FINANCIAL_SOURCE_AND_TARGET')
    return qualified_view(financial, reviewed, Path(root)/'qualified-input-view', target, review)


def require_closed_binding(spec):
    import re
    need(re.fullmatch('[a-f0-9]{64}',ROOT_SHA) is not None
         and spec.get('root_admission_sha256')==ROOT_SHA,
         'P07_COMPOSITE_ONLY_REAL_FINALIZED_ROOT_BINDING_NO_DRAFT_AUTHORITY')
    admission=spec.get('root_admission',{})
    need(admission.get('completed')==1259 and admission.get('source_cursor')=='2022-12-30'
         and admission.get('parent_root_admission_sha256')=='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d'
         and admission.get('outer_sha256')=='1e1e4dbce5a3b13c329bfb2c16a99e6f6043bcc8628a9852971f7100d9295a3a'
         and len(admission.get('repairs',[]))==24,
         'P07_COMPOSITE_EXACT_REAL1259_FULL24_ORIGINAL1238_LINEAGE')


def source_names():
    return tuple(sorted(set(quarantine.source_names())|{Path(__file__).name,CATALOG}))


from contextlib import contextmanager


@contextmanager
def context(spec,*,mode):
    if mode=='launch':quarantine.launcher_guard()
    else:
        from full_system_core import hosted
        hosted()
    need(mode in ('launch','preflight'),'P07_COMPOSITE_SOURCE_ONLY_LAUNCH_AND_PREFLIGHT')
    if not applies(spec):yield;return
    validated(spec)
    import system_campaign_financial_requalified_parent as original
    saved={name:getattr(original,name) for name in ('applies','admit','accounting_review')}
    original.applies=lambda value:applies(value) or saved['applies'](value)
    original.admit=lambda value,*args,**kwargs:admit(value,*args,**kwargs) if applies(value) else saved['admit'](value,*args,**kwargs)
    original.accounting_review=lambda value:accounting_review(value) if applies(value) else saved['accounting_review'](value)
    try:yield
    finally:
        for name,value in saved.items():setattr(original,name,value)


def bind_launch(original):
    def launch(args):
        quarantine.launcher_guard()
        request=json.loads(Path(args.request).read_bytes())
        if args.arm!='P07':
            return original(args)
        from system_campaign_financial_partial import root_spec
        spec=root_spec('P07')
        if not applies(spec):return original(args)
        request_only_source(request,spec)
        with context(spec,mode='launch'):return original(args)
    return launch


SOURCE_MODE='READONLY_FROZEN_SOURCE_WITNESSES'
SOURCE_FIELD='selected_p07_composite_source_bridges'


def source_declaration(spec):
    validated(spec)
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is proof['all_comparisons_and_state_sets_verified']
         is proof['all_math_watch_financial_chains_verified'] is True
         and type(proof['rows']) is type(proof['retained_rows']) is int
         and (proof['rows'],proof['retained_rows'])==(21,784),
         'P07_COMPOSITE_SOURCE_ONLY_EXACT805_ADMITTED_PROOFS')
    return dict(schema='research.P07-FIN326-composite-source-only-declaration/1',arm='P07',
        root_admission_sha256=ROOT_SHA,outer_sha256=spec['outer_sha256'],completed=1259,source_cursor='2022-12-30',
        full_input_descriptors=24,committed_proof_rows=805,original_retained_proofs=784,new_committed_proofs=21,
        qualified_review_transport_sha256=CATALOG_SHA,independent_validation_sha256='74762af37dd69927a58fad586665ba8be4cd06f120c085e1c008a7167a52cfd8',
        financial_authority=False,financial_transitions_reexecuted=0,new_factual_overlay=False,
        new_input_adoption=False,certificate_factory_installed=False,full_original_model_route_required=True)


def request_only_source(request,spec):
    expected=source_declaration(spec)
    need(request.get('execution_mode')==SOURCE_MODE and request.get('readonly_source_witnesses') is True
         and request.get('financial_resume_authorized') is request.get('readonly_partial_review') is False
         and type(request.get('maximum_parallel_financial_workers')) is int and request['maximum_parallel_financial_workers']==0
         and type(request.get('maximum_parallel_readonly_workers')) is int and 1<=request['maximum_parallel_readonly_workers']<=4
         and 'P07' in request.get('arms',[]) and request.get('admitted_checkpoints',{}).get('P07')==spec['outer_sha256']
         and request.get('arm_inputs',{}).get('P07')==dict(new_factual_overlay=False,restored_correlation=False)
         and request.get(SOURCE_FIELD,{}).get('P07')==expected,
         'P07_COMPOSITE_EXPLICIT_EXACT_SOURCE_ONLY_REQUEST_NO_FINANCIAL_ENABLE')
    return expected


def expected_request(original,*,execution_mode,selected_arms,root_lookup,source_bytes=None):
    result=original();declared={}
    if 'P07' in selected_arms:
        spec=root_lookup('P07')
        if applies(spec):
            need(execution_mode==SOURCE_MODE,'P07_COMPOSITE_FINANCIAL805_CONTINUATION_NOT_YET_QUALIFIED')
            declared['P07']=source_declaration(spec)
    result[SOURCE_FIELD]=declared
    reader=(lambda name:(Path(__file__).parent/name).read_bytes()) if source_bytes is None else source_bytes
    for name in source_names():
        pin=sha(reader(name));need(name not in result['sources'] or result['sources'][name]==pin,
            'P07_COMPOSITE_NO_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result


@contextmanager
def source_context(module,spec,*,mode,request):
    from full_system_core import hosted
    hosted()
    if not applies(spec):yield;return
    need(mode=='preflight','P07_COMPOSITE_SOURCE_CONTEXT_PREFLIGHT_ONLY')
    request_only_source(request,spec)
    import system_campaign_p07_abmd_lifecycle as lifecycle
    need(lifecycle.selected(spec) and lifecycle.valid_retained(spec),
         'P07_COMPOSITE_UNCHANGED_FULL24_LIFECYCLE_ROUTE_REQUIRED')
    phase=lifecycle.phase(spec)
    need((phase['completed'],phase['source_cursor'],phase['proof_rows'],phase['proof_new_rows'],phase['proof_retained_rows'])
         ==(1259,'2022-12-30',805,21,784),
         'P07_COMPOSITE_EXACT_SOURCE_ONLY_FULL24_AND805_LIFECYCLE_PHASE')
    with context(spec,mode='preflight'):yield
