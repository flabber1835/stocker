"""Metadata/fence qualification only; all canonical transitions stay hosted."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path, PurePosixPath
import sys
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('LOCAL_DISCOVERY_FLOW_METADATA_ONLY:'+fullname)
        return None


sys.meta_path.insert(0,Fence())
import system_campaign_discovery_job as job
import system_campaign_discovery_parent as parent
from system_campaign_pxd_financial_body import tree


def test_frozen_request_has_only_diagnostic_authority_and_latest_strict_parent():
    request=json.loads((HERE/job.REQUEST).read_bytes())
    assert request==job.expected_request() and len(request['sources'])==343
    assert request['expected_remaining_sessions']==314 and not request['financial_authority']
    assert not request['new_origin'] and not request['new_overlay']
    spec=parent.scope(json.loads((HERE/parent.SPEC).read_bytes()))
    assert spec['selected_session']=='2025-04-30' and spec['measured_closes']==1842
    assert spec['full_client_admission']['all226_actual_members_readback_verified'] is True
    assert request['qualify_wait_seconds']+request['discovery_wait_seconds'] < 270*60


def test_unadmitted_diagnostic_cursor_is_not_a_parent():
    spec=json.loads((HERE/parent.SPEC).read_bytes())
    spec['selected_session']='2025-05-15'
    with pytest.raises(ValueError,match='EXACT_PUBLIC_STRICT_PARENT'):
        parent.scope(spec)


def test_actual_download_destination_guard_accepts_caller_and_rejects_old_name():
    """Exercise the retained guard, with only host metadata/I/O stubbed."""
    source=ast.parse(Path(parent.crypto.__file__).read_bytes())
    fn,=[v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='hosted_destination']
    scope=dict(vars(parent.crypto),
        Path=lambda value:SimpleNamespace(resolve=lambda:PurePosixPath(value)),
        os=SimpleNamespace(name='posix',environ={'RUNNER_TEMP':'/home/runner/work/_temp'}),
        check_context=lambda env:None,
        shutil=SimpleNamespace(disk_usage=lambda path:SimpleNamespace(free=20*1024**3)))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual-hosted-destination-metadata-guard>','exec'),scope)
    jobtree=ast.parse((HERE/'system_campaign_discovery_job.py').read_bytes())
    call,=[v for v in ast.walk(jobtree) if isinstance(v,ast.Call)
           and isinstance(v.func,ast.Name) and v.func.id=='admit']
    name=ast.literal_eval(call.args[1].right)
    root='/home/runner/work/_temp/'+name
    assert scope['hosted_destination'](root)==PurePosixPath(root)
    with pytest.raises(ValueError,match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):
        scope['hosted_destination']('/home/runner/work/_temp/p02-discovery-strict-parent')
    with pytest.raises(ValueError,match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):
        scope['hosted_destination']('/other/campaign-factual-transfer-p02-discovery-strict-parent')


def inspection():
    return dict(Name='/capital-system-discovery-p02-worker-123-1',Image=job.EXECUTION_IMAGE,Id='exact-id',
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,
            NanoCpus=2000000000,PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges']),
        Config=dict(WorkingDir='/variant',User='1001:1001',Env=['FULL_SYSTEM_HOSTED=1'],
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out')
                for n in ('/variant','/frozen','/driver','/out','/old')])


def actual_inspector(record):
    # Execute the actual source-bound fence with Docker I/O replaced by a JSON stub.
    body=tree('system_campaign_p02_continue_job.py','inspect',{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-discovery-p02-(?:qualify|worker)-[0-9]+-1'})
    scope=dict(vars(job.inspector_source),
        os=SimpleNamespace(getuid=lambda:1001,getgid=lambda:1001),
        subprocess=SimpleNamespace(run=lambda *args,**kw:SimpleNamespace(stdout=json.dumps([record]).encode())))
    exec(compile(body,'<actual-discovery-stop-fences-stub-docker>','exec'),scope)
    return scope['inspect']


def test_actual_inspection_requires_exact_private_identity_and_fences():
    record=inspection()
    assert actual_inspector(record)('capital-system-discovery-p02-worker-123-1','exact-id')==record
    with pytest.raises(ValueError,match='WORKER_IDENTITY'):
        actual_inspector(record)('capital-system-discovery-p02-worker-123-1','wrong-id')


@pytest.mark.parametrize('change', ['network','swap','image','mount','key','name'])
def test_actual_stop_boundary_refuses_fence_changes(change):
    record=inspection();name='capital-system-discovery-p02-worker-123-1'
    if change=='network':record['HostConfig']['NetworkMode']='bridge'
    if change=='swap':record['HostConfig']['MemorySwap']*=2
    if change=='image':record['Image']='wrong-image'
    if change=='mount':record['Mounts'][0]['RW']=True
    if change=='key':record['Config']['Env'].append(job.SECRET+'=MUST_NEVER_BE_IN_WORKER')
    if change=='name':name='capital-system-factual-p02-worker-123-1'
    with pytest.raises(ValueError):actual_inspector(record)(name,'exact-id')


def test_actual_export_body_changes_only_diagnostic_stage_literal():
    body=tree('system_campaign_evidence_export.py','seal',{'campaign-factual-suffix':'campaign-disposable-discovery'})
    source=ast.unparse(body)
    assert 'campaign-disposable-discovery' in source
    assert 'EncryptWriter' in source and 'writer.finish()' in source and 'os.fsync' in source
    assert 'sha256_file' in source and 'is_symlink' in source


def test_workflow_is_serial_research_only_and_uploads_encrypted_evidence():
    workflow=(HERE.parents[1]/'.github/workflows/capital-system-p02-discovery.yml').read_text()
    assert 'group: system-optimization-002-p02-only' in workflow
    assert 'cancel-in-progress: false' in workflow and 'retention-days: 7' in workflow
    assert 'contents: read' in workflow and 'actions: read' in workflow
    assert 'codex/capital-risk-research' in workflow
    assert 'p02-discovery.tar.crseal' in workflow
    assert 'workflow_dispatch' not in workflow and 'self-hosted' not in workflow


def test_hosted_qualification_precedes_discovery_and_unknown_never_seals():
    body=ast.parse((HERE/'system_campaign_discovery_job.py').read_bytes())
    fn,=[v for v in body.body if isinstance(v,ast.FunctionDef) and v.name=='main']
    text=ast.unparse(fn)
    assert text.index("proof['status'] == 'QUALIFIED'") < text.index("cmd(name, 'discovery', out)")
    unknown,=[v for v in ast.walk(fn) if isinstance(v,ast.ExceptHandler)
              and isinstance(v.type,ast.Name) and v.type.id=='StopUnknown']
    assert ast.unparse(unknown.body[0])=='known = False'
    seals=[v for v in ast.walk(fn) if isinstance(v,ast.If) and ast.unparse(v.test)=='known'
           and any(isinstance(a,ast.Assign) and 'sealed(' in ast.unparse(a) for a in v.body)]
    assert len(seals)==1
