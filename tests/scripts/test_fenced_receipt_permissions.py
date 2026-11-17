"""Exercise the Compose permission helper without touching installed authority."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
STAMP = '20261117T200720Z-068e378f7e53'


def _helper(authority, relative):
    compose = yaml.safe_load((ROOT / 'docker-compose.sentinel-automation.yml').read_text())
    command = compose['services']['sentinel-authority-permissions']['command'][0]
    # Docker Compose reduces $$ to a literal $ before the service shell runs.
    command = command.replace('$$', '$').replace('/authority', str(authority))
    env = dict(os.environ, SENTINEL_RECOVERY_RECEIPT_REL=relative)
    return subprocess.run(['sh', '-ceu', command], env=env,
                          capture_output=True, text=True)


def _authority():
    return tempfile.TemporaryDirectory(prefix='fenced-receipt-permissions-')


@pytest.mark.skipif(os.name != 'posix' or os.geteuid() != 0,
                    reason='UID/GID permission probe requires the root CI container')
def test_exact_receipt_becomes_readable_to_nonroot_cli_without_byte_change():
    with _authority() as directory:
        base = Path(directory)
        base.chmod(0o711)
        authority = base / 'authority'
        receipt = authority / 'deployments' / STAMP / 'installation-receipt.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b'{"schema":"sentinel.installation-receipt/1"}\n')
        receipt.chmod(0o600)
        other = authority / 'deployments' / (STAMP + '-1') / 'installation-receipt.json'
        other.parent.mkdir()
        other.write_bytes(b'other immutable receipt\n')
        other.chmod(0o600)
        original = hashlib.sha256(receipt.read_bytes()).hexdigest()
        relative = 'deployments/' + STAMP + '/installation-receipt.json'
        result = _helper(authority, relative)
        assert result.returncode == 0, result.stderr
        assert stat.S_IMODE(receipt.stat().st_mode) == 0o640
        assert receipt.stat().st_gid == 10001
        assert hashlib.sha256(receipt.read_bytes()).hexdigest() == original
        assert stat.S_IMODE(other.stat().st_mode) == 0o600

        def drop_to_cli():
            os.setgroups([])
            os.setgid(10001)
            os.setuid(10001)

        read = subprocess.run([sys.executable, '-c',
                               'from pathlib import Path; '
                               'assert Path(%r).read_bytes() == %r' %
                               (str(receipt), receipt.read_bytes())],
                              preexec_fn=drop_to_cli, capture_output=True, text=True)
        assert read.returncode == 0, read.stderr


@pytest.mark.parametrize('invalid', ['traversal', 'symlink', 'wrong-basename'])
def test_helper_refuses_noncanonical_receipt_without_permission_change(invalid):
    with _authority() as directory:
        authority = Path(directory) / 'authority'
        stamp = authority / 'deployments' / STAMP
        stamp.mkdir(parents=True)
        original = stamp / 'installation-receipt.json'
        original.write_bytes(b'original\n')
        original.chmod(0o600)
        if invalid == 'traversal':
            relative = 'deployments/' + STAMP + '/../installation-receipt.json'
        elif invalid == 'symlink':
            link = authority / 'deployments' / (STAMP + '-1') / 'installation-receipt.json'
            link.parent.mkdir()
            link.symlink_to(original)
            relative = 'deployments/' + STAMP + '-1/installation-receipt.json'
        else:
            wrong = stamp / 'other.json'
            wrong.write_bytes(b'other\n')
            wrong.chmod(0o600)
            relative = 'deployments/' + STAMP + '/other.json'
        result = _helper(authority, relative)
        assert result.returncode != 0
        assert stat.S_IMODE(original.stat().st_mode) == 0o600
