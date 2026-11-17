"""The operator signed-CLI wrapper must never start Compose dependencies."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "sentinel-authorized-cli.sh"
FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_DOCKER_LOG'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(args) + '\\n')
if 'ps' in args:
    mode = os.environ.get('FAKE_PG_MODE', 'healthy')
    if mode == 'ambiguous':
        print('a' * 64 + '\\n' + 'b' * 64)
    elif mode != 'absent':
        print('a' * 64)
elif args and args[0] == 'inspect':
    print('starting' if os.environ.get('FAKE_PG_MODE') == 'starting' else 'healthy')
elif args and args[-1] == 'sentinel-authority-permissions':
    if os.environ.get('FAKE_HELPER_FAIL') == '1':
        sys.exit(77)
elif 'sentinel-authorized-cli' in args:
    print('SIGNED_CLI_REACHED')
"""


def _run(tmp_path, *, pg_mode="healthy", helper_fail=False, mutate_cli=False):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    wrapper = scripts / WRAPPER.name
    source = WRAPPER.read_text(encoding="utf-8")
    if mutate_cli:
        source = source.replace(
            'run --rm -T --no-deps sentinel-authorized-cli',
            'run --rm -T sentinel-authorized-cli')
        assert source != WRAPPER.read_text(encoding="utf-8")
    wrapper.write_text(source, encoding="utf-8")
    (scripts / "sentinel-env.sh").write_text(
        'sentinel_load_environment() { :; }\n', encoding="utf-8")
    (scripts / "sentinel_host_python.py").write_text(
        'pass\n', encoding="utf-8")
    authority = tmp_path / "authority"
    authority.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    env = dict(os.environ,
        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
        SENTINEL_HOST_PYTHON=sys.executable,
        SENTINEL_RUNTIME_IMAGE_DIGEST="sha256:" + "a" * 64,
        SENTINEL_TEST_IMAGE_DIGEST="sha256:" + "b" * 64,
        SENTINEL_GIT_COMMIT="c" * 40,
        SENTINEL_AUTHORITY_ARTIFACTS_DIR=str(authority),
        FAKE_DOCKER_LOG=str(log), FAKE_PG_MODE=pg_mode,
        FAKE_HELPER_FAIL="1" if helper_fail else "0")
    result = subprocess.run(
        ["bash", str(wrapper), "inspect-paper-account", "--deployment-id",
         "deployment", "--expect-account", "PAPER 1"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return result, calls


def _assert_no_dependency_start(calls):
    assert len(calls) == 4
    assert calls[0][-5:] == ["ps", "--status", "running", "-q", "sentinel-postgres"]
    assert calls[1][0] == "inspect" and calls[1][-1] == "a" * 64
    assert calls[2][-5:] == ["run", "--rm", "-T", "--no-deps", "sentinel-authority-permissions"]
    assert calls[3][-10:] == ["run", "--rm", "-T", "--no-deps",
                            "sentinel-authorized-cli", "inspect-paper-account",
                            "--deployment-id", "deployment", "--expect-account", "PAPER 1"]
    assert all(not any(arg in {"up", "start", "recreate"} for arg in call)
               for call in calls)


def test_signed_cli_inspection_keeps_database_existing_and_arguments_exact(tmp_path):
    result, calls = _run(tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == "SIGNED_CLI_REACHED"
    _assert_no_dependency_start(calls)


@pytest.mark.parametrize("pg_mode,expected_calls", [("absent", 1),
                                                    ("ambiguous", 1),
                                                    ("starting", 2)])
def test_signed_cli_refuses_without_one_healthy_existing_database(
        tmp_path, pg_mode, expected_calls):
    result, calls = _run(tmp_path, pg_mode=pg_mode)
    assert result.returncode == 2
    assert len(calls) == expected_calls
    assert "SIGNED_CLI_REACHED" not in result.stdout


def test_signed_cli_stops_if_permission_helper_fails(tmp_path):
    result, calls = _run(tmp_path, helper_fail=True)
    assert result.returncode == 77
    assert len(calls) == 3


def test_no_deps_falsifier_catches_unreviewed_wrapper_mutation(tmp_path):
    result, calls = _run(tmp_path, mutate_cli=True)
    assert result.returncode == 0
    with pytest.raises(AssertionError):
        _assert_no_dependency_start(calls)
