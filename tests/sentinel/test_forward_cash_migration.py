from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest
from sentinel import economic_migration as migration
from sentinel.feed.rolling_contract import digest


def strategies():
    old = {'strategy': 'frozen', 'controller_rule_sha256': 'a'*64,
           'wealth_core_source_sha256': 'b'*64, 'data_semantics_source_sha256': 'c'*64}
    new = {**old, 'data_semantics_source_sha256': 'd'*64,
           'cash_distribution_policy': migration.POLICY}
    return old, new


def test_forward_transition_requires_exact_prior_and_target_commitments():
    old, new = strategies()
    prior = SimpleNamespace(strategy_identity=old, state_hash='e'*64)
    proof = migration.transition(prior, new)
    migration.require_transition(prior, new, proof)
    for field in ('prior_state_sha256', 'original_strategy_sha256', 'target_strategy_sha256', 'profile_sha256'):
        with pytest.raises(ValueError, match='migration required'):
            migration.require_transition(prior, new, {**proof, field: 'f'*64})
    with pytest.raises(ValueError):
        migration.require_transition(prior, new, None)


def test_canonical_migration_check_performs_no_profile_io(monkeypatch):
    old, new = strategies()
    prior = SimpleNamespace(strategy_identity=old, state_hash='e'*64)
    proof = migration.transition(prior, new)
    monkeypatch.setattr(migration, 'profile', lambda: pytest.fail('kernel performed profile I/O'))
    migration.require_transition(prior, new, proof)


@pytest.mark.parametrize('field', ['strategy', 'controller_rule_sha256', 'wealth_core_source_sha256', 'economic_configuration'])
def test_controller_and_wealth_model_cannot_migrate_as_cash_policy(field):
    old, new = strategies()
    assert not migration.compatible(old, {**new, field: 'changed'})


def test_reviewed_source_profile_accepts_only_its_exact_bytes():
    from sentinel import execution_upgrade
    root = Path(migration.__file__).parent
    profile = migration.profile()
    for name, item in profile['files'].items():
        actual = hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual != item['after']:
            assert execution_upgrade.source_allowed(name, item['after'], actual), name
            assert not migration.source_allowed(name, item['before'][0], actual)
        assert migration.source_allowed(name, item['before'][0], item['after'])
        assert not migration.source_allowed(name, 'f'*64, actual)
        assert not migration.source_allowed(name, item['before'][0], 'f'*64)
    assert not migration.source_allowed('unknown.py', 'a'*64, 'b'*64)


def test_profile_itself_cannot_be_substituted(monkeypatch, tmp_path):
    path = tmp_path/'wrong.json'
    path.write_text('{}')
    monkeypatch.setattr(migration, 'PROFILE', path)
    with pytest.raises(ValueError, match='PROFILE_CHANGED'):
        migration.profile()


@pytest.mark.parametrize('name', ['core/cash_distributions.py', 'economic_migration.py'])
def test_new_policy_modules_cannot_use_an_unchanged_admission_profile(monkeypatch, tmp_path, name):
    original = migration.PROFILE.parent
    profile = tmp_path / migration.PROFILE.name
    profile.write_bytes(migration.PROFILE.read_bytes())
    for module in migration.profile()['additions']:
        target = tmp_path / module
        target.parent.mkdir(exist_ok=True)
        target.write_bytes((original / module).read_bytes())
    with (tmp_path / name).open('ab') as stream:
        stream.write(b'\n# unreviewed economic bytes\n')
    monkeypatch.setattr(migration, 'PROFILE', profile)
    with pytest.raises(ValueError, match='ADDITION_CHANGED'):
        migration.profile()
