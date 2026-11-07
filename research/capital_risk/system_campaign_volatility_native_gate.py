"""Run changed native FAST only; compare every field to retained REFERENCE."""
import ast,gzip,json,os,shutil,time
from pathlib import Path
from full_system_benchmark import need,save
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from system_campaign_discovery_context import digest as publication_digest
from system_campaign_volatility_discovery_gate_v2 import recorder_tree
from system_campaign_volatility_native_parent import specification
from system_campaign_volatility_native_transport import profile
import system_campaign_volatility_discovery_gate as original


def phase(out,stage,**extra):
    target=Path(out)/'native-fast-progress';target.mkdir(exist_ok=True)
    with (target/'phases.jsonl').open('ab') as f:
        f.write((json.dumps(dict(stage=stage,monotonic_seconds=time.monotonic(),**extra),sort_keys=True)+'\n').encode())
        f.flush();os.fsync(f.fileno())


def progress(out,mode,records):
    need(mode=='FAST' and 1<=len(records)<=3,'V_NATIVE_ONLY_CHANGED_FAST_TRANSITIONS_RECORDED')
    target=Path(out)/'native-fast-progress';target.mkdir(exist_ok=True);record=records[-1]
    file=target/(record['session']+'.json.gz')
    with file.open('xb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',filename='',mtime=0) as stream:
            stream.write((json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode())
        f.flush();os.fsync(f.fileno())
    phase(out,'NATIVE_FAST_TRANSITION_RETAINED',session=record['session'],sha256=sha256_file(file))


def seed_reference(previous,parent,out,root,selected_file):
    previous=Path(previous);spec=specification(json.loads((previous/'spec.json').read_bytes())['arm'])
    need(parent['sha256']==spec['strict_parent_outer_sha256']
         and sha256_file(previous/'source-bindings.json')==spec['source_binding_sha256'],
         'V_NATIVE_RETAINED_REFERENCE_SAME_OWN_PARENT_AND_SOURCE')
    source=Path(root)/selected_file
    need(source.read_bytes()==(previous/'qualification/strict-parent.json.gz').read_bytes(),
         'V_NATIVE_ORIGINAL_STRICT_PARENT_BYTES_IDENTICAL')
    shutil.copyfile(source,Path(out)/'strict-parent.json.gz')
    target=Path(out)/'reference';shutil.copytree(previous/'qualification/reference',target)
    need(sha256_file(target/'actual-runtime-path.json.gz')==spec['reference_path']['sha256']
         and sha256_file(target/'discovery-canonical-qualification.json')==spec['reference_proof']['sha256'],
         'V_NATIVE_REFERENCE_PATH_AND_PROOF_EXACT_UNRECOMPUTED_BYTES')
    path=json.loads(gzip.decompress((target/'actual-runtime-path.json.gz').read_bytes()))
    proof=json.loads((target/'discovery-canonical-qualification.json').read_bytes())
    need(len(path)==3 and proof['strict_parent_outer_sha256']==parent['sha256'],
         'V_NATIVE_COMPLETED_REFERENCE_PATH_OWN_PARENT')
    for record in path:
        cp=record['checkpoint']
        need(all(cp[k]==parent['run'][k] for k in ('schema','policy','input_sha256','base_main_sha'))
             and cp['state']['strategy_identity']==parent['run']['state']['strategy_identity'],
             'V_NATIVE_REFERENCE_KEEPS_EVERY_ORIGINAL_IDENTITY')
    save(Path(out)/'retained-reference-admission.json',dict(
        schema='research.volatility-reused-reference-qualification/1',run_id=spec['run_id'],head=spec['head'],
        artifact_id=spec['artifact_id'],receipt_sha256=spec['receipt_sha256'],
        cipher_sha256=spec['encrypted_output']['sha256'],inventory_sha256=spec['inventory_sha256'],
        source_binding_sha256=spec['source_binding_sha256'],reference_path_sha256=spec['reference_path']['sha256'],
        reference_proof_sha256=spec['reference_proof']['sha256'],recomputed=False,financial_authority=False))
    return path,proof


def compiled_native_gate(horizon):
    tree=original.corrected_tree('FAST');sites=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='Execution':
            need(ast.unparse(n)=="Execution('FAST', signal_closes=127)",'V_NATIVE_EXACT_RETAINED_FAST_CONFIGURATION')
            n.keywords[0].value=ast.Constant(horizon);sites.append(n)
    need(len(sites)==2,'V_NATIVE_TWO_QUALIFICATION_TRANSPORT_SITES_ONLY')
    scope=dict(vars(original.original));exec(compile(ast.fix_missing_locations(tree),'<exact-original-native-v-input-material>','exec'),scope)
    return scope['qualify']


def native_tree():
    fn=recorder_tree();loops=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=="('FAST', 'REFERENCE')"]
    need(len(loops)==1,'V_NATIVE_ONE_OLD_TWO_MODE_LOOP');loops[0].iter=ast.Tuple(elts=[ast.Constant('FAST')],ctx=ast.Load())
    at,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='proofs']
    fn.body[at+1:at+1]=ast.parse("paths['REFERENCE'],proofs['REFERENCE']=seed_reference(Path('/previous'),parent,out,root,selected_file)").body
    observed,=[n for n in ast.walk(fn) if isinstance(n,ast.FunctionDef) and n.name=='observed']
    at,=[i for i,n in enumerate(observed.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='records.append']
    observed.body[at+1:at+1]=ast.parse('progress(out,mode,records)').body
    observed.body[:0]=ast.parse("phase(out,'NATIVE_FAST_ADVANCE_BEGIN',session=published.session)").body
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='proof.update']
    value,=[k for k in call.keywords if k.arg=='signal_material_closes'];value.value=ast.Name(id='signal_horizon',ctx=ast.Load())
    call.keywords.extend([ast.keyword(arg='native_signal_factory_sha256',value=ast.parse("material_profile['factory_sha256']",mode='eval').body),
                          ast.keyword(arg='reference_recomputed',value=ast.Constant(False))])
    return ast.fix_missing_locations(fn)


def qualify(root,parent,out,**kwargs):
    material_profile=profile();horizon=material_profile['signal_closes'];iterator=kwargs['source_iterator'];calls=0
    def timed_iterator(*args,**options):
        nonlocal calls
        calls+=1;phase(out,'SOURCE_PREFIX_BEGIN',invocation=calls)
        try:return iterator(*args,**options)
        finally:phase(out,'SOURCE_PREFIX_RETURNED',invocation=calls)
    def compiled(mode):
        need(mode=='FAST','V_NATIVE_COMPLETED_REFERENCE_MUST_NOT_EXECUTE_AGAIN')
        return compiled_native_gate(horizon)
    return compile_body(native_tree(),dict(vars(original),publication_digest=publication_digest,
        seed_reference=seed_reference,progress=progress,phase=phase,compiled_gate=compiled,
        signal_horizon=horizon,material_profile=material_profile))(root,parent,out,**dict(kwargs,source_iterator=timed_iterator))
