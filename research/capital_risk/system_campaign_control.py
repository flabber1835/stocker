"""DATA-only campaign inventory, receipt classification and scheduling advice."""
import argparse,ast,csv,gzip,hashlib,io,json,os,sys,zipfile
from pathlib import Path
from collections import Counter
HERE=Path(__file__).parent
PROVIDER='P06-WWE-original-provider-SHARADAR_ACTIONS.zip'
PROVIDER_SHA='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
EVENT_ACTIONS={'acquisitionby','bankruptcyliquidation','regulatorydelisting','voluntarydelisting','spinoff','spinoffdividend','mergerto','delisted'}
FAMILIES={'spinoff':'DISTRIBUTION','spinoffdividend':'DISTRIBUTION','mergerto':'STOCK_OR_MIXED_CONSIDERATION',
 'acquisitionby':'CONSIDERATION_REVIEW','delisted':'EXIT_CLASSIFICATION',
 'bankruptcyliquidation':'UNKNOWN_COMMON_RIGHTS','regulatorydelisting':'UNKNOWN_COMMON_RIGHTS','voluntarydelisting':'UNKNOWN_COMMON_RIGHTS'}

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def accepted_status(driver=HERE):
    """Read existing admission metadata; never inspect or restore a strategy book."""
    driver=Path(driver);tree=ast.parse((driver/'system_campaign_financial_partial.py').read_bytes());maps={}
    for n in tree.body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('ADMISSIONS','COMPLETED_ADMISSIONS'):
            maps[n.targets[0].id]=ast.literal_eval(n.value)
    bundle=json.loads((driver/'system-campaign-financial-admitted-parents.json').read_bytes())
    original=json.loads((driver/'system-campaign-parallel-discovery-parents.json').read_bytes())['arms']
    rows=[]
    for arm in ('P'+str(i).zfill(2) for i in range(12)):
        if arm in ('P01','P02','P08') or arm in maps['COMPLETED_ADMISSIONS']:
            rows.append(dict(arm=arm,completed=2156,through='2026-07-31',complete=True));continue
        if arm in maps['ADMISSIONS']:
            pin=maps['ADMISSIONS'][arm];entry=bundle['arms'][arm]
            if entry['admission_sha256']!=pin:entry=bundle['historical_roots'][pin]
            a=entry['admission'];rows.append(dict(arm=arm,completed=a['completed'],through=a['source_cursor'],complete=False,root=pin))
        else:
            a=original[arm];rows.append(dict(arm=arm,completed=a['measured_closes'],through=a['selected_session'],complete=False))
    return rows

def classify_receipt(receipt):
    """A workflow color is insufficient; UNKNOWN and review/admission stay distinct."""
    def stopped(role):
        s=receipt.get(role)
        return isinstance(s,dict) and s.get('stopped') is True and type(s.get('exit_code')) is int and type(s.get('oom_killed')) is bool
    status=receipt.get('status','UNKNOWN')
    if 'UNKNOWN' in status:return dict(stage='UNKNOWN',admission_required=True,retry_authorized=False)
    if status=='SOURCE_BATCH_CAPTURED':
        s=receipt.get('worker',{})
        if not stopped('worker') or s.get('exit_code')!=0 or s.get('oom_killed') is not False:
            return dict(stage='UNKNOWN',admission_required=True,retry_authorized=False)
        return dict(stage='SOURCE_DATA_PENDING_INDEPENDENT_QUALIFICATION',admission_required=False,
            source_qualification_required=True,retry_authorized=False)
    for role in ('preflight','worker','reviewer'):
        if role in receipt and not stopped(role):return dict(stage='UNKNOWN',role=role,admission_required=True,retry_authorized=False)
        if stopped(role) and (receipt[role]['exit_code']!=0 or receipt[role]['oom_killed']):
            # A stopped worker may have a useful partial that its reviewer passes.
            if role=='worker' and not receipt[role]['oom_killed'] and stopped('reviewer') and receipt['reviewer']['exit_code']==0 and not receipt['reviewer']['oom_killed']:
                return dict(stage='REVIEWED_PARTIAL_PENDING_INDEPENDENT_ADMISSION',admission_required=True,retry_authorized=False)
            return dict(stage='FAILED_'+role.upper(),admission_required=True,retry_authorized=False)
    if status in ('COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT','PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'):
        return dict(stage=status,admission_required=True,retry_authorized=False)
    return dict(stage=status,admission_required=True,retry_authorized=False)

