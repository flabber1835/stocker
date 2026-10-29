"""Bounded persistent accounts with exact own journal/checkpoint recovery."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

from alpaca_fit_inputs import hosted,need
from alpaca_fit_baseline import source_check
from alpaca_fit_account import Runtime
from alpaca_fit_policy import profiles
from alpaca_fit_funded_source import Source,benchmark_inputs
from selective_journal import Journal,encode,digest,save,load


FINANCIAL_FILES=('research/capital_risk/alpaca_fit_account.py','research/capital_risk/holding_account.py',
    'research/capital_risk/selective_model.py','shared/stock_strategy_shared/wealth_core/shares.py')


def model_basis(request,source):
    return {'schema':'research.alpaca-funded-model-basis/1','financial_source_files':{p:request['source_files'][p] for p in FINANCIAL_FILES},
        'protocol_sha256':request['protocol_sha256'],'dataset_sha256':request['dataset_sha256'],
        'training_source_prefix':source.training_prefix,'capital':'50000','initial_clock':'BEFORE_FIRST_MEASURED_OPEN',
        'stock_fee':'0.001','defensive_cash':'BIL_ADJUSTED_PROXY_SPLIT_OPEN_GEOMETRY',
        'whole_buys_cash_clips':'RETAINED_PERSISTENT_ACCOUNT_OPERATIONS'}


class Buffer:
    def __init__(self):self.values=[]
    def write(self,value):self.values.append(value)


def recover(previous,path,commit,lineage,name):
    shutil.copyfile(previous,lineage/('original-'+name+'.jsonl.gz'))
    journal=Journal(path);tail=lineage/(name+'-unsent.bin');sha=hashlib.sha256();length=0
    with gzip.open(previous,'rb') as old,tail.open('xb') as saved:
        for raw in old:
            if journal.records<commit['records']:
                value=json.loads(raw);need(encode(value)+b'\n'==raw,'FUNDED_PREFIX_ENCODING');journal.write(value)
            else:saved.write(raw);sha.update(raw);length+=len(raw)
    journal.flush();need(journal.commitment()==commit,'FUNDED_OWN_JOURNAL_PREFIX')
    return journal,{'file':tail.name,'bytes':length,'sha256':sha.hexdigest()}


def write_json(path,value):
    need(not path.exists(),'FUNDED_OUTPUT_COLLISION');path.write_bytes(encode(value)+b'\n')


def book(source,protocol,profile,model_sha,root,deadline,previous=None):
    root.mkdir(exist_ok=False);lineage=root/'lineage';lineage.mkdir();buffer=Buffer()
    kwargs=dict(model_sha256=model_sha,dataset_sha256=source.dataset_sha256,profile_id=profile,protocol=protocol,
        source_navs=source.navs,recorder=buffer)
    journals={};current=None;retained_tail={};state='PARTIAL';failure=None
    if previous is not None:
        previous=Path(previous);current=load(previous/'checkpoint.json.gz')
        need(current['model_sha256']==model_sha and current['profile_id']==profile
             and current['training_source_prefix']==source.training_prefix,'FUNDED_OWN_BOUNDARY')
        shutil.copyfile(previous/'checkpoint.json.gz',lineage/'exact-predecessor.json.gz')
        shutil.copyfile(previous/'origin.json.gz',root/'origin.json.gz')
        if (previous/'lineage').is_dir():shutil.copytree(previous/'lineage',lineage/'inherited')
        for name in ('events','daily','checkpoints'):
            spec=current['checkpoint_archive'] if name=='checkpoints' else current['journals'][name]
            journals[name],retained_tail[name]=recover(previous/(name+'.jsonl.gz'),root/(name+'.jsonl.gz'),spec,lineage,name)
        runtime=Runtime(**kwargs,checkpoint=current['runtime'])
        need(runtime.checkpoint()==current['runtime'],'FUNDED_OWN_ACTUAL_ROUNDTRIP')
        write_json(lineage/'prefix-admission.json',{'own_profile':profile,'predecessor_file_sha256':hashlib.sha256(
            (previous/'checkpoint.json.gz').read_bytes()).hexdigest(),'recovered_tails':retained_tail,
            'model_and_training_prefix_unchanged':True,'origin_recreated':False})
    else:
        journals={name:Journal(root/(name+'.jsonl.gz')) for name in ('events','daily','checkpoints')}
        runtime=Runtime(**kwargs);runtime.start(source.anchor)
    def commit():
        value={'schema':'research.alpaca-funded-book-checkpoint/1','model_sha256':model_sha,'profile_id':profile,
            'training_source_prefix':source.training_prefix,'runtime':runtime.checkpoint(),
            'journals':{k:journals[k].commitment() for k in ('events','daily')}}
        journals['checkpoints'].write(value)
        for j in journals.values():j.flush()
        value={**value,'checkpoint_archive':journals['checkpoints'].commitment()}
        save(root/'checkpoint.json.gz',value)
        return value
    if current is None:
        current=commit();save(root/'origin.json.gz',current)
    try:
        for row in source.measured:
            if row['session']<=current['runtime']['session']:continue
            if time.monotonic()>deadline-120:break
            buffer.values=[];daily=runtime.advance(row)
            for value in buffer.values:journals['events'].write(value)
            journals['daily'].write(daily);current=commit()
        if current['runtime']['session']==source.end:state='COMPLETE'
    except Exception as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'attempted_session':row['session'],
            'last_committed_session':current['runtime']['session']}
        save(root/'failed-unsent-state.json.gz',{'authority':'UNCOMMITTED_NOT_RESUMABLE','runtime':runtime.checkpoint(),
            'buffered_events':buffer.values,'committed_checkpoint_sha256':digest(current)})
        state='REFUSED'
    finally:
        for j in journals.values():j.close()
    result={'status':state,'profile_id':profile,'session':current['runtime']['session'],'daily_records':current['journals']['daily']['records'],
        'model_sha256':model_sha,'failure':failure,'checkpoint_sha256':hashlib.sha256((root/'checkpoint.json.gz').read_bytes()).hexdigest()}
    write_json(root/'book-status.json',result);return result


def main(a):
    hosted();started=time.monotonic();out=Path(a.output);out.mkdir(exist_ok=False,parents=True)
    request=json.loads(Path(a.request).read_bytes());protocol=json.loads(Path(a.protocol).read_bytes())
    need(request['stage'] in ('TRAINING','DIAGNOSTIC') and hashlib.sha256(Path(a.protocol).read_bytes()).hexdigest()==request['protocol_sha256'],
         'FUNDED_REQUEST_SCOPE')
    binding=source_check(Path('/src'),request['source_files']);write_json(out/'source-bindings.json',request['source_files'])
    previous=Path(a.previous) if a.previous else None
    if previous is None:
        from alpaca_fit_account_qualify import cases
        qualified=cases()
    else:
        qualified=json.loads((previous/'component-qualification.json').read_bytes())
        old_bindings=json.loads((previous/'source-bindings.json').read_bytes())
        need(qualified['status']=='PASSED' and all(old_bindings[p]==request['source_files'][p] for p in FINANCIAL_FILES)
            and old_bindings['research/capital_risk/alpaca_fit_account_qualify.py']==request['source_files']['research/capital_risk/alpaca_fit_account_qualify.py'],
            'UNCHANGED_REUSED_ACCOUNT_COMPONENT')
    write_json(out/'component-qualification.json',qualified)
    source=Source(a.core_evidence,protocol,request['stage'])
    need(source.dataset_sha256==request['dataset_sha256'],'FUNDED_FROZEN_DATASET')
    write_json(out/'source-preflight.json',source.preflight)
    proof,spy=benchmark_inputs(a.inputs,a.prefix_inputs,a.bil_inputs,protocol,source)
    write_json(out/'benchmark-proof.json',proof);write_json(out/'spy-series.json',spy)
    basis=model_basis(request,source);model_sha=digest(basis);write_json(out/'financial-model-basis.json',basis)
    registered,baseline=profiles(protocol);wanted=[baseline.id]+sorted(p.id for p in registered if p.id!=baseline.id)
    if request['stage']=='DIAGNOSTIC':
        need(previous is not None,'DIAGNOSTIC_NEEDS_LOCKED_TRAINING')
        selected=json.loads((previous.parent/'stopped-independent-review/review/locked-selection.json').read_bytes())
        need(hashlib.sha256((previous.parent/'stopped-independent-review/review/locked-selection.json').read_bytes()).hexdigest()==request['locked_selection_sha256'],
             'DIAGNOSTIC_EXACT_LOCK')
        need(selected['status']=='TRAINING_SELECTION_LOCKED' and selected['selection_cutoff']==protocol['training_end']
             and selected['validation_used_for_selection'] is False,'LOCKED_SELECTION_SCOPE')
        wanted=list(dict.fromkeys([baseline.id]+selected['selected']));write_json(out/'locked-selection-reference.json',selected)
        need(set(wanted).issubset(p.id for p in registered) and len(wanted)<=protocol['maximum_shortlist']+1,'SELECTED_REGISTERED_SHORTLIST')
    rows=[];deadline=started+3000
    for profile in wanted:
        target=out/'books'/profile;target.parent.mkdir(exist_ok=True)
        prior=None if previous is None else previous/'books'/profile
        if prior is not None and not prior.exists():
            need(request['stage']=='TRAINING','MISSING_SELECTED_TRAINING_ACCOUNT');prior=None
        if prior is not None:
            cp=load(prior/'checkpoint.json.gz');need(cp['model_sha256']==model_sha,'FROZEN_FINANCIAL_MODEL_CHANGED')
            if cp['runtime']['session']==source.end:
                shutil.copytree(prior,target);rows.append(json.loads((target/'book-status.json').read_bytes()));continue
        if time.monotonic()>deadline-120:
            rows.append({'profile_id':profile,'status':'UNSTARTED_NO_NEW_ORIGIN'});continue
        result=book(source,protocol,profile,model_sha,target,deadline,prior);rows.append(result)
        if profile==baseline.id and result['status']=='REFUSED':break
    covered={r['profile_id'] for r in rows}
    rows.extend({'profile_id':p,'status':'UNSTARTED_NO_NEW_ORIGIN'} for p in wanted if p not in covered)
    complete=all(r['status']=='COMPLETE' for r in rows)
    write_json(out/'fit-status.json',{'schema':'research.alpaca-funded-fit-status/1','stage':request['stage'],
        'status':'COMPLETE_PENDING_REVIEW' if complete else 'PARTIAL_OR_REFUSED_PRESERVED','profiles':rows,
        'required_profiles':wanted,'financial_model_sha256':model_sha,'source_execution_sha256':binding,
        'source_training_prefix':source.training_prefix,'elapsed_seconds':time.monotonic()-started,
        'production_contacted':False,'performance_admitted':False})
    return 0 if complete else 2


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('request','protocol','core-evidence','inputs','prefix-inputs','bil-inputs','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--previous');raise SystemExit(main(p.parse_args()))
