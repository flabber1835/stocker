"""Build and hold the isolated synthetic database for capped status readers."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--universe', type=int, default=5000)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    assert not (args.evidence / 'stop').exists()
    root = Path(__file__).resolve().parents[3]
    code = '''import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,'-u','audit/economic_399/status_memory/probe.py','serve',*sys.argv[1:]]).returncode)
'''
    command = ['docker', 'run', '--rm', '--name', 'sentinel-status-memory-fixture',
        '--network', 'none', '--memory', '8g', '--cpus', '2',
        '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
        '--mount', f'type=bind,source={args.evidence.resolve().as_posix()},target=/evidence',
        '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', code,
        '--universe', str(args.universe)]
    print(command, flush=True)
    return subprocess.run(command).returncode


if __name__ == '__main__':
    raise SystemExit(main())
