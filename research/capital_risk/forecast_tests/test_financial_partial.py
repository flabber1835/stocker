"""Synthetic archive and recorded-report checks; no canonical financial runtime."""
import ast
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

import system_campaign_financial_partial as p
import system_campaign_financial_resume as m


def test_two_format_changes_preserve_every_other_original_admission_statement():
    original=next(n for n in ast.parse(Path(p.crypto.__file__).read_bytes()).body
                  if isinstance(n,ast.FunctionDef) and n.name=='admit')
    adapted=p.admission_tree()
    class Undo(ast.NodeTransformer):
        members=review=0
        def visit_Call(self,node):
            if ast.unparse(node)=='public_names(spec, z)':
                self.members+=1
                return ast.parse("{spec['receipt_name'], 'full-core-staging.json', asset['name']}",mode='eval').body
            return self.generic_visit(node)
        def visit_BinOp(self,node):
            if ast.unparse(node)=="dest / 'stopped-review/core-review.json'":
                self.review+=1
                return ast.parse("dest / 'core-review.json'",mode='eval').body
            return self.generic_visit(node)
    undo=Undo();restored=undo.visit(adapted)
    assert undo.members==undo.review==1
    assert ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False)


def reporting_fixture():
    class RecordedStats:
        count=0
        def advance(self,day,navs,*,core_target,month_end):
            self.count+=1
            assert core_target=='0.5' and navs=={'pooled':p.Decimal('50000')}
            return dict(session=day,nav='50000') if month_end else None
        def to_dict(self):return dict(recorded_rows=self.count)
    daily=[dict(session=d,comparison_navs={'pooled':'50000'},decision={'target_core_exposure':.5})
           for d in ['2019-01-30','2019-01-31']]
    reports=[dict(session='2019-01-31',nav='50000',slot_retries={'inert':True})]
    parent=dict(completed=10)
    current=dict(completed=12,source_cursor='2019-01-31',stats=dict(recorded_rows=2))
    return RecordedStats,parent,current,daily,reports


def test_recorded_report_reproduction_checks_full_summary_without_mutating_records():
    cls,parent,current,daily,reports=reporting_fixture();saved=deepcopy((daily,reports,current))
    result=p.reproduce_reports(cls(),parent,current,daily,reports,'2019-02-01')
    assert result['new_daily_records']==2 and result['new_reports']==1
    assert result['all_monthly_checkpoint_state_exact'] is True
    assert (daily,reports,current)==saved


@pytest.mark.parametrize('change',['stored_report','stats','count','next_date'])
def test_reporting_mismatch_refuses(change):
    cls,parent,current,daily,reports=reporting_fixture();following='2019-02-01'
    if change=='stored_report':reports[0]['nav']='50001'
    elif change=='stats':current['stats']['recorded_rows']=3
    elif change=='count':current['completed']=13
    else:following='2019-01-31'
    with pytest.raises(ValueError):p.reproduce_reports(cls(),parent,current,daily,reports,following)


def test_actual_entire_report_and_stats_guard_removal_falsifier():
    cls,parent,current,daily,reports=reporting_fixture();current['stats']['recorded_rows']=3
    with pytest.raises(ValueError):p.reproduce_reports(cls(),parent,current,daily,reports,'2019-02-01')
    fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reproduce_reports')
    sites=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
           any(isinstance(a,ast.Constant) and a.value=='PARTIAL_ALL_NEW_REPORTS_AND_ENTIRE_STATS_EXACT' for a in n.value.args)]
    assert len(sites)==1;fn.body.remove(sites[0]);namespace=dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-entire-monthly-summary-guard>','exec'),namespace)
    assert namespace['reproduce_reports'](cls(),parent,current,daily,reports,'2019-02-01')['all_monthly_checkpoint_state_exact'] is True


