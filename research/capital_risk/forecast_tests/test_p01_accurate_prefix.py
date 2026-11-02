"""Scope, real encrypted marker and worker fences; no financial execution."""
import ast,json,os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_parallel_discovery import compile_body
import system_campaign_p01_accurate_job as job
import system_campaign_p01_accurate_export as export

def receipt():
    return dict(schema='research.p01-accurate-financial-prefix-receipt/1',arm='P01',stage=export.STAGE,
        run_id='123',head='1'*40,request_sha256='2'*64,protocol_sha256='3'*64,
        strict_parent_outer_sha256='4'*64,strict_parent_run_id=41000113747,
        status='NOT_STARTED',production_contacted=False)

def test_actual_marker_encrypt_authenticate_decrypt_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_bytes(json.dumps(dict(protocol_sha256='2'*64)).encode())
    proof=export.qualify_export(tmp_path/'probe',request)
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']
    assert proof['source_adapter_sha256']==job.sha256_file(Path(export.__file__))

@pytest.mark.parametrize('key,value',[('cash',50000),('daily',[]),('production_contacted',True),('arm','P02')])
def test_public_metadata_guard_rejects_financial_or_wrong_scope_fields(tmp_path,key,value):
    r=receipt();r[key]=value
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',r)
    assert not (tmp_path/'public.json').exists()

def test_actual_public_allowlist_guard_removal_falsifier(tmp_path):
    fn,=[n for n in ast.parse(Path(export.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='write_receipt']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(c,ast.Constant)
        and c.value=='P01_ACCURATE_PUBLIC_ALLOWLIST' for c in ast.walk(n)))]
    r=receipt();r['cash']=50000
    compile_body(fn,vars(export))(tmp_path/'mutated.json',r)
    assert json.loads((tmp_path/'mutated.json').read_bytes())['cash']==50000

def test_unknown_stop_has_no_mutable_snapshot_or_plaintext(tmp_path,monkeypatch):
    r=receipt();root=tmp_path/'root';root.mkdir();(root/'financial.txt').write_text('PRIVATE_SYNTHETIC')
    monkeypatch.setattr(export,'sealed',lambda *a:pytest.fail('UNKNOWN snapshot attempted'))
    export.finish(r,root,tmp_path/'receipt.json',b'1'*32,tmp_path/'request.json',known=False)
    assert r['encrypted_output_exported'] is False and 'encrypted_output' not in r

def test_known_stop_export_failure_keeps_receipt_without_plaintext(tmp_path,monkeypatch):
    def broken(*a):raise RuntimeError('Private financial data must not be public')
    monkeypatch.setattr(export,'sealed',broken);r=receipt()
    export.finish(r,tmp_path,tmp_path/'receipt.json',b'1'*32,tmp_path/'request.json',known=True)
    assert r['status']=='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    assert r['export_error']==dict(type='RuntimeError',code='EXPORT_OPERATION_FAILED')
    assert 'Private' not in (tmp_path/'receipt.json').read_text()

@pytest.mark.parametrize('mode',['economic','review'])
def test_actual_full_inspector_accepts_only_exact_fences_and_entrypoint(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    role='review' if mode=='review' else 'worker';name=f'capital-system-p01-accurate-{role}-123-1'
    mounts=['/variant','/frozen','/driver','/out','/old']+(['/evidence'] if role=='review' else [])
    value=dict(Name='/'+name,Image=job.inspector_source.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(mode),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':role}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in mounts])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64)==value
    for n in ('NetworkMode','MemorySwap'):
        original=value['HostConfig'][n];value['HostConfig'][n]='bridge' if n=='NetworkMode' else 0
        with pytest.raises(ValueError):job.inspect(name,'1'*64)
        value['HostConfig'][n]=original
    value['Config']['Cmd']=job.entrypoint('review' if mode=='economic' else 'economic')
    with pytest.raises(ValueError,match='ENTRYPOINT'):job.inspect(name,'1'*64)

def test_only_original_strict419_to_438_no_overlay_or_diagnostic_state():
    value=job.expected_request()
    assert len(value['sources'])==402 and value['repairs']==8 and value['maximum_transitions']==19
    assert value['financial_start']=='2019-09-03' and value['processing_endpoint']=='2019-09-27'
    assert value['full_measurement_end']=='2026-07-31' and not value['new_factual_overlay']
    assert not value['diagnostic_state_adopted'] and not value['financial_source_changed']
    import system_campaign_p01_accurate_run as runner
    tree=ast.parse(Path(runner.__file__).read_bytes());text=ast.unparse(tree)
    assert 'DiscoveryContext' not in text and 'backtest.main(args)' in text
    assert 'new_transitions=current' in text and 'preserve_tails' in text
