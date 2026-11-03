"""Direct admission of actual own37 financial output; no qualification-copy origin."""
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_pxd_financial_body import function
import system_campaign_content_reference as original
import system_campaign_factual_admit as crypto

HERE = Path(__file__).resolve().parent
SPEC = 'system-campaign-p02-unconsumed2024-cash-predecessor.json'
SPEC_SHA = 'e88ea815531a1087c9fc2172ba4d4ed2ae130ac5b6189370f55cad77eda4f0f9'
PATH = 'lineage/unconsumed2024-financial-parent-reference.json'


def scope(spec):
    need(sha((json.dumps(spec, sort_keys=True, indent=2)+'\n').encode()) == SPEC_SHA
         and spec['schema'] == 'research.actual-unchanged-financial-prefix-predecessor/1'
         and spec['financial_resume_authorized'] is True and spec['review_only'] is False
         and all(spec[k] is False for k in ('new_origin', 'source_conversion', 'production_contacted')),
         'UNCONSUMED_CASH_DISTINCT_EXACT_FINANCIAL_AUTHORITY')
    need(spec['run_id'] == 41233199484 and spec['artifact_id'] == 13055072366
         and spec['head'] == '3dfb8cedc457e76ffd0013318bcd5a0e74ec1af9'
         and spec['selected_session'] == '2024-04-30' and spec['measured_closes'] == 1592
         and spec['formation_closes'] == 126 and len(spec['repairs']) == 37
         and spec['outer_sha256'] == 'a7f540e5834352f03074013537473ebfda69abb02e68ac1b065f1d0ba025102b'
         and spec['parent_certificate_rows'] == 1138,
         'UNCONSUMED_CASH_ACTUAL_OWN37_NOT_DISPOSABLE_COMPONENT')
    full = spec['full_client_admission']
    need(full['schema'] == 'research.complete-unchanged-prefix-client-admission/1'
         and full['review_sha256'] == '44140268ce7e8ea5283c0a65c7992262a1392958a2c11c1b916e17b153809bf1'
         and full['admitted_prefix_sha256'] == '1ab0d5f879632061c0324ff4c0a2d80900944e346371f79ae7cb47a034d73928'
         and full['prior_complete_financial_review_sha256'] == '270ac2e09e684c203011991d42d9cbf7ca705c5ba9b7b067adb8a747e7809f97'
         and all(full[k] is True for k in ('all_committed_financial_journal_bytes_identical',
             'every_financial_controller_reporting_state_field_identical', 'all188_actual_members_readback_verified',
             'actual_financial_run_output_selected')) and full['qualification_copy_used_as_predecessor'] is False,
         'UNCONSUMED_CASH_FULL_FINANCIAL_PROOF_AND_EXACT_ADOPTION_EQUIVALENCE')
    return spec


def reference(spec):
    scope(spec)
    return function('system_campaign_content_reference.py', 'reference', {
        'research.system-p02-uncertainty-suffix-receipt/1': 'research.system-p02-pxd-suffix-receipt/1'},
        vars(original))(spec)


def admit(spec, root, key, *, max_zip_bytes=512*1024**2):
    crypto.check_context(crypto.os.environ)
    reference(spec)
    need(max_zip_bytes == 512*1024**2
         and sha(Path(crypto.__file__).read_bytes()) == '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'UNCONSUMED_CASH_UNCHANGED_COMPLETE_CRYPTO_AND_PREFIX_ADMISSION')
    admitted = crypto.admit(spec, root, key, max_zip_bytes=max_zip_bytes)
    need((Path(root)/'predecessor.zip').is_file()
         and json.loads((HERE/SPEC).read_bytes()) == spec, 'UNCONSUMED_CASH_EXACT_PUBLIC_PARENT_DOCUMENT')
    entry = spec['retained_parent_content_reference_file']
    raw = (admitted/entry['path']).read_bytes()
    need(entry['path'] == 'lineage/composite-financial-parent-reference.json'
         and len(raw) == entry['bytes'] and sha(raw) == entry['sha256']
         and json.loads(raw) == spec['retained_parent_content_reference'],
         'UNCONSUMED_CASH_EXACT_RETAINED_COMPOSITE_ANCESTRAL_REFERENCE')
    prior_request_raw = (admitted/'request.json').read_bytes()
    prior_request = json.loads(prior_request_raw)
    prior_spec_raw = (admitted/'spec.json').read_bytes()
    need(sha(prior_request_raw) == spec['request_sha256'] and sha(prior_spec_raw) == prior_request['predecessor_sha256']
         and digest(json.loads(prior_spec_raw)) == json.loads(raw)['composite_spec_sha256'],
         'UNCONSUMED_CASH_ACTUAL_ANCESTRAL_REQUEST_AND_FINANCIAL_BOUNDARY')
    need(len(prior_request['sources']) == 286
         and all(sha((HERE/n).read_bytes()) == h for n, h in prior_request['sources'].items()),
         'UNCONSUMED_CASH_ALL286_ACTUAL_ADMITTED_SOURCE_BYTES_UNCHANGED')
    from system_campaign_pxd_financial_diagnostics import stopped
    for role, name, meta in [('worker','economic-worker-inspect.json',spec['inspections']['economic-worker-inspect.json']),
                             ('review','independent-review-stop/worker-inspect.json',spec['inspections']['independent-review-stop/worker-inspect.json'])]:
        stopped(json.loads((admitted/name).read_bytes()),
                dict(stopped=True, oom_killed=False, exit_code=meta['exit_code']), role, str(spec['run_id']),
                'system-campaign-p02-pxd-request.json')
    need(spec['inspections']['economic-worker-inspect.json']['exit_code'] == 1
         and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code'] == 0,
         'UNCONSUMED_CASH_ORIGINAL_FAILURE_AND_SUCCESSFUL_FINANCIAL_REVIEW_PRESERVED')
    return admitted


def preserve(old, out, spec):
    reference(spec)
    fn = original.preserve
    need(fn.__closure__ is None, 'UNCONSUMED_CASH_EXACT_REFERENCE_STORAGE_WITHOUT_CLOSURE')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, reference=reference, PATH=PATH), fn.__name__, fn.__defaults__)
    return checked(old, out, spec)
