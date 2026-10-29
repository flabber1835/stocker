"""Hosted joint sensor/controller calculations on a complete immutable Core path."""
import argparse,gzip,hashlib,json,os,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from full_system_benchmark import need
from full_system_controller_policy import parent_module
from full_system_controller_vector import targets as independent_targets
from full_system_controller_worker import KEYS,write
from owned_grid import canonical_leaf,configure
from selective_journal import Journal
from system_campaign_correlation import ClassifierBatch
from system_campaign_facts import digest
from system_campaign_joint_space import joint_profiles,DEFAULT_CORRELATION
from system_campaign_basis import basis

LEVELS=(0.,.25,.55,.75,1.)


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
         and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_JOINT_NUMERICAL_ONLY')


def own_origin(evidence):
    identities=[json.loads(p.read_bytes()) for p in evidence.rglob('origin-admission.json')]
    need(identities and len({p['state_sha256'] for p in identities})==1,'JOINT_ONE_OWN_FEATURE_ORIGIN')
    identity=identities[0]
    paths=list(evidence.rglob(identity['outer_sha256']+'.json.gz'))
    need(paths,'JOINT_RETAINED_OWN_ORIGIN_GZIP')
    raw=paths[0].read_bytes();need(hashlib.sha256(raw).hexdigest()==identity['outer_file_sha256'],'JOINT_OWN_ORIGIN_FILE')
    cp=json.loads(gzip.decompress(raw))
    need(cp['run']['state_sha256']==identity['state_sha256'] and cp['run']['state']['last_processed_session'] is None
         and cp['completed']==0,'JOINT_ZERO_FINANCIAL_OWN_ORIGIN')
    return cp


def load_complete(evidence):
    root=evidence/'book';cp=json.loads(gzip.decompress((root/'checkpoint.json.gz').read_bytes()))
    proof=json.loads((evidence/'core-review.json').read_bytes())
    need(cp['completed']==2156 and cp['source_cursor']=='2026-07-31' and proof['complete']
         and proof['counts']=={'formation':126,'daily':2156} and proof['checkpoint_sha256']==cp['sha256']
         and proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
         and all(t['bytes']==0 for t in proof['preserved_tails'].values()),'JOINT_COMPLETE_REVIEWED_CORE_ONLY')
    rows=[]
    for name,count in (('formation',126),('daily',2156)):
        raw=(root/(name+'.jsonl')).read_bytes();commit=cp['journals'][name]
        need(len(raw)==commit['bytes'] and hashlib.sha256(raw).hexdigest()==commit['prefix_sha256'],'JOINT_IMMUTABLE_FINANCIAL_PREFIX')
        values=[json.loads(v) for v in raw.splitlines()];need(len(values)==count,'JOINT_COMPLETE_FINANCIAL_AXIS');rows.extend(values)
    return cp,rows,own_origin(evidence)


