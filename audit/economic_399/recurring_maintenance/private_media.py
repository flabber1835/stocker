"""Exercise actual offline worker CLI against private, mixed-UID Docker media."""
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[3]


def run(command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    print(result.stdout, end="")
    print(result.stderr, end="")
    return result


def main():
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
        request = result.stdout.strip().splitlines()[-1]
        worker = ['sentinel-test:ci', '-m', 'sentinel.backup_retention', 'retain',
                  '--system-id', '7377777777777777777']
        # Negative control: root alone with all capabilities dropped cannot
        # traverse PostgreSQL's 0700 namespace. No permission loosening allowed.
        denied = run(common[:3] + ['-i'] + common[3:] + ['--cap-drop', 'ALL'] + worker, input=request)
        assert denied.returncode == 4 and 'Permission denied' in denied.stderr
        allowed = run(common[:3] + ['-i'] + common[3:] + ['--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE'] + worker,
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
