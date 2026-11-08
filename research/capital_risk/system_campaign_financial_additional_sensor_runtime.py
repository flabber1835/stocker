"""Hosted-only ordered additional-sensor adoption and original B19 suffix proof."""
import ast
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import system_campaign_financial_additional_sensor as data

HERE=Path(__file__).parent
FROZEN_FUTURE='system_campaign_financial_additional_sensor_ordinary_v1.py'
ORIGIN_DIR='additional-sensor-origin'

def hosted():
    from full_system_core import hosted as check
    check()

def save(path,value):
    raw=data.encoded(value);path=Path(path)
    if path.exists():data.need(path.read_bytes()==raw,'ADDITIONAL_EXISTING_EVIDENCE_BYTES')
    else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

def read_cp(path):
    hosted()
    from research.pooled_vacancy_funding import journal
    return journal.read_checkpoint(path)


def frozen_metadata(raw,namespace):
    """Extract declarative selector data only; never run external catalog initialization."""
    tree=ast.parse(raw)
    names={'PLANS','CASH_PHASES','COMBINED_PHASES','SINGLE_PHASES','FOLLOWING_PHASES','FUTURE_LITERAL_PHASES',
        'RETAINED_OWN_CASH_PHASES','OWN_CASH_PHASES','ORIGINAL_ORDINARY_SOURCES','ORIGINAL_ORDINARY_PHASES',
        'ORIGINAL_DELIVERY_SOURCES','ORIGINAL_DELIVERY_PHASES','SUPPLEMENTAL_PHASES',
        'SUPPLEMENTAL_SAME_DAY_PHASES','SUPPLEMENTAL_SHARED_VALIDATOR_PHASES',
        'ROOT_BOUND_ALIAS_SOURCE_PHASES','ADDITIONAL_SENSOR_ALIAS_PHASES'}
    literals=set()
    for node in tree.body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
        try:value=ast.literal_eval(node.value)
        except (ValueError,TypeError,SyntaxError):continue
        if value is None or type(value) in (str,int,float,bool):
            namespace[node.targets[0].id]=value;literals.add(node.targets[0].id)
    for name in names:namespace.pop(name,None)
    namespace.update(dict=dict,tuple=tuple,set=set,frozenset=frozenset,deepcopy=deepcopy)
    selected=[];declared=set();pure={'dict','tuple','set','frozenset','deepcopy'}
    allowed=(ast.Assign,ast.Name,ast.Subscript,ast.Constant,ast.Dict,ast.List,ast.Tuple,ast.Set,
        ast.Load,ast.Store,ast.Call,ast.keyword,ast.BinOp,ast.BitOr,ast.Add,ast.DictComp,ast.ListComp,
        ast.SetComp,ast.comprehension,ast.Starred)
    def root(node):
        while isinstance(node,(ast.Subscript,ast.Attribute)):node=node.value
        return node.id if isinstance(node,ast.Name) else None
    for node in tree.body:
        targets=node.targets if isinstance(node,ast.Assign) else []
        if not any(root(t) in names for t in targets):
            if not isinstance(node,(ast.FunctionDef,ast.ClassDef,ast.Import,ast.ImportFrom)):
                touched=any(isinstance(v,ast.Name) and v.id in names for v in ast.walk(node))
                data.need(not touched,'ADDITIONAL_NO_UNDECLARED_ROUTING_METADATA_SITE')
            continue
        data.need(len(targets)==1 and root(targets[0]) in names,'ADDITIONAL_ONE_DECLARATIVE_ROUTING_TARGET')
        bound={n.target.id for n in ast.walk(node) if isinstance(n,ast.comprehension) and isinstance(n.target,ast.Name)}
        for item in ast.walk(node):
            data.need(isinstance(item,allowed),'ADDITIONAL_ONLY_DECLARATIVE_ROUTING_AST')
            if isinstance(item,ast.Call):
                data.need(isinstance(item.func,ast.Name) and item.func.id in pure,
                          'ADDITIONAL_NO_NONDECLARATIVE_METADATA_CALL')
            if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Load):
                data.need(item.id in literals|declared|pure|bound,
                          'ADDITIONAL_NO_CURRENT_REGISTRY_GLOBAL_FALLBACK')
        selected.append(deepcopy(node));declared.add(root(targets[0]))
    data.need(names<=declared,'ADDITIONAL_COMPLETE_FROZEN_SELECTOR_METADATA')
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),
        '<source-qualified-declarative-ordinary-generation>','exec'),namespace)
    return namespace

