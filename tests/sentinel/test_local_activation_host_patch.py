"""The pinned local activation overlay preserves actual child identity checks."""
import importlib.util
import gzip
from pathlib import Path
import sys

import pytest

from tools import sentinel_local_activation_host_patch as patch
from tests.sentinel import test_go_probe_artifact_identity as contract


@pytest.fixture
def sources():
    # Exact Git dda0195c module bytes. This historical overlay must not derive
    # its predecessor from a current deployment script that keeps evolving.
    fixture = Path(__file__).with_name('fixtures')/'activation-host-dda0195c.py.gz'
    old = gzip.decompress(fixture.read_bytes())
    assert patch.sha(old) == patch.BASE_SHA
    needle = b'        "SENTINEL_RUNTIME_IMAGE_DIGEST",\n'
    assert old.count(needle) == 1
    new = old.replace(needle, needle + b'        "SENTINEL_TEST_IMAGE_DIGEST",\n')
    return old, new


def test_historical_fixture_follows_imported_test_not_metadata_mirror(
        monkeypatch, tmp_path, request):
    # CI imports tests from /work/tests while ROOT points at /work/repo, which
    # deliberately contains only the metadata/source mirrors requested by COPY.
    monkeypatch.setattr(contract, 'ROOT', tmp_path)
    old, _new = request.getfixturevalue('sources')
    assert patch.sha(old) == patch.BASE_SHA


@pytest.fixture
def overlay(sources, tmp_path, monkeypatch):
    path = tmp_path/'sentinel_autonomous_deploy.py'; path.write_bytes(sources[0])
    spec = importlib.util.spec_from_file_location('sentinel_autonomous_deploy', path)
    module = importlib.util.module_from_spec(spec)
    # ROOT is a file-relative default; command transport uses its fixture cwd.
    monkeypatch.setitem(sys.modules, 'sentinel_autonomous_deploy', module)
    spec.loader.exec_module(module)
    patch.install(module, *sources)
    monkeypatch.setattr(contract, 'deploy', module)


def test_overlay_passes_real_child(overlay, monkeypatch):
    contract.test_owned_go_child_receives_complete_actual_artifact_identity('activation', monkeypatch)


@pytest.mark.parametrize('defect', ('missing', 'malformed', 'foreign'))
def test_overlay_preserves_real_child_refusals(overlay, defect, monkeypatch):
    contract.test_child_does_not_invent_or_repair_unproven_test_identity('activation', defect, monkeypatch)


def test_overlay_has_real_forwarding_falsifier(overlay, monkeypatch):
    # Installed definition comes from AST, so its qualified source is explicit.
    command, values = contract.command_for('activation', contract.configured(), monkeypatch)
    index = command.index(patch.KEY)
    del command[index-1:index+1]
    child = contract.child_environment(command, values)
    result = contract.subprocess.run([sys.executable, '-B', '-c', contract.CHILD], env=child,
        capture_output=True, text=True, timeout=15)
    assert result.returncode != 0


def test_overlay_refuses_neighbor_change(sources):
    with pytest.raises(patch.Refused, match='NEIGHBOR_CHANGED'):
        patch.reviewed_definition(sources[0], sources[1]+b'\nUNREVIEWED = True\n')


def test_overlay_refuses_base_change(sources):
    with pytest.raises(patch.Refused, match='BASE_CHANGED'):
        patch.reviewed_definition(sources[0]+b'\n', sources[1])


def test_neighbor_comparison_has_falsifier(sources, monkeypatch):
    monkeypatch.setattr(patch.ast, 'dump', lambda *a, **kw: 'removed')
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_overlay_refuses_neighbor_change(sources)


def test_interpreter_scopes_the_exact_coordinator(tmp_path):
    source, deployed = tmp_path/'source', tmp_path/'deployed'
    (source/'tools').mkdir(parents=True)
    (source/'tools/sentinel_local_activation_host_patch.py').write_text('import sys,json; print(json.dumps(sys.argv[1:]))')
    manifest = tmp_path/'manifest.json'; wrapper = tmp_path/'activation-python'
    wrapper.write_text(patch.interpreter_source(source, deployed, manifest, python=sys.executable)); wrapper.chmod(0o700)
    entry = str(deployed/'scripts/sentinel_activation_coordinator.py')
    result = contract.subprocess.run([str(wrapper), entry, '--request', '/private/request.json'],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert contract.json.loads(result.stdout) == [str(manifest), entry, '--request', '/private/request.json']
    result = contract.subprocess.run([str(wrapper), '-B', '-c', 'print("ordinary")'],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'ordinary'
