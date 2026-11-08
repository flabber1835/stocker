"""Finite exact qualification reuse and consumed-event retained constructor binding."""
import ast,gzip,inspect,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_p03_thor_runtime as thor
import system_campaign_bounded_sensor_binding as binding

HERE=Path(__file__).parent
FIELD='selected_p03_thor_qualification_reuse'
FACT='P03-FIN337-exact-qualification-reuse-fact-v1.json'
FACT_SHA='f2d3a1f3121d9d33e03db90ae9f5487a2179ff4d0b25663f980e444ee5b218c8'
DATA='P03-FIN337-qualification-collision-DATA.json'
DATA_SHA='6740c0a3afed021d7137bd501cd4fdac98171dfe50569bbf833c131f7b63422c'
AUDIT='P03-FIN337-downstream-writer-audit.json'
AUDIT_SHA='a6ecce786ca4e8a8475dfd6c448096d362ac12120aee93b921c952f376660e69'
QUALIFICATION='P03-THOR-qualification-reuse-preparation.json'
THOR_SHA='a06bafcd0999f918df7369f4f73526042a22ae5b917be9f30da90c414f9449b7'
BINDING_SHA='a9fcbe1d1c36069036dbddc1982f19c4092f32bc6007534cf4760da527af350d'
RECEIPT='p03-thor-ordinary17-qualification-reuse.json'
need,sha,encoded=thor.data.need,thor.data.sha,thor.data.encoded

def sources():
    return (Path(__file__).name,FACT,DATA,AUDIT,QUALIFICATION,*thor.source_names())

def source_names():return sources()

def facts():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'THOR_REUSE_EXACT_ACTUAL_FIN337_FACT_BYTES')
    need(sha((HERE/DATA).read_bytes())==DATA_SHA,'THOR_REUSE_COMPLETE_AUTHENTICATED_FIN337_DATA')
    need(sha((HERE/AUDIT).read_bytes())==AUDIT_SHA,'THOR_REUSE_COMPLETE_DOWNSTREAM_WRITER_AND_CONSTRUCTOR_AUDIT')
    need(sha(Path(thor.__file__).read_bytes())==THOR_SHA and sha(Path(thor.typed.__file__).read_bytes())==thor.TYPED_SHA
        and sha(Path(thor.uncertainty.__file__).read_bytes())==thor.U_SHA
        and sha(Path(binding.__file__).read_bytes())==BINDING_SHA,'THOR_REUSE_ALL_WHOLE_FROZEN_THOR_TYPED_U_AND_BINDING_BYTES')
    return json.loads(raw)

def declaration(spec):
    old=thor.declaration(spec);fact=facts()
    return dict(schema='research.P03-THOR-exact-qualified-proof-reuse-declaration/1',arm='P03',
        root_admission_sha256=thor.data.ROOT,original_ordinary17_declaration=old,
        actual_known_neutral17_outer_sha256=fact['actual_neutral17_outer_sha256'],qualified_file=fact['qualified_file'],
        exact_admitted_prefix=fact['exact_admitted_prefix'],entire_retained_proof=fact['entire_retained_proof'],
        exact_duplicate_DATA_only=True,original_exclusive_writer_for_missing_file=True,
        whole_retained_seed_and_full17_boundary_required=True,consumed_DOVA_constructor_only_exact49_seed=True,
        canonical_financial_source_changed=False,future17_root_restart_selected=False)

def selected(spec,request):
    declared=request.get(FIELD,{})
    if not declared or not thor.selected(spec):return False
    need(thor.request_selected(spec,request) and declared=={'P03':declaration(spec)},'THOR_REUSE_SEPARATE_EXACT_INITIAL503_REQUEST_REQUIRED')
    return True

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original();need(FIELD not in result,'THOR_REUSE_NO_DECLARATION_REPLACEMENT');result[FIELD]={}
    if execution_mode==thor.MODE and 'P03' in selected_arms:
        spec=root_lookup('P03')
        if thor.selected(spec):result[FIELD]['P03']=declaration(spec)
    for name in sources():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,'THOR_REUSE_NO_FROZEN_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result

def seed_bytes(rows):
    return b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in rows)

