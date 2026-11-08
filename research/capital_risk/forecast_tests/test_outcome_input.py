"""Proof-input metadata and packet identity only; no canonical execution."""
from copy import deepcopy
import gzip
import json
from types import SimpleNamespace

import pytest

import system_campaign_outcome_input as codec
from system_campaign_outcome_facts import boundary, common_semantics
from system_campaign_facts import digest


def fixture(tmp_path):
    run = dict(state={'metadata_fixture_only': True},
        state_sha256=digest({'metadata_fixture_only': True}),
        input_sha256=digest(dict(base={'metadata': True}, repairs=[])))
    run['checkpoint_sha256'] = digest(run)
    cp = dict(base={'metadata': True}, repairs=[], run=run, source_cursor='2023-07-31')
    cp['sha256'] = digest(cp)
    raw = gzip.compress(json.dumps(cp).encode(), mtime=0)
    bound = boundary(cp, raw, ['2023-07-31', '2023-08-01'])
    refs = [dict(reference='research:proof-fixture/'+str(i), sha256='a'*64,
                 description='Metadata-only source reference fixture.') for i in range(7)]
    value = dict(schema=codec.SCHEMA, predecessor_checkpoint_sha256=bound['inner_sha256'],
        parent_outer_sha256=bound['outer_sha256'], parent_file_sha256=bound['file_sha256'],
        parent_input_sha256=bound['input_sha256'], first_affected_session='2023-08-01',
        proof_mode=codec.MODE, max_leaves=64, max_nodes=127, max_depth=16,
        no_point_valuation=True, retained_uncertainty_models_unchanged=True, source_evidence=refs)
    path = tmp_path/'input.json'
    path.write_text(json.dumps(value), encoding='utf8')
    return path, value, refs, bound, cp, raw


def parse(path, refs, bound, **changes):
    args = dict(resume_session=bound['session'], predecessor_checkpoint_sha256=bound['inner_sha256'],
                expected_evidence=refs, boundary=bound)
    return codec.parse(path, **{**args, **changes})


def test_exact_hash_bound_metadata_and_identity_packet_operation(tmp_path):
    path, value, refs, bound, _, _ = fixture(tmp_path)
    adapter = codec.InputCodec(refs, bound)
    obj = adapter.load(path, resume_session=bound['session'],
                       predecessor_checkpoint_sha256=bound['inner_sha256'])
    packet = SimpleNamespace(day='2023-08-23', bars=('unaltered',), terminal=('incomplete',))
    assert adapter.apply(packet, obj) is packet and obj.earliest_affected_session == '2023-08-01'
    foreign = codec.OutcomeInput.model_validate(value)
    with pytest.raises(ValueError, match='ONLY_EXACT_ADMITTED_PROOF_INPUT'):
        adapter.apply(packet, foreign)


def test_consumed_or_foreign_inner_predecessor_refuses(tmp_path):
    path, _, refs, bound, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='UNCONSUMED_EXACT_PARENT_CURSOR'):
        parse(path, refs, bound, resume_session='2023-08-01')
    with pytest.raises(ValueError, match='ALL_PARENT_AND_NEXT_SESSION_BINDINGS'):
        parse(path, refs, bound, predecessor_checkpoint_sha256='b'*64)


@pytest.mark.parametrize('field', ['parent_outer_sha256', 'parent_file_sha256', 'parent_input_sha256'])
def test_every_original_boundary_commitment_is_required(tmp_path, field):
    path, value, refs, bound, _, _ = fixture(tmp_path)
    value[field] = 'b'*64
    path.write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ValueError, match='ALL_PARENT_AND_NEXT_SESSION_BINDINGS'):
        parse(path, refs, bound)


def test_original_parent_binding_guard_removal_falsifier(tmp_path, monkeypatch):
    path, _, refs, bound, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='ALL_PARENT_AND_NEXT_SESSION_BINDINGS'):
        parse(path, refs, bound, predecessor_checkpoint_sha256='b'*64)
    original = codec.require
    monkeypatch.setattr(codec, 'require', lambda value, label:
        None if label == 'OUTCOME_EXACT_ALL_PARENT_AND_NEXT_SESSION_BINDINGS' else original(value, label))
    assert parse(path, refs, bound, predecessor_checkpoint_sha256='b'*64).parent_outer_sha256 == bound['outer_sha256']


def test_refinement_cannot_smuggle_a_cash_price_or_change_scope(tmp_path):
    path, value, refs, bound, _, _ = fixture(tmp_path)
    value['cash_per_share'] = 40.0
    path.write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ValueError):
        parse(path, refs, bound)
    value.pop('cash_per_share')
    value['no_point_valuation'] = 1
    path.write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ValueError, match='EXACT_BOOLEAN_SCOPE'):
        parse(path, refs, bound)


def test_recompressed_or_mutated_parent_is_not_the_original_boundary(tmp_path):
    _, _, _, bound, cp, raw = fixture(tmp_path)
    changed = deepcopy(cp)
    changed['run']['state']['metadata_fixture_only'] = False
    with pytest.raises(ValueError, match='FULL_PARENT_FILE_OUTER_INNER_STATE_INPUT_METADATA'):
        boundary(changed, raw, ['2023-07-31', '2023-08-01'])
    other = gzip.compress(json.dumps(cp).encode(), mtime=1)
    assert boundary(cp, other, ['2023-07-31', '2023-08-01'])['file_sha256'] != bound['file_sha256']


def test_only_explicit_lineage_fields_are_removed_from_common_semantics(tmp_path):
    path, value, refs, bound, _, _ = fixture(tmp_path)
    obj = parse(path, refs, bound)
    semantic = common_semantics(obj)
    assert semantic == {k: v for k, v in value.items() if k not in codec.LINEAGE_FIELDS}
    assert semantic['max_leaves'] == 64 and semantic['source_evidence'] == refs
    assert semantic['proof_mode'] == codec.MODE and semantic['no_point_valuation'] is True
