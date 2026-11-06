"""Three actual neutral cash adoptions, then one unchanged financial main."""
import ast,gzip,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path,PurePosixPath
from types import FunctionType
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_financial_future as future
import system_campaign_p05_batch_data as data
import system_campaign_p05_batch_api as api_module
import system_campaign_retained_cash_materials_v2 as original_materials

HERE=Path(__file__).parent
CHAIN='P05-neutral-cash-batch-chain.json'
PARENT='p05-neutral-batch-origin/actual-parent-checkpoint.json.gz'
U_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
MATERIALS_SHA='54a637eba2b34f17efd17125e1eeaa24c30684246c04cfa1ad58bdf3a114d06a'
ORIGINAL_INVENTORY=original_materials.inventory
need,sha,digest,encoded=data.need,data.sha,data.digest,data.encoded

def exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'P05_BATCH_EXISTING_RESOURCE_BYTES_IDENTICAL')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)

def strict_json(raw):
    cp=json.loads(gzip.decompress(raw));run=cp['run']
    need(cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==digest(run['state']) and cp['source_cursor']==run['state']['last_processed_session']
         and run['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),
         'P05_BATCH_ALL_ACTUAL_JSON_COMMITMENTS')
    return cp

def initial(spec):return isinstance(spec,dict) and spec.get('arm')=='P05' and spec.get('root_admission_sha256')==data.ROOT

def family(spec):
    if initial(spec):return True
    if not isinstance(spec,dict) or spec.get('arm')!='P05' or len(spec.get('repairs',[]))<19:return False
    from system_campaign_financial_partial import root_spec
    return spec['repairs'][:16]==root_spec('P05',data.ROOT)['repairs']

def source_names():
    return (Path(__file__).name,'system_campaign_p05_batch_data.py','system_campaign_p05_batch_api.py',
        *data.PINS,data.SUPPORTED,*data.acc.source_names())

def declaration(spec):
    need(family(spec),'P05_BATCH_ONLY_EXACT_SOURCE_BOUND_REQUEST_FAMILY')
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    return dict(schema='research.p05-bounded-neutral-cash-batch-declaration/1',arm='P05',
        root_admission_sha256=spec['root_admission_sha256'],origin_root_admission_sha256=data.ROOT,
        source_scope_sha256=data.SCOPE,source_qualification_sha256=data.PINS['P05-batch-source-qualification-v2.json'],
        chunk_sizes=[30,30,6],original_repair_maximum_source_evidence=128,initial_adoption_required=initial(spec),
        financial_entry_scope='INITIAL_OWN1152_ONLY',original_canonical_financial_source_unchanged=True)

def adoption_tree(raw):
    need(sha(raw)==U_SHA,'P05_BATCH_ENTIRE_ORIGINAL_NEUTRAL_ADOPTION_HELPER')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
    mapping=next(n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    need(isinstance(mapping,ast.Dict) and [ast.unparse(k) for k in mapping.keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION']
         and [ast.unparse(v) for v in mapping.values]==["'future-financial-overlay.json'",'DATE_OVERLAY',"'branch-uncertainty-input.json'"],
         'P05_BATCH_EXACT_ORIGINAL_FILENAME_MAP')
    for index in range(3):mapping.keys.append(ast.Constant(api_module.directory(index)));mapping.values.append(ast.Constant(api_module.overlay(index)))
    return ast.fix_missing_locations(fn)

def adopter():
    fn=adoption_tree(Path(uncertainty.__file__).read_bytes());scope=dict(vars(uncertainty))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<entire-original-neutral-adoption-three-explicit-filenames>','exec'),scope)
    return scope['paused_own_adoption']

def chain_relations(value,current,member):
    """Read genuine archived boundaries; never form or restore a checkpoint."""
    from system_campaign_pxd_pause import adoption
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P05',data.ROOT)
    need(value['schema']=='research.p05-actual-neutral-cash-batch-chain/1' and value['passed'] is True
         and value['origin_root_admission_sha256']==data.ROOT and value['financial_sessions_advanced']==0
         and type(value['financial_sessions_advanced']) is int and value['origin_parent_is_retained_financial_seed'] is False
         and value['canonical_financial_source_changed'] is False and len(value['stages'])==3,
         'P05_BATCH_CHAIN_EXACT_INITIAL_AUTHORITY_AND_THREE_STAGES')
    pins=value['resources']
    need(type(pins) is dict and pins and all(type(n) is str and not PurePosixPath(n).is_absolute()
         and '..' not in PurePosixPath(n).parts and ':' not in n and '\\' not in n for n in pins),
         'P05_BATCH_SAFE_WHOLE_RESOURCE_INVENTORY_BEFORE_READ')
    blobs={n:member(n) for n in pins}
    need(all(dict(bytes=len(blobs[n]),sha256=sha(blobs[n]))==pin for n,pin in pins.items())
         and pins[PARENT]==spec['selected_file'],'P05_BATCH_ALL_WHOLE_RESOURCE_BYTES_AND_ORIGINAL_PARENT_GZIP')
    initial_parent=strict_json(blobs[PARENT]);data.parent_contract(initial_parent);before=initial_parent
    watch=member('book/watch.jsonl');summaries=[]
    required={PARENT}
    for index,stage in enumerate(value['stages']):
        directory=api_module.directory(index);overlay=api_module.overlay(index);catalog=api_module.catalog_name(index)
        names=(directory+'/checkpoint.json.gz',directory+'/proof.json',directory+'-correlation-inputs.jsonl.gz',overlay,catalog,
            api_module.qualification(index),future.hydration_name(before))
        required.update(names)
        need(all(n in blobs for n in names) and stage['index']==index and stage['parent_outer_sha256']==before['sha256'],
             'P05_BATCH_EACH_ACTUAL_STAGE_PARENT_AND_EXACT_RESOURCE_SET')
        after=strict_json(blobs[names[0]]);doc=json.loads(blobs[overlay]);proof=json.loads(blobs[names[1]])
        earliest=min(r['session'] for key in ('suppress','add') for r in doc[key])
        event=adoption(after,before,sha(blobs[overlay]),earliest)
        need(stage['successor_outer_sha256']==after['sha256'] and proof==dict(event=event,
             actual_checkpoint_gzip_sha256=sha(blobs[names[0]]),original_outer_sha256=before['sha256'],
             financial_state_unchanged=True,financial_sessions_advanced=0)
             and len(after['repairs'])==17+index and after['repairs'][-1]['predecessor_checkpoint_sha256']==before['run']['checkpoint_sha256']
             and after['run']['state']==initial_parent['run']['state'] and after['completed']==initial_parent['completed']
             and after['source_cursor']==initial_parent['source_cursor'], 'P05_BATCH_ENTIRE_ACTUAL_NEUTRAL_CHAIN_NO_FINANCIAL_ADVANCE')
        a,b=before['journals']['watch'],after['journals']['watch']
        need(sha(watch[:a['bytes']])==a['prefix_sha256'] and sha(watch[:b['bytes']])==b['prefix_sha256']
             and [json.loads(line) for line in watch[a['bytes']:b['bytes']].splitlines()]==[event],
             'P05_BATCH_ONLY_ONE_CANONICAL_SUCCESSOR_WATCH_PER_NEUTRAL_STAGE')
        need(sha(gzip.decompress(blobs[names[2]]))==value['original_correlation_rows_sha256']
             and len(doc['source_evidence'])<=128 and doc['schema']=='terminal-repair/1'
             and doc['predecessor_checkpoint_sha256']==before['run']['checkpoint_sha256'],
             'P05_BATCH_ZERO_NEW_CORRELATION_AND_ORIGINAL128_EVIDENCE_CAP')
        summaries.append(dict(index=index,parent=before['sha256'],successor=after['sha256'],source_evidence=len(doc['source_evidence'])))
        before=after
    need(set(blobs)==required and current['sha256']==digest({k:v for k,v in current.items() if k!='sha256'})
         and current['run']['checkpoint_sha256']==digest({k:v for k,v in current['run'].items() if k!='checkpoint_sha256'})
         and current['run']['state_sha256']==digest(current['run']['state'])
         and current['source_cursor']==current['run']['state']['last_processed_session']
         and current['base']==initial_parent['base'] and current['repairs'][:19]==before['repairs']
         and current['run']['input_sha256']==digest(dict(base=current['base'],repairs=current['repairs']))
         and current['completed']>=before['completed'] and current['source_cursor']>=before['source_cursor'],
         'P05_BATCH_CURRENT_FULL19_PREFIX_AND_UNTRUNCATED_INPUT_HASH')
    return initial_parent,before,summaries

def preserve_chain(root,current,out):
    from full_system_core import hosted
    hosted()
    root,out=Path(root),Path(out);raw=(root/CHAIN).read_bytes();value=json.loads(raw)
    chain_relations(value,current,lambda n:(root/n).read_bytes())
    for n in value['resources']:exact(out/n,(root/n).read_bytes())
    exact(out/CHAIN,raw)

def inventory(cp,plan,names,member):
    original=original_materials
    need(sha(Path(original.__file__).read_bytes())==MATERIALS_SHA and ORIGINAL_INVENTORY.__closure__ is None,
         'P05_BATCH_ENTIRE_ORIGINAL_MATERIAL_INVENTORY_SOURCE')
    fn=FunctionType(ORIGINAL_INVENTORY.__code__,dict(ORIGINAL_INVENTORY.__globals__,RULES=original.RULES|{data.acc.NEXT}),
        ORIGINAL_INVENTORY.__name__,ORIGINAL_INVENTORY.__defaults__)
    result=fn(cp,plan,names,member)
    for term in result['terms']:
        if term['recognition_rule']==data.acc.NEXT:
            need(term['security_id']==data.acc.SID,'P05_BATCH_NEXT_ONLY_EXACT_ACC_NO_OTHER_POLICY_UPGRADE')
            value=json.loads(member(CHAIN));raw=member(PARENT)
            need(dict(bytes=len(raw),sha256=sha(raw))==value['resources'][PARENT],'P05_BATCH_INVENTORY_AUTHENTIC_ORIGINAL_PARENT_METADATA')
            data.validate_acc_bound(term,strict_json(raw))
    return result

class BatchGate:
    def __init__(self,initial,out,args_rows,spec,catalogs):
        self.initial,self.out,self.rows,self.spec,self.catalogs=initial,Path(out),args_rows,spec,catalogs
        self.in_adoption=False;self.started=False;self.completed=False
        self.first=self.prepare(initial,0)
        exact(self.out/future.OVERLAY,(self.out/api_module.overlay(0)).read_bytes())
    def prepare(self,current,index):
        from full_system_core import hosted
        hosted()
        api=api_module.api(self.initial,current,self.catalogs[index],index)
        exact(self.out/api_module.catalog_name(index),encoded(self.catalogs[index]))
        path,loaded=api.prepare(current,self.out,'P05')
        material=json.loads((self.out/future.hydration_name(current)).read_bytes());doc=json.loads(path.read_bytes())
        need(material['terms']==self.catalogs[index]['terms'] and len(doc['source_evidence'])<=128
             and loaded.sha256==sha(path.read_bytes()) and path.name==api_module.overlay(index),
             'P05_BATCH_WHOLE_ACTUAL_PREPARED_CHUNK_AND_ORIGINAL_EVIDENCE_CAP')
        qualified=json.loads((self.out/api_module.qualification(index)).read_bytes())
        need(qualified['passed'] is True and type(qualified['financial_sessions_advanced']) is int
             and qualified['financial_sessions_advanced']==0,'P05_BATCH_ACTUAL_PHASE_QUALIFICATION_SAVED_EXCLUSIVELY')
        return api,path,loaded
    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest
        self.backtest=backtest;self.original_main=backtest.main;backtest.main=self.main;return self
    def __exit__(self,*args):self.backtest.main=self.original_main
    def main(self,args):
        from full_system_core import hosted
        hosted()
        if self.in_adoption:return self.original_main(args)
        need(not self.started and '--repair-overlay' not in args,'P05_BATCH_ONE_FINAL_ORIGINAL_MAIN_WITHOUT_EXTRA_OVERLAY')
        self.started=True;current=self.initial;stages=[];resources={}
        parent_raw=(self.out/'book/predecessor-checkpoints'/(self.initial['sha256']+'.json.gz')).read_bytes()
        need(dict(bytes=len(parent_raw),sha256=sha(parent_raw))==self.spec['selected_file'],'P05_BATCH_ACTUAL_ORIGINAL_SELECTED_PARENT_GZIP')
        exact(self.out/PARENT,parent_raw)
        resources[PARENT]=dict(bytes=len(parent_raw),sha256=sha(parent_raw))
        for index in range(3):
            api,path,loaded=self.first if index==0 else self.prepare(current,index)
            before=current;self.in_adoption=True
            try:current=adopter()(before,self.out,args,self.rows,path,loaded.earliest_affected_session,api_module.directory(index))
            finally:self.in_adoption=False
            directory=api_module.directory(index)
            names=(directory+'/checkpoint.json.gz',directory+'/proof.json',directory+'-correlation-inputs.jsonl.gz',api_module.overlay(index),
                api_module.catalog_name(index),api_module.qualification(index),future.hydration_name(before))
            for name in names:
                raw=(self.out/name).read_bytes();resources[name]=dict(bytes=len(raw),sha256=sha(raw))
            stages.append(dict(index=index,parent_outer_sha256=before['sha256'],successor_outer_sha256=current['sha256']))
        value=dict(schema='research.p05-actual-neutral-cash-batch-chain/1',passed=True,origin_root_admission_sha256=data.ROOT,
            origin_parent_is_retained_financial_seed=False,financial_sessions_advanced=0,canonical_financial_source_changed=False,
            original_correlation_rows_sha256=sha(b''.join(self.rows)),stages=stages,resources=resources)
        chain_relations(value,current,lambda n:(self.out/n).read_bytes());exact(self.out/CHAIN,encoded(value));self.completed=True
        return self.original_main(args)

def review_chain(evidence,out,parent,spec):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    evidence,out=Path(evidence),Path(out);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
    value=json.loads((evidence/CHAIN).read_bytes());original,last,summaries=chain_relations(value,current,lambda n:(evidence/n).read_bytes())
    need(not initial(spec) or original==parent and current['repairs']==last['repairs'] and len(current['repairs'])==19
         and current['run']['input_sha256']==last['run']['input_sha256'],
         'P05_BATCH_REVIEW_EXACT_ACTUAL_ORIGINAL_PARENT_AND_FULL19_FINANCIAL_SEGMENT')
    catalogs=data.catalogs(evidence,original);before=original
    for index,stage in enumerate(value['stages']):
        api=api_module.api(original,before,catalogs[index],index)
        need((evidence/api_module.catalog_name(index)).read_bytes()==encoded(catalogs[index]),'P05_BATCH_INDEPENDENT_EXACT_FULL_QUALIFIED_CATALOG')
        earliest=api.review_input(before,evidence,'P05')
        after=strict_json((evidence/api_module.directory(index)/'checkpoint.json.gz').read_bytes())
        need(earliest==min(t['native_session'] for t in catalogs[index]['terms']) and after['sha256']==stage['successor_outer_sha256'],
             'P05_BATCH_INDEPENDENT_FULL_MATERIAL_AND_NEUTRAL_CHAIN_RECONSTRUCTION')
        before=after
    exact(out/'P05-neutral-cash-batch-chain-review.json',encoded(dict(passed=True,stages=summaries,
        original_financial_seed_root_admission_sha256=data.ROOT,neutral_financial_sessions_advanced=0,
        all_original_source_and_economic_predicates_retained=True,actual_initial16_then_full19=True)))
    return current

@contextmanager
def entry_context(module,spec):
    if not family(spec):yield;return
    need(getattr(module,'EXECUTION_MODE',None)!='OWN_ADMITTED_FINANCIAL_CONTINUATION' or initial(spec),
         'P05_BATCH_FINANCIAL_ENTRY_INITIAL_OWN1152_ONLY_FUTURE_GENERATION_UNQUALIFIED')
    import system_campaign_retained_cash_v2 as cash
    import system_campaign_retained_cash_materials_v2 as materials
    import system_campaign_pending_cash_api as pending
    saved=[];session=[None]
    def patch(owner,name,fn):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,fn)
    old_stage,old_inputs,old_overlay,old_review=cash.stage,module.financial_inputs,module.qualified_overlay,module.review_adoption
    old_parent=pending.for_parent
    patch(materials,'inventory',inventory)
    def stage(root,current,out,plan):
        prior=old_stage(root,current,out,plan)
        if not initial(spec):return prior
        chunks=data.catalogs(root,current)
        need(len(prior)==28,'P05_BATCH_ALL28_AUTHENTIC_PRIOR_OBSERVATION_TERMS')
        return cash.union_terms(prior,*[c['terms'] for c in chunks])
    patch(cash,'stage',stage)
    @contextmanager
    def financial_inputs(root,current,out,target):
        if family(target) and not initial(target):preserve_chain(root,current,out)
        with old_inputs(root,current,out,target):yield
    patch(module,'financial_inputs',financial_inputs)
    def qualified_overlay(current,out,target):
        if not initial(target):return old_overlay(current,out,target)
        from system_campaign_financial_compound_dispatch import selected
        need(selected(current,'P05') is None,'P05_BATCH_ORIGINAL_ECONOMIC_BODY_WILL_CONSTRUCT_ACTUAL_OBSERVER')
        need(session[0] is None,'P05_BATCH_ONE_ACTUAL_INITIAL_BATCH_SESSION')
        rows=module.seed_rows(Path('/old'),current,target)
        gate=BatchGate(current,out,rows,target,data.catalogs(out,current));session[0]=gate
        return [],gate
    patch(module,'qualified_overlay',qualified_overlay)
    def for_parent(current,arm):
        if arm!='P05' or current['sha256']!=data.OUTER:return old_parent(current,arm)
        need(session[0] is not None,'P05_BATCH_OBSERVER_ONLY_AFTER_EXACT_FIRST_PREPARATION')
        return session[0].first[0]
    patch(pending,'for_parent',for_parent)
    def review_adoption(evidence,parent,target):
        if not initial(target):return old_review(evidence,parent,target)
        return review_chain(evidence,Path('/out'),parent,target)
    patch(module,'review_adoption',review_adoption)
    try:yield
    finally:
        for owner,name,fn in reversed(saved):setattr(owner,name,fn)
