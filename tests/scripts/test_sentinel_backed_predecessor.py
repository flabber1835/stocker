"""A completed local patch is a predecessor, not another activation grant."""
from copy import deepcopy
import inspect
import json
import textwrap

import pytest

from tests.scripts.test_sentinel_backed_local_patch import patch


OLD, NEW = 'a'*40, 'b'*40
OLD_IMAGE, NEW_IMAGE = 'sha256:'+'a'*64, 'sha256:'+'b'*64


@pytest.fixture
def chain(tmp_path):
    anchor_root=tmp_path/'anchor'; (anchor_root/'.git').mkdir(parents=True)
    anchor=anchor_root/'artifacts/sentinel/authority/deployments/initial/activation-receipt.json'
    anchor.parent.mkdir(parents=True)
    anchor.write_text(json.dumps(dict(schema='sentinel.activation-receipt/1',
        operational_ready=True,activation_mode='dual',completed_at='2026-10-26T10:00:00Z',
        git_commit=OLD,runtime_image=OLD_IMAGE,control_generation=50,certificate_sha256='c'*64)))
    source=tmp_path/'source'; (source/'.git').mkdir(parents=True)
    operation=tmp_path/'operation';operation.mkdir()
    pg=dict(command=['postgres','-c','archive_mode=on'],container='pg-container',image='pg-image',
        started='original-start',source='/owned/pgdata',volume='sentinel_sentinel_pgdata')
    predecessor=dict(commit=OLD,image=OLD_IMAGE,postgres=pg,system='1234')
    candidate=dict(commit=NEW,image=NEW_IMAGE,source_identity={k:'e'*64 for k in ('source','wealth','shadow_config')})
    report=operation/'qualification.json'
    report.write_text(json.dumps(dict(commit=NEW,final=True,source_files_unchanged=True,
        source_files={'sentinel/module.py':'f'*64})))
    qualification=dict(report_path=str(report),report_sha256=patch.sha256_file(report),
        commit=NEW,passed=True,source_files={'sentinel/module.py':'f'*64})
    request=dict(schema='sentinel.local-paper-delivery/3',operation_id='private-completed-patch',
        handoff_mode='PRE_OPEN',source=str(source),deployment=str(anchor_root),
        predecessor=predecessor,candidate=candidate,qualification=qualification,
        allowed_delta=['sentinel/module.py'],created_at='2026-10-26T11:00:00Z')
    built=dict(schema=patch.builder.BUILD_SCHEMA,commit=NEW,image=NEW_IMAGE,
        source_identity=candidate['source_identity'],source=str(source),deployment=str(anchor_root),
        foundation=predecessor,predecessor_receipt=dict(path=str(anchor),sha256=patch.sha256_file(anchor)),
        qualification={k:qualification[k] for k in ('report_path','report_sha256')})
    return dict(anchor=anchor,anchor_root=anchor_root,source=source,operation=operation,
                pg=pg,request=request,built=built,report=report)


def complete(case, *, final_stage='VERIFIED', artifacts=None):
    folder=case['operation']
    (folder/'request.json').write_text(json.dumps(case['request']))
    (folder/'build.json').write_text(json.dumps(case['built']))
    journal=patch.Journal(folder)
    for before,after in zip(journal.stages,journal.stages[1:]):
        fields=(artifacts or dict(postgres=case['pg'],preserved={'system':'1234'})) if after=='PREFLIGHT_PASS' else {}
        journal.advance(before,after,**fields)
        if after==final_stage:break
    return folder/'receipt.json'


def test_completed_patch_retains_original_activation_and_exact_candidate(chain):
    actual=patch.predecessor_witness(complete(chain))
    assert actual['git_commit']==NEW and actual['runtime_image']==NEW_IMAGE
    assert actual['foundation_reference']=='sentinel-local-paper:'+NEW[:8]
    assert actual['control_generation']==50 and actual['certificate_sha256']=='c'*64
    assert actual['postgres']==chain['pg'] and actual['system']=='1234'
    assert actual['roots']==(chain['anchor_root'],chain['source'])


@pytest.mark.parametrize('field',['commit','image','source_identity','source','deployment','foundation'])
def test_tampered_build_subject_is_refused(chain,field):
    path=complete(chain)
    changed=deepcopy(chain['built']);changed[field]='foreign'
    (chain['operation']/'build.json').write_text(json.dumps(changed))
    with pytest.raises(patch.DeliveryRefused,match='BUILD_CHANGED'):
        patch.predecessor_witness(path)


