import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from research.sharadar_replay.verify_evidence import verify


def fixture(root):
    names = ['alpha', 'beta']
    ids = [f'research/sharadar_replay/tests/test_postgres.py::test_daily_production_replay[{n}]' for n in names]
    for i, name in enumerate(names):
        shard = root / str(i)
        shard.mkdir()
        (shard / 'collection.json').write_text(json.dumps(dict(shard=i, shards=2, collected=ids, selected=[ids[i]])))
        suite = ET.Element('testsuite')
        ET.SubElement(suite, 'testcase', classname='research.sharadar_replay.tests.test_postgres',
                      name=f'test_daily_production_replay[{name}]')
        ET.ElementTree(suite).write(shard / 'junit.xml')
        report = shard / name
        report.mkdir()
        (report / 'report.json').write_text(json.dumps(dict(scenario=name, commit='abc', verdict='PASS',
            steps=[dict(corpus_digest='same', expected_digest='same')])))
    return root


def test_complete_evidence_passes(tmp_path):
    result = verify(fixture(tmp_path), commit='abc', shards=2)
    assert result == dict(verdict='PASS', commit='abc', tests=2, scenarios=2, shards=2)


@pytest.mark.parametrize('mutation', ['missing_manifest', 'duplicate_index', 'omit_test',
    'different_collection', 'failed_test', 'skipped_test', 'missing_report', 'failed_report',
    'wrong_digest', 'wrong_commit'])
def test_evidence_gate_rejects_incomplete_or_forged_passes(tmp_path, mutation):
    fixture(tmp_path)
    manifest = tmp_path / '1/collection.json'
    report = tmp_path / '1/beta/report.json'
    if mutation == 'missing_manifest':
        manifest.unlink()
    elif mutation in ('duplicate_index', 'omit_test', 'different_collection'):
        data = json.loads(manifest.read_text())
        if mutation == 'duplicate_index': data['shard'] = 0
        elif mutation == 'omit_test': data['selected'] = []
        else: data['collected'] = list(reversed(data['collected']))
        manifest.write_text(json.dumps(data))
    elif mutation in ('failed_test', 'skipped_test'):
        path = tmp_path / '1/junit.xml'
        tree = ET.parse(path)
        ET.SubElement(next(tree.getroot().iter('testcase')),
                      'failure' if mutation == 'failed_test' else 'skipped')
        tree.write(path)
    elif mutation == 'missing_report':
        report.unlink()
    else:
        data = json.loads(report.read_text())
        if mutation == 'failed_report': data['verdict'] = 'FAIL'
        elif mutation == 'wrong_digest': data['steps'][0]['corpus_digest'] = 'wrong'
        else: data['commit'] = 'other'
        report.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        verify(tmp_path, commit='abc', shards=2)
