"""Research-only atomic checkpoint and output-prefix journal."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time

from sentinel.feed.rolling_contract import digest
from sentinel.core.session import SessionState

OUTPUTS = ('daily.jsonl', 'monthly.jsonl', 'monthly.csv', 'terminal-audit.jsonl',
           'formation.jsonl', 'fills.jsonl', 'positions.jsonl')


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def append(root, name, value):
    with (Path(root)/name).open('a', encoding='utf8', newline='\n') as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False)+'\n')


def file_prefix(path, size=None):
    h, read = hashlib.sha256(), 0
    with Path(path).open('rb') as stream:
        while block := stream.read(min(1024*1024, size-read) if size is not None else 1024*1024):
            h.update(block)
            read += len(block)
    return dict(bytes=read, sha256=h.hexdigest())


def checkpoint(root, payload):
    root = Path(root)
    value = {**payload, 'outputs':{name:file_prefix(root/name) for name in OUTPUTS if (root/name).exists()}}
    temporary = root/'checkpoint.tmp.gz'
    with temporary.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0) as stream:
            stream.write(json.dumps(value, separators=(',', ':'), allow_nan=False).encode())
        raw.flush()
        os.fsync(raw.fileno())
    sha = file_prefix(temporary)['sha256']
    path = root/('checkpoint-'+sha+'.json.gz')
    temporary.replace(path)
    write_json(root/'latest-checkpoint.json', dict(file=path.name, sha256=sha, session=value['cursor']))
    return path


def checkpoint_pointer(root, checkpoint_file=None):
    if checkpoint_file is None:
        return json.loads((Path(root)/'latest-checkpoint.json').read_text())
    match = re.fullmatch(r'checkpoint-([0-9a-f]{64})\.json\.gz', checkpoint_file)
    if not match:
        raise ValueError('invalid selected checkpoint filename')
    return dict(file=checkpoint_file, sha256=match.group(1))


def read_checkpoint(root, binding, checkpoint_file=None):
    """Authenticate a checkpoint without changing even an uncommitted suffix."""
    root = Path(root)
    pointer = checkpoint_pointer(root, checkpoint_file)
    path = (root/pointer['file']).resolve()
    if root.resolve() != path.parent or file_prefix(path)['sha256'] != pointer['sha256']:
        raise ValueError('checkpoint bytes changed')
    with gzip.open(path, 'rt', encoding='utf8') as stream:
        value = json.load(stream)
    if (value['binding'] != digest(binding)
            or ('session' in pointer and value['cursor'] != pointer['session'])):
        raise ValueError('checkpoint binding changed')
    state = SessionState.from_dict(value['state'])
    if state.state_hash != value['state_sha256']:
        raise ValueError('checkpoint canonical state changed')
    if state.last_processed_session is not None and state.last_processed_session != value['cursor']:
        raise ValueError('checkpoint state cursor changed')
    for name, expected in value['outputs'].items():
        if name not in OUTPUTS or file_prefix(root/name, expected['bytes']) != expected:
            raise ValueError('committed output prefix changed')
    return value, state


def restore(root, binding):
    root = Path(root)
    value, state = read_checkpoint(root, binding)
    # Validation completes before preserving and truncating task-owned suffixes.
    for name in OUTPUTS:
        path = root/name
        expected_size = value['outputs'].get(name, {}).get('bytes', 0)
        if path.exists() and path.stat().st_size > expected_size:
            with path.open('rb') as stream:
                stream.seek(expected_size)
                suffix = stream.read()
            (root/(name+'.uncommitted-'+str(time.time_ns()))).write_bytes(suffix)
            with path.open('r+b') as stream:
                stream.truncate(expected_size)
    return value, state
