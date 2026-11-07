"""Separate financial root loader: immutable failedFIN339 plus positive REVIEW344."""
import ast, json, shutil, stat
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
import system_campaign_p07_fin326_requalified_parent as original
import system_campaign_p06_fin339_readonly_recovery_v2 as quarantine
import system_campaign_p06_WWE_admission as authority
from full_system_benchmark import need
from system_campaign_facts import sha
HERE = Path(__file__).parent
CATALOG = 'P06-REVIEW344-positive-requalified-transport.json'
CATALOG_SHA = '36a68f0c46a295c5c4dc4e8a4233eeb6d2bdfff2dbfe2349c4b7687be1ec89f5'
TARGET = 'P06-FIN339-exact-failed-target.json'
TARGET_SHA = '6124a681f560b9012cd060daaa43b1bca28c0638b3cd670a648a648a898888bf'
ORIGINAL_SHA = 'ca981e5bc69446730cc390093aaf59ed5eec310ac15e950feacb68d4bdb6f680'
STATUS = 'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
MODE = 'OWN_ADMITTED_FINANCIAL_CONTINUATION'
FIELD = 'selected_p06_WWE12_retained173_financial_profile'
CORE = 'root-review344/core-review.json'

def bind(fn, **bindings):
    need(fn.__closure__ is None, 'P06_REQUALIFIED_WHOLE_ORIGINAL_FUNCTION_NO_CLOSURE')
    result = FunctionType(fn.__code__, dict(fn.__globals__, **bindings), fn.__name__, fn.__defaults__)
    result.__kwdefaults__ = fn.__kwdefaults__
    need(result.__code__ is fn.__code__, 'P06_REQUALIFIED_IDENTICAL_COMPLETE_ORIGINAL_FUNCTION_CODE')
    return result

def original_source():
    raw = Path(original.__file__).read_bytes()
    need(sha(raw) == ORIGINAL_SHA, 'P06_REQUALIFIED_WHOLE_MATURE_P07_LOADER_SOURCE')
    return raw

def transport():
    raw = (HERE / CATALOG).read_bytes()
    need(sha(raw) == CATALOG_SHA, 'P06_REQUALIFIED_ACTUAL_POSITIVE_REVIEW344_TRANSPORT')
    value = json.loads(raw)
    need((value['arm'], value['run_id'], value['head'], value['artifact_id']) == ('P06', 42272581118, '932b8db4205c9f09438819ecf5866ba7ef7e85fd', 13531362933) and value['quarantine_target_sha256'] == TARGET_SHA and (value['receipt_status'] == STATUS) and (value['zip_bytes'] == 226488) and (value['zip_sha256'] == '4f1d861f8f09543de3def77f94a71d2e6c13b8cae3b88b32bb399257d242bd70'), 'P06_REQUALIFIED_ONLY_REAL_ZERO_FINANCIAL_REVIEW344_SUCCESS')
    return value

def failed_target():
    raw = (HERE / TARGET).read_bytes()
    need(sha(raw) == TARGET_SHA, 'P06_REQUALIFIED_EXACT_FAILED_FIN339_TARGET_BYTES')
    value = json.loads(raw)
    quarantine.validate_target(value)
    return value

def applies(spec):
    return isinstance(spec, dict) and spec.get('arm') == 'P06' and (spec.get('root_admission_sha256') == authority.ROOT_SHA) and (spec.get('outer_sha256') == quarantine.OUTER)

