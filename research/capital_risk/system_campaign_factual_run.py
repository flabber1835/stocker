"""Hosted canonical factual suffix of each own retained pre-event checkpoint."""
import argparse,gzip,json,os,shutil,zipfile
from contextlib import nullcontext
from dataclasses import asdict,replace
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,digest,sha
from system_campaign_observe import Observation
from system_campaign_readonly import reader,review as readonly_review


def preflight(spec,old,out):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    from research.pooled_input_support.bundle import axis
    readonly_review(old/'book',out/'old-branch-canonical-review.json')
    cp=journal.read_checkpoint(old/spec['selected_checkpoint']);full=axis()
    wanted=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    backtest.validate_checkpoint(cp,cp['base'],wanted)
    need(cp['base']['sources']==backtest.source_files() and cp['sha256']==spec['outer_sha256']
         and cp['source_cursor']==spec['selected_session']<'2017-08-09','FACTUAL_OWN_SOURCE_CURSOR')
    restored=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(restored)==cp['run'],'FACTUAL_OWN_CANONICAL_ROUNDTRIP')
    j=reader(journal.Journal,old/'book',journal.STREAMS)
    try:j.verify(cp['journals'])
    finally:j.close()
    book=out/'book';book.mkdir();(book/'predecessor-checkpoints').mkdir()
    shutil.copyfile(old/'book/identity.json',book/'identity.json')
    for target in (book/'checkpoint.json.gz',book/'predecessor-checkpoints'/(cp['sha256']+'.json.gz')):
        shutil.copyfile(old/spec['selected_checkpoint'],target)
    if (old/'book/repairs').exists():shutil.copytree(old/'book/repairs',book/'repairs')
    tails={}
    for n,c in cp['journals'].items():
        raw=(old/f'book/{n}.jsonl').read_bytes();(book/f'{n}.jsonl').write_bytes(raw);tail=raw[c['bytes']:]
        tails[n]={'bytes':len(tail),'sha256':sha(tail)}
    save(out/'factual-preflight.json',{'canonical_roundtrip':True,'all_old_checkpoints_and_prefixes_verified':True,
         'selected_outer_sha256':cp['sha256'],'selected_inner_sha256':cp['run']['checkpoint_sha256'],
         'source_conversion':False,'fresh_origin':False,'next_session':wanted[wanted.index(cp['source_cursor'])+1],
         'old_branch_mounted_read_only':str(old),'tails_to_preserve':tails})
    return cp


def correlation_seed(old,cp):
    capture=old/'correlation-inputs.jsonl.gz'
    if not capture.exists():capture=old/'lineage/old-branch/correlation-inputs.jsonl.gz'
    if not capture.exists():return []
    financial={}
    for n in ('formation','daily'):
        with (old/f'book/{n}.jsonl').open('rb') as f:
            for raw in f.read(cp['journals'][n]['bytes']).splitlines():
                r=json.loads(raw);financial[r['session']]=r['state_sha256']
    chain=digest('system-optimization-002/raw-correlation/1');rows=[]
    with gzip.open(capture,'rb') as f:
        for raw in f:
            r=json.loads(raw)
            if r['session']>cp['source_cursor']:break
            committed=r.pop('chain_sha256');chain=digest({'previous':chain,'record':r})
            need(chain==committed and financial[r['session']]==r['next_state_sha256'],'FACTUAL_OLD_CORRELATION_PREFIX');rows.append(raw)
    need(len(rows)==len(financial),'FACTUAL_OLD_CORRELATION_AXIS')
    if rows:need(json.loads(rows[-1])['next_state_sha256']==cp['run']['state_sha256'],'FACTUAL_CORRELATION_SELECTED_STATE')
    return rows


