"""Run sequential offline scale stages with separately enforced Compose caps."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--universe', type=int, default=5000)
    parser.add_argument('--stages', nargs='+', default=['publish', 'initialize', 'status', 'http',
                        'next_publish', 'advance', 'advanced_status', 'advanced_http'])
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    prefix = 'sentinel-cost-' + uuid4().hex[:8]
    pg_name = prefix+'-postgres'
    bootstrap = '''import os,subprocess,sys
os.chdir('/source')
os.environ.update(PYTHONPATH='/source:/source/shared:/source/scripts',SENTINEL_REPO_ROOT='/source',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,'-u','audit/economic_399/local_closeout/stages.py',*sys.argv[1:]]).returncode)
'''
    def command(stage, memory, cpus):
        return ['docker', 'run', '--name', prefix+'-'+stage,
                *(['--shm-size', '1g'] if stage == 'postgres' else []),
                '--network', 'none' if stage == 'postgres' else 'container:'+pg_name,
                '--memory', memory, '--memory-swap', memory, '--cpus', cpus,
                '--mount', f'type=bind,source={args.source.resolve().as_posix()},target=/source,readonly',
                '--mount', f'type=bind,source={args.evidence.resolve().as_posix()},target=/evidence',
                '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap,
                stage, '--universe', str(args.universe)]
    def inspect(name):
        result = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, check=True)
        value = json.loads(result.stdout)[0]
        retained = {key: value[key] for key in ('State', 'HostConfig', 'Image')}
        (args.evidence/(name+'.inspect.json')).write_text(json.dumps(retained, indent=2))
        print(json.dumps({'container': name, 'state': value['State'], 'image': value['Image'],
                          'memory': value['HostConfig']['Memory'], 'cpus': value['HostConfig']['NanoCpus']}), flush=True)
    pg_log = (args.evidence/'postgres.log').open('w')
    pg = subprocess.Popen(command('postgres', '1g', '1.5'), stdout=pg_log, stderr=subprocess.STDOUT)
    failures = []
    try:
        deadline = time.monotonic()+120
        while not (args.evidence/'database.json').exists():
            if pg.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('isolated PostgreSQL startup failed')
            time.sleep(.5)
        for stage in args.stages:
            memory, cpus = ('512m', '.5') if 'status' in stage or 'http' in stage else ('4g', '2')
            cmd = command(stage, memory, cpus)
            print(json.dumps(cmd), flush=True)
            with (args.evidence/(stage+'.log')).open('w') as log:
                result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
            inspect(prefix+'-'+stage)
            subprocess.run(['docker', 'rm', prefix+'-'+stage], check=True)
            with (args.evidence/(stage+'-postgres-memory.log')).open('w') as log:
                subprocess.run(['docker', 'exec', pg_name, 'python', '-c',
                    "from pathlib import Path; [(print(p),print(Path('/sys/fs/cgroup',p).read_text())) for p in ('memory.peak','memory.events','memory.stat','cpu.stat')]"],
                    stdout=log, stderr=subprocess.STDOUT, check=True)
            if result.returncode:
                failures.append((stage, result.returncode))
                # A failed read-only request cannot earn a pass, but should not
                # prevent collecting the independent next-session measurements.
                if stage not in ('status', 'http', 'advanced_status', 'advanced_http'):
                    raise AssertionError(failures)
        assert not failures, failures
    finally:
        (args.evidence/'stop').touch()
        try:
            pg.wait(timeout=60)
        except subprocess.TimeoutExpired:
            subprocess.run(['docker', 'stop', pg_name], check=True)
            pg.wait(timeout=30)
        pg_log.close()
        inspect(pg_name)
        subprocess.run(['docker', 'rm', pg_name], check=True)


if __name__ == '__main__':
    main()
