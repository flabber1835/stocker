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
from sentinel.panel import review_schema
from tests.sentinel.test_installation_selector_fence import (
    conn, pg, test_public_selector_obeys_current_transactional_fence as _check_selector,
)


def exercise(monkeypatch):
    calls=[]
    monkeypatch.setattr(phase.bootstrap.BootstrapDeploy,'quiesce_backup_and_migrate',lambda _self:calls.append('drained'))
    monkeypatch.setattr(selection,'_write_pointer',lambda image:calls.append(('pointer',image)))
    obj=object.__new__(phase.InstallationDeploy)
    obj.phase=lambda _message:None
    obj._automation_status=lambda:pytest.fail('duplicated the guarded database read')
    obj.base_compose=['docker','compose','qualified-config']
    obj.runtime_repo_digest='ghcr.io/flabber1835/stocker/sentinel@sha256:'+'a'*64
    obj.runner=SimpleNamespace(run=lambda command,**kwargs:calls.append(('schema',command,kwargs)))
    obj.quiesce_backup_and_migrate()
    return calls


def test_exact_presentation_schema_installs_after_drain_and_fence_before_runtime_pointer(monkeypatch):
    calls=exercise(monkeypatch)
    assert calls[0]=='drained' and calls[1][0]=='schema' and calls[2][0]=='pointer'
    command=calls[1][1]
    assert command[-4:-1]==['python','sentinel','-c']
    assert 'review_schema import install_quiescent' in command[-1]
    assert 'SENTINEL_DATABASE_URL' in command[-1] and 'authority' not in command[-1]
    assert calls[1][2]['timeout']==150


def test_removed_installation_fence_is_detected(conn, monkeypatch, tmp_path):
    source=textwrap.dedent(inspect.getsource(review_schema.install_quiescent))
    guard='if row != (False, True):'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard, 'if False:'), 'removed-dashboard-installation-fence', 'exec'),
         vars(review_schema), namespace)
    monkeypatch.setattr(review_schema, 'install_quiescent', namespace['install_quiescent'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        _check_selector(conn, monkeypatch, tmp_path, 'enabled')
