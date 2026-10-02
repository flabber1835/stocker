"""Run the manual joint campaign on an internal Docker network."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from tools.acquisition_resources.runner import command, inspect, ready, database_memory


def _unreclaimable(sample):
    return (sample['anon']+sample['shmem']+sample['slab_unreclaimable']
            +sample['kernel_stack']+sample['pagetables'])


def _database_headroom(samples, limit):
    return bool(samples) and max(map(_unreclaimable, samples)) <= limit-128*1024**2


def _callback_headroom(cycles):
    callbacks = [callback['seconds'] for cycle in cycles
                 for callback in cycle['callbacks']]
    return bool(callbacks) and max(callbacks) <= 720


def run(args):
    prefix = 'joint-rehearsal-' + uuid.uuid4().hex[:10]
    db, provider, worker, automation = [prefix+'-'+role for role in ('db','provider','worker','automation')]
    network = prefix+'-net'
    volumes = [prefix+'-db', prefix+'-cache']
    report = dict(schema='sentinel.joint-local-rehearsal/1', verdict='INCOMPLETE',
        scope='PRODUCTION_FINANCIAL_FUNCTIONS_AND_SIMULATED_PAPER',
        excluded=['shell GO certification/image promotion', 'NAS backup medium',
                  'actual vendor/broker', 'deployable authority'],
        small=args.small, containers=[db,provider,worker,automation], network=network, volumes=volumes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    samples = []
    deadline = time.monotonic()+args.deadline_seconds
    def save():
        args.output.write_text(json.dumps(report, indent=2, default=str)+'\n', encoding='utf-8')
    save()
    try:
        image = json.loads(command('docker','image','inspect',args.image))[0]['Id']
        postgres = json.loads(command('docker','image','inspect',args.postgres))[0]['Id']
        report.update(image=image, postgres_image=postgres)
        command('docker','network','create','--internal',network)
        created.append(('network',network))
        for volume in volumes:
            command('docker','volume','create',volume)
            created.append(('volume',volume))
        command('docker','run','-d','--name',db,'--network',network,'--network-alias','database',
            '--memory','1g','--memory-swap','2g','--shm-size','1g','--cpus','1.5',
            '--mount',f'type=volume,src={volumes[0]},dst=/var/lib/postgresql/data',
            '-e','POSTGRES_PASSWORD=offline-fixture',postgres)
        common = ['--network',network,'--entrypoint','python',
            '-e','PYTHONDONTWRITEBYTECODE=1', '-e','SENTINEL_PUBLICATION_RECEIPT_KEY=offline-fixture-key-0123456789abcdef']
        size = ['--small'] if args.small else []
        command('docker','run','-d','--name',provider,'--network-alias','provider',*common,
            '--memory','512m','--memory-swap','512m','--cpus','1',image,
            '-u','-m','tools.operational_rehearsal.provider',*size)
        ready(db,['pg_isready','-U','postgres'],deadline)
        ready(provider,['python','-c',"import urllib.request; urllib.request.urlopen('http://localhost:8080/metrics',timeout=5).read()"],deadline)
        environment = [
            '-e','SENTINEL_STATE_DIR=/var/lib/sentinel',
            '-e','NDL_BASE_URL=http://provider:8080/api/v3/datatables/SHARADAR',
            '-e','SHARADAR_ALLOW_INSECURE_BASE_URL=1','-e','SHARADAR_API_KEY=offline-fixture',
            '-e','RESOURCE_DSN=postgresql://postgres:offline-fixture@database/postgres',
            '-e',f'SENTINEL_IMAGE_SOURCE_REVISION={args.commit}']
        command('docker','run','-d','--name',automation,'--network-alias','automation',*common,
            '--memory','2g','--memory-swap','2g','--cpus','1',*environment,image,
            '-u','-m','tools.operational_rehearsal.automation')
        ready(automation,['python','-c',"import urllib.request; urllib.request.urlopen('http://localhost:8081/health',timeout=5).read()"],deadline)
        command('docker','run','-d','--name',worker,*common,
            '--memory','4g','--memory-swap','4g','--cpus','2',
            '--mount',f'type=volume,src={volumes[1]},dst=/var/lib/sentinel',*environment,image,
            '-u','-m','tools.operational_rehearsal.worker',*size)
        report['limits'] = {name: {k:inspect(name)['HostConfig'][k]
            for k in ('Memory','MemorySwap','NanoCpus','ShmSize')} for name in (db,provider,worker,automation)}
        save()
        last = 0
        while inspect(worker)['State']['Running']:
            if time.monotonic() >= deadline:
                raise TimeoutError('joint campaign deadline exceeded')
            samples.append(database_memory(db))
            if time.monotonic()-last > 30:
                output = subprocess.run(['docker','logs','--tail','3',worker],capture_output=True,text=True,timeout=20)
                print((output.stdout+output.stderr)[-2000:],flush=True)
                last = time.monotonic()
            time.sleep(2)
        # The worker requests automation completion after all three cycles.
        for role,name,limit in (('worker',worker,4),('automation',automation,2)):
            state = inspect(name)['State']
            report[role+'_state'] = state
            assert not state['Running'] and state['ExitCode'] == 0 and not state['OOMKilled'], state
            logs = command('docker','logs',name)
            objects = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
            results = [value for value in objects if value.get('event') == 'result']
            assert len(results) == 1, 'complete '+role+' result missing'
            result = results[0]
            report[role+'_result'] = result
            assert len(result['daily_cycles']) == 3
            assert result['measurement']['cgroup']['events']['oom'] == 0
            assert result['measurement']['cgroup']['events']['oom_kill'] == 0
            assert result['measurement']['cgroup']['limit'] == limit*1024**3
        report['database'] = database_memory(db)
        assert report['database']['events'] == dict(oom=0,oom_kill=0)
        report['database_unreclaimable_peak'] = max(map(_unreclaimable, samples))
        assert _database_headroom(samples, report['database']['limit']), (
                    'database lacks 128 MiB unreclaimable-memory headroom')
        report['callback_peak_seconds'] = max(
            callback['seconds']
            for cycle in report['automation_result']['daily_cycles']
            for callback in cycle['callbacks'])
        if not args.small:
            assert _callback_headroom(report['automation_result']['daily_cycles']), (
                'full-size callback lacks 20% headroom against 900-second deadline')
        report['verdict'] = 'PASS_SYNTHETIC_FUNCTION_COMPOSITION'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure'] = f'{type(exc).__name__}: {exc}'
        report['verdict'] = 'FAIL'
    finally:
        try:
            report['database'] = database_memory(db)
        except Exception as exc:
            report['database_measurement_failure'] = f'{type(exc).__name__}: {exc}'
        save()
        for role,name in (('worker',worker),('automation',automation),('provider',provider),('database',db)):
            raw = command('docker','inspect',name,check=False)
            if raw and raw != '[]':
                report[role+'_state'] = json.loads(raw)[0]['State']
                log = subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=30)
                args.output.with_suffix('.'+role+'.log').write_text(log.stdout+log.stderr,encoding='utf-8')
                command('docker','rm','-f',name)
        for kind,name in reversed(created):
            command('docker',kind,'rm',name)
        report['database_samples'] = len(samples)
        report['database_working_peak'] = max((s['working'] for s in samples),default=0)
        report['database_anon_peak'] = max((s['anon'] for s in samples),default=0)
        report['database_shmem_peak'] = max((s['shmem'] for s in samples),default=0)
        report['database_active_file_peak'] = max((s['active_file'] for s in samples),default=0)
        report['database_unreclaimable_peak'] = max(map(_unreclaimable, samples),default=0)
        save()
    print(json.dumps(dict(verdict=report['verdict'],output=str(args.output))),flush=True)
    return report['verdict'] != 'PASS_SYNTHETIC_FUNCTION_COMPOSITION'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--postgres', default='postgres:16')
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--small',action='store_true')
    parser.add_argument('--deadline-seconds',type=int,default=21600)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
