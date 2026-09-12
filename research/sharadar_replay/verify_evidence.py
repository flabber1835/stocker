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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_required_recovery_tests(path: Path) -> list[str]:
    authority = json.loads(path.read_text())
    require(authority.get('schema') == 'sharadar-replay-required-recovery-tests/1',
            'invalid required recovery-test schema')
    required = authority.get('required_tests')
    require(isinstance(required, list) and bool(required), 'empty required recovery-test inventory')
    require(all(isinstance(item, str) and item for item in required),
            'invalid required recovery-test id')
    require(len(required) == len(set(required)), 'duplicate required recovery-test id')
    return required


def _require_catalogue_coverage(scenarios, collected, catalogue, required_recovery):
    require(catalogue.get('schema') == 'sharadar-replay-catalogue/1', 'invalid catalogue schema')
    declared = catalogue.get('scenarios')
    require(isinstance(declared, dict) and bool(declared), 'empty scenario catalogue')
    require(Counter(scenarios) == Counter(declared.keys()), 'declared scenario coverage differs')
    required_tests = catalogue.get('required_tests')
    require(isinstance(required_tests, list), 'invalid catalogue required-test inventory')
    require(set(required_tests).issubset(collected), 'required falsifier coverage differs')
    require(set(required_recovery).issubset(collected), 'required recovery-test coverage differs')


def verify(root: Path, *, commit: str, shards: int = 4,
           catalogue_path: Path = CATALOGUE,
           required_recovery_path: Path = REQUIRED_RECOVERY_TESTS) -> dict:
    catalogue = json.loads(catalogue_path.read_text())
    required_recovery = _load_required_recovery_tests(required_recovery_path)
    manifests = sorted(root.glob('*/collection.json'))
    require(len(manifests) == shards, 'missing or extra shard manifests')
    collected = None
    selected_all, indices, scenarios = [], [], []
    for manifest in manifests:
        data = json.loads(manifest.read_text())
        index = data.get('shard')
        require(isinstance(index, int) and data.get('shards') == shards and 0 <= index < shards,
                'invalid shard identity')
        indices.append(index)
        if collected is None:
            collected = data.get('collected')
        require(isinstance(collected, list) and data.get('collected') == collected,
                'shards collected different tests')
        selected = collected[index::shards]
        require(data.get('selected') == selected, 'shard selection differs from declared partition')
        selected_all.extend(selected)
        junit_path = manifest.parent / 'junit.xml'
        require(junit_path.is_file(), 'missing shard JUnit evidence')
        tests = list(ET.parse(junit_path).getroot().iter('testcase'))
        require(len(tests) == len(selected), 'missing or extra JUnit tests')
        require(all(not any(t.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                    for t in tests), 'JUnit contains non-passing tests')
        actual_ids = [t.attrib.get('classname', '') + '::' + t.attrib.get('name', '') for t in tests]
        expected_ids = [s.replace('.py::', '::').replace('/', '.') for s in selected]
        require(Counter(actual_ids) == Counter(expected_ids), 'JUnit test identities differ')
        expected_scenarios = [m.group(1) for s in selected
                              if (m := re.search(r'::test_daily_production_replay\[(.+)\]$', s))]
        reports = [json.loads(p.read_text()) for p in manifest.parent.glob('*/report.json')]
        require(Counter(r.get('scenario') for r in reports) == Counter(expected_scenarios),
                'scenario report coverage differs')
        for report in reports:
            require(report.get('commit') == commit, 'report code commit differs')
            require(report.get('verdict') == 'PASS' and bool(report.get('steps')),
                    'scenario failed or has no steps')
            scenario = report.get('scenario')
            require(scenario in catalogue['scenarios'], 'scenario absent from catalogue')
            require([s.get('step') for s in report['steps']] == catalogue['scenarios'][scenario],
                    'declared step coverage differs')
            require(all(s.get('corpus_digest') == s.get('expected_digest') for s in report['steps']),
                    'corpus digest differs')
        scenarios.extend(expected_scenarios)
    require(sorted(indices) == list(range(shards)), 'duplicate or missing shard indices')
    require(bool(collected) and len(set(collected)) == len(collected),
            'empty or duplicate test collection')
    require(Counter(selected_all) == Counter(collected), 'test partition is incomplete')
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
