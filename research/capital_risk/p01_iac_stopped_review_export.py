"""Only fresh stopped review output is sealed; no financial/Q tree export."""
import ast,json,os,re
from pathlib import Path
from full_system_benchmark import need
from seal import sha256_file
from system_campaign_pxd_financial_body import function
from system_campaign_parallel_discovery import compile_body
import system_campaign_evidence_export as original
import system_campaign_p01_discovery_export as marker
from p01_iac_stopped_review_target import encoded,target,read,plain
STAGE='campaign-p01-stopped-evidence-review'
SCHEMA='research.p01-stopped-evidence-review-receipt/1'
CIPHER='p01-iac-stopped-review-report.tar.crseal'
PUBLIC={'schema','stage','run_id','head','request_sha256','source_count','protocol_sha256','target_run_id','target_head',
 'target_request_sha256','target_source_count','target_sha256','status','production_contacted','financial_authority',
 'financial_resume_authorized','original_review_exit_code','reviewer','review_log_copy_failed','export_qualification_sha256',
 'review_encrypted_output','output_exported','export_error'}
ROOT_FILES={'request.json','target.json','spec.json','review-authentication.json','review-execution.json',
 'iac-unit-financial-review.json','review-result-link.json','review-output-scope.json','worker-inspect.json','worker.log','log-copy-failure.json','worker-error.txt','driver-error.txt'}

def sealed(root,destination,key,request):
    call=function('system_campaign_evidence_export.py','seal',{'campaign-factual-suffix':STAGE,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'STOPPED_REVIEW_EXACT_REPORT_SCOPE'},vars(original))
    return call(Path(root),Path(destination),key,Path(request),'P01',stage=STAGE,protocol_sha256=plain(read(request))['protocol_sha256'])

