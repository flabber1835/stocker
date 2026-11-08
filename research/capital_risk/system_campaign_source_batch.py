"""Bounded source evidence batches; no financial parent, book or transitions."""
import argparse,base64,csv,hashlib,io,json,os,subprocess,sys,zipfile
from dataclasses import asdict
from pathlib import Path
HERE=Path(__file__).parent
REQUEST='system-campaign-source-batch-request.json'
PARSER_SHA='5381b3b41b14cfc2f9d9d6e97c35929c9acc3d237d6df359a9ad7e6d0e4df7ec'
ACTIONS_SHA='ec6f1d96c0beed8bf4baba45a55cc56a881f001d27456b9630471d69e2d46139'
ACTIONS_BYTES=5322055

def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(value,reason):
    if not value:raise ValueError(reason)
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def save(path,value):
    with Path(path).open('xb') as stream:stream.write(encoded(value))

def validate(request):
    from datetime import date
    need(request['schema']=='research.source-evidence-batch-request/1'
        and request['financial_authority'] is request['input_adopted'] is False
        and request['maximum_parallel_financial_workers']==0
        and request['maximum_parallel_readonly_workers']==1,'SOURCE_BATCH_NO_FINANCIAL_AUTHORITY')
    need(1<=len(request['observations'])<=32 and 1<=len(request['native_groups'])<=8,'SOURCE_BATCH_BOUNDED_QUERY_COUNTS')
    names=[]
    for q in request['observations']+request['native_groups']:
        need(q['arm'] in ('P03','P05','P06','P07') and q['arm'] in request['admitted_context']
            and date.fromisoformat(q['session']).isoformat()==q['session']
            and request['admitted_context'][q['arm']]['through']<q['session']<='2026-07-31'
            and (q.get('ticker') is None or isinstance(q['ticker'],str) and 1<=len(q['ticker'])<=16)
            and (q.get('security_id') or q.get('ticker')),'SOURCE_BATCH_EXACT_FUTURE_QUERY_CONTEXT')
        names.append(q['name'])
    need(len(names)==len(set(names)) and all(n.replace('-','').isalnum() for n in names),'SOURCE_BATCH_UNIQUE_QUERY_NAMES')
    need(all(q.get('security_id') for q in request['native_groups']),'SOURCE_BATCH_NATIVE_PARENT_IDENTITY_REQUIRED')
    return True

def validate_files(request,driver=HERE):
    validate(request)
    for name,pin in request['sources'].items():
        need(Path(name).name==name and '/' not in name and '\\' not in name,'SOURCE_BATCH_PLAIN_SOURCE_FILENAMES')
        need(sha((Path(driver)/name).read_bytes())==pin,'SOURCE_BATCH_EXACT_DRIVER_SOURCE:'+name)
    need(request['sources'].get(Path(__file__).name)==sha(Path(__file__).read_bytes()),'SOURCE_BATCH_OWN_PRODUCER_PIN')
    from system_campaign_financial_partial import root_spec
    for arm,context in request['admitted_context'].items():
        spec=root_spec(arm,context['root_admission_sha256'])
        need(context['outer_sha256']==spec['outer_sha256'] and context['through']==spec['selected_session']
            and context['completed']==spec['measured_closes'] and context['input_sha256']==spec['input_sha256']
            and spec['base']['archive_sha256']==request['archive_sha256']
            and spec['base']['bundle_sha256']==request['bundle_sha256'],
            'SOURCE_BATCH_EXACT_ADMITTED_CAPTURE_CONTEXT_NOT_EVENT_DATE_ROLES')

def select_observations(queries,rows):
    found={q['name']:[] for q in queries}
    for row in rows:
        for q in queries:
            if row['session']==q['session'] and (q.get('ticker') is None or row['ticker']==q['ticker']) and (q.get('security_id') is None or row['security_id']==q['security_id']):
                found[q['name']].append(row)
    need(all(len(v)<=1 for v in found.values()),'SOURCE_BATCH_AMBIGUOUS_OBSERVATION_REFUSED')
    return [dict(query=q,status='FOUND' if found[q['name']] else 'NOT_FOUND',
        rows=[dict(source_row=r,source_row_sha256=digest(r)) for r in found[q['name']]],
        event_date_ownership='UNKNOWN_NOT_CAPTURED',financial_authority=False) for q in queries]

def select_actions(queries,rows):
    selected={q['name']:[] for q in queries}
    for row in rows:
        for q in queries:
            if row['effective_session']==q['session'] and row['security_id']==q['security_id']:
                selected[q['name']].append(row)
    need(all(len(v)<=8 for v in selected.values()),'SOURCE_BATCH_NATIVE_RECORD_BUDGET')
    return selected

