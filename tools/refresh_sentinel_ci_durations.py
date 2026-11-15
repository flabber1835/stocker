"""Refresh scheduling estimates from the complete successful Sentinel CI lanes."""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree

from sentinel_ci_parallel_evidence import SENTINEL_LANES
from sentinel_ci_shards import MODULE


def _sha(contents):
    return hashlib.sha256(contents).hexdigest()


def build_manifest(root, artifacts, commit, run, attempt, *, default=60_000):
    if not re.fullmatch('[0-9a-f]{40}', commit) or run < 1 or attempt < 1 or default < 1:
        raise ValueError('invalid CI timing evidence subject')
    tree = subprocess.check_output(['git', '-C', str(root), 'rev-parse', f'{commit}^{{tree}}'],
                                   text=True).strip()
    inventory = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '--name-only',
                                         commit, '--', 'tests/sentinel'], text=True).splitlines()
    expected = {path for path in inventory if MODULE.fullmatch(path)}
    modules = defaultdict(Decimal)
    cases = set()
    hashes = []
    bundle_id = None
    for lane in sorted(SENTINEL_LANES):
        folder = artifacts / f'sentinel-ci-lane-{lane}-{commit}-{attempt}'
        receipt = json.loads((folder / 'receipt.json').read_bytes())
        identity = receipt['identity']
        if (receipt['schema'] != 'sentinel.ci-lane-receipt/1' or receipt['lane'] != lane
                or identity['commit'] != commit or identity['tree'] != tree
                or str(identity['workflow_run']) != str(run)
                or int(identity['workflow_attempt']) != attempt):
            raise ValueError(f'{lane}: receipt differs from the reviewed CI subject')
        bundle_id = receipt['bundle_sha256'] if bundle_id is None else bundle_id
        if receipt['bundle_sha256'] != bundle_id or not re.fullmatch('[0-9a-f]{64}', bundle_id):
            raise ValueError(f'{lane}: receipt identifies a different runtime bundle')
        filename = f'{lane}.xml'
        xml = (folder / filename).read_bytes()
        digest = _sha(xml)
        if digest != receipt['files'][filename]:
            raise ValueError(f'{lane}: JUnit evidence digest differs from the receipt')
        hashes.append(f'{lane}\0{digest}\n')
        recorded = list(ElementTree.fromstring(xml).iter('testcase'))
        if not recorded:
            raise ValueError(f'{lane}: JUnit evidence has no tests')
        for case in recorded:
            identity = case.attrib['classname'], case.attrib['name']
            if identity in cases or any(case.find(tag) is not None for tag in ('skipped', 'error', 'failure')):
                raise ValueError(f'{lane}: duplicate or non-passing test in duration evidence')
            cases.add(identity)
            module = '/'.join(identity[0].split('.')[:3]) + '.py'
            if module not in expected:
                raise ValueError(f'{lane}: JUnit module is outside the tracked Sentinel owner: {module}')
            duration = Decimal(case.attrib['time'])
            if not duration.is_finite() or duration < 0:
                raise ValueError(f'{lane}: invalid test duration')
            modules[module] += duration
    if set(modules) != expected:
        raise ValueError(f'CI timing evidence does not cover {len(expected - set(modules))} tracked modules')
    return {'schema': 'sentinel.ci-module-durations/1', 'source_commit': commit,
            'junit_sha256': _sha(''.join(hashes).encode()), 'default_milliseconds': default,
            'modules': {path: max(1, int((seconds * 1000).to_integral_value(rounding=ROUND_HALF_UP)))
                        for path, seconds in sorted(modules.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--workflow-run', type=int, required=True)
    parser.add_argument('--workflow-attempt', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new output file')
    args = parser.parse_args()
    manifest = build_manifest(args.root, args.artifacts, args.source_commit,
                              args.workflow_run, args.workflow_attempt)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