def ordinary_api(p):
    """Frozen function namespaces; no stale historical module-level catalog import."""
    import system_campaign_financial_future as current
    raw=(HERE/FROZEN_FUTURE).read_bytes()
    data.need(data.sha(raw)==p['ordinary_producer_sha256'],'ADDITIONAL_IMMUTABLE_ORDINARY_PRODUCER')
    tree=ast.parse(raw)
    namespace=dict(vars(current),__file__=str(HERE/FROZEN_FUTURE))
    frozen_metadata(raw,namespace)
    data.need(set(p['ordinary_metadata'])=={'CASH_PHASES','SUPPLEMENTAL_PHASES'},
              'ADDITIONAL_EXACT_ORIGINAL_ORDINARY_METADATA_REGISTRIES')
    for name,entries in p['ordinary_metadata'].items():
        registry=deepcopy(namespace[name]);declared=deepcopy(registry.get((p['arm'],p['origin_cursor'])))
        if name=='CASH_PHASES':
            data.need(len(entries)==2,'ADDITIONAL_EXACT_PRIMARY_METADATA_SHAPE')
            registry[p['arm'],p['origin_cursor']]=(entries[0],tuple(entries[1]))
        else:
            data.need(all(len(v)==7 for v in entries),'ADDITIONAL_EXACT_SUPPLEMENT_METADATA_SHAPE')
            registry[p['arm'],p['origin_cursor']]=tuple((*v[:6],tuple(v[6])) for v in entries)
        data.need(registry[p['arm'],p['origin_cursor']]==declared,
                  'ADDITIONAL_PHASE_METADATA_MATCHES_ORIGINAL_PRODUCER')
        namespace[name]=registry
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
        '<immutable-additional-ordinary-source-functions>','exec'),namespace)
    # Original ActualEvents is used in the current qualified caller namespace.
    old,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ActualEvents']
    now,=[n for n in ast.parse(Path(current.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='ActualEvents']
    data.need(ast.dump(old,include_attributes=False)==ast.dump(now,include_attributes=False),
              'ADDITIONAL_UNCHANGED_ORDINARY_OBSERVER_CLASS_AST')
    for name in ('actual_terminal_call','actual_cash_phase','actual_stock_phase','cash_postcondition',
                 'unheld_stock_postcondition','require_source_absent','actual_source_phase'):
        original=data.function(raw,name);actual=data.function(Path(current.__file__).read_bytes(),name)
        data.need(ast.dump(original,include_attributes=False)==ast.dump(actual,include_attributes=False),
                  'ADDITIONAL_UNCHANGED_ORIGINAL_OBSERVER_HELPER_AST')
    namespace['ActualEvents']=current.ActualEvents
    return namespace

def origin(root):return json.loads((Path(root)/data.ORIGIN).read_bytes())

def validate_origin(root,cp,p):
    hosted();root=Path(root);value=origin(root)
    prior=(root/ORIGIN_DIR/'entire-prior-certificate.jsonl').read_bytes()
    data.need(len(prior)==p['original_certificate_file_bytes'] and data.sha(prior)==p['original_certificate_file_sha256'],
              'ADDITIONAL_ENTIRE_ORIGINAL_CERTIFICATE_AND_UNCOMMITTED_TAIL_BYTES')
    raw=(root/ORIGIN_DIR/'cp0.json.gz').read_bytes()
    data.need(data.sha(raw)==value['cp0_gzip_sha256']==p['original_checkpoint_file_sha256'] and len(raw)==p['original_checkpoint_file_bytes'],'ADDITIONAL_IMMUTABLE_ORDINARY_ORIGIN_GZIP')
    cp0=read_cp(root/ORIGIN_DIR/'cp0.json.gz')
    data.need(cp['base']==cp0['base'] and cp['source_cursor']>=cp0['source_cursor'] and cp['completed']>=cp0['completed'],
              'ADDITIONAL_FULL_SUCCESSOR_AXIS_AND_ORIGINAL_BASE')
    data.need(cp0['sha256']==p['origin_outer_sha256']==value['ordinary_origin_outer_sha256']
         and cp0['source_cursor']==p['origin_cursor'] and cp0['completed']==p['origin_completed']
         and cp0['repairs']==p['original_descriptors']
         and value['ordinary_producer_sha256']==p['ordinary_producer_sha256']
         and value['source_payload_sha256']==p['source_payload_sha256']
         and value['origin_root_admission_sha256']==p['origin_root_admission_sha256'],
         'ADDITIONAL_IMMUTABLE_CP0_SOURCE_AND_OBSERVER_GENERATION')
    from research.pooled_vacancy_funding import backtest
    data.validate_models(root,cp,p,origin=value,input_hash=backtest.input_hash)
    for name,h in value['input_files'].items():
        data.need(data.sha((root/name).read_bytes())==h,'ADDITIONAL_RETAINED_INPUT_EVIDENCE_BYTES')
    return value,cp0

def ordinary_reconstruction(root,target,p):
    value,cp0=validate_origin(root,read_cp(Path(root)/'book/checkpoint.json.gz'),p)
    target=Path(target);target.mkdir()
    api=ordinary_api(p);path,loaded=api['prepare'](cp0,target,p['arm'])
    for name in (api['OVERLAY'],api['hydration_name'](cp0)):
        data.need((target/name).read_bytes()==(Path(root)/name).read_bytes(),
                  'ADDITIONAL_ORDINARY_RECONSTRUCTED_FROM_IMMUTABLE_CP0')
    data.need(loaded.sha256==value['ordinary_descriptor']['sha256'],
              'ADDITIONAL_RECONSTRUCTED_ORDINARY_DESCRIPTOR')
    return cp0

@contextmanager
def original_chain(root,cp,spec):
    """Original B19 then actual activated APHA, then the separately typed model."""
    hosted()
    from research.pooled_vacancy_funding import backtest,repair
    import system_campaign_financial_partial as partial
    import system_campaign_financial_branches as b
    import system_campaign_financial_projection as projection
    from system_campaign_zogenix_input import InputCodec
    from system_campaign_zogenix_facts import evidence,PRIVATE
    p=data.selected_declaration(root,cp,spec)
    data.need(p is not None,'ADDITIONAL_CHAIN_REQUIRES_EXPLICIT_DECLARATION')
    with ExitStack() as stack:
        codec=stack.enter_context(b.Codec(b.evidence(Path(root))))
        own=stack.enter_context(projection.retained_context(root,cp))
        partial.activate_retained_projection(root,cp,own)
        data.need(projection.branch_loader_owner(backtest.load_repair) is codec,
                  'ADDITIONAL_ACTUAL_ORIGINAL_ACTIVE_BRANCH_OWNER')
        z=None
        if any(doc['schema']==data.SCHEMA for d,doc in data.descriptors(root,cp)):
            value,_=validate_origin(root,cp,p)
            native_dict=json.loads((Path(root)/PRIVATE).read_bytes())['actual_native']
            from research.pooled_input_support import inputs
            from dataclasses import asdict
            native,=[v for v in inputs.load_actions(Path('/frozen/bundle')).terminal.get(p['event']['native_session'],()) if v.security_id==p['event']['security_id']]
            data.need(asdict(native)==native_dict,'ADDITIONAL_ACTUAL_RETAINED_NATIVE_OBJECT')
            z=stack.enter_context(qualified_zcodec(codec,own,evidence(Path(root)),native))
        yield codec,z

@contextmanager
def qualified_zcodec(branch,projection,expected,native):
    hosted()
    from research.pooled_vacancy_funding import backtest,repair
    from system_campaign_financial_projection import OwnProjection,branch_loader_owner
    from system_campaign_zogenix_input import InputCodec
    data.source('system_campaign_zogenix_input.py');data.source('system_campaign_financial_projection.py');data.source('system_campaign_future_amendment.py')
    installed=backtest.load_repair
    data.need(isinstance(projection,OwnProjection) and projection.active
         and getattr(installed,'__self__',None) is projection
         and getattr(installed,'__func__',None) is OwnProjection.load
         and repair.load_repair==installed and branch_loader_owner(installed) is branch,
         'ADDITIONAL_EXACT_INSTALLED_ACTIVE_APHA_B19_LOADER_IDENTITIES')
    with InputCodec(expected,native) as codec:
        data.need(codec.original_load==installed and backtest.load_repair==codec.load
             and repair.load_repair==codec.load,'ADDITIONAL_ORIGINAL_CODEC_CAPTURES_FULL_CHAIN')
        yield codec
    data.need(backtest.load_repair==installed and repair.load_repair==installed,
              'ADDITIONAL_ORIGINAL_CODEC_RESTORES_BOTH_LOADERS')

@contextmanager
def growth_scope(cp,spec):
    hosted()
    import system_campaign_uncertainty_context as base
    import system_campaign_financial_branches as b
    from system_campaign_uncertainty_math import growth as interval
    from system_campaign_point_growth import point_growth
    from system_campaign_financial_uncertainty import proof_scope
    data.source('system_campaign_point_growth.py');data.source('system_campaign_uncertainty_math.py')
    def mixed(values):return data.mixed_growth(values,point=point_growth,interval=interval)
    with proof_scope(cp,spec):
        previous=(base.growth,b.growth)
        base.growth=b.growth=mixed
        try:yield mixed
        finally:base.growth,b.growth=previous

def joint_certificate(mixed):
    hosted()
    import system_campaign_zogenix_sensor as z
    import system_campaign_uncertainty_context as base
    import system_campaign_financial_branches as b
    from system_campaign_zogenix_input import SID
    for n in ('system_campaign_zogenix_sensor.py','system_campaign_uncertainty_context.py',
              'system_campaign_financial_branches.py'):data.source(n)
    material=z.isolated_function(base.return_material,SID=SID,growth=mixed)
    witness=z.isolated_function(base.SensorCertificate.witness,return_material=material)
    class Joint(z.SensorCertificate,b.Certificate):pass
    Joint.witness=witness
    data.need(Joint.__mro__[1:4]==(z.SensorCertificate,b.Certificate,base.SensorCertificate)
         and Joint.recover is z.SensorCertificate.recover and Joint.append is b.Certificate.append
         and witness.__code__ is base.SensorCertificate.witness.__code__
         and material.__code__ is base.return_material.__code__,
         'ADDITIONAL_EXACT_COOPERATIVE_ORIGINAL_METHOD_COMPOSITION')
    return Joint

def pause(cp,out,args,rows,path,earliest,directory):
    import system_campaign_financial_uncertainty as u
    fn=data.legacy_function(u.__file__,'paused_own_adoption','pause')
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    data.need(isinstance(assignment.value,ast.Dict),'ADDITIONAL_ORIGINAL_PAUSE_NAME_WHITELIST')
    assignment.value.keys.append(ast.Constant(data.ADOPTION));assignment.value.values.append(ast.Constant('zogenix-sensor-input.json'))
    namespace=dict(vars(u));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<original-paused-adoption-one-new-typed-filename>','exec'),namespace)
    return namespace['paused_own_adoption'](cp,out,args,rows,path,earliest,directory)

def packet_qualification(out,cp,objects,loaded,codec,request,hashes):
    """Original packet/values/parser gate prefix, then immutable B19 cloud gate."""
    hosted()
    import system_campaign_zogenix_gate as z
    import system_campaign_financial_branches as b
    fn=data.function(data.source('system_campaign_zogenix_gate.py'),'qualify')
    site,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='state']
    fn.body=fn.body[:site]
    namespace=dict(vars(z));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<original-zogenix-packets-values-parser-only>','exec'),namespace)
    namespace['qualify'](out,cp,objects,loaded,codec,request)
    gate=out/'additional-sensor-cloud-qualification';gate.mkdir()
    b.qualify(gate,hashes)
    proof=json.loads((gate/'branch-controller-qualification.json').read_bytes())
    data.need(proof['passed'] is True and proof['historical_financial_sessions_advanced']==0
         and proof['ambiguous_comparisons_exhaustively_partitioned'] is True
         and proof['all_possible_counters_retained_and_later_merged'] is True,
         'ADDITIONAL_ORIGINAL_EXHAUSTIVE_CLOUD_QUALIFICATION')
    return data.sha((gate/'branch-controller-qualification.json').read_bytes())

def preserve(root,cp,out,spec):
    p=data.selected_declaration(root,cp,spec)
    if p is None or not any(doc['schema']==data.SCHEMA for d,doc in data.descriptors(root,cp)):return
    value,_=validate_origin(root,cp,p)
    names={data.ORIGIN,ORIGIN_DIR+'/cp0.json.gz',data.QUALIFICATION,*value['input_files']}
    from system_campaign_financial_uncertainty import ORDINARY_ADOPTION
    for directory in (ORDINARY_ADOPTION,data.ADOPTION):
        names.add(directory+'-correlation-inputs.jsonl.gz')
        for path in (Path(root)/directory).rglob('*'):
            if path.is_file():names.add(path.relative_to(root).as_posix())
    for path in (Path(root)/'additional-sensor-cloud-qualification').rglob('*'):
        if path.is_file():names.add(path.relative_to(root).as_posix())
    for path in (Path(root)/ORIGIN_DIR).rglob('*'):
        if path.is_file():names.add(path.relative_to(root).as_posix())
    if cp['source_cursor']>=p['event']['effective_session']:
        paths=list((Path(root)/'book/pre-event').glob(p['event']['effective_session']+'-*.json.gz'))
        data.need(paths,'ADDITIONAL_RETAINED_COMMITTED_EVENT_ARCHIVE_REQUIRED')
        names.update(path.relative_to(root).as_posix() for path in paths)
    for name in names:
        raw=(Path(root)/name).read_bytes();target=Path(out)/name
        if target.exists():data.need(target.read_bytes()==raw,'ADDITIONAL_RETAINED_ORIGIN_EXACT_BYTES')
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    # Actual future cash observations are committed only after their event.
    for path in Path(root).rglob('actual-future-event-*.json'):
        day=path.name[len('actual-future-event-'):-5]
        if day<=cp['source_cursor']:
            target=Path(out)/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():data.need(target.read_bytes()==path.read_bytes(),'ADDITIONAL_ACTUAL_ORDINARY_PROOF_RETENTION')
            else:target.write_bytes(path.read_bytes())

def run(cp,out,args,rows,observer,execution,spec,old):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    import system_campaign_financial_uncertainty as u
    import system_campaign_financial_projection as projection
    import system_campaign_zogenix_facts as z
    from system_campaign_zogenix_input import parse,NATIVE
    from system_campaign_alder_date_v2 import AlderDateV2
    from system_campaign_p02_retained_run import idempotent_dispatch
    from system_campaign_uncertainty_archive import preserve as preserve_event
    from system_campaign_financial_compound_dispatch import retained_versions,retained_terminal_callers
    p=data.phase(spec)
    data.need(p is not None,'ADDITIONAL_ONLY_QUALIFIED_EXPLICIT_PHASE')
    if p['adoption_mode']=='RETAINED':return run_retained(cp,out,args,rows,observer,execution,spec,old,p)
    data.common_source_binding(cp,p)
    hashes,seed,qualification=u.retained_seed(old,cp,spec)
    data.need(len(seed)==p['retained_rows'],
              'ADDITIONAL_EXACT_ORIGINAL_SEED_COUNT')
    from system_campaign_financial_branches import encoded as proof_encoded
    data.need(data.sha(b''.join(proof_encoded(v)+b'\n' for v in seed))==p['retained_prefix_sha256'],
              'ADDITIONAL_ALL_593_COMMITTED_PROOF_BYTES')
    branch=u.active_codec(backtest,old,cp)
    own=getattr(backtest.load_repair,'__self__',None)
    (out/'branch-controller-qualification.json').write_bytes(qualification);preserve_event(old,out)
    folder=out/ORIGIN_DIR;folder.mkdir()
    shutil.copyfile(old/spec['selected_checkpoint'],folder/'cp0.json.gz')
    shutil.copyfile(old/'uncertainty-certificate.jsonl',folder/'entire-prior-certificate.jsonl')
    api=ordinary_api(p);path,loaded=api['prepare'](cp,out,p['arm'])
    material_name=api['hydration_name'](cp)
    data.need([t['ticker'] for t in json.loads((out/material_name).read_bytes())['terms']]==p['ordinary_expected_tickers'],
              'ADDITIONAL_EXACT_SEVEN_ORDINARY_TERMS')
    cp1=pause(cp,out,args,rows,path,loaded.earliest_affected_session,u.ORDINARY_ADOPTION)
    data.need(api['review_input'](cp,out,p['arm'])==loaded.earliest_affected_session,
              'ADDITIONAL_ORDINARY_REVIEW_BEFORE_SENSOR_ADOPTION')
    native=z.hydrate(out,out);path=z.overlay(cp1,out)
    with qualified_zcodec(branch,own,z.evidence(out),native) as codec:
        loaded=backtest.load_repair(path,resume_session=cp1['source_cursor'],
            predecessor_checkpoint_sha256=cp1['run']['checkpoint_sha256'])
        cp2=pause(cp1,out,args,rows,path,NATIVE,data.ADOPTION)
        data.need(len(cp1['repairs'])==21 and len(cp2['repairs'])==22
             and cp1['repairs'][:20]==cp['repairs'] and cp2['repairs'][:21]==cp1['repairs'],
             'ADDITIONAL_EXACT_TWENTY_TWENTYONE_TWENTYTWO_BOUNDARIES')
        files={api['OVERLAY'],material_name,z.PRIVATE,path.name,'provider-source/SHARADAR_ACTIONS.zip','provider-alias-proof.json'}
        files.update(r['material_file'] for r in p['inherited_ordinary_observers'])
        files.update(r['effective_file'] for r in p['inherited_ordinary_observers'])
        files.update(r['projection']['payload_file'] for r in p['inherited_ordinary_observers'] if r['projection'] is not None)
        value=dict(schema='research.retained-additional-sensor-origin/1',origin_root_admission_sha256=p['origin_root_admission_sha256'],
            ordinary_origin_outer_sha256=cp['sha256'],cp0_gzip_sha256=data.sha((folder/'cp0.json.gz').read_bytes()),
            source_payload_sha256=p['source_payload_sha256'],ordinary_producer_sha256=p['ordinary_producer_sha256'],
            observation_seed_sha256=data.sha(b''.join(rows)),observation_seed_bytes=len(b''.join(rows)),
            ordinary_descriptor=cp1['repairs'][-1],sensor_descriptor=cp2['repairs'][-1],cp1_outer_sha256=cp1['sha256'],
            cp1_inner_sha256=cp1['run']['checkpoint_sha256'],cp2_outer_sha256=cp2['sha256'],
            input_files={name:data.sha((out/name).read_bytes()) for name in sorted(files)})
        save(out/data.ORIGIN,value)
        data.validate_models(out,cp2,p,origin=value,input_hash=backtest.input_hash)
        reconstruction=out/'additional-sensor-input-reconstruction';reconstruction.mkdir()
        z.hydrate(out,reconstruction);reconstructed=z.overlay(cp1,reconstruction)
        data.need(reconstructed.read_bytes()==path.read_bytes(),'ADDITIONAL_INDEPENDENT_ORIGINAL_SENSOR_INPUT_RECONSTRUCTION')
        parse(reconstructed,resume_session=cp1['source_cursor'],predecessor_checkpoint_sha256=cp1['run']['checkpoint_sha256'],
            expected_evidence=z.evidence(reconstruction),native_sha256=codec.native_sha256)
        objects=[backtest.load_repair(out/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp1['repairs']]
        from system_campaign_sprint_facts import PACKET_SOURCE_PATH
        request={'qualified_packet_source_sha256':cp['base']['sources'][PACKET_SOURCE_PATH]}
        cloud_sha=packet_qualification(out,cp1,objects,loaded,codec,request,hashes)
        with ordinary_observers(out,out,p,cp) as bound_observers:
            observer_binding_sha=data.digest(bound_observers)
        receipt=dict(schema='research.retained-additional-sensor-zero-advance/1',passed=True,
            observer_binding_sha256=observer_binding_sha,
            root_admission_sha256=p['root_admission_sha256'],origin_sha256=data.sha((out/data.ORIGIN).read_bytes()),
            parent_outer_sha256=cp['sha256'],cp1_outer_sha256=cp1['sha256'],cp2_outer_sha256=cp2['sha256'],
            original593_prefix_sha256=p['retained_prefix_sha256'],cloud_qualification_sha256=cloud_sha,
            actual_parser_packets_and_two_neutral_adoptions_qualified=True,financial_sessions_advanced=0,
            canonical_financial_source_changed=False)
        save(out/data.QUALIFICATION,receipt)
        verify_qualification(out,cp2,p)
        alder=AlderDateV2(HERE/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/'retained-alder-source.json')
        source=json.loads((old/'hydrated-uncertainty-event.json').read_bytes())
        with growth_scope(cp,spec) as mixed:
            Joint=joint_certificate(mixed)
            certificate=Joint(out,branch,alder.native,hashes,seed=seed,event_source=source,
                zogenix_codec=codec,zogenix_native=native,zogenix_source=json.loads((out/z.PRIVATE).read_bytes()))
            with alder,idempotent_dispatch(alder),certificate,observer,execution:
                with ordinary_observers(out,out,p,cp):
                    code=backtest.main(args)
        actual=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        data.need(actual['base']==cp['base'] and actual['repairs']==cp2['repairs']
             and actual['run']['input_sha256']==cp2['run']['input_sha256'],
             'ADDITIONAL_FINANCE_ONLY_FROM_FULL_SECOND_NEUTRAL_SUCCESSOR')
    return code

def verify_qualification(root,cp,p):
    value,cp0=validate_origin(root,cp,p)
    import system_campaign_financial_uncertainty as u
    api=ordinary_api(p);material=json.loads((Path(root)/api['hydration_name'](cp0)).read_bytes())
    first=u.boundary(Path(root),u.ORDINARY_ADOPTION,cp0,api['OVERLAY'],min(t['native_session'] for t in material['terms']))
    second=u.boundary(Path(root),data.ADOPTION,first,'zogenix-sensor-input.json',p['event']['native_session'])
    data.need(first['sha256']==value['cp1_outer_sha256'] and first['run']['checkpoint_sha256']==value['cp1_inner_sha256']
         and second['sha256']==value['cp2_outer_sha256'] and second['repairs']==cp['repairs']
         and second['base']==cp['base'] and second['run']['input_sha256']==cp['run']['input_sha256'],
         'ADDITIONAL_INDEPENDENT_BOTH_ACTUAL_CANONICAL_NEUTRAL_BOUNDARIES')
    for directory in (u.ORDINARY_ADOPTION,data.ADOPTION):
        raw=gzip.decompress((Path(root)/(directory+'-correlation-inputs.jsonl.gz')).read_bytes())
        data.need(len(raw)==value['observation_seed_bytes'] and data.sha(raw)==value['observation_seed_sha256'],
                  'ADDITIONAL_ZERO_NEW_OBSERVATIONS_AT_BOTH_BOUNDARIES')
    q=json.loads((Path(root)/data.QUALIFICATION).read_bytes())
    data.need(q['schema']=='research.retained-additional-sensor-zero-advance/1' and q['passed'] is True
         and q['root_admission_sha256']==p['origin_root_admission_sha256']
         and q['origin_sha256']==data.sha((Path(root)/data.ORIGIN).read_bytes())
         and q['parent_outer_sha256']==cp0['sha256'] and q['cp1_outer_sha256']==value['cp1_outer_sha256']
         and q['cp2_outer_sha256']==value['cp2_outer_sha256']
         and q['original593_prefix_sha256']==p['retained_prefix_sha256']
         and q['actual_parser_packets_and_two_neutral_adoptions_qualified'] is True
         and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0
         and q['canonical_financial_source_changed'] is False
         and q['observer_binding_sha256']==data.digest(observer_bindings(root,p)),
         'ADDITIONAL_EXACT_CLOSED_ZERO_FINANCIAL_PREPARATION_GATE')
    gate=Path(root)/'additional-sensor-cloud-qualification/branch-controller-qualification.json'
    data.need(data.sha(gate.read_bytes())==q['cloud_qualification_sha256'],'ADDITIONAL_ACTUAL_CLOUD_QUALIFICATION_BYTES')
    return value,cp0

def event_rows(root,rows):
    """Reuse original Zogenix event preimage checks, never its recovery oracle."""
    hosted()
    import system_campaign_zogenix_review as z
    from system_campaign_zogenix_facts import PRIVATE
    from system_campaign_zogenix_input import SID,DAY
    fn=data.function(data.source('system_campaign_zogenix_review.py'),'review')
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='row']
    start,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='material']
    end,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='returns']
    block=ast.fix_missing_locations(ast.Module(body=loop.body[start:end],type_ignores=[]))
    allowed={};resolutions=[];source=json.loads((Path(root)/PRIVATE).read_bytes())
    for row in rows:
        scope=dict(vars(z),root=Path(root),row=row,source=source,resolution=None)
        exec(compile(block,'<original-zogenix-event-preimage-block>','exec'),scope)
        if scope['resolution'] is not None:resolutions.append(scope['resolution'])
        if scope['selected']:
            actual,=[v for v in row['material']['rows'] if v['security_id']==SID]
            allowed[data.digest(row)]=(DAY,SID,deepcopy(actual['current']))
    return allowed,resolutions

