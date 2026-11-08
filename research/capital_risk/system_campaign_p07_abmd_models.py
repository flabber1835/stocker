"""Full23/24 P07 input visitor; no checkpoint projection or substituted hash."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_ordinary_augmentation_data as legacy
from system_campaign_bounded_sensor_input import SCHEMA,parse,need,sha,digest

HERE=Path(__file__).parent
PLAN='P07-abmd-full24-source-plan.json'
PLAN_SHA='1c7b3e4c69282a5eec437372e4bd2aa944d47b95cbf11ad5946da6cda4280c2b'

def plan():
    raw=(HERE/PLAN).read_bytes();need(sha(raw)==PLAN_SHA,'P07_ABMD_EXACT_CLOSED_SOURCE_PLAN_BYTES');value=json.loads(raw)
    need(value['schema']=='research.p07-abmd-full24-retained-source-plan/1'
         and value['financial_authority'] is value['input_adopted'] is False
         and len(value['parent_descriptors'])==23 and value['committed_proof_rows']==784
         and value['root_admission_sha256']=='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d',
         'P07_ABMD_EXACT_INITIAL_PARENT_PLAN')
    for name,pin in value['source_files'].items():
        need(sha((legacy.HERE/name).read_bytes())==pin,'P07_ABMD_ENTIRE_LEGACY_INTERPRETER_SOURCE:'+name)
    return value

def bound(fn,**bindings):
    need(fn.__closure__ is None,'P07_ABMD_NO_HIDDEN_METADATA_READER_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**bindings),fn.__name__,fn.__defaults__)
    result.__kwdefaults__=fn.__kwdefaults__
    need(result.__code__ is fn.__code__,'P07_ABMD_WHOLE_ORIGINAL_METADATA_READER_CODE')
    return result

def typed_descriptor(root,cp,catalog,evidence,*,input_hash,root_metadata):
    p=plan();prefix=p['parent_descriptors']
    need(catalog['parent_descriptors']==prefix and catalog['parent_outer_sha256']==p['parent_outer_sha256']
         and catalog['parent_cursor']==p['parent_cursor'] and catalog['parent_inner_sha256']==p['parent_inner_sha256']
         and catalog['parent_completed']==p['parent_completed'] and root_metadata['repairs']==prefix,
         'P07_ABMD_EXACT_COMPLETE_SOURCE_BOUND_PARENT')
    need(cp['base']==root_metadata['base'] and cp['repairs'][:23]==prefix and len(cp['repairs']) in (23,24)
         and cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']),
         'P07_ABMD_FULL_CURRENT_INPUT_IDENTITY')
    if len(cp['repairs'])==23:
        need((cp['sha256'],cp['source_cursor'],cp['completed'])==
             (p['parent_outer_sha256'],p['parent_cursor'],p['parent_completed']),
             'P07_ABMD_UNADOPTED_EXACT_OWN1238_PARENT')
        return None
    d=cp['repairs'][23]
    need(d['filename']==d['sha256']+'.json' and Path(d['filename']).name==d['filename']
         and d['resume_session']==p['parent_cursor'] and d['predecessor_checkpoint_sha256']==p['parent_inner_sha256'],
         'P07_ABMD_ONE_EXACT_SAFE_NEW_DESCRIPTOR')
    path=Path(root)/'book/repairs'/d['filename'];raw=path.read_bytes()
    need(sha(raw)==d['sha256'],'P07_ABMD_ACTUAL_TYPED_INPUT_BYTES')
    obj=parse(path,resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'],
              expected_event=catalog['event'],expected_evidence=evidence)
    need(obj.sha256==d['sha256'] and obj.event.model_dump()==catalog['event']
         and [v.model_dump() for v in obj.source_evidence]==evidence,
         'P07_ABMD_WHOLE_EXACT_INDEPENDENT_TYPED_PARSE')
    return deepcopy(d)

def receipt_input_hashes(value,cp,input_hash):
    return (value['adopted_descriptors']==cp['repairs'][:23]
        and value['adopted_input_sha256']==input_hash(cp['base'],value['adopted_descriptors'])
        and cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']))

def replace(tree,expression,replacement,label):
    hits=0
    class Adapter(ast.NodeTransformer):
        def visit(self,node):
            nonlocal hits
            if isinstance(node,(ast.Compare,ast.Subscript)) and ast.unparse(node)==expression:
                hits+=1;return ast.copy_location(ast.parse(replacement,mode='eval').body,node)
            return super().visit(node)
    result=Adapter().visit(tree);need(hits==1,label);return result

def receipt_tree(raw):
    fn=legacy.original.function(raw,'validated_receipt')
    fn=replace(fn,"value['adopted_descriptors'] == cp['repairs']","value['adopted_descriptors'] == cp['repairs'][:23]",
               'P07_ABMD_ONE_ORIGINAL_RECEIPT_BOUNDARY_SITE')
    fn=replace(fn,"cp['run']['input_sha256'] == value['adopted_input_sha256'] == input_hash(cp['base'], cp['repairs'])",
               'receipt_input_hashes(value,cp,input_hash)','P07_ABMD_ONE_ORIGINAL_RECEIPT_HASH_SITE')
    fn=replace(fn,'values[-1]','values[22]','P07_ABMD_ONE_ORIGINAL_ORDINARY_DESCRIPTOR_SITE')
    return ast.fix_missing_locations(fn)

def branch_tree(raw):
    fn=legacy.original.function(raw,'validate_input')
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    site,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='schema']
    skip=ast.parse("if schema==BOUNDED_SCHEMA:\n need(validated_bounded_descriptor is not None and descriptor==validated_bounded_descriptor,'P07_ABMD_ONLY_INDEPENDENTLY_PARSED_BOUNDED_INPUT')\n continue").body[0]
    loop.body.insert(site+1,skip)
    return ast.fix_missing_locations(fn)

def model_tree(raw):
    fn=legacy.model_tree(raw)
    compares=[n for n in ast.walk(fn) if isinstance(n,ast.Compare)
              and ast.unparse(n)=="doc['schema'] in ('terminal-repair/1', *MODELS)"]
    need(len(compares)==1,'P07_ABMD_ONE_LEGACY_SCHEMA_VISITOR_SITE')
    compares[0].comparators[0].elts.append(ast.Name(id='BOUNDED_SCHEMA',ctx=ast.Load()))
    scopes=[n.value for n in ast.walk(fn) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='namespace']
    need(len(scopes)==1 and isinstance(scopes[0],ast.Call),'P07_ABMD_ONE_ORIGINAL_B19_NAMESPACE_SITE')
    scopes[0].keywords.extend([ast.keyword(arg='BOUNDED_SCHEMA',value=ast.Name(id='BOUNDED_SCHEMA',ctx=ast.Load())),
        ast.keyword(arg='validated_bounded_descriptor',value=ast.Name(id='validated_bounded_descriptor',ctx=ast.Load()))])
    return ast.fix_missing_locations(fn)

def receipt_reader():
    old_plan=legacy.catalog()
    descriptors=bound(legacy.original.descriptors,Path=Path)
    proxy=SimpleNamespace(**dict(vars(legacy.original),descriptors=descriptors))
    def old_suffix(actual,p):
        need(actual['repairs'][:22]==p['parent_descriptors'] and len(actual['repairs']) in (23,24)
             and actual['repairs'][:23]==plan()['parent_descriptors'],
             'P07_ABMD_COMPLETE_ORIGINAL23_AND_INDEPENDENT_SUFFIX')
        return actual['repairs'][22:23]
    receipt_scope=dict(vars(legacy),Path=Path,original=proxy,suffix=old_suffix,receipt_input_hashes=receipt_input_hashes)
    exec(compile(ast.Module(body=[receipt_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
                 '<whole-original-ordinary-receipt-full24-current-hash>','exec'),receipt_scope)
    return receipt_scope['validated_receipt']

def read_legacy_receipt(root,cp,*,input_hash):
    return receipt_reader()(root,cp,legacy.catalog(),input_hash=input_hash)

def validate_full(root,cp,catalog,evidence,*,input_hash,root_metadata):
    selected=typed_descriptor(root,cp,catalog,evidence,input_hash=input_hash,root_metadata=root_metadata)
    old_plan=legacy.catalog();raw=Path(legacy.original.__file__).read_bytes()
    need(sha(raw)==old_plan['source_files'][Path(legacy.original.__file__).name],
         'P07_ABMD_ENTIRE_ORIGINAL_TWO_MODEL_VISITOR')
    descriptors=bound(legacy.original.descriptors,Path=Path)
    def validate_tail(where,actual,*,input_hash):
        need(input_hash is not None,'P07_ABMD_ACTUAL_FULL_INPUT_HASH_FUNCTION_REQUIRED')
        return read_legacy_receipt(where,actual,input_hash=input_hash)
    def function(source,name):
        return branch_tree(source) if name=='validate_input' else legacy.original.function(source,name)
    scope=dict(vars(legacy.original),Path=Path,descriptors=descriptors,validate_tail=validate_tail,
        function=function,BOUNDED_SCHEMA=SCHEMA,validated_bounded_descriptor=selected)
    exec(compile(ast.Module(body=[model_tree(raw)],type_ignores=[]),
                 '<whole-two-model-visitor-one-independently-parsed-ABMD-input>','exec'),scope)
    value=json.loads((Path(root)/legacy.original.ORIGIN).read_bytes())
    added=scope['validate_models'](root,cp,legacy.original.phase(root_metadata),origin=value,input_hash=input_hash)
    need(len(added)==1,'P07_ABMD_ORIGINAL_ZOGNIX_MODEL_PRESERVED')
    return dict(legacy_models=added,bounded_descriptor=selected,full_input_count=len(cp['repairs']))

def legacy_validator(catalog,evidence,root_metadata):
    """Legacy reconstruction22 stays metadata-only; current seeds require23/24."""
    def validate(where,actual,p,*,origin=None,require_additional=True,input_hash=None):
        need(input_hash is not None and require_additional is True,'P07_ABMD_FULL_TYPED_VISITOR_REQUIRED')
        if len(actual['repairs'])==22:
            old=legacy.catalog();legacy.parent_scope(actual,old)
            return legacy.validator(old)(where,actual,p,origin=origin,require_additional=True,input_hash=input_hash)
        result=validate_full(where,actual,catalog,evidence,input_hash=input_hash,root_metadata=root_metadata)
        return result['legacy_models']
    return validate