def qualified_profile(driver,record,accepted):
    if record.get('requires_owner_choice'):return False,'OWNER_CHOICE_REQUIRED'
    name=record.get('profile_qualification')
    if not name:return False,'EVENT_PROFILE_NOT_QUALIFIED'
    path=Path(name)
    if path.name!=name or '/' in name or '\\' in name:return False,'UNSAFE_PROFILE_REFERENCE'
    target=Path(driver)/name
    if not target.is_file():return False,'PROFILE_QUALIFICATION_MISSING'
    value=json.loads(target.read_bytes())
    if value.get('passed') is not True or value.get('financial_profile_ready') is not True or value.get('financial_authority') is not False or value.get('root_admission_sha256')!=accepted.get('root'):
        return False,'PROFILE_ROOT_OR_QUALIFICATION_MISMATCH'
    for n,pin in value['files'].items():
        if Path(n).name!=n or '/' in n or '\\' in n:return False,'UNSAFE_SOURCE_REFERENCE'
        p=Path(driver)/n
        if not p.is_file() or dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))!=pin:return False,'PROFILE_SOURCE_CHANGED'
    return True,'QUALIFIED_SOURCE_PROFILE_CANARY_REQUIRED_BEFORE_FINANCE'

def next_actions(driver,policy,active_arms=()):
    rows={r['arm']:r for r in accepted_status(driver)};ready=[];blocked=[]
    for record in policy['next_events']:
        arm=record['arm']
        if rows[arm]['complete']:continue
        if arm in active_arms:blocked.append(dict(arm=arm,reason='ACTIVE_JOB_NO_DUPLICATE'));continue
        passed,reason=qualified_profile(driver,record,rows[arm])
        (ready if passed else blocked).append(dict(arm=arm,reason=reason,event=record['event']))
    return dict(ready=ready[:4],blocked=blocked,automatic_launch_authority=False)

def provider_inventory(driver,policy):
    driver=Path(driver);raw=(driver/PROVIDER).read_bytes()
    if sha(raw)!=PROVIDER_SHA:raise ValueError('CONTROL_ORIGINAL_PROVIDER_BYTES_CHANGED')
    accepted=accepted_status(driver);unfinished={r['arm']:r for r in accepted if not r['complete']};first=min(r['through'] for r in unfinished.values());groups={}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream,encoding='utf8',newline='')):
                    if row['action'] not in EVENT_ACTIONS or not first<row['date']<='2026-07-31':continue
                    key=row['date'],row['ticker'];group=groups.setdefault(key,dict(provider_date=row['date'],ticker=row['ticker'],source_rows=[]))
                    group['source_rows'].append(dict(row=row,row_digest=sha(json.dumps(row,sort_keys=True,separators=(',',':')).encode())))
    records=[]
    for key,value in sorted(groups.items()):
        value['potentially_affected_arms']=[a for a,r in unfinished.items() if r['through']<value['provider_date']]
        value['research_families']=sorted({FAMILIES[v['row']['action']] for v in value['source_rows']})
        value['frozen_security_identity']=value['legal_terms']=value['event_date_ownership']=value['runtime_qualification']='UNKNOWN'
        value['financial_authority']=False;records.append(value)
    return dict(schema='research.full-remaining-provider-event-inventory/1',provider_file=PROVIDER,provider_sha256=PROVIDER_SHA,
        provider_dates_are_not_legal_or_native_recognition_clocks=True,scope='ALL_PROVIDER_CANDIDATES_NOT_FUTURE_HOLDING_PREDICTIONS',
        accepted=accepted,next_events=policy['next_events'],groups=len(records),raw_rows=sum(len(v['source_rows']) for v in records),
        families=dict(Counter(f for v in records for f in v['research_families'])),events=records,
        full_frozen_native_event_coverage_verified=False,financial_authority=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('status','inventory','classify'));p.add_argument('--driver',type=Path,default=HERE)
    p.add_argument('--state',type=Path);p.add_argument('--receipt',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    policy=json.loads((args.driver/'system-campaign-control-policy.json').read_bytes())
    if args.mode=='inventory':value=provider_inventory(args.driver,policy)
    elif args.mode=='classify':value=classify_receipt(json.loads(args.receipt.read_bytes()))
    else:
        state=json.loads(args.state.read_bytes()) if args.state else {};active=state.get('active_runs',[]);rows=accepted_status(args.driver)
        value=dict(accepted=rows,verified_sessions=sum(r['completed'] for r in rows),required_sessions=25872,
            completed_variants=sum(r['complete'] for r in rows),active_runs=[{k:r.get(k) for k in ('arm','run_id','status')} for r in active],
            **next_actions(args.driver,policy,{r.get('arm') for r in active}))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        if args.mode=='inventory':
            event_file=args.output.with_name(args.output.stem+'.events.json.gz')
            packed=gzip.compress(encoded(dict(schema='research.provider-event-records/1',events=value.pop('events'))),mtime=0)
            event_tmp=event_file.with_name(event_file.name+'.tmp')
            with event_tmp.open('xb') as f:f.write(packed)
            os.replace(event_tmp,event_file)
            value.update(events_file=event_file.name,events_file_sha256=sha(packed),events_file_bytes=len(packed))
        temporary=args.output.with_name(args.output.name+'.tmp')
        with temporary.open('xb') as f:f.write(encoded(value))
        os.replace(temporary,args.output)
        print(json.dumps({k:v for k,v in value.items() if k not in ('events','accepted','next_events')}))
    else:print(json.dumps(value))
if __name__=='__main__':main()
