import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from research.sharadar_replay import verify_evidence


def verify(root, **kwargs):
    return verify_evidence.verify(
        root,
        catalogue_path=root / 'catalogue.json',
        required_recovery_path=root / 'required_recovery_tests.json',
        **kwargs,
    )


def fixture(root):
    names = ['alpha', 'beta']
    (root / 'catalogue.json').write_text(json.dumps(dict(
        schema='sharadar-replay-catalogue/1',
        scenarios={n: ['bootstrap', 'recover'] for n in names}, required_tests=[])))
    scenario_ids = [f'research/sharadar_replay/tests/test_postgres.py::test_daily_production_replay[{n}]' for n in names]
    recovery_id = (
        'research/sharadar_replay/tests/test_recovery_authority.py::'
        'test_critical_recovery_contract'
    )
    ids = [*scenario_ids, recovery_id]
    (root / 'required_recovery_tests.json').write_text(json.dumps(dict(
        schema='sharadar-replay-required-recovery-tests/1',
        required_tests=[recovery_id],
    )))
    for i, name in enumerate(names):
        shard = root / str(i)
        shard.mkdir()
        selected = ids[i::2]
        (shard / 'collection.json').write_text(json.dumps(dict(
            shard=i, shards=2, collected=ids, selected=selected)))
        suite = ET.Element('testsuite')
        for item in selected:
            path, test_name = item.split('::')
            ET.SubElement(
                suite, 'testcase', classname=path[:-3].replace('/', '.'),
                name=test_name)
        ET.ElementTree(suite).write(shard / 'junit.xml')
        report = shard / name
        report.mkdir()
        (report / 'report.json').write_text(json.dumps(dict(scenario=name, commit='abc', verdict='PASS',
            steps=[dict(step=step, corpus_digest='same', expected_digest='same')
                   for step in ('bootstrap', 'recover')])))
    return root


def test_complete_evidence_passes(tmp_path):
    result = verify(fixture(tmp_path), commit='abc', shards=2)
    assert result == dict(verdict='PASS', commit='abc', tests=3, scenarios=2, shards=2)


@pytest.mark.parametrize('mutation', ['missing_manifest', 'duplicate_index', 'omit_test',
    'different_collection', 'failed_test', 'skipped_test', 'missing_report', 'failed_report',
    'wrong_digest', 'wrong_commit', 'missing_recovery_step'])
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
        elif mutation == 'missing_recovery_step': data['steps'].pop()
        else: data['commit'] = 'other'
        report.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        verify(tmp_path, commit='abc', shards=2)


def omit_beta_from_every_shard(root, *, unit_only=False):
    import shutil
    ids = (['research/sharadar_replay/tests/test_contract.py::test_a_unit'] if unit_only else
           ['research/sharadar_replay/tests/test_postgres.py::test_daily_production_replay[alpha]'])
    for i in range(2):
        folder = root / str(i)
        chosen = ids[i::2]
        (folder / 'collection.json').write_text(json.dumps(dict(
            shard=i, shards=2, collected=ids, selected=chosen)))
        suite = ET.Element('testsuite')
        for item in chosen:
            path, name = item.split('::')
            ET.SubElement(suite, 'testcase', classname=path[:-3].replace('/', '.'), name=name)
        ET.ElementTree(suite).write(folder / 'junit.xml')
    shutil.rmtree(root / '1/beta')
    if unit_only:
        shutil.rmtree(root / '0/alpha')


@pytest.mark.parametrize('unit_only', [False, True])
def test_coordinated_omission_and_zero_replays_are_rejected(tmp_path, unit_only):
    fixture(tmp_path)
    omit_beta_from_every_shard(tmp_path, unit_only=unit_only)
    with pytest.raises(AssertionError, match='declared scenario coverage'):
        verify(tmp_path, commit='abc', shards=2)


def test_catalogue_guard_falsifier_exposes_original_false_pass(tmp_path, monkeypatch):
    fixture(tmp_path)
    omit_beta_from_every_shard(tmp_path, unit_only=True)
    monkeypatch.setattr(verify_evidence, '_require_catalogue_coverage', lambda *a: None)
    result = verify(tmp_path, commit='abc', shards=2)
    with pytest.raises(AssertionError, match='replay evidence is empty'):
        assert result['scenarios'] > 0, 'replay evidence is empty'


def test_required_falsifier_cannot_disappear(tmp_path):
    fixture(tmp_path)
    path = tmp_path / 'catalogue.json'
    data = json.loads(path.read_text())
    data['required_tests'] = ['research/sharadar_replay/tests/test_postgres.py::test_required_falsifier']
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match='required falsifier'):
        verify(tmp_path, commit='abc', shards=2)


def test_coordinated_required_recovery_omission_is_rejected(tmp_path):
    fixture(tmp_path)
    authority = json.loads((tmp_path / 'required_recovery_tests.json').read_text())
    recovery_id = authority['required_tests'][0]
    for i in range(2):
        folder = tmp_path / str(i)
        manifest = folder / 'collection.json'
        data = json.loads(manifest.read_text())
        data['collected'] = [item for item in data['collected'] if item != recovery_id]
        data['selected'] = data['collected'][i::2]
        manifest.write_text(json.dumps(data))
        suite = ET.Element('testsuite')
        for item in data['selected']:
            path, name = item.split('::')
            ET.SubElement(suite, 'testcase', classname=path[:-3].replace('/', '.'), name=name)
        ET.ElementTree(suite).write(folder / 'junit.xml')
    with pytest.raises(AssertionError, match='required recovery-test coverage'):
        verify(tmp_path, commit='abc', shards=2)
