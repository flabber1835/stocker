"""Strict host phase documents with atomic, non-overwriting completion records."""
import json
import math
import os
from pathlib import Path
import tempfile


def read_document(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('duplicate phase document key')
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError('non-finite phase document number')
    def number(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError('non-finite phase document number')
        return value
    value = json.loads(Path(path).read_text(encoding='utf-8'),
                       object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)
    if not isinstance(value, dict):
        raise ValueError('phase document must be an object')
    return value


def write_document(path, value, *, immutable=False):
    path = Path(path)
    if not isinstance(value, dict):
        raise ValueError('phase document must be an object')
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, str(path))
        else:
            os.replace(temporary, str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def publish_immutable(path, value):
    write_document(path, value, immutable=True)
