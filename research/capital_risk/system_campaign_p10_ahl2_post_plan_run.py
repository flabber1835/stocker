"""Only declared capsule paths; Q reuse and fresh OWN1 suffix stay disjoint."""
import argparse
from pathlib import Path

from system_campaign_p10_ahl2_contract import HERE,SPEC,need,specification,physical_tree
from system_campaign_p10_ahl2_wire import object_bytes
from system_campaign_p10_ahl2_post_plan import worker_raw_request
from system_campaign_p10_ahl2_post_plan_parent import validate_capsule


def main(args):
    from full_system_core import hosted
    hosted()
    spec = specification()
    out,root = Path('/out'),Path('/old')
    need(args.spec == out/'spec.json' and args.request == out/'request.json'
         and args.spec.read_bytes() == (HERE/SPEC).read_bytes(), 'P10_POST_PLAN_EXACT_RAW_SPEC_ENTRYPOINT')
    worker_raw_request(args.request)
    previous,retained = validate_capsule(Path('/previous'),spec)
    physical_tree('/variant',object_bytes((previous/'source-bindings.json').read_bytes()),spec)
    if args.mode == 'qualify':
        from system_campaign_p10_ahl2_post_plan_gate import qualify
        return qualify(root,previous,out,spec,retained=retained)
    if args.mode == 'review':
        from system_campaign_p10_ahl2_post_plan_review import review
        return review(spec,out,'/evidence',previous=previous)
    from system_campaign_p10_ahl2_parent import read_checkpoint
    from system_campaign_parallel_discovery_run import retained_inputs
    from system_campaign_p10_ahl2_epoch import prepare_epoch
    from system_campaign_p10_ahl2_post_plan_gate import qualification_valid
    from system_campaign_p10_ahl2_post_plan_replay import replay
    summary = object_bytes((out/'retained-qualification/qualification-summary.json').read_bytes())
    qualification_valid(summary,spec)
    parent = read_checkpoint(root/spec['financial_strict_predecessor']['selected_checkpoint'])
    with retained_inputs(root,parent,out):
        binding = prepare_epoch(root,previous,out,spec)
        need(binding.run.input_sha256 == summary['successor_input_sha256'],
             'P10_POST_PLAN_FRESH_ORIGINAL_OWN1_INPUT_EQUALS_QUALIFIED_PATH')
        return replay(binding,resume=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('qualify','discovery','review'),required=True)
    for name in ('spec','request'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
