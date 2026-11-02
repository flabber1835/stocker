"""Stopped pilot prefix/canonical/accounting review; no market session advancement."""
import argparse
from decimal import localcontext
import hashlib
import json
import math
from pathlib import Path
from statistics import mean,median

from core_window_review import reconcile,factor
from core_lineage_review import review_lineage


def require(value,code):
    if not value:raise ValueError(code)


def review(root,lineage,timings,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    before={p.name:backtest.file_sha(p) for p in root.iterdir() if p.is_file()}
    saved=read_checkpoint(root/'checkpoint.json.gz');base=saved['base'];full=axis()
    selected=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    count=selected.index(saved['source_cursor'])-298
    require(0<=count<=5 and saved['completed']==0 and saved['stats'] is None and saved['spy_base'] is None,
        'REFUSED_PILOT_SCOPE')
    require(base['policy']=='wealth-core-v5-zero-share-fixed-2008-v1' and backtest.START=='2021-01-04'
        and base['sources']==backtest.source_files(),'REFUSED_PILOT_SOURCE_OR_POLICY')
    lineage_proof=review_lineage(root,lineage,backtest,runtime,axis)
    journal=Journal(root,resume=True);retained=0;uncommitted=[]
    try:
        for p in root.rglob('*.json.gz'):
            if p.name=='failed-canonical-state.json.gz':
                uncommitted.append(dict(name=p.relative_to(root).as_posix(),sha256=backtest.file_sha(p)));continue
            c=read_checkpoint(p);backtest.validate_checkpoint(c,base,selected)
            restored=runtime.restore(c['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,c['repairs']))
            require(runtime.checkpoint(restored)==c['run'],'REFUSED_PILOT_CANONICAL_ROUNDTRIP')
            journal.verify(c['journals']);retained+=1
        journal.verify(saved['journals'])
    finally:journal.close()
    tails={};records={}
    for name,v in saved['journals'].items():
        raw=(root/(name+'.jsonl')).read_bytes();require(len(raw)>=v['bytes'],'REFUSED_PILOT_SHORT_JOURNAL')
        prefix,tail=raw[:v['bytes']],raw[v['bytes']:]
        records[name]=[json.loads(x) for x in prefix.splitlines()]
        tails[name]=dict(bytes=len(tail),sha256=hashlib.sha256(tail).hexdigest())
    require(not records['daily'] and not records['monthly'],'REFUSED_MEASURED_PILOT_RECORDS')
    require([r['session'] for r in records['formation']]==selected[299:299+count]
        and saved['retries']['transitions']==count,'REFUSED_PILOT_FORMATION_AXIS')
    prior=None
    with localcontext() as context:
        context.prec=50
        for row in records['formation']:
            require(row['phase']=='FORMATION','REFUSED_PILOT_PHASE')
            audit=row['evidence']['research_entry_audit']
            for key in ('opening_accounting','closing_accounting'):reconcile(audit[key])
            factor(prior,row);prior=row['economics']
    timing_rows=[];timing_tail=b''
    if timings.exists():
        raw=timings.read_bytes()
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'):timing_tail=line;break
            value=json.loads(line)
            require(all(isinstance(value[k],(float,int)) and math.isfinite(value[k]) and value[k]>=0
                for k in ('wall_seconds','cpu_seconds')),'REFUSED_PILOT_CLOCK')
            timing_rows.append(value)
    grouped={}
    for row in timing_rows:
        values=grouped.setdefault(row['label'],[])
        require(row['ordinal']==len(values),'REFUSED_PILOT_TIMING_ORDINAL');values.append(row)
    transitions=grouped.get('canonical_transition',[])
    committed_timings=transitions[:count]
    stats={}
    for label,rows in grouped.items():
        wall=[v['wall_seconds'] for v in rows]
        stats[label]=dict(observations=len(rows),wall_total=sum(wall),wall_mean=mean(wall),wall_median=median(wall),
            wall_min=min(wall),wall_max=max(wall),cpu_total=sum(v['cpu_seconds'] for v in rows))
    require(before=={p.name:backtest.file_sha(p) for p in root.iterdir() if p.is_file()},'REFUSED_PILOT_REVIEW_MUTATION')
    result=dict(schema='research.capital-risk-timing-pilot-review/1',status='TIMING_PILOT_PREFIX_REVIEW_PASSED',
        formation_transitions=count,measured_closes=0,source_cursor=saved['source_cursor'],canonical_checkpoints=retained,
        canonical_roundtrips=True,all_journal_prefixes_verified=True,preserved_tails=tails,uncommitted_snapshots=uncommitted,
        independent_accounting_rows=count,lineage=lineage_proof,checkpoint_bytes=(root/'checkpoint.json.gz').stat().st_size,
        checkpoint_file_sha256=backtest.file_sha(root/'checkpoint.json.gz'),checkpoint_outer=saved['sha256'],
        timing_categories=stats,committed_transition_timings=committed_timings,
        committed_timings_complete=len(committed_timings)==count,timing_tail_bytes=len(timing_tail),
        profiling_overhead_included=True,categories_overlap=True,performance_claim=False)
    output.write_text(json.dumps(result,indent=2)+'\n');print('TIMING_PILOT_PREFIX_REVIEW_PASSED')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','lineage','timings','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();review(a.root,a.lineage,a.timings,a.output)
