"""Qualified P07 ABMD entry, real neutral adoption, retained runtime and review."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import ast,json
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_abmd_models as models
import system_campaign_p07_abmd_origin as origin
import system_campaign_p07_abmd_legacy as legacy

HERE=Path(__file__).parent
CATALOG='P07-own1238-ABMD-bounded-catalog-v2.json'
CATALOG_SHA='9ee81ba4dfe9ceb6e4d486be601e5e171126f949f4897cb605061aa7a5d5fdc1'
DECLARATION='research.p07-abmd-bounded-declaration/1'
RETAINED='research.p07-abmd-retained-origin-declaration/1'
INITIAL_ROOT='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d'
LEGACY_PHASE=models.legacy.original.phase
PREPARATION_SHA='6a998f614f814b9dd4e4d20ff9c7f7a76389fdb4513689bdb7858c3c2cf57443'

def packet_tree(raw):
    need(sha(raw)==PREPARATION_SHA,'P07_ABMD_ENTIRE_ORIGINAL_PACKET_QUALIFIER_SOURCE')
    fn=models.legacy.original.function(raw,'qualify_packets')
    class Cumulative(ast.NodeTransformer):
        hits=0
        def visit_Call(self,node):
            if ast.unparse(node)=='backtest.apply_repair(original, loaded)':
                self.hits+=1;return ast.copy_location(ast.parse('apply_cumulative(original,loaded)',mode='eval').body,node)
            return self.generic_visit(node)
    adapter=Cumulative();fn=adapter.visit(fn);need(adapter.hits==1,'P07_ABMD_ONE_ACTUAL_CUMULATIVE_PACKET_APPLICATION')
    return ast.fix_missing_locations(fn)

def source_names():
    return ('system_campaign_p07_abmd_models.py','system_campaign_p07_abmd_certificate.py',
        'system_campaign_p07_abmd_origin.py','system_campaign_p07_abmd_legacy.py',
        'system_campaign_p07_abmd_lifecycle.py',models.PLAN,CATALOG)

def initial_spec():
    from system_campaign_financial_partial import root_spec
    return root_spec('P07',INITIAL_ROOT)

def catalog(*,source_bytes=None):
    from system_campaign_abmd_bounded_catalog import validate
    from system_campaign_financial_partial import root_spec
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'P07_ABMD_EXACT_FROZEN_CATALOG_GENERATION')
    return validate(json.loads(raw),root_lookup=root_spec,source_bytes=source_bytes)

def declaration(spec):
    need(spec.get('arm')=='P07','P07_ABMD_DECLARATION_ARM')
    return dict(schema=DECLARATION,arm='P07',catalog_file=CATALOG,catalog_sha256=CATALOG_SHA,
        initial_root_admission_sha256=INITIAL_ROOT,current_root_admission_sha256=spec['root_admission_sha256'],
        old_models_and_784_source_proofs_preserved=True,original_controller_source_unchanged=True,
        actual_owned_or_ordered_right_valuation_authorized=False,
        every_reachable_canonical_decision_must_match=True)

def retained_declaration(value):
    need(value['schema']==origin.SCHEMA and value['passed'] is True
         and value['initial_root_admission_sha256']==INITIAL_ROOT and value['catalog_sha256']==CATALOG_SHA,
         'P07_ABMD_RETAIN_ONLY_ACTUAL_QUALIFIED_NEUTRAL_ORIGIN')
    return dict(schema=RETAINED,initial_root_admission_sha256=INITIAL_ROOT,catalog_file=CATALOG,
        catalog_sha256=CATALOG_SHA,origin_file=origin.ORIGIN,origin_sha256=sha(origin.encoded(value)),
        descriptor=deepcopy(value['descriptor']),old_models_and_sources_preserved=True,
        prior_proof_rows_reexecuted=0)

def valid_retained(spec):
    d=spec.get('retained_abmd')
    if not isinstance(d,dict):return False
    need(set(d)=={'schema','initial_root_admission_sha256','catalog_file','catalog_sha256','origin_file','origin_sha256',
         'descriptor','old_models_and_sources_preserved','prior_proof_rows_reexecuted'}
         and d['schema']==RETAINED and d['initial_root_admission_sha256']==INITIAL_ROOT
         and d['catalog_file']==CATALOG and d['catalog_sha256']==CATALOG_SHA and d['origin_file']==origin.ORIGIN
         and d['old_models_and_sources_preserved'] is True and type(d['prior_proof_rows_reexecuted']) is int
         and d['prior_proof_rows_reexecuted']==0 and type(d['origin_sha256']) is str and len(d['origin_sha256'])==64,
         'P07_ABMD_EXACT_RETAINED_SOURCE_DECLARATION')
    need(all(c in '0123456789abcdef' for c in d['origin_sha256']),'P07_ABMD_ORIGIN_SHA256_CANONICAL_HEX')
    if 'root_admission_sha256' in spec:
        need(len(spec['repairs'])==24 and spec['repairs'][:23]==models.plan()['parent_descriptors']
             and spec['repairs'][23]==d['descriptor'],'P07_ABMD_RETAINED_TRANSPORT_FULL24_INPUT_HISTORY')
    return True

def selected(spec,request=None):
    if not isinstance(spec,dict) or spec.get('arm')!='P07':return False
    if valid_retained(spec):return True
    if spec.get('root_admission_sha256')!=INITIAL_ROOT:return False
    if request is None:request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
    record=request.get('selected_abmd_bounded_inputs',{}).get('P07')
    return record==declaration(spec) and request.get('execution_mode')=='OWN_ADMITTED_FINANCIAL_CONTINUATION'

def phase(spec):
    if spec.get('arm')!='P07':return LEGACY_PHASE(spec)
    root=spec.get('root_admission_sha256',spec.get('monthly_seed_root_admission_sha256'))
    if root==INITIAL_ROOT:
        return LEGACY_PHASE(spec) if 'root_admission_sha256' in spec else LEGACY_PHASE(initial_spec())
    need(valid_retained(spec),'P07_ABMD_LATER_PHASE_REQUIRES_ADMITTED_RETAINED_DECLARATION')
    from system_campaign_financial_partial import validate_root_spec,root_spec
    if 'root_admission_sha256' not in spec:
        admitted=root_spec('P07',root)
        need(admitted['root_admission_sha256']==root and admitted.get('retained_abmd')==spec['retained_abmd'],
             'P07_ABMD_READONLY_TRANSPORT_EXACT_INDEPENDENTLY_ADMITTED_SOURCE')
        spec=admitted
    validate_root_spec(spec)
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is proof['all_comparisons_and_state_sets_verified']
         is proof['all_math_watch_financial_chains_verified'] is True
         and type(proof['rows']) is type(proof.get('retained_rows',0)) is int
         and proof['rows']>=0 and proof.get('retained_rows',0)>=784,
         'P07_ABMD_ACTUAL_CURRENT_ADMISSION_PROOF_COUNTS_AND_CHAINS')
    value=deepcopy(LEGACY_PHASE(initial_spec()))
    value.update(root_admission_sha256=spec['root_admission_sha256'],outer_sha256=spec['outer_sha256'],
        completed=spec['measured_closes'],source_cursor=spec['selected_session'],
        proof_rows=proof['rows']+proof.get('retained_rows',0),proof_new_rows=proof['rows'],
        proof_retained_rows=proof.get('retained_rows',0))
    models.legacy.original.retained_origin(value)
    return value

def check_retained_origin(root,current,catalog,spec):
    checked=origin.verify(root,current,catalog)
    if valid_retained(spec):
        need(sha((Path(root)/origin.ORIGIN).read_bytes())==spec['retained_abmd']['origin_sha256'],
             'P07_ABMD_ADMITTED_RETAINED_ORIGIN_BYTES')
    return checked

def runtime_api(root,cp,spec,value,*,seed_bridge=None):
    from full_system_core import hosted
    hosted()
    root=Path(root)
    from research.pooled_input_support import inputs
    from research.pooled_vacancy_funding import backtest
    from system_campaign_bounded_sensor_input import InputCodec
    from system_campaign_abmd_bounded_catalog import evidence
    check_retained_origin(root,cp,value,spec)
    def review_new(parent,current,evidence_root,out,selected):
        checked=check_retained_origin(evidence_root,current,value,selected)
        if len(parent['repairs'])==23:
            need(parent==checked['parent'],'P07_ABMD_REVIEW_ACTUAL_INITIAL_PARENT_NO_SUBSTITUTE')
        else:
            need(parent['repairs']==current['repairs'] and (Path('/old')/origin.ORIGIN).read_bytes()==
                 (Path(evidence_root)/origin.ORIGIN).read_bytes(),'P07_ABMD_RESTART_NO_READOPTION_OR_ORIGIN_CHANGE')
        return True
    api=legacy.build(root,cp,spec,value,phase=phase,root_metadata=initial_spec(),review_bounded_origin=review_new,
                     seed_bridge=seed_bridge)
    prior_chain,prior_models,prior_preserve=api.original_chain,api.retained_models,api.preserve
    @contextmanager
    def chain(where,actual,selected):
        check_retained_origin(where,actual,value,selected)
        with prior_chain(where,actual,selected) as old_chain:
            native,=[v for v in inputs.load_actions(Path('/frozen/bundle')).terminal.get(value['event']['native_session'],())
                      if v.security_id==value['event']['security_id']]
            need(asdict(native)==value['native'],'P07_ABMD_ACTUAL_RETAINED_FROZEN_NATIVE')
            with InputCodec(value['event'],evidence(value),native) as codec:
                d=actual['repairs'][23]
                obj=backtest.load_repair(Path(where)/'book/repairs'/d['filename'],resume_session=d['resume_session'],
                    predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
                need(obj.sha256==d['sha256'] and obj in codec.objects,'P07_ABMD_ACTUAL_INSTALLED_RETAINED_TYPED_INPUT')
                yield old_chain
    def retained_models(where,actual,selected):
        check_retained_origin(where,actual,value,selected);return prior_models(where,actual,selected)
    def preserve(where,actual,out,selected):
        prior_preserve(where,actual,out,selected);origin.preserve(where,out,actual,value)
        if actual['source_cursor']>=value['event']['effective_session']:
            from system_campaign_bounded_sensor_event_review import permissions
            from system_campaign_financial_branches import seed
            event_rows=[row for row in seed(Path(where),actual)
                        if row['session']==value['event']['effective_session']]
            _,resolutions=permissions(where,event_rows,value,through=actual['source_cursor'],input_descriptors=actual['repairs'])
            need(len(resolutions)==1,'P07_ABMD_RETAIN_ONE_ACTUAL_COMMITTED_EVENT_ARCHIVE')
            name=resolutions[0]['actual'];raw=(Path(where)/name).read_bytes()
            need(sha(raw)==resolutions[0]['gzip_sha256'],'P07_ABMD_RETAIN_EXACT_ACTUAL_PRODUCER_GZIP_BYTES')
            origin.write_exact(Path(out)/name,raw)
    namespace=api.run.__globals__;namespace['original_chain']=chain;namespace['retained_models']=retained_models;namespace['preserve']=preserve
    return SimpleNamespace(**namespace)

def run_initial(parent,out,args,rows,observer,execution,spec,old):
    from full_system_core import hosted
    hosted()
    from system_campaign_ordinary_augmentation_runtime import api as old_api
    from system_campaign_uncertainty_archive import preserve as preserve_archive
    from system_campaign_abmd_bounded_hydration import hydrate
    from system_campaign_abmd_bounded_catalog import evidence,document
    import system_campaign_abmd_bounded_preparation as preparation
    from system_campaign_bounded_sensor_input import InputCodec
    from research.pooled_vacancy_funding import backtest
    value=catalog();source=old_api(old,parent,spec);p=phase(spec)
    need(parent['sha256']==models.plan()['parent_outer_sha256'] and parent['repairs']==models.plan()['parent_descriptors'],
         'P07_ABMD_FINANCIAL_START_ONLY_ACTUAL_OWN1238_FULL23')
    hashes,seed,qualified=source.retained_seed(old,parent,spec,p)
    need(len(seed)==784,'P07_ABMD_ALL784_ORIGINAL_SEED_GUARDS_PASSED_BEFORE_ADOPTION')
    preserve_archive(Path(old),Path(out))
    native,market=hydrate(value,Path(out)/origin.SOURCE)
    origin.write_exact(Path(out)/origin.DOCUMENT,origin.encoded(document(value)))
    with InputCodec(value['event'],evidence(value),native) as codec:
        loaded=backtest.load_repair(Path(out)/origin.DOCUMENT,resume_session=parent['source_cursor'],
            predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
        objects=[backtest.load_repair(Path(out)/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
        def apply_cumulative(packet,final):
            for old_object in objects:packet=backtest.apply_repair(packet,old_object)
            return backtest.apply_repair(packet,final)
        packet_scope=dict(vars(preparation),apply_cumulative=apply_cumulative)
        exec(compile(ast.Module(body=[packet_tree(Path(preparation.__file__).read_bytes())],type_ignores=[]),
            '<whole-original-packet-qualifier-all23-old-inputs-plus-ABMD>','exec'),packet_scope)
        packets=packet_scope['qualify_packets'](parent,Path(out)/origin.DOCUMENT,loaded,native,value)
        modeled=origin.adopt(parent,out,args,rows,value,codec,spec,Path(old))
        origin.write_exact(Path(out)/'p07-abmd-financial-entry-qualification.json',origin.encoded(dict(
            passed=True,catalog_sha256=CATALOG_SHA,old_proof_rows=784,old_proof_rows_reexecuted=0,
            packets=packets,canonical_neutral_adoption_completed=True,financial_sessions_advanced=0)))
        api=runtime_api(out,modeled,spec,value,seed_bridge=(parent,hashes,seed,qualified))
        return api.run_retained(modeled,Path(out),args,rows,observer,execution,spec,Path(out),p)

def api(root,cp,spec):
    from full_system_core import hosted
    hosted()
    from system_campaign_ordinary_augmentation_runtime import api as old_api
    value=catalog()
    if len(cp['repairs'])==23 and (Path(root)/origin.ORIGIN).is_file():
        from research.pooled_vacancy_funding import journal
        current=journal.read_checkpoint(Path(root)/'book/checkpoint.json.gz')
        need(current['repairs'][:23]==cp['repairs'] and len(current['repairs'])==24,
             'P07_ABMD_REVIEW_ACTUAL_CURRENT24_WITH_ORIGINAL23_PARENT')
        return runtime_api(root,current,spec,value)
    if len(cp['repairs'])==23:
        old=old_api(root,cp,spec)
        return SimpleNamespace(**dict(vars(old),run=run_initial))
    return runtime_api(root,cp,spec,value)

@contextmanager
def entry(spec):
    from full_system_core import hosted
    hosted()
    if not selected(spec):yield;return
    import system_campaign_financial_additional_sensor as additional
    import system_campaign_ordinary_augmentation_router as router
    saved=(additional.phase,router.implementation)
    def implementation(root,cp,selected_spec):
        return api(root,cp,selected_spec) if selected(selected_spec) else saved[1](root,cp,selected_spec)
    additional.phase=phase;router.implementation=implementation
    try:yield
    finally:additional.phase,router.implementation=saved
