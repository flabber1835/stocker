#!/usr/bin/env python3
"""Falsify the receipt helper's capability boundary on an isolated bind mount."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STAMP = '20261117T200720Z-068e378f7e53'
RELATIVE = f'deployments/{STAMP}/installation-receipt.json'
IMAGE_PLACEHOLDER = 'sha256:' + '0' * 64


def _service():
    env = dict(os.environ)
    env.update(
        SENTINEL_POSTGRES_PASSWORD='isolated-test-only',
        SENTINEL_PUBLICATION_RECEIPT_KEY='isolated-test-only',
        SENTINEL_GIT_COMMIT='0' * 40,
        SENTINEL_RUNTIME_IMAGE_DIGEST=IMAGE_PLACEHOLDER,
        SENTINEL_TEST_IMAGE_DIGEST=IMAGE_PLACEHOLDER,
    )
    result = subprocess.run(
        ['docker', 'compose', '--profile', 'authorized-cli',
         '-f', 'docker-compose.sentinel.yml',
         '-f', 'docker-compose.sentinel-automation.yml',
         'config', '--format', 'json'],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    service = json.loads(result.stdout)['services']['sentinel-authority-permissions']
    assert service['user'] == '0:0'
    assert service['network_mode'] == 'none'
    assert service['cap_drop'] == ['ALL']
    assert service['cap_add'] == ['DAC_OVERRIDE', 'FOWNER', 'CHOWN']
    assert service['security_opt'] == ['no-new-privileges:true']
    assert service['entrypoint'] == ['sh', '-ceu']
    assert len(service['command']) == 1
    return service


def _run(service, authority, *, chown):
    capabilities = [cap for cap in service['cap_add'] if chown or cap != 'CHOWN']
    command = [
        'docker', 'run', '--rm', '--network', service['network_mode'],
        '--user', service['user'], '--cap-drop', 'ALL',
    ]
    for cap in capabilities:
        command.extend(('--cap-add', cap))
    for option in service['security_opt']:
        command.extend(('--security-opt', option))
    command.extend((
        '--mount', f'type=bind,source={authority},target=/authority',
        '--env', f'SENTINEL_RECOVERY_RECEIPT_REL={RELATIVE}',
        service['image'], *service['entrypoint'],
        service['command'][0].replace('$$', '$'),
    ))
    return subprocess.run(command, capture_output=True, text=True)


def _snapshot(path):
    state = path.stat()
    return state.st_gid, state.st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.name != 'posix' or os.geteuid() == 0:
        raise SystemExit('run this Docker bind-mount test as a non-root host user')
    service = _service()
    with tempfile.TemporaryDirectory(prefix='sentinel-receipt-capabilities-') as directory:
        authority = Path(directory) / 'authority'
        receipt = authority / RELATIVE
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b'{"schema":"sentinel.installation-receipt/1"}\n')
        receipt.chmod(0o600)
        sibling = authority / 'deployments' / (STAMP + '-1') / 'installation-receipt.json'
        sibling.parent.mkdir()
        sibling.write_bytes(b'unrelated receipt\n')
        sibling.chmod(0o600)
        before = _snapshot(receipt)
        sibling_before = _snapshot(sibling)
        assert receipt.stat().st_uid == os.geteuid() and before[0] != 10001

        denied = _run(service, authority, chown=False)
        assert denied.returncode != 0, 'receipt helper succeeded without CAP_CHOWN'
        assert 'chgrp:' in denied.stderr, denied.stderr
        assert _snapshot(receipt) == before
        assert _snapshot(sibling) == sibling_before

        allowed = _run(service, authority, chown=True)
        assert allowed.returncode == 0, allowed.stderr
        assert _snapshot(receipt) == (10001, 0o640, before[2])
        assert _snapshot(sibling) == sibling_before

        # A later retry must be safe even when the exact receipt is already
        # group-readable. A no-op chgrp is separately probed without CHOWN.
        noop = _run(service, authority, chown=False)
        assert noop.returncode != 0, 'no-op chgrp unexpectedly bypassed CAP_CHOWN'
        assert 'chgrp:' in noop.stderr, noop.stderr
        assert _snapshot(receipt) == (10001, 0o640, before[2])
        assert _snapshot(sibling) == sibling_before
    print('fenced receipt capability falsifier passed')


if __name__ == '__main__':
    main()
