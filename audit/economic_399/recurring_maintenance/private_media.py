"""Exercise actual offline worker CLI against private, mixed-UID Docker media."""
import argparse
import json
from pathlib import Path
import subprocess
import re
import uuid

ROOT = Path(__file__).resolve().parents[3]


def run(command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    print(result.stdout, end="")
    print(result.stderr, end="")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-image')
    args = parser.parse_args()
    if args.runtime_image and not re.fullmatch(r'sha256:[0-9a-f]{64}', args.runtime_image):
        raise ValueError('the optional baked worker must use an immutable local image ID')
    volume = 'sentinel-maintenance-private-' + uuid.uuid4().hex[:12]
    created = subprocess.run(['docker', 'volume', 'create', volume], check=True)
    assert created.returncode == 0
    common = ['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
              '-v', volume + ':/backup', '-v', ROOT.as_posix() + ':/workspace:ro',
              '-e', 'PYTHONPATH=/workspace:/workspace/tests/backup:/workspace/scripts',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', 'python']
    seed = '''from pathlib import Path
import json,os
from test_recurring_maintenance import media,receipt,IMAGE,NOW,SEGMENT,SYSTEM
value=media.__wrapped__(Path('/backup'))
namespace=value.wal/('cluster-'+SYSTEM)
for index in (130,131):
    p=namespace/('0000000100000000%08X'%index)
    p.write_bytes(b'fixture')
    os.chmod(p,0o600);os.chown(p,999,999)
os.chown(namespace,999,999);os.chmod(namespace,0o700)
for p in value.base.glob('base-*'):
    os.chmod(p,0o710)
    for field in ('backup_manifest','backup_label','sentinel-recovery-marker','sentinel-pitr-base-identity'):
        os.chmod(p/field,0o640);os.chown(p/field,0,999)
request={'receipt':receipt(value.selected()),'image':IMAGE,'now':NOW,'segment_size':SEGMENT}
print(json.dumps(request))
'''
    try:
        result = run(common + ['sentinel-test:ci', '-c', seed])
        assert result.returncode == 0
        request_value = json.loads(result.stdout.strip().splitlines()[-1])
        if args.runtime_image:
            request_value['image'] = args.runtime_image
            request_value['receipt']['runtime_image'] = args.runtime_image
        request = json.dumps(request_value)
        worker = [args.runtime_image or 'sentinel-test:ci', '-m', 'sentinel.backup_retention', 'retain',
                  '--system-id', '7377777777777777777']
        invocation = common[:3] + ['-i'] + common[3:]
        if args.runtime_image:
            # No source overlay or PYTHONPATH: exercise only baked runtime bytes.
            invocation = ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0',
                          '--read-only', '--security-opt', 'no-new-privileges',
                          '-v', volume + ':/backup', '--entrypoint', 'python']
        # Negative control: root alone with all capabilities dropped cannot
        # traverse PostgreSQL's 0700 namespace. No permission loosening allowed.
        denied = run(invocation + ['--cap-drop', 'ALL'] + worker, input=request)
        assert denied.returncode == 4 and 'Permission denied' in denied.stderr
        allowed = run(invocation + ['--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE'] + worker,
                      input=request)
        assert allowed.returncode == 0
        assert json.loads(allowed.stdout)['base_removed'] == 62
        assert json.loads(allowed.stdout)['wal_removed'] == 1
        check = run(common + ['sentinel-test:ci', '-c',
            "from pathlib import Path; p=Path('/backup/wal/cluster-7377777777777777777'); "
            "assert not (p/'000000010000000000000082').exists(); "
            "assert (p/'000000010000000000000083').read_bytes()==b'fixture'; "
            "assert p.stat().st_mode & 0o777 == 0o700; assert p.stat().st_uid==999; "
            "print('PRIVATE_MEDIA: exact floor retained; PostgreSQL 0700 ownership unchanged')"])
        assert check.returncode == 0
    finally:
        subprocess.run(['docker', 'volume', 'rm', volume], check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
