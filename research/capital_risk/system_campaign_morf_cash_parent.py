"""Admit only the actual independently reviewed own38 July financial output."""
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import digest,sha
from system_campaign_pxd_financial_body import function
import system_campaign_content_reference as original
import system_campaign_factual_admit as crypto

HERE=Path(__file__).resolve().parent
SPEC='system-campaign-p02-morf-cash-predecessor.json'
SPEC_SHA='7626afe93915b660da7b8994d4724d161b535615a56af0a2d92e3a707e4a7ca1'
PATH='lineage/morf-cash-financial-parent-reference.json'


def scope(spec):
    need(sha((json.dumps(spec,sort_keys=True,indent=2)+'\n').encode())==SPEC_SHA
         and spec['schema']=='research.actual-advanced-financial-prefix-predecessor/1'
         and spec['financial_resume_authorized'] is True and spec['review_only'] is False
         and all(spec[k] is False for k in ('new_origin','source_conversion','production_contacted')),
         'MORF_DISTINCT_EXACT_ADVANCED_FINANCIAL_AUTHORITY')
    need(spec['run_id']==41239118150 and spec['artifact_id']==13057615894
         and spec['head']=='9075bf537aac518c63e6549e2aede74f48c73187'
         and spec['selected_session']=='2024-07-31' and spec['measured_closes']==1655
         and spec['formation_closes']==126 and len(spec['repairs'])==38
         and spec['outer_sha256']=='7bf2e6ef8a4679b4948b0de948cd0bec58917c49b69516f3073b904219817340'
         and spec['parent_certificate_rows']==1201,'MORF_ACTUAL_OWN38_NOT_DIAGNOSTIC_AUGUST_OR_COMPONENT')
    full=spec['full_client_admission']
    need(full['schema']=='research.complete-advanced-prefix-client-admission/1'
         and full['review_sha256']=='bd2aad66a6e9fdab7083004874b6e2fc69fdd1d92bcbb322bc99c8344354ea6d'
         and full['admitted_prefix_sha256']=='ab5ace78acda4e2045e3fec8dc30e9bf9b6a12174dc73c6b50cf336efb84568f'
         and all(full[k] is True for k in ('all198_actual_members_readback_verified',
             'actual_financial_run_output_selected','every_actual_financial_factor_chain_and_controller_branch_verified',
             'all_original_and_current_checkpoint_prefixes_and_tails_verified','all_eight_original_model_semantics_unchanged'))
         and full['qualification_copy_used_as_predecessor'] is False
         and full['accounting_snapshots']==3562 and full['new_committed_closes']==63
         and full['monthly_reports_all_four_series']==79,'MORF_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF')
    return spec


def reference(spec):
    scope(spec)
    return function('system_campaign_content_reference.py','reference',{
        'research.system-p02-uncertainty-suffix-receipt/1':'research.system-p02-unconsumed-cash-suffix-receipt/1'},
        vars(original))(spec)


def admit(spec,root,key,*,max_zip_bytes=512*1024**2):
    crypto.check_context(crypto.os.environ);reference(spec)
    need(max_zip_bytes==512*1024**2
         and sha(Path(crypto.__file__).read_bytes())=='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'MORF_UNCHANGED_COMPLETE_CRYPTO_AND_PREFIX_ADMISSION')
    admitted=crypto.admit(spec,root,key,max_zip_bytes=max_zip_bytes)
    need((Path(root)/'predecessor.zip').is_file() and json.loads((HERE/SPEC).read_bytes())==spec,
         'MORF_EXACT_PUBLIC_FINANCIAL_PARENT_DOCUMENT')
    entry=spec['retained_parent_content_reference_file'];raw=(admitted/entry['path']).read_bytes()
    need(entry['path']=='lineage/unconsumed2024-financial-parent-reference.json'
         and len(raw)==entry['bytes'] and sha(raw)==entry['sha256']
         and json.loads(raw)==spec['retained_parent_content_reference'],
         'MORF_ALL_RETAINED_PRIOR_REFERENCE_BYTES_UNCHANGED')
    prior_request_raw=(admitted/'request.json').read_bytes();prior_request=json.loads(prior_request_raw)
    prior_spec_raw=(admitted/'spec.json').read_bytes()
    need(sha(prior_request_raw)==spec['request_sha256'] and sha(prior_spec_raw)==prior_request['predecessor_sha256']
         and digest(json.loads(prior_spec_raw))==json.loads(raw)['parent_spec_sha256'],
         'MORF_ACTUAL_PRIOR_REQUEST_AND_OWN37_BOUNDARY_PRESERVED')
    need(len(prior_request['sources'])==297
         and all(sha((HERE/n).read_bytes())==h for n,h in prior_request['sources'].items()),
         'MORF_ALL297_ACTUAL_ADMITTED_SOURCE_BYTES_UNCHANGED')
    from system_campaign_unconsumed_cash_diagnostics import stopped
    for role,name,meta in [('worker','economic-worker-inspect.json',spec['inspections']['economic-worker-inspect.json']),
                          ('review','independent-review-stop/worker-inspect.json',spec['inspections']['independent-review-stop/worker-inspect.json'])]:
        stopped(json.loads((admitted/name).read_bytes()),dict(stopped=True,oom_killed=False,exit_code=meta['exit_code']),
                role,str(spec['run_id']),'system-campaign-p02-unconsumed2024-cash-request.json')
    need(spec['inspections']['economic-worker-inspect.json']['exit_code']==1
         and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==0,
         'MORF_ACTUAL_ORIGINAL_REFUSAL_AND_SUCCESSFUL_REVIEW_PRESERVED')
    return admitted


def preserve(old,out,spec):
    reference(spec);fn=original.preserve
    need(fn.__closure__ is None,'MORF_EXACT_REFERENCE_STORAGE_WITHOUT_CLOSURE')
    checked=FunctionType(fn.__code__,dict(fn.__globals__,reference=reference,PATH=PATH),fn.__name__,fn.__defaults__)
    return checked(old,out,spec)
