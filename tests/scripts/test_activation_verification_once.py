"""Installed activation parses once and reads financial lineage only fenced."""
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tests.scripts import test_sentinel_reviewed_deploy_gate as gate
import sentinel_activation_coordinator as activate
import sentinel_installation_phase as installation

core = activate.core


@pytest.mark.parametrize('fault',[None,'publication','configuration','lineage'])
def test_installed_entry_keeps_one_fenced_lineage_read(monkeypatch,tmp_path,fault):
    bundle=gate._bundle(tmp_path/'bundle',dual=True)
    env=gate._env()
    events=[]
    fenced=[False]
    lineage=[]
    host=gate.ReadOnlyHost()
    def invoke(argv,**kwargs):
        if 'sentinel.shadow_service' in argv:
            assert fenced[0]
            lineage.append('read')
            if fault=='lineage':
                return subprocess.CompletedProcess(argv,2,'unrecognized retained lineage','')
        return host(argv,**kwargs)
    obj=core.AutonomousDeploy(SimpleNamespace(account_id='paper-account'),SimpleNamespace(env=env),tmp_path/'attempt')
    obj.phase=lambda text:None
    obj._reviewed_invoke=invoke
    obj.git_preflight=lambda: (setattr(obj,'commit',gate.COMMIT),events.append('git'))
    obj.read_paper_account=lambda: events.append('account')
    obj.build_promote=lambda: events.append('build')
    obj.activation_transition=nullcontext
    quiesces=[]
    def quiesce():
        quiesces.append(True)
        fenced[0]=True
        if len(quiesces)==1:
            if fault=='publication':host.publication=dict(gate.PUBLICATION,publication_fingerprint='9'*64)
            if fault=='configuration':env['SENTINEL_SHADOW_STARTING_CASH']='200000'
        return True
    obj._quiesce_database=quiesce
    for name in ('check_paper_account_deployment_integrity','confirm_disabled_activation_fence',
            'check_durable_deployment_integrity','configure_reviewed_mode_while_fenced',
            'start_operator_services','ensure_ownership','start_fenced_runtime'):
        setattr(obj,name,lambda name=name:events.append(name))
    obj.rotate_observation_authority=lambda: ('certificate','2026-08-20')
    obj._wait_for_dual_shadow_session=lambda day:dict(session=day)
    obj.prepare_activate_start=lambda *a:events.append('plan')
    obj.verify_operational=lambda certificate:dict(ready=True)
    obj.persist_success=lambda health:events.append('success')
    monkeypatch.setattr(activate.sentinel_env,'validate',lambda *a,**k:None)
    monkeypatch.setattr(core,'merged_environment',lambda:env)
    monkeypatch.setattr(activate.bootstrap,'discover',lambda actual, **_kwargs:actual)
    monkeypatch.setattr(activate.roles, 'activation_types',
        lambda mode: (lambda actual: obj.cfg, lambda *args, **kwargs: obj))
    monkeypatch.setattr(core,'Runner',lambda *a:obj.runner)
    monkeypatch.setattr(core,'_attempt_dir',lambda *a:tmp_path/'attempt')
    monkeypatch.setattr(core,'_utcnow',lambda:gate.NOW)
    monkeypatch.setattr(installation,'select_certified_runtime',
        lambda actual:setattr(actual,'runtime_repo_digest',gate.RUNTIME))
    monkeypatch.setattr(activate,'financial_bundle',lambda *a:(bundle.path,bundle.sha256))
    monkeypatch.setattr(core,'deployment_request',lambda **k:pytest.fail('duplicate full reviewed validation'))
    software=core.verify_reviewed_software_environment
    software_calls=[]
    def verify(*a,**k):
        software_calls.append(True)
        return software(*a,**k)
    monkeypatch.setattr(core,'verify_reviewed_software_environment',verify)
    request=dict(source_commit=gate.COMMIT,mode='dual',installation_sha256='a'*64,
                 bundle=str(bundle.path),bundle_sha256=bundle.sha256)
    if fault:
        with pytest.raises(core.DeployRefused):
            activate.attempt(tmp_path/'activation-request.json',request,dict(runtime_image=gate.RUNTIME))
        assert 'configure_reviewed_mode_while_fenced' not in events
        assert 'plan' not in events
        assert not (tmp_path/'activation-result.json').exists()
    else:
        activate.attempt(tmp_path/'activation-request.json',request,dict(runtime_image=gate.RUNTIME))
        assert lineage==['read'] and events[-1]=='success'
        assert json.loads((tmp_path/'activation-result.json').read_text())['activation_state']=='ACTIVE'
    assert software_calls==[True]
    assert quiesces==[True]


