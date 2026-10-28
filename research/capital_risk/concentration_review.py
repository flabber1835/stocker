"""Hosted stopped-book committed-prefix review; partial evidence stays partial."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from core_window_review import require,reconcile,factor,monthly_metrics,near

def committed_prefix(raw,size):
    if type(size) is not int or not 0<=size<=len(raw) or size and raw[size-1:size]!=b'\n':
        raise ValueError('REFUSED_C_QUARTER_PREFIX_LENGTH')
    return raw[:size],dict(bytes=len(raw)-size,sha256=hashlib.sha256(raw[size:]).hexdigest())

def review(root,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    if (backtest.START,backtest.END,backtest.MEASURED_CLOSES)!=('2025-01-02','2025-03-31',60):raise ValueError('REFUSED_C_QUARTER_AXIS')
    saved=read_checkpoint(root/'checkpoint.json.gz');base=saved['base'];full=axis()
    selected=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    require(base['sources']==backtest.source_files(),'REFUSED_C_QUARTER_SOURCES')
    current=selected.index(saved['source_cursor']);require(current>=298,'REFUSED_C_QUARTER_CURSOR')
    journals=('formation','daily','monthly','watch')
    require(all((root/(name+'.jsonl')).is_file() for name in journals),'REFUSED_C_QUARTER_JOURNALS')
    before={name:backtest.file_sha(root/(name+'.jsonl')) for name in journals}
    checkpoints=[root/'checkpoint.json.gz',*sorted((root/'pre-event').glob('*.json.gz')),*sorted((root/'month-end').glob('*.json.gz'))]
    journal=Journal(root,resume=True)
    try:
        for path in checkpoints:
            c=read_checkpoint(path);backtest.validate_checkpoint(c,base,selected)
            restored=runtime.restore(c['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,c['repairs']))
            require(runtime.checkpoint(restored)==c['run'],'REFUSED_C_QUARTER_ROUNDTRIP');journal.verify(c['journals'])
    finally:journal.close()
    committed={};tails={}
    for name in journals:
        raw=(root/(name+'.jsonl')).read_bytes();size=saved['journals'][name]['bytes']
        committed[name],tails[name]=committed_prefix(raw,size)
    prior=None;counts={};ledger_final=None
    for name,wanted,phase in (('formation',selected[299:min(current+1,425)],'FORMATION'),('daily',selected[425:current+1],'MEASURED')):
        rows=[json.loads(x) for x in committed[name].splitlines()];require([r['session'] for r in rows]==wanted,'REFUSED_C_QUARTER_COMMITTED_AXIS')
        for row in rows:
            require(row['phase']==phase,'REFUSED_C_QUARTER_PHASE');audit=row['evidence']['research_entry_audit']
            for key,expected,valuation in (('opening_accounting','OPEN_BEFORE_FILLS','parent_core_open_equity'),('closing_accounting','CLOSE_AFTER_DECISION','parent_core_close_equity')):
                snap=audit[key];require(snap['session']==row['session'] and snap['phase']==expected,'REFUSED_C_QUARTER_ACCOUNTING_BINDING')
                reconcile(snap);near(snap['resolved_equity'],row['economics'][valuation],'REFUSED_C_QUARTER_EQUITY_BINDING')
            factor(prior,row);prior=row['economics']
            ledger_final=audit['closing_accounting']['ledger']
        counts[name]=len(rows)
    require(counts['daily']==saved['completed'],'REFUSED_C_QUARTER_COUNT')
    with tempfile.TemporaryDirectory(prefix='committed-review-',dir=output.parent) as tmp:
        prefix=Path(tmp)
        for name,raw in committed.items():(prefix/(name+'.jsonl')).write_bytes(raw)
        months=monthly_metrics(prefix,backtest.START)
    require(before=={name:backtest.file_sha(root/(name+'.jsonl')) for name in journals},'REFUSED_C_QUARTER_REVIEW_MUTATION')
    complete=saved['source_cursor']==backtest.END and saved['completed']==60
    trim_fills=sum(e['event_type']=='SELL' and e['reason']=='CONCENTRATION_BAND' for e in ledger_final['events']) if ledger_final else 0
    require(not complete or all(t['bytes']==0 for t in tails.values()),'REFUSED_C_QUARTER_COMPLETE_TAIL')
    result=dict(status='C_QUARTER_COMPLETE_REVIEW_PASSED' if complete else 'C_QUARTER_PARTIAL_PREFIX_REVIEW_PASSED',
        complete=complete,source_cursor=saved['source_cursor'],counts=counts,source_checkpoint=saved['sha256'],
        all_checkpoints=len(checkpoints),all_prefixes_verified=True,canonical_roundtrips=True,
        recovered_tails_preserved=tails,monthly_metrics_recomputed=months,trim_fills=trim_fills,
        production_contacted=False,whole_quarter_performance_admitted=complete)
    output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();review(a.root,a.output)
