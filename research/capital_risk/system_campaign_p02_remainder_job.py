"""One serial exact financial suffix; unchanged worker/stop/export fences."""
import argparse
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest
from system_campaign_pxd_financial_body import function
from seal import sha256_file
from system_campaign_remainder_parent import SPEC, SPEC_SHA, PATH, scope, reference, admit, preserve
import system_campaign_p02_close_job as original
import system_campaign_p02_winter2025_cash_job as prior
from system_campaign_discovery_job import SOURCES as RETAINED

HERE = Path(__file__).resolve().parent
REQUEST = 'system-campaign-p02-remainder-request.json'
SOURCES = tuple(dict.fromkeys((*RETAINED, 'system-campaign-p02-discovery-request.json',
    'system-campaign-remainder-terminal-facts.json', 'system_campaign_remainder_input.py',
    'system_campaign_remainder_facts.py', 'system_campaign_remainder_sensor.py',
    'system_campaign_remainder_gate.py', 'system_campaign_remainder_parent.py',
    'system_campaign_remainder_review.py', 'system_campaign_p02_remainder_run.py',
    'system_campaign_p02_remainder_job.py', 'system_campaign_remainder_import_probe.py')))
SITES = {
    'campaign-factual-transfer-p02-close-suffix': 'campaign-factual-transfer-p02-remainder',
    'p02-close-financial-output': 'p02-remainder-financial-output',
    'p02-close-financial-source': 'p02-remainder-financial-source',
    'p02-close-independent-review': 'p02-remainder-independent-review',
    'research.system-p02-close-suffix-receipt/1': 'research.system-p02-remainder-suffix-receipt/1',
    '/driver/system_campaign_p02_close_run.py': '/driver/system_campaign_p02_remainder_run.py',
    '/driver/system-campaign-p02-close-request.json': '/driver/' + REQUEST,
    'p02-close.tar.crseal': 'p02-remainder.tar.crseal', 1468: 1842,
    'STOPPED_P02_CLOSE_PREFIX_PRESERVED': 'STOPPED_P02_REMAINDER_PREFIX_PRESERVED',
    'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED': 'COMPLETE_P02_REMAINDER_SUFFIX_REVIEWED',
    'PARTIAL_P02_CLOSE_PREFIX_REVIEWED': 'PARTIAL_P02_REMAINDER_PREFIX_REVIEWED',
    'P02_CLOSE_REVIEW_STOP_UNKNOWN': 'P02_REMAINDER_REVIEW_STOP_UNKNOWN',
    'P02_CLOSE_WRITER_STOP_UNKNOWN': 'P02_REMAINDER_WRITER_STOP_UNKNOWN',
    'P02_CLOSE_REFUSED_KNOWN_PREFIX': 'P02_REMAINDER_REFUSED_KNOWN_PREFIX',
    'P02_CLOSE_REFUSED_BEFORE_STOP_PROOF': 'P02_REMAINDER_REFUSED_BEFORE_STOP_PROOF',
}


def expected_request():
    spec = scope(json.loads((HERE / SPEC).read_bytes()))
    result = prior.expected_request()
    result.update(predecessor_file=SPEC, predecessor_sha256=SPEC_SHA,
        execution_mode='RETAINED_EIGHT_MODELS_AND_REMAINDER_TERMINALS',
        predecessor_common_basis_sha256=spec['admitted_common_basis_sha256'],
        parent_certificate_rows=spec['parent_certificate_rows'],
        parent_guard_review_sha256=spec['completion_guard_review_sha256'],
        parent_content_reference_sha256=digest(reference(spec)), actual_refusal_sha256=spec['actual_refusal_sha256'],
        financial_wait_seconds=12600, review_wait_seconds=2400,
        remainder_catalog_sha256=sha256_file(HERE / 'system-campaign-remainder-terminal-facts.json'),
        remainder_input_parser_sha256=sha256_file(HERE / 'system_campaign_remainder_input.py'),
        remainder_sensor_sha256=sha256_file(HERE / 'system_campaign_remainder_sensor.py'),
        remainder_gate_sha256=sha256_file(HERE / 'system_campaign_remainder_gate.py'),
        metadata_import_probe_sha256=sha256_file(HERE / 'system_campaign_remainder_import_probe.py'),
        sources={name: sha256_file(HERE / name) for name in SOURCES})
    return result


def inspect(name, identity=None):
    return function('system_campaign_p02_close_job.py', 'inspect', {
        '/driver/system_campaign_p02_close_run.py': '/driver/system_campaign_p02_remainder_run.py',
        '/driver/system-campaign-p02-close-request.json': '/driver/' + REQUEST}, vars(original))(name, identity)


def main(args):
    namespace = dict(vars(original), expected_request=expected_request, admit=admit,
        reference=reference, preserve_content_reference=preserve, REFERENCE_PATH=PATH, inspect=inspect)
    return function('system_campaign_p02_close_job.py', 'main', SITES, namespace,
        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED': 2}, receipt_fields=dict(
            remainder_catalog_sha256="request['remainder_catalog_sha256']",
            remainder_input_parser_sha256="request['remainder_input_parser_sha256']",
            remainder_sensor_sha256="request['remainder_sensor_sha256']",
            remainder_gate_sha256="request['remainder_gate_sha256']",
            retained_typed_models='8', new_distinct_input_models='1',
            discovery_checkpoint_used='False'))(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('request', 'staging', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
