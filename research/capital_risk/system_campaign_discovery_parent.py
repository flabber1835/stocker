"""Exact own41 financial parent of a separately tainted diagnostic fork."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_pxd_financial_body import function
import system_campaign_content_reference as reference_source
import system_campaign_factual_admit as crypto

SPEC='system-campaign-p02-discovery-predecessor.json'
SPEC_SHA='210886f9bce15c0187b2fc36c26c8388504d5c604150ea0a0f8ce8f8d072bfad'
PATH='lineage/discovery-strict-parent-reference.json'


def scope(spec):
    need(sha((json.dumps(spec,sort_keys=True,indent=2)+'\n').encode())==SPEC_SHA,
         'DISCOVERY_EXACT_PUBLIC_STRICT_PARENT')
    need(spec['run_id']==41256802322 and spec['artifact_id']==13064935129
         and spec['head']=='8423b5bd9bb3e7aba7657e7d119816892c71b1ba'
         and spec['selected_session']=='2025-04-30' and spec['measured_closes']==1842
         and len(spec['repairs'])==41 and spec['parent_certificate_rows']==1388
         and spec['outer_sha256']=='1f8b47018ffe4f2c09bd9d1c58e49fd2162559ae2c665a5c711f73072f08868c',
         'DISCOVERY_ONLY_ADMITTED_OWN41_NOT_MAY_DIAGNOSTIC_CURSOR')
    full=spec['full_client_admission']
    need(full['admitted_prefix_sha256']=='d0070f26e123b33b30f7add8a36ae07f072bd58e53c3b8295d3c78ae22fb62c0'
         and full['all226_actual_members_readback_verified'] is True
         and full['every_actual_financial_factor_chain_and_controller_branch_verified'] is True
         and full['all_original_and_current_checkpoint_prefixes_and_tails_verified'] is True
         and full['all_eight_original_model_semantics_unchanged'] is True
         and full['accounting_snapshots']==3936 and full['monthly_reports_all_four_series']==88
         and full['qualification_copy_used_as_predecessor'] is False,
         'DISCOVERY_FULL_INDEPENDENT_STRICT_FINANCIAL_ADMISSION')
    return spec


def reference(spec):
    scope(spec)
    return function('system_campaign_content_reference.py','reference',{
        'research.system-p02-uncertainty-suffix-receipt/1':'research.system-p02-winter2025-cash-suffix-receipt/1'},
        vars(reference_source))(spec)


def admit(spec,root,key):
    scope(spec)
    need(sha(Path(crypto.__file__).read_bytes())=='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'DISCOVERY_ORIGINAL_COMPLETE_ZIP_CIPHER_GCM_INVENTORY_ADMISSION')
    value=crypto.admit(spec,root,key,max_zip_bytes=512*1024**2)
    request=json.loads((value/'request.json').read_bytes())
    need(len(request['sources'])==333 and all(sha((Path(__file__).parent/n).read_bytes())==h
         for n,h in request['sources'].items()),'DISCOVERY_ALL333_ADMITTED_DRIVER_BYTES_UNCHANGED')
    return value
