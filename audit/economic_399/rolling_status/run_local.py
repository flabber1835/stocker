"""Run a bounded offline Linux probe or focused review acceptance."""
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
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    command = ['audit/economic_399/rolling_status/probe.py',*sys.argv[1:]]
    if sys.argv[1:2] == ['test']:
        command = ['-m','pytest',*sys.argv[2:],'-q','-ra','--tb=short','-p','no:cacheprovider']
    elif sys.argv[1:2] == ['mutations']:
        command = ['audit/economic_399/rolling_status/mutations.py']
    elif sys.argv[1:2] == ['go-mutants']:
        command = ['-m','tools.sentinel_rolling_go_falsifiers']
    elif sys.argv[1:2] == ['consumer-mutants']:
        command = ['audit/economic_399/rolling_status/report_consumers/mutations.py', *sys.argv[2:]]
    docker = ['docker','run','--rm','--network','none','--memory','4g','--cpus','2',
              '--mount',f'type=bind,source={root.as_posix()},target=/source,readonly',
              '--entrypoint','python','sentinel-test:ci','-u','-c',bootstrap,*command]
    print(json.dumps(docker),flush=True)
    return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