def review_rows(parent,current,retained,rows,financial,root,mixed):
    hosted()
    import system_campaign_financial_branches as b
    from system_campaign_uncertainty_math import RollingWitnessBounds
    from sentinel.controller import median5,champion_config
    data.need(retained and rows is not retained and len(rows)==current['completed']-parent['completed']
         and all(parent['source_cursor']<r['session']<=current['source_cursor'] for r in rows)
         and [r['session'] for r in rows]==sorted(financial),'ADDITIONAL_EXACT_NEW_COMMITTED_SUFFIX')
    allowed,resolutions=event_rows(root,rows)
    def additional_event_allows(row,item):
        expected=allowed.get(data.digest(row))
        return expected is not None and (row['session'],item['security_id'],item['current'])==expected
    namespace=dict(vars(b),rows=rows,retained_count=len(retained),cp=current,financial=financial,
        math_state=RollingWitnessBounds.restore(retained[-1]['math']),
        possible=deepcopy(retained[-1]['possible_after']),representative=b.discrete(parent['run']['state']['median5']),
        median5=median5,champion_config=champion_config,total=0,maximum=len(retained[-1]['possible_after']),
        growth=mixed,additional_event_allows=additional_event_allows)
    exec(compile(data.suffix_tree(),'<source-qualified-additional-branch-suffix>','exec'),namespace)
    return dict(rows=len(rows),retained_rows=len(retained),exhaustive_leaves=namespace['total'],
        maximum_possible_states=namespace['maximum'],event_resolution=resolutions,
        prior_proof_rows_reexecuted=0,every_reachable_decision_identical=True)

