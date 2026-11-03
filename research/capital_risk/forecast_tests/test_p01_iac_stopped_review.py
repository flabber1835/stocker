"""Review-only source/metadata/stub crypto; no actual financial payloads."""
import ast,base64,gzip,hashlib,importlib.util,io,json,os,subprocess,sys,tarfile,zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace,ModuleType
import pytest,yaml
HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_stopped_review_target as target
import p01_iac_stopped_review_transport as transport
import p01_iac_stopped_review_export as export
import p01_iac_stopped_review_job as job
import p01_iac_stopped_review_run as runtime
import p01_iac_namespace_export as oldexport


def receipt():
    old=target.target()['original']
    return dict(schema=export.SCHEMA,stage=export.STAGE,run_id='123',head='a'*40,request_sha256='b'*64,source_count=524,
      protocol_sha256=old['financial_protocol_sha256'],target_run_id=old['run_id'],target_head=old['head'],target_request_sha256=old['request_sha256'],target_source_count=515,
      target_sha256=target.TARGET_SHA,status='REVIEW_NOT_STARTED',production_contacted=False,financial_authority=False,financial_resume_authorized=False,original_review_exit_code=1,output_exported=False)


def inspection(role,spec=None,name=None,cmd=None):
    spec=spec or target.target();old=spec['original'];code=0 if role!='review' else 1
    name=name or f'capital-system-p01-iac-namespace-{role}-{old["run_id"]}-1'
    mode={'qualify':'qualify','worker':'economic','review':'review'}[role]
    return dict(Name='/'+name,Id=old['actual_inspection_ids'][role],Image=transport.EXECUTION_IMAGE,
      State=dict(Running=False,OOMKilled=False,ExitCode=code),HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
      Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in transport.RO|{'/out'}],Config=dict(User='1001:1001',WorkingDir='/variant',
      Cmd=cmd or ['-B','-u','/driver/p01_iac_namespace_run.py','--mode',mode,'--spec','/out/spec.json'],Env=['FULL_SYSTEM_HOSTED=1'],
      Labels={'research.study':'full-system-search-20261029','research.role':'review' if role=='review' else 'worker'}))


def test_real_closed_target_and_separate_original_public_domains():
    value=target.target();assert target.sha(target.encoded(value))==target.TARGET_SHA
    assert value['public_members']['p01-iac-namespace.json']['sha256']==value['original']['receipt']['captured_copy']['sha256']
    assert value['original']['manifests']['qualification']['original_manifest_sha256']!=value['original']['manifests']['qualification']['captured_metadata_copy']['sha256']
    for key,bad in [('financial_authority',True),('root_review_only_authorized',False),('extra',{})]:
        wrong=deepcopy(value);wrong[key]=bad
        with pytest.raises(ValueError):target.check_target(wrong)


@pytest.mark.parametrize('field,bad',[('source_count',True),('run_id',None),('head',7),('target_run_id',True),('target_source_count',515.0),('request_sha256',{}),('review_log_copy_failed','false')])
def test_public_receipt_closed_scalar_identity_types(field,bad,tmp_path):
    value=receipt();value[field]=bad
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',value)


