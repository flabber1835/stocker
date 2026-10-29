"""Direct canonical confirmation of training-locked joint finalists, hosted only."""
import argparse,gzip,hashlib,json,os
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from full_system_benchmark import need
from full_system_controller_policy import parent_module
from full_system_controller_worker import KEYS,actual_account,independently_check,write
from full_system_controller_review import journal,value_step
from owned_grid import canonical_leaf,configure
from selective_journal import Journal
from system_campaign_numeric import hosted,load_complete,LEVELS
from system_campaign_joint_space import joint_profiles
from system_campaign_correlation import module,decode
from system_campaign_facts import digest
from system_campaign_basis import basis
from system_campaign_selection import CUTOFFS
from system_campaign_space import record


def selected_for_core(locks,core_id):
    need([v['cutoff'] for v in locks]==list(CUTOFFS),'FINALIST_ORDERED_TRAINING_LOCKS')
    wanted=set()
    for locked in locks:
        raw={k:v for k,v in locked.items() if k!='sha256'}
        need(locked['schema']=='research.system-campaign-global-training-lock/1'
             and locked['sha256']==digest(raw) and locked['evaluation_used'] is False
             and locked['global_optimum_claim'] is False
             and locked['status'] in ('TRAINING_LOCKED','PARTIAL_CLASS_TRAINING_LOCKED_UNKNOWN_COVERAGE_RETAINED'),
             'FINALIST_AUTHENTIC_TRAINING_LOCK')
        need(len(locked['selected'])==len(set(locked['selected'])),'FINALIST_UNIQUE_SELECTED_IDS')
        for identity in locked['selected']:
            core,joint=identity.split('::')
            if core==core_id:wanted.add(joint)
    registry=joint_profiles();ids=[v['id'] for v in registry['joint_profiles']]
    need(wanted<=set(ids) and 0<len(wanted)<=8,'FINALIST_ONLY_FROZEN_SELECTED_IDS')
    return [identity for identity in ids if identity in wanted]