def capture(request,out):
    from full_system_core import hosted
    hosted();need(str(Path(__file__).resolve()).startswith('/driver/'),'SOURCE_BATCH_HOSTED_DRIVER_ONLY')
    from research.pooled_input_support import inputs
    from research.bounded_20y import run
    validate_files(request);out=Path(out)
    need(sha(Path(run.__file__).read_bytes())==PARSER_SHA,'SOURCE_BATCH_UNCHANGED_ORIGINAL_PARSER')
    observations=[]
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw=archive.read('actions.csv.gz')
        need(len(raw)==ACTIONS_BYTES and sha(raw)==ACTIONS_SHA,'SOURCE_BATCH_ORIGINAL_RAW_ACTIONS_BYTES')
        selected=select_actions(request['native_groups'],inputs._archive_rows(archive,'actions.csv.gz'))
        for year in sorted({q['session'][:4] for q in request['observations']}):
            queries=[q for q in request['observations'] if q['session'].startswith(year+'-')]
            observations.extend(select_observations(queries,inputs._archive_rows(archive,'observations-'+year+'.csv.gz')))
    actions=inputs.load_actions(Path('/frozen/bundle'));groups=[]
    for q in request['native_groups']:
        rows=selected[q['name']];spin_rows=[r for r in rows if r['action'].lower() in ('spinoff','spinoffdividend')]
        spins=run.distributions(spin_rows) if spin_rows else {}
        terminals=[asdict(t) for t in actions.terminal.get(q['session'],()) if t.security_id==q['security_id']]
        groups.append(dict(query=q,status='FOUND' if rows else 'NOT_FOUND',
            raw_rows=[dict(row=r,sha256=digest(r)) for r in rows],
            original_typed_distributions=[asdict(t) for values in spins.values() for t in values],
            original_typed_terminals=terminals,event_date_ownership='UNKNOWN_NOT_CAPTURED',financial_authority=False))
    value=dict(schema='research.source-evidence-batch/1',request_sha256=sha(encoded(request)),
        producer_sha256=sha(Path(__file__).read_bytes()),original_parser_sha256=PARSER_SHA,
        archive_sha256=request['archive_sha256'],bundle_sha256=request['bundle_sha256'],
        admitted_context=request['admitted_context'],context_is_not_event_date_ownership=True,
        observations=sorted(observations,key=lambda v:v['query']['name']),native_groups=groups,
        financial_authority=False,input_adopted=False,financial_sessions_advanced=0,production_contacted=False)
    save(out/'source-evidence.json',value)
    print(json.dumps(dict(status='SOURCE_BATCH_CAPTURED',observations=len(observations),native_groups=len(groups),
        missing=[v['query']['name'] for v in observations+groups if v['status']=='NOT_FOUND'],financial_sessions_advanced=0)),flush=True)

def launch(request_path,staging,output):
    from probe import check_context
    from stage import SECRET,PROTOCOL,IMAGE
    from runtime_identity import EXECUTION_IMAGE
    from full_system_trials_job import command,inspect,seal
    from alpaca_fit_job import stopped_run,StopUnknown
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','SOURCE_BATCH_NO_BLIND_RERUN')
    request=json.loads(Path(request_path).read_bytes());validate_files(request)
    proof=json.loads(Path(staging).read_bytes())
    need(proof['status']=='STAGING_PASSED' and proof['run_id']==os.environ['GITHUB_RUN_ID']
        and proof['source_commit']==os.environ['GITHUB_SHA'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and proof['authenticated_before_parsing'] is proof['offline_image_source_verified'] is True
        and proof['runtime_index_config_layer_chain_verified'] is True and proof['replay_started'] is False,
        'SOURCE_BATCH_AUTHENTICATED_IMMUTABLE_INPUT_STAGE')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'SOURCE_BATCH_SEPARATE_KEY')
    os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
    frozen=Path(os.environ['RUNNER_TEMP'])/'capital-risk-stage-001/inputs';root=Path(os.environ['RUNNER_TEMP'])/'source-evidence-batch-output';root.mkdir(mode=0o700)
    save(root/'request.json',request)
    name='capital-full-core-b0-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
    values=command(name,frozen/'source-fixed',frozen,root,'economic')
    values[values.index('-B'):]=['-B','-u','/driver/system_campaign_source_batch.py','--mode','capture','--request','/driver/'+REQUEST]
    def inspector(actual,identity=None):
        v=inspect(actual,identity)
        need(v['Config']['Cmd']==values[values.index('-B'):],'SOURCE_BATCH_EXACT_SOURCE_ONLY_COMMAND')
        return v
    receipt=dict(schema='research.source-evidence-batch-receipt/1',run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha(Path(request_path).read_bytes()),protocol_sha256=request['protocol_sha256'],
        status='SOURCE_BATCH_RUNNING',financial_authority=False,input_adopted=False,financial_sessions_advanced=0)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    try:
        receipt['worker']=stopped_run(values,name,root,deadline=1200,inspector=inspector)
    except StopUnknown:
        receipt['status']='SOURCE_WORKER_UNKNOWN_NO_MUTABLE_EXPORT';save(output,receipt);raise
    s=receipt['worker'];need(s['stopped'] is True and type(s['exit_code']) is int,'SOURCE_BATCH_POSITIVE_STOP_BEFORE_EXPORT')
    receipt['status']='SOURCE_BATCH_CAPTURED' if s['exit_code']==0 and not s['oom_killed'] else 'SOURCE_BATCH_REFUSED_PRESERVED'
    receipt['encrypted_output']=seal(root,Path(output).with_suffix('.tar.crseal'),key,Path(request_path),'SOURCE_BATCH',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    save(output,receipt);print(json.dumps(receipt),flush=True)
    return 0 if receipt['status']=='SOURCE_BATCH_CAPTURED' else 2

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('capture','launch'),required=True);p.add_argument('--request',type=Path,required=True)
    p.add_argument('--staging',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    if a.mode=='capture':capture(json.loads(a.request.read_bytes()),Path('/out'))
    else:raise SystemExit(launch(a.request,a.staging,a.output))
if __name__=='__main__':main()