def qualify_export(path,request):
    node,=[n for n in ast.parse(Path(marker.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_export']
    return compile_body(node,dict(vars(marker),STAGE=STAGE,sealed=sealed,__file__=__file__))(path,request)

def write_receipt(path,value):
    need(set(value)<=PUBLIC and value['schema']==SCHEMA and value['stage']==STAGE and value['production_contacted'] is False
        and value['financial_authority'] is False and value['financial_resume_authorized'] is False,'STOPPED_REVIEW_PUBLIC_ALLOWLIST')
    need(type(value['run_id']) is str and value['run_id'].isdigit() and int(value['run_id'])>0
        and type(value['target_run_id']) is int and value['target_run_id']>0
        and all(type(value[k]) is str and re.fullmatch('[0-9a-f]{40}',value[k]) is not None for k in ('head','target_head'))
        and all(type(value[k]) is str and re.fullmatch('[0-9a-f]{64}',value[k]) is not None for k in
            ('request_sha256','protocol_sha256','target_request_sha256','target_sha256'))
        and type(value['source_count']) is int and value['source_count']>0
        and type(value['target_source_count']) is int and value['target_source_count']==515
        and type(value['original_review_exit_code']) is int and value['original_review_exit_code']==1
        and type(value['output_exported']) is bool and type(value['status']) is str
        and ('review_log_copy_failed' not in value or type(value['review_log_copy_failed']) is bool),
        'STOPPED_REVIEW_PUBLIC_IDENTITY_COUNT_HASH_AND_STATUS_TYPES')
    if 'export_qualification_sha256' in value:
        need(type(value['export_qualification_sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['export_qualification_sha256']) is not None,
             'STOPPED_REVIEW_PUBLIC_MARKER_HASH_TYPE')
    for k,v in value.items():
        if k not in ('reviewer','review_encrypted_output','export_error'):need(type(v) in (str,int,bool,type(None)),'STOPPED_REVIEW_PUBLIC_SCALARS_ONLY')
    if 'reviewer' in value:
        s=value['reviewer'];need(set(s)=={'stopped','exit_code','oom_killed','wait_error'} and s['stopped'] is True
            and type(s['exit_code']) is int and type(s['oom_killed']) is bool and type(s['wait_error']) in (str,type(None)), 'STOPPED_REVIEW_PUBLIC_STOP_TYPES')
    if 'review_encrypted_output' in value:
        a=value['review_encrypted_output'];need(set(a)=={'name','bytes','sha256','manifest_sha256','compression'}
            and a['name']==CIPHER and type(a['bytes']) is int and a['bytes']>0 and a['compression']=='TAR_GZIP_V1'
            and all(type(a[k]) is str and re.fullmatch('[0-9a-f]{64}',a[k]) is not None for k in ('sha256','manifest_sha256')),'STOPPED_REVIEW_PUBLIC_ASSET_TYPES')
    if 'export_error' in value:
        e=value['export_error'];need(set(e)=={'type','code'} and type(e['type']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',e['type']) is not None
            and type(e['code']) is str and re.fullmatch('REFUSED_[A-Z0-9_]+|REVIEW_EXPORT_FAILED',e['code']) is not None,'STOPPED_REVIEW_PUBLIC_ERROR_TYPES')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);pending=path.with_suffix('.partial')
    with pending.open('xb') as stream:stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
    os.replace(pending,path)

def output_inventory(root,spec,*,success=False):
    root=Path(root);paths=list(root.rglob('*'));need(not root.is_symlink() and not any(p.is_symlink() for p in paths),'STOPPED_REVIEW_OUTPUT_NO_SYMLINK')
    inventory={}
    directories={str(parent).replace('\\','/') for name in ROOT_FILES|set(spec['review_context_files'])
        for parent in Path(name).parents if str(parent)!='.'}
    for path in paths:
        name=path.relative_to(root).as_posix();base=re.sub(r'\.tmp-[0-9a-f]+$','',name)
        if path.is_dir():
            need(name in directories,'STOPPED_REVIEW_ONLY_DECLARED_OUTPUT_PARENT_DIRECTORIES');continue
        need(path.is_file(),'STOPPED_REVIEW_ONLY_REGULAR_OUTPUT_FILES')
        need(base in ROOT_FILES or base in spec['review_context_files'],'STOPPED_REVIEW_ONLY_DECLARED_FRESH_REPORT_CONTEXT_OR_FRAGMENT')
        if success and name in spec['review_context_files'] and name.startswith('contexts/book/repairs/'):
            need(dict(bytes=path.stat().st_size,sha256=sha256_file(path))==spec['review_context_files'][name],'STOPPED_REVIEW_ORIGINAL_REPAIR_COPY_EXACT')
        inventory[name]=dict(bytes=path.stat().st_size,sha256=sha256_file(path))
    need(len(inventory)<5000 and sum(e['bytes'] for e in inventory.values())<=2*1024**3,'STOPPED_REVIEW_EXISTING_TWO_GIB_EXPORT_BOUND')
    return inventory

def finish(receipt,root,path,key,request,*,known):
    receipt['output_exported']=False;write_receipt(path,receipt)
    if known:
        try:
            need(receipt['reviewer']['stopped'] is True,'STOPPED_REVIEW_KNOWN_STOP_BEFORE_EXPORT')
            stop=receipt['reviewer'];success=(stop['exit_code']==0 and stop['oom_killed'] is False
                and receipt['status']=='STOPPED_EVIDENCE_READONLY_REVIEW_PASSED_PENDING_CLIENT')
            if success:
                required={'request.json','target.json','spec.json','review-authentication.json','review-execution.json',
                    'iac-unit-financial-review.json','review-result-link.json','worker-inspect.json'}
                need(all((Path(root)/name).is_file() for name in required)
                    and any((Path(root)/name).is_file() for name in ('worker.log','log-copy-failure.json')),
                    'STOPPED_REVIEW_COMPLETE_SUCCESS_REPORT_AND_PROVENANCE_FILES')
            inventory=output_inventory(root,target(),success=success)
            scope=dict(schema='research.p01-stopped-review-output-scope/1',reviewer_stop=stop,members=inventory,
                successful_repair_copy_checks=success,all_failure_fragments_unadmitted=not success,financial_authority=False)
            with (Path(root)/'review-output-scope.json').open('xb') as stream:
                stream.write(encoded(scope));stream.flush();os.fsync(stream.fileno())
            receipt['review_encrypted_output']=sealed(root,Path(path).parent/CIPHER,key,request);receipt['output_exported']=True
        except Exception as error:
            text=str(error);receipt['export_error']=dict(type=type(error).__name__,code=text if re.fullmatch('REFUSED_[A-Z0-9_]+',text) else 'REVIEW_EXPORT_FAILED')
            receipt['status']='KNOWN_STOP_REPORT_EXPORT_REFUSED'
    write_receipt(path,receipt)
