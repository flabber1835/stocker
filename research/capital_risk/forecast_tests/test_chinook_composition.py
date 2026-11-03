"""Pure admission/composition/source checks; no controller initialized."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import system_campaign_chinook_basis as basis
import system_campaign_chinook_sensor as sensor
import system_campaign_uncertainty_context as original
from system_campaign_chinook_input import SCHEMA


def test_private_symbol_binding_reuses_the_original_code_without_global_mutation():
    assert sensor.material.__code__ is original.return_material.__code__
    assert sensor.inherited_witness.__code__ is original.SensorCertificate.witness.__code__
    assert sensor.material.__globals__['SID'] == '47247117758471252'
    assert original.SID == '941065113449292610'
    sensor.check_inherited()


def test_first_creation_cannot_silently_become_a_post_event_parent():
    cp = dict(sha256='a' * 64, source_cursor='2023-07-31')
    proof = dict(checkpoint_sha256=cp['sha256'], through=cp['source_cursor'])
    admitted = sensor.admit_parent_extension(cp, json.dumps(proof).encode(), None, 'b' * 64)
    assert admitted['mode'] == 'FIRST_TYPED_INPUT' and admitted['original_joint_math_not_reset']
    cp['source_cursor'] = proof['through'] = '2023-08-11'
    with pytest.raises(ValueError, match='UNCONSUMED_CREATION_PARENT'):
        sensor.admit_parent_extension(cp, json.dumps(proof).encode(), None, 'b' * 64)


def test_retained_event_requires_exact_adapter_position_proof_and_resolution():
    cp = dict(sha256='a' * 64, source_cursor='2023-08-31')
    proof = dict(checkpoint_sha256=cp['sha256'], through=cp['source_cursor'],
        every_new_chinook_before_and_after_position_and_intent_checked=True,
        chinook_event_resolution={'file_sha256': 'c' * 64})
    result = sensor.admit_parent_extension(cp, json.dumps(proof).encode(), 'b' * 64, 'b' * 64)
    assert result['mode'] == 'RETAINED_TYPED_INPUT'
    for changed, source in [(dict(chinook_event_resolution=None), 'b' * 64),
            (dict(every_new_chinook_before_and_after_position_and_intent_checked=False), 'b' * 64),
            ({}, 'd' * 64)]:
        with pytest.raises(ValueError, match='ADMITTED_POST_EVENT_CONTINUATION'):
            sensor.admit_parent_extension(cp, json.dumps({**proof, **changed}).encode(), source, 'b' * 64)


def fixture(tmp_path, *, extra=None):
    values = [dict(schema=s) for s in sorted(basis.original_preflight.MODELS | {SCHEMA})]
    if extra is not None:
        values.append(dict(schema=extra))
    repairs = []
    for value in values:
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        h = basis.sha(raw)
        path = tmp_path / 'book/repairs' / (h + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        repairs.append(dict(filename=path.name, sha256=h))
    # Input-set metadata fixture: no financial state or checkpoint identity.
    value = dict(base={'metadata_fixture': True}, repairs=repairs)
    value['run'] = dict(input_sha256=basis.digest(value))
    return value


def test_all_five_descriptors_are_bound_without_projecting_the_input_set(tmp_path):
    value = fixture(tmp_path)
    before = deepcopy(value)
    found = basis.documents(tmp_path, value)
    assert len(found) == 5 and value == before
    value['run']['input_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='FULL_ACTUAL_INPUT_COMMITMENT'):
        basis.documents(tmp_path, value)


def test_unknown_schema_and_mutated_original_bytes_refuse(tmp_path):
    value = fixture(tmp_path, extra='undeclared-sixth-model/1')
    with pytest.raises(ValueError, match='NO_UNDECLARED_SCHEMA'):
        basis.documents(tmp_path, value)
    value = fixture(tmp_path)
    (tmp_path / 'book/repairs' / value['repairs'][0]['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='EVERY_ORIGINAL_DESCRIPTOR_BYTES'):
        basis.documents(tmp_path, value)


def test_inherited_source_guard_detects_a_changed_composition_dependency(monkeypatch):
    read = Path.read_bytes
    def changed(path):
        raw = read(path)
        return raw + b'\n# changed' if path.name == 'system_campaign_uncertainty_math.py' else raw
    monkeypatch.setattr(Path, 'read_bytes', changed)
    with pytest.raises(ValueError, match='COMPOSITION_SOURCES_UNCHANGED'):
        basis.require_inherited_sources()


def test_only_the_declared_model_may_change_the_common_basis():
    old = dict(schema='old', factual_semantics={'cash': []}, model_semantics=[{'old': True}])
    new_model = dict(schema=SCHEMA, consideration_range='40<=cash_plus_nontransferable_right<=44')
    after = deepcopy(old)
    after['schema'] = 'research.system-campaign-common-four-sensor-completion-basis/1'
    after['model_semantics'].append(new_model)
    assert basis.require_exact_delta(old, after, new_model)
    for changed in [dict(after, factual_semantics={'cash': [40]}),
                    dict(after, model_semantics=[{'old': False}, new_model])]:
        with pytest.raises(ValueError, match='ALL_PRIOR_SEMANTICS_UNCHANGED'):
            basis.require_exact_delta(old, changed, new_model)
