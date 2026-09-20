"""Run quantity falsifiers in a disposable, network-disabled container."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[3]
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
mode = sys.argv[1:2]
script = {'storage': 'storage_mutations.py', 'read': 'read_mutations.py',
          'oracle': 'oracle_mutation.py'}.get(
    mode[0] if mode else '', 'campaign.py')
args = sys.argv[2:] if mode in (['storage'], ['read'], ['oracle']) else sys.argv[1:]
raise SystemExit(subprocess.run([sys.executable,'audit/economic_399/local_closeout/'+script,*args]).returncode)
'''
    command = ['docker', 'run', '--rm', '--network', 'none', '--memory', '4g',
               '--cpus', '2', '--mount',
               f'type=bind,source={root.as_posix()},target=/source,readonly',
               '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, *sys.argv[1:]]
    print(json.dumps(command), flush=True)
    return subprocess.run(command).returncode


if __name__ == '__main__':
    raise SystemExit(main())
