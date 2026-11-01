"""P01 hosted preflight, actual gate and diagnostic-only chronological fork."""
import argparse,json
from pathlib import Path
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_discovery_gate import qualify
from system_campaign_p01_discovery_parent import scope
from system_campaign_p01_discovery_inputs import retained_inputs,qualify_inputs
from system_campaign_p01_discovery_replay import replay

def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal
    spec=scope(json.loads(args.spec.read_bytes()));request=json.loads(args.request.read_bytes())
    root,out=Path('/old'),Path('/out')
    parent=require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    need(parent['sha256']==spec['outer_sha256'] and parent['source_cursor']=='2019-08-30'
         and parent['completed']==419 and parent['base']==spec['base'], 'P01_EXACT_ADMITTED_STRICT_PARENT')
    with retained_inputs(root,parent,out) as (v1,distribution):
        if args.mode=='qualify':
            from system_campaign_readonly import review as readonly_review
            readonly_review(root/'book',out/'strict-parent-canonical-review.json')
            review=json.loads((out/'strict-parent-canonical-review.json').read_bytes())
            need(review['checkpoint_sha256']==parent['sha256'] and review['counts']==dict(formation=126,daily=419)
                 and review['all_prefixes_verified'] and review['all_daily_factors_and_chains_verified'],
                 'P01_ACTUAL_COMPLETE_OWN_PREFIX_PREFLIGHT')
            for n,c in parent['journals'].items():
                raw=(root/'book'/(n+'.jsonl')).read_bytes()
                need(dict(bytes=len(raw)-c['bytes'],sha256=sha(raw[c['bytes']:]))
                     ==spec['full_client_admission']['unsent_tails_preserved'][n], 'P01_ALL_ORIGINAL_UNSENT_TAIL_BYTES')
            from research.pooled_vacancy_funding import backtest
            objects=[backtest.load_repair(root/'book/repairs'/d['filename'],resume_session=d['resume_session'],
                predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
            qualify_inputs(root,parent,out,objects,v1,distribution)
            qualify(root,parent,out,selected_file=spec['selected_checkpoint'])
        else:
            replay(root,parent,out,selected_file=spec['selected_checkpoint'],
                strict_admission_sha256=spec['full_client_admission']['independent_review_sha256'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','discovery'),required=True)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
