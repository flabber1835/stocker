"""Unsent-plan renewal never becomes a general execution source waiver."""
import hashlib
from pathlib import Path

import pytest

from sentinel import dual_plan_renewal_upgrade as upgrade, runtime_admission as admission
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_only_exact_retained_readiness_sources_are_pinned(name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert actual == record['after']
    reviewed = record['after']
    for previous in record['before']:
        assert upgrade.source_allowed(name, previous, reviewed)
        assert not upgrade.source_allowed(name, previous, 'f'*64)
    assert not upgrade.source_allowed(name, '0'*64, actual)
    assert not upgrade.source_allowed('core/kernel.py', record['before'][0], actual)


def test_renewal_profile_and_code_tamper_refuse(tmp_path, monkeypatch):
    path = tmp_path/'profile.json'
    path.write_text(upgrade.PROFILE.read_text()+' ')
    with monkeypatch.context() as local:
        local.setattr(upgrade, 'PROFILE', path)
        with pytest.raises(ValueError, match='PROFILE_CHANGED'): upgrade.profile()
    path = tmp_path/'dual_plan_renewal_upgrade.py'
    source = Path(upgrade.__file__).read_text()
    assert 'previous in record' in source
    path.write_text(source.replace('previous in record', 'previous not in record'))
    monkeypatch.setattr(upgrade, '__file__', str(path))
    with pytest.raises(ValueError, match='MODULE_CHANGED'): upgrade.profile()


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_source_upgrade_requires_full_authenticated_origin_and_environment(closure, name):
    _, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))


def test_neighboring_command_guard_change_still_refuses(closure):
    root, checkpoint, context, manifest, source = _execution_closure(closure, 'paper/preparation.py', source_profile=upgrade)
    path = root/'paper/preparation.py'
    raw = path.read_text()
    assert 'command.state is not CommandState.PLANNED' in raw
    path.write_text(raw.replace('command.state is not CommandState.PLANNED', 'False'))
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED:paper/preparation.py'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


__all__ = ['closure']
