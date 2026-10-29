"""Build public hash-only request from exact Git blobs and sealed inventories."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def need(v,reason):
    if not v:raise ValueError('REFUSED_FIT_REQUEST_'+reason)


def digest(value):return hashlib.sha256(value).hexdigest()


def source_inventory():
    index=subprocess.run(['git','ls-files','-s','-z'],capture_output=True,check=True).stdout
    selected=[]
    required={'docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json','docs/sentinel-handoff/00_README/SHA256SUMS.txt'}
    for item in index.split(b'\0'):
        if not item:continue
        header,path=item.split(b'\t',1);name=path.decode();mode,blob,stage=header.decode().split()
        need(stage=='0','UNMERGED_INDEX')
        in_source=name.startswith(('sentinel/','shared/stock_strategy_shared/','research/capital_risk/'))
        if name in ('research/capital_risk/alpaca-fit-request.json','research/capital_risk/alpaca-funded-request.json'):continue
        if name in required or in_source and name.endswith(('.py','.json')):
            need(mode=='100644','SOURCE_LINK_OR_EXECUTABLE');selected.append((name,blob))
    need(required.issubset({name for name,_ in selected}),'FROZEN_RULE_CLOSURE')
    process=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    result={}
    try:
        for name,blob in selected:
            process.stdin.write((blob+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().decode().split();need(len(header)==3 and header[0]==blob and header[1]=='blob','GIT_BLOB')
            size=int(header[2]);payload=process.stdout.read(size);need(len(payload)==size and process.stdout.read(1)==b'\n','GIT_BLOB_LENGTH')
            result[name]={'bytes':size,'sha256':digest(payload)}
    finally:process.stdin.close();process.wait(timeout=10)
    return dict(sorted(result.items()))


def continuation_request(previous,artifact_id,source,dataset_sha,protocol_sha):
    previous=Path(previous);root=previous/'verified/full/book'
    admitted=json.loads((previous/'verified/admission.json').read_bytes())
    receipt=json.loads((previous/'download/alpaca-fit-baseline.json').read_bytes())
    reviewed=json.loads((previous/'verified/full/stopped-independent-review/review/independent-review.json').read_bytes())
    status=json.loads((root/'baseline-status.json').read_bytes())
    retained=json.loads((root/'retained-checkpoints.json').read_bytes())
    cp=max(retained,key=lambda r:r['session'] or '')
    need(admitted['ciphers_gcm_and_inventory_verified'] is True and admitted['stopped'] is True
         and admitted['run_id']==int(receipt['run_id']) and admitted['head']==receipt['head']
         and reviewed['status']=='PARTIAL_PREFIX_REVIEWED'
         and cp['session']==status['last_committed_session']==reviewed['last_committed_session']
         and cp['journal']==status['journal'],'LATEST_OWN_REVIEWED_PREFIX')
    old=json.loads((previous/'request.json').read_bytes())
    need(old['protocol_sha256']==protocol_sha and old['dataset_sha256']==dataset_sha,'UNCHANGED_PREFIX_INPUT')
    protected=[p for p in old['source_files'] if p.startswith(('sentinel/','shared/stock_strategy_shared/'))
        or p in ('research/capital_risk/alpaca_fit_policy.py','research/capital_risk/alpaca-fit-protocol.json')]
    need(all(source[p]==old['source_files'][p] for p in protected),'UNCHANGED_CANONICAL_FINANCIAL_SOURCE')
    archive=previous/'download/artifact.zip'
    artifact={'id':artifact_id,'run_id':int(receipt['run_id']),'head':receipt['head'],
        'bytes':archive.stat().st_size,'sha256':digest(archive.read_bytes()),'full':receipt['encrypted_outputs']['full']}
    if status.get('new_transitions',0)>0:
        prior_ordinary=status['elapsed_seconds']/status['new_transitions']
    else:
        timing_path=root/'timing-gate.json'
        if not timing_path.exists():timing_path=root/'lineage/previous-timing-gate.json'
        timing=json.loads(timing_path.read_bytes())
        prior_ordinary=max(t['ordinary_seconds'] for t in timing['transition_seconds'][-3:])
    reference=old.get('input_reference') or {'commit':receipt['head'],'path':'research/capital_risk/alpaca_fit_inputs.py',
        **old['source_files']['research/capital_risk/alpaca_fit_inputs.py']}
    continuation={'artifact':artifact,'checkpoint':cp,'dataset_sha256':dataset_sha,'protocol_sha256':protocol_sha,
        'prior_ordinary_estimate_seconds':prior_ordinary}
    if (root/'suffix-budget.json').is_file():
        budget=json.loads((root/'suffix-budget.json').read_bytes())
        continuation['prior_fixed_transition_seconds']=max(1.,budget['estimated_seconds_per_step']-budget['measured_input_seconds'])
        continuation['timing_basis']='Prior measured packed input and bounded fixed-cost estimate; actual deadline still enforced.'
    return continuation,reference


def prepare(case,destination,request_id,previous=None,artifact_id=None,input_repair=None,admission_context=None,role_repair=None):
    case=Path(case);protocol=Path(__file__).with_name('alpaca-fit-protocol.json');p_sha=digest(protocol.read_bytes())
    captures={key:json.loads((case/folder/'transport.json').read_bytes()) for key,folder in
        [('prefix','transport-001'),('corroboration','transport-002'),('market','transport-003'),('bil','bil-transport-001')]}
    for key,transport in captures.items():
        expected={'prefix':'FAILED','corroboration':'INCOMPLETE','market':'COMPLETE','bil':'COMPLETE'}[key]
        need(transport['status']==expected and transport['protocol_sha256']==p_sha
             and transport['roster_sha256']==digest((case/'roster.json').read_bytes()),'CAPTURE_SCOPE')
    need(captures['prefix']['capture_status']['reason']=='SSLError'
        and captures['corroboration']['capture_status']['status']=='INCOMPLETE','FAILED_PREFIX_RETAINED')
    dataset={'schema':'research.alpaca-composite-input/1','protocol_sha256':p_sha,'roster_sha256':digest((case/'roster.json').read_bytes()),
        'manifests':{k:v['manifest_sha256'] for k,v in captures.items()}}
    component_book=case/'baseline-001/verified/full/book'
    qualification=component_book/'controller-component-qualification.json'
    old_request=json.loads((case/'baseline-001/request.json').read_bytes())
    source=source_inventory()
    common=('sentinel/controller/owned_impairment.py','research/capital_risk/alpaca_fit_policy.py','research/capital_risk/alpaca_fit_qualify.py')
    need(all(source[p]==old_request['source_files'][p] for p in common) and old_request['protocol_sha256']==p_sha,'UNCHANGED_REUSED_COMPONENT')
    reuse={'kind':'REUSE_AUTHENTICATED_COMPLETED_COMPONENT_CASES','run_id':40783323604,
        'head':'734eb1d3bdf38b60a7f60759410dbb7a47573e30','artifact_id':12857599938,
        'report_sha256':digest(qualification.read_bytes()),'qualified_source_files':{p:source[p] for p in common},
        'protocol_sha256':p_sha,'not_financial_or_performance_evidence':True}
    value={'schema':'research.alpaca-fit-hosted-request/1','study_id':'alpaca-owned55-fit-001','request_id':request_id,
        'stage':'INPUT_AND_CANONICAL_BASELINE','protocol_sha256':p_sha,'roster_sha256':dataset['roster_sha256'],
        'dataset_sha256':digest(json.dumps(dataset,sort_keys=True,separators=(',',':')).encode()),'captures':captures,
        'runtime':{'bytes':115666468,'sha256':'2069216d4133ae154eb76d4ac09cc0f719275c19fc3a95c7476d0f07f56b6b32'},
        'source_files':source,'reused_component_qualification':reuse,'verified_main_base':'bbcb728a972f483c9f76f2b0db2599b2134ab1bb',
        'production_contacted':False,'new_forecaster':False,'performance_result_expected_from_this_stage':False}
    if previous:
        need(type(artifact_id) is int and artifact_id>0,'CONTINUATION_ARTIFACT')
        value['continuation'],value['input_reference']=continuation_request(previous,artifact_id,source,value['dataset_sha256'],p_sha)
    if input_repair:
        need(previous is not None,'REPAIR_REQUIRES_OWN_PREFIX')
        path=Path(input_repair);name=path.as_posix();raw=path.read_bytes();repair=json.loads(raw)
        need(name in source and source[name]=={'bytes':len(raw),'sha256':digest(raw)}
             and repair['dataset_sha256']==value['dataset_sha256'] and repair['protocol_sha256']==p_sha,'EXACT_FACTUAL_REPAIR')
        value['sparse_input_repair']={'path':name,**source[name]}
    if admission_context:
        need(previous is not None and admission_context=='SPLIT_BOUNDARY_CAPTURED_PREDECESSOR_V1','BOUND_ADMISSION_CONTEXT')
        value['admission_context']=admission_context
    if role_repair:
        need(previous is not None,'ROLE_REQUIRES_OWN_PREFIX')
        path=Path(role_repair);name=path.as_posix();raw=path.read_bytes();role=json.loads(raw)
        need(name in source and source[name]=={'bytes':len(raw),'sha256':digest(raw)}
             and role['dataset_sha256']==value['dataset_sha256'] and role['protocol_sha256']==p_sha,'EXACT_ROLE_REPAIR')
        value['source_role_repair']={'path':name,**source[name]}
    destination=Path(destination);need(not destination.exists(),'REQUEST_COLLISION')
    destination.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'request_sha256':digest(destination.read_bytes()),'source_files':len(value['source_files']),
        'dataset_sha256':value['dataset_sha256'],'performance_result':False}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--output',required=True)
    p.add_argument('--request-id',required=True)
    p.add_argument('--continue-from');p.add_argument('--artifact-id',type=int)
    p.add_argument('--input-repair')
    p.add_argument('--admission-context')
    p.add_argument('--role-repair')
    a=p.parse_args();prepare(a.case,a.output,a.request_id,a.continue_from,a.artifact_id,a.input_repair,a.admission_context,a.role_repair)
