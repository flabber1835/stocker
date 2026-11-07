import ast,gzip,hashlib,json,os,sys,zipfile
from copy import deepcopy
from pathlib import Path,PurePosixPath
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p03-fin340-full17-reporting-20261106');C=Path(__file__).parents[2];sys.path.insert(0,str(C))
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P03_FIN340_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
F=R/'financial340-P03-source-snapshot';CAP=F/'capture-P03-13525097150-001'
ROOT='4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1'
OUTER='7b1a0140089732de1dc6c77a4d4cc996f79883be3d5b721c30cf9b41d85cac5b'
def long(p):
    p=Path(p);return p if str(p).startswith('\\\\?\\') or os.name!='nt' else Path('\\\\?\\'+str(p.resolve()))
sha=lambda raw:hashlib.sha256(raw).hexdigest()
enc=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
digest=lambda v:sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(v,s):
    if not v:raise ValueError(s)
def read_actual():
    manifest=json.loads((CAP/'authenticated-manifest.json').read_bytes());members=manifest['members'];root=long(CAP/'verified-output')
    need(len(members)==209 and sum(v['bytes'] for v in members.values())==142622219,'EXACT_COMPLETE_AUTHENTICATED_MANIFEST')
    def member(name):
        p=PurePosixPath(name);need(not p.is_absolute() and '..' not in p.parts and ':' not in name and '\\' not in name,'SAFE_MEMBER')
        raw=(root/name).read_bytes();need(dict(bytes=len(raw),sha256=sha(raw))==members[name],'AUTHENTICATED_MEMBER:'+name);return raw
    member.names=set(members)
    for name in members:member(name)
    from system_campaign_discovery_context import require_strict_checkpoint
    cp=require_strict_checkpoint(json.loads(gzip.decompress(member('book/checkpoint.json.gz'))))
    need((cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,524,'2020-01-31',17),'ACTUAL_FULL17_SAVED524')
    need(cp['run']['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),'ENTIRE_FULL17_INPUT_HASH')
    request=json.loads(member('request.json'));spec=json.loads(member('spec.json'))
    need(request['schema']=='research.system-campaign-accurate-resume-request/206' and request['financial_resume_authorized'] is True
         and request['selected_bounded_models']['P03']['root_admission_sha256']==ROOT,'ACTUAL_FIN340_FINANCIAL_SEED_DECLARATION')
    for name,h in request['sources'].items():need(sha((F/'producer/research/capital_risk'/name).read_bytes())==h,'CAPTURED_PRODUCER_SOURCE:'+name)
    need(cp['base']==spec['base'] and spec['root_admission_sha256']==ROOT and spec['measured_closes']==503,'ACTUAL_SELECTED_ROOT503')
    return root,members,member,cp,request,spec
def prepare():
    root,members,member,cp,request,spec=read_actual()
    receipt=json.loads((CAP/'public-receipt.json').read_bytes());summary=json.loads((CAP/'capture-review.json').read_bytes())
    archive=F/'connector-financial-P03-13525097150.zip';zraw=archive.read_bytes()
    need(len(zraw)==109007402 and sha(zraw)=='1717706bdcb7500aa20022f81f00a1d384e92a5592ad5fe99c1e509eafbeb169','EXACT_ACTUAL_TRANSPORT_ZIP')
    need(receipt['head']=='6ffac21270330a1cf5ce94fcb20acfd22c170421' and receipt['run_id']=='42259363025'
         and receipt['request_sha256']==sha(member('request.json')) and receipt['performance_admitted'] is False
         and summary['independently_root_admitted'] is False and summary['new_committed_sessions']==21,'AUTHENTICATED_PARTIAL_NOT_ADMITTED')
    target=deepcopy(json.loads((C/'system-campaign-financial-partials.json').read_bytes())['arms']['P03'])
    for key in ('base','repairs','journals'):target[key]=deepcopy(cp[key])
    target.update(artifact_id=13525097150,run_id=42259363025,head=receipt['head'],measured_closes=524,selected_session='2020-01-31',
        monthly_seed_root_admission_sha256=ROOT,outer_sha256=OUTER,inner_sha256=cp['run']['checkpoint_sha256'],state_sha256=cp['run']['state_sha256'],
        input_sha256=cp['run']['input_sha256'],source_binding_sha256=sha(member('source-bindings.json')),encrypted_output=receipt['encrypted_output'],
        receipt_sha256=sha((CAP/'public-receipt.json').read_bytes()),receipt_status=receipt['status'],request_sha256=sha(member('request.json')),
        original_request_member=members['request.json'],review_sha256=sha(member('stopped-review/core-review.json')),
        selected_file=members['book/checkpoint.json.gz'],zip_bytes=len(zraw),zip_sha256=sha(zraw),manifest=dict(member_count=209,raw_member_bytes=142622219),
        prior_stops={n:receipt[n] for n in ('preflight','worker','reviewer')},financial_authority=False,financial_predecessor_admitted=False,
        reuse_closed_hosted_prefix_review=True,complete_journals={n:members['book/'+n+'.jsonl'] for n in cp['journals']})
    with zipfile.ZipFile(archive) as z:
        names=z.namelist();asset=receipt['encrypted_output'];need(len(names)==len(set(names))==5,'EXACT_FIVE_ZIP_MEMBERS')
        target['public_members']={n:dict(bytes=len(z.read(n)),sha256=sha(z.read(n))) for n in names if n!=asset['name']}
        need(set(target['public_members'])=={'campaign-factual-P03.json','full-core-staging.json','ephemeral-runner-capacity.json','resume-export-qualification-P03.json'},'EXACT_PUBLIC_NAMES')
        need(z.read('campaign-factual-P03.json')==(CAP/'public-receipt.json').read_bytes(),'EXACT_PUBLIC_RECEIPT_BYTES')
    target['inspections']={}
    for name,phase,role,exitcode in [('parent-preflight/worker-inspect.json','preflight','preflight',0),('worker-inspect.json','worker','worker',1),('stopped-review/worker-inspect.json','review','reviewer',0)]:
        raw=member(name);v=json.loads(raw);need(v['Name']==f'/capital-system-resume-p03-{phase}-42259363025-1' and v['State']['ExitCode']==exitcode
            and v['State']['Running'] is v['State']['OOMKilled'] is False and v['Config']['User']=='1001:1001' and receipt[role]['exit_code']==exitcode,'EXACT_ACTUAL_STOP')
        target['inspections'][name]=dict(name=v['Name'],id=v['Id'],exit_code=exitcode,user='1001:1001',sha256=sha(raw),correlation_prefix_mounted=False)
    asts={}
    for name,functions in [('system_campaign_financial_resume.py',('preflight','economic','review','launch')),('system_campaign_financial_partial.py',('monthly_reproduction','retained_models','model_context','financial_inputs','retention_tree'))]:
        asts[name]={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/name).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in functions}
    fact=dict(schema='research.p03-FIN340-full17-readonly-reporting-fact/1',target=deepcopy(target),captured_request_sha256=sha(member('request.json')),
        captured_bounded_declaration=request['selected_bounded_models']['P03'],original_AST=asts,
        frozen_sources={n:sha((C/n).read_bytes()) for n in ('system_campaign_bounded_sensor_runtime_v2.py','system_campaign_p03_thor_runtime.py','system_campaign_p03_thor_qualification_reuse.py')},
        retained_rows=49,new_financial_rows=21,total_committed_proof_rows=70,root_admitted=False,readonly_reporting_only=True,
        financial_resume_authorized=False,actual_state_serialized=False,financial_transitions_reexecuted=0)
    for name,raw in [('P03-FIN340-full17-target.json',enc(target)),('P03-FIN340-full17-reporting-fact-v1.json',enc(fact)),('P03-FIN340-full17-reporting-source-request.json',member('request.json'))]:
        with (D/name).open('xb') as stream:stream.write(raw)
    print(json.dumps({n:dict(bytes=(D/n).stat().st_size,sha256=sha((D/n).read_bytes())) for n in ('P03-FIN340-full17-target.json','P03-FIN340-full17-reporting-fact-v1.json','P03-FIN340-full17-reporting-source-request.json')}))
if __name__=='__main__':prepare()
