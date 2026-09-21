"""Offline exact-image PostgreSQL 16 storage checks, with separate service caps."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4


IMAGE = 'postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    name = 'sentinel-cost-pg16-' + uuid4().hex[:8]
    def run(command, **kwargs):
        print(json.dumps(command), flush=True)
        return subprocess.run(command, check=True, **kwargs)
    run(['docker', 'run', '-d', '--name', name, '--network', 'none',
         '--memory', '1g', '--memory-swap', '1g', '--cpus', '1.5', '--shm-size', '1g',
         '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', IMAGE])
    try:
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'postgres'],
                                    capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('offline PostgreSQL 16 did not start')
        run(['docker', 'exec', name, 'psql', '-U', 'postgres', '-Atc', 'SELECT version()'])
        dsn = 'postgresql://postgres@127.0.0.1:5432/postgres'
        (args.evidence/'database.json').write_text(json.dumps({'dsn': dsn}))
        prefix = ['docker', 'run', '--rm', '--network', 'container:'+name,
                  '--memory', '4g', '--memory-swap', '4g', '--cpus', '2',
                  '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
                  '--mount', f'type=bind,source={args.evidence.resolve().as_posix()},target=/evidence',
                  '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c']
        bootstrap = """import os,sys
os.chdir('/source')
sys.path[:0]=['/source','/source/shared','/source/scripts']
os.environ.update(SENTINEL_REPO_ROOT='/source',PYTHONDONTWRITEBYTECODE='1')
"""
        tests = bootstrap + """import pytest
from tests.sentinel import test_rolling_snapshot_publisher as fixture
class ExistingServer:
    sync_dsn='postgresql://postgres@127.0.0.1:5432/postgres'
    def start(self): pass
    def stop(self): pass
fixture._EphemeralPostgres=ExistingServer
raise SystemExit(pytest.main(['tests/sentinel/test_status_memory.py','tests/sentinel/test_observation_storage_envelope.py','-q','--tb=short',
    '-p','no:cacheprovider','-k','database or exact_json_comparison or cursor_decoder or envelope']))
"""
        with (args.evidence/'tests.log').open('w') as log:
            run([*prefix, tests], stdout=log, stderr=subprocess.STDOUT)
        storage = bootstrap + """import runpy
sys.argv=['stages.py','storage','--universe','8408']
runpy.run_path('audit/economic_399/local_closeout/stages.py',run_name='__main__')
"""
        with (args.evidence/'storage.log').open('w') as log:
            run([*prefix, storage], stdout=log, stderr=subprocess.STDOUT)
    finally:
        metrics = 'for p in memory.peak memory.events memory.stat cpu.stat; do echo "$p"; cat /sys/fs/cgroup/$p; done'
        with (args.evidence/'postgres-memory.log').open('w') as log:
            run(['docker', 'exec', name, 'sh', '-c', metrics], stdout=log)
        run(['docker', 'stop', name])
        with (args.evidence/'postgres.log').open('w') as log:
            run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT)
        with (args.evidence/'postgres.inspect.json').open('w') as log:
            run(['docker', 'inspect', name], stdout=log)
        run(['docker', 'rm', name])


if __name__ == '__main__':
    main()