def stopped_archive(tmp_path,monkeypatch):
    import ephemeral_runner_capacity as capacity
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    payload=tmp_path/'payload';(payload/'book').mkdir(parents=True);(payload/'stopped-review').mkdir()
    (payload/'parent-preflight').mkdir()
    request=dict(sources={'ephemeral_runner_capacity.py':'c'*64},protocol_sha256='b'*64)
    raw_request=(json.dumps(request)+'\n').encode();(payload/'request.json').write_bytes(raw_request)
    request_path=tmp_path/'request.json';request_path.write_bytes(raw_request)
    cp=dict(schema='research.pooled-vacancy-backtest/1',sha256='d'*64,base={'inert':True},
        source_cursor='2018-01-02',completed=1,repairs=[],
        run=dict(checkpoint_sha256='e'*64,state_sha256='f'*64,input_sha256='1'*64),
        journals={n:dict(bytes=0,prefix_sha256=p.sha(b'')) for n in ['formation','daily','monthly','watch']})
    raw_cp=gzip.compress(json.dumps(cp).encode());(payload/'book/checkpoint.json.gz').write_bytes(raw_cp)
    for name in cp['journals']:(payload/'book'/f'{name}.jsonl').write_bytes(b'')
    binding=b'{"inert":true}\n';(payload/'source-bindings.json').write_bytes(binding)
    report=dict(all_prefixes_verified=True,all_daily_factors_and_chains_verified=True,
                checkpoint_sha256=cp['sha256'],counts=dict(formation=126,daily=1))
    raw_review=json.dumps(report).encode();(payload/'stopped-review/core-review.json').write_bytes(raw_review)
    inspections={};stops={}
    for filename,phase,field in [('parent-preflight/worker-inspect.json','preflight','preflight'),
                                  ('worker-inspect.json','economic','worker'),('stopped-review/worker-inspect.json','review','reviewer')]:
        role='worker' if phase=='economic' else phase;name=f'capital-system-resume-p07-{role}-123-1';exit_code=1 if phase=='economic' else 0
        value=dict(Name='/'+name,Image=m.EXECUTION_IMAGE,Id=p.sha(name.encode()),
            State=dict(Running=False,OOMKilled=False,ExitCode=exit_code),
            HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
                PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in
                    ['/variant','/frozen','/driver','/old','/out']+(['/evidence'] if phase=='review' else [])],
            Config=dict(WorkingDir='/variant',User='1001:1001',Entrypoint=['python'],Env=[],
                Labels={'research.study':'full-system-search-20261029','research.role':'review' if phase=='review' else 'worker'},
                Cmd=['-B','-u','/driver/system_campaign_financial_resume.py','--mode',phase,'--spec','/out/spec.json']))
        raw=json.dumps(value).encode();(payload/filename).write_bytes(raw)
        inspections[filename]=dict(sha256=p.sha(raw),name='/'+name,id=value['Id'],exit_code=exit_code,user='1001:1001',correlation_prefix_mounted=False)
        stops[field]=dict(stopped=True,exit_code=exit_code,oom_killed=False,wait_error=None)
    key=b'k'*32;cipher=tmp_path/'stopped.crseal'
    asset=m.seal(payload,cipher,key,request_path,'P07',stage='campaign-factual-suffix',protocol_sha256='b'*64)
    receipt=dict(schema='research.system-campaign-accurate-resume-receipt/1',arm='P07',run_id='123',head='a'*40,
        protocol_sha256='b'*64,request_sha256=p.sha(raw_request),production_contacted=False,performance_admitted=False,
        status='PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT',encrypted_output=asset,**stops)
    stage=dict(status='STAGING_PASSED',run_id='123',source_commit='a'*40,protocol_sha256=p.PROTOCOL,
        runtime_image=p.IMAGE,execution_image=p.EXECUTION_IMAGE,source_files_verified=514,members_verified=591,
        authenticated_before_parsing=True,offline_image_source_verified=True,runtime_index_config_layer_chain_verified=True,replay_started=False)
    marker=dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED',arm='P07',financial_sessions_advanced=0,credentials_saved=False)
    public={n:json.dumps(v).encode() for n,v in [('campaign-factual-P07.json',receipt),('full-core-staging.json',stage),
        ('ephemeral-runner-capacity.json',{}),('resume-export-qualification-P07.json',marker)]}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        for n,raw in public.items():z.writestr(n,raw)
        z.write(cipher,asset['name'])
    archive=buffer.getvalue()
    spec=dict(archive_format=p.FORMAT,financial_authority=False,financial_predecessor_admitted=False,
        manifest=dict(raw_member_bytes=sum(f.stat().st_size for f in payload.rglob('*') if f.is_file())),
        arm='P07',artifact_id=456,run_id=123,head='a'*40,request_sha256=p.sha(raw_request),protocol_sha256='b'*64,
        stage='campaign-factual-suffix',receipt_name='campaign-factual-P07.json',receipt_schema=receipt['schema'],
        receipt_sha256=p.sha(public['campaign-factual-P07.json']),receipt_status=receipt['status'],prior_stops=stops,
        encrypted_output=asset,public_members={n:dict(bytes=len(raw),sha256=p.sha(raw)) for n,raw in public.items()},
        zip_bytes=len(archive),zip_sha256=p.sha(archive),inspections=inspections,source_binding_sha256=p.sha(binding),
        review_sha256=p.sha(raw_review),selected_checkpoint='book/checkpoint.json.gz',selected_file=dict(bytes=len(raw_cp),sha256=p.sha(raw_cp)),
        outer_sha256=cp['sha256'],inner_sha256=cp['run']['checkpoint_sha256'],state_sha256=cp['run']['state_sha256'],
        input_sha256=cp['run']['input_sha256'],base=cp['base'],selected_session=cp['source_cursor'],measured_closes=1,
        journals=cp['journals'],repairs=[],original_request_member=dict(bytes=len(raw_request),sha256=p.sha(raw_request)))
    monkeypatch.setattr(p.crypto,'hosted_destination',lambda root:Path(root))
    def download(command,*,stdout,**kwargs):
        assert command==['gh','api','repos/flabber1835/stocker/actions/artifacts/456/zip']
        stdout.write(archive);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(p.crypto.subprocess,'run',download)
    calls=[]
    monkeypatch.setattr(capacity,'validate_prepared_receipt',lambda value,**kw:calls.append(kw))
    return spec,archive,key,raw_cp,calls