def seed_contract(rows,current,spec):
    fact=facts();thor.declaration(spec);raw=seed_bytes(rows);pin=fact['exact_admitted_prefix']
    need(len(rows)==49 and dict(rows=len(rows),bytes=len(raw),sha256=sha(raw))==pin
        and rows[-1]['session']==current['source_cursor']=='2019-12-31'
        and rows[-1]['next_state_sha256']==current['run']['state_sha256']
        and current['sha256']==fact['actual_neutral17_outer_sha256'] and len(current['repairs'])==17
        and current['sha256']==thor.data.digest({k:v for k,v in current.items() if k!='sha256'})
        and current['run']['checkpoint_sha256']==thor.data.digest({k:v for k,v in current['run'].items() if k!='checkpoint_sha256'})
        and current['run']['state_sha256']==thor.data.digest(current['run']['state'])
        and current['completed']==503 and current['repairs'][:16]==spec['repairs'] and current['base']==spec['base']
        and current['run']['input_sha256']==thor.data.digest(dict(base=current['base'],repairs=current['repairs'])),
        'THOR_REUSE_ONLY_REAL_NEUTRAL17_AND_BYTE_EXACT49_ADMITTED_SEED')
    return pin

def qualification_contract(out,current,spec,old,rows,hashes,qualified):
    fact=facts();out,old=Path(out),Path(old);pin=seed_contract(rows,current,spec)
    need(dict(bytes=len(qualified),sha256=sha(qualified))==fact['qualified_file']
        and (old/'branch-controller-qualification.json').read_bytes()==qualified,
        'THOR_REUSE_EXACT_ORIGINAL_QUALIFICATION_BYTES_NEVER_REPLACED')
    value=json.loads(qualified)
    need(hashes==fact['exact_controller_sources']==value['exact_controller_sources']
        and all(current['base']['sources'][n]==h for n,h in hashes.items())
        and value['passed'] is value['actual_divergent_decisions_refused'] is value['ambiguous_comparisons_exhaustively_partitioned']
            is value['all_possible_counters_retained_and_later_merged'] is True
        and type(value['historical_financial_sessions_advanced']) is int and value['historical_financial_sessions_advanced']==0,
        'THOR_REUSE_ALL_SIX_ORIGINAL_CONTROLLER_AND_FULL_QUALIFICATION_GUARDS')
    parent_raw=(out/thor.SELECTED).read_bytes()
    need(dict(bytes=len(parent_raw),sha256=sha(parent_raw))==spec['selected_file']
        and (old/spec['selected_checkpoint']).read_bytes()==parent_raw,'THOR_REUSE_REAL_SELECTED16_ARCHIVE_STILL_EXACT')
    parent=thor.strict_json(parent_raw)
    corr=gzip.decompress((out/(thor.api_module.DIRECTORY+'-correlation-inputs.jsonl.gz')).read_bytes()).splitlines(keepends=True)
    boundary=thor.boundary_relation(parent,current,spec,lambda n:(out/n).read_bytes(),corr)
    need(thor.strict_json((out/'book/checkpoint.json.gz').read_bytes())==current,'THOR_REUSE_ONLY_REAL_PRE_FINANCIAL_CURRENT17_BOOK')
    raw=(out/thor.RAW_PROOF).read_bytes();lines=raw.splitlines(keepends=True)
    need(dict(rows=len(lines),bytes=len(raw),sha256=sha(raw))==fact['entire_retained_proof']
        and (old/'uncertainty-certificate.jsonl').read_bytes()==raw and b''.join(lines[:49])==seed_bytes(rows)
        and all(json.loads(v)['session']>parent['source_cursor'] for v in lines[49:]),
        'THOR_REUSE_ALL63_RAW_PROOF_BYTES_KEEP14_TAILS_OUT_OF49_SEED')
    return dict(schema='research.P03-ordinary17-exact-qualified-proof-reuse/1',passed=True,
        root_admission_sha256=thor.data.ROOT,parent16_outer_sha256=parent['sha256'],actual_neutral17_outer_sha256=current['sha256'],
        qualified_file=fact['qualified_file'],exact_admitted_prefix=pin,entire_retained_proof=fact['entire_retained_proof'],
        unadmitted_tail_rows_seeded=0,original_full_boundary_revalidated=True,original_controller_sources=hashes,
        financial_state_changed=False,financial_sessions_advanced=0)

def qualification_present(out,current,spec,old,rows,hashes,qualified):
    qualification_contract(out,current,spec,old,rows,hashes,qualified)
    path=Path(out)/'branch-controller-qualification.json'
    if not path.exists():return False
    need(path.is_file() and not path.is_symlink() and path.read_bytes()==qualified,'THOR_REUSE_EXISTING_OUTPUT_ONLY_IDENTICAL_QUALIFIED_DATA')
    return True

