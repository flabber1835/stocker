"""Same original discovery transitions, with corrected C/V qualification only."""
import argparse,json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import digest
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_parallel_discovery import specification
from system_campaign_parallel_discovery_run import (main as original_main,retained_inputs,Anchors,iterator)
from system_campaign_risk_discovery_gate import qualify

ARMS=('P09','P10','P11')
CODES={'P09':'REFUSED_TRIM_CURRENT_RAW_MARK','P10':'REFUSED_VOLATILITY_CAUSAL_AXIS','P11':'REFUSED_VOLATILITY_CAUSAL_AXIS'}


def main(args):
    hosted();need(args.arm in ARMS,'RISK_RECOVERY_ONLY_THREE_UNSTARTED_DISCOVERIES')
    if args.mode=='discovery':return original_main(args)
    from research.pooled_vacancy_funding import journal,runtime
    from system_campaign_parallel_discovery import check_parent
    spec=specification(args.arm);need(json.loads(args.spec.read_bytes())==spec,'RISK_RECOVERY_EXACT_ORIGINAL_PARENT')
    root,out=Path('/old'),Path('/out');parent=require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    check_parent(parent,spec)
    with retained_inputs(root,parent,out):
        run=runtime.restore(parent['run'],policy=parent['base']['policy'],input_sha256=parent['run']['input_sha256'])
        need(runtime.checkpoint(run)==parent['run'],'RISK_RECOVERY_ACTUAL_OWN_PARENT_ROUNDTRIP')
        with Anchors(out,run.state,source_sha256=digest(parent['base']['sources']),input_sha256=parent['run']['input_sha256'],
            expected_adapter_sha256=parent['base']['sources']['research/pooled_input_support/adapter.py']) as anchors:
            qualify(root,parent,out,selected_file=spec['selected_checkpoint'],source_iterator=iterator(anchors),code=CODES[args.arm])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    p.add_argument('--mode',choices=('qualify','discovery'),required=True);p.add_argument('--spec',type=Path,required=True)
    main(p.parse_args())
