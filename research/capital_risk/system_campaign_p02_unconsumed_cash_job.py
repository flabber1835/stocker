"""One hosted own37 ordinary-cash suffix with unchanged stopped-only export."""
import argparse
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest
from seal import sha256_file
import system_campaign_p02_close_job as original
import system_campaign_p02_pxd_job as prior
from system_campaign_pxd_financial_body import function
from system_campaign_unconsumed_cash_parent import scope, reference, admit, preserve, PATH, SPEC

HERE = Path(__file__).resolve().parent
REQUEST = 'system-campaign-p02-unconsumed2024-cash-request.json'
SOURCES = tuple((*prior.SOURCES, 'system-campaign-p02-pxd-request.json', SPEC,
    'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json',
    'system-campaign-unconsumed2024-cash-registry-extension.json',
    'system_campaign_unconsumed_cash_context.py', 'system_campaign_unconsumed_cash_facts.py',
    'system_campaign_unconsumed_cash_parent.py', 'system_campaign_p02_unconsumed_cash_run.py',
    'system_campaign_p02_unconsumed_cash_job.py', 'system_campaign_unconsumed_cash_diagnostics.py',
    'system_campaign_unconsumed_cash_import_probe.py'))
JOB_SITES = {
    'campaign-factual-transfer-p02-close-suffix': 'campaign-factual-transfer-p02-unconsumed2024-cash',
    'p02-close-financial-output': 'p02-unconsumed2024-cash-output',
    'p02-close-financial-source': 'p02-unconsumed2024-cash-source',
    'p02-close-independent-review': 'p02-unconsumed2024-cash-review',
    'research.system-p02-close-suffix-receipt/1': 'research.system-p02-unconsumed-cash-suffix-receipt/1',
    '/driver/system_campaign_p02_close_run.py': '/driver/system_campaign_p02_unconsumed_cash_run.py',
    '/driver/system-campaign-p02-close-request.json': '/driver/'+REQUEST,
    'p02-close.tar.crseal': 'p02-unconsumed2024-cash.tar.crseal', 1468: 1592,
    'STOPPED_P02_CLOSE_PREFIX_PRESERVED': 'STOPPED_P02_UNCONSUMED_CASH_PREFIX_PRESERVED',
    'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED': 'COMPLETE_P02_UNCONSUMED_CASH_SUFFIX_REVIEWED',
    'PARTIAL_P02_CLOSE_PREFIX_REVIEWED': 'PARTIAL_P02_UNCONSUMED_CASH_PREFIX_REVIEWED',
    'P02_CLOSE_REVIEW_STOP_UNKNOWN': 'P02_UNCONSUMED_CASH_REVIEW_STOP_UNKNOWN',
    'P02_CLOSE_WRITER_STOP_UNKNOWN': 'P02_UNCONSUMED_CASH_WRITER_STOP_UNKNOWN',
    'P02_CLOSE_REFUSED_KNOWN_PREFIX': 'P02_UNCONSUMED_CASH_REFUSED_KNOWN_PREFIX',
    'P02_CLOSE_REFUSED_BEFORE_STOP_PROOF': 'P02_UNCONSUMED_CASH_REFUSED_BEFORE_STOP_PROOF',
}


def expected_request():
    spec = json.loads((HERE/SPEC).read_bytes()); scope(spec)
    value = prior.expected_request()
    value.update(predecessor_file=SPEC, predecessor_sha256=sha256_file(HERE/SPEC),
        execution_mode='RETAINED_EIGHT_MODEL_UNCONSUMED2024_CASH_SUFFIX',
        predecessor_common_basis_sha256=spec['admitted_common_basis_sha256'],
        parent_certificate_rows=spec['parent_certificate_rows'],
        parent_guard_review_sha256=spec['completion_guard_review_sha256'],
        parent_content_reference_sha256=digest(reference(spec)),
        unconsumed_cash_catalog_sha256=sha256_file(HERE/'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json'),
        unconsumed_cash_registry_extension_sha256=sha256_file(HERE/'system-campaign-unconsumed2024-cash-registry-extension.json'),
        diagnostic_driver_sha256=sha256_file(HERE/'system_campaign_unconsumed_cash_diagnostics.py'),
        metadata_import_probe_sha256=sha256_file(HERE/'system_campaign_unconsumed_cash_import_probe.py'),
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def inspect(name, identity=None):
    return function('system_campaign_p02_close_job.py', 'inspect', {
        '/driver/system_campaign_p02_close_run.py': '/driver/system_campaign_p02_unconsumed_cash_run.py',
        '/driver/system-campaign-p02-close-request.json': '/driver/'+REQUEST}, vars(original))(name, identity)


def main(args):
    namespace = dict(vars(original), expected_request=expected_request, admit=admit,
        reference=reference, preserve_content_reference=preserve, REFERENCE_PATH=PATH, inspect=inspect)
    fields = dict(unconsumed_cash_catalog_sha256="request['unconsumed_cash_catalog_sha256']",
                  unconsumed_cash_registry_extension_sha256="request['unconsumed_cash_registry_extension_sha256']",
                  retained_pxd_contract_sha256="request['pxd_contract_sha256']", retained_typed_models='8',
                  qualification_copy_used_as_predecessor='False')
    return function('system_campaign_p02_close_job.py', 'main', JOB_SITES, namespace,
                    expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED': 2}, receipt_fields=fields)(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('request', 'staging', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    main(parser.parse_args())
