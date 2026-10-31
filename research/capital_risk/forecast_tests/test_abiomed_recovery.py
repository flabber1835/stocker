"""Pure provider/byte/stop-boundary tests; no canonical or financial replay."""
import ast
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

import system_campaign_abiomed_facts as facts
from system_campaign_facts import digest,sha
from system_campaign_stopped_diagnostics import stopped


def provider():
    # Synthetic strings, not a copy of the private provider payload.
    rows=[dict(date='2022-12-21',action='acquisitionof',ticker='BUYER',name='Buyer',value='',contraticker='ABMD',contraname='Target'),
          dict(date='2022-12-21',action='delisted',ticker='ABMD',name='Target',value='',contraticker='N/A',contraname='N/A'),
          dict(date='2022-12-21',action='acquisitionby',ticker='ABMD',name='Target',value='',contraticker='BUYER',contraname='Buyer')]
    table=io.StringIO(newline='');writer=csv.DictWriter(table,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:z.writestr('synthetic.csv',table.getvalue())
    raw=buffer.getvalue()
    return raw,rows,dict(provider_archive_sha256=sha(raw),provider_rows_sha256=digest(rows),provider_row_sha256=[digest(v) for v in rows])


def test_complete_target_and_inverse_rows_in_physical_order():
    raw,rows,contract=provider()
    assert facts.provider_rows(raw)==facts.verify_provider_rows(raw,contract)==rows


def test_original_two_target_row_contract_refuses_actual_inverse_record():
    raw,rows,contract=provider()
    contract.update(provider_rows_sha256=digest(rows[1:]),provider_row_sha256=[digest(v) for v in rows[1:]])
    with pytest.raises(ValueError,match='ALL_ORIGINAL_PROVIDER_ROWS'):facts.verify_provider_rows(raw,contract)


def test_permuted_or_omitted_provider_row_is_not_masked():
    raw,rows,contract=provider()
    for bad in (rows[::-1],rows[:-1],[dict(rows[0],action='different'),*rows[1:]]):
        changed={**contract,'provider_rows_sha256':digest(bad),'provider_row_sha256':[digest(v) for v in bad]}
        with pytest.raises(ValueError,match='ALL_ORIGINAL_PROVIDER_ROWS'):facts.verify_provider_rows(raw,changed)


def test_provider_archive_guard_is_effective():
    raw,_,contract=provider()
    with pytest.raises(ValueError,match='FROZEN_PROVIDER_ARCHIVE'):
        facts.verify_provider_rows(raw,{**contract,'provider_archive_sha256':'0'*64})


def inspection():
    command=['-B','-u','/driver/system_campaign_p02_abiomed_run.py','--mode','economic',
             '--spec','/out/spec.json','--request','/driver/request.json']
    return dict(Name='/capital-system-factual-p02-worker-999-1',Id='a'*64,
        State=dict(Running=False,OOMKilled=False,ExitCode=1),
        Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            ReadonlyRootfs=True,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in ['/variant','/frozen','/driver','/out','/old']],
        Config=dict(WorkingDir='/variant',Cmd=command,Env=['PYTHONHASHSEED=0']))


def test_diagnostics_accept_only_exact_known_stopped_worker():
    stopped(inspection(),dict(stopped=True,oom_killed=False,exit_code=1),'worker','999','request.json')


@pytest.mark.parametrize('change',[lambda x:x['State'].update(Running=True),
    lambda x:x['State'].update(OOMKilled=True),lambda x:x.update(Name='/other'),
    lambda x:x['HostConfig'].update(NetworkMode='bridge'),
    lambda x:x['HostConfig'].update(MemorySwap=16*1024**3),
    lambda x:x['Mounts'][0].update(RW=True),lambda x:x['Config']['Cmd'].append('--different'),
    lambda x:x['Config']['Env'].append('GH_TOKEN=synthetic-forbidden')])
def test_diagnostic_stop_fences_and_payload_scope_refuse(change):
    value=inspection();change(value)
    with pytest.raises(ValueError):stopped(value,dict(stopped=True,oom_killed=False,exit_code=1),'worker','999','request.json')