def validated(spec):
    value = authority.require(spec)
    target = failed_target()
    review = transport()
    admission = spec['root_admission']
    need(all((spec.get(k) == v for k, v in target.items())) and spec['receipt_status'] == 'FINANCIAL_REVIEW_REFUSED_PRESERVED' and (spec['readonly_failed_review_requalification'] is True) and (admission['original_failed_financial_receipt_preserved'] is True) and (admission['original_failed_financial_receipt_sha256'] == target['receipt_sha256']) and (admission['fresh_readonly_artifact_zip_sha256'] == review['zip_sha256']), 'P06_REQUALIFIED_ACTUAL_P06_FAILED_TARGET_AND_FRESH344_LINEAGE')
    proof = admission['fresh_readonly_financial_review_requalification']
    need(proof['passed'] is True and proof['checkpoint_sha256'] == spec['outer_sha256'] == target['outer_sha256'] == quarantine.OUTER and (proof['original_financial_artifact_id'] == target['artifact_id'] == 13525611349) and (proof['original_failed_receipt_sha256'] == target['receipt_sha256']) and (proof['core_review_sha256'] == review['core_review_sha256']) and (proof['branch_review_sha256'] == review['branch_review_sha256']) and (proof['source_review_sha256'] == review['source_review_sha256']) and (proof['original_failed_stops_preserved'] is True) and (proof['financial_authority'] is False) and (type(proof['financial_sessions_advanced']) is int) and (proof['financial_sessions_advanced'] == 0), 'P06_REQUALIFIED_REAL_POSITIVE344_PROOF_NEVER_P07_SCHEMA_OR_RELABELED_FAILURE')
    return (target, review)

def public_names(spec, archive):
    original_source()
    return bind(original.public_names, transport=transport, STATUS=STATUS)(spec, archive)

def review_admission_tree():
    original_source()
    return original.review_admission_tree()

def authenticate_review_tree():
    fn, = [n for n in ast.parse(original_source()).body if isinstance(n, ast.FunctionDef) and n.name == 'authenticate_review']
    sites = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value == 'P07']
    need(len(sites) == 1, 'P06_REQUALIFIED_ONE_EXACT_ORIGINAL_REVIEW_ARM_LITERAL')
    sites[0].value = 'P06'
    return ast.fix_missing_locations(fn)

def authenticate_review(spec, root, key, inspector):
    need(spec == transport(), 'P06_REQUALIFIED_ONLY_ACTUAL_REVIEW344_AUTHENTICATION_SCOPE')
    namespace = dict(vars(original), public_names=public_names, review_admission_tree=review_admission_tree)
    exec(compile(ast.Module(body=[authenticate_review_tree()], type_ignores=[]), '<whole-original-review-authenticator-P06-arm-only>', 'exec'), namespace)
    return namespace['authenticate_review'](spec, root, key, inspector)

def accounting_review(spec):
    _, review = validated(spec)
    return (CORE, review['core_review_sha256'])

def request_financial(request, spec):
    authority.require(spec)
    need(False, 'P06_REQUALIFIED_DEFAULT_CLOSED_UNTIL_SEPARATE_WHOLE_FINANCIAL_PROFILE_VALIDATOR')