def classifier_paths(evidence,rows,origin,registry,out):
    hosted();registered=registry['correlations'];parameters=[r['parameters'] for r in registered]
    raw=Path('/variant/sentinel/controller/median5_breadth.py').read_bytes()
    expected=json.loads((evidence/'source-bindings.json').read_bytes())['all_sources']['sentinel/controller/median5_breadth.py']
    engine=ClassifierBatch(raw,expected,parameters);count=len(rows)
    ambers=np.zeros((len(parameters),count),dtype=np.uint8);denominators=np.zeros(count,dtype=np.uint8)
    greens=np.zeros(count,dtype=np.uint8);chain=digest('system-optimization-002/raw-correlation/1');seen=0
    baseline=parameters.index(DEFAULT_CORRELATION);history=list(origin['run']['state']['breadth_history'])
    need(not history,'JOINT_DECLARED_EMPTY_ORIGIN_BREADTH_PREFIX')
    prior=origin['run']['state_sha256']
    with gzip.open(evidence/'correlation-inputs.jsonl.gz','rb') as stream:
        for line in stream:
            need(seen<count,'JOINT_NO_EXTRA_CAPTURE_ROWS');record=json.loads(line);committed=record.pop('chain_sha256')
            chain=digest({'previous':chain,'record':record});row=rows[seen]
            need(chain==committed and record['session']==row['session'] and record['prior_state_sha256']==prior
                 and record['next_state_sha256']==row['state_sha256'] and record['input_sha256']==row['input_sha256'],
                 'JOINT_ACTUAL_CAUSAL_CAPTURE_BINDINGS')
            for h in record['material']['held']:
                indices=h['session_indices'];need(len(indices)==len(h['signal_closes']) and indices==sorted(set(indices))
                    and (not indices or indices[-1]<=record['material']['index']),'JOINT_CAPTURE_NO_FUTURE_BARS')
            value=engine.one(record['material']);n=value['denominator'];need(0<=n<256,'JOINT_CANONICAL_HOLDING_COUNT')
            ambers[:,seen]=value['ambers'];denominators[seen]=n;greens[seen]=value['greens']
            ob=row['evidence']['observation'];history.append(float(value['damage'][baseline]))
            delta=history[-1]-history[-6] if len(history)>=6 else None
            need(ob['damaged_breadth']==history[-1] and ob['green_breadth']==value['green']
                 and ob['damaged_breadth_delta5']==delta,'JOINT_DEFAULT_OBSERVATION_COMPLETE_PARITY')
            prior=row['state_sha256'];seen+=1
    need(seen==count,'JOINT_COMPLETE_CAPTURE_AXIS')
    for name,value in (('classifier-amber-counts.npy',ambers),('holding-denominators.npy',denominators),('green-counts.npy',greens)):
        with (out/name).open('xb') as f:np.save(f,value,allow_pickle=False)
    write(out/'classifier-proof.json',{'canonical_source_sha256':expected,'classifiers':len(parameters),'observations':count,
        'capture_chain_sha256':chain,'default_every_label_fraction_and_acceleration_exact':True,
        'no_future_capture_dates':True,'origin_breadth_prefix':history[:0]})
    return ambers,denominators


def controller_paths(rows,ambers,denominators,registry,out,source_hashes):
    hosted();os.environ['OWNED_GRID_HOSTED']='1'
    profiles=registry['controllers'];joint=registry['joint_profiles'];indices=np.asarray([j['correlation_index'] for j in joint])
    controls=[profiles[j['controller_index']] for j in joint]
    damage=np.divide(ambers[indices],denominators[None,:],out=np.zeros((len(joint),len(rows))),where=denominators[None,:]!=0)
    vector=independent_targets(rows,controls,damage=damage);del damage
    parent=Path('/variant/sentinel/controller/champion_frozen.py').read_bytes();parent_sha=source_hashes['sentinel/controller/champion_frozen.py']
    need(hashlib.sha256(parent).hexdigest()==parent_sha,'JOINT_PARENT_SOURCE_BOUND_TO_OWN_BOOK')
    leafpath=Path('/variant/sentinel/controller/owned_impairment.py');leaf_sha=hashlib.sha256(leafpath.read_bytes()).hexdigest()
    need(leaf_sha=='699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b','JOINT_EXACT_CANONICAL_OWNED_BASIS')
    modules={};journal=Journal(out/'joint-controller-checkpoints.jsonl.gz')
    codes=np.lib.format.open_memmap(out/'joint-target-codes.npy',mode='w+',dtype=np.uint8,shape=(len(joint),len(rows)))
    restores=0;baseline=registry['baseline_id']
    try:
        for index,identity in enumerate(joint):
            ci,si=identity['controller_index'],identity['correlation_index'];profile=profiles[ci]
            if ci not in modules:
                par=parent_module(parent,profile,parent_sha)
                leaf=canonical_leaf(leafpath,leaf_sha,name='_private_sharadar_owned_grid_joint_'+str(ci));configure(leaf,profile['owned']);modules[ci]=par,leaf
            par,leaf=modules[ci];native=par.Native();candidate=par.CandidateA();state=leaf.fresh();effective=previous=1.;prefix=hashlib.sha256()
            d=np.divide(ambers[si],denominators,out=np.zeros(len(rows)),where=denominators!=0)
            for i,row in enumerate(rows):
                ob=dict(row['evidence']['observation']);w=row['evidence']['recent_leadership']
                ob['damaged_breadth']=float(d[i]);ob['damaged_breadth_delta5']=float(d[i]-d[i-5]) if i>=5 else None
                n,_,_=native.step(tuple(ob[k] for k in KEYS))
                desired,_=candidate.step(n,effective,ob['shadow_drawdown'],w['recent_r20'],w['recent_r40'],ob['spy_r20'],ob['shadow_r20'])
                effective,previous=previous,n;state,evidence=leaf.step(observation=SimpleNamespace(**ob),base_target=desired,state=state)
                target=evidence['target'];need(target==float(vector[index,i]) and target in LEVELS,'JOINT_EVERY_CANONICAL_TARGET_AND_INDEPENDENT_EQUATION')
                if identity['id']==baseline:need(target==row['decision']['target_core_exposure'],'JOINT_COMPLETE_BASELINE_CONTROLLER_PARITY')
                code=LEVELS.index(target);codes[index,i]=code;prefix.update(bytes([code]))
                if i==len(rows)-1 or row['session'][:7]!=rows[i+1]['session'][:7]:
                    cp={'id':identity['id'],'session':row['session'],'native':native.snapshot(),'candidate':candidate.snapshot(),
                        'owned':state,'effective':effective,'previous':previous,'target_prefix_sha256':prefix.hexdigest()}
                    journal.write(cp);saved=json.loads(json.dumps(cp,allow_nan=False));native=par.Native.from_snapshot(saved['native']);candidate=par.CandidateA.from_snapshot(saved['candidate']);state=saved['owned'];restores+=1
        journal.flush();codes.flush()
        write(out/'joint-controller-proof.json',{'joint_profiles':len(joint),'actual_canonical_steps':len(joint)*len(rows),
            'all_independent_vector_targets_exact':True,'serialized_controller_restores':restores,'journal':journal.commitment(),
            'baseline_full_formation_and_measured_targets_exact':True,'parent_source_sha256':parent_sha,'owned_source_sha256':leaf_sha,
            'exposure_levels':LEVELS})
    finally:journal.close()
    return codes


