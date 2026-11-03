"""An already-current financial schema cannot skip the new presentation install."""
import inspect
import os
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
import sentinel_installation_phase as phase
import sentinel_runtime_selection as selection


def exercise(monkeypatch,state):
    calls=[]
    monkeypatch.setattr(phase.bootstrap.BootstrapDeploy,'quiesce_backup_and_migrate',lambda _self:calls.append('drained'))
    monkeypatch.setattr(selection,'_write_pointer',lambda image:calls.append(('pointer',image)))
    obj=object.__new__(phase.InstallationDeploy)
    obj.phase=lambda _message:None
    obj._automation_status=lambda:state
    obj.base_compose=['docker','compose','qualified-config']
    obj.runtime_repo_digest='ghcr.io/flabber1835/stocker/sentinel@sha256:'+'a'*64
    obj.runner=SimpleNamespace(run=lambda command,**kwargs:calls.append(('schema',command,kwargs)))
    obj.quiesce_backup_and_migrate()
    return calls


def test_exact_presentation_schema_installs_after_drain_and_fence_before_runtime_pointer(monkeypatch):
    calls=exercise(monkeypatch,{'enabled':False,'kill_switch_engaged':True})
    assert calls[0]=='drained' and calls[1][0]=='schema' and calls[2][0]=='pointer'
    command=calls[1][1]
    assert command[-4:-1]==['python','sentinel','-c']
    assert 'review_schema import install_quiescent' in command[-1]
    assert 'SENTINEL_DATABASE_URL' in command[-1] and 'authority' not in command[-1]
    assert calls[1][2]['timeout']==150


@pytest.mark.parametrize('state',[{}, {'enabled':True,'kill_switch_engaged':True},
                                 {'enabled':False,'kill_switch_engaged':False}])
def test_fence_refusal_happens_before_any_metadata_or_pointer_writer(monkeypatch,state):
    with pytest.raises(phase.core.DeployRefused,match='disabled.killed'):
        exercise(monkeypatch,state)


def test_removed_installation_fence_is_detected(monkeypatch):
    source=textwrap.dedent(inspect.getsource(phase.InstallationDeploy.quiesce_backup_and_migrate))
    guard="if state.get('enabled') is not False or state.get('kill_switch_engaged') is not True:"
    assert source.count(guard)==1
    namespace={}
    # Preserve the real method's parent and zero-argument super class cell.
    body=source.replace(guard,'if False:')
    class_source='class Broken(InstallationDeploy):\n'+textwrap.indent(body,'    ')
    exec(compile(class_source,'removed-dashboard-installation-fence','exec'),
         dict(phase.__dict__,InstallationDeploy=phase.bootstrap.BootstrapDeploy),namespace)
    monkeypatch.setattr(phase,'InstallationDeploy',namespace['Broken'])
    with pytest.raises(pytest.fail.Exception):
        test_fence_refusal_happens_before_any_metadata_or_pointer_writer(monkeypatch,{})
