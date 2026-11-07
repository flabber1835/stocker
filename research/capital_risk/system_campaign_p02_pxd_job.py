"""One exact P02 financial suffix, with three separately authenticated authorities."""
import argparse
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest
from seal import sha256_file
import system_campaign_p02_close_job as original
from system_campaign_pxd_qualification_job import SOURCES as PRIOR
from system_campaign_pxd_financial_body import function
from system_campaign_pxd_financial_parent import scope,reference,admit,preserve,PATH

HERE=Path(__file__).resolve().parent
REQUEST='system-campaign-p02-pxd-request.json'
SOURCES=tuple((*PRIOR,'system-campaign-pxd-qualification-request.json',
    'system-campaign-pxd-qualified-component.json','system-campaign-p02-pxd-predecessor.json',
    'system_campaign_pxd_financial_parent.py','system_campaign_pxd_financial_body.py',
    'system_campaign_p02_pxd_run.py','system_campaign_p02_pxd_job.py',
    'system_campaign_pxd_financial_diagnostics.py','system_campaign_pxd_financial_import_probe.py'))
JOB_SITES={
    'campaign-factual-transfer-p02-close-suffix':'campaign-factual-transfer-p02-pxd-suffix',
    'p02-close-financial-output':'p02-pxd-financial-output',
    'p02-close-financial-source':'p02-pxd-financial-source',
    'p02-close-independent-review':'p02-pxd-independent-review',
    'research.system-p02-close-suffix-receipt/1':'research.system-p02-pxd-suffix-receipt/1',
    '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p02_pxd_run.py',
    '/driver/system-campaign-p02-close-request.json':'/driver/'+REQUEST,
    'p02-close.tar.crseal':'p02-pxd.tar.crseal',1468:1592,
    'STOPPED_P02_CLOSE_PREFIX_PRESERVED':'STOPPED_P02_PXD_PREFIX_PRESERVED',
    'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':'COMPLETE_P02_PXD_SUFFIX_REVIEWED',
    'PARTIAL_P02_CLOSE_PREFIX_REVIEWED':'PARTIAL_P02_PXD_PREFIX_REVIEWED',
    'P02_CLOSE_REVIEW_STOP_UNKNOWN':'P02_PXD_REVIEW_STOP_UNKNOWN',
    'P02_CLOSE_WRITER_STOP_UNKNOWN':'P02_PXD_WRITER_STOP_UNKNOWN',
    'P02_CLOSE_REFUSED_KNOWN_PREFIX':'P02_PXD_REFUSED_KNOWN_PREFIX',
    'P02_CLOSE_REFUSED_BEFORE_STOP_PROOF':'P02_PXD_REFUSED_BEFORE_STOP_PROOF',
}


def expected_request():
    name='system-campaign-p02-pxd-predecessor.json'
    spec=json.loads((HERE/name).read_bytes());_,_,qualified=scope(spec)
    value=original.expected_request()
    value.update(predecessor_file=name,predecessor_sha256=sha256_file(HERE/name),
        execution_mode='RETAINED_SEVEN_MODELS_UNOWNED_PXD_SUFFIX',
        predecessor_common_basis_sha256=spec['admitted_common_basis_sha256'],
        parent_certificate_rows=spec['parent_certificate_rows'],
        parent_guard_review_sha256=spec['completion_guard_review_sha256'],
        parent_content_reference_sha256=digest(reference(spec)),
        pxd_contract_sha256=sha256_file(HERE/'system-campaign-pxd-preopen-contract.json'),
        qualified_pxd_overlay_sha256=qualified['qualified_overlay_sha256'],
        qualified_pxd_component_run_id=qualified['run_id'],
        qualified_pxd_component_artifact_id=qualified['artifact_id'],
        qualified_pxd_component_sha256=sha256_file(HERE/spec['qualified_component_file']),
        actual_refusal_sha256='37509e8a74abef8a13f37c252a10773b7fcc5181e690b9dbd9fc9d472eaf6b50',
        diagnostic_driver_sha256=sha256_file(HERE/'system_campaign_pxd_financial_diagnostics.py'),
        metadata_import_probe_sha256=sha256_file(HERE/'system_campaign_pxd_financial_import_probe.py'),
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def inspect(name,identity=None):
    return function('system_campaign_p02_close_job.py','inspect',{
        '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p02_pxd_run.py',
        '/driver/system-campaign-p02-close-request.json':'/driver/'+REQUEST},vars(original))(name,identity)


def main(args):
    namespace=dict(vars(original),expected_request=expected_request,admit=admit,
        reference=reference,preserve_content_reference=preserve,REFERENCE_PATH=PATH,inspect=inspect)
    fields=dict(pxd_contract_sha256="request['pxd_contract_sha256']",
                qualified_pxd_overlay_sha256="request['qualified_pxd_overlay_sha256']",
                qualified_pxd_component_run_id="request['qualified_pxd_component_run_id']",
                qualified_pxd_component_artifact_id="request['qualified_pxd_component_artifact_id']",
                composite_financial_predecessor=True,qualification_copy_used_as_predecessor=False)
    fields={key:(str(value) if isinstance(value,bool) else value) for key,value in fields.items()}
    return function('system_campaign_p02_close_job.py','main',JOB_SITES,namespace,
        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2},receipt_fields=fields)(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