def retained_seed(root,cp,spec,p):
    """Reuse original committed-seed guards with one typed validator binding."""
    hosted()
    import system_campaign_financial_uncertainty as u
    from system_campaign_financial_partial import validate_root_spec
    def contract(actual,selected):
        validate_root_spec(selected)
        data.need(data.phase(selected)==p and p['adoption_mode']=='RETAINED'
             and actual['base']==selected['base'],'ADDITIONAL_EXPLICIT_LATER_ROOT_AND_ORIGIN')
        validate_origin(root,actual,p)
        hashes=json.loads((HERE/u.INTEGRATION).read_bytes())['canonical_controller_sources']
        data.need(len(hashes)==6 and all(actual['base']['sources'].get(n)==h for n,h in hashes.items()),
                  'ADDITIONAL_RETAINED_UNCHANGED_SIX_CONTROLLER_SOURCES')
        return hashes
    def validate(where,actual):
        from research.pooled_vacancy_funding import backtest
        return data.validate_models(where,actual,p,origin=origin(where),input_hash=backtest.input_hash)
    fn=data.legacy_function(u.__file__,'retained_seed','retained_seed')
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
    data.need(len(imports)==1 and sum(n.name=='validate_input' for n in imports[0].names)==1,
              'ADDITIONAL_EXACT_RETAINED_SEED_VALIDATOR_IMPORT')
    imports[0].names=[n for n in imports[0].names if n.name!='validate_input']
    namespace=dict(vars(u),retained_contract=contract,retained_phase=lambda spec:dict(rows=p['proof_rows'],
        new_rows=p['proof_new_rows'],retained_rows=p['proof_retained_rows']),validate_input=validate)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<original-retained-seed-qualified-typed-validator>','exec'),namespace)
    return namespace['retained_seed'](Path(root),cp,spec)

