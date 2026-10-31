"""One own-origin canonical Core path plus causal read-only correlation material."""
import argparse,json,os,time
from pathlib import Path
from full_system_core import arguments,hosted,review
from system_campaign_baseline import facts
from system_campaign_qualify import qualify
from system_campaign_observe import Observation
from system_campaign_acceleration import Execution
from full_system_benchmark import need,save

def run(root):
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.journal import read_checkpoint
    binding=json.loads((root.parent/'source-bindings.json').read_bytes());p=binding['parameters']
    profile={'CORE':'wealth-core-v5-zero-share-fixed-2008-v1','C':'wealth-core-capital-risk-c-v1','V':'wealth-core-capital-risk-v-v1'}[p['family']]
    save(root.parent/'canonical-qualification.json',qualify(p,profile))
    args=arguments(root);args[args.index('--policy')+1]=profile
    os.environ['FULL_SYSTEM_WARMUP_ONLY']='1'
    try:code=backtest.main(args)
    finally:os.environ.pop('FULL_SYSTEM_WARMUP_ONLY',None)
    need(code==0,'CAMPAIGN_CANDIDATE_OWN_WARMUP');overlay=facts(root)
    keep=p['v_horizon'] if p['family']=='V' else 21 if p['family']=='C' else 1
    start=time.monotonic()
    with Observation(root.parent/'correlation-inputs.jsonl.gz') as observer:
        with Execution('FAST',signal_closes=keep) as execution:
            args=arguments(root,True);args[args.index('--policy')+1]=profile
            code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(root.parent/'correlation-capture-proof.json',observer.proof());save(root.parent/'acceleration-proof.json',execution.proof())
    cp=read_checkpoint(root/'checkpoint.json.gz')
    save(root.parent/'candidate-outcome.json',{'session':cp['source_cursor'],'completed':cp['completed'],
        'elapsed_financial_seconds':time.monotonic()-start,'complete':cp['completed']==2156 and cp['source_cursor']=='2026-07-31',
        'source_profile_sha256':binding['profile_sha256'],'production_contacted':False})
    need(code==0,'CAMPAIGN_CANDIDATE_REFUSED')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--evidence-root',type=Path);a=p.parse_args();hosted()
    if a.mode=='economic':run(Path('/out/book'))
    else:
        from system_campaign_readonly import review as readonly_review
        need(a.evidence_root==Path('/evidence'),'EXACT_READ_ONLY_EVIDENCE_ROOT')
        readonly_review(a.evidence_root/'book',Path('/out/core-review.json'))
