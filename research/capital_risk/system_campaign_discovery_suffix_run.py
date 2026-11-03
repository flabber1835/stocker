"""Hosted-only entrypoint restoring the exact admitted diagnostic runtime."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_discovery_context import require_strict_checkpoint, digest
from system_campaign_parallel_discovery import check_parent
from system_campaign_parallel_discovery_run import retained_inputs
from system_campaign_discovery_suffix_parent import specification, validate_contents
from system_campaign_discovery_suffix_replay import Anchors, replay


def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal, runtime
    spec = specification(args.arm); financial = spec['financial_strict_predecessor']
    need(json.loads(args.spec.read_bytes()) == spec, 'SUFFIX_EXACT_MOUNTED_OWN_SPEC')
    root, out, previous = Path('/old'), Path('/out'), Path('/previous')
    parent = require_strict_checkpoint(journal.read_checkpoint(root / financial['selected_checkpoint']))
    check_parent(parent, financial)
    saved = validate_contents(previous, spec)
    need((root / 'source-bindings.json').read_bytes() == (previous / 'source-bindings.json').read_bytes(),
         'SUFFIX_DIAGNOSTIC_SOURCE_IDENTICAL_TO_DISTINCT_ORIGINAL_FINANCIAL_SOURCE')
    factory = None
    if args.arm in ('P06', 'P07'):
        from system_campaign_discovery_spinoff_deferral import context_class
        factory = lambda base: context_class(base, expected_first=spec['first_expected_unresolved'])
    with retained_inputs(root, parent, out):
        run = runtime.restore(saved['runtime_checkpoint'], policy=parent['base']['policy'], input_sha256=spec['input_sha256'])
        need(runtime.checkpoint(run) == saved['runtime_checkpoint'], 'SUFFIX_ACTUAL_CANONICAL_DIAGNOSTIC_RUNTIME_ROUNDTRIP')
        with Anchors(out, run.state, source_sha256=digest(parent['base']['sources']), input_sha256=run.input_sha256,
            expected_adapter_sha256=parent['base']['sources']['research/pooled_input_support/adapter.py'],
            previous=previous, saved=saved) as anchors:
            replay(root, parent, out, selected_file=financial['selected_checkpoint'],
                strict_admission_sha256=saved['strict_client_admission_sha256'],
                previous=previous, spec=spec, anchors=anchors, context_class=factory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--arm', required=True)
    for name in ('spec', 'request'): parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
