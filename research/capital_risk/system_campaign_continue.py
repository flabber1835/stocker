"""Continue official B/B0 books from their own authenticated committed cursor."""
import argparse,json
from pathlib import Path
from full_system_core import hosted,arguments,review
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_predecessor import preserve

def run(root,mode):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    spec=json.loads((root.parent/'continuation-predecessor.json').read_bytes())
    cp=read_checkpoint(root/'checkpoint.json.gz');need(cp['sha256']==spec['outer_sha256'],'CONTINUE_OWN_PREDECESSOR')
    full=axis();wanted=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    backtest.validate_checkpoint(cp,cp['base'],wanted)
    need(cp['base']['sources']==backtest.source_files(),'CONTINUE_IDENTICAL_SOURCES')
    restored=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(restored)==cp['run'],'CONTINUE_CANONICAL_ROUNDTRIP')
    j=Journal(root,resume=True)
    try:j.verify(cp['journals'])
    finally:j.close()
    need(wanted[wanted.index(cp['source_cursor'])+1]=='2018-01-12','CONTINUE_EXACT_ADJACENCY')
    save(root.parent/'continuation-preflight.json',{'canonical_roundtrip':True,'all_prefixes_verified':True,
        'exact_predecessor_outer_sha256':cp['sha256'],'exact_next_session':'2018-01-12','source_conversion':False,'fresh_origin':False})
    with Execution(mode) as execution:code=backtest.main(arguments(root,True))
    save(root.parent/'acceleration-proof.json',execution.proof())
    save(root.parent/'predecessor-prefix-preservation.json',preserve(root,spec))
    current=read_checkpoint(root/'checkpoint.json.gz')
    save(root.parent/'campaign-segment.json',{'status':'CONTINUATION_STOPPED_REVIEW_REQUIRED','session':current['source_cursor'],
        'completed':current['completed'],'mode':mode,'fresh_origin':False,'source_conversion':False,'production_contacted':False})
    need(code==0,'CONTINUATION_REFUSED')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--acceleration',choices=('FAST','REFERENCE'),required=True);a=p.parse_args();hosted()
    if a.mode=='economic':run(Path('/out/book'),a.acceleration)
    else:
        root=Path('/out/book');spec=json.loads((root.parent/'continuation-predecessor.json').read_bytes())
        review(root,Path('/out/core-review.json'));save(Path('/out/reviewed-predecessor-prefix-preservation.json'),preserve(root,spec))
