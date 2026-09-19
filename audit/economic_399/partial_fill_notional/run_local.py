"""Offline fill-integrity acceptance with disposable source and PostgreSQL."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('regression', 'mutations'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    command = (['-m', 'tools.sentinel_partial_fill_falsifiers']
               if args.campaign == 'mutations' else ['-m', 'pytest',
               'tests/sentinel/test_native_fill_acceptance.py',
               'tests/sentinel/test_native_fill_progression.py',
               'tests/sentinel/test_journal_and_reconcile.py',
               'tests/sentinel/test_execution_contract.py',
               'tests/sentinel/test_alpaca_boundary_overlay.py',
               'tests/sentinel/test_trial_fill_interval_evidence.py',
               'tests/sentinel/test_trial_fill_interval_proof.py',
               '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider'])
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
