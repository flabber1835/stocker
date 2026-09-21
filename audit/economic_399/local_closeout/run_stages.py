"""Run sequential offline scale stages with separately enforced Compose caps."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--universe', type=int, default=5000)
    parser.add_argument('--attach-prefix', help='Resume this retained isolated test database after coordinator exit')
    parser.add_argument('--resume-reason', default='Resume the existing isolated test database after coordinator exit.')
    parser.add_argument('--stages', nargs='+', default=['publish', 'initialize', 'status', 'http',
                        'next_publish', 'advance', 'advanced_status', 'advanced_http'])
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=bool(args.attach_prefix))
    prefix = args.attach_prefix or 'sentinel-cost-' + uuid4().hex[:8]
    assert re.fullmatch(r'sentinel-cost-[0-9a-f]{8}', prefix)
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
    pg_log = pg = None
    if args.attach_prefix:
        retained = json.loads(subprocess.check_output(['docker', 'inspect', pg_name], text=True))[0]
        assert retained['State']['Running'] and retained['HostConfig']['NetworkMode'] == 'none'
        assert retained['HostConfig']['Memory'] == retained['HostConfig']['MemorySwap'] == 1024**3
        assert retained['HostConfig']['NanoCpus'] == 1500000000
        assert retained['Image'] == 'sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146'
        assert (args.evidence/'database.json').exists() and not (args.evidence/'stop').exists()
        resume = args.evidence/'coordinator-resume.json'
        suffix = 2
        while resume.exists():
            resume = args.evidence/f'coordinator-resume-{suffix}.json'
            suffix += 1
        resume.write_bytes((json.dumps({
            'prefix': prefix, 'source': args.source.as_posix(), 'stages': args.stages,
            'reason': args.resume_reason}, indent=2)+'\n').encode())
    else:
        pg_log = (args.evidence/'postgres.log').open('w')
        pg = subprocess.Popen(command('postgres', '1g', '1.5'), stdout=pg_log, stderr=subprocess.STDOUT)
    failures = []
    try:
        deadline = time.monotonic()+120
        while not (args.evidence/'database.json').exists():
            if (pg is not None and pg.poll() is not None) or time.monotonic() > deadline:
                raise RuntimeError('isolated PostgreSQL startup failed')
            time.sleep(.5)
        for stage in args.stages:
            memory, cpus = ('512m', '.5') if 'status' in stage or 'http' in stage else ('4g', '2')
            cmd = command(stage, memory, cpus)
            print(json.dumps(cmd), flush=True)
            existing = subprocess.run(['docker', 'inspect', prefix+'-'+stage], capture_output=True, text=True)
            if args.attach_prefix and existing.returncode == 0:
                live = json.loads(existing.stdout)[0]
                assert live['HostConfig']['NetworkMode'] == 'container:'+retained['Id']
                expected_memory = 512*1024**2 if memory == '512m' else 4*1024**3
                assert live['HostConfig']['Memory'] == live['HostConfig']['MemorySwap'] == expected_memory
                assert live['HostConfig']['NanoCpus'] == (500000000 if cpus == '.5' else 2000000000)
                code = int(subprocess.check_output(['docker', 'wait', prefix+'-'+stage], text=True).strip())
                result = subprocess.CompletedProcess(cmd, code)
                # A lost host client can leave its log incomplete while Docker
                # continues the stage. Preserve both sources without overwriting.
                with (args.evidence/(stage+'-adopted-container.log')).open('wb') as log:
                    subprocess.run(['docker', 'logs', prefix+'-'+stage], stdout=log,
                                   stderr=subprocess.STDOUT, check=True)
            else:
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
            if pg is None:
                subprocess.run(['docker', 'wait', pg_name], check=True, timeout=60)
            else:
                pg.wait(timeout=60)
        except subprocess.TimeoutExpired:
            subprocess.run(['docker', 'stop', pg_name], check=True)
            if pg is not None:
                pg.wait(timeout=30)
        if pg_log is not None:
            pg_log.close()
        inspect(pg_name)
        subprocess.run(['docker', 'rm', pg_name], check=True)


if __name__ == '__main__':
    main()