def confirm(core,numeric,audit,selection,out):
    hosted();need(not out.exists(),'FINALIST_OUTPUT_ALREADY_EXISTS')
    cp,rows,origin=load_complete(core);common_sha,_=basis(core,cp)
    source=json.loads((core/'source-bindings.json').read_bytes());core_id=record(source['parameters'])['id']
    locks=json.loads(selection.read_bytes());ids=selected_for_core(locks,core_id)
    proof=json.loads((audit/'independent-review.json').read_bytes())
    need(proof['status']=='JOINT_NUMERICAL_TRAINING_REVIEW_PASSED_FINALISTS_REQUIRE_DIRECT_CLASSIFIER_AND_ACCOUNT'
         and proof['canonical_core_checkpoint_sha256']==cp['sha256']
         and proof['common_factual_basis_sha256']==common_sha and proof['all_training_metrics_verified']
         and proof['baseline_all_account_fields_exact'],'FINALIST_EXACT_PRIOR_INDEPENDENT_REVIEW')
    registry=joint_profiles();need(json.loads((numeric/'joint-registry.json').read_bytes())==registry,
                                 'FINALIST_UNCHANGED_JOINT_REGISTRY')
    wanted={v['id']:i for i,v in enumerate(registry['joint_profiles']) if v['id'] in ids}
    codes=np.load(numeric/'joint-target-codes.npy',mmap_mode='r',allow_pickle=False)
    fast_amber=np.load(numeric/'classifier-amber-counts.npy',mmap_mode='r',allow_pickle=False)
    fast_denom=np.load(numeric/'holding-denominators.npy',allow_pickle=False)
    need(codes.dtype==fast_amber.dtype==fast_denom.dtype==np.uint8
         and codes.shape==(4096,len(rows)) and fast_amber.shape==(2916,len(rows))
         and fast_denom.shape==(len(rows),),'FINALIST_REVIEWED_MATRIX_SHAPES')
    fast_controllers={(v['id'],v['session']):v for v in journal(numeric/'joint-controller-checkpoints.jsonl.gz') if v['id'] in wanted}
    groups={identity:hashlib.sha256(bytes(codes[index,126:])).hexdigest() for identity,index in wanted.items()}
    fast_values={(v['group'],v['session']):v for v in journal(numeric/'joint-value-checkpoints.jsonl.gz') if v['group'] in set(groups.values())}
    parent=Path('/variant/sentinel/controller/champion_frozen.py').read_bytes()
    leaf=Path('/variant/sentinel/controller/owned_impairment.py');classifier=Path('/variant/sentinel/controller/median5_breadth.py').read_bytes()
    source_hashes=source['all_sources'];leaf_sha=source_hashes['sentinel/controller/owned_impairment.py']
    need(hashlib.sha256(leaf.read_bytes()).hexdigest()==leaf_sha,'FINALIST_EXACT_OWNED_SOURCE')
    events=cp['run']['state']['ledger']['events'];out.mkdir();os.environ['OWNED_GRID_HOSTED']='1'
    results=[]
    for identity in ids:
        index=wanted[identity];joint=registry['joint_profiles'][index]
        profile=registry['controllers'][joint['controller_index']]
        par=parent_module(parent,profile,source_hashes['sentinel/controller/champion_frozen.py'])
        owned=canonical_leaf(leaf,leaf_sha,name='_private_sharadar_owned_grid_confirm_'+str(index));configure(owned,profile['owned'])
        sensor=module(classifier,registry['correlations'][joint['correlation_index']]['parameters'],
                      source_hashes['sentinel/controller/median5_breadth.py'])
        native=par.Native();candidate=par.CandidateA();state=owned.fresh();effective=previous=1.
        damage=[];prior=origin['run']['state_sha256'];chain=digest('system-optimization-002/raw-correlation/1')
        target_prefix=hashlib.sha256();value_prefix=hashlib.sha256();account=None;nav='50000';seen=0;restores=0
        accounts=Journal(out/(identity+'-direct-accounts.jsonl.gz'));labels=Journal(out/(identity+'-direct-classifier.jsonl.gz'))
        try:
            with gzip.open(core/'correlation-inputs.jsonl.gz','rb') as capture:
                for line in capture:
                    need(seen<len(rows),'FINALIST_NO_EXTRA_CAPTURE');r=json.loads(line);committed=r.pop('chain_sha256')
                    chain=digest({'previous':chain,'record':r});row=rows[seen]
                    need(chain==committed and r['session']==row['session'] and r['prior_state_sha256']==prior
                         and r['next_state_sha256']==row['state_sha256'] and r['input_sha256']==row['input_sha256'],
                         'FINALIST_EVERY_CAUSAL_CAPTURE_BOUNDARY')
                    breadth=sensor.from_capture(decode(r['material']))[0]
                    need(breadth.ambers==int(fast_amber[joint['correlation_index'],seen])
                         and breadth.denominator==int(fast_denom[seen]),'FINALIST_DIRECT_CLASSIFIER_EVERY_OBSERVATION')
                    labels.write({'session':row['session'],'breadth':asdict(breadth)})
                    damage.append(breadth.damaged_breadth);ob=dict(row['evidence']['observation'])
                    ob['damaged_breadth']=damage[-1];ob['damaged_breadth_delta5']=damage[-1]-damage[-6] if len(damage)>=6 else None
                    witness=row['evidence']['recent_leadership'];n,_,_=native.step(tuple(ob[k] for k in KEYS))
                    desired,_=candidate.step(n,effective,ob['shadow_drawdown'],witness['recent_r20'],witness['recent_r40'],ob['spy_r20'],ob['shadow_r20'])
                    effective,previous=previous,n;state,evidence=owned.step(observation=SimpleNamespace(**ob),base_target=desired,state=state)
                    target=evidence['target'];need(target==LEVELS[int(codes[index,seen])],'FINALIST_EVERY_DIRECT_CANONICAL_TARGET')
                    target_prefix.update(bytes([LEVELS.index(target)]))
                    if seen>=126:
                        if account is None:
                            account=deepcopy(row['economics'])
                            if Decimal(account['pending_allocation'])!=Decimal(str(target)):account['pending_allocation']=str(target)
                        else:
                            old=account;account=actual_account(old,row,target,events);independently_check(old,row,account,events)
                            nav=value_step(nav,account['net_factor'])
                        need(account['strategy_nav']==nav,'FINALIST_EVERY_DIRECT_ACCOUNT_VALUE')
                        accounts.write({'session':row['session'],'account':account})
                        value_prefix.update((json.dumps((row['session'],nav),separators=(',',':'))+'\n').encode())
                    month=seen==len(rows)-1 or row['session'][:7]!=rows[seen+1]['session'][:7]
                    if month:
                        saved={'id':identity,'session':row['session'],'native':native.snapshot(),'candidate':candidate.snapshot(),
                            'owned':state,'effective':effective,'previous':previous,'target_prefix_sha256':target_prefix.hexdigest()}
                        need(fast_controllers.get((identity,row['session']))==saved,'FINALIST_DIRECT_FULL_CONTROLLER_PREFIX')
                        saved=json.loads(json.dumps(saved,allow_nan=False));native=par.Native.from_snapshot(saved['native']);candidate=par.CandidateA.from_snapshot(saved['candidate']);state=saved['owned'];restores+=1
                        if seen>=126:
                            expected={'group':groups[identity],'session':row['session'],'completed':seen-126+1,
                                      'nav':nav,'prefix_sha256':value_prefix.hexdigest()}
                            need(fast_values.get((groups[identity],row['session']))==expected,'FINALIST_DIRECT_FULL_ACCOUNT_PREFIX')
                    prior=row['state_sha256'];seen+=1
            need(seen==2282,'FINALIST_COMPLETE_FORMATION_AND_MEASURED_AXIS');accounts.flush();labels.flush()
            results.append({'id':identity,'observations':seen,'direct_account_closes':2156,'monthly_restores':restores,
                            'classifier_journal':labels.commitment(),'account_journal':accounts.commitment(),
                            'compiled_classifier_sha256':sensor.compiled_sha256,'compiled_parent_sha256':par.compiled_sha256})
        finally:accounts.close();labels.close()
    write(out/'confirmation.json',{'status':'TRAINING_LOCKED_FINALISTS_DIRECT_CANONICAL_CONFIRMATION_PASSED',
        'core_id':core_id,'core_checkpoint_sha256':cp['sha256'],'common_factual_basis_sha256':common_sha,
        'selection_file_sha256':hashlib.sha256(selection.read_bytes()).hexdigest(),
        'numeric_review_sha256':hashlib.sha256((audit/'independent-review.json').read_bytes()).hexdigest(),
        'results':results,'new_core_financial_sessions':0,'production_contacted':False,
        'selected_using_later_returns':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('core','numeric','audit','selection','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();confirm(args.core,args.numeric,args.audit,args.selection,args.output)