def test_marker_actual_crypto_in_new_stage(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_bytes(target.encoded(dict(protocol_sha256='c'*64)))
    value=export.qualify_export(tmp_path/'marker',request)
    assert value['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED' and value['source_adapter_sha256']==job.sha256_file(Path(export.__file__))


@pytest.mark.parametrize('kind',['duplicate','root','writable','network','wrongcmd','id','oom','unknown'])
def test_original_actual_stop_and_all_eight_fences(kind):
    spec=target.target();value=inspection('review',spec);transport.original_stop(value,'review',spec)
    if kind=='duplicate':value['Mounts'].append(deepcopy(value['Mounts'][0]))
    if kind=='root':value['Config']['User']='0:0'
    if kind=='writable':next(v for v in value['Mounts'] if v['Destination']=='/evidence')['RW']=True
    if kind=='network':value['HostConfig']['NetworkMode']='bridge'
    if kind=='wrongcmd':value['Config']['Cmd'][2]='/driver/wrong.py'
    if kind=='id':value['Id']='a'*64
    if kind=='oom':value['State']['OOMKilled']=True
    if kind=='unknown':value['State']['Running']=True
    with pytest.raises(ValueError):transport.original_stop(value,'review',spec)


def test_report_only_output_allowlist_and_known_partial_repair(tmp_path,monkeypatch):
    spec=target.target();name=next(n for n in spec['review_context_files'] if n.startswith('contexts/book/repairs/'))
    path=tmp_path/name;path.parent.mkdir(parents=True);path.write_bytes(b'incomplete declared input copy')
    assert name in export.output_inventory(tmp_path,spec,success=False)
    with pytest.raises(ValueError):export.output_inventory(tmp_path,spec,success=True)
    bad=tmp_path/'book/checkpoint.json.gz';bad.parent.mkdir();bad.write_bytes(b'forbidden book')
    with pytest.raises(ValueError):export.output_inventory(tmp_path,spec)


def test_unknown_never_seals_and_known_stop_report_only_crypto(tmp_path,monkeypatch):
    from seal import decrypt
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    out=tmp_path/'out';out.mkdir();(out/'worker.log').write_bytes(b'SYNTHETIC_STOPPED_LOG')
    request=tmp_path/'request.json';request.write_bytes(target.encoded(dict(protocol_sha256='c'*64)))
    public=tmp_path/'public/receipt.json';public.parent.mkdir();value=receipt()
    export.finish(value,out,public,b'x'*32,request,known=False);assert not value['output_exported'] and 'review_encrypted_output' not in value
    value['reviewer']=dict(stopped=True,exit_code=1,oom_killed=False,wait_error=None)
    export.finish(value,out,public,b'x'*32,request,known=True);assert value['output_exported']
    asset=value['review_encrypted_output'];plain=tmp_path/'plain.tar.gz';decrypt(public.parent/asset['name'],plain,b'x'*32,asset['sha256'])
    with tarfile.open(plain,mode='r:gz') as tar:
        manifest=json.loads(tar.extractfile('manifest.json').read())
        assert manifest['stage']==export.STAGE and set(manifest['members'])=={'worker.log','review-output-scope.json'}
        assert not any(n.startswith('book/') for n in manifest['members'])


def test_actual_fixed_cli_rejects_financial_modes_before_first_io(tmp_path):
    for mode in ('qualify','economic'):
        result=subprocess.run([sys.executable,'-B',str(HERE/'p01_iac_stopped_review_run.py'),'--mode',mode,'--spec','/out/spec.json'],capture_output=True,text=True,timeout=30)
        assert result.returncode==2 and 'unrecognized arguments' in result.stderr


def test_actual_commands_and_workflow_report_only_bounded(monkeypatch):
    import full_system_benchmark as common
    monkeypatch.setattr(common.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(common.os,'getgid',lambda:1001,raising=False)
    values=job.worker_command('capital-system-p01-stopped-review-review-123-1',Path('/source'),Path('/frozen'),Path('/out'),Path('/old'),Path('/quote'),Path('/evidence'))
    assert values[values.index('-B'):]==job.entrypoint() and '--mode' not in job.entrypoint()
    binds=[values[i+1] for i,v in enumerate(values) if v=='--mount'];assert len(binds)==8 and any('target=/evidence,readonly' in v for v in binds)
    value=yaml.safe_load((HERE.parents[1]/'.github/workflows'/job.WORKFLOW).read_bytes());steps=value['jobs']['iac-stopped-review']['steps']
    assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,90,5] and sum(s['timeout-minutes'] for s in steps)<=115
    assert 'qualification.tar.crseal' not in steps[-1]['with']['path'] and 'financial.tar.crseal' not in steps[-1]['with']['path']


def synthetic_archive(tmp_path,monkeypatch,*,damage=False):
    spec=deepcopy(target.target());old=spec['original'];key=b'x'*32
    monkeypatch.setenv('GITHUB_RUN_ID',str(old['run_id']));monkeypatch.setenv('GITHUB_SHA',old['head'])
    raw_request=(HERE/old['request_file']).read_bytes();request=json.loads(raw_request)
    public={};files={};q={n:b'SYNTHETIC_OPAQUE_PROOF' for n in ['spec.json','request.json','source-map.json','source-bindings.json']}
    q['request.json']=raw_request;q['spec.json']=b'SYNTHETIC_SPEC'
    q.update({'qualification/'+n:b'SYNTHETIC_OPAQUE_PROOF' for n in oldexport.QUALIFICATION_FILES})
    q['qualification/worker-inspect.json']=target.encoded(inspection('qualify',spec));q['qualification/worker.log']=b'SYNTHETIC_Q_LOG'
    f=dict(q);f.update({'worker-inspect.json':target.encoded(inspection('worker',spec)),
       'stopped-review/worker-inspect.json':target.encoded(inspection('review',spec)),
       'book/checkpoint.json.gz':b'\x1f\x8bOPAQUE_INVALID_CP_MUST_NOT_PARSE','book/daily.jsonl':b'{incomplete opaque'})
    for role,members,assetkey,stage in (('qualification',q,'qualification_encrypted_output',oldexport.QUALIFICATION_STAGE),('financial',f,'encrypted_output',oldexport.STAGE)):
        root=tmp_path/role;root.mkdir()
        for n,raw in members.items():p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        destination=tmp_path/old['assets'][assetkey]['name'];asset=oldexport.sealed(root,destination,key,HERE/old['request_file'],stage=stage)
        old['assets'][assetkey]=asset;files[asset['name']]=destination.read_bytes()
        inventory={n:dict(bytes=len(raw),sha256=target.sha(raw)) for n,raw in members.items()}
        m=dict(schema='research.full-system-output/1',stage=stage,arm='P01',run_id=str(old['run_id']),head=old['head'],request_sha256=old['request_sha256'],protocol_sha256=old['financial_protocol_sha256'],compression='TAR_GZIP_V1',members=inventory)
        raw=(json.dumps(m,sort_keys=True)+'\n').encode();assert target.sha(raw)==asset['manifest_sha256']
        old['manifests'][role]=dict(original_manifest_bytes=len(raw),original_manifest_sha256=asset['manifest_sha256'],member_count=len(inventory),raw_member_bytes=sum(e['bytes'] for e in inventory.values()),inventory_sha256=target.digest(inventory))
    pubreceipt=dict(schema=old['receipt']['schema'],stage=old['receipt']['stage'],status='FINANCIAL_SUFFIX_REVIEW_REFUSED_PRESERVED',run_id=str(old['run_id']),head=old['head'],request_sha256=old['request_sha256'],production_contacted=False,qualification_exported=True,encrypted_output_exported=True,**old['assets'],**old['stops'])
    marker=dict(status='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED',request_sha256=old['request_sha256'],source_adapter_sha256=request['sources']['p01_iac_namespace_export.py'])
    public['p01-iac-namespace-export-qualification.json']=target.encoded(marker);pubreceipt['export_qualification_sha256']=target.sha(public['p01-iac-namespace-export-qualification.json'])
    public['p01-iac-namespace.json']=target.encoded(pubreceipt)
    for name in ('ephemeral-runner-capacity.json','full-core-staging.json','p01-iac-namespace-phase.json'):public[name]=b'{"synthetic_only":true}'
    spec['public_members']={n:dict(bytes=len(raw),sha256=target.sha(raw)) for n,raw in public.items()};files.update(public)
    if damage:
        n=old['assets']['encrypted_output']['name'];files[n]=files[n][:-1]+bytes([files[n][-1]^1])
    archive=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
        for n,raw in files.items():z.writestr(n,raw)
    monkeypatch.setattr(transport,'check_target',lambda value:value)
    original_read=transport.read
    monkeypatch.setattr(transport,'read',lambda path,*args: b'SYNTHETIC_SPEC' if Path(path)==HERE/request['source_financial_file'] else original_read(path,*args))
    original_hash=transport.sha256_file
    monkeypatch.setattr(transport,'sha256_file',lambda path:request['sources'][Path(path).name] if Path(path).parent==HERE and Path(path).name in request['sources'] else original_hash(path))
    monkeypatch.setattr(transport,'validate_prepared_receipt',lambda *a,**k:None)
    return archive,spec,key


def test_real_two_tag_crypto_before_any_private_control_and_full_opaque_inventory(tmp_path,monkeypatch):
    archive,spec,key=synthetic_archive(tmp_path,monkeypatch);tags=[];extracted=[];authenticate=transport.crypto.authenticate;extract=transport.extract;plain=transport.plain
    def tagged(z,asset,key):value=authenticate(z,asset,key);tags.append(asset['name']);return value
    def extraction(*a,**k):assert len(tags)==2;value=extract(*a,**k);extracted.append(value);return value
    def parse(raw):
        assert len(tags)==2 and b'OPAQUE_INVALID_CP' not in raw
        value=plain(raw)
        if value.get('schema')!='research.full-system-output/1':assert len(extracted)==2
        return value
    monkeypatch.setattr(transport.crypto,'authenticate',tagged);monkeypatch.setattr(transport,'extract',extraction);monkeypatch.setattr(transport,'plain',parse)
    dest=tmp_path/'authenticated';dest.mkdir()
    with zipfile.ZipFile(archive) as z:auth=transport.unpack(z,key,dest,spec)
    assert len(tags)==len(extracted)==2 and not auth['financial_payloads_parsed']
    transport.verify_tree(dest/'financial',spec,auth)
    (dest/'financial/book/daily.jsonl').write_bytes(b'changed')
    with pytest.raises(ValueError):transport.verify_tree(dest/'financial',spec,auth)


def test_wrong_second_gcm_refuses_before_any_private_json(tmp_path,monkeypatch):
    archive,spec,key=synthetic_archive(tmp_path,monkeypatch,damage=True)
    monkeypatch.setattr(transport,'plain',lambda *a:pytest.fail('private JSON before both tags'))
    dest=tmp_path/'authenticated';dest.mkdir()
    with zipfile.ZipFile(archive) as z:
        with pytest.raises(Exception):transport.unpack(z,key,dest,spec)
    assert list(dest.iterdir())==[]


@pytest.fixture
def flat(tmp_path,monkeypatch):
    folder=tmp_path/'driver';folder.mkdir()
    for name in job.SOURCES:(folder/name).write_bytes((HERE/name).read_bytes())
    (folder/'system-campaign-search-protocol.json').write_bytes((HERE/'system-campaign-search-protocol.json').read_bytes())
    seen=set()
    def patch(module):
        if id(module) in seen:return
        seen.add(id(module))
        if hasattr(module,'HERE'):monkeypatch.setattr(module,'HERE',folder)
        for key in ('previous','predecessor'):
            child=getattr(module,key,None)
            if isinstance(child,ModuleType):patch(child)
    patch(job);patch(target)
    import p01_iac_unit_contract as oldcontract,p01_iac_reference_evidence as oldevidence
    patch(oldcontract);patch(oldevidence)
    value=job.expected_request();path=folder/job.REQUEST;path.write_bytes(target.encoded(value));copy=folder/'out-request.json';copy.write_bytes(path.read_bytes())
    original=job.read;monkeypatch.setattr(job,'read',lambda p,*args:original(copy,*args) if str(p)=='/out/request.json' else original(p,*args))
    return folder,path,copy,value


def test_actual_flat_request_old515_and_new_execution_envelopes(flat):
    folder,path,copy,value=flat
    assert len(value['sources'])==len(job.SOURCES) and value['target_source_count']==515
    assert value['target_request_sha256']==job.PRIOR_SHA and value['execution_role']=='READ_ONLY_STOPPED_EVIDENCE_REVIEW'
    assert 'maximum_financial_transitions' not in value and value['qualification_or_financial_replay_authorized'] is False
    assert not (folder.parents[1]/'.github/workflows').exists()
    assert job.validate_worker_request(path)==value
    prior=json.loads((folder/job.PRIOR).read_bytes())
    assert len(prior['sources'])==515 and all(value['sources'][n]==h for n,h in prior['sources'].items())


def test_new_raw_request_copy_and_guard_removal_falsifier(flat,monkeypatch):
    folder,path,copy,value=flat;bad=deepcopy(value);bad['execution_role']='FINANCIAL_STARTUP_FORBIDDEN'
    path.write_bytes(target.encoded(bad));copy.write_bytes(path.read_bytes())
    monkeypatch.setattr(job,'expected_request',lambda:value)
    with pytest.raises(ValueError):job.validate_worker_request(path)
    fn=next(n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_worker_request')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='STOPPED_REVIEW_ENTIRE_NEW_REQUEST_FLAT_CLOSURE_AND_RAW_COPY_FIRST' for x in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(job));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-new-request-domain>','exec'),ns)
    assert ns['validate_worker_request'](path)==value


def main_fixture(tmp_path,monkeypatch,case):
    events=[];public=tmp_path/'public/receipt.json';request=dict(protocol_sha256='c'*64,sources={'synthetic.py':'a'*64},capacity_source_sha256='d'*64,
      quote_descriptor={},initial_min_disk_bytes=1,preworker_min_disk_bytes=1,preworker_min_memory_bytes=1,review_wait_seconds=1800)
    raw=tmp_path/'request.json';raw.write_bytes(target.encoded(request))
    for n in ('capacity','staging'):(tmp_path/(n+'.json')).write_bytes(b'{}')
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('RUNNER_TEMP',str(tmp_path));monkeypatch.setenv(job.SECRET,base64.b64encode(b'x'*32).decode())
    monkeypatch.setattr(job,'expected_request',lambda:request)
    for name in ('check_context','validate_prepared_receipt','stage_valid'):monkeypatch.setattr(job.previous,name,lambda *a,**k:None)
    monkeypatch.setattr(job,'qualify_export',lambda *a:events.append('marker') or {'synthetic_only':True})
    def auth(spec,root,key):
        events.append('target')
        if case=='auth_refusal':raise ValueError('REFUSED_SYNTHETIC_TARGET')
        q,f=root/'q',root/'f';q.mkdir(parents=True);f.mkdir();return SimpleNamespace(qualification_root=q,financial_root=f,authentication={'synthetic_only':True})
    monkeypatch.setattr(job,'authenticate',auth)
    def old(root,key,spec):events.append('old');root.mkdir();return root
    monkeypatch.setattr(job.previous,'admit',old)
    def capsule(descriptor,path,**k):events.append('quote');path.mkdir()
    monkeypatch.setattr(job.previous,'authenticate_capsule',capsule)
    def source(*a):
        events.append('source');one=tmp_path/'original';two=tmp_path/'variant';one.mkdir();two.mkdir();return one,two
    monkeypatch.setattr(job.previous,'reconstruct',source);monkeypatch.setattr(job.previous,'freeze',lambda p:None);monkeypatch.setattr(job.previous,'resources',lambda *a:None)
    monkeypatch.setattr(job,'worker_command',lambda name,src,frozen,out,old,capsule,evidence: job.entrypoint())
    def stopped(cmd,name,out,**k):
        events.append('review');assert cmd==job.entrypoint() and k['deadline']==1800
        if case=='unknown':raise job.StopUnknown('SYNTHETIC_UNKNOWN')
        (out/'worker.log').write_bytes(b'SYNTHETIC');(out/'worker-inspect.json').write_bytes(b'{}')
        if case!='review_refusal':
            report=out/'iac-unit-financial-review.json';report.write_bytes(b'SYNTHETIC_OPAQUE_REPORT')
            link=dict(schema='research.p01-stopped-review-result-link/1',adapter_sha256=runtime.ADAPTER_SHA,execution_request_sha256=job.sha256_file(raw),
              target_request_sha256='0'*64 if case=='bad_link' else target.target()['original']['request_sha256'],
              report=dict(bytes=report.stat().st_size,sha256=job.sha256_file(report)),review_returned_without_exception=True,financial_authority=False)
            (out/'review-result-link.json').write_bytes(target.encoded(link))
        return dict(stopped=True,exit_code=1 if case=='review_refusal' else 0,oom_killed=False,wait_error=None)
    monkeypatch.setattr(job,'stopped_run',stopped)
    saved=[]
    def finish(value,*a,known):events.append('finish');value['output_exported']=known;saved.append((deepcopy(value),known))
    monkeypatch.setattr(job,'finish',finish)
    return SimpleNamespace(request=raw,capacity=tmp_path/'capacity.json',staging=tmp_path/'staging.json',output=public),events,saved


@pytest.mark.parametrize('case',['success','unknown','review_refusal','bad_link','auth_refusal'])
def test_actual_main_one_review_order_no_replay_and_truthful_final_phase(case,tmp_path,monkeypatch):
    args,events,saved=main_fixture(tmp_path,monkeypatch,case)
    with pytest.raises(SystemExit) as end:job.main(args)
    assert end.value.code==(0 if case=='success' else 2)
    assert events.index('marker')<events.index('target') and events.count('review')<=1
    if 'old' in events:assert events.index('target')<events.index('old')<events.index('quote')<events.index('source')<events.index('review')
    assert saved[0][1] is (case not in ('unknown','auth_refusal'))
    phase=json.loads((args.output.parent/'p01-iac-stopped-review-phase.json').read_bytes())['phase']
    assert phase==('EXPORTED' if saved[0][1] else 'FINISHED_NO_EXPORT')
    assert saved[0][0]['original_review_exit_code']==1 and saved[0][0]['target_request_sha256']==job.PRIOR_SHA


def test_actual_main_target_link_guard_removal_falsifier(tmp_path,monkeypatch):
    args,events,saved=main_fixture(tmp_path,monkeypatch,'bad_link')
    fn=next(n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='STOPPED_REVIEW_FRESH_REPORT_LINK_AFTER_ACTUAL_STOP_ZERO' for x in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(job));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-target-execution-link>','exec'),ns)
    with pytest.raises(SystemExit) as end:ns['main'](args)
    assert end.value.code==0


def test_undeclared_empty_book_directory_is_not_silently_filtered(tmp_path):
    (tmp_path/'book').mkdir()
    with pytest.raises(ValueError,match='PARENT_DIRECTORIES'):export.output_inventory(tmp_path,target.target())


@pytest.mark.parametrize('fail_gate',[False,True])
def test_actual_worker_new_request_then_tree_before_single_readonly_adapter(fail_gate,tmp_path,monkeypatch):
    events=[];out=tmp_path/'out';out.mkdir();driver=tmp_path/'driver';driver.mkdir();evidence=tmp_path/'evidence';evidence.mkdir()
    spec=target.target();(driver/target.TARGET).write_bytes(target.encoded(spec));(out/'target.json').write_bytes((driver/target.TARGET).read_bytes())
    request=driver/runtime.REQUEST;request.write_bytes(b'SYNTHETIC_NEW_REVIEW_REQUEST')
    (driver/'old-spec.json').write_bytes(b'SYNTHETIC_OLD628_SPEC');(out/'spec.json').write_bytes(b'SYNTHETIC_OLD628_SPEC')
    (out/'review-authentication.json').write_bytes(b'{"synthetic_only":true}')
    execution=dict(schema='research.p01-stopped-evidence-review-execution/1',request_sha256=job.sha256_file(request),source_count=1,
        target_request_sha256=spec['original']['request_sha256'],financial_authority=False,qualification_or_financial_replay_authorized=False)
    (out/'review-execution.json').write_bytes(target.encoded(execution))
    def gate(path):
        events.append('new_request')
        if fail_gate:raise ValueError('REFUSED_SYNTHETIC_NEW_REQUEST')
        return {'sources':{'synthetic.py':'a'*64}}
    monkeypatch.setattr(job,'validate_worker_request',gate)
    monkeypatch.setattr(transport,'verify_tree',lambda *a:events.append('entire_target_tree'))
    core=ModuleType('full_system_core');core.hosted=lambda:events.append('hosted')
    old=ModuleType('p01_iac_unit_contract');old.SPEC='old-spec.json';old.specification=lambda:{'synthetic_only':True}
    adapter=ModuleType('p01_iac_namespace_review_recovery');module=tmp_path/'adapter.py';module.write_bytes(b'SYNTHETIC_ADAPTER');adapter.__file__=str(module)
    def review(specification,output,source):
        events.append('review_only');assert output==out and source==evidence
        with (output/'iac-unit-financial-review.json').open('xb') as stream:stream.write(b'SYNTHETIC_REPORT_CREATED_ONCE')
        return dict(reference_reuse_review=dict(actual_new_request_sha256=spec['original']['request_sha256'],actual_new_driver_source_count=515),qualification_state_adopted=False,financial_predecessor_admitted=False)
    adapter.review=review
    for name,value in [('full_system_core',core),('p01_iac_unit_contract',old),('p01_iac_namespace_review_recovery',adapter)]:monkeypatch.setitem(sys.modules,name,value)
    original=Path
    def mapped(value):
        value=str(value)
        if value=='/out':return out
        if value=='/out/spec.json':return out/'spec.json'
        if value=='/evidence':return evidence
        return original(value)
    monkeypatch.setattr(runtime,'Path',mapped);monkeypatch.setattr(runtime,'HERE',driver);monkeypatch.setattr(runtime,'ADAPTER_SHA',job.sha256_file(module))
    if fail_gate:
        with pytest.raises(ValueError,match='NEW_REQUEST'):runtime.main(SimpleNamespace(spec=out/'spec.json'))
        assert events==['new_request'] and not (out/'iac-unit-financial-review.json').exists()
    else:
        assert runtime.main(SimpleNamespace(spec=out/'spec.json'))==0
        assert events==['new_request','hosted','entire_target_tree','review_only']
        link=json.loads((out/'review-result-link.json').read_bytes());assert link['target_request_sha256']==spec['original']['request_sha256']
        assert (out/'iac-unit-financial-review.json').read_bytes()==b'SYNTHETIC_REPORT_CREATED_ONCE' and not (out/'book').exists()


def test_review_entry_source_has_no_qualifier_financial_or_advance_call_and_mutation_falsifier():
    raw=Path(runtime.__file__).read_bytes()
    def validate(raw):
        tree=ast.parse(raw);calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
        assert not any(name in ('qualify','economic','branch','backtest.main','runtime.advance','advance_session') for name in calls)
        assert sum(name=='adapter.review' for name in calls)==1
    validate(raw)
    bad=raw+b'\nruntime.advance()\n'
    with pytest.raises(AssertionError):validate(bad)


@pytest.mark.parametrize('status,exit_code,successful',[
    ('STOPPED_EVIDENCE_READONLY_REVIEW_PASSED_PENDING_CLIENT',0,True),
    ('STOPPED_EVIDENCE_READONLY_REVIEW_REFUSED_PRESERVED',0,False),
    ('STOPPED_EVIDENCE_READONLY_REVIEW_REFUSED_PRESERVED',1,False)])
def test_known_stop_scope_success_requires_both_zero_and_host_link_pass(status,exit_code,successful,tmp_path,monkeypatch):
    root=tmp_path/'out';root.mkdir()
    required={'request.json','target.json','spec.json','review-authentication.json','review-execution.json',
      'iac-unit-financial-review.json','review-result-link.json','worker-inspect.json','worker.log'}
    for name in required:(root/name).write_bytes(b'SYNTHETIC_REVIEW_ONLY_OUTPUT')
    request=tmp_path/'request.json';request.write_bytes(target.encoded({'protocol_sha256':'c'*64}))
    value=receipt();value['status']=status;value['reviewer']=dict(stopped=True,exit_code=exit_code,oom_killed=False,wait_error=None)
    seen=[]
    def sealed(source,destination,key,request):
        scope=json.loads((source/'review-output-scope.json').read_bytes());seen.append(scope)
        assert set(scope['members'])==required
        return dict(name=export.CIPHER,bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(export,'sealed',sealed)
    export.finish(value,root,tmp_path/'receipt.json',b'x'*32,request,known=True)
    assert value['output_exported'] is True and len(seen)==1
    assert seen[0]['successful_repair_copy_checks'] is successful
    assert seen[0]['all_failure_fragments_unadmitted'] is (not successful)
    assert seen[0]['reviewer_stop']['exit_code']==exit_code


def hydrated_review_layout(tmp_path):
    """Use the exact frozen copy helper, including its otherwise empty mkdir."""
    helper=(HERE/'system_campaign_discovery_inputs.py').read_bytes()
    assert hashlib.sha256(helper).hexdigest()=='25ef331e425c22aab0d42b0d470946a9539e05aeaca8e5a91874f70558ea0d28'
    node,=[n for n in ast.parse(helper).body if isinstance(n,ast.FunctionDef) and n.name=='preserve_input_documents']
    namespace=dict(Path=Path,hashlib=hashlib,need=export.need)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-frozen-input-copy-helper>','exec'),namespace)
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True)
    descriptors=[]
    for i in range(8):
        raw=target.encoded(dict(schema='terminal-repair/1',synthetic_only=True,index=i))
        h=hashlib.sha256(raw).hexdigest();name=h+'.json';(old/'book/repairs'/name).write_bytes(raw)
        descriptors.append(dict(filename=name,sha256=h))
    out=tmp_path/'review-output';out.mkdir()
    namespace['preserve_input_documents'](old,dict(repairs=descriptors),out/'contexts')
    for name in ('discovery-fnf-hydration.json','discovery-distribution-hydration.json'):
        (out/'contexts'/name).write_bytes(target.encoded(dict(synthetic_only=True,kind=name)))
    context={p.relative_to(out).as_posix():dict(bytes=p.stat().st_size,sha256=job.sha256_file(p))
             for p in (out/'contexts').rglob('*') if p.is_file()}
    for name in ('request.json','target.json','spec.json','review-authentication.json','review-execution.json',
                 'iac-unit-financial-review.json','review-result-link.json','worker-inspect.json','worker.log'):
        (out/name).write_bytes(target.encoded(dict(synthetic_only=True,kind=name)))
    return out,dict(review_context_files=context)


def test_actual_hydration_layout_old_fails_new_complete_export_passes(tmp_path,monkeypatch):
    out,spec=hydrated_review_layout(tmp_path)
    empty=out/'contexts/book/predecessor-checkpoints';assert empty.is_dir() and not any(empty.iterdir())
    raw=subprocess.check_output(['git','show','b7baa688fd754b99c46b9f3c3c80410909f77ab1:research/capital_risk/p01_iac_stopped_review_export.py'])
    assert hashlib.sha256(raw).hexdigest()=='aba0f05ac9175f77e4b78fbbeab46669bbf675698733b90f203c2d8c2cc127dd'
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='output_inventory']
    namespace=dict(vars(export));exec(compile(ast.Module(body=[node],type_ignores=[]),'<published-export-inventory>','exec'),namespace)
    with pytest.raises(ValueError,match='ONLY_DECLARED_OUTPUT_PARENT_DIRECTORIES'):
        namespace['output_inventory'](out,spec,success=True)
    inventory=export.output_inventory(out,spec,success=True)
    assert set(inventory)=={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
    request=tmp_path/'execution-request.json';request.write_bytes(target.encoded(dict(protocol_sha256='c'*64)))
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    monkeypatch.setattr(export,'target',lambda:spec)
    value=receipt();value.update(status='STOPPED_EVIDENCE_READONLY_REVIEW_PASSED_PENDING_CLIENT',
        reviewer=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))
    export.finish(value,out,tmp_path/'public.json',b'x'*32,request,known=True)
    assert value['output_exported'] is True
    from seal import decrypt
    plain=tmp_path/'report.tar.gz';decrypt(tmp_path/export.CIPHER,plain,b'x'*32,value['review_encrypted_output']['sha256'])
    with tarfile.open(plain,'r:gz') as archive:
        manifest=json.loads(archive.extractfile('manifest.json').read())
        assert set(manifest['members'])==set(inventory)|{'review-output-scope.json'}
        assert empty.relative_to(out).as_posix() not in archive.getnames()
        for name,entry in manifest['members'].items():
            raw=archive.extractfile(name).read()
            assert dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())==entry
            assert raw==(out/name).read_bytes()


@pytest.mark.parametrize('fault',['unknown_empty','file_in_known_empty','nested_in_known_empty','changed_repair'])
def test_hydration_layout_fix_remains_exact_and_empty(fault,tmp_path):
    out,spec=hydrated_review_layout(tmp_path)
    if fault=='unknown_empty':(out/'other-empty').mkdir()
    elif fault=='file_in_known_empty':(out/'contexts/book/predecessor-checkpoints/fake.json').write_bytes(b'{}')
    elif fault=='nested_in_known_empty':(out/'contexts/book/predecessor-checkpoints/nested').mkdir()
    else:
        p=next((out/'contexts/book/repairs').iterdir());p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):export.output_inventory(out,spec,success=True)
