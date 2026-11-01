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


def test_fixture_fault_precedes_feature_materialization():
    source=ast.parse((HERE/'system_campaign_discovery_gate.py').read_bytes())
    fn,=[v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='qualify']
    text=ast.unparse(fn)
    assert text.index('packet = replace(packet,') < text.index('buffer.append(packet)')
    assert text.index('buffer.append(packet)') < text.index('publication = buffer.prepare(')
    assert 'bars=tuple(b for b in publication.bars' not in text
    assert 'DISCOVERY_GATE_ACTUAL_MISSING_SIGNAL_OBSERVATION_OMITTED' in text


def test_actual_provenance_copy_fragment_requires_and_gets_archive_directory(tmp_path):
    """Metadata I/O fragments only; canonical restore is never called locally."""
    loader=ast.parse((HERE/'system_campaign_discovery_inputs.py').read_bytes())
    fn,=[v for v in loader.body if isinstance(v,ast.FunctionDef) and v.name=='preserve_input_documents']
    setup,=[v for v in fn.body if isinstance(v,ast.Expr)
            and isinstance(v.value,ast.Call) and ast.unparse(v.value.func)=="(output / 'book/predecessor-checkpoints').mkdir"]
    legacy=ast.parse((HERE/'system_campaign_p02_calendar_run.py').read_bytes())
    method,=[v for v in legacy.body if isinstance(v,ast.FunctionDef) and v.name=='retained_amendment']
    start=next(i for i,v in enumerate(method.body) if isinstance(v,ast.Assign)
               and isinstance(v.targets[0],ast.Name) and v.targets[0].id=='archive')
    fragment=compile(ast.Module(body=method.body[start:start+2],type_ignores=[]),
                     '<actual-retained-provenance-byte-copy-only>','exec')
    old=tmp_path/'old';out=tmp_path/'out';out.mkdir()
    old_archive=old/'book/predecessor-checkpoints';old_archive.mkdir(parents=True)
    raw=b'EXPLICIT_METADATA_ONLY_ORIGINAL_GZIP_BYTE_FIXTURE'
    (old_archive/'origin.json.gz').write_bytes(raw)
    def need(value,reason):
        assert value,reason
    namespace=dict(old=old,out=out,OUTER='origin',need=need)
    with pytest.raises(FileNotFoundError):exec(fragment,namespace)
    exec(compile(ast.Module(body=[setup],type_ignores=[]),'<actual-diagnostic-directory-setup>','exec'),dict(output=out))
    exec(fragment,namespace)
    assert (out/'book/predecessor-checkpoints/origin.json.gz').read_bytes()==raw
    assert (old_archive/'origin.json.gz').read_bytes()==raw


def test_actual_amendment_documents_reader_gets_original_descriptor_bytes(tmp_path):
    import gzip
    import hashlib
    loader=ast.parse((HERE/'system_campaign_discovery_inputs.py').read_bytes())
    helper,=[v for v in loader.body if isinstance(v,ast.FunctionDef) and v.name=='preserve_input_documents']
    source=ast.parse((HERE/'system_campaign_future_amendment.py').read_bytes())
    reader,=[v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='documents']
    namespace=dict(Path=Path,hashlib=hashlib,json=json,
        sha=lambda raw:hashlib.sha256(raw).hexdigest(),
        need=lambda value,reason:None if value else (_ for _ in ()).throw(ValueError(reason)))
    exec(compile(ast.Module(body=[helper,reader],type_ignores=[]),'<actual-metadata-only-input-copies-and-reader>','exec'),namespace)
    old=tmp_path/'old';out=tmp_path/'out';(old/'book/repairs').mkdir(parents=True)
    raw=b'{"explicit":"metadata-only"}';h=hashlib.sha256(raw).hexdigest();name=h+'.json'
    (old/'book/repairs'/name).write_bytes(raw);cp={'repairs':[{'sha256':h,'filename':name}]}
    with pytest.raises(FileNotFoundError):namespace['documents'](out,cp)
    namespace['preserve_input_documents'](old,cp,out)
    assert namespace['documents'](out,cp)=={h:json.loads(raw)}
    assert not (out/'book/checkpoint.json.gz').exists() and not list(out.rglob('*.jsonl'))
    # Actual retained amendment boundary: every descriptor is a metadata read,
    # never a canonical restore, strategy transition or accounting operation.
    root=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p02-sequential-001/winter2025-cash-suffix-001/evidence-001/verified')
    if sys.platform=='win32':root=Path(chr(92)*2+'?'+chr(92)+str(root))
    if root.exists():
        latest=json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
        historical=json.loads(gzip.decompress((root/'book/predecessor-checkpoints/a9b87ca80dbc29e3700173c4c879083266554457aec10e4327c58ee872b860ee.json.gz').read_bytes()))
        copied=tmp_path/'actual';namespace['preserve_input_documents'](root,latest,copied)
        actual=namespace['documents'](copied,historical)
        assert set(actual)=={d['sha256'] for d in historical['repairs']}


