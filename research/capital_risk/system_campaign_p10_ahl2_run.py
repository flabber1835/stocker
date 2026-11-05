"""One hosted P10 qualification/fresh diagnostic/review entrypoint."""
import argparse
import json
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import (HERE, SPEC, TAINT, need, sha, specification, physical_tree)
from system_campaign_p10_ahl2_epoch import prepare_epoch


def main(args):
    from full_system_core import hosted
    hosted()
    spec = specification()
    out, root, previous = Path('/out'), Path('/old'), Path('/previous')
    need(args.spec == out / 'spec.json' and args.request == out / 'request.json'
         and args.spec.read_bytes() == (HERE / SPEC).read_bytes(), 'P10_EXACT_RAW_SPEC_REQUEST_ENTRYPOINT')
    request = json.loads(args.request.read_bytes())
    from system_campaign_p10_ahl2_job import expected_request
    need(request == expected_request(), 'P10_ALL_REQUEST_SOURCE_BYTES_AND_BOUNDED_SCOPE')
    physical_tree('/variant', json.loads((previous / 'source-bindings.json').read_bytes()), spec)
    if args.mode == 'qualify':
        from system_campaign_p10_ahl2_gate import qualify
        return qualify(root, previous, out, spec)
    if args.mode == 'review':
        from system_campaign_p10_ahl2_review import review
        return review(spec, out, '/evidence')
    from system_campaign_p10_ahl2_parent import read_checkpoint
    from system_campaign_parallel_discovery_run import retained_inputs
    from system_campaign_p10_ahl2_gate import qualification_valid
    from system_campaign_p10_ahl2_replay import replay
    proof = out / 'retained-qualification/qualification-summary.json'
    qualification_valid(json.loads(proof.read_bytes()), spec)
    parent = read_checkpoint(root / spec['financial_strict_predecessor']['selected_checkpoint'])
    with retained_inputs(root, parent, out):
        binding = prepare_epoch(root, previous, out, spec)
        need(binding.run.input_sha256 == json.loads(proof.read_bytes())['successor_input_sha256'],
             'P10_FRESH_CP1_ZERO_INPUT_EQUALS_EXACT_CHANGED_QUALIFIER')
        return replay(binding)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('qualify', 'discovery', 'review'), required=True)
    for name in ('spec', 'request'):
        p.add_argument('--' + name, type=Path, required=True)
    main(p.parse_args())
