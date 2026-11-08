"""Closed literal cash cases and exact own-scope refusals on inert DATA."""
from pathlib import Path

import pytest

import core_volatility_cash_facts as facts
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    c = facts.CASES['BEL']
    return {'sha256': c['parent'], 'source_cursor': c['cursor'], 'completed': c['completed'],
        'run': {'state': {'wealth_core': {'episodes': {'19': {'security_id': c['sid'], 'ticker': 'BEL',
            'current_shares': 102, 'initial_shares': 102, 'slot_id': 19, 'exit_pending': False,
            'entry_date': '2018-12-26', 'signal_date': '2018-12-24'}}}, 'pending': []}}}


def test_literal_bel_cash_and_unknown_source_metadata_preserved():
    c = facts.CASES['BEL']
    term = facts.selected_term((Path(facts.__file__).parent/facts.CATALOG).read_bytes(), 'BEL')
    assert term['added']['cash_per_share'] == 25. and term['added']['session'] == '2019-04-17'
    assert c['issuer'] == 'SEC_UNKNOWN:'+c['sid'] and c['eligible'] == '0'
    facts.own_scope(parent(), 'VOL075', 'BEL')


@pytest.mark.parametrize('field', ('outer', 'count', 'arm', 'shares', 'entry', 'pending'))
def test_foreign_or_changed_bel_own_predecessor_refuses(field):
    cp, arm = parent(), 'VOL075'
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'count': cp['completed'] = 324
    elif field == 'arm': arm = 'CONTROL'
    elif field == 'shares': cp['run']['state']['wealth_core']['episodes']['19']['current_shares'] = 103
    elif field == 'entry': cp['run']['state']['wealth_core']['episodes']['19']['entry_date'] = '2018-12-24'
    else: cp['run']['state']['pending'] = [{'security_id': facts.CASES['BEL']['sid']}]
    with pytest.raises(ValueError):
        facts.own_scope(cp, arm, 'BEL')


def test_unknown_cash_catalog_refuses():
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_CLOSED_CASH_CATALOG'):
        facts.selected_term(b'{}', 'BEL')


@pytest.mark.parametrize('review', (False, True))
def test_cash_case_entrypoint_is_actually_inspected(monkeypatch, review):
    constructor_canary(monkeypatch, 'VOL075', review, True, False, cash_case='BEL')


def test_cash_qualification_stays_hosted(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        facts.prepare(parent(), Path('/out'), 'VOL075', 'BEL')
