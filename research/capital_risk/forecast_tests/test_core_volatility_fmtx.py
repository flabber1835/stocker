"""FMTX source selection and future-own-prefix guards on inert DATA only."""
from pathlib import Path
import json

import pytest

import core_volatility_fmtx_facts as facts
import core_volatility_fmtx_job as job
from core_volatility_source import sha
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    return dict(sha256=facts.PARENT, completed=1196, source_cursor='2022-09-30',
                run={'state': {'wealth_core': {'episodes': {}}, 'pending': []}})


def test_prepared_mandatory_cash_source_is_not_mislabelled_previous_adoption():
    h = Path(facts.__file__).parent
    term = facts.selected_term((h/facts.CATALOG).read_bytes())
    assert term['added']['session'] == '2022-10-14' and term['added']['cash_per_share'] == 20.
    assert term['mandatory_common_share_completion_confirmed'] and term['preopen_completion_confirmed']
    assert term['timing_evidence']['input_adopted'] is False
    assert sha((h/'system_campaign_cash_calendar.py').read_bytes()) == facts.LOADER_SHA
    facts.own_scope(parent(), 'VOL075')


@pytest.mark.parametrize('field', ('outer', 'count', 'cursor', 'arm', 'held', 'pending'))
def test_foreign_or_nonfuture_own_scope_refuses(field):
    cp, arm = parent(), 'VOL075'
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'count': cp['completed'] = 1205
    elif field == 'cursor': cp['source_cursor'] = '2022-10-13'
    elif field == 'arm': arm = 'CONTROL'
    elif field == 'held': cp['run']['state']['wealth_core']['episodes']['0'] = {'security_id': facts.SID}
    else: cp['run']['state']['pending'] = [{'security_id': facts.SID}]
    with pytest.raises(ValueError):
        facts.own_scope(cp, arm)


def test_changed_catalog_refuses():
    with pytest.raises(ValueError, match='EXACT_SOURCE_BOUND_OCTOBER_CATALOG'):
        facts.selected_term(b'{}')


def test_new_fmtx_request_resumes_only_its_admitted_gbt_input_prefix(tmp_path):
    value = job.expected_request()
    assert value['generation'] == 12 and value['maximum'] == 960
    assert value['parents']['VOL075']['checkpoint_sha256'] == facts.PARENT
    assert value['cash_case'] == 'FMTX' and value['arms'] == {'VOL075': .75}
    path = tmp_path/'request.json'
    path.write_bytes(json.dumps(value).encode())
    assert job.probe(path)['canonical_runtime_executed'] is False


@pytest.mark.parametrize('review', (False, True))
def test_fmtx_worker_and_reviewer_entrypoints_are_inspected(monkeypatch, review):
    constructor_canary(monkeypatch, 'VOL075', review, True, False, cash_case='FMTX')


def test_actual_fmtx_qualification_is_hosted_only(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        facts.prepare(parent(), Path('/out'), 'VOL075')
