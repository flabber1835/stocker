"""Canonical single-level storage for complete, independently pinned inventories.

This serializer grants no compatibility authority. The runtime checker validates
the expanded maps against its independent revision/count/closure pins.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compact(value):
    anchor = value['candidate_files']
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


def main():
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