def qualified_view(financial, reviewed, view, target, review):
    quarantine.launcher_guard()
    financial, reviewed, view = (Path(financial), Path(reviewed), Path(view))
    need(target == failed_target() and review == transport() and (not view.exists()) and view.parent.is_dir(), 'P06_REQUALIFIED_FRESH_OWNED_COPY_OF_TWO_EXACT_AUTHENTICATED_TRANSPORTS')
    qualification = quarantine.require_requalified_review(reviewed / 'requalified-review', target)
    need(json.loads((reviewed / 'failed-review-requalification.json').read_bytes()) == qualification, 'P06_REQUALIFIED_ACTUAL_FRESH344_CORE_BRANCH_SOURCE_REVIEW_GATE')
    before = {p.relative_to(financial).as_posix(): sha(p.read_bytes()) for p in financial.rglob('*') if p.is_file()}
    need('book/checkpoint.json.gz' in before and all((not p.is_symlink() for p in financial.rglob('*'))), 'P06_REQUALIFIED_NO_SYMLINK_AND_REAL_ORIGINAL_BOOK_SOURCE')
    shutil.copytree(financial, view)
    paths = [view, *view.rglob('*')]
    resolved = view.resolve()
    need(not view.is_symlink() and all((not p.is_symlink() and (p.resolve() == resolved or resolved in p.resolve().parents) for p in paths)), 'P06_REQUALIFIED_VALIDATE_ALL_COPIED_PATHS_BEFORE_ANY_OWNER_CHMOD')
    for p in paths:
        if p.is_dir():
            p.chmod(stat.S_IMODE(p.stat().st_mode) | stat.S_IWUSR | stat.S_IXUSR)
    folder = view / 'root-review344'
    need(not folder.exists(), 'P06_REQUALIFIED_FRESH_SEPARATE_REVIEW_NAMESPACE')
    folder.mkdir()
    for name, pin in (('core-review.json', review['core_review_sha256']), ('uncertainty-certificate-review.json', review['branch_review_sha256']), ('p06-BBIG-combined-observation-review.json', review['source_review_sha256'])):
        raw = (reviewed / 'requalified-review' / name).read_bytes()
        need(sha(raw) == pin, 'P06_REQUALIFIED_EACH_FRESH_REVIEW_BYTE_IDENTITY')
        with (folder / name).open('xb') as stream:
            stream.write(raw)
    raw = (reviewed / 'monthly-reproduction.json').read_bytes()
    need(sha(raw) == review['monthly_reproduction_sha256'], 'P06_REQUALIFIED_EXACT_FRESH_MONTHLY_PROOF')
    with (folder / 'monthly-reproduction.json').open('xb') as stream:
        stream.write(raw)
    after = {n: sha((view / n).read_bytes()) for n in before}
    need(before == after and sha((view / 'stopped-review/uncertainty-certificate-review.json').read_bytes()) == '190de5015b174b76f42786943f87ac5e3100555b660e0e116d7d305a18b71bf8', 'P06_REQUALIFIED_ALL_ORIGINAL_FILES_FAILED_RECEIPT_BOOK_AND_FIN339_ORACLE_UNCHANGED')
    receipt = dict(passed=True, original_failed_stops_preserved=True, all_original_files=before, separate_review_transport_sha256=CATALOG_SHA, original_FIN339_oracle_preserved=True, financial_checkpoint_replaced=False, financial_sessions_reexecuted=0)
    with (folder / 'qualified-input-source-receipt.json').open('xb') as stream:
        stream.write(authority.encoded(receipt))
    return view

def admit(spec, root, key, inspector):
    quarantine.launcher_guard()
    target, review = validated(spec)

    def rooted(request, actual):
        need(actual == target, 'P06_REQUALIFIED_ONLY_ORIGINAL_FAILED_TRANSPORT')
        request_financial(request, spec)
    original_admit = quarantine.legacy('admit')
    authenticate = bind(original_admit, request_only_readonly=rooted)
    financial = authenticate(target, root, key, inspector)
    reviewed = authenticate_review(review, Path(root).with_name(Path(root).name + '-review344'), key, inspector)
    need((financial / 'source-bindings.json').read_bytes() == (reviewed / 'source-bindings.json').read_bytes() and json.loads((reviewed / 'spec.json').read_bytes()) == target, 'P06_REQUALIFIED_SAME_ACTUAL_FINANCIAL_SOURCE_AND_FAILED_TARGET')
    return qualified_view(financial, reviewed, Path(root) / 'qualified-input-view', target, review)

@contextmanager
def context(spec, request, *, mode, profile_validator=None):
    if mode == 'launch':
        quarantine.launcher_guard()
    else:
        from full_system_core import hosted
        hosted()
    need(mode in ('launch', 'preflight', 'economic', 'review'), 'P06_REQUALIFIED_ONLY_EXPLICIT_PROCESS_MODES')
    if not applies(spec):
        yield
        return
    validated(spec)
    need(callable(profile_validator) and profile_validator(request, spec) is True, 'P06_REQUALIFIED_SEPARATE_EXACT_PROFILE_VALIDATOR_REQUIRED')
    import system_campaign_financial_requalified_parent as dispatch
    saved = {n: getattr(dispatch, n) for n in ('applies', 'admit', 'accounting_review')}
    guarded_admit = bind(admit, request_financial=profile_validator)
    dispatch.applies = lambda value: applies(value) or saved['applies'](value)
    dispatch.admit = lambda value, *a, **k: guarded_admit(value, *a, **k) if applies(value) else saved['admit'](value, *a, **k)
    dispatch.accounting_review = lambda value: accounting_review(value) if applies(value) else saved['accounting_review'](value)
    try:
        yield
    finally:
        for n, v in saved.items():
            setattr(dispatch, n, v)

def source_names():
    return (Path(__file__).name, CATALOG, TARGET, *authority.source_names(), *quarantine.source_names())
