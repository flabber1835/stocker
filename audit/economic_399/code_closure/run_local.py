"""Reproduce one retained campaign in an offline, disposable Docker container."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    here = Path(__file__).resolve().parent
    record = json.loads((here / 'commands.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=[*record['campaigns'], 'rolling-falsifiers', *record['mutations']])
    parser.add_argument('--image', default=record['runtime']['image'])
    args = parser.parse_args()
    if args.campaign in record['campaigns']:
        command = ['-u', '-m', 'pytest', *record['campaigns'][args.campaign], *record['pytest_common']]
    elif args.campaign == 'rolling-falsifiers':
        command = record['rolling_falsifiers'][1:]
    else:
        command = ['-u', 'tools/economic_audit_mutation_check.py', args.campaign]
    with tempfile.TemporaryDirectory(prefix='sentinel-offline-') as directory:
        empty = Path(directory) / 'empty.env'
        empty.write_bytes(b'')
        docker = ['docker', 'run', '--rm', '--network', 'none',
                  '--mount', f'type=bind,source={here.parents[2].as_posix()},target=/repo,readonly',
                  '--mount', f'type=bind,source={empty.as_posix()},target=/repo/.env,readonly',
                  '--workdir', '/repo']
        for key, value in record['runtime']['environment'].items():
            docker += ['-e', key + '=' + value]
        docker += ['--entrypoint', 'python', args.image, *command]
        print(json.dumps(docker), flush=True)
        return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
