"""Actual export/identity/adapter behavior; no local canonical replay."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_parallel_discovery as scope
import system_campaign_parallel_discovery_export as export
import system_campaign_parallel_discovery_job as job
import system_campaign_parallel_discovery_parent as admission
import system_campaign_parallel_discovery_run as replay


@pytest.fixture
def frozen_request(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    path=tmp_path/'frozen_request.json';path.write_text(json.dumps(dict(protocol_sha256='a'*64)))
    return path


@pytest.mark.parametrize('arm',scope.ARMS)
def test_actual_own_arm_cipher_gcm_inventory_marker_roundtrip(tmp_path,frozen_request,arm):
    proof=export.qualify_export(tmp_path/'probe',frozen_request,arm)
    assert proof['status']=='PARALLEL_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED' and proof['arm']==arm
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']
    assert proof['source_adapter_sha256']==hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest()
    assert proof['retained_export_body_sha256']==hashlib.sha256(Path(export.proven.__file__).read_bytes()).hexdigest()


@pytest.mark.parametrize('arm',['P00','P01','P02','P08','P12','B'])
def test_completed_running_or_unselected_candidates_cannot_export(arm):
    with pytest.raises(ValueError,match='ONLY_SELECTED_ARMS'):export.seal_adapter(arm)


def receipt():
    return dict(arm='P03',stage=export.STAGE,financial_authority=False,
        account_performance_computed=False,production_contacted=False,
        status='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW',
        worker=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))


def test_dynamic_adapter_still_rejects_cross_arm_and_wrong_stage(tmp_path,frozen_request):
    for arm,stage in [('P04',export.STAGE),('P03','campaign-factual-suffix')]:
        with pytest.raises(ValueError,match='EXACT_ARM_EXPORT_SCOPE'):
            export.seal_adapter('P03')(tmp_path,tmp_path/'bad.crseal',b'x'*32,frozen_request,arm,
                stage=stage,protocol_sha256='a'*64)


def test_unknown_never_snapshots_private_root(tmp_path,frozen_request,monkeypatch):
    monkeypatch.setattr(export,'sealed',lambda *a:(_ for _ in ()).throw(AssertionError('Snapshot forbidden')))
    value=receipt();value.pop('worker');value['status']='DISCOVERY_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    saved=export.finish_export(value,tmp_path/'ABSENT',tmp_path/'public.json',b'x'*32,frozen_request,known=False)
    assert not saved['encrypted_output_exported'] and 'encrypted_output' not in saved


def test_stop_receipt_durable_before_export_failure(tmp_path,frozen_request,monkeypatch):
    value=receipt();public=tmp_path/'public.json'
    def fail(*a):
        assert json.loads(public.read_bytes())['worker']==value['worker']
        raise ValueError('REFUSED_SYNTHETIC_EXPORT')
    monkeypatch.setattr(export,'sealed',fail)
    saved=export.finish_export(value,tmp_path/'private',public,b'x'*32,frozen_request,known=True)
    assert json.loads(public.read_bytes())==saved
    assert saved['status']=='KNOWN_STOP_EXPORT_REFUSED_NO_PLAINTEXT_FALLBACK'
    assert saved['pre_export_status']=='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW'


@pytest.mark.parametrize('extra',[dict(nav=123.),dict(status=dict(payload='private'))])
def test_public_receipt_refuses_private_or_nested_fields(tmp_path,extra):
    value=receipt();value.update(extra)
    with pytest.raises(ValueError,match='PUBLIC_'):export.write_public_receipt(tmp_path/'public.json',value)


def test_actual_public_guard_removal_falsifier(tmp_path):
    fn=scope.literals(scope.body('system_campaign_p01_discovery_export.py','write_public_receipt'),{'P01':'P03'})
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='P01_PUBLIC_RECEIPT_ONLY_DECLARED_NONFINANCIAL_FIELDS' for v in ast.walk(n)))]
    value=receipt();value['nav']='SYNTHETIC_PRIVATE_VALUE'
    scope.compile_body(fn,vars(export.proven))(tmp_path/'public.json',value)
    assert json.loads((tmp_path/'public.json').read_bytes())['nav']=='SYNTHETIC_PRIVATE_VALUE'


def test_admission_changes_only_financial_certification_branch_not_crypto_or_prefixes():
    text=ast.unparse(admission.admission_body())
    assert 'validate_diagnostic_origin(spec, inventory, dest)' in text
    assert 'authenticate(z, asset, key)' in text and 'seen == set(inventory)' in text
    assert 'FACTUAL_OLD_ACTUAL_STOP' in text and 'FACTUAL_SELECTED_PREFIX' in text
    assert 'prove_review_refusal' not in text
    assert 'FACTUAL_OLD_REVIEW_BYTES' not in text
    scope.compile_body(admission.admission_body(),vars(admission.original))


@pytest.mark.parametrize('arm',scope.ARMS)
def test_actual_parent_scope_and_wrong_arm_state_refusal(arm):
    spec=scope.specification(arm)
    parent=dict(sha256=spec['outer_sha256'],source_cursor=spec['selected_session'],completed=spec['measured_closes'],
        base=spec['base'],journals=spec['journals'],repairs=spec['repairs'],run=dict(
            checkpoint_sha256=spec['inner_sha256'],state_sha256=spec['state_sha256'],input_sha256=spec['input_sha256']))
    scope.check_parent(parent,spec)
    parent['completed']+=1
    with pytest.raises(ValueError,match='EXACT_OWN_STRICT_PARENT'):scope.check_parent(parent,spec)


def test_actual_parent_identity_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(scope.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='check_parent']
    fn.body=[ast.Pass()]
    scope.compile_body(fn,vars(scope))({'completed':'wrong'},{'completed':'other'})
    with pytest.raises((KeyError,ValueError)):scope.check_parent({'completed':'wrong'},{'completed':'other'})


def test_only_prefix_observation_and_checkpoint_scheduling_differ():
    dummy=SimpleNamespace(observe=lambda value:None)
    source=replay.iterator(dummy)
    assert callable(source)
    fn=replay.diagnostic_tree();text=ast.unparse(fn)
    assert 'runtime.advance(run, published)' in text
    assert 'anchor_gate.prepare(buffer, run)' in text and 'anchor_gate.after(run, next_run)' in text
    assert 'if len(observed) == 1:' in text and 'packet.day in checkpoint_days' in text
    assert 'retained_source_anchors=anchors.commitment()' in text
    assert 'shutil.copyfile(' in text
    scope.compile_body(fn,vars(replay.original))


def test_profile_specific_adapter_hash_required(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    from test_p01_discovery_anchors import LAYOUT
    h=hashlib.sha256(LAYOUT).hexdigest();tree=replay.anchor_prepare_tree(LAYOUT,h)
    assert '_retained_source_anchor(' in ast.unparse(tree)
    with pytest.raises(ValueError,match='EXACT_FROZEN_INPUT_ADAPTER'):
        replay.anchor_prepare_tree(LAYOUT,'0'*64)


def test_actual_anchor_use_reproduces_old_refusal_and_qualifies_next_transition(tmp_path):
    class Temporal(ValueError):pass
    state=SimpleNamespace(last_processed_session='2020-01-31',state_hash='1'*64,data_version=1,
        feed=dict(series={'SYNTHETIC':dict(signal_basis_anchor=['2018-01-02',12.5,13.])}),
        to_dict=lambda:dict(state='SYNTHETIC_UNCHANGED'))
    cache=replay.anchor_source.RetainedAnchors(tmp_path,state,source_sha256='1'*64,input_sha256='3'*64)
    cache.stream=(tmp_path/'anchors.jsonl').open('xb')
    cache.m=SimpleNamespace(adapter=SimpleNamespace(protected=lambda v:{'SYNTHETIC'},TemporalViolation=Temporal),
        VendorBar=lambda day,sid,ticker,raw,*a,signal_close:SimpleNamespace(session=day,security_id=sid,
            ticker=ticker,raw_close=raw,signal_close=signal_close))
    cache.store(SimpleNamespace(session='2018-01-02',security_id='SYNTHETIC',ticker='SYNTHETIC',
        raw_close=12.5,signal_close=13.),'FROZEN_SOURCE_PACKET')
    def original(*a,**k):raise Temporal('LIVE_ANCHOR_OUTSIDE_WINDOW: SYNTHETIC')
    cache.original=original
    buffer=SimpleNamespace(current=SimpleNamespace(day='2020-02-03',bars=()),rings={},axis=['2020-01-31']*300)
    def prepare(*a,**k):
        bar=cache.retained(buffer,state,'SYNTHETIC',state.feed['series']['SYNTHETIC']['signal_basis_anchor'])
        return SimpleNamespace(bars=(),signal_basis_anchors={'SYNTHETIC':bar},
            window_features=dict(sessions=list(buffer.axis)))
    buffer.prepare=prepare;gate=replay.AnchorQualification(tmp_path,cache);run=SimpleNamespace(state=state)
    try:
        gate.prepare(buffer,run)
        assert gate.pending and len(gate.pending['source_falsifiers'])==2
        gate.after(run,SimpleNamespace(state=SimpleNamespace(last_processed_session='2020-02-03',state_hash='2'*64)))
        assert len(gate.proofs)==1 and (tmp_path/'actual-anchor-qualification.json').exists()
    finally:cache.stream.close()


def test_each_worker_exact_fences_mount_and_entrypoint(monkeypatch,tmp_path):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    for arm in scope.ARMS:
        for mode,role in [('qualify','qualify'),('discovery','worker')]:
            name=f'capital-system-parallel-discovery-{arm.lower()}-{role}-123-1'
            cmd=job.worker_command(name,arm,mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
            assert cmd[cmd.index('-B'):]==job.entrypoint(arm,mode)
            assert any('target=/old,readonly' in v for v in cmd)
            value=dict(Name='/'+name,Image=job.EXECUTION_IMAGE,Id='1'*64,
                HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
                    PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
                Config=dict(Cmd=job.entrypoint(arm,mode),WorkingDir='/variant',User='1001:1001',Env=[],
                    Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
                Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old')])
            monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
            assert job.inspect(name,'1'*64)==value
            value['Mounts'][-1]['RW']=True
            with pytest.raises(ValueError,match='MOUNTS'):job.inspect(name,'1'*64)


def test_workflow_is_disjoint_eight_way_matrix_without_rerun_dispatch():
    raw=(Path(__file__).resolve().parents[3]/'.github/workflows/capital-system-parallel-discovery.yml').read_text()
    assert 'max-parallel: 8' in raw and 'fail-fast: false' in raw
    assert 'group: system-optimization-002-eight-parallel-discovery' in raw
    assert 'workflow_dispatch' not in raw and 'retention-days: 7' in raw
    assert 'arm: [P03, P04, P05, P06, P07, P09, P10, P11]' in raw