def active_branch():
    hosted()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_zogenix_input import InputCodec
    from system_campaign_financial_projection import OwnProjection,branch_loader_owner
    from system_campaign_financial_branches import Codec
    installed=backtest.load_repair;z=getattr(installed,'__self__',None)
    data.need(isinstance(z,InputCodec) and installed==z.load,'ADDITIONAL_ACTUAL_INSTALLED_RETAINED_SENSOR_CODEC')
    own=getattr(z.original_load,'__self__',None)
    data.need(isinstance(own,OwnProjection) and own.active and z.original_load==own.load,
              'ADDITIONAL_RETAINED_SENSOR_DELEGATES_ACTUAL_ACTIVE_APHA')
    branch=branch_loader_owner(z.original_load)
    data.need(isinstance(branch,Codec),'ADDITIONAL_RETAINED_ORIGINAL_BRANCH_OWNER')
    return branch,z

def run_retained(cp,out,args,rows,observer,execution,spec,old,p):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_alder_date_v2 import AlderDateV2
    from system_campaign_p02_retained_run import idempotent_dispatch
    from system_campaign_uncertainty_archive import preserve as preserve_event
    from system_campaign_zogenix_facts import PRIVATE
    from system_campaign_financial_compound_dispatch import retained_versions,retained_terminal_callers
    value,cp0=verify_qualification(old,cp,p)
    hashes,seed,qualification=retained_seed(old,cp,spec,p)
    branch,zcodec=active_branch()
    preserve(old,cp,out,spec);preserve_event(old,out)
    (out/'branch-controller-qualification.json').write_bytes(qualification)
    ordinary_reconstruction(old,out/'additional-retained-ordinary-reconstruction',p)
    for d in cp['repairs']:
        backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
    alder=AlderDateV2(HERE/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/'retained-alder-source.json')
    source=json.loads((old/'hydrated-uncertainty-event.json').read_bytes())
    api=ordinary_api(p)
    with growth_scope(cp,spec) as mixed:
        Joint=joint_certificate(mixed)
        certificate=Joint(out,branch,alder.native,hashes,seed=seed,event_source=source,zogenix_codec=zcodec,
            zogenix_native=zcodec.native,zogenix_source=json.loads((out/PRIVATE).read_bytes()))
        with alder,idempotent_dispatch(alder),certificate,observer,execution:
            with ordinary_observers(out,out,p,cp0):code=backtest.main(args)
    actual=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    data.need(actual['base']==cp['base'] and actual['repairs']==cp['repairs']
         and actual['run']['input_sha256']==cp['run']['input_sha256'],'ADDITIONAL_RESTART_HAS_NO_IMPLICIT_NEW_INPUT')
    return code

