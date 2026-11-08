"""Original GBT cash and own-prefix guards, using inert DATA only."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import core_volatility_gbt_facts as facts
import core_volatility_gbt_job as job
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    return {'sha256': facts.PARENT, 'source_cursor': '2022-09-30', 'completed': 1196,
        'run': {'state': {'wealth_core': {'episodes': {'16': {'security_id': facts.SID, 'ticker': 'GBT',
            'current_shares': 75, 'initial_shares': 75, 'slot_id': 16, 'exit_pending': False,
            'entry_date': '2022-09-12', 'signal_date': '2022-09-09'}}}, 'pending': []}}}


def literal():
    return facts.selected_term((Path(facts.__file__).parent/facts.CATALOG).read_bytes())


def test_original_ordinary_cash_clock_and_source_witnesses():
    term = literal()
    assert term['added']['cash_per_share'] == 68.5
    assert term['native_session'] == term['last_trading_session'] == '2022-10-04'
    assert term['added']['session'] == '2022-10-05'
    assert term['recognition_rule'] == 'CONFIRMED_PREOPEN_COMPLETION'
    assert term['mandatory_common_share_completion_confirmed']
    raw = (Path(facts.__file__).parent/facts.SCOPE).read_bytes()
    assert len(facts.source_scope(raw, term)) == 3
    facts.own_scope(parent(), 'VOL075')


@pytest.mark.parametrize('field', ('outer', 'count', 'cursor', 'arm', 'shares', 'initial', 'entry', 'signal', 'slot', 'ticker', 'exit', 'pending', 'duplicate'))
def test_foreign_or_changed_gbt_parent_refuses(field):
    cp, arm = parent(), 'VOL075'
    ep = cp['run']['state']['wealth_core']['episodes']['16']
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'count': cp['completed'] = 1198
    elif field == 'cursor': cp['source_cursor'] = '2022-10-04'
    elif field == 'arm': arm = 'CONTROL'
    elif field == 'shares': ep['current_shares'] = 76
    elif field == 'initial': ep['initial_shares'] = 74
    elif field == 'entry': ep['entry_date'] = '2022-09-09'
    elif field == 'signal': ep['signal_date'] = '2022-09-08'
    elif field == 'slot': ep['slot_id'] = 15
    elif field == 'ticker': ep['ticker'] = 'FOREIGN'
    elif field == 'exit': ep['exit_pending'] = True
    elif field == 'duplicate': cp['run']['state']['wealth_core']['episodes']['15'] = deepcopy(ep)
    else: cp['run']['state']['pending'] = [{'security_id': facts.SID}]
    with pytest.raises(ValueError):
        facts.own_scope(cp, arm)


@pytest.mark.parametrize('field', ('duplicate', 'date', 'identity', 'eligibility', 'metadata'))
def test_changed_source_scope_refuses(field):
    scope = json.loads((Path(facts.__file__).parent/facts.SCOPE).read_bytes())
    if field == 'duplicate': scope['witnesses'].append(deepcopy(scope['witnesses'][0]))
    elif field == 'date': scope['witnesses'][0]['session'] = '2022-09-29'
    elif field == 'identity': scope['witnesses'][1]['issuer_id'] = 'FOREIGN'
    elif field == 'eligibility': scope['witnesses'][0]['security_type_eligible'] = '0'
    else: scope['provider_metadata_upgraded'] = True
    with pytest.raises(ValueError):
        facts.source_scope(json.dumps(scope).encode(), literal())


def test_changed_catalog_refuses():
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_GBT_CATALOG'):
        facts.selected_term(b'{}')


def test_exact_final_request_and_data_probe(tmp_path):
    request = job.expected_request()
    assert request['maximum'] == 960 and request['arms'] == {'VOL075': .75}
    assert request['parents']['VOL075']['completed'] == 1196
    assert request['cash_case'] == 'GBT' and request['generation'] == 10
    path = tmp_path/'request.json'
    path.write_text(json.dumps(request))
    assert job.probe(path)['canonical_runtime_executed'] is False


def test_changed_request_cannot_select_another_model(tmp_path):
    request = job.expected_request()
    request['cash_case'] = 'BEL'
    path = tmp_path/'wrong-request.json'
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match='EXACT_GBT_SOURCE_CLOSURE'):
        job.probe(path)


@pytest.mark.parametrize('review', (False, True))
def test_gbt_entrypoint_is_actually_inspected(monkeypatch, review):
    constructor_canary(monkeypatch, 'VOL075', review, True, False, cash_case='GBT')


def test_gbt_qualification_stays_hosted(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        facts.prepare(parent(), Path('/out'), 'VOL075')
