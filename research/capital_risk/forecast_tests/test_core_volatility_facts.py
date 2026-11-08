"""Own-predecessor factual compiler checks; no local financial imports."""
from copy import deepcopy
import importlib.abc
from pathlib import Path
import sys

import pytest

from core_volatility_facts import document, prepare


def terms():
    return [{'ticker': ticker, 'native_session': day, 'security_id': ticker, 'native_term_sha256': 'a'*64,
             'parent_outer_sha256': 'FOREIGN_ORIGINAL_BOOK', 'added': {'session': day, 'kind': 'CASH_MERGER'}}
            for ticker, day in (('ILG', '2018-09-04'), ('TGI', '2025-07-25'))]


def test_common_facts_bind_only_this_own_predecessor():
    values = terms()
    original = deepcopy(values)
    own = {'source_cursor': '2018-01-11', 'run': {'checkpoint_sha256': 'OWN_CANONICAL_PREDECESSOR'}}
    result = document(own, values, [])
    assert result['predecessor_checkpoint_sha256'] == 'OWN_CANONICAL_PREDECESSOR'
    assert result['add'] == [v['added'] for v in original]
    assert values == original and 'FOREIGN_ORIGINAL_BOOK' not in str(result)


@pytest.mark.parametrize('cursor', ('2018-09-04', '2025-07-25'))
def test_consumed_facts_cannot_be_rebound(cursor):
    with pytest.raises(ValueError, match='UNCONSUMED_OWN_FUTURE_FACTS'):
        document({'source_cursor': cursor, 'run': {'checkpoint_sha256': 'OWN'}}, terms(), [])


def test_unrelated_fact_cannot_enter_the_common_batch():
    values = terms()
    values[0]['ticker'] = 'UNRELATED'
    with pytest.raises(ValueError, match='ORIGINAL_TWO_P00_FUTURE_FACTS'):
        document({'source_cursor': '2018-01-11', 'run': {'checkpoint_sha256': 'OWN'}}, values, [])


def test_local_factual_qualification_is_closed_before_canonical_import(monkeypatch):
    class Fence(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_')):
                raise AssertionError(name)
    finder = Fence()
    sys.meta_path.insert(0, finder)
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    try:
        with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
            prepare({}, Path('/out'))
    finally:
        sys.meta_path.remove(finder)