def independent_value(nav,net):
    from decimal import Decimal,localcontext
    with localcontext() as context:
        context.prec=28
        value=Decimal(nav)*Decimal(net)
        need(value.is_finite() and value>0,'JOINT_INDEPENDENT_POSITIVE_VALUE')
        return format(value.normalize(),'f')


def value_paths(evidence,cp,rows,allcodes,registry,out):
    """One exact value group in memory; training-shaped outputs only."""
    hosted()
    from fractions import Fraction
    from decimal import Decimal
    from owned_value import nav_step
    from full_system_controller_worker import factor_table,metrics,actual_account,independently_check
    from full_system_controller_review import independent_factor,check_factor
    codes=allcodes[:,126:];need(codes.shape==(4096,2156),'JOINT_MEASURED_TARGET_AXIS')
    events=cp['run']['state']['ledger']['events']
    need(rows[0]['session']=='2018-01-02' and Decimal(rows[0]['economics']['strategy_nav'])==50000,
         'JOINT_EXACT_FIRST_ACCOUNT_ANCHOR')
    table=factor_table(rows,codes,LEVELS,events,out)
    checked=0
    for i in range(1,len(rows)):
        for pair,actual in table[i].items():
            prior=dict(rows[i-1]['economics']);prior['strategy_nav']='50000'
            prior['pending_allocation']=str(LEVELS[pair if i==1 else pair%256])
            if i>1:prior['held_allocation']=str(LEVELS[pair//256])
            check_factor(actual,independent_factor(prior,rows[i],events));checked+=1
    groups={};training={end:[] for end in ('2020-12-31','2022-12-30')}
    paths=Journal(out/'joint-value-paths.jsonl.gz');checkpoints=Journal(out/'joint-value-checkpoints.jsonl.gz')
    direct=Journal(out/'direct-default-account.jsonl.gz');restores=0
    try:
        for index,identity in enumerate(registry['joint_profiles']):
            code=codes[index];group=hashlib.sha256(code.tobytes()).hexdigest()
            paths.write({'id':identity['id'],'group':group,'index':index})
            if group not in groups:
                nav='50000';independent='50000';series=[(rows[0]['session'],nav)]
                turnover=[Fraction(0)];prefix=hashlib.sha256()
                prefix.update((json.dumps(series[0],separators=(',',':'))+'\n').encode())
                for i in range(1,len(rows)):
                    pair=int(code[0]) if i==1 else int(code[i-2])*256+int(code[i-1]);factor=table[i][pair]
                    nav=nav_step(nav,factor['net']);independent=independent_value(independent,factor['net'])
                    need(nav==independent,'JOINT_EVERY_INDEPENDENT_VALUE_STEP')
                    series.append((rows[i]['session'],nav));turnover.append(Fraction(factor['turnover']))
                    prefix.update((json.dumps(series[-1],separators=(',',':'))+'\n').encode())
                    if i==len(rows)-1 or rows[i]['session'][:7]!=rows[i+1]['session'][:7]:
                        saved={'group':group,'session':rows[i]['session'],'completed':i+1,
                               'nav':nav,'prefix_sha256':prefix.hexdigest()}
                        checkpoints.write(saved);loaded=json.loads(json.dumps(saved,allow_nan=False))
                        need(loaded==saved,'JOINT_SERIALIZED_VALUE_CHECKPOINT');nav=loaded['nav'];restores+=1
                groups[group]={'training':{end:{'metrics':metrics(series,'2018-01-02',end),
                    'turnover':str(sum((v for (day,_),v in zip(series,turnover) if day<=end),Fraction(0)))}
                    for end in training}}
                # No full/later-period metric enters the training interface.
                if identity['id']==registry['baseline_id']:
                    previous=None
                    for i,row in enumerate(rows):
                        target=LEVELS[int(code[i])]
                        if i==0:
                            from copy import deepcopy
                            account=deepcopy(row['economics'])
                            if Decimal(account['pending_allocation'])!=Decimal(str(target)):
                                account['pending_allocation']=str(target)
                        else:
                            account=actual_account(previous,row,target,events);independently_check(previous,row,account,events)
                        need(account==row['economics'] and account['strategy_nav']==series[i][1],
                             'JOINT_DEFAULT_ALL_COMPLETE_ACCOUNT_FIELDS')
                        direct.write({'session':row['session'],'account':account})
                        previous=json.loads(json.dumps(account,allow_nan=False))
            for end in training:
                training[end].append({'id':identity['id'],'group':group,**groups[group]['training'][end]})
        paths.flush();checkpoints.flush();direct.flush()
        for end,records in training.items():
            write(out/('training-'+end+'.json'),{'cutoff':end,'records':records,
                'core_profile_sha256':json.loads((evidence/'source-bindings.json').read_bytes())['profile_sha256'],
                'no_evaluation_fields':True})
        write(out/'joint-value-proof.json',{'joint_profiles':len(registry['joint_profiles']),'unique_groups':len(groups),
            'measured_closes':len(rows),'independently_checked_dated_factors':checked,
            'every_independent_value_step_exact':True,'monthly_serialized_value_restores':restores,
            'value_journal':checkpoints.commitment(),'path_journal':paths.commitment(),'direct_default_journal':direct.commitment(),
            'default_all_complete_account_fields_exact':True,'later_metrics_not_in_training_interface':True})
    finally:
        paths.close();checkpoints.close();direct.close()
    return training


def run(evidence,out):
    hosted();need(not out.exists(),'JOINT_OUTPUT_ALREADY_EXISTS');out.mkdir()
    started=time.monotonic();cp,allrows,origin=load_complete(evidence);registry=joint_profiles()
    source=json.loads((evidence/'source-bindings.json').read_bytes())
    common_sha,common=basis(evidence,cp);write(out/'common-factual-basis.json',common)
    write(out/'joint-registry.json',registry)
    ambers,denominators=classifier_paths(evidence,allrows,origin,registry,out)
    codes=controller_paths(allrows,ambers,denominators,registry,out,source['all_sources'])
    value_paths(evidence,cp,allrows[126:],codes,registry,out)
    write(out/'summary.json',{'status':'COMPLETE_JOINT_NUMERICAL_INDEPENDENT_REVIEW_REQUIRED',
        'core_checkpoint_sha256':cp['sha256'],'joint_registry_sha256':digest(registry),'common_factual_basis_sha256':common_sha,
        'elapsed_seconds':time.monotonic()-started,'production_contacted':False,
        'global_selection_performed':False,'known_history_not_unseen':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();run(args.evidence,args.output)
