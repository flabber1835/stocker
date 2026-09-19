"""Offline acceptance of GO renewal after runtime backup horizon exhaustion."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('focused', 'regression', 'mutations', 'postgres'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    command = ['-m', 'pytest', 'tests/backup/test_shell_lifecycle.py',
        'tests/sentinel/test_go_backup_refresh.py', '-q', '-ra', '--tb=short',
        '-p', 'no:cacheprovider']
    if args.campaign == 'focused':
        command += ['-k', 'horizon or object_bound or repairable_states']
    elif args.campaign == 'regression':
        command[2:4] = ['tests/backup', 'tests/sentinel/test_go_backup_refresh.py',
            'tests/sentinel/test_go_backup_refresh_call_contract.py',
            'tests/scripts/test_sentinel_bringup.py',
            'tests/scripts/test_sentinel_bringup_entrypoint.py']
    elif args.campaign == 'postgres':
        command = ['-m', 'pytest', 'tests/backup/test_shell_lifecycle.py::test_runtime_horizon_shell_uses_actual_postgres_manifest',
                   '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    else:
        command = ['-m', 'tools.sentinel_backup_horizon_falsifiers']
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    docker = ['docker', 'run', '--rm', '--network', 'none', '--mount',
        f'type=bind,source={root.as_posix()},target=/source,readonly',
        '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, *command]
    print(json.dumps(docker), flush=True)
    return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
