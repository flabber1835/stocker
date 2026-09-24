"""Run focused startup checks in the existing offline Linux/Postgres image."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = '''import hashlib,json,os,pathlib,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__','sec-filings'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('sentinel','shared','tests','tools','scripts') for p in pathlib.Path(folder).rglob('*.py')}
print('FROZEN_VALIDATION_SOURCE_SHA256='+hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),flush=True)
result=subprocess.run([sys.executable,*sys.argv[1:]])
if pathlib.Path('/tmp/repo/startup-mutations').exists():
    result_file = pathlib.Path('/tmp/repo/startup-mutations/results.json')
    if result_file.exists():
        print('MUTATION_RESULTS='+result_file.read_text(),flush=True)
    for log in sorted(pathlib.Path('/tmp/repo/startup-mutations').glob('*.log')):
        print('MUTATION_LOG='+log.name+'\\n'+log.read_text(),flush=True)
raise SystemExit(result.returncode)
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['test', 'mutations', 'resource', 'partitions'])
    parser.add_argument('nodes', nargs='*')
    args = parser.parse_args()
    command = (['-m', 'pytest', *args.nodes, '-v', '--tb=short', '-p', 'no:cacheprovider'] if args.mode == 'test'
               else ['tools/owned55_startup_mutations.py', '--group', 'startup', '--output', 'startup-mutations'])
    if args.mode == 'resource':
        command = ['tools/owned55_resource_probe.py', *args.nodes]
    if args.mode == 'partitions':
        command = ['tools/verify_sentinel_test_partitions.py']
    if args.mode == 'mutations' and args.nodes:
        if len(args.nodes) != 1:
            parser.error('mutations accepts at most one case name')
        command += ['--case', args.nodes[0]]
    raise SystemExit(subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--memory', '4g', '--cpus', '2',
        '--mount', f'type=bind,source={ROOT.as_posix()},target=/source,readonly', '--entrypoint', 'python',
        'sentinel-test:ci', '-u', '-c', BOOTSTRAP, *command]).returncode)
