"""Exercise operator tests with the CI image's separate test/script roots."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=('scripts', 'ownership'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    target = ('tests/scripts' if args.campaign == 'scripts'
              else 'tests/scripts/test_host_lock_ownership.py')
    bootstrap = '''import os,shutil,subprocess,sys
ignore=shutil.ignore_patterns('.git','.env','__pycache__')
shutil.copytree('/source','/work/repo',dirs_exist_ok=True,ignore=ignore)
shutil.rmtree('/app/sentinel')
shutil.copytree('/source/sentinel','/app/sentinel',ignore=ignore)
shutil.copytree('/source/.github','/work/.github',dirs_exist_ok=True,ignore=ignore)
for name in ('tests','tools'):
    shutil.rmtree('/work/'+name)
    shutil.copytree('/source/'+name,'/work/'+name,ignore=ignore)
shutil.copyfile('/source/pytest.ini','/work/pytest.ini')
os.chdir('/work')
os.environ.update(PYTHONPATH='/work:/app',SENTINEL_REPO_ROOT='/work/repo',SENTINEL_IN_IMAGE='1',PYTHONDONTWRITEBYTECODE='1')
assert not os.path.exists('/work/scripts/sentinel_lock_ownership.py')
raise SystemExit(subprocess.run([sys.executable,'-m','pytest',sys.argv[1],'-q','-ra','-p','no:cacheprovider']).returncode)
'''
    command = ['docker', 'run', '--rm', '--network', 'none',
               '--mount', f'type=bind,source={root.as_posix()},target=/source,readonly',
               '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', bootstrap, target]
    print(json.dumps(command), flush=True)
    return subprocess.run(command).returncode


if __name__ == '__main__':
    raise SystemExit(main())