def test_actual_stop_guard_removal_falsifier():
    import system_campaign_stopped_diagnostics as module
    tree=ast.parse(Path(module.__file__).read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(v,ast.Constant) and v.value=='DIAGNOSTIC_EXACT_ACTUAL_STOP' for v in n.value.args)]
    fn.body.remove(site);ns=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<diagnostic-actual-stop-guard-removal>', 'exec'),ns)
    bad=inspection();bad['State']['Running']=True
    ns['stopped'](bad,dict(stopped=True,oom_killed=False,exit_code=1),'worker','999','request.json')


def test_recovery_requires_complete_journal_bytes_including_unsent_tail(tmp_path,monkeypatch):
    import system_campaign_abiomed_recovery as module
    public=Path(module.__file__).parent/module.EQUIVALENCE;proof=json.loads(public.read_bytes())
    proof=deepcopy(proof)
    for name in proof['exact_unchanged_members']:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);raw=('synthetic-'+name).encode();path.write_bytes(raw)
        proof['exact_unchanged_members'][name]=dict(bytes=len(raw),sha256=sha(raw))
    (tmp_path/module.EQUIVALENCE).write_text(json.dumps(proof))
    monkeypatch.setattr(module,'HERE',tmp_path)
    spec=dict(run_id=41166283025,outer_sha256=proof['financial_parent_outer_sha256'],selected_session='2022-11-30',
              selected_file=proof['exact_unchanged_members']['book/checkpoint.json.gz'])
    request=dict(abiomed_unadvanced_equivalence_sha256=sha((tmp_path/module.EQUIVALENCE).read_bytes()))
    module.verify(tmp_path,spec,request)
    with (tmp_path/'book/daily.jsonl').open('ab') as f:f.write(b'unsent-tail-change')
    with pytest.raises(ValueError,match='UNSENT_TAIL_BYTES'):module.verify(tmp_path,spec,request)
    tree=ast.parse(Path(module.__file__).read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify']
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    guard,=[n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(v,ast.Constant) and v.value=='ABIOMED_RECOVERY_ACTUAL_COMPLETE_PARENT_AND_UNSENT_TAIL_BYTES'
                    for v in n.value.args)]
    loop.body.remove(guard);namespace=dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<actual-recovery-tail-guard-removal>','exec'),namespace)
    assert namespace['verify'](tmp_path,spec,request)==proof


def test_diagnostic_actual_synthetic_crypto_roundtrip_and_original_scope_refusal(tmp_path,monkeypatch):
    import tarfile
    import system_campaign_stopped_diagnostics as module
    from seal import decrypt
    root=tmp_path/'diagnostic';root.mkdir();(root/'fixed-marker.txt').write_bytes(b'synthetic metadata only\n')
    request=tmp_path/'request.json';request.write_bytes(b'{"synthetic":true}\n')
    monkeypatch.setenv('GITHUB_RUN_ID','999');monkeypatch.setenv('GITHUB_SHA','a'*40)
    key=b'\x01'*32;target=tmp_path/'diagnostic.crseal'
    with pytest.raises(ValueError,match='RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE'):
        module.original_export.seal(root,tmp_path/'forbidden.crseal',key,request,'P02',
            stage='campaign-stopped-diagnostics',protocol_sha256='b'*64)
    asset=module.seal_diagnostics(root,target,key,request,'b'*64)
    plain=tmp_path/'synthetic.tar.gz';decrypt(target,plain,key,asset['sha256'])
    with tarfile.open(plain,'r:gz') as tar:
        manifest_raw=tar.extractfile('manifest.json').read();manifest=json.loads(manifest_raw)
        assert sha(manifest_raw)==asset['manifest_sha256']
        assert manifest['stage']=='campaign-stopped-diagnostics' and manifest['arm']=='P02'
        assert manifest['run_id']=='999' and manifest['head']=='a'*40
        assert manifest['members']=={'fixed-marker.txt':dict(bytes=24,sha256=sha(b'synthetic metadata only\n'))}
        assert tar.extractfile('fixed-marker.txt').read()==b'synthetic metadata only\n'
