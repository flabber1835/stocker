"""Existing research model, exact own source roles; no canonical execution."""
from copy import deepcopy
from pathlib import Path
import pytest

from core_volatility_aaap import PARENT, SID, own_position, prepare


def parent():
    return {'sha256': PARENT, 'source_cursor': '2018-01-31', 'completed': 21,
            'run': {'state': {'wealth_core': {'episodes': {'5': {'security_id': SID, 'ticker': 'AAAP1',
                'current_shares': 31, 'entry_date': '2017-12-12'}}}}}}


def test_uses_this_book_31_ads_without_original_variant_positions():
    cp = parent()
    before = deepcopy(cp)
    assert own_position(cp, 'VOL075')[0]['current_shares'] == 31 and cp == before


@pytest.mark.parametrize('case', ('arm', 'outer', 'date', 'count', 'sid', 'quantity', 'entry'))
def test_foreign_or_changed_aaap_predecessor_refuses(case):
    cp = parent()
    arm = 'VOL075'
    episode = cp['run']['state']['wealth_core']['episodes']['5']
    if case == 'arm': arm = 'CONTROL'
    elif case == 'outer': cp['sha256'] = '0'*64
    elif case == 'date': cp['source_cursor'] = '2018-02-01'
    elif case == 'count': cp['completed'] = 22
    elif case == 'sid': episode['security_id'] = 'FOREIGN'
    elif case == 'quantity': episode['current_shares'] = 25
    elif case == 'entry': episode['entry_date'] = '2017-12-13'
    with pytest.raises(ValueError):
        own_position(cp, arm)


def test_aaap_financial_qualification_is_hosted_only(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        prepare(parent(), Path('/out'), 'VOL075')
