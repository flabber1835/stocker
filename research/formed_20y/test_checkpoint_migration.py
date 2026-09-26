from copy import deepcopy
from types import SimpleNamespace

import pytest

from .migrate_checkpoint import (
    rebind_multi_child_identity, validate_certificates, validate_harness,
    validate_pre_cursor_single_child,
    validate_supplement_extension,
)


def record(name='OLD', day='2010-01-04', cash='1'):
    return dict(id=name, effective_session=day, security_id=name, cash_per_share=cash)


def test_only_future_effective_supplement_additions_are_accepted():
    old = [record()]
    addition = record('NEW', '2014-12-05', '129')
    assert validate_supplement_extension(old, old+[addition], '2014-12-04') == [addition]


@pytest.mark.parametrize('mutation', ['changed', 'deleted', 'same_day', 'duplicate', 'none'])
def test_invalid_supplement_migrations_refuse(mutation):
    old = [record()]
    new = deepcopy(old)
    if mutation == 'changed':
        new[0]['cash_per_share'] = '2'
    elif mutation == 'deleted':
        new = []
    elif mutation == 'same_day':
        new.append(record('NEW', '2014-12-04'))
    elif mutation == 'duplicate':
        new.append(deepcopy(old[0]))
    with pytest.raises(ValueError):
        validate_supplement_extension(old, new, '2014-12-04')


def test_only_named_non_economic_harness_changes_are_accepted():
    old = {'run.py':'a', 'prepare_supplements.py':'a'}
    new = {'run.py':'a', 'prepare_supplements.py':'b', 'migrate_checkpoint.py':'c'}
    result = validate_harness(old, new)
    assert result == dict(removed=[], changed=['prepare_supplements.py'],
                          added=['migrate_checkpoint.py'])
    with pytest.raises(ValueError, match='economic harness changed'):
        validate_harness(old, {**new, 'run.py':'changed'})
    with pytest.raises(ValueError, match='economic harness changed'):
        validate_harness(old, {'prepare_supplements.py':'b'})


def test_production_or_proof_commitment_change_refuses():
    old = dict(runtime_files={'economic.py':'a'}, proof_programs={'proof.py':'b'},
               evidence_files={'old':'c'}, reviewed_revision='main')
    new = deepcopy(old)
    new['evidence_files'] = {'new':'d'}
    validate_certificates(old, new)
    new['runtime_files']['economic.py'] = 'changed'
    with pytest.raises(ValueError, match='production or proof-program'):
        validate_certificates(old, new)


def test_scoped_multi_child_compatibility_accepts_only_spinoff_kernel_change():
    old = dict(runtime_files={'sentinel/core/spinoffs.py':'a', 'economic.py':'same'},
               proof_programs={'proof.py':'same'}, evidence_files={'old':'x'},
               reviewed_revision='old')
    new = deepcopy(old)
    new['runtime_files']['sentinel/core/spinoffs.py'] = 'b'
    new['reviewed_revision'] = 'new'
    validate_certificates(old, new, multi_child_compatibility=True)
    new['runtime_files']['economic.py'] = 'changed'
    with pytest.raises(ValueError, match='unscoped production'):
        validate_certificates(old, new, multi_child_compatibility=True)


def test_multi_child_compatibility_requires_all_prior_reviewed_events_single_child():
    one = dict(id='one', kind='SPINOFF', effective_session='2014-01-02',
               security_id='P', child_security_id='A')
    assert validate_pre_cursor_single_child([one], '2016-07-22') == 1
    with pytest.raises(ValueError, match='pre-checkpoint reviewed multi-child'):
        validate_pre_cursor_single_child([one, {**one, 'id':'two',
                                                'child_security_id':'B'}],
                                         '2016-07-22')


def test_scoped_harness_mode_still_rejects_unrelated_economic_change():
    old = {'run.py':'a', 'spinoff_inputs.py':'a', 'unrelated.py':'a'}
    accepted = {'run.py':'b', 'spinoff_inputs.py':'b', 'unrelated.py':'a'}
    validate_harness(old, accepted, multi_child_compatibility=True)
    with pytest.raises(ValueError, match='economic harness changed'):
        validate_harness(old, {**accepted, 'unrelated.py':'b'},
                         multi_child_compatibility=True)


def test_multi_child_identity_rebind_changes_only_data_semantics():
    from sentinel.strategy import production_strategy
    current = production_strategy()[1]
    prior = {**current, 'data_semantics_source_sha256':'old'}
    state = SimpleNamespace(strategy_identity=prior)
    result = rebind_multi_child_identity(state)
    assert result['changed'] == ['data_semantics_source_sha256']
    assert state.strategy_identity == current
    with pytest.raises(ValueError, match='unscoped strategy identity'):
        rebind_multi_child_identity(SimpleNamespace(strategy_identity={
            **prior, 'wealth_core_config_sha256':'wrong'}))
