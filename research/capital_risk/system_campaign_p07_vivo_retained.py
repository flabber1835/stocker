"""Whole mature lifecycle functions with explicit actual805 and full25 bindings."""
import ast,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_financial_additional_sensor_runtime as additional_runtime
import system_campaign_p07_abmd_lifecycle as lifecycle_original
import system_campaign_p07_abmd_legacy as legacy_original
import system_campaign_p07_abmd_models as models_original
import system_campaign_p07_historical_selector_review as historical
import system_campaign_p07_vivo_models as models
import system_campaign_p07_vivo_boundary as boundary
import system_campaign_p07_vivo_certificate as certificate
import system_campaign_p07_vivo_data as data

U_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
LEGACY_SHA='d41fccdc9ecb3dbaa4165329812ea3037b15ea316e073e9c6af50a71a9f4ab7c'
LIFECYCLE_SHA='05a34b6b3d849a81d632fb035675b88ccb8a7ad938ea7066689e6ec60ece5f81'
WITNESS_SHA='177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1'

def actual_event_descriptors(root,descriptors):
    if len(descriptors)==24:
        from system_campaign_financial_partial import root_spec
        data.need(descriptors==root_spec('P07',data.ROOT)['repairs'],'VIVO_PAST_EVENT_EXACT_ACTUAL_ADMITTED24_DESCRIPTOR_LIST')
        return descriptors
    data.need(len(descriptors)==25,'VIVO_EVENT_ARCHIVE_ONLY_ORIGINAL24_OR_GENUINE25')
    member=lambda name:(Path(root)/name).read_bytes()
    neutral=boundary.strict_json(member(boundary.DIRECTORY+'/checkpoint.json.gz'))
    checked=boundary.validate_members(neutral,member,input_hash=lambda b,r:data.digest(dict(base=b,repairs=r)))
    data.need(descriptors==neutral['repairs'],'VIVO_EVENT_ARCHIVE_CURRENT_AXIS_EQUALS_ACTUAL_NEUTRAL25_GZIP')
    return checked['parent']['repairs']

def permissions(root,rows,catalog,*,through,input_descriptors):
    from system_campaign_bounded_sensor_event_review import permissions as original
    return original(root,rows,catalog,through=through,input_descriptors=actual_event_descriptors(root,input_descriptors))

def legacy_tree(raw):
    data.need(data.sha(raw)==LEGACY_SHA,'VIVO_WHOLE_ORIGINAL_GEN2_LEGACY_SOURCE')
    tree=ast.parse(raw)
    for fn in tree.body:
        if not isinstance(fn,ast.FunctionDef):continue
        if fn.name=='suffix':models.replace_count(fn,'(23, 24)','(23, 24, 25)',1,'VIVO_LEGACY_ONE_FULL25_COUNT_SITE')
        if fn.name=='future_tree':
            values=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=="len(cp['repairs'])==24 and entry==cp['repairs'][23]"]
            data.need(len(values)==1,'VIVO_LEGACY_ONE_EXACT_ABMD_COMPOSITION_SITE')
            values[0].value="len(cp['repairs']) in (24,25) and entry==cp['repairs'][23]"
        if fn.name=='added_permissions':
            models.replace_count(fn,"current['repairs']", "actual_event_descriptors(where,current['repairs'])",1,'VIVO_LEGACY_REAL_OLD_EVENT_INPUT_AXIS_BINDING')
    return ast.fix_missing_locations(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]))

def lifecycle_tree(raw):
    data.need(data.sha(raw)==LIFECYCLE_SHA,'VIVO_WHOLE_ORIGINAL_ABMD_LIFECYCLE_SOURCE')
    tree=ast.parse(raw);fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='runtime_api']
    nested,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='preserve']
    imports=[n for n in ast.walk(nested) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_bounded_sensor_event_review']
    data.need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('permissions',None)],
         'VIVO_LIFECYCLE_ONE_PAST_EVENT_PERMISSION_IMPORT')
    block,=[n for n in nested.body if isinstance(n,ast.If)]
    block.body.remove(imports[0])
    return ast.fix_missing_locations(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]))

def lifecycle():
    model=models.models();origin=models.origin()
    legacy_scope=dict(vars(legacy_original),models=model,origin=origin,actual_event_descriptors=actual_event_descriptors)
    exec(compile(legacy_tree(Path(legacy_original.__file__).read_bytes()),'<whole-gen2-legacy-full25-and-authentic-past-event-axis>','exec'),legacy_scope)
    original_build=legacy_scope['build']
    def build(*a,**k):
        value=original_build(*a,**k);namespace=value.run.__globals__
        reviewed=historical.bind_review_lambda(value.review_ordinary)
        namespace['review_ordinary']=reviewed;value.review_ordinary=reviewed
        return value
    legacy_scope['build']=build
    legacy=SimpleNamespace(**legacy_scope)
    scope=dict(vars(lifecycle_original),models=model,origin=origin,legacy=legacy,permissions=permissions)
    exec(compile(lifecycle_tree(Path(lifecycle_original.__file__).read_bytes()),'<whole-ABMD-lifecycle-full25-real-past-event-descriptors>','exec'),scope)
    return SimpleNamespace(**scope)

