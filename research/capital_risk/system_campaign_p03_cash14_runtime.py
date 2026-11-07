"""Finite financial profile: actual524/full17 through genuine fourteen-term input18."""
import ast,gzip,inspect,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_p03_cash14_data as data
import system_campaign_p03_cash14_api as api_module
import system_campaign_p03_cash14_lifecycle as lifecycle
import system_campaign_p03_thor_qualification_reuse as reuse
import system_campaign_bounded_sensor_binding as binding
HERE=Path(__file__).parent
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
FIELD='selected_p03_cash14_ordinary18'
QUALIFICATION='P03-own524-14cash18-private-qualification.json'
RECEIPT='p03-cash14-exact70-qualification-reuse.json'
PREPARATION='P03-cash14-original28-packet-preparation.json'
OBSERVER_INVENTORY='P03-own524-original19-observer-inventory.json'
OBSERVER_SHA='8ee5499cd9d920b47eccf934c31581e1bb938d722c73e0089652a72bcfaa90a4'
need,sha,encoded=data.need,data.sha,data.encoded
def selected(spec):return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==data.ROOT
def validate_spec(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);value=data.facts()
    need(selected(spec) and {k:v for k,v in spec.items() if k!='root_admission'}==value['parent_transport']
        and spec['root_admission']['branch_uncertainty_proof']==value['branch_proof'],'P03_14_EXACT_ADMITTED524_FULL17_REQUEST_SPEC')
def qualification():
    raw=(HERE/QUALIFICATION).read_bytes();value=json.loads(raw)
    need(value['passed'] is True and value['root_admission_sha256']==data.ROOT and value['financial_authority'] is False
        and value['canonical_runtime_executed'] is value['neutral18_known'] is False,'P03_14_ONLY_CLOSED_PRIVATE_PREPARATION_NOT_FINANCIAL_RESULT')
    for name,pin in value['files'].items():need(sha((HERE/name).read_bytes())==pin['sha256'],'P03_14_FROZEN_PRIVATE_PREREQUISITE:'+name)
    return sha(raw)
def declaration(spec):
    validate_spec(spec)
    return dict(schema='research.P03-own524-cash14-genuine-ordinary18-financial-declaration/1',arm='P03',root_admission_sha256=data.ROOT,
        original_outer_sha256=data.OUTER,original_inputs=17,required_actual_neutral_inputs=18,old_committed_proof_rows=70,
        entire_raw_proof_rows=81,unadmitted_tail_rows_seeded=0,batch_terms=14,existing_observer_terms=19,required_total_observer_terms=33,
        qualification_sha256=qualification(),required_actual_preflight_packet_checks=28,actual_future_neutral_checkpoint_known=False,
        future18_root_restart_selected=False,financial_source_changed=False,provider_metadata_upgraded=False)