class SeededObservation(Observation):
    def __init__(self,path,rows):super().__init__(path);self.seed=rows
    def __enter__(self):
        super().__enter__()
        for raw in self.seed:self.stream.write(raw)
        if self.seed:
            self.rows=len(self.seed);self.chain=json.loads(self.seed[-1])['chain_sha256'];self.stream.flush();os.fsync(self.stream.fileno())
        return self


def preserve_tails(book,proof):
    result={}
    for n,e in proof['tails_to_preserve'].items():
        if e['bytes']:
            matches=[p for p in book.glob(f'interrupted-{n}-*.jsonl') if p.stat().st_size==e['bytes'] and sha(p.read_bytes())==e['sha256']]
            need(len(matches)==1,'FACTUAL_EXACT_RECOVERED_TAIL');result[n]={'path':matches[0].name,**e}
        else:result[n]=e
    return result


def qualify_inputs(catalog,loaded,output):
    """Use actual frozen native rows/quotes, without advancing a financial session."""
    from research.pooled_input_support import inputs
    from research.pooled_input_support.adapter import Packet
    from research.bounded_20y.run import vendor,distributions
    from research.pooled_vacancy_funding import backtest
    actions=inputs.load_actions(Path('/frozen/bundle'))
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        spins=distributions(inputs._archive_rows(archive,'actions.csv.gz'))
        bars=tuple(vendor(r) for r in inputs._archive_rows(archive,'observations-2017.csv.gz')
                   if r['session']=='2017-10-02' and r['security_id'] in ('234488913323173693','285304847559167677'))
    original=Packet('2017-10-02',bars,{},{},1.,{},tuple(actions.terminal.get('2017-10-02',())),tuple(spins.get('2017-10-02',())))
    before=digest(asdict(original));changed=backtest.apply_repair(original,loaded)
    need(digest(asdict(original))==before,'FACTUAL_ORIGINAL_PACKET_UNCHANGED')
    fnf=[r for r in changed.spins if r.parent_security_id=='234488913323173693']
    need(len(fnf)==1 and asdict(fnf[0])==catalog.catalog['fnf']['added'],'FACTUAL_ACTUAL_TYPED_SPIN')
    parent,=[b for b in changed.bars if b.security_id=='234488913323173693']
    need(parent.dividend_per_share==0. and all(asdict(b)==asdict(c) for b,c in zip(original.bars,changed.bars)
         if b.security_id!=parent.security_id),'FACTUAL_NO_DUPLICATE_CASH_OR_OTHER_QUOTE_CHANGE')
    bad_packets=(replace(original,spins=tuple(s for s in original.spins if s.source_row_id!=catalog.catalog['fnf']['native'][0]['source_row_id'])),
                 replace(original,bars=tuple(replace(b,raw_open=b.raw_open+.01) if b.security_id==parent.security_id else b for b in original.bars)))
    for bad in bad_packets:
        try:backtest.apply_repair(bad,loaded)
        except ValueError:pass
        else:raise ValueError('REFUSED_FACTUAL_NATIVE_SOURCE_FALSIFIER')
    for item in catalog.catalog['terms']:
        for day in {item['native']['session'],item['added']['session']}:
            packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
            # This probe intentionally has only terminal data. Actual complete
            # packets above and every financial packet use the full wrapper.
            fixed=catalog.original(packet,loaded);matches=[t for t in fixed.terminal if t.security_id==item['native']['security_id']]
            if day==item['added']['session']:
                need(len(matches)==1 and asdict(matches[0])==item['added'] and matches[0].completeness(1)[0],'FACTUAL_ACTUAL_TERM_REPLACEMENT')
            else:need(not matches,'FACTUAL_ACTUAL_NATIVE_SUPPRESSION')
    save(output,{'actual_frozen_native_terms':[v['ticker'] for v in catalog.catalog['terms']],
         'actual_fnf_source_rows_and_bars':True,'typed_spin_and_cash_proxy_suppression':True,
         'source_row_and_quote_falsifiers':True,'original_packet_unchanged':True,'financial_sessions_advanced':0})


