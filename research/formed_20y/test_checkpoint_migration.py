from copy import deepcopy

import pytest

from .migrate_checkpoint import validate_certificates, validate_harness, validate_supplement_extension


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
