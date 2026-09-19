"""Reproduce one bounded offline acceptance campaign or falsifier."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    here = Path(__file__).resolve().parent
    record = json.loads((here / 'commands.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', choices=[*record['campaigns'], *record['mutations']])
    parser.add_argument('--image', default=record['runtime']['image'])
    args = parser.parse_args()
    command = (['-u', '-m', 'pytest', *record['campaigns'][args.campaign], *record['pytest_common']]
               if args.campaign in record['campaigns'] else
               ['-u', *record['mutations'][args.campaign]])
    with tempfile.TemporaryDirectory(prefix='sentinel-offline-') as directory:
        empty = Path(directory) / 'empty.env'
        empty.write_bytes(b'')
        docker = ['docker', 'run', '--rm', '--network', 'none',
                  '--mount', f'type=bind,source={here.parents[2].as_posix()},target=/repo,readonly',
                  '--workdir', '/repo']
        if (here.parents[2] / '.env').exists():
            docker += ['--mount', f'type=bind,source={empty.as_posix()},target=/repo/.env,readonly']
        for key, value in record['runtime']['environment'].items():
            docker += ['-e', key + '=' + value]
        docker += ['--entrypoint', 'python', args.image, *command]
        print(json.dumps(docker), flush=True)
        return subprocess.run(docker).returncode


if __name__ == '__main__':
    raise SystemExit(main())