def seed_tree(raw):
    data.need(data.sha(raw)==U_SHA,'VIVO_ENTIRE_ORIGINAL_UNCERTAINTY_SEED_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed']
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
    data.need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==
         [('validate_input',None),('seed',None),('discrete',None),('digest',None)],'VIVO_ONE_ORIGINAL_SEED_VALIDATOR_IMPORT')
    imports[0].names=imports[0].names[1:]
    return ast.fix_missing_locations(fn)

def seed_reader(parent,spec,*,neutral=None,evidence=None,rows=None):
    from full_system_core import hosted
    hosted()
    data.parent_contract(parent,spec);life=lifecycle();catalog=life.catalog();model=models.models()
    def contract(current,target):
        data.need(target==spec,'VIVO_SEED_READER_ONLY_EXACT_ACTUAL_ADMITTED_ROOT')
        if neutral is None:data.need(current==parent,'VIVO_SEED_READER_ACTUAL_PARENT24_NO_SUBSTITUTE')
        else:
            data.need(current==neutral,'VIVO_SEED_READER_ONLY_ACTUAL_NEUTRAL25')
            boundary.relation(parent,current,spec,lambda n:(Path(evidence)/n).read_bytes(),rows)
        life.check_retained_origin(evidence if neutral is not None else contract.root,current,catalog,spec)
        hashes=json.loads((Path(uncertainty.__file__).parent/uncertainty.INTEGRATION).read_bytes())['canonical_controller_sources']
        data.need(len(hashes)==6 and all(current['base']['sources'].get(n)==h for n,h in hashes.items()),
             'VIVO_SEED_ALL_SIX_IMMUTABLE_CONTROLLER_SOURCE_IDENTITIES')
        return hashes
    def validate(where,current):
        from research.pooled_vacancy_funding import backtest
        from system_campaign_abmd_bounded_catalog import evidence as source_evidence
        return model.validate_full(where,current,catalog,source_evidence(catalog),input_hash=backtest.input_hash,root_metadata=life.initial_spec())
    scope=dict(vars(uncertainty),retained_contract=contract,validate_input=validate,
        retained_phase=lambda target:dict(rows=805,new_rows=21,retained_rows=784))
    exec(compile(ast.Module(body=[seed_tree(Path(uncertainty.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-retained-seed-exact805-full24-or-real-neutral25>','exec'),scope)
    whole=scope['retained_seed']
    def read(root,current,target):
        contract.root=Path(root)
        result=whole(Path(root),current,target);plan=data.identity_plan()
        raw=b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in result[1])
        data.need(dict(bytes=len(raw),sha256=data.sha(raw))==plan['committed_prefix'] and len(result[1])==805,
             'VIVO_ALL805_LITERAL_COMMITTED_PROOF_BYTES_NO_REEXECUTION_OR_TAIL_SEED')
        return result
    return read

def growth_tree(raw):
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='growth_scope']
    expected=models_original.plan()['source_files'][Path(additional_runtime.__file__).name]
    data.need(data.sha(raw)==expected,'VIVO_WHOLE_ORIGINAL_MIXED_GROWTH_CONTEXT_SOURCE')
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_uncertainty']
    data.need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('proof_scope',None)],'VIVO_ONE_ORIGINAL_PROOF_CONTEXT_IMPORT')
    fn.body.remove(imports[0]);return ast.fix_missing_locations(fn)

def proof_scope(cp,spec):
    from full_system_core import hosted
    hosted()
    from system_campaign_point_growth import point_growth_scope
    data.need(spec['root_admission_sha256']==data.ROOT and len(cp['repairs']) in (24,25)
         and cp['base']==spec['base'] and cp['base']['sources']['sentinel/controller/median5.py']==WITNESS_SHA,
         'VIVO_ONLY_GENUINE805_FROZEN_PHYSICAL_POINT_WITNESS_SOURCE')
    return point_growth_scope(Path('/variant/sentinel/controller/median5.py').read_bytes(),WITNESS_SHA)

def growth_scope(namespace):
    scope=dict(namespace,proof_scope=proof_scope)
    exec(compile(ast.Module(body=[growth_tree(Path(additional_runtime.__file__).read_bytes())],type_ignores=[]),
        '<whole-mixed-point-interval-growth-with-frozen-physical-witness>','exec'),scope)
    return scope['growth_scope']

def runtime_api(root,cp,spec,parent,seed):
    from full_system_core import hosted
    hosted()
    life=lifecycle();value=life.catalog();result=life.runtime_api(root,cp,spec,value)
    namespace=result.run.__globals__;namespace['retained_seed']=lambda where,current,target,p:seed(where,current,target)
    namespace['growth_scope']=growth_scope(namespace)
    def joint(mixed):
        from research.pooled_vacancy_funding import backtest
        codec=getattr(backtest.load_repair,'__self__',None)
        data.need(codec is not None and codec.event==value['event'] and codec.objects,
             'VIVO_ACTUAL_OUTER_ABMD_CODEC_NO_B19_SUBSTITUTION')
        return certificate.certificate_class(value['event'],value['market_source'],codec,codec.native,mixed=mixed,
            inherited_root=life.models.legacy.HERE,retained_root=root,current_checkpoint=parent,admitted_spec=spec,catalog=value)
    namespace['joint_certificate']=joint
    return SimpleNamespace(**namespace)

def source_names():return (Path(__file__).name,*certificate.source_names())
