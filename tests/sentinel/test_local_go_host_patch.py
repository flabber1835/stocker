"""The local overlay runs the same real-child contracts over pinned base code."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
from tools import sentinel_local_go_host_patch as patch
from tests.sentinel import test_go_probe_artifact_identity as contract


@pytest.fixture
def base_sources():
    new_go = (contract.ROOT/'scripts/sentinel_go_validate.py').read_bytes()
    new_entry = (contract.ROOT/'scripts/sentinel_go_validate_entry.py').read_bytes()
    old_go, count = re.subn(rb'^ *"--env", "SENTINEL_TEST_IMAGE_DIGEST",\n', b'', new_go, flags=re.M)
    assert count == 3
    old_entry = new_entry.replace(b'    "SENTINEL_TEST_IMAGE_DIGEST",\n', b'')
    # These independently exported Git dda0195c hashes pin the complete old
    # modules; an inverse transformation alone is not historical evidence.
    assert patch.sha(old_go) == '66cd2d8493e7e722bb5fad95003a3e969e9e56a7ed88b863d2b4bc07f60cca79'
    assert patch.sha(old_entry) == 'f1155a3e73d2cd8abf15150f939f171c3cbbd6c382a27b950980cc7e50f57c8e'
    return old_go, old_entry, new_go, new_entry


@pytest.fixture
def local_overlay(base_sources, tmp_path, monkeypatch):
    scripts = tmp_path/'installed/scripts'
    scripts.mkdir(parents=True)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    modules = []
    for name, raw in zip(('sentinel_go_validate', 'sentinel_go_validate_entry'), base_sources[:2]):
        path = scripts/(name+'.py')
        path.write_bytes(raw)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    go, entry = modules
    monkeypatch.setattr(contract, 'go', go)
    monkeypatch.setattr(contract, 'entry', entry)
    monkeypatch.setattr(contract.source_final, 'go', go)
    patch.install(go, entry, old_go=base_sources[0], old_entry=base_sources[1],
        new_go=base_sources[2], new_entry=base_sources[3],
        filename=str(contract.ROOT/'scripts/sentinel_go_validate.py'))


@pytest.mark.parametrize('route', contract.ROUTES[:-1])
def test_local_overlay_passes_the_real_child_contract(local_overlay, route, monkeypatch):
    contract.test_owned_go_child_receives_complete_actual_artifact_identity(route, monkeypatch)


@pytest.mark.parametrize('route', contract.ROUTES[:-1])
@pytest.mark.parametrize('defect', ('missing', 'malformed', 'foreign'))
def test_local_overlay_preserves_identity_refusals(local_overlay, route, defect, monkeypatch):
    contract.test_child_does_not_invent_or_repair_unproven_test_identity(route, defect, monkeypatch)


@pytest.mark.parametrize('route', contract.ROUTES[:-1])
def test_local_overlay_forwarding_has_real_falsifiers(local_overlay, route, monkeypatch):
    contract.test_removing_test_identity_forwarding_is_detected_by_real_child(route, monkeypatch)


@pytest.mark.parametrize('module', (0, 1))
def test_local_overlay_cannot_change_neighboring_code(base_sources, module):
    values = list(base_sources)
    values[module+2] += b'\nUNREVIEWED_NEIGHBOR = True\n'
    with pytest.raises(patch.Refused, match='NEIGHBOR_CHANGED'):
        patch.reviewed_definitions(*values)


def test_removing_whole_module_comparison_is_detected(base_sources, monkeypatch):
    monkeypatch.setattr(patch, '_dump', lambda _: 'comparison removed')
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_local_overlay_cannot_change_neighboring_code(base_sources, 0)


def test_local_overlay_requires_the_exact_installed_base_bytes(base_sources):
    values = list(base_sources)
    values[0] += b'\n# different installed source\n'
    with pytest.raises(patch.Refused, match='BASE_BYTES_CHANGED'):
        patch.reviewed_definitions(*values)


def test_interpreter_launcher_delegates_ordinary_python_calls(tmp_path):
    launcher = tmp_path/'host-python'
    launcher.write_text(patch.interpreter_source(source=contract.ROOT,
        deployment=tmp_path/'installed', manifest=tmp_path/'manifest.json', python=sys.executable))
    launcher.chmod(0o700)
    completed = subprocess.run([str(launcher), '-B', '-c', 'print("ordinary interpreter")'],
        capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0 and completed.stdout.strip() == 'ordinary interpreter'


def test_interpreter_launcher_scopes_only_the_exact_original_entry(tmp_path):
    source, deployed = tmp_path/'patch', tmp_path/'installed'
    (source/'tools').mkdir(parents=True)
    # Only transport is a fixture here; the real loader has the whole-module
    # and real-child qualifications above.
    (source/'tools/sentinel_local_go_host_patch.py').write_text('import sys,json;print(json.dumps(sys.argv[1:]))')
    manifest = tmp_path/'manifest.json'
    launcher = tmp_path/'host-python'
    launcher.write_text(patch.interpreter_source(source=source, deployment=deployed,
        manifest=manifest, python=sys.executable))
    launcher.chmod(0o700)
    completed = subprocess.run([str(launcher), str(deployed/'scripts/sentinel_go_verified_entry.py'),
        '--target', 'DUAL_RUN_OBSERVATION'], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == [str(manifest), '--target', 'DUAL_RUN_OBSERVATION']
    other = tmp_path/'sentinel_go_verified_entry.py'
    other.write_text('print("other entry")')
    completed = subprocess.run([str(launcher), str(other)], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0 and completed.stdout.strip() == 'other entry'