def test_real_synthetic_five_member_cipher_admission_and_all_archived_fences(tmp_path,monkeypatch):
    spec,_,key,raw,calls=stopped_archive(tmp_path,monkeypatch)
    dest=p.admit(spec,tmp_path/'transfer',key,m.inspect)
    assert (dest/'book/checkpoint.json.gz').read_bytes()==raw
    assert calls==[dict(head='a'*40,run_id='123',source_sha256='c'*64)]


@pytest.mark.parametrize('change',['public_hash','review_hash','stop_id','input_hash','selected_gzip','source_hash'])
def test_new_archive_mismatches_refuse_without_financial_execution(tmp_path,monkeypatch,change):
    spec,_,key,_,_=stopped_archive(tmp_path,monkeypatch)
    if change=='public_hash':spec['public_members']['resume-export-qualification-P07.json']['sha256']='0'*64
    elif change=='review_hash':spec['review_sha256']='0'*64
    elif change=='stop_id':spec['inspections']['worker-inspect.json']['id']='0'*64
    elif change=='input_hash':spec['input_sha256']='0'*64
    elif change=='selected_gzip':spec['selected_file']['sha256']='0'*64
    else:spec['source_binding_sha256']='0'*64
    with pytest.raises(ValueError):p.admit(spec,tmp_path/'transfer',key,m.inspect)


def test_duplicate_public_zip_member_is_rejected(tmp_path,monkeypatch):
    spec,raw,_,_,_=stopped_archive(tmp_path,monkeypatch)
    buffer=io.BytesIO(raw)
    with zipfile.ZipFile(buffer,'a') as archive:
        original=archive.read('full-core-staging.json')
        with pytest.warns(UserWarning,match='Duplicate name'):archive.writestr('full-core-staging.json',original)
    with zipfile.ZipFile(buffer) as archive:
        with pytest.raises(ValueError,match='FIVE_UNIQUE'):p.public_names(spec,archive)
        fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='public_names')
        sites=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
               any(isinstance(a,ast.Constant) and a.value=='PARTIAL_EXACT_FIVE_UNIQUE_ZIP_MEMBERS' for a in n.value.args)]
        assert len(sites)==1;fn.body.remove(sites[0]);namespace=dict(vars(p))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-unique-zip-member-guard>','exec'),namespace)
        assert namespace['public_names'](spec,archive)==set(spec['public_members'])|{spec['encrypted_output']['name']}


def test_full_gcm_authentication_rejects_changed_cipher_before_plaintext_parse(tmp_path,monkeypatch):
    from cryptography.exceptions import InvalidTag
    spec,raw,key,_,_=stopped_archive(tmp_path,monkeypatch)
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        members={n:original.read(n) for n in original.namelist()}
    asset=spec['encrypted_output'];cipher=bytearray(members[asset['name']]);cipher[30]^=1
    members[asset['name']]=bytes(cipher);asset['sha256']=p.sha(bytes(cipher))
    receipt=json.loads(members[spec['receipt_name']]);receipt['encrypted_output']=asset
    members[spec['receipt_name']]=json.dumps(receipt).encode();spec['receipt_sha256']=p.sha(members[spec['receipt_name']])
    spec['public_members'][spec['receipt_name']]=dict(bytes=len(members[spec['receipt_name']]),sha256=spec['receipt_sha256'])
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        for n,b in members.items():archive.writestr(n,b)
    changed=buffer.getvalue();spec.update(zip_bytes=len(changed),zip_sha256=p.sha(changed))
    def download(command,*,stdout,**kwargs):stdout.write(changed);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(p.crypto.subprocess,'run',download)
    with pytest.raises(InvalidTag):p.admit(spec,tmp_path/'transfer',key,m.inspect)
    assert not (tmp_path/'transfer/admitted').exists()
