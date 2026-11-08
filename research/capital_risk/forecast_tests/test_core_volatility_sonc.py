"""Literal SONC facts, own-position refusals and actual entrypoint inspection."""
from pathlib import Path

import pytest

import core_volatility_sonc_facts as facts
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    return {'sha256': facts.PARENT, 'source_cursor': '2018-11-30', 'completed': 232,
            'run': {'state': {'wealth_core': {'episodes': {'1': {
                'security_id': facts.SID, 'current_shares': 63, 'initial_shares': 63,
                'entry_date': '2018-11-27', 'signal_date': '2018-11-26', 'slot_id': 1,
                'ticker': 'SONC', 'exit_pending': False}}}, 'pending': []}}}


def test_original_literal_sonc_cash_terms_and_own_position():
    term = facts.selected_term((Path(facts.__file__).parent/facts.CATALOG).read_bytes())
    assert term['added']['cash_per_share'] == 43.5 and term['added']['session'] == '2018-12-07'
    facts.own_scope(parent(), 'VOL075')


@pytest.mark.parametrize('field', ('outer', 'count', 'arm', 'shares', 'entry', 'pending'))
def test_foreign_or_changed_sonc_own_predecessor_refuses(field):
    cp = parent()
    arm = 'VOL075'
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'count': cp['completed'] = 236
    elif field == 'arm': arm = 'CONTROL'
    elif field == 'shares': cp['run']['state']['wealth_core']['episodes']['1']['current_shares'] = 64
    elif field == 'entry': cp['run']['state']['wealth_core']['episodes']['1']['entry_date'] = '2018-11-26'
    else: cp['run']['state']['pending'] = [{'security_id': facts.SID}]
    with pytest.raises(ValueError):
        facts.own_scope(cp, arm)


def test_unknown_sonc_catalog_refuses():
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_SONC_FACT_CATALOG'):
        facts.selected_term(b'{}')


@pytest.mark.parametrize('review', (False, True))
def test_sonc_entrypoint_is_checked_by_actual_inspector(monkeypatch, review):
    constructor_canary(monkeypatch, 'VOL075', review, True, False, sonc_facts=True)


def test_sonc_canonical_qualification_stays_hosted(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        facts.prepare(parent(), Path('/out'), 'VOL075')
