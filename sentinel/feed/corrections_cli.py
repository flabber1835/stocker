"""Attended source-data installation; no acquisition, publication or broker I/O."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from sentinel.feed import source_corrections as data
from sentinel.feed.correction_model import CorrectionRefused, require_extension, validate
from sentinel.feed.rolling_contract import canonical_json, digest


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install(value, *, expected_sha256, expected_parent, reviewer):
    """CAS installation under one Linux kernel lock, including Synology 3.10."""
    import fcntl
    value = validate(value)
    identity = digest(value)
    if identity != expected_sha256 or not reviewer.strip() or len(reviewer) > 256:
        raise CorrectionRefused('explicit content digest and bounded reviewer are required')
    directory = data.root()
    directory.parent.mkdir(parents=True, exist_ok=True)
    # The lock is outside the dataset directory: a failed validation must not
    # create an apparently installed but incomplete dataset.
    with (directory.parent / 'source-corrections-v1.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CorrectionRefused('another correction installation is running') from exc
        previous = data.installed()
        if digest(previous) == identity:
            if expected_parent == identity:
                return identity
            # A committed install whose response was lost is idempotent too.
            if data.root().exists() and data.read(data.root() / 'current.json')['installation']['parent_sha256'] == expected_parent:
                return identity
        if digest(previous) != expected_parent:
            raise CorrectionRefused('correction predecessor changed; review current dataset')
        require_extension(previous, value)
        if identity == expected_parent:
            return identity
        payload = {'dataset': value, 'parent_sha256': expected_parent,
                   'reviewer': reviewer, 'installed_at': datetime.now(timezone.utc).isoformat()}
        envelope = {'installation': payload, 'hmac_sha256': data.signature(payload)}
        encoded = canonical_json(envelope).encode('ascii')
        # Prepare the entire first installation before exposing its directory.
        first = not directory.exists()
        target = Path(tempfile.mkdtemp(dir=directory.parent, prefix='.corrections-')) if first else directory
        archive = target / (identity + '.json')
        if archive.exists():
            # A crash after archiving but before changing current is retryable.
            retained = data.read(archive)
            existing = data.authenticated(retained)
            if existing != value or retained['installation']['parent_sha256'] != expected_parent:
                raise CorrectionRefused('retained correction installation differs from requested update')
            envelope = retained
            encoded = canonical_json(envelope).encode('ascii')
        else:
            _replace(target, archive, encoded)
        _replace(target, target / 'current.json', encoded)
        if first:
            os.rename(target, directory)
            _sync(directory.parent)
        return identity


def _replace(directory, path, encoded):
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.install-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('export')
    check = sub.add_parser('validate')
    check.add_argument('path', type=Path)
    approve = sub.add_parser('install')
    approve.add_argument('path', type=Path)
    approve.add_argument('--expected-sha256', required=True)
    approve.add_argument('--expected-parent', required=True)
    approve.add_argument('--reviewer', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'install':
            identity = install(data.read(args.path), expected_sha256=args.expected_sha256,
                               expected_parent=args.expected_parent, reviewer=args.reviewer)
            print(json.dumps({'installed_sha256': identity}))
        else:
            value = validate(data.read(args.path)) if args.command == 'validate' else data.installed()
            print(json.dumps(value if args.command == 'export' else {
                'sha256': digest(value), 'coverage_records': len(value['coverage']),
                'cash_authorities': len(value['cash_authorities'])}, sort_keys=True, indent=2))
        return 0
    except (CorrectionRefused, OSError, ValueError) as exc:
        print('REFUSED: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
