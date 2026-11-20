"""Native recovery host owner with external Git, CI and Docker responses only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
import sentinel_chain_progress_recovery as progress_owner
import sentinel_order_amount_coverage_recovery as order_amount_owner

SHA='a'*40
IMAGE='ghcr.io/flabber1835/stocker/sentinel@sha256:'+'b'*64


@pytest.fixture(params=["progress", "order-amount", "backup-compaction", "acquisition-guard"])
def operation(monkeypatch,tmp_path,request):
    kind = request.param
    owner = progress_owner if kind == 'progress' else order_amount_owner
    uses_signed_pointer = owner is order_amount_owner
    root=tmp_path/'checkout';(root/'scripts').mkdir(parents=True)
    monkeypatch.setattr(owner,'__file__',str(root/'scripts'/Path(owner.__file__).name))
    (root/'.env').write_text('SENTINEL_BACKUP_DIR=/backup\nSENTINEL_POSTGRES_PASSWORD=synthetic\n'
        'SENTINEL_DEPLOYMENT_ID=fixture\nSENTINEL_PAPER_ACCOUNT_ID=PAfixture\n'
        'SENTINEL_LOCAL_PAPER_MODE=OWNER_AUTHORIZED_FUNCTION_FIRST_V1\n'
        'SENTINEL_LOCAL_PAPER_ACCOUNT_ID=PAfixture\nSENTINEL_LOCAL_PAPER_BACKUP_POLICY=REQUIRED_V1\n'
        'SENTINEL_PAPER_BUY_POLICY=PROTECTED_LIMIT_DAY_V1\nSENTINEL_PAPER_BUY_CAP_BPS=100\n'
        'ALPACA_BASE_URL=https://paper-api.alpaca.markets\n'
        'SENTINEL_GITHUB_READ_TOKEN=fixture-read-only-token\nSENTINEL_RUNTIME_IMAGE_REF='+IMAGE+'\n'
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR='+str(root/'authority')+'\n')
    receipt=root/'installation-receipt.json'
    value=dict(schema='sentinel.installation-receipt/1',installation_state='INSTALLED',
        activation_state='FENCED',automation_enabled=False,kill_switch_engaged=True,
        git_commit=SHA,runtime_image=IMAGE,deployment_id='fixture',paper_account_id='PAfixture')
    receipt.write_text(json.dumps(value))
    witness=root/'witness.json';witness.write_text('{"witness":{"fixture":true},"hmac_sha256":"fixture"}')
    witness.chmod(0o600)
    sha=hashlib.sha256(witness.read_bytes()).hexdigest()
    args=SimpleNamespace(kind=kind,installation_receipt=receipt,witness=witness,
        confirm_witness_sha256=sha,backup='base-20261029T072734Z',output=root/'transfer.json')
    content_sha=hashlib.sha256(json.dumps(json.loads(witness.read_text()),sort_keys=True,
        separators=(',',':')).encode()).hexdigest()
    state=dict(dirty=False,head=SHA,proof_image=IMAGE,graph='-f docker-compose.sentinel.yml',
        command_failed=False,result=dict(schema=('sentinel.'+kind+'-coverage-transfer/1' if uses_signed_pointer
            else 'sentinel.chain-progress-coverage-transfer/1'),
            witness_content_sha256=content_sha,backup=args.backup,
            prefixes={'OBSERVATION':'c'*64,'MIRROR':'d'*64},operational_ready=False,broker_contacted=False))
    calls=[]
    def git(argv,**kwargs):
        assert argv[:3]==['git','-C',str(root)]
        return ('dirty' if state['dirty'] else '') if 'status' in argv else state['head']
    monkeypatch.setattr(owner.subprocess,'check_output',git)
    monkeypatch.setattr(owner.certification,'verify_current',lambda **kwargs:{'certified_image':state['proof_image']})
    if uses_signed_pointer:
        monkeypatch.setattr(owner, '_pointer_digest', lambda: IMAGE)
        def read_client(*, token):
            assert token == 'fixture-read-only-token'
            return object()
        monkeypatch.setattr(owner.certification, 'GitHubReadClient', read_client)
    runtime_target = ':/'+kind+'-ddl-witness.json:ro' if uses_signed_pointer else ':/progress-witness.json:ro'
    class Runner:
        def __init__(self,env,log):
            assert env['SENTINEL_POSTGRES_PASSWORD']=='synthetic'
            self.log=log
        def run(self,argv,**kwargs):
            calls.append(argv)
            if argv[:2]==['bash','scripts/sentinel-compose.sh']:
                return subprocess.CompletedProcess(argv,0,state['graph'],'')
            assert '--no-deps' in argv and '-B' in argv and '-m' in argv
            if kind == 'backup-compaction':
                assert argv[argv.index('-m')+1] == 'sentinel.backup_compaction_coverage_recovery'
            elif kind == 'acquisition-guard':
                assert argv[argv.index('-m')+1] == 'sentinel.acquisition_coverage_recovery'
                assert argv[argv.index('--expect-account')+1] == value['paper_account_id']
                assert argv[argv.index('--deployment-id')+1] == value['deployment_id']
            mounted=Path(argv[argv.index('--volume')+1].removesuffix(runtime_target))
            assert mounted!=witness and mounted.read_bytes()==witness.read_bytes()
            assert mounted.stat().st_mode&0o777==0o444
            assert mounted.parent.stat().st_mode&0o777==0o700
            assert witness.stat().st_mode&0o777==0o600
            assert '--confirm-witness-sha256' in argv and sha in argv
            assert kwargs['timeout']==660
            if state['command_failed']:raise owner.core.DeployRefused('native recovery refused')
            return subprocess.CompletedProcess(argv,0,json.dumps(state['result']),'')
    monkeypatch.setattr(owner.core,'Runner',Runner)
    return owner,args,state,calls,value,runtime_target


def test_one_shot_native_owner_binds_installed_source_and_exact_witness(operation):
    owner,args,state,calls,_receipt,runtime_target=operation
    owner.execute(args)
    result=owner.read_document(args.output)
    assert result['source_commit']==SHA and result['runtime_image']==IMAGE
    assert result['witness_file_sha256']==args.confirm_witness_sha256
    assert result['operational_ready'] is False
    assert len(calls)==2
    runtime_mount=Path(calls[-1][calls[-1].index('--volume')+1].removesuffix(runtime_target))
    assert not runtime_mount.exists() and not runtime_mount.parent.exists()
    with pytest.raises(owner.core.DeployRefused,match='existing recovery'):
        owner.execute(args)
    assert len(calls)==2


@pytest.mark.parametrize('fault',['dirty','head','image','witness','receipt','fence','existing'])
def test_changed_installation_or_confirmation_refuses_before_docker(operation,fault):
    owner,args,state,calls,receipt,_runtime_target=operation
    if fault=='dirty':state['dirty']=True
    if fault=='head':state['head']='e'*40
    if fault=='image':state['proof_image']=IMAGE.replace('b'*64,'e'*64)
    if fault=='witness':args.confirm_witness_sha256='e'*64
    if fault=='receipt':receipt['runtime_image']='other'
    if fault=='fence':receipt['automation_enabled']=True
    if fault in {'receipt','fence'}:args.installation_receipt.write_text(json.dumps(receipt))
    if fault=='existing':args.output.with_suffix('.commands.log').touch()
    with pytest.raises(owner.core.DeployRefused):owner.execute(args)
    assert calls==[] and not args.output.exists()


@pytest.mark.parametrize('fault',['native','graph','ready','broker','prefix','subject','extra'])
def test_native_refusal_or_malformed_result_never_publishes_success(operation,fault):
    owner,args,state,_calls,_receipt,_runtime_target=operation
    if fault=='native':state['command_failed']=True
    if fault=='graph':state['graph']=''
    if fault=='ready':state['result']['operational_ready']=True
    if fault=='broker':state['result']['broker_contacted']=True
    if fault=='prefix':state['result']['prefixes']['MIRROR']='bad'
    if fault=='subject':state['result']['backup']='base-other'
    if fault=='extra':state['result']['unexpected']='data'
    with pytest.raises(owner.core.DeployRefused):owner.execute(args)
    assert not args.output.exists() and args.output.with_suffix('.commands.log').exists()


def test_competing_host_lifecycle_owner_prevents_docker(operation,monkeypatch):
    owner,args,_state,calls,_receipt,_runtime_target=operation
    def busy(*_args):raise BlockingIOError('another host writer owns the lock')
    if owner is order_amount_owner:
        monkeypatch.setattr(owner, 'host_lifecycle_lock', busy)
    else:
        monkeypatch.setattr(owner.fcntl, 'flock', busy)
    with pytest.raises(BlockingIOError):owner.execute(args)
    assert calls==[] and not args.output.with_suffix('.commands.log').exists()


@pytest.mark.parametrize('flags,expected', [
    ([], 'order-amount'),
    (['--backup-compaction'], 'backup-compaction'),
    (['--acquisition-guard'], 'acquisition-guard'),
    (['--acquisition-guard', '--backup-compaction'], None),
])
def test_host_selects_only_one_reviewed_transition(monkeypatch, flags, expected):
    selected = []
    monkeypatch.setattr(order_amount_owner, 'execute', lambda args: selected.append(args.kind))
    common = ['--installation-receipt', 'receipt', '--witness', 'witness',
              '--confirm-witness-sha256', '0'*64, '--backup', 'base', '--output', 'out']
    if expected is None:
        with pytest.raises(SystemExit) as exc:
            order_amount_owner.main(common + flags)
        assert exc.value.code == 2 and not selected
    else:
        assert order_amount_owner.main(common + flags) == 0
        assert selected == [expected]


@pytest.mark.parametrize('fault', [None, 'dirty', 'different_pointer', 'different_publication', 'no_image'])
def test_witness_runtime_requires_exact_checkout_pointer_and_ci_image(tmp_path, monkeypatch, fault):
    owner = order_amount_owner
    def git(argv, **_kwargs):
        return ('untracked' if fault == 'dirty' else '') if 'status' in argv else SHA
    monkeypatch.setattr(owner.subprocess, 'check_output', git)
    monkeypatch.setattr(owner, '_pointer_digest', lambda: 'other' if fault == 'different_pointer' else IMAGE)
    monkeypatch.setattr(owner.certification, 'verify_current', lambda **_kwargs: {
        'certified_image': 'other' if fault == 'different_publication' else IMAGE})
    env = {'SENTINEL_RUNTIME_IMAGE_REF': IMAGE} if fault != 'no_image' else {}
    if fault:
        with pytest.raises(owner.core.DeployRefused):
            owner.verify_recovery_runtime(tmp_path, env, require_validated_pointer=True)
    else:
        assert owner.verify_recovery_runtime(tmp_path, env, require_validated_pointer=True) == SHA


@pytest.mark.parametrize('operation', ['order-amount', 'backup-compaction'], indirect=True)
def test_historical_apply_verifies_configured_release_then_rechecks_pointer_under_lock(operation, monkeypatch):
    owner, args, _state, calls, _receipt, _runtime_target = operation
    stages = []
    def absent_pointer():
        stages.append('pointer')
        return None
    def certification(**_kwargs):
        stages.append('certification')
        return {'certified_image': IMAGE}
    monkeypatch.setattr(owner, '_pointer_digest', absent_pointer)
    monkeypatch.setattr(owner.certification, 'verify_current', certification)
    with pytest.raises(owner.core.DeployRefused, match='validated runtime changed before coverage recovery'):
        owner.execute(args)
    assert stages == ['pointer', 'certification', 'pointer']
    assert not calls and not args.output.exists() and not args.output.with_suffix('.commands.log').exists()
