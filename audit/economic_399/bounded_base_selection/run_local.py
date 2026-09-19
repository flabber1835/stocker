"""Offline backup-selection acceptance in a disposable checkout and database."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('regression', 'mutations'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    command = (['-m', 'tools.sentinel_backup_selection_falsifiers']
               if args.campaign == 'mutations' else ['-m', 'pytest',
               'tests/backup', 'tests/sentinel/test_backup_selection_sql.py',
               'tests/sentinel/test_backup_bounded_reads.py',
               'tests/sentinel/test_backup_manifest_bound.py',
               'tests/sentinel/test_backup_orchestration_hardening.py',
               'tests/sentinel/test_backup_owner_contract.py',
               '-q', '--tb=short', '-p', 'no:cacheprovider'])
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    command = ['docker', 'run', '--rm', '--network', 'none',
               '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
               '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, *command]
    print(json.dumps(command), flush=True)
    return subprocess.run(command).returncode


if __name__ == '__main__':
    raise SystemExit(main())
