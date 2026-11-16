"""Read a committed prefix without restoring or changing the source run."""
import gzip
import hashlib
import json
from pathlib import Path
import re

from sentinel.feed.calendar import sessions_in_range
from sentinel.feed.rolling_contract import digest


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf8')


def authenticate(identity: bytes, checkpoint: bytes, pointer: dict, daily: bytes) -> tuple[dict, list[dict]]:
    name = pointer['file']
    if not re.fullmatch(r'checkpoint-[0-9a-f]{64}\.json\.gz', name):
        raise ValueError('invalid checkpoint filename')
    if sha(checkpoint) != pointer['sha256'] or name != f"checkpoint-{sha(checkpoint)}.json.gz":
        raise ValueError('checkpoint hash changed')
    binding = json.loads(identity)['binding']
    saved = json.loads(gzip.decompress(checkpoint))
    if saved['binding'] != digest(binding) or saved['cursor'] != pointer['session']:
        raise ValueError('checkpoint binding or cursor changed')
    expected = saved['outputs']['daily.jsonl']
    if expected != dict(bytes=len(daily), sha256=sha(daily)) or not daily.endswith(b'\n'):
        raise ValueError('committed daily prefix changed')
    rows = [json.loads(line) for line in daily.splitlines()]
    if (not rows or len(rows) != saved['measured'] or rows[-1]['session'] != saved['cursor']
            or rows[0]['session'] != binding['measurement_start']):
        raise ValueError('daily measurement boundary changed')
    if [r['session'] for r in rows] != sessions_in_range(rows[0]['session'], saved['cursor']):
        raise ValueError('daily sessions are not contiguous')
    return binding, rows


def capture(source: Path, destination: Path) -> None:
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('snapshot must be separate from source run')
    pointer = json.loads((source/'latest-checkpoint.json').read_text())
    if not re.fullmatch(r'checkpoint-[0-9a-f]{64}\.json\.gz', pointer['file']):
        raise ValueError('invalid checkpoint filename')
    identity = (source/'identity.json').read_bytes()
    checkpoint = (source/pointer['file']).read_bytes()
    if sha(checkpoint) != pointer['sha256']:
        raise ValueError('checkpoint hash changed')
    saved = json.loads(gzip.decompress(checkpoint))
    with (source/'daily.jsonl').open('rb') as stream:
        daily = stream.read(saved['outputs']['daily.jsonl']['bytes'])
    authenticate(identity, checkpoint, pointer, daily)
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'identity.json').write_bytes(identity)
    (destination/pointer['file']).write_bytes(checkpoint)
    (destination/'daily.jsonl').write_bytes(daily)
    write_json(destination/'latest-checkpoint.json', pointer)
    write_json(destination/'manifest.json', dict(schema='exposure-oracle-snapshot/1',
        source=str(source), checkpoint=pointer, binding=saved['binding'], through=saved['cursor'],
        measured_sessions=saved['measured'], identity_sha256=sha(identity), daily=saved['outputs']['daily.jsonl']))


def load(snapshot: Path, start: str | None = None, end: str | None = None) -> tuple[dict, list[dict]]:
    pointer = json.loads((snapshot/'latest-checkpoint.json').read_text())
    if not re.fullmatch(r'checkpoint-[0-9a-f]{64}\.json\.gz', pointer['file']):
        raise ValueError('invalid checkpoint filename')
    identity = (snapshot/'identity.json').read_bytes()
    binding, rows = authenticate(identity, (snapshot/pointer['file']).read_bytes(), pointer,
                                 (snapshot/'daily.jsonl').read_bytes())
    manifest = json.loads((snapshot/'manifest.json').read_text())
    if manifest['identity_sha256'] != sha(identity) or manifest['checkpoint'] != pointer:
        raise ValueError('snapshot manifest changed')
    start, end = start or rows[0]['session'], end or rows[-1]['session']
    sessions = {r['session'] for r in rows}
    if start not in sessions or end not in sessions or start >= end:
        raise ValueError('period must contain at least two completed session closes')
    return binding, [r for r in rows if start <= r['session'] <= end]


def verify_accountant_sources(binding: dict, root: Path) -> dict:
    names = ('sentinel/shadow_observation.py', 'sentinel/formed_economics.py')
    actual = {name:sha((root/name).read_bytes()) for name in names}
    if any(actual[name] != binding['production']['files'].get(name) for name in names):
        raise ValueError('canonical accounting sources differ from recorded replay')
    return actual
