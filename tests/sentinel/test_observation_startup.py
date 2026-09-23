"""Formation authority cannot be obtained with truncated or relabelled evidence."""
from copy import deepcopy
import pytest

from sentinel import observation_startup as startup
from sentinel.authority import AuthorityRefused
from sentinel.controller import owned_impairment
from sentinel.feed.calendar import previous_sessions


@pytest.mark.parametrize('change', [
    {'measured_sessions': 378}, {'warmup_sessions': 251},
    {'decision_session': 'not-a-date'}, {'decision_session': '2026-08-01'},
    {'first_session': '2026-07-31'},
    {'formation': {'policy': 'HISTORICAL_PIT_V1'}},
    {'formation': {'sessions': 125}}, {'formation': {'end': '2026-07-31'}},
    {'formation': {'chain_sha256': ''}}, {'formation': {'state_sha256': ''}},
    {'formation': {'source_sha256': ''}},
])
def test_truncated_or_relabelled_formation_cannot_authorize_owned55(change):
    days = previous_sessions('2026-07-31', 379)
    proof = dict(schema=startup.FORMED_SCHEMA, measured_sessions=379, warmup_sessions=252,
        decision_session='2026-07-31', first_session=days[0], formation=dict(
            schema='sentinel.formation-parity/1', policy='CURRENT_INFORMATION_INITIALIZATION_V1',
            sessions=126, end=days[-2], chain_sha256='a'*64, state_sha256='b'*64, source_sha256='c'*64))
    binding = dict(strategy_sha256='d'*64, controller_sha256=owned_impairment.load().digest)
    startup.require(proof, **binding)
    broken = deepcopy(proof)
    if 'formation' in change:
        broken['formation'].update(change['formation'])
    else:
        broken.update(change)
    with pytest.raises(AuthorityRefused):
        startup.require(broken, **binding)
