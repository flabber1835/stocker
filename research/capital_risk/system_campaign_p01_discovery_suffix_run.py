"""One hosted canonical diagnostic suffix from the exact admitted prefix."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_discovery_context import require_strict_checkpoint,digest
from system_campaign_p01_discovery_parent import scope
from system_campaign_p01_discovery_inputs import retained_inputs
from system_campaign_p01_discovery_anchors import RetainedAnchors
from system_campaign_p01_discovery_suffix_parent import specification,validate_contents
from system_campaign_p01_discovery_suffix_replay import replay


def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal,runtime
    root,out,previous=Path('/old'),Path('/out'),Path('/previous')
    financial=scope(json.loads(args.spec.read_bytes()));spec=specification()
    need(json.loads(args.diagnostic_spec.read_bytes())==spec,'P01_SUFFIX_EXACT_MOUNTED_DIAGNOSTIC_SPEC')
    parent=require_strict_checkpoint(journal.read_checkpoint(root/financial['selected_checkpoint']))
    need(parent['sha256']==financial['outer_sha256']==spec['strict_parent_outer_sha256'],
         'P01_SUFFIX_KEEPS_ORIGINAL_STRICT_FINANCIAL_PARENT')
    saved=validate_contents(previous,spec)
    with retained_inputs(root,parent,out):
        run=runtime.restore(saved['runtime_checkpoint'],policy=parent['base']['policy'],
            input_sha256=spec['input_sha256'])
        need(runtime.checkpoint(run)==saved['runtime_checkpoint'],
             'P01_SUFFIX_ACTUAL_DIAGNOSTIC_CANONICAL_RUNTIME_ROUNDTRIP')
        with RetainedAnchors(out,run.state,source_sha256=digest(parent['base']['sources']),
                             input_sha256=run.input_sha256) as anchors:
            replay(root,parent,out,selected_file=financial['selected_checkpoint'],
                strict_admission_sha256=financial['full_client_admission']['independent_review_sha256'],
                previous=previous,spec=spec,anchors=anchors)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('spec','diagnostic-spec','request'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
