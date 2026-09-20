"""Run full-status probes only in offline disposable containers."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
payload = ['audit/economic_399/full_status/probe.py', *sys.argv[1:]]
if sys.argv[1:] == ['mutations']:
    payload = ['audit/economic_399/full_status/mutations.py']
command = ['docker','run','--rm','--network','none','--memory','8g','--cpus','2',
           '--mount',f'type=bind,source={root.as_posix()},target=/source,readonly',
           '--entrypoint','python','sentinel-test:ci','-u','-c',bootstrap,
           *payload]
print(json.dumps(command),flush=True)
raise SystemExit(subprocess.run(command).returncode)
