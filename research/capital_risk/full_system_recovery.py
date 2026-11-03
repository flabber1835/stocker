"""Hosted factual PNRA suffix recovery; no source or financial parameter changes."""
import argparse,gzip,hashlib,json,os,shutil,time
from datetime import datetime,timezone
from pathlib import Path
from full_system_core import arguments,hosted,review
from full_system_benchmark import need,save

SID='746303916718780698'
SEC='https://www.sec.gov/Archives/edgar/data/724606/000119312517229854/d425559d8k.htm'
ISSUER='https://www.globenewswire.com/news-release/2017/7/18/1047853/0/en/JAB-Completes-Acquisition-of-Panera-Bread-Company.html'

def prepare(root):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_input_support import inputs
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_vacancy_funding.repair import load_repair,term_sha256
    spec=json.loads((root.parent/'recovery-spec.json').read_bytes())
    old=read_checkpoint(root/'checkpoint.json.gz');lineage=root.parent/'prior-branch';lineage.mkdir()
    review(root,lineage/'predecessor-review.json')
    for name in ('checkpoint.json.gz','failed-canonical-state.json.gz','result.json'):
        if (root/name).exists():shutil.copyfile(root/name,lineage/name)
    selected=root/spec['selected_checkpoint'];need(backtest.file_sha(selected)==spec['selected_file_sha256'],'OWN_EXACT_SELECTED_FILE')
    cp=read_checkpoint(selected)
    need(cp['sha256']==spec['outer_sha256'] and cp['source_cursor']==spec['cursor']<'2017-07-17','OWN_EXACT_PRE_EVENT_CURSOR')
    need(cp['run']['checkpoint_sha256']==spec['inner_sha256'] and cp['run']['state_sha256']==spec['state_sha256']
        and cp['run']['input_sha256']==spec['input_sha256'] and cp['base']['sources']==backtest.source_files(),'OWN_EXACT_SELECTED_BINDINGS')
    restored=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(restored)==cp['run'],'OWN_SELECTED_CANONICAL_ROUNDTRIP')
    j=Journal(root,resume=True)
    try:
        j.verify(old['journals']);j.verify(cp['journals'])
    finally:j.close()
    tails={}
    for name,commitment in cp['journals'].items():
        raw=(root/(name+'.jsonl')).read_bytes();tail=raw[commitment['bytes']:]
        tails[name]={'bytes':len(tail),'sha256':hashlib.sha256(tail).hexdigest()}
    need(tails==spec['tails'],'EXACT_UNSENT_TAILS')
    terms=[t for t in inputs.load_actions(Path('/frozen/bundle')).terminal.get('2017-07-17',()) if t.security_id==SID]
    need(len(terms)==1 and terms[0].cash_per_share is None,'EXACT_INCOMPLETE_PNRA_TERM')
    evidence=[{'reference':SEC,'description':'SEC 8-K accession 0001193125-17-229854: July 18 completion; 315 USD cash per share.','sha256':None},
        {'reference':ISSUER,'description':'Issuer release July 18 2017 at 08:36 ET confirms transaction completed and stock ceases trading that day, before regular open.','sha256':None}]
    document={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
        'source_evidence':evidence,'suppress':[{'session':'2017-07-17','security_id':SID,'term_sha256':term_sha256(terms[0])}],
        'add':[{'session':'2017-07-18','security_id':SID,'kind':'CASH_MERGER','cash_per_share':315.,
        'delivered_security_id':None,'delivered_ticker':None,'delivered_issuer_id':None,'exchange_ratio':None,
        'cash_in_lieu_price_per_delivered_share':None,'reference':SEC+' | issuer release 2017-07-18 08:36 ET','entitlement_aggregation':'HOLDER'}]}
    retained={d['sha256'] for d in cp['repairs']}
    for descriptor in old['repairs']:
        if descriptor['sha256'] in retained:continue
        raw=root/'repairs'/descriptor['filename'];need(backtest.file_sha(raw)==descriptor['sha256'],'RETAINED_MYOV_BYTES')
        previous=json.loads(raw.read_bytes())
        need(previous['suppress'] and previous['add'] and all(r['session']>'2023-03-01' for r in previous['suppress']+previous['add']),
            'ONLY_UNCONSUMED_MYOV_FACT_REBINDING')
        document['suppress']+=previous['suppress'];document['add']+=previous['add'];document['source_evidence']+=previous['source_evidence']
    path=root.parent/'own-pnra-successor.json';save(path,document)
    repair=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for wrong in ('0'*64,):
        try:load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=wrong)
        except ValueError:pass
        else:raise ValueError('WRONG_PREDECESSOR_FALSIFIER')
    try:load_repair(path,resume_session='2017-07-17',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    except ValueError:pass
    else:raise ValueError('CONSUMED_SESSION_FALSIFIER')
    # The entire failed branch is retained in the authenticated previous artifact.
    # Only checkpoints at/before the selected prefix belong to this continuing branch.
    for folder in ('pre-event','month-end','predecessor-checkpoints'):
        for candidate in list((root/folder).glob('*.json.gz')):
            value=read_checkpoint(candidate)
            if value['source_cursor']>cp['source_cursor']:
                target=lineage/folder/candidate.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.move(candidate,target)
    need(backtest.file_sha(selected)==spec['selected_file_sha256'],'SELECTED_PREDECESSOR_PRESERVED')
    shutil.copyfile(selected,root/'checkpoint.json.gz')
    save(root.parent/'recovery-admission.json',{'own_predecessor':spec,'unchanged_financial_source':True,
        'all_old_prefixes_verified':True,'canonical_roundtrip':True,'falsifiers_passed':True,'repair_sha256':repair.sha256,
        'old_current_checkpoint_sha256':old['sha256'],'production_contacted':False})
    return path,cp,tails

def economic(root):
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.retries import RetryStats
    path,cp,tails=prepare(root)
    original=RetryStats.advance;observations=[];costs=[]
    saved_functions={name:getattr(backtest,name) for name in ('checkpoint_value','write_checkpoint')}
    def wrap(name):
        def timed(*a,**k):
            start=time.monotonic()
            try:return saved_functions[name](*a,**k)
            finally:costs.append({'operation':name,'start':start,'end':time.monotonic()})
        return timed
    def observe(*a,**k):
        result=original(*a,**k);observations.append(time.monotonic());return result
    for name in saved_functions:setattr(backtest,name,wrap(name))
    RetryStats.advance=observe
    try:
        code=backtest.main(arguments(root,True)+['--repair-overlay',str(path)])
    finally:
        RetryStats.advance=original
        for name,fn in saved_functions.items():setattr(backtest,name,fn)
        save(root.parent/'phase-timing.json',{'advance_completions':observations,'checkpoint_components':costs,
            'formation_checkpoint_cost_not_extrapolated_to_all_measured_days':True,'hard_deadline_utc':'2026-10-29T17:57:00Z'})
    # Journal.recover must have archived, rather than lost, every unsent tail.
    recovered={}
    for name,spec in tails.items():
        candidates=[p for p in root.glob('interrupted-'+name+'-*.jsonl') if p.is_file() and p.stat().st_size==spec['bytes']
            and hashlib.sha256(p.read_bytes()).hexdigest()==spec['sha256']] if spec['bytes'] else []
        need(not spec['bytes'] or candidates,'ACTUAL_RECOVERED_TAIL_PRESERVATION')
        recovered[name]={**spec,'verified':True,'paths':[str(p.relative_to(root)) for p in candidates]}
    save(root.parent/'actual-tail-preservation.json',recovered)
    return code

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);a=p.parse_args();hosted()
    if a.mode=='economic':raise SystemExit(economic(Path('/out/book')))
    review(Path('/out/book'),Path('/out/core-review.json'))
