"""Canonical single-level storage for complete, independently pinned inventories.

This serializer grants no compatibility authority. The runtime checker validates
the expanded maps against its independent revision/count/closure pins.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile


_CATALOG = Path('sentinel/url-selected-trading-transition.json')
_CHECKER = Path('sentinel/url_selected_source_basis.py')
_PIN = re.compile(rb"^PROFILE_SHA256 = '([0-9a-f]{64})'$", re.MULTILINE)


def _sha(contents):
    return hashlib.sha256(contents).hexdigest()


def _closure(files):
    return _sha(b''.join(f'{name}\0{digest}\n'.encode()
                         for name, digest in sorted(files.items())))


def _git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def _inventory(repo, commit):
    raw = _git(repo, 'archive', commit, 'sentinel')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for entry in archive:
            if entry.name.endswith('.py'):
                if not entry.isfile() or entry.name in files:
                    raise ValueError('unsupported or duplicate Python source entry')
                files[entry.name] = _sha(archive.extractfile(entry).read())
    return {name[len('sentinel/'):]: digest for name, digest in files.items()}


def compact(value):
    anchor = value.get('retained_anchor_files', value['candidate_files'])
    records = {}
    for revision, record in value['retained_predecessors'].items():
        files = record['files']
        records[revision] = dict(source_sha256=record['source_sha256'],
            overrides={name: digest for name, digest in files.items()
                       if anchor.get(name) != digest},
            removed=sorted(set(anchor)-set(files)))
    return {**value, 'retained_predecessors': records}


def encoded(value):
    return (json.dumps(compact(value), sort_keys=True, separators=(',', ':'),
                       allow_nan=False)+'\n').encode('utf-8')


def seal_candidate(repo, predecessor, candidate):
    """Read reviewed Git objects and emit the next exact-source comparison edge."""
    for commit in (predecessor, candidate):
        if re.fullmatch('[0-9a-f]{40}', commit) is None:
            raise ValueError('source identities must be complete Git commit hashes')
    if predecessor == candidate or _git(repo, 'merge-base', predecessor, candidate).decode().strip() != predecessor:
        raise ValueError('candidate must descend from the installed predecessor')
    old_raw = _git(repo, 'show', f'{predecessor}:{_CATALOG.as_posix()}')
    checker = _git(repo, 'show', f'{predecessor}:{_CHECKER.as_posix()}')
    for path, previous in ((_CATALOG, old_raw), (_CHECKER, checker)):
        if _git(repo, 'show', f'{candidate}:{path.as_posix()}') != previous:
            raise ValueError(f'candidate edited generated source input {path}')

    pins = _PIN.findall(checker)
    if pins != [_sha(old_raw).encode()]:
        raise ValueError('predecessor catalog digest differs from its checker')
    old = json.loads(old_raw)
    normalized = _PIN.sub(b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", checker)
    if (old['authority_effect'] != 'NONE' or old['module_sha256'] != _sha(normalized)):
        raise ValueError('predecessor source comparison boundary differs')

    predecessor_files = _inventory(repo, predecessor)
    if predecessor_files != {**old['candidate_files'], _CHECKER.name: _sha(checker)}:
        raise ValueError('predecessor catalog does not cover the reviewed Git inventory')
    anchor = old['retained_anchor_files']
    retained = {}
    for revision, record in old['retained_predecessors'].items():
        files = {name: digest for name, digest in anchor.items() if name not in record['removed']}
        files.update(record['overrides'])
        if _closure(files) != record['source_sha256']:
            raise ValueError(f'retained source inventory changed for {revision}')
        retained[revision] = {'files': files, 'source_sha256': record['source_sha256']}
    if predecessor in retained:
        raise ValueError('catalog already contains the installed predecessor')
    digest = _closure(predecessor_files)
    retained[predecessor] = {'files': predecessor_files, 'source_sha256': digest}
    schema_prefix = 'sentinel.url-selected-trading-transition/'
    if not old['schema'].startswith(schema_prefix):
        raise ValueError('unsupported predecessor source catalog schema')
    next_schema = schema_prefix + str(int(old['schema'][len(schema_prefix):]) + 1)
    registration = "RETAINED_PREDECESSORS = {"
    old_schema = f"_SCHEMA = '{old['schema']}'"
    for marker in (registration, old_schema):
        if normalized.count(marker.encode()) != 1:
            raise ValueError('unexpected predecessor source checker shape')
    normalized = normalized.replace(registration.encode(),
        (registration + f"\n    '{predecessor}': ({len(predecessor_files)}, '{digest}'),").encode())
    normalized = normalized.replace(old_schema.encode(), f"_SCHEMA = '{next_schema}'".encode())
    current = _inventory(repo, candidate)
    current.pop(_CHECKER.name)
    raw = encoded({**old, 'schema': next_schema, 'module_sha256': _sha(normalized),
                   'candidate_files': current, 'retained_predecessors': retained})
    if len(raw) > 1_000_000:
        raise ValueError('compact profile exceeds the existing file bound')
    return raw, _PIN.sub(f"PROFILE_SHA256 = '{_sha(raw)}'".encode(), normalized)


def _seal_cli(argv):
    parser = argparse.ArgumentParser(description=seal_candidate.__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--predecessor', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path, required=True, help='new artifact directory')
    args = parser.parse_args(argv)
    raw, checker = seal_candidate(args.repo, args.predecessor, args.candidate)
    args.output.mkdir(mode=0o700)
    (args.output / _CATALOG.name).write_bytes(raw)
    (args.output / _CHECKER.name).write_bytes(checker)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'seal':
        _seal_cli(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='expanded logical profile JSON')
    parser.add_argument('output', type=Path, help='new compact profile; must not exist')
    args = parser.parse_args()
    raw = encoded(json.loads(args.input.read_bytes()))
    if len(raw) > 1_000_000:
        parser.error('compact profile exceeds the existing file bound')
    with args.output.open('xb') as stream:
        stream.write(raw)


if __name__ == '__main__':
    main()