def qualification_postcondition(out,current,spec,old,rows,hashes,qualified,present):
    receipt=qualification_contract(out,current,spec,old,rows,hashes,qualified)
    need(type(present) is bool and (Path(out)/'branch-controller-qualification.json').read_bytes()==qualified,
        'THOR_REUSE_ORIGINAL_CREATE_OR_REUSE_WHOLE_BYTE_POSTCONDITION')
    receipt['mode']='EXACT_EXISTING_QUALIFICATION_REUSED' if present else 'ORIGINAL_EXCLUSIVE_WRITER_CREATED'
    thor.exact(Path(out)/RECEIPT,encoded(receipt))

def run_tree():
    facts();fn=deepcopy(thor.typed.body_tree('run_retained'));old=deepcopy(fn)
    sites=[(i,n) for i,n in enumerate(fn.body) if isinstance(n,ast.With) and ast.unparse(n.items[0].context_expr)=="(out / 'branch-controller-qualification.json').open('xb')"]
    need(len(sites)==1,'THOR_REUSE_ONE_EXACT_ORIGINAL_EXCLUSIVE_DATA_WRITER')
    i,statement=sites[0]
    need(ast.unparse(statement.body[0])=='stream.write(qualified)' and len(statement.body)==1,'THOR_REUSE_WHOLE_ORIGINAL_QUALIFICATION_STREAM_WRITE')
    additions=ast.parse("""qualification_was_present = qualification_present(out, cp, spec, old, rows, hashes, qualified)
if not qualification_was_present:
    pass
qualification_postcondition(out, cp, spec, old, rows, hashes, qualified, qualification_was_present)
""").body
    additions[1].body=[statement];fn.body[i:i+1]=additions
    undo=deepcopy(fn);undo.body[i:i+3]=[deepcopy(statement)]
    need(ast.dump(undo,include_attributes=False)==ast.dump(old,include_attributes=False),'THOR_REUSE_WHOLE_ORIGINAL_TYPED_BODY_THREE_STATEMENT_UNDO')
    return ast.fix_missing_locations(fn)

def bound_body(name,bindings):
    original=thor.typed.bound_body(name,bindings)
    if name!='run_retained':return original
    namespace=dict(original.__globals__,qualification_present=qualification_present,qualification_postcondition=qualification_postcondition)
    exec(compile(ast.Module(body=[run_tree()],type_ignores=[]),'<whole-original-retained-body-one-exact-DATA-reuse-dispatch>','exec'),namespace)
    return namespace['run_retained']

def constructor_seed(seed,event,current,spec):
    pin=seed_contract(seed,current,spec)
    need(event==thor.typed.catalog()['event'] and event['native_session']<=current['source_cursor']
        and seed[-1]['session']>=event['native_session'],'THOR_REUSE_ONLY_ALREADY_CONSUMED_ORIGINAL_DOVA_EVENT_WITH49_SEED')
    return pin

def bind_constructor(Original,event,current,spec):
    constructor=Original.__init__
    need(constructor.__closure__ is not None,'THOR_REUSE_KEEP_ENTIRE_ORIGINAL_BOUNDED_CONSTRUCTOR_CLOSURE')
    base_need=constructor.__globals__['need']
    def constructor_need(value,label):
        if label!='PRIOR_COMMITTED_B19_SEED':return base_need(value,label)
        frame=inspect.currentframe().f_back;self=frame.f_locals.get('self')
        need(frame.f_code is constructor.__code__ and isinstance(self,Original),'THOR_REUSE_ONLY_REAL_ORIGINAL_CONSTRUCTOR_CALLER_AND_SELF')
        constructor_seed(self.seed,event,current,spec)
        return base_need(True,label)
    bound=FunctionType(constructor.__code__,dict(constructor.__globals__,need=constructor_need),constructor.__name__,constructor.__defaults__,constructor.__closure__)
    bound.__qualname__=constructor.__qualname__
    bound.__kwdefaults__=deepcopy(constructor.__kwdefaults__)
    need(bound.__code__ is constructor.__code__ and bound.__closure__ is constructor.__closure__,'THOR_REUSE_WHOLE_ORIGINAL_CONSTRUCTOR_CODE_AND_CLOSURE')
    Original.__init__=bound
    return Original

