"""Installed activation parses once and reads financial lineage only fenced."""
from contextlib import nullcontext
import json
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
        if len(quiesces)==2:
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
    monkeypatch.setattr(activate.bootstrap,'discover',lambda actual:actual)
    monkeypatch.setattr(activate.bootstrap.hardened,'Config',lambda actual:obj.cfg)
    monkeypatch.setattr(activate.bootstrap,'BootstrapDeploy',lambda *a,**k:obj)
    monkeypatch.setattr(core,'Runner',lambda *a:obj.runner)
    monkeypatch.setattr(core,'_attempt_dir',lambda *a:tmp_path/'attempt')
    monkeypatch.setattr(core,'_utcnow',lambda:gate.NOW)
    monkeypatch.setattr(installation.InstallationDeploy,'build_promote',
        lambda actual:setattr(actual,'runtime_repo_digest',gate.RUNTIME))
    monkeypatch.setattr(activate,'financial_bundle',lambda *a:(bundle.path,bundle.sha256))
    monkeypatch.setattr(core,'deployment_request',lambda **k:pytest.fail('duplicate full reviewed validation'))
    software=core.verify_reviewed_software_environment
    software_calls=[]
    def verify(*a,**k):
        software_calls.append(True)
        return software(*a,**k)
    monkeypatch.setattr(core,'verify_reviewed_software_environment',verify)
    request=dict(source_commit=gate.COMMIT,mode='dual',installation_sha256='a'*64)
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


def test_removed_final_fenced_guard_is_detected(monkeypatch,tmp_path):
    monkeypatch.setattr(core.AutonomousDeploy,'verify_reviewed_shadow_bindings_quiesced',lambda self:None)
    with pytest.raises(pytest.fail.Exception):
        test_installed_entry_keeps_one_fenced_lineage_read(monkeypatch,tmp_path,'publication')