@pytest.mark.parametrize('fault',['incomplete','journal','qualification_hash','qualification_subject',
    'anchor_hash','foundation','postgres','system','missing_root'])
def test_incomplete_or_changed_lineage_cannot_become_a_predecessor(chain,fault):
    artifacts=None
    if fault=='foundation':
        chain['request']['predecessor']['commit']='d'*40
    if fault=='qualification_subject':
        report=json.loads(chain['report'].read_text());report['commit']='d'*40
        chain['report'].write_text(json.dumps(report));sha=patch.sha256_file(chain['report'])
        chain['request']['qualification']['report_sha256']=chain['built']['qualification']['report_sha256']=sha
    if fault=='postgres':
        pg=deepcopy(chain['pg']);pg['command']=['postgres','-c','archive_mode=off']
        artifacts=dict(postgres=pg,preserved={'system':'1234'})
    if fault=='system':artifacts=dict(postgres=chain['pg'],preserved={'system':'9999'})
    path=complete(chain,final_stage='APPLICATIONS_STARTED' if fault=='incomplete' else 'VERIFIED',artifacts=artifacts)
    if fault=='journal':
        v=json.loads(path.read_text());v['history'][-1]['sha256']='0'*64;path.write_text(json.dumps(v))
    if fault=='qualification_hash':chain['report'].write_text('{}')
    if fault=='anchor_hash':chain['anchor'].write_text(chain['anchor'].read_text()+'\n')
    if fault=='missing_root':(chain['source']/'.git').rmdir()
    with pytest.raises(patch.DeliveryRefused):patch.predecessor_witness(path)


def test_repeated_or_excessive_chain_is_refused(chain):
    path=complete(chain)
    for trail in ((path.resolve(),),tuple(chain['operation']/str(i) for i in range(16))):
        with pytest.raises(patch.DeliveryRefused,match='CHAIN_INVALID'):
            patch.predecessor_witness(path,trail=trail)


def test_signed_anchor_resolves_to_exact_actual_local_image(chain):
    v=json.loads(chain['anchor'].read_text());v['runtime_image']='registry/sentinel@sha256:'+'9'*64
    chain['anchor'].write_text(json.dumps(v))
    chain['built']['predecessor_receipt']['sha256']=patch.sha256_file(chain['anchor'])
    seen=[]
    def inspect_image(ref):
        seen.append(ref)
        return dict(Id=OLD_IMAGE,Config={'Labels':{'org.opencontainers.image.revision':OLD}})
    actual=patch.predecessor_witness(complete(chain),inspect_image=inspect_image)
    assert actual['runtime_image']==NEW_IMAGE and seen==[v['runtime_image']]


def test_foreign_signed_anchor_image_revision_is_refused(chain):
    with pytest.raises(patch.DeliveryRefused,match='RUNTIME_CHANGED'):
        patch.predecessor_witness(chain['anchor'],inspect_image=lambda ref:
            dict(Id=OLD_IMAGE,Config={'Labels':{'org.opencontainers.image.revision':NEW}}))


def test_original_signed_foundation_reference_survives_image_resolution(chain):
    value=json.loads(chain['anchor'].read_text())
    value['runtime_image']='registry/sentinel@sha256:'+'9'*64
    chain['anchor'].write_text(json.dumps(value))
    actual=patch.predecessor_witness(chain['anchor'],inspect_image=lambda ref:
        dict(Id=OLD_IMAGE,Config={'Labels':{'org.opencontainers.image.revision':OLD}}))
    assert actual['runtime_image']==OLD_IMAGE
    assert actual['foundation_reference']==value['runtime_image']


def test_removing_exact_candidate_image_guard_is_detected(chain,monkeypatch):
    raw=textwrap.dedent(inspect.getsource(patch.predecessor_witness))
    guard="built.get('image')==candidate['image']"
    assert raw.count(guard)==1
    namespace={}
    exec(compile(raw.replace(guard,'True'),'<backed-chain-subject-falsifier>','exec'),patch.__dict__,namespace)
    monkeypatch.setattr(patch,'predecessor_witness',namespace['predecessor_witness'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_tampered_build_subject_is_refused(chain,'image')
