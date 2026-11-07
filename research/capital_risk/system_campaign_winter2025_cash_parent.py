"""Admit only the actual independently reviewed own40 January financial output."""
import json
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_pxd_financial_body import function
import system_campaign_content_reference as original
import system_campaign_factual_admit as crypto
HERE = Path(__file__).resolve().parent
SPEC = 'system-campaign-p02-winter2025-cash-predecessor.json'
SPEC_SHA = 'c8b45232c4148c0eb171bfa3f54eb2af7f929d3d7ce9d662cb1dd7a24bda61ef'
PATH = 'lineage/winter2025-cash-financial-parent-reference.json'

def scope(spec):
    need(sha((json.dumps(spec, sort_keys=True, indent=2) + '\n').encode()) == SPEC_SHA and spec['schema'] == 'research.actual-advanced-financial-prefix-predecessor/1' and (spec['financial_resume_authorized'] is True) and (spec['review_only'] is False) and all((spec[k] is False for k in ('new_origin', 'source_conversion', 'production_contacted'))), 'WINTER2025_DISTINCT_EXACT_ADVANCED_FINANCIAL_AUTHORITY')
    need(spec['run_id'] == 41250116694 and spec['artifact_id'] == 13061755679 and (spec['head'] == '62368832c22d02016a67547ba86cab4605e654db') and (spec['selected_session'] == '2025-01-31') and (spec['measured_closes'] == 1781) and (spec['formation_closes'] == 126) and (len(spec['repairs']) == 40) and (spec['outer_sha256'] == 'd3dc754fad4532314bc7e83a4cac98af9c9a0c92cf338f79b7ac6597448e18d3') and (spec['parent_certificate_rows'] == 1327), 'WINTER2025_ACTUAL_OWN40_NOT_DIAGNOSTIC_FEBRUARY_OR_COMPONENT')
    full = spec['full_client_admission']
    need(full['schema'] == 'research.complete-advanced-prefix-client-admission/1' and full['review_sha256'] == '43fca429f7f665cb7360a0ec44362f7c75bcb2a74562e20a895b626adafdcd8a' and (full['admitted_prefix_sha256'] == '354cf49ecac7de4db7937682cba4054c651c7d8dbf828f2509173dc245a8012d') and all((full[k] is True for k in ('all215_actual_members_readback_verified', 'actual_financial_run_output_selected', 'every_actual_financial_factor_chain_and_controller_branch_verified', 'all_original_and_current_checkpoint_prefixes_and_tails_verified', 'all_eight_original_model_semantics_unchanged'))) and (full['qualification_copy_used_as_predecessor'] is False) and (full['accounting_snapshots'] == 3814) and (full['new_committed_closes'] == 61) and (full['monthly_reports_all_four_series'] == 85), 'WINTER2025_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF')
    return spec

def reference(spec):
    scope(spec)
    return function('system_campaign_content_reference.py', 'reference', {'research.system-p02-uncertainty-suffix-receipt/1': 'research.system-p02-lbph-cash-suffix-receipt/1'}, vars(original))(spec)

def admit(spec, root, key, *, max_zip_bytes=512 * 1024 ** 2):
    crypto.check_context(crypto.os.environ)
    reference(spec)
    need(max_zip_bytes == 512 * 1024 ** 2 and sha(Path(crypto.__file__).read_bytes()) == '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4', 'WINTER2025_UNCHANGED_COMPLETE_CRYPTO_AND_PREFIX_ADMISSION')
    admitted = crypto.admit(spec, root, key, max_zip_bytes=max_zip_bytes)
    need((Path(root) / 'predecessor.zip').is_file() and json.loads((HERE / SPEC).read_bytes()) == spec, 'WINTER2025_EXACT_PUBLIC_FINANCIAL_PARENT_DOCUMENT')
    entry = spec['retained_parent_content_reference_file']
    raw = (admitted / entry['path']).read_bytes()
    need(entry['path'] == 'lineage/lbph-cash-financial-parent-reference.json' and len(raw) == entry['bytes'] and (sha(raw) == entry['sha256']) and (json.loads(raw) == spec['retained_parent_content_reference']), 'WINTER2025_ALL_RETAINED_PRIOR_REFERENCE_BYTES_UNCHANGED')
    prior_request_raw = (admitted / 'request.json').read_bytes()
    prior_request = json.loads(prior_request_raw)
    prior_spec_raw = (admitted / 'spec.json').read_bytes()
    need(sha(prior_request_raw) == spec['request_sha256'] and sha(prior_spec_raw) == prior_request['predecessor_sha256'] and (digest(json.loads(prior_spec_raw)) == json.loads(raw)['parent_spec_sha256']), 'WINTER2025_ACTUAL_PRIOR_REQUEST_AND_ORIGINAL_BOUNDARY_PRESERVED')
    need(len(prior_request['sources']) == 321 and all((sha((HERE / n).read_bytes()) == h for n, h in prior_request['sources'].items())), 'WINTER2025_ALL321_ACTUAL_ADMITTED_SOURCE_BYTES_UNCHANGED')
    from system_campaign_lbph_cash_diagnostics import stopped
    for role, name, meta in [('worker', 'economic-worker-inspect.json', spec['inspections']['economic-worker-inspect.json']), ('review', 'independent-review-stop/worker-inspect.json', spec['inspections']['independent-review-stop/worker-inspect.json'])]:
        stopped(json.loads((admitted / name).read_bytes()), dict(stopped=True, oom_killed=False, exit_code=meta['exit_code']), role, str(spec['run_id']), 'system-campaign-p02-lbph-cash-request.json')
    need(spec['inspections']['economic-worker-inspect.json']['exit_code'] == 1 and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code'] == 0, 'WINTER2025_ACTUAL_ORIGINAL_REFUSAL_AND_SUCCESSFUL_REVIEW_PRESERVED')
    return admitted

def preserve(old, out, spec):
    reference(spec)
    fn = original.preserve
    need(fn.__closure__ is None, 'WINTER2025_EXACT_REFERENCE_STORAGE_WITHOUT_CLOSURE')
    checked = FunctionType(fn.__code__, dict(fn.__globals__, reference=reference, PATH=PATH), fn.__name__, fn.__defaults__)
    return checked(old, out, spec)
