"""Isolated qualification and disposable remainder; no scalar financial replay."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from system_campaign_discovery_context import need,require_strict_checkpoint
from system_campaign_discovery_inputs import retained_inputs
from system_campaign_discovery_parent import scope


def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_discovery_gate import qualify
    from system_campaign_discovery_replay import replay
    spec=scope(json.loads(args.spec.read_bytes()))
    request=json.loads(args.request.read_bytes())
    root=Path('/old');out=Path('/out')
    parent=require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    need(parent['sha256']==spec['outer_sha256'] and parent['source_cursor']==spec['selected_session'],
         'DISCOVERY_ACTUAL_EXACT_OWN41_STRICT_CHECKPOINT')
    with retained_inputs(root,parent,out):
        if args.mode=='qualify':
            qualify(root,parent,out,selected_file=spec['selected_checkpoint'])
        else:
            replay(root,parent,out,selected_file=spec['selected_checkpoint'],
                   strict_admission_sha256=spec['full_client_admission']['admitted_prefix_sha256'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('qualify','discovery'),required=True)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
