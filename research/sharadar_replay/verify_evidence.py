"""Verify complete, passing evidence from all independent CI shards."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


CATALOGUE = Path(__file__).with_name('scenario_catalogue.json')
REQUIRED_RECOVERY_TESTS = Path(__file__).with_name('required_recovery_tests.json')


def _load_required_recovery_tests(path: Path) -> list[str]:
    authority = json.loads(path.read_text())
    assert authority.get('schema') == 'sharadar-replay-required-recovery-tests/1', \
        'invalid required recovery-test schema'
    required = authority.get('required_tests')
    assert isinstance(required, list) and required, 'empty required recovery-test inventory'
    assert all(isinstance(item, str) and item for item in required), \
        'invalid required recovery-test id'
    assert len(required) == len(set(required)), 'duplicate required recovery-test id'
    return required


def _require_catalogue_coverage(scenarios, collected, catalogue, required_recovery):
    assert catalogue['schema'] == 'sharadar-replay-catalogue/1', 'invalid catalogue schema'
    declared = catalogue['scenarios']
    assert declared, 'empty scenario catalogue'
    assert Counter(scenarios) == Counter(declared.keys()), 'declared scenario coverage differs'
    assert set(catalogue['required_tests']).issubset(collected), 'required falsifier coverage differs'
    assert set(required_recovery).issubset(collected), 'required recovery-test coverage differs'


def verify(root: Path, *, commit: str, shards: int = 4,
           catalogue_path: Path = CATALOGUE,
           required_recovery_path: Path = REQUIRED_RECOVERY_TESTS) -> dict:
    catalogue = json.loads(catalogue_path.read_text())
    required_recovery = _load_required_recovery_tests(required_recovery_path)
    manifests = sorted(root.glob('*/collection.json'))
    assert len(manifests) == shards, 'missing or extra shard manifests'
    collected = None
    selected_all, indices, scenarios = [], [], []
    for manifest in manifests:
        data = json.loads(manifest.read_text())
        index = data['shard']
        assert data['shards'] == shards and 0 <= index < shards, 'invalid shard identity'
        indices.append(index)
        if collected is None:
            collected = data['collected']
        assert data['collected'] == collected, 'shards collected different tests'
        selected = collected[index::shards]
        assert data['selected'] == selected, 'shard selection differs from declared partition'
        selected_all.extend(selected)
        tests = list(ET.parse(manifest.parent / 'junit.xml').getroot().iter('testcase'))
        assert len(tests) == len(selected), 'missing or extra JUnit tests'
        assert all(not any(t.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for t in tests), 'JUnit contains non-passing tests'
        actual_ids = [t.attrib['classname'] + '::' + t.attrib['name'] for t in tests]
        expected_ids = [s.replace('.py::', '::').replace('/', '.') for s in selected]
        assert Counter(actual_ids) == Counter(expected_ids), 'JUnit test identities differ'
        expected_scenarios = [m.group(1) for s in selected
                              if (m := re.search(r'::test_daily_production_replay\[(.+)\]$', s))]
        reports = [json.loads(p.read_text()) for p in manifest.parent.glob('*/report.json')]
        assert Counter(r['scenario'] for r in reports) == Counter(expected_scenarios), 'scenario report coverage differs'
        for report in reports:
            assert report['commit'] == commit, 'report code commit differs'
            assert report['verdict'] == 'PASS' and report['steps'], 'scenario failed or has no steps'
            assert [s['step'] for s in report['steps']] == catalogue['scenarios'].get(report['scenario']), 'declared step coverage differs'
            assert all(s['corpus_digest'] == s['expected_digest'] for s in report['steps']), 'corpus digest differs'
        scenarios.extend(expected_scenarios)
    assert sorted(indices) == list(range(shards)), 'duplicate or missing shard indices'
    assert collected and len(set(collected)) == len(collected), 'empty or duplicate test collection'
    assert Counter(selected_all) == Counter(collected), 'test partition is incomplete'
    _require_catalogue_coverage(scenarios, collected, catalogue, required_recovery)
    return {'verdict': 'PASS', 'commit': commit, 'tests': len(collected),
            'scenarios': len(scenarios), 'shards': shards}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--shards', type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, commit=args.commit, shards=args.shards), sort_keys=True))
