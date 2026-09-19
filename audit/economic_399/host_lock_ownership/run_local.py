"""Run host-lock acceptance offline in a disposable writable checkout copy."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('regression', 'mutations', 'backup', 'host', 'entrypoints'))
    parser.add_argument('--image', default='sentinel-test:ci')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    cases = ['tests/scripts/test_host_lock_ownership.py',
             'tests/production_composition/test_lock_process_boundary.py',
             'tests/production_composition/test_cross_actor_concurrency.py',
             'tests/production_composition/test_go_backup_lock_concurrency.py',
             'tests/production_composition/test_go_preparation_authority.py',
             'tests/production_composition/test_phase_c_authority_process.py',
             'tests/scripts/test_sentinel_bringup_entrypoint.py']
    command = ['-m', 'pytest', *cases, '-q', '-p', 'no:cacheprovider']
    if args.campaign == 'backup':
        command = ['-m', 'pytest', 'tests/backup/test_shell_lifecycle.py',
                   '-q', '-p', 'no:cacheprovider']
    if args.campaign == 'mutations':
        command = ['-m', 'tools.sentinel_host_lock_falsifiers']
    if args.campaign == 'host':
        command = ['-m', 'unittest', 'tests.host_python38.test_lock_ownership', '-v']
    if args.campaign == 'entrypoints':
        command = ['-m', 'pytest', 'tests/sentinel/test_backup_orchestration_hardening.py',
                   'tests/sentinel/test_go_output_guard.py', 'tests/sentinel/test_go_validation_liveness.py',
                   '-q', '-p', 'no:cacheprovider']
    bootstrap = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
'''
    docker = ['docker', 'run', '--rm', '--network', 'none',
              '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
              '--entrypoint', 'python', args.image, '-u', '-c', bootstrap, *command]
    print(json.dumps(docker), flush=True)
    return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
