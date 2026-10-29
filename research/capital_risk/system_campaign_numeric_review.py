"""Independent stopped joint-numerical value and decision-prefix reviewer."""
import argparse,gzip,hashlib,json,os
from pathlib import Path
from fractions import Fraction as Q
import numpy as np
from full_system_benchmark import need
from full_system_controller_vector import targets
from full_system_controller_review import journal,independent_factor,check_factor,value_step,training_metric
from selective_journal import verify_prefixes
from system_campaign_joint_space import joint_profiles
from system_campaign_numeric import hosted,load_complete,LEVELS
from system_campaign_facts import digest


def review(core,evidence,out):
    hosted();need(not out.exists(),'JOINT_REVIEW_OUTPUT_COLLISION')
    cp,rows,origin=load_complete(core);registry=joint_profiles()
    need(json.loads((evidence/'joint-registry.json').read_bytes())==registry,'INDEPENDENT_JOINT_FINITE_CLASS')
    summary=json.loads((evidence/'summary.json').read_bytes())
    need(summary['core_checkpoint_sha256']==cp['sha256'] and summary['joint_registry_sha256']==digest(registry)
         and not summary['global_selection_performed'] and not summary['production_contacted'],'JOINT_REVIEW_SCOPE')
    ambers=np.load(evidence/'classifier-amber-counts.npy',allow_pickle=False)
    denom=np.load(evidence/'holding-denominators.npy',allow_pickle=False)
    green=np.load(evidence/'green-counts.npy',allow_pickle=False)
    need(ambers.dtype==denom.dtype==green.dtype==np.uint8 and ambers.shape==(2916,len(rows))
         and denom.shape==green.shape==(len(rows),) and np.all(ambers<=denom[None,:])
         and np.all(green<=denom),'JOINT_INTEGER_CLASSIFIER_OBSERVATIONS')
    need(not out.with_suffix('.target-verification.npy').exists(),'JOINT_REVIEW_TARGET_COLLISION')
    expected=np.lib.format.open_memmap(out.with_suffix('.target-verification.npy'),mode='w+',dtype=np.uint8,
        shape=(4096,len(rows)))
    actual=np.load(evidence/'joint-target-codes.npy',mmap_mode='r',allow_pickle=False)
    need(actual.dtype==np.uint8 and actual.shape==expected.shape and np.all(actual<len(LEVELS)),
         'JOINT_COMPLETE_TARGET_CODE_SHAPE')
    # Independent controller equations receive each profile's own damage history.
    # Bound temporary allocation to 128 profiles, never the full Cartesian matrix.
    joint=registry['joint_profiles'];controllers=registry['controllers']
    for start in range(0,len(joint),128):
        batch=joint[start:start+128];ids=[v['correlation_index'] for v in batch]
        damage=np.divide(ambers[ids],denom[None,:],out=np.zeros((len(batch),len(rows))),where=denom[None,:]!=0)
        values=targets(rows,[controllers[v['controller_index']] for v in batch],damage=damage)
        code=np.searchsorted(np.asarray(LEVELS),values).astype('uint8')
        need(np.array_equal(np.asarray(LEVELS)[code],values)
             and np.array_equal(code,actual[start:start+len(batch)]),'JOINT_EVERY_INDEPENDENT_CONTROLLER_TARGET')
        expected[start:start+len(batch)]=code
    expected.flush()
    for i,row in enumerate(rows):
        need(LEVELS[int(actual[0,i])]==row['decision']['target_core_exposure'],'JOINT_BASELINE_COMPLETE_TARGETS')
        ob=row['evidence']['observation'];n=int(denom[i])
        need(ob['damaged_breadth']==(int(ambers[0,i])/n if n else 0.)
             and ob['green_breadth']==(int(green[i])/n if n else 0.),'JOINT_BASELINE_CLASSIFIER_FRACTIONS')
    controller=json.loads((evidence/'joint-controller-proof.json').read_bytes())
    verify_prefixes(evidence/'joint-controller-checkpoints.jsonl.gz',[controller['journal']])
    lookup={v['id']:i for i,v in enumerate(joint)};axis={r['session']:i+1 for i,r in enumerate(rows)}
    checkpoints=0;checkpoint_keys=set()
    month_ends={row['session'] for i,row in enumerate(rows)
        if i==len(rows)-1 or row['session'][:7]!=rows[i+1]['session'][:7]}
    for record in journal(evidence/'joint-controller-checkpoints.jsonl.gz'):
        index=lookup[record['id']];end=axis[record['session']]
        key=record['id'],record['session']
        need(record['session'] in month_ends and key not in checkpoint_keys,'JOINT_UNIQUE_MONTHLY_CONTROLLER_PREFIX')
        checkpoint_keys.add(key)
        need(hashlib.sha256(bytes(expected[index,:end])).hexdigest()==record['target_prefix_sha256'],
             'JOINT_ALL_CONTROLLER_CHECKPOINT_PREFIXES');checkpoints+=1
    need(checkpoints==len(joint)*len(month_ends),'JOINT_NO_MISSING_CONTROLLER_CHECKPOINT')
    measured=rows[126:];codes=actual[:,126:];events=cp['run']['state']['ledger']['events']
    factors=json.loads((evidence/'factor-proof.json').read_bytes());verify_prefixes(evidence/'factors.jsonl.gz',[factors['journal']])
    table=[{} for _ in measured];factor_count=0
    for item in journal(evidence/'factors.jsonl.gz'):
        i,pair=item['index'],item['pair']
        need(0<i<len(measured) and item['session']==measured[i]['session'] and pair not in table[i],
             'JOINT_DATED_UNIQUE_ACCOUNT_FACTOR')
        previous=dict(measured[i-1]['economics']);previous['strategy_nav']='50000'
        previous['pending_allocation']=str(LEVELS[pair if i==1 else pair%256])
        if i>1:previous['held_allocation']=str(LEVELS[pair//256])
        check_factor(item,independent_factor(previous,measured[i],events));table[i][pair]=item;factor_count+=1
    proof=json.loads((evidence/'joint-value-proof.json').read_bytes())
    for name,key in (('joint-value-paths.jsonl.gz','path_journal'),('joint-value-checkpoints.jsonl.gz','value_journal'),
                     ('direct-default-account.jsonl.gz','direct_default_journal')):
        verify_prefixes(evidence/name,[proof[key]])
    paths=list(journal(evidence/'joint-value-paths.jsonl.gz'))
    need([p['id'] for p in paths]==[v['id'] for v in joint],'JOINT_ALL_VALUE_PATH_IDENTITIES')
    saved={}
    for item in journal(evidence/'joint-value-checkpoints.jsonl.gz'):
        key=item['group'],item['session'];need(key not in saved,'JOINT_UNIQUE_VALUE_CHECKPOINT');saved[key]=item
    training={end:json.loads((evidence/('training-'+end+'.json')).read_bytes()) for end in ('2020-12-31','2022-12-30')}
    for end,document in training.items():
        need(document['cutoff']==end and document['no_evaluation_fields']
             and [r['id'] for r in document['records']]==[v['id'] for v in joint],'JOINT_TRAINING_AXIS')
    done={};baseline=None;steps=0;checked_cp=set()
    for index,item in enumerate(paths):
        code=codes[index];group=hashlib.sha256(bytes(code)).hexdigest()
        need(item=={'id':joint[index]['id'],'group':group,'index':index},'JOINT_EXACT_FUNDED_PATH_BINDING')
        if group not in done:
            nav='50000';series=[(measured[0]['session'],nav)];turn=[Q(0)];prefix=hashlib.sha256()
            prefix.update((json.dumps(series[0],separators=(',',':'))+'\n').encode())
            for i in range(1,len(measured)):
                pair=int(code[0]) if i==1 else int(code[i-2])*256+int(code[i-1])
                need(pair in table[i],'JOINT_ALL_REQUIRED_DATED_FACTORS');f=table[i][pair]
                nav=value_step(nav,f['net']);series.append((measured[i]['session'],nav));turn.append(Q(f['turnover']));steps+=1
                prefix.update((json.dumps(series[-1],separators=(',',':'))+'\n').encode())
                if i==len(measured)-1 or measured[i]['session'][:7]!=measured[i+1]['session'][:7]:
                    key=group,measured[i]['session'];record={'group':group,'session':key[1],'completed':i+1,'nav':nav,'prefix_sha256':prefix.hexdigest()}
                    need(saved.get(key)==record,'JOINT_EVERY_EXACT_VALUE_PREFIX');checked_cp.add(key)
            done[group]={end:{'metrics':training_metric(series,end),
                'turnover':str(sum((t for (day,_),t in zip(series,turn) if day<=end),Q(0)))} for end in training}
            if index==0:baseline=series
        for end,document in training.items():
            need(document['records'][index]=={'id':joint[index]['id'],'group':group,**done[group][end]},
                 'JOINT_EVERY_INDEPENDENT_TRAINING_METRIC')
    need(checked_cp==set(saved) and len(done)==proof['unique_groups'],'JOINT_COMPLETE_VALUE_CHECKPOINT_SET')
    direct=0
    for i,item in enumerate(journal(evidence/'direct-default-account.jsonl.gz')):
        need(i<len(measured) and item=={'session':measured[i]['session'],'account':measured[i]['economics']}
             and item['account']['strategy_nav']==baseline[i][1],'JOINT_INDEPENDENT_DEFAULT_FULL_ACCOUNT');direct+=1
    need(direct==len(measured),'JOINT_COMPLETE_DIRECT_ACCOUNT_AXIS')
    out.mkdir();(out/'independent-review.json').write_text(json.dumps({
        'status':'JOINT_NUMERICAL_TRAINING_REVIEW_PASSED_FINALISTS_REQUIRE_DIRECT_CLASSIFIER_AND_ACCOUNT',
        'joint_profiles':4096,'canonical_core_checkpoint_sha256':cp['sha256'],'independent_targets':actual.size,
        'controller_prefixes':checkpoints,'dated_factors':factor_count,'value_steps':steps,'value_checkpoints':len(saved),
        'baseline_all_account_fields_exact':True,'all_training_metrics_verified':True,
        'selected_classifier_and_account_confirmation_complete':False,'production_contacted':False},indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('core','evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();review(args.core,args.evidence,args.output)
