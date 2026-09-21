"""Profile production PostgreSQL locally; no external network or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4


PG_IMAGE = 'postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'
TEST_IMAGE = 'sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146'
SAMPLER = '''while [ ! -e /evidence/stop-sampling ]; do
printf 'BEGIN '; cut -d ' ' -f 1 /proc/uptime
printf 'phase '; cat /evidence/phase
for metric in memory.current memory.peak memory.events memory.stat memory.pressure cpu.stat; do
echo "$metric"; cat "/sys/fs/cgroup/$metric" || exit 1
done
echo END
sleep 1
done
'''
BOOTSTRAP = """import os,sys,runpy
os.chdir('/source')
sys.path[:0]=['/source','/source/shared','/source/scripts']
os.environ.update(SENTINEL_REPO_ROOT='/source',PYTHONDONTWRITEBYTECODE='1')
sys.argv=['worker.py',*sys.argv[1:]]
runpy.run_path('audit/economic_399/postgres_pressure/worker.py',run_name='__main__')
"""


def save(path, value):
    path.write_bytes((json.dumps(value, indent=2, default=str)+'\n').encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    sources = {}
    for prefix in ('sentinel', 'shared', 'scripts', 'audit/economic_399/postgres_pressure'):
        for path in (root/prefix).rglob('*.py'):
            sources[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(evidence/'sources.json', sources)
    save(evidence/'git.json', {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                              'status': subprocess.check_output(['git', 'status', '--short'], text=True)})
    name = 'sentinel-pressure-' + uuid4().hex[:8]
    def run(command, **kwargs):
        print(json.dumps(command), flush=True)
        return subprocess.run(command, check=True, **kwargs)
    run(['docker', 'run', '-d', '--name', name, '--network', 'none',
         '--memory', '1g', '--memory-swap', '1g', '--cpus', '1.5', '--shm-size', '1g',
         '--mount', f'type=bind,source={evidence.as_posix()},target=/evidence',
         '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', PG_IMAGE])
    monitor = None
    completed = []
    try:
        for _ in range(60):
            if subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'postgres'],
                              capture_output=True).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('isolated PostgreSQL did not start')
        save(evidence/'database.json', {'dsn': 'postgresql://postgres@127.0.0.1:5432/postgres'})
        (evidence/'phase').write_bytes(b'baseline\n')
        with (evidence/'samples.log').open('wb') as sample_log:
            monitor = subprocess.Popen(['docker', 'exec', name, 'sh', '-c', SAMPLER],
                                       stdout=sample_log, stderr=subprocess.STDOUT)
            for stage in ('baseline', 'publish', 'scan1', 'scan2', 'storage', 'final'):
                (evidence/'phase').write_bytes((stage+'\n').encode())
                client = name+'-'+stage
                cmd = ['docker', 'run', '--name', client, '--network', 'container:'+name,
                       '--memory', '4g', '--memory-swap', '4g', '--cpus', '2',
                       '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
                       '--mount', f'type=bind,source={evidence.as_posix()},target=/evidence',
                       '--entrypoint', 'python', TEST_IMAGE, '-u', '-c', BOOTSTRAP, stage]
                started = time.monotonic()
                try:
                    with (evidence/(stage+'.log')).open('wb') as log:
                        run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
                    completed.append({'stage': stage, 'seconds': time.monotonic()-started})
                finally:
                    with (evidence/(stage+'.inspect.json')).open('wb') as log:
                        run(['docker', 'inspect', client], stdout=log)
                    run(['docker', 'rm', '-f', client])
                assert monitor.poll() is None, 'memory sampler stopped early'
            save(evidence/'completed.json', completed)
            (evidence/'stop-sampling').touch()
            assert monitor.wait(timeout=10) == 0
        for rel, expected in sources.items():
            assert hashlib.sha256((root/rel).read_bytes()).hexdigest() == expected, rel
    finally:
        (evidence/'stop-sampling').touch()
        if monitor is not None:
            monitor.wait(timeout=10)
        run(['docker', 'stop', name])
        with (evidence/'postgres.log').open('wb') as log:
            run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT)
        with (evidence/'postgres.inspect.json').open('wb') as log:
            run(['docker', 'inspect', name], stdout=log)
        run(['docker', 'rm', '-v', name])


if __name__ == '__main__':
    main()
