"""Fresh campaign baseline segments and exact independently stopped review."""
import argparse,hashlib,json,os,shutil,time
from pathlib import Path
from full_system_core import arguments,initial_repair,hosted,review
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution

def facts(root):
    # Retain the previously verified future MYOV facts under this OWN origin.
    old=initial_repair(root);document=json.loads(old.read_bytes())
    from research.pooled_input_support import inputs
    from research.pooled_vacancy_funding.repair import term_sha256,load_repair
    from research.pooled_vacancy_funding.journal import read_checkpoint
    cp=read_checkpoint(root/'checkpoint.json.gz')
    sid='746303916718780698';rows=[t for t in inputs.load_actions(Path('/frozen/bundle')).terminal.get('2017-07-17',()) if t.security_id==sid]
    need(len(rows)==1 and rows[0].cash_per_share is None and cp['source_cursor']<'2017-07-17','EXACT_FUTURE_PNRA_TERM')
    sec='https://www.sec.gov/Archives/edgar/data/724606/000119312517229854/d425559d8k.htm'
    issuer='https://www.globenewswire.com/news-release/2017/7/18/1047853/0/en/JAB-Completes-Acquisition-of-Panera-Bread-Company.html'
    document['source_evidence']+=[{'reference':sec,'description':'SEC accession0001193125-17-229854: July18 completion,315USD cash per share.','sha256':None},
        {'reference':issuer,'description':'Issuer July18,2017 08:36ET announcement confirms completion before regular open.','sha256':None}]
    document['suppress'].append({'session':'2017-07-17','security_id':sid,'term_sha256':term_sha256(rows[0])})
    document['add'].append({'session':'2017-07-18','security_id':sid,'kind':'CASH_MERGER','cash_per_share':315.,
        'delivered_security_id':None,'delivered_ticker':None,'delivered_issuer_id':None,'exchange_ratio':None,
        'cash_in_lieu_price_per_delivered_share':None,'reference':sec+' | issuer 2017-07-18 08:36ET','entitlement_aggregation':'HOLDER'})
    path=root.parent/'campaign-own-facts.json';save(path,document)
    repair=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    save(root.parent/'campaign-fact-admission.json',{'repair_sha256':repair.sha256,'own_predecessor_inner_sha256':cp['run']['checkpoint_sha256'],
        'own_predecessor_outer_sha256':cp['sha256'],'resume_session':cp['source_cursor'],'consumed_event':False,'old_descriptor_authority_reused':False})
    return path

def run(root,mode):
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.journal import read_checkpoint
    start=time.monotonic();os.environ['FULL_SYSTEM_WARMUP_ONLY']='1'
    try:code=backtest.main(arguments(root))
    finally:os.environ.pop('FULL_SYSTEM_WARMUP_ONLY',None)
    need(code==0,'FRESH_FEATURE_WARMUP');overlay=facts(root)
    with Execution(mode) as execution:code=backtest.main(arguments(root,True,134)+['--repair-overlay',str(overlay)])
    save(root.parent/'acceleration-proof.json',execution.proof());cp=read_checkpoint(root/'checkpoint.json.gz')
    rows=[json.loads(v) for v in (root/'formation.jsonl').read_bytes().splitlines()];daily=[json.loads(v) for v in (root/'daily.jsonl').read_bytes().splitlines()]
    need(code==0 and len(rows)==126 and len(daily)==8 and cp['completed']==8 and cp['source_cursor']=='2018-01-11','COMPLETE_FIRST_BASELINE_SEGMENT')
    pnra=[e for e in cp['run']['state']['ledger']['events'] if e.get('security_id')=='746303916718780698']
    save(root.parent/'campaign-segment.json',{'status':'BASELINE_SEGMENT_COMPLETE_REVIEW_REQUIRED','mode':mode,'formation':126,'measured_closes':8,
        'elapsed_seconds':time.monotonic()-start,'checkpoint_sha256':cp['sha256'],'pnra_ledger_events':pnra,'performance_selected':False,
        'fresh_origin':True,'unknown_prior_branch_recovered':False,'production_contacted':False})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--acceleration',choices=('FAST','REFERENCE'),required=True);a=p.parse_args();hosted()
    if a.mode=='economic':run(Path('/out/book'),a.acceleration)
    else:review(Path('/out/book'),Path('/out/core-review.json'))