def review_receipt(evidence,spec):
    fact=facts();evidence=Path(evidence);receipt=json.loads((evidence/RECEIPT).read_bytes())
    need(receipt['schema']=='research.P03-ordinary17-exact-qualified-proof-reuse/1' and receipt['passed'] is True
        and receipt['root_admission_sha256']==thor.data.ROOT and receipt['actual_neutral17_outer_sha256']==fact['actual_neutral17_outer_sha256']
        and receipt['parent16_outer_sha256']==fact['selected_parent_outer_sha256']
        and receipt['qualified_file']==fact['qualified_file'] and receipt['exact_admitted_prefix']==fact['exact_admitted_prefix']
        and receipt['entire_retained_proof']==fact['entire_retained_proof'] and receipt['unadmitted_tail_rows_seeded']==0
        and type(receipt['unadmitted_tail_rows_seeded']) is type(receipt['financial_sessions_advanced']) is int
        and receipt['original_controller_sources']==fact['exact_controller_sources'] and receipt['original_full_boundary_revalidated'] is True
        and receipt['mode'] in ('EXACT_EXISTING_QUALIFICATION_REUSED','ORIGINAL_EXCLUSIVE_WRITER_CREATED')
        and receipt['financial_sessions_advanced']==0 and receipt['financial_state_changed'] is False,
        'THOR_REUSE_INDEPENDENT_EXACT_INITIAL_REUSE_RECEIPT')
    qualified=(evidence/'branch-controller-qualification.json').read_bytes()
    raw=(evidence/thor.RAW_PROOF).read_bytes();lines=raw.splitlines(keepends=True)
    actual=(evidence/'uncertainty-certificate.jsonl').read_bytes().splitlines(keepends=True)
    need(dict(bytes=len(qualified),sha256=sha(qualified))==fact['qualified_file']
        and dict(rows=len(lines),bytes=len(raw),sha256=sha(raw))==fact['entire_retained_proof']
        and len(actual)>=49 and b''.join(actual[:49])==b''.join(lines[:49])
        and dict(rows=49,bytes=len(b''.join(actual[:49])),sha256=sha(b''.join(actual[:49])))==fact['exact_admitted_prefix'],
        'THOR_REUSE_REAL_CERTIFICATE_EXISTS_AND_ALL49_PRIOR_PREFIX_BYTES_PRESERVED')
    thor.declaration(spec)

@contextmanager
def entry_context(module,spec,request):
    from full_system_core import hosted
    hosted()
    if request.get('execution_mode')!=thor.MODE or not thor.selected(spec):
        with thor.entry_context(module,spec,request):yield
        return
    need(selected(spec,request),'THOR_REUSE_EXPLICIT_CORRECTIVE_PHASE_REQUIRED')
    context=[None];old_bound,old_factory,old_review=thor.bound_runtime,binding.certificate_class,thor.review
    def bound_runtime(name,seed):
        base=old_bound(name,seed)
        if name!='run':return base
        def tracked(where,current,target):
            result=seed(where,current,target);seed_contract(result[1],current,target)
            need(context[0] is None,'THOR_REUSE_ONE_ACTUAL_TYPED_RETAINED_SEED_CALL')
            context[0]=(current,target,result[1]);return result
        bound=FunctionType(base.__code__,dict(base.__globals__,seed=tracked,bound_body=bound_body),base.__name__,base.__defaults__)
        bound.__kwdefaults__=deepcopy(base.__kwdefaults__)
        need(bound.__code__ is base.__code__,'THOR_REUSE_WHOLE_FROZEN_TYPED_RUN_CODE_OBJECT')
        return bound
    def certificate_class(event,source,codec,native,*,inherited_root):
        need(context[0] is not None,'THOR_REUSE_CONSTRUCTOR_ONLY_AFTER_WHOLE_REAL_RETAINED_SEED')
        current,target,seed=context[0];constructor_seed(seed,event,current,target)
        Original=old_factory(event,source,codec,native,inherited_root=inherited_root)
        return bind_constructor(Original,event,current,target)
    def review(parent,evidence,out,*,spec,old):
        review_receipt(evidence,spec)
        return old_review(parent,evidence,out,spec=spec,old=old)
    with thor.entry_context(module,spec,request):
        thor.bound_runtime,binding.certificate_class,thor.review=bound_runtime,certificate_class,review
        try:yield
        finally:thor.bound_runtime,binding.certificate_class,thor.review=old_bound,old_factory,old_review
