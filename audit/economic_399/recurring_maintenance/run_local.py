"""Run maintenance acceptance in a disposable offline Linux source copy."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('focused', 'regression', 'mutations', 'final', 'semantic'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    command = ['-m', 'pytest', 'tests/backup/test_recurring_maintenance.py',
               'tests/backup/test_shell_lifecycle.py', '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    if args.campaign == 'regression':
        command[2:4] = ['tests/backup', 'tests/sentinel/test_backup_contract.py',
                        'tests/sentinel/test_backup_owner_contract.py',
                        'tests/sentinel/test_backup_orchestration_hardening.py',
                        'tests/sentinel/test_go_backup_refresh.py',
                        'tests/scripts/test_sentinel_backup_visibility.py']
    elif args.campaign == 'mutations':
        command = ['-m', 'tools.sentinel_maintenance_falsifiers']
    elif args.campaign == 'final':
        command = ['-m', 'pytest', 'tests/backup/test_recurring_maintenance.py',
                   'tests/backup/test_shell_lifecycle.py::test_restore_rechecks_manifest_after_storage_corruption',
                   'tests/sentinel/test_backup_contract.py', 'tests/host_python38/test_env_ingestion.py',
                   '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    elif args.campaign == 'semantic':
        command = ['-m', 'pytest',
                   'tests/backup/test_recurring_maintenance.py::test_real_postgres_semantic_bootstrap_and_durable_receipt_query',
                   '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
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