def review(parent,evidence,out,spec,old):
    hosted()
    import system_campaign_financial_uncertainty as u
    import system_campaign_zogenix_facts as z
    from system_campaign_financial_branches import seed,encoded
    from system_campaign_uncertainty_review import committed_rows
    from system_campaign_financial_partial import financial_inputs
    from system_campaign_uncertainty_archive import resolve
    from research.pooled_vacancy_funding import backtest
    p=data.phase(spec);data.need(p is not None,'ADDITIONAL_REVIEW_REQUIRES_EXACT_PHASE')
    current=read_cp(evidence/'book/checkpoint.json.gz')
    value,cp0=verify_qualification(evidence,current,p)
    if p['adoption_mode']=='INITIAL':
        data.common_source_binding(parent,p)
        hashes,retained,qualified=u.retained_seed(old,parent,spec)
        api=ordinary_api(p)
        cp1=u.boundary(evidence,u.ORDINARY_ADOPTION,parent,api['OVERLAY'],
            min(t['native_session'] for t in json.loads((evidence/api['hydration_name'](parent)).read_bytes())['terms']))
        cp2=u.boundary(evidence,data.ADOPTION,cp1,'zogenix-sensor-input.json',p['event']['native_session'])
        data.need(cp1['sha256']==value['cp1_outer_sha256'] and cp2['sha256']==value['cp2_outer_sha256']
             and cp2['repairs']==current['repairs'],'ADDITIONAL_REVIEW_TWO_EXACT_NEUTRAL_BOUNDARIES')
        from system_campaign_financial_resume import seed_rows
        expected=b''.join(seed_rows(old,parent,spec))
        for directory in (u.ORDINARY_ADOPTION,data.ADOPTION):
            data.need(gzip.decompress((evidence/(directory+'-correlation-inputs.jsonl.gz')).read_bytes())==expected,
                      'ADDITIONAL_REVIEW_NO_OBSERVATIONS_DURING_EITHER_ADOPTION')
    else:
        hashes,retained,qualified=retained_seed(old,parent,spec,p)
        data.need(parent['repairs']==current['repairs'],'ADDITIONAL_REVIEW_REGISTERED_RESTART_INPUTS_UNCHANGED')
    data.need((evidence/'branch-controller-qualification.json').read_bytes()==qualified,
              'ADDITIONAL_ORIGINAL_BRANCH_QUALIFICATION_BYTES')
    original,_=resolve(old);actual,_=resolve(evidence)
    data.need(original.name==actual.name and original.read_bytes()==actual.read_bytes(),
              'ADDITIONAL_ORIGINAL_ALDR_PRE_EVENT_GZIP_UNCHANGED')
    reconstruction=out/'additional-review-source';reconstruction.mkdir()
    z.hydrate(evidence,reconstruction)
    data.need((reconstruction/z.PRIVATE).read_bytes()==(evidence/z.PRIVATE).read_bytes(),
              'ADDITIONAL_INDEPENDENT_ORIGINAL_EVENT_SOURCE_RECONSTRUCTION')
    modeled=data.validate_models(evidence,current,p,origin=value,input_hash=backtest.input_hash)
    data.need(len(modeled)==1,'ADDITIONAL_REVIEW_ONE_EXACT_TYPED_SENSOR')
    # Installed codec context is needed by original ordinary packet qualification.
    active_branch()  # review_driver keeps this exact chain installed through readonly review.
    ordinary_reconstruction(evidence,out/'additional-review-ordinary',p)
    current_rows=seed(evidence,current)
    data.need(len(current_rows)>=len(retained) and b''.join(encoded(r)+b'\n' for r in current_rows[:len(retained)])==
         b''.join(encoded(r)+b'\n' for r in retained),'ADDITIONAL_ENTIRE_PRIOR_COMMITTED_PREFIX_BYTE_IDENTICAL')
    financial={r['session']:r for r in committed_rows(evidence/'book',current,'daily') if r['session']>parent['source_cursor']}
    with growth_scope(parent,spec) as mixed:
        result=review_rows(parent,current,retained,current_rows[len(retained):],financial,evidence,mixed)
    # A retained restart may start after the added event; still require its archived exact proof.
    all_added=current_rows[p['retained_rows']:]
    allowed,resolutions=event_rows(evidence,all_added)
    if current['source_cursor']>=p['event']['effective_session']:
        data.need(len(resolutions)==1,'ADDITIONAL_COMMITTED_EVENT_PREIMAGE_PROOF_REQUIRED')
    save(out/'uncertainty-certificate-review.json',dict(result,schema='research.retained-additional-sensor-branch-review/1',
        passed=True,checkpoint_sha256=current['sha256'],parent_sha256=parent['sha256'],through=current['source_cursor'],
        original593_prefix_sha256=p['retained_prefix_sha256'],original_model_origin=p['original_branch_descriptor'],
        additional_model_descriptor=value['sensor_descriptor'],full_input_descriptors=len(current['repairs']),
        all_financial_watch_and_proof_identities_verified=True,all_original_and_added_uncertainty_retained=True,
        full_period_complete=current['completed']==2156))

