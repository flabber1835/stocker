"""Exercise CI-only PostgreSQL setup without network, packages or databases."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ('postgres', 'initdb', 'pg_ctl', 'pg_basebackup', 'pg_verifybackup',
         'pg_controldata', 'pg_dump', 'pg_restore', 'psql', 'createdb', 'dropdb')


def setup_fixture(tmp_path, *, missing=None, broken=None, install_repairs=True,
                  update_code=0, install_code=0):
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    pg_bin = tmp_path / 'postgres bin'
    pg_bin.mkdir()
    calls = tmp_path / 'calls.jsonl'
    probe = f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
with open(os.environ['CALLS'], 'a') as out:
    out.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')
assert sys.argv[1:] == ['--version'], 'database or other operation reached'
if Path(sys.argv[0]).name == os.environ['BROKEN']:
    raise SystemExit(9)
print(Path(sys.argv[0]).name + ' (PostgreSQL) 16.10')
'''
    for tool in TOOLS:
        if tool != missing:
            target = pg_bin / tool
            target.write_text(probe)
            target.chmod(0o755)
    config = binaries / 'pg_config'
    config.write_text(f'#!{sys.executable}\n' +
                      'import os, sys\nassert sys.argv[1:] == ["--bindir"]\n'
                      'print(os.environ["PG_BIN"])\n')
    config.chmod(0o755)
    sudo = binaries / 'sudo'
    sudo.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as out:
    out.write(json.dumps(['sudo', *args]) + '\\n')
assert args[0] == 'apt-get'
if args[-1] == 'update':
    raise SystemExit(int(os.environ['UPDATE_CODE']))
assert args[-3:] == ['install', '-y', 'postgresql']
if os.environ['INSTALL_CODE'] != '0':
    raise SystemExit(int(os.environ['INSTALL_CODE']))
if os.environ['INSTALL_REPAIRS'] == '1' and os.environ['MISSING']:
    source = Path(os.environ['PG_BIN']) / 'postgres'
    target = source.parent / os.environ['MISSING']
    target.write_text(source.read_text())
    target.chmod(0o755)
''')
    sudo.chmod(0o755)
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
               CALLS=str(calls), PG_BIN=str(pg_bin), MISSING=missing or '',
               BROKEN=broken or '', INSTALL_REPAIRS=str(int(install_repairs)),
               UPDATE_CODE=str(update_code), INSTALL_CODE=str(install_code))
    return env, calls


def invoke(tmp_path, **kwargs):
    env, calls = setup_fixture(tmp_path, **kwargs)
    result = subprocess.run(['bash', str(ROOT / 'tools/ci_postgres.sh')],
                            env=env, text=True, capture_output=True, timeout=10)
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    return result, observed


def test_complete_tools_are_reused_without_package_network_or_database_start(tmp_path):
    result, calls = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls == [[tool, '--version'] for tool in TOOLS]


def test_missing_tool_requires_bounded_package_install_and_complete_reprobe(tmp_path):
    result, calls = invoke(tmp_path, missing='pg_verifybackup')
    assert result.returncode == 0, result.stderr
    package_calls = [call for call in calls if call[0] == 'sudo']
    assert len(package_calls) == 2
    for call in package_calls:
        for option in ('Acquire::Retries=2', 'Acquire::http::Timeout=30',
                       'Acquire::https::Timeout=30', 'APT::Update::Error-Mode=any'):
            assert option in call
    assert package_calls[0][-1] == 'update'
    assert package_calls[1][-3:] == ['install', '-y', 'postgresql']
    assert calls[-len(TOOLS):] == [[tool, '--version'] for tool in TOOLS]


@pytest.mark.parametrize('fault', ['update', 'install', 'unrepaired', 'broken-probe'])
def test_failed_or_incomplete_setup_never_reports_success(tmp_path, fault):
    result, calls = invoke(tmp_path, missing='pg_verifybackup' if fault != 'broken-probe' else None,
                           update_code=4 if fault == 'update' else 0,
                           install_code=5 if fault == 'install' else 0,
                           install_repairs=fault != 'unrepaired',
                           broken='pg_ctl' if fault == 'broken-probe' else None)
    assert result.returncode != 0
    assert 'toolchain verified;' not in result.stdout
    if fault == 'update':
        assert not any(call[-3:] == ['install', '-y', 'postgresql'] for call in calls)


@pytest.mark.parametrize('workflow_name,job_name,step_name', [
    ('internal-state-harness.yml', 'contract', 'Install locked dependencies and real PostgreSQL tools'),
    ('internal-state-harness.yml', 'lifecycle', 'Install locked dependencies and real PostgreSQL tools'),
    ('internal-state-harness.yml', 'core-infrastructure', 'Install locked dependencies and PostgreSQL'),
    ('alpaca-simulation-harness.yml', 'alpaca', 'Install locked test dependencies and PostgreSQL'),
    ('production-composition-harness.yml', 'database-preflight', 'Install PostgreSQL and locked dependencies'),
    ('production-composition-harness.yml', 'composition', 'Install PostgreSQL physical restore tools'),
])
def test_every_postgres_setup_uses_the_bounded_verified_helper(workflow_name, job_name, step_name):
    workflow = yaml.safe_load((ROOT / '.github/workflows' / workflow_name).read_text())
    job = workflow['jobs'][job_name]
    step = next(step for step in job['steps'] if step.get('name') == step_name)
    assert step['timeout-minutes'] == 10
    assert 'bash tools/ci_postgres.sh' in step['run']
    assert 'apt-get' not in step['run']


def test_filtered_alpaca_workflow_qualifies_shared_setup_changes():
    workflow = yaml.safe_load((ROOT / '.github/workflows/alpaca-simulation-harness.yml').read_text())
    events = workflow.get('on', workflow.get(True))
    paths = events['pull_request']['paths']
    assert 'tools/ci_postgres.sh' in paths
    assert 'tests/scripts/test_ci_postgres.py' in paths