def test_original_input_digest_guard_rejects_corruption_and_removal_is_detected(tmp_path):
    import hashlib
    source=ast.parse((HERE/'system_campaign_discovery_inputs.py').read_bytes())
    helper,=[v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='preserve_input_documents']
    old=tmp_path/'old';(old/'book/repairs').mkdir(parents=True)
    raw=b'ORIGINAL_METADATA_ONLY';h=hashlib.sha256(raw).hexdigest();name=h+'.json'
    (old/'book/repairs'/name).write_bytes(b'CORRUPTED_METADATA_ONLY')
    def need(value,reason):
        if not value:raise ValueError(reason)
    scope=dict(Path=Path,hashlib=hashlib,need=need)
    exec(compile(ast.Module(body=[helper],type_ignores=[]),'<actual-original-input-digest-guard>','exec'),scope)
    cp={'repairs':[{'sha256':h,'filename':name}]}
    with pytest.raises(ValueError,match='DISCOVERY_ORIGINAL_INPUT_BYTES'):
        scope['preserve_input_documents'](old,cp,tmp_path/'rejected')
    def removed(value,reason):
        if reason!='DISCOVERY_ORIGINAL_INPUT_BYTES':need(value,reason)
    scope['need']=removed
    scope['preserve_input_documents'](old,cp,tmp_path/'guard-removed')
    assert (tmp_path/'guard-removed/book/repairs'/name).read_bytes()!=raw


def test_actual_window_feature_key_guard_rejects_old_incoherent_fixture():
    # Frozen guard predicate only; no canonical module is imported or executed.
    root=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/zero-share-2008-20261026/source-fixed')
    if not root.exists():
        root=Path('/variant')
    if not (root/'sentinel/core/window_material.py').is_file():
        pytest.skip('Frozen canonical source is checked by hosted qualification.')
    source=ast.parse((root/'sentinel/core/window_material.py').read_bytes())
    fn,=[v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='install']
    guard,=[v for v in ast.walk(fn) if isinstance(v,ast.If)
            and any(isinstance(c,ast.Constant) and c.value=='CURRENT_WINDOW_FEATURE_KEYS_CHANGED' for c in ast.walk(ast.Module(body=v.body,type_ignores=[])))]
    code=compile(ast.Expression(body=guard.test),'<actual-window-key-guard-metadata-predicate>','eval')
    bars={'Q':SimpleNamespace(security_id='Q')}
    publication=SimpleNamespace(bars=list(bars.values()))
    material=SimpleNamespace(signals=[SimpleNamespace(security_id=sid) for sid in ('Q','ABSENT')])
    assert eval(code,dict(bars=bars,published=publication,material=material))
    material.signals=[SimpleNamespace(security_id='Q')]
    assert not eval(code,dict(bars=bars,published=publication,material=material))


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