def retained_models(root,cp,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest
    p=data.selected_declaration(root,cp,spec)
    data.need(p is not None,'ADDITIONAL_RETAINED_MODEL_EXPLICIT_SCOPE')
    has_added=any(doc['schema']==data.SCHEMA for d,doc in data.descriptors(root,cp))
    if has_added:
        value,_=verify_qualification(root,cp,p)
    else:
        data.need(p['adoption_mode']=='INITIAL' and cp['sha256']==p['origin_outer_sha256']
             and cp['completed']==p['origin_completed'] and cp['repairs']==p['original_descriptors'],
             'ADDITIONAL_ONLY_ORIGINAL_PRE_ADOPTION_PARENT_WITHOUT_SENSOR')
        data.common_source_binding(cp,p);value=None
    data.validate_models(root,cp,p,origin=value,require_additional=has_added,input_hash=backtest.input_hash)
    return True

def review_driver(evidence,out,spec):
    """Keep both codecs installed through uncertainty AND readonly roundtrips."""
    hosted()
    import system_campaign_financial_resume as resume
    from system_campaign_financial_partial import financial_inputs
    current=json.loads(gzip.decompress((Path(evidence)/'book/checkpoint.json.gz').read_bytes()))
    fn=data.function(Path(resume.__file__).read_bytes(),'review')
    # Remove exactly the newly documented dispatch prefix; all legacy review calls stay.
    start,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.ImportFrom) and
            n.module=='system_campaign_financial_additional_sensor']
    data.need(start==1 and isinstance(fn.body[start+1],ast.If)
         and ast.unparse(fn.body[start+1].test)=='additional_phase(spec) is not None',
         'ADDITIONAL_EXACT_REVIEW_LIFETIME_DISPATCH_SITE')
    fn.body=fn.body[:start]+fn.body[start+2:]
    data.need(data.sha(ast.dump(fn,include_attributes=False).encode())==data.LEGACY_AST['review_driver_body'],
              'ADDITIONAL_UNCHANGED_WHOLE_READONLY_REVIEW_BODY_AST')
    namespace=dict(vars(resume));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unchanged-review-body-inside-additional-codec-lifetime>','exec'),namespace)
    scratch=Path(out)/'additional-review-codec-retention';scratch.mkdir()
    with financial_inputs(Path(evidence),current,scratch,spec):
        return namespace['review'](evidence,out,spec)

