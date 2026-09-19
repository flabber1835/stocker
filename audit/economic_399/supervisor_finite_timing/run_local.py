"""Offline supervisor startup and recovery checks; no broker or NAS access."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('regression', 'mutations'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    cases = ['tests/sentinel/test_supervisor_timing_admission.py',
             'tests/sentinel/test_supervisor_dependency_bounds.py',
             'tests/sentinel/test_automation_p0_continuity.py',
             'tests/sentinel/test_automation_p1_continuity.py',
             'tests/sentinel/test_automation_safety_seams.py',
             'tests/sentinel/test_alert_supervisor.py']
    command = (['-m', 'tools.sentinel_supervisor_timing_falsifiers']
               if args.campaign == 'mutations' else
               ['-m', 'pytest', *cases, '-q', '--tb=short', '-p', 'no:cacheprovider'])
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    docker = ['docker', 'run', '--rm', '--network', 'none',
              '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
              '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, *command]
    print(json.dumps(docker), flush=True)
    return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