def request_selected(spec,request):
    return (selected(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False
        and request.get(FIELD,{}).get('P03')==declaration(spec))
def expected_thor_request(original,*,execution_mode,selected_arms,root_lookup):
    if execution_mode!=MODE or 'P03' not in selected_arms or not selected(root_lookup('P03')):
        return lifecycle.original.expected_request(original,execution_mode=execution_mode,selected_arms=selected_arms,root_lookup=root_lookup)
    spec=root_lookup('P03');validate_spec(spec)
    result=lifecycle.original.expected_request(original,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P03'),root_lookup=root_lookup)
    need(result['admitted_checkpoints']['P03']==data.OUTER and result[lifecycle.original.FIELD]=={},'P03_14_ONLY_SEPARATE_PROFILE_BYPASSES_OLD17_REFUSAL')
    result['arm_inputs']['P03']['new_factual_overlay']=True
    return result
def source_names():return tuple(sorted({Path(__file__).name,QUALIFICATION,OBSERVER_INVENTORY,'system_campaign_p03_cash14_stage.py',Path(lifecycle.__file__).name,*api_module.source_names()}))
def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original();need(FIELD not in result,'P03_14_NO_REPLACED_FINANCIAL_DECLARATION');result[FIELD]={}
    if execution_mode==MODE and 'P03' in selected_arms and selected(root_lookup('P03')):result[FIELD]['P03']=declaration(root_lookup('P03'))
    for name in source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,'P03_14_NO_REPLACED_SOURCE_PIN');result['sources'][name]=pin
    return result
def seed_contract(rows,current,spec):
    validate_spec(spec);fact=data.facts();raw=reuse.seed_bytes(rows)
    need(dict(rows=len(rows),bytes=len(raw),sha256=sha(raw))==fact['retained_seed'] and len(rows)==70
        and current['completed']==524 and current['source_cursor']=='2020-01-31' and len(current['repairs'])==18
        and current['repairs'][:17]==spec['repairs'] and current['base']==spec['base']
        and current['run']['state_sha256']==spec['state_sha256']==data.digest(current['run']['state'])
        and current['run']['input_sha256']==data.digest(dict(base=current['base'],repairs=current['repairs']))
        and current['sha256']==data.digest({k:v for k,v in current.items() if k!='sha256'})
        and rows[-1]['session']==current['source_cursor'] and rows[-1]['next_state_sha256']==current['run']['state_sha256'],
        'P03_14_ONLY_REAL_NEUTRAL18_AND_EXACT70_ADMITTED_SEED')
    return fact['retained_seed']
def qualification_contract(out,current,spec,old,rows,hashes,qualified):
    out,old=Path(out),Path(old);fact=data.facts();seed_contract(rows,current,spec)
    need(dict(bytes=len(qualified),sha256=sha(qualified))==fact['qualification_file']
        and (old/'branch-controller-qualification.json').read_bytes()==qualified,'P03_14_EXACT_ORIGINAL922_CONTROLLER_QUALIFICATION')
    parentraw=(out/lifecycle.SELECTED).read_bytes();need(dict(bytes=len(parentraw),sha256=sha(parentraw))==spec['selected_file']
        and (old/spec['selected_checkpoint']).read_bytes()==parentraw,'P03_14_ACTUAL_SELECTED17_ARCHIVE_NEVER_REPLACED')
    parent=lifecycle.strict_json(parentraw);data.parent_contract(parent,spec)
    corr=gzip.decompress((out/(api_module.DIRECTORY+'-correlation-inputs.jsonl.gz')).read_bytes()).splitlines(keepends=True)
    boundary=lifecycle.namespace()['boundary_relation'](parent,current,spec,lambda n:(out/n).read_bytes(),corr)
    need(lifecycle.strict_json((out/'book/checkpoint.json.gz').read_bytes())==current,'P03_14_REAL_PREFINANCIAL_NEUTRAL18_BOOK')
    raw=(out/lifecycle.RAW_PROOF).read_bytes();lines=raw.splitlines(keepends=True)
    need(dict(rows=len(lines),bytes=len(raw),sha256=sha(raw))==fact['entire_raw_proof']
        and (old/'uncertainty-certificate.jsonl').read_bytes()==raw and b''.join(lines[:70])==reuse.seed_bytes(rows)
        and all(json.loads(v)['session']>'2020-01-31' for v in lines[70:]),'P03_14_RETAIN_ALL81_RAW_ROWS_SEED_ONLY70_EXCLUDE11_TAILS')
    q=json.loads(qualified)
    need(q['passed'] is q['actual_divergent_decisions_refused'] is q['all_possible_counters_retained_and_later_merged'] is q['ambiguous_comparisons_exhaustively_partitioned'] is True
        and q['historical_financial_sessions_advanced']==0 and hashes==q['exact_controller_sources']
        and len(hashes)==6 and all(current['base']['sources'][n]==h for n,h in hashes.items()),'P03_14_ALL_SIX_UNCHANGED_CONTROLLER_SOURCES')
    return dict(schema='research.P03-cash14-exact70-qualification-reuse/1',passed=True,root_admission_sha256=data.ROOT,
        real_neutral_outer_sha256=current['sha256'],selected_parent_outer_sha256=parent['sha256'],qualified_file=fact['qualification_file'],
        entire_raw_proof=fact['entire_raw_proof'],exact_admitted_prefix=fact['retained_seed'],unadmitted_tail_rows_seeded=0,boundary=boundary,financial_sessions_advanced=0)
def qualification_present(*args):
    qualification_contract(*args);out=Path(args[0]);qualified=args[-1];path=out/'branch-controller-qualification.json'
    if not path.exists():return False
    need(path.is_file() and not path.is_symlink() and path.read_bytes()==qualified,'P03_14_EXISTING_OUTPUT_ONLY_EXACT_QUALIFIED_DATA');return True
def qualification_postcondition(*args):
    *values,present=args;receipt=qualification_contract(*values);out=Path(values[0]);qualified=values[-1]
    need(type(present) is bool and (out/'branch-controller-qualification.json').read_bytes()==qualified,'P03_14_ORIGINAL_CREATE_OR_EXACT_REUSE_POSTCONDITION')
    receipt['mode']='EXACT_EXISTING_QUALIFICATION_REUSED' if present else 'ORIGINAL_EXCLUSIVE_WRITER_CREATED';lifecycle.exact(out/RECEIPT,encoded(receipt))
def run_tree():
    fn=FunctionType(reuse.run_tree.__code__,dict(reuse.run_tree.__globals__,facts=data.facts),reuse.run_tree.__name__,reuse.run_tree.__defaults__)
    return fn()
def bound_body(name,bindings):
    original=lifecycle.typed.bound_body(name,bindings)
    if name!='run_retained':return original
    scope=dict(original.__globals__,qualification_present=qualification_present,qualification_postcondition=qualification_postcondition)
    exec(compile(ast.Module(body=[run_tree()],type_ignores=[]),'<whole-original-retained-body-exact70-DATA-reuse>','exec'),scope)
    return scope['run_retained']
def constructor_seed(seed,event,current,spec):
    pin=seed_contract(seed,current,spec)
    need(event==lifecycle.typed.catalog()['event'] and event['native_session']<=current['source_cursor']
        and seed[-1]['session']>=event['native_session'],'P03_14_ONLY_REAL_CONSUMED_DOVA_EVENT_AND70_SEED')
    return pin
def observers(root,current,count):
    import system_campaign_bounded_sensor_observers_v2 as original
    raw=(HERE/OBSERVER_INVENTORY).read_bytes();need(sha(raw)==OBSERVER_SHA,'P03_14_EXACT_ACTUAL_ORIGINAL19_OBSERVER_INVENTORY')
    old=json.loads(raw);root=Path(root);contractraw=(root/original.DIRECTORY/original.CONTRACT).read_bytes()
    need(sha(contractraw)==old['original_contract_sha256'] and old['parent_outer_sha256']==data.OUTER,'P03_14_ORIGINAL18_CONTRACT_BYTES_NEVER_REPLACED')
    contract=json.loads(contractraw);tail,resources=original.tail_materials(root,current);terms=original.merge(contract['terms'],tail)
    need(len(terms)==count and terms==original.merge(old['terms'],data.terms()) if count==33 else terms==old['terms'],
        'P03_14_COMPLETE19_OLD_PLUS14_NEW_OBSERVER_TERMS_NO_LOSS_OR_DUPLICATION')
    for n,pin in old['resources'].items():
        raw=(root/n).read_bytes();need(dict(bytes=len(raw),sha256=sha(raw))==pin,'P03_14_ALL_ORIGINAL_THOR_OBSERVER_MATERIAL_BYTES')
    return terms
def require_preflight(out,spec):
    root=Path(out)/'parent-preflight';value=json.loads((root/PREPARATION).read_bytes())
    need(value['passed'] is True and value['root_admission_sha256']==data.ROOT and value['parent_outer_sha256']==data.OUTER
        and value['packet_checks']==28 and value['financial_sessions_advanced']==0 and value['original_parent_unchanged'] is True,
        'P03_14_FINANCE_ONLY_AFTER_REAL_HOSTED28_PACKET_PREFLIGHT')
    raw=(root/api_module.QUALIFICATION).read_bytes();need(sha(raw)==value['qualification_sha256'] and json.loads(raw)['packet_checks']==28,'P03_14_EXACT_ACTUAL_ORIGINAL28_PACKET_QUALIFICATION')
@contextmanager
def entry_context(module,spec,request):
    from full_system_core import hosted
    hosted()
    if not selected(spec):yield;return
    if request.get('execution_mode')!=MODE:yield;return
    need(request_selected(spec,request),'P03_14_EXPLICIT_NEW_FINANCIAL_PROFILE_REQUIRED')
    package=lifecycle.namespace();context=[None];old_run,old_review,old_overlay=lifecycle.uncertainty.run,lifecycle.uncertainty.review,module.factual_overlay_needed
    old_factory=binding.certificate_class;old_bound=package['bound_runtime']
    def bound_runtime(name,seed):
        def tracked(where,current,target):
            result=seed(where,current,target);seed_contract(result[1],current,target);observers(where,current,33);need(context[0] is None,'P03_14_ONE_REAL_TYPED70_SEED_CALL');context[0]=(current,target,result[1]);return result
        base=old_bound(name,tracked if name=='run' else seed)
        return FunctionType(base.__code__,dict(base.__globals__,bound_body=bound_body),base.__name__,base.__defaults__)
    package['bound_runtime']=bound_runtime
    def certificate_class(event,source,codec,native,*,inherited_root):
        need(context[0] is not None,'P03_14_CONSTRUCTOR_ONLY_AFTER_WHOLE_REAL70_SEED')
        current,target,rows=context[0];constructor_seed(rows,event,current,target)
        Original=old_factory(event,source,codec,native,inherited_root=inherited_root)
        fn=FunctionType(reuse.bind_constructor.__code__,dict(reuse.bind_constructor.__globals__,constructor_seed=constructor_seed),reuse.bind_constructor.__name__,reuse.bind_constructor.__defaults__)
        return fn(Original,event,current,target)
    def run(*args,**kwargs):require_preflight(args[1],kwargs['spec']);return package['run'](*args,**kwargs)
    lifecycle.uncertainty.run=lambda *a,**k:run(*a,**k) if selected(k.get('spec')) else old_run(*a,**k)
    lifecycle.uncertainty.review=lambda *a,**k:package['review'](*a,**k) if selected(k.get('spec')) else old_review(*a,**k)
    module.factual_overlay_needed=lambda target:True if selected(target) else old_overlay(target)
    binding.certificate_class=certificate_class
    try:yield
    finally:lifecycle.uncertainty.run,lifecycle.uncertainty.review,module.factual_overlay_needed,binding.certificate_class=old_run,old_review,old_overlay,old_factory