def observer_bindings(root,p):
    """Original raw input/material generations; observations grant no new input."""
    hosted();root=Path(root)
    import system_campaign_financial_future as f
    bindings=[];keys=set()
    cp0=read_cp(root/ORIGIN_DIR/'cp0.json.gz')
    data.need(len(p['inherited_ordinary_observers'])==3 and sum(v['stock_bearing'] for v in p['inherited_ordinary_observers'])==1,
              'ADDITIONAL_COMPLETE_THREE_ORIGIN_UNIQUE_STOCK_INVENTORY')
    expected={}
    from system_campaign_financial_projection import retained_activation,binding
    approved_projection=retained_activation(root,cp0)
    for d,doc in data.descriptors(root,cp0):
        selected_refs=[v['reference'] for v in doc['source_evidence'] if v['reference'].startswith(f.REFERENCE.rsplit('/',1)[0]+'/')]
        if not selected_refs:continue
        data.need(doc['schema']=='terminal-repair/1' and all(v.startswith(f.REFERENCE+'/') for v in selected_refs),
                  'ADDITIONAL_NO_UNKNOWN_SELECTED_FUTURE_NAMESPACE_OR_SCHEMA')
        effective=approved_projection.payload['derived_projection'] if (approved_projection is not None and d['sha256']==binding().bindings['TARGET']) else doc
        future={(v['session'],v['security_id']) for v in effective['add'] if v['session']>p['origin_cursor']}
        if future:expected[d['sha256']]=future
    data.need(set(expected)=={r['descriptor']['sha256'] for r in p['inherited_ordinary_observers']},
              'ADDITIONAL_COMPLETE_REGISTERED_INHERITED_FORWARD_INVENTORY')
    for record in p['inherited_ordinary_observers']:
        d=record['descriptor'];raw=(root/'book/repairs'/d['filename']).read_bytes()
        material_raw=(root/record['material_file']).read_bytes();material=json.loads(material_raw);doc=json.loads(raw)
        data.need(d in p['original_descriptors'] and data.sha(raw)==d['sha256']
             and data.sha(material_raw)==record['material_sha256']
             and doc['schema']=='terminal-repair/1' and material['parent_outer_sha256']==record['parent_outer_sha256']
             and material['selector_sha256']==record['original_producer_sha256']
             and doc['add']==[v['added'] for v in material['terms']]
             and any(e['reference']==f.REFERENCE+'/hydrated' and e['sha256']==record['material_sha256']
                     for e in doc['source_evidence']),
             'ADDITIONAL_INHERITED_ORDINARY_EXACT_RAW_MATERIAL_AND_SOURCE_GENERATION')
        effective_raw=(root/record['effective_file']).read_bytes();effective=json.loads(effective_raw)
        data.need(data.sha(effective_raw)==record['effective_sha256'],
                  'ADDITIONAL_EXACT_INHERITED_EFFECTIVE_DOCUMENT_BYTES')
        if record['projection'] is not None:
            from system_campaign_financial_projection import retained_activation,binding,PAYLOAD
            approved=retained_activation(root,cp0);declared=record['projection']
            data.need(approved is not None and d['sha256']==binding().bindings['TARGET']
                 and record['effective_file']==approved.projection_path.relative_to(root).as_posix()
                 and effective==approved.payload['derived_projection']
                 and declared['payload_file']==PAYLOAD
                 and declared['payload_sha256']==data.sha((root/PAYLOAD).read_bytes())
                 and declared['binding_sha256']==data.sha((HERE/'system-campaign-own-future-projection.json').read_bytes()),
                 'ADDITIONAL_ONLY_ORIGINAL_QUALIFIED_APHA_EFFECTIVE_PROJECTION')
        else:data.need(effective==doc,'ADDITIONAL_UNPROJECTED_ORDINARY_DOCUMENT_EXACT')
        actual={(t['session'],t['security_id']) for t in effective['add']}
        data.need(type(record['stock_bearing']) is bool
             and {(v['session'],v['security_id']) for v in effective['add'] if v['session']>p['origin_cursor']}==expected[d['sha256']]
             and [list(k) for k in [(t['session'],t['security_id']) for t in effective['add']]]==record['selected_keys']
             and record['stock_bearing']==any(t['kind']=='CASH_PLUS_STOCK' and t['session']>p['origin_cursor'] for t in effective['add'])
             and all(t['session']<=p['origin_cursor'] or t['kind'] in ('CASH_MERGER','CASH_PLUS_STOCK') for t in effective['add']),
             'ADDITIONAL_EXACT_ORIGIN_SELECTED_KEYS_AND_ORIGINAL_KINDS')
        data.need(len(actual)==len(effective['add']) and not keys.intersection(actual),
                  'ADDITIONAL_OBSERVER_DISJOINT_INHERITED_SELECTED_KEYS')
        keys.update(actual);bindings.append(dict(descriptor_sha256=d['sha256'],material_sha256=record['material_sha256'],
            effective_sha256=record['effective_sha256'],stock_bearing=record['stock_bearing'],
            original_producer_sha256=record['original_producer_sha256'],
            observation_directory='additional-inherited-ordinary-observation/'+d['sha256']))
    material=json.loads((root/ordinary_api(p)['hydration_name'](dict(sha256=p['origin_outer_sha256']))).read_bytes())
    extra={(v['added']['session'],v['security_id']) for v in material['terms']}
    data.need(len(extra)==len(material['terms']) and not keys.intersection(extra),
              'ADDITIONAL_OBSERVER_NEW_AND_INHERITED_TERMS_DISJOINT')
    return bindings


def empty_scope_results(api,current,cp,material,overlay_sha,material_sha):
    before=deepcopy(material)
    frozen_input=deepcopy(material);frozen=api['source_scopes'](cp,frozen_input,overlay_sha,material_sha)
    data.need(frozen==[] and frozen_input==before,'ADDITIONAL_FROZEN_ORIGINAL_EMPTY_SCOPE_READONLY')
    current_input=deepcopy(material);actual=current.source_scopes(cp,current_input,overlay_sha,material_sha)
    data.need(actual==frozen and current_input==before,'ADDITIONAL_CURRENT_EMPTY_SCOPE_READONLY')
    return frozen

@contextmanager
def ordinary_observers(root,out,p,cp0):
    """Unique stock owner outermost; exact current-class calls and original gate."""
    hosted();root,out=Path(root),Path(out)
    import system_campaign_financial_future as f
    from system_campaign_zogenix_sensor import isolated_function
    from system_campaign_financial_compound_dispatch import retained_versions,retained_terminal_callers
    api=ordinary_api(p);bindings=observer_bindings(root,p)
    modules=retained_versions(root,cp0)
    data.need(modules,'ADDITIONAL_EXACT_QUALIFIED_RETAINED_CALLER_ROUTE_REQUIRED')
    events=[]
    for record,binding in zip(p['inherited_ordinary_observers'],bindings,strict=True):
        bound=isolated_function(f.ActualEvents.__init__,OVERLAY=record['effective_file'],
                                hydration_name=lambda cp,name=record['material_file']:name)
        material_path=root/record['material_file'];overlay_path=root/record['effective_file']
        empty_scope_results(api,f,cp0,json.loads(material_path.read_bytes()),data.sha(overlay_path.read_bytes()),data.sha(material_path.read_bytes()))
        event=f.ActualEvents.__new__(f.ActualEvents);bound(event,root,p['arm'],cp=cp0)
        data.need(event.scopes==[],'ADDITIONAL_ORIGINAL_SOURCE_SCOPES_PROVE_UNSCOPED_ORIGINAL_INPUT')
        event.out=out/binding['observation_directory'];event.out.mkdir(parents=True,exist_ok=True)
        events.append((record['stock_bearing'],event))
    material_path=root/api['hydration_name'](cp0);overlay_path=root/api['OVERLAY']
    empty_scope_results(api,f,cp0,json.loads(material_path.read_bytes()),data.sha(overlay_path.read_bytes()),data.sha(material_path.read_bytes()))
    newer=f.ActualEvents(root,p['arm'],cp=cp0)
    data.need(newer.scopes==[] and all(v['kind']=='CASH_MERGER' for v in newer.terms.values()),
              'ADDITIONAL_NEW_OBSERVER_UNSCOPED_CASH_ONLY')
    newer.out=out
    cash=[event for stock,event in events if not stock]
    stock=[event for stock,event in events if stock]
    data.need(len(stock)==1 and all(v['session']<=p['origin_cursor'] or v['kind']=='CASH_MERGER' for event in cash for v in event.terms.values()),
              'ADDITIONAL_UNIQUE_STOCK_OUTERMOST_WITH_CASH_ONLY_INNERS')
    with ExitStack() as stack:
        for event in [*cash,newer,*stock]:stack.enter_context(event)
        stack.enter_context(retained_terminal_callers(modules))
        yield bindings