def test_removed_final_fenced_guard_is_detected(monkeypatch,tmp_path):
    monkeypatch.setattr(core.AutonomousDeploy,'verify_reviewed_shadow_bindings_quiesced',lambda self:None)
    with pytest.raises(pytest.fail.Exception):
        test_installed_entry_keeps_one_fenced_lineage_read(monkeypatch,tmp_path,'publication')


def test_attended_policy_replacement_queues_and_reaches_only_plan_preparation(monkeypatch, tmp_path):
    env = tmp_path / '.env'
    env.write_text('SENTINEL_PAPER_BUY_POLICY=FRACTIONAL_MARKET_DAY_V1\n')
    receipt = tmp_path / 'installation-receipt.json'
    receipt.write_text(json.dumps(dict(
        schema='sentinel.installation-receipt/1', installation_state='INSTALLED',
        activation_state='FENCED', git_commit=gate.COMMIT, runtime_image='sentinel@' + gate.RUNTIME,
        automation_enabled=False, kill_switch_engaged=True)))
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'ENV_PATH', env)
    queued = []

    def handoff(path):
        queued.append(Path(path))
        request, _ = activate.validate_request(path)
        assert request['schema'] == 'sentinel.activation-request/4'
        return {'activation_state': 'QUEUED'}

    monkeypatch.setattr(activate, 'handoff', handoff)
    fingerprint = '1' * 64
    flags = ['--replace-unsent-plan', 'sentinel-' + fingerprint,
             '--replace-unsent-plan-fingerprint', fingerprint,
             '--policy-replacement-actor', 'operator',
             '--policy-replacement-reason', 'Monday fractional policy',
             '--confirm-unsent-policy-replacement']
    queue = ['--queue-from-installation', str(receipt), '--mode', 'dual']
    with pytest.raises(SystemExit):
        activate.main(queue + flags[:-1])
    with pytest.raises(SystemExit):
        activate.main(queue + flags + ['--unsent-blocked-cycle-id', '2'*64,
            '--unsent-decision-session', '2026-11-13', '--unsent-recovery-actor', 'operator',
            '--unsent-recovery-reason', 'other recovery', '--confirm-authorize-unsent-recovery'])
    assert queued == []
    assert activate.main(queue + flags) == 0
    request, _ = activate.validate_request(queued[0])
    obj = core.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    obj.reviewed_validation = SimpleNamespace(mode='dual')
    obj.requested_policy_replacement = request['policy_replacement']
    base = ['prepare-paper-plan', '--through', '2026-11-13']
    invoked = []

    def prepare(args, **_kwargs):
        invoked.append(args)
        return subprocess.CompletedProcess(args, 0, '{}', '')

    obj._authorized_cli = prepare
    obj._load_native_fee_protocol = lambda: SimpleNamespace(
        EXIT_NATIVE_FEE_WAIT=32, NATIVE_FEE_WAIT_MARKER='NATIVE_FEE_WAIT')
    assert obj._prepare_activation_plan(base, 'certificate', '2026-11-13', None) == ({}, None)
    assert invoked == [base + flags]
    env.write_text('SENTINEL_PAPER_BUY_POLICY=MARKET_DAY_V1\n')
    with pytest.raises(core.DeployRefused, match='configuration changed'):
        activate.validate_request(queued[0])
