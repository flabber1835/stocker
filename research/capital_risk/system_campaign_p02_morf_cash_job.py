"""One hosted exact own38 MORF suffix; unchanged stop/export fencing."""
import argparse
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest
from seal import sha256_file
import system_campaign_p02_close_job as original
import system_campaign_p02_unconsumed_cash_job as prior
from system_campaign_pxd_financial_body import function
from system_campaign_morf_cash_parent import scope,reference,admit,preserve,PATH,SPEC

HERE=Path(__file__).resolve().parent
REQUEST='system-campaign-p02-morf-cash-request.json'
GATE_RECOVERY=dict(
    schema='research.unadvanced-qualification-harness-recovery/1',
    failed_run_id=41244715485,failed_head='a6b78338a44fc7dbbc8ee67716c799dece967bb8',
    failed_artifact_id=13058837660,failed_artifact_sha256='5dbad31bb652cf41f55297ec413e99b43ef3a0c955fb94104b1be0a426b9a2e9',
    failed_request_sha256='621de3999ada943e82a7a112512b32620c9f0d1e46ebf26f48ad5faf76401548',
    failed_gate_source_sha256='b4e4543b369d9a32a6662df72ef01e92a3ed125fd0312a67344f5a13101641f1',
    unchanged_prefix_review_sha256='ce3516a7d7a167e65490bf7afe0efd17e4679a9bb90e533e49c7098c3c4f1443',
    preserved_failure_log_sha256='cafe14934888c5c442cfc3b5127176058e770670fbe97c576fb75ddc65380a4e',
    selected_outer_sha256='7bf2e6ef8a4679b4948b0de948cd0bec58917c49b69516f3073b904219817340',
    actual_new_financial_rows=0,all154_members_authenticated=True,all309_failed_source_blobs_verified=True,
    entire_financial_state_and_seven_files_including_tails_identical=True,
    morf_overlay_adopted=False,financial_source_conversion=False,new_origin=False,
    correction='Exact standard refusal prefix in the deliberate veto-removal expected-error comparison only')
SOURCES=tuple((*prior.SOURCES,'system-campaign-p02-unconsumed2024-cash-request.json',SPEC,
    'system-campaign-morf-preopen-cash-terminal-facts.json','system-campaign-morf-cash-registry-extension.json',
    'system_campaign_morf_cash_context.py','system_campaign_morf_cash_facts.py','system_campaign_morf_cash_parent.py',
    'system_campaign_morf_cash_gate.py','system_campaign_p02_morf_cash_run.py','system_campaign_p02_morf_cash_job.py',
    'system_campaign_morf_cash_diagnostics.py','system_campaign_morf_cash_import_probe.py'))
JOB_SITES={
    'campaign-factual-transfer-p02-close-suffix':'campaign-factual-transfer-p02-morf-cash',
    'p02-close-financial-output':'p02-morf-cash-output','p02-close-financial-source':'p02-morf-cash-source',
    'p02-close-independent-review':'p02-morf-cash-review',
    'research.system-p02-close-suffix-receipt/1':'research.system-p02-morf-cash-suffix-receipt/1',
    '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p02_morf_cash_run.py',
    '/driver/system-campaign-p02-close-request.json':'/driver/'+REQUEST,
    'p02-close.tar.crseal':'p02-morf-cash.tar.crseal',1468:1655,
    'STOPPED_P02_CLOSE_PREFIX_PRESERVED':'STOPPED_P02_MORF_CASH_PREFIX_PRESERVED',
    'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':'COMPLETE_P02_MORF_CASH_SUFFIX_REVIEWED',
    'PARTIAL_P02_CLOSE_PREFIX_REVIEWED':'PARTIAL_P02_MORF_CASH_PREFIX_REVIEWED',
    'P02_CLOSE_REVIEW_STOP_UNKNOWN':'P02_MORF_CASH_REVIEW_STOP_UNKNOWN',
    'P02_CLOSE_WRITER_STOP_UNKNOWN':'P02_MORF_CASH_WRITER_STOP_UNKNOWN',
    'P02_CLOSE_REFUSED_KNOWN_PREFIX':'P02_MORF_CASH_REFUSED_KNOWN_PREFIX',
    'P02_CLOSE_REFUSED_BEFORE_STOP_PROOF':'P02_MORF_CASH_REFUSED_BEFORE_STOP_PROOF',
}


def expected_request():
    spec=json.loads((HERE/SPEC).read_bytes());scope(spec);value=prior.expected_request()
    need(GATE_RECOVERY['selected_outer_sha256']==spec['outer_sha256']
         and GATE_RECOVERY['actual_new_financial_rows']==0
         and GATE_RECOVERY['entire_financial_state_and_seven_files_including_tails_identical'] is True
         and all(GATE_RECOVERY[k] is False for k in ('morf_overlay_adopted','financial_source_conversion','new_origin')),
         'MORF_HARNESS_RECOVERY_EXACT_UNADVANCED_OWN38')
    value.update(predecessor_file=SPEC,predecessor_sha256=sha256_file(HERE/SPEC),
        execution_mode='RETAINED_EIGHT_MODEL_MORF_PREOPEN_CASH_SUFFIX',
        predecessor_common_basis_sha256=spec['admitted_common_basis_sha256'],
        parent_certificate_rows=spec['parent_certificate_rows'],parent_guard_review_sha256=spec['completion_guard_review_sha256'],
        parent_content_reference_sha256=digest(reference(spec)),actual_refusal_sha256=spec['actual_refusal_sha256'],
        morf_cash_catalog_sha256=sha256_file(HERE/'system-campaign-morf-preopen-cash-terminal-facts.json'),
        morf_cash_registry_extension_sha256=sha256_file(HERE/'system-campaign-morf-cash-registry-extension.json'),
        morf_quote_gate_sha256=sha256_file(HERE/'system_campaign_morf_cash_gate.py'),
        morf_gate_harness_recovery=GATE_RECOVERY,
        diagnostic_driver_sha256=sha256_file(HERE/'system_campaign_morf_cash_diagnostics.py'),
        metadata_import_probe_sha256=sha256_file(HERE/'system_campaign_morf_cash_import_probe.py'),
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def inspect(name,identity=None):
    return function('system_campaign_p02_close_job.py','inspect',{
        '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p02_morf_cash_run.py',
        '/driver/system-campaign-p02-close-request.json':'/driver/'+REQUEST},vars(original))(name,identity)


def main(args):
    namespace=dict(vars(original),expected_request=expected_request,admit=admit,reference=reference,
        preserve_content_reference=preserve,REFERENCE_PATH=PATH,inspect=inspect)
    fields=dict(morf_cash_catalog_sha256="request['morf_cash_catalog_sha256']",
        morf_cash_registry_extension_sha256="request['morf_cash_registry_extension_sha256']",
        morf_quote_gate_sha256="request['morf_quote_gate_sha256']",
        retained_unconsumed_cash_catalog_sha256="request['unconsumed_cash_catalog_sha256']",
        retained_pxd_contract_sha256="request['pxd_contract_sha256']",retained_typed_models='8',
        qualification_copy_used_as_predecessor='False')
    return function('system_campaign_p02_close_job.py','main',JOB_SITES,namespace,
        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2},receipt_fields=fields)(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
