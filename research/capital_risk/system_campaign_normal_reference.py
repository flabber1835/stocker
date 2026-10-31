"""Exact normal receipt successors; no spec projection or financial execution."""
import ast
import hashlib
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest
import system_campaign_content_reference as original
from seal import sha256_file

SOURCE_SHA = '51adc655b0c9ea7e9db349b9f73fe15ecc005053cbe311da2214b1043b546474'
ADMIT_SHA = '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
RECEIPTS = frozenset(('research.system-p02-wwe-suffix-receipt/1',
                      'research.system-p02-cash-suffix-receipt/1'))
LIMIT = 512 * 1024**2


def source_bytes():
    raw = Path(original.__file__).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == SOURCE_SHA,
         'NORMAL_REFERENCE_EXACT_ORIGINAL_SCHEMA_AND_ADAPTER_SOURCE')
    return raw


def reference(spec):
    """Change only the explicitly declared receipt-format eligibility guard."""
    fn, = [v for v in ast.parse(source_bytes()).body
           if isinstance(v, ast.FunctionDef) and v.name == 'reference']
    nodes = [v for v in ast.walk(fn) if isinstance(v, ast.Compare)
             and ast.unparse(v) == "spec['receipt_schema'] == 'research.system-p02-uncertainty-suffix-receipt/1'"]
    need(len(nodes) == 1, 'NORMAL_REFERENCE_ONE_EXACT_RECEIPT_SCOPE_SITE')
    nodes[0].ops = [ast.In()]
    nodes[0].comparators = [ast.Name(id='APPROVED_NORMAL_REFERENCE_RECEIPTS', ctx=ast.Load())]
    namespace = dict(vars(original), APPROVED_NORMAL_REFERENCE_RECEIPTS=RECEIPTS)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<declared-normal-receipt-successors-full-actual-spec>', 'exec'), namespace)
    return namespace['reference'](spec)


def preserve(old, out, spec):
    source_bytes()
    fn = original.preserve
    need(fn.__closure__ is None, 'NORMAL_REFERENCE_ORIGINAL_STORAGE_WITHOUT_CLOSURE')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, reference=reference),
                           fn.__name__, fn.__defaults__)
    return checked(old, out, spec)


def admit(spec, root, key, *, max_zip_bytes=LIMIT):
    import system_campaign_factual_admit as admission
    admission.check_context(admission.os.environ)
    source_bytes()
    need(sha256_file(Path(admission.__file__)) == ADMIT_SHA,
         'NORMAL_REFERENCE_UNCHANGED_ORIGINAL_CRYPTO_AND_PREFIX_ADMISSION')
    reference(spec)
    need(type(max_zip_bytes) is int and max_zip_bytes == LIMIT
         and type(spec['zip_bytes']) is int and 0 < spec['zip_bytes'] < LIMIT,
         'NORMAL_REFERENCE_EXPLICIT_SMALL_PARENT_ARCHIVE_BOUND')
    expected = original.ParentReference.model_validate(
        spec['retained_parent_content_reference']).model_dump(by_alias=True)
    entry = spec['retained_parent_content_reference_file']
    need(set(entry) == {'path', 'bytes', 'sha256'} and entry['path'] == original.PATH
         and type(entry['bytes']) is int and 0 < entry['bytes'] < 1024**2,
         'NORMAL_REFERENCE_EXACT_RETAINED_REFERENCE_MEMBER')
    # The unchanged admission authenticates before parsing and verifies every
    # current member, stopped fence, source, checkpoint and journal commitment.
    admitted = admission.admit(spec, root, key, max_zip_bytes=LIMIT)
    raw = (admitted / original.PATH).read_bytes()
    need(len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
         and original.ParentReference.model_validate(json.loads(raw)).model_dump(by_alias=True) == expected,
         'NORMAL_REFERENCE_ACTUAL_AUTHENTICATED_ANCESTRAL_REFERENCE_BYTES')
    prior_spec_raw = (admitted / 'spec.json').read_bytes()
    prior_spec = json.loads(prior_spec_raw)
    request_raw = (admitted / 'request.json').read_bytes()
    request = json.loads(request_raw)
    need(hashlib.sha256(request_raw).hexdigest() == spec['request_sha256']
         and request['predecessor_sha256'] == hashlib.sha256(prior_spec_raw).hexdigest()
         and expected['parent_spec_sha256'] == digest(prior_spec)
         and expected['selected_outer_sha256'] == prior_spec['outer_sha256'],
         'NORMAL_REFERENCE_EXACT_ACTUAL_ANCESTRAL_REQUEST_SPEC_AND_BOUNDARY')
    return admitted
