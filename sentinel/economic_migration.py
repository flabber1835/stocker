"""One explicitly qualified forward cash policy; never arbitrary model reuse."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from sentinel.core.cash_distributions import POLICY, LEGACY_POLICY
from sentinel.feed.rolling_contract import digest

PROFILE_SHA256 = '5d7bd8183d1cf479f144ac711c40704eb33dbe2d160e0b84dba5097af9036520'
PROFILE = Path(__file__).with_name('forward-cash-migration-v2.json')
LEGACY_PROFILE_SHA256 = 'c241c1c6ea7dc302c783469fbf4f0d7684ab25c52851d49f1c00544f898c2f01'


def legacy_profile():
    raw = PROFILE.with_name('forward-cash-migration.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != LEGACY_PROFILE_SHA256:
        raise ValueError('LEGACY_ECONOMIC_MIGRATION_PROFILE_CHANGED')
    return json.loads(raw)


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('ECONOMIC_MIGRATION_PROFILE_CHANGED')
    value = json.loads(raw)
    for name, expected in value['additions'].items():
        content = (PROFILE.parent / name).read_bytes()
        if name == 'economic_migration.py':
            content = re.sub(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$", b"PROFILE_SHA256 = '" + b'0'*64 + b"'", content, flags=re.M)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('ECONOMIC_MIGRATION_ADDITION_CHANGED:' + name)
    return value


def compatible(old, new):
    ignored = {'data_semantics_source_sha256', 'cash_distribution_policy'}
    return (new.get('cash_distribution_policy') == POLICY
            and old.get('cash_distribution_policy') in (None, LEGACY_POLICY, POLICY)
            and {k: v for k, v in old.items() if k not in ignored}
            == {k: v for k, v in new.items() if k not in ignored})


def transition(prior, target):
    if not compatible(prior.strategy_identity, target):
        raise ValueError('ECONOMIC_MIGRATION_STRATEGY_CHANGED')
    return {'schema': 'sentinel.forward-cash-policy-transition/2',
            'profile_sha256': PROFILE_SHA256, 'prior_state_sha256': prior.state_hash,
            'original_strategy_sha256': digest(prior.strategy_identity),
            'target_strategy_sha256': digest(target)}


def require_transition(prior, target, supplied):
    if not compatible(prior.strategy_identity, target) or supplied != transition(prior, target):
        raise ValueError('persisted strategy/config/source identity differs from running identity: migration required')


def source_allowed(name, previous, actual):
    item = profile()['files'].get(name)
    return item is not None and previous in item['before'] and actual == item['after']