def run(out,old,spec):
    from research.pooled_vacancy_funding import backtest,journal
    cp=preflight(spec,old,out);catalog=FactualInputs('/driver/system-campaign-factual-catalog.json')
    need(catalog.catalog['archive_sha256']==cp['base']['archive_sha256'],'FACTUAL_FROZEN_ARCHIVE_BINDING')
    catalog.hydrate(out/'hydrated-factual-catalog.json')
    origin_path=old/'campaign-own-facts.json'
    if not origin_path.exists():origin_path=old/'lineage/old-branch/campaign-own-facts.json'
    origin=json.loads(origin_path.read_bytes()) if not cp['repairs'] else None
    overlay=out/'common-factual-overlay.json';loaded=catalog.overlay(cp,overlay,origin)
    from research.pooled_vacancy_funding.repair import load_repair
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),('2017-08-09',cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_FACTUAL_PARSER_FALSIFIER')
    save(out/'factual-overlay-admission.json',{'overlay_sha256':loaded.sha256,'catalog_sha256':catalog.catalog_sha,
         'compiler_sha256':catalog.compiler_sha,'own_predecessor':cp['run']['checkpoint_sha256'],
         'wrong_predecessor_refused':True,'consumed_session_refused':True,'financial_source_changed':False})
    p=json.loads((old/'source-bindings.json').read_bytes()).get('parameters',{});family=p.get('family','CORE')
    keep=p['v_horizon'] if family=='V' else 21 if family=='C' else 1
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp)) if spec['arm'].startswith('P') else None
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with catalog:
        qualify_inputs(catalog,loaded,out/'factual-input-qualification.json')
        with observer if observer is not None else nullcontext():
            with Execution('REFERENCE' if spec['arm']=='B0' else 'FAST',signal_closes=keep) as execution:
                code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof())
    if observer is not None:save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'factual-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
         'complete':current['source_cursor']==backtest.END and current['completed']==2156,
         'source_conversion':False,'fresh_origin':False,'production_contacted':False})
    need(code==0,'FACTUAL_SUFFIX_REFUSED_PREFIX_PRESERVED')


def review(out,evidence,old,spec):
    readonly_review(evidence/'book',out/'core-review.json')
    proof=json.loads((evidence/'factual-preflight.json').read_bytes())
    save(out/'reviewed-recovered-tail-proof.json',preserve_tails(evidence/'book',proof))
    selected=evidence/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')
    need(sha(selected.read_bytes())==spec['selected_file']['sha256'],'FACTUAL_EXACT_OLD_GZIP')
    if spec['arm'].startswith('P'):verify_correlation(evidence)
    save(out/'factual-lineage-review.json',{'old_branch_canonical_checks_reused_from_exact_preflight':True,
         'exact_selected_gzip_old_prefixes_and_recovered_tails':True,'source_conversion':False,'production_contacted':False})


def verify_correlation(root):
    cp=json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()));financial={}
    for n in ('formation','daily'):
        with (root/f'book/{n}.jsonl').open('rb') as f:
            for raw in f.read(cp['journals'][n]['bytes']).splitlines():
                r=json.loads(raw);financial[r['session']]=r['state_sha256']
    chain=digest('system-optimization-002/raw-correlation/1');seen=[]
    with gzip.open(root/'correlation-inputs.jsonl.gz','rb') as f:
        for raw in f:
            r=json.loads(raw);committed=r.pop('chain_sha256');chain=digest({'previous':chain,'record':r})
            need(chain==committed,'FACTUAL_CORRELATION_CHAIN')
            if r['session']<=cp['source_cursor']:
                need(financial[r['session']]==r['next_state_sha256'],'FACTUAL_CORRELATION_ACTUAL_STATE');seen.append(r['session'])
    need(seen==sorted(financial),'FACTUAL_CORRELATION_COMMITTED_AXIS')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--spec',type=Path,required=True)
    a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
