"""Run only heartbeat acceptance and directly related supervisor regressions."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('focused', 'regression', 'mutations'))
    args = parser.parse_args()
    tests = ['tests/sentinel/test_shadow_heartbeat_isolation.py']
    if args.campaign == 'regression':
        tests += ['tests/sentinel/test_supervisor_dependency_bounds.py',
                  'tests/sentinel/test_supervisor_timing_admission.py',
                  'tests/sentinel/test_review_followup_20260825.py',
                  'tests/sentinel/test_automation_p1_continuity.py',
                  'tests/sentinel/test_reboot_outage_recovery.py',
                  'tests/sentinel/test_operator_monitoring.py']
    command = ['-m', 'pytest', *tests, '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    if args.campaign == 'mutations':
        command = ['audit/economic_399/shadow_heartbeat/mutations.py']
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    root = Path(__file__).resolve().parents[3]
    docker = ['docker', 'run', '--rm', '--network', 'none', '--mount',
              f'type=bind,source={root.as_posix()},target=/source,readonly',
              '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, *command]
    print(json.dumps(docker), flush=True)
    return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
