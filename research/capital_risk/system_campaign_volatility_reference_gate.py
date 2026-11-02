"""Reuse the completed FAST path; execute and retain only missing REFERENCE."""
import ast,gzip,json,os,shutil,time
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_discovery_context import digest as publication_digest
from system_campaign_parallel_discovery import compile_body
from system_campaign_volatility_reference_parent import specification,validate_fast
import system_campaign_volatility_discovery_gate as original
from system_campaign_volatility_discovery_gate_v2 import recorder_tree


def phase(out,stage,**extra):
    target=Path(out)/'reference-progress';target.mkdir(exist_ok=True)
    with (target/'phases.jsonl').open('ab') as stream:
        stream.write((json.dumps(dict(stage=stage,monotonic_seconds=time.monotonic(),**extra),sort_keys=True)+'\n').encode())
        stream.flush();os.fsync(stream.fileno())


def progress(out,mode,records):
    need(mode=='REFERENCE' and 1<=len(records)<=3,'V_REFERENCE_ONE_CANONICAL_PROGRESS_RECORD_PER_SESSION')
    target=Path(out)/'reference-progress';target.mkdir(exist_ok=True)
    record=records[-1];path=target/(record['session']+'.json.gz')
    with path.open('xb') as file:
        with gzip.GzipFile(fileobj=file,mode='wb',filename='',mtime=0) as stream:
            stream.write((json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode())
        file.flush();os.fsync(file.fileno())
    phase(out,'CANONICAL_REFERENCE_TRANSITION_RETAINED',session=record['session'],
          checkpoint_file=path.name,sha256=sha256_file(path))


def seed_fast(previous,parent,out,root,selected_file):
    previous=Path(previous);spec=specification(json.loads((previous/'spec.json').read_bytes())['arm'])
    inventory=json.loads((Path(__file__).parent/'system-campaign-volatility-fast-predecessors-001.json').read_bytes())
    need(inventory['arms'][spec['arm']]==spec,'V_REFERENCE_OWN_IMMUTABLE_FAST_SPEC')
    need(parent['sha256']==spec['strict_parent_outer_sha256']
         and sha256_file(previous/'source-bindings.json')==spec['source_binding_sha256'],
         'V_REFERENCE_FAST_AND_REFERENCE_SAME_STRICT_PARENT_AND_FINANCIAL_SOURCE')
    shutil.copyfile(Path(root)/selected_file,Path(out)/'strict-parent.json.gz')
    need(json.loads(gzip.decompress((Path(out)/'strict-parent.json.gz').read_bytes()))==parent,
         'V_REFERENCE_PRESERVE_EXACT_ORIGINAL_PARENT_FOR_INDEPENDENT_PATH_REVIEW')
    source=previous/'qualification/fast';target=Path(out)/'fast'
    shutil.copytree(source,target)
    need(sha256_file(target/'actual-runtime-path.json.gz')==spec['actual_fast_path']['sha256']
         and sha256_file(target/'discovery-canonical-qualification.json')==spec['actual_fast_proof']['sha256'],
         'V_REFERENCE_COPIED_FAST_BYTES_UNCHANGED')
    records=json.loads(gzip.decompress((target/'actual-runtime-path.json.gz').read_bytes()))
    proof=json.loads((target/'discovery-canonical-qualification.json').read_bytes())
    need(proof['strict_parent_outer_sha256']==parent['sha256'] and len(records)==3,
         'V_REFERENCE_FAST_THREE_CASE_PATH_OWN_PARENT')
    for value in records:
        cp=value['checkpoint']
        need(all(cp[k]==parent['run'][k] for k in ('schema','policy','input_sha256','base_main_sha'))
             and cp['state']['strategy_identity']==parent['run']['state']['strategy_identity'],
             'V_REFERENCE_FAST_RETAINED_ORIGINAL_INPUT_POLICY_AND_STRATEGY')
    receipt=dict(schema='research.volatility-reused-fast-qualification/1',run_id=spec['run_id'],head=spec['head'],
        artifact_id=spec['artifact_id'],receipt_sha256=spec['receipt_sha256'],
        cipher_sha256=spec['encrypted_output']['sha256'],inventory_sha256=spec['inventory_sha256'],
        source_binding_sha256=spec['source_binding_sha256'],fast_path_sha256=spec['actual_fast_path']['sha256'],
        fast_proof_sha256=spec['actual_fast_proof']['sha256'],recomputed=False,financial_authority=False)
    original.save(Path(out)/'retained-fast-admission.json',receipt)
    return records,proof


def reference_tree():
    fn=recorder_tree()
    loops=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=="('FAST', 'REFERENCE')"]
    need(len(loops)==1,'V_REFERENCE_EXACT_OLD_TWO_MODE_LOOP')
    loops[0].iter=ast.Tuple(elts=[ast.Constant('REFERENCE')],ctx=ast.Load())
    assignments=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and len(n.targets)==1
                 and ast.unparse(n.targets[0])=='proofs']
    need(len(assignments)==1,'V_REFERENCE_ONE_RETAINED_FAST_SEED_SITE')
    at=assignments[0]+1
    fn.body[at:at]=ast.parse("paths['FAST'],proofs['FAST']=seed_fast(Path('/previous'),parent,out,root,selected_file)").body
    observed,=[n for n in ast.walk(fn) if isinstance(n,ast.FunctionDef) and n.name=='observed']
    inserts=[i for i,n in enumerate(observed.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
             and ast.unparse(n.value.func)=='records.append']
    need(len(inserts)==1,'V_REFERENCE_ONE_DURABLE_COMPLETED_CANONICAL_TRANSITION_SITE')
    observed.body[inserts[0]+1:inserts[0]+1]=ast.parse('progress(out,mode,records)').body
    observed.body[0:0]=ast.parse("phase(out,'CANONICAL_REFERENCE_ADVANCE_BEGIN',session=published.session)").body
    return ast.fix_missing_locations(fn)


def qualify(*args,**kwargs):
    iterator=kwargs['source_iterator'];calls=0;out=Path(args[2])
    def timed_iterator(*values,**options):
        nonlocal calls
        calls+=1;phase(out,'SOURCE_PREFIX_BEGIN',invocation=calls)
        try:return iterator(*values,**options)
        finally:phase(out,'SOURCE_PREFIX_RETURNED',invocation=calls)
    kwargs=dict(kwargs,source_iterator=timed_iterator)
    return compile_body(reference_tree(),dict(vars(original),publication_digest=publication_digest,
        seed_fast=seed_fast,progress=progress,phase=phase))(*args,**kwargs)
