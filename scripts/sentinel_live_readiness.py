#!/usr/bin/env python3
"""Read a bounded file-only preparation inventory. Exit 3 means NOT_QUALIFIED."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel.live_readiness import MAX_ARTIFACT_BYTES, MAX_TOTAL_BYTES, PreparationManifest, inventory


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError('nonfinite JSON number')


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError('a regular evidence file is required')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('file exceeds its byte bound')
    return raw


def read_manifest(path: Path) -> PreparationManifest:
    material = json.loads(_read(path, 1024 * 1024).decode('utf-8'),
                          object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    return PreparationManifest.model_validate(material)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.manifest)
        directory = args.evidence_dir.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError('an evidence directory is required')
        artifacts = {}
        for reference in manifest.evidence:
            if reference.artifact in artifacts:
                continue
            path = directory / reference.artifact
            if not path.exists():
                continue
            artifacts[reference.artifact] = _read(path, MAX_ARTIFACT_BYTES)
            if sum(map(len, artifacts.values())) > MAX_TOTAL_BYTES:
                raise ValueError('evidence exceeds the aggregate byte bound')
        result = inventory(manifest, artifacts, now=datetime.now(timezone.utc))
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        # Validation errors may echo arbitrary input. Do not print file content.
        print(json.dumps({'status': 'INVALID_INPUT', 'error': type(exc).__name__}), file=sys.stderr)
        return 2
    print(result.model_dump_json(by_alias=True, indent=2))
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
