"""Original cash consideration, own source role and future-gzip preservation."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

import core_volatility_completion_facts as facts
from core_volatility_worker import archive_uncommitted_checkpoints
from core_volatility_recovery import financial_inventory
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    return {'sha256': facts.PARENT, 'source_cursor': '2018-11-30', 'completed': 232,
            'run': {'state': {'wealth_core': {'episodes': {}}, 'pending': [{
                'security_id': facts.SID, 'operation': 'OPEN_SLOT_POSITION', 'signal_session': '2018-11-30',
                'slot_id': 8, 'ticker': 'SODA'}]}}}


def test_original_literal_cash_and_unknown_provider_identity_stay_exact():
    raw = (Path(facts.__file__).parent/facts.CATALOG).read_bytes()
    term = facts.selected_term(raw)
    assert term['added']['cash_per_share'] == 144. and term['added']['session'] == '2018-12-06'
    facts.own_scope(parent(), 'VOL075')
    scope = json.loads((Path(facts.__file__).parent/facts.SCOPE).read_bytes())
    assert all(v['issuer_id'] == 'SEC_UNKNOWN:'+facts.SID and v['security_type_eligible'] == '0'
               for v in scope['witnesses'])


@pytest.mark.parametrize('field', ('outer', 'date', 'slot', 'ticker', 'owned'))
def test_foreign_or_changed_soda_own_predecessor_refuses(field):
    cp = parent()
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'date': cp['source_cursor'] = '2018-12-03'
    elif field == 'slot': cp['run']['state']['pending'][0]['slot_id'] = 7
    elif field == 'ticker': cp['run']['state']['pending'][0]['ticker'] = 'FOREIGN'
    else: cp['run']['state']['wealth_core']['episodes']['0'] = {'security_id': facts.SID}
    with pytest.raises(ValueError):
        facts.own_scope(cp, 'VOL075')


def test_unknown_changed_catalog_is_not_accepted():
    with pytest.raises(ValueError, match='EXACT_ORIGINAL_SODA_FACT_CATALOG'):
        facts.selected_term(b'{}')


def test_only_future_diagnostic_checkpoint_moves(tmp_path):
    book = tmp_path/'book'
    book.mkdir()
    for name in ('checkpoint.json.gz', 'daily.jsonl', 'formation.jsonl', 'watch.jsonl', 'monthly.jsonl', 'interrupted-daily-old.jsonl'):
        (book/name).write_bytes(b'ORIGINAL INERT FINANCIAL OR TAIL BYTES\n')
    (book/'pre-event').mkdir()
    common = {'source_cursor': '2018-11-30', 'completed': 232, 'base': {'source': 'same'}, 'sha256': 'PARENT'}
    old = dict(common, source_cursor='2018-10-31', completed=211)
    future = dict(common, source_cursor='2018-12-03', completed=233)
    (book/'pre-event/past.json.gz').write_bytes(gzip.compress(json.dumps(old).encode()))
    (book/'pre-event/future.json.gz').write_bytes(gzip.compress(json.dumps(future).encode()))
    lineage = tmp_path/'lineage'
    lineage.mkdir()
    before = financial_inventory(tmp_path)
    archive_uncommitted_checkpoints(book, common, lineage)
    assert financial_inventory(tmp_path) == before and (book/'pre-event/past.json.gz').exists()
    assert not (book/'pre-event/future.json.gz').exists()
    index = json.loads((lineage/'uncommitted-checkpoint-index.json').read_bytes())
    assert len(index['archived']) == 1 and index['financial_sessions_advanced'] == 0


@pytest.mark.parametrize('review', (False, True))
@pytest.mark.parametrize('mode', ('completion', 'recovery'))
def test_new_entrypoint_flags_are_checked_by_actual_inspector(monkeypatch, review, mode):
    constructor_canary(monkeypatch, 'VOL075', review, True, False,
                       completion_facts=mode == 'completion', recover_prefix=mode == 'recovery')


def test_soda_canonical_qualification_is_closed_locally(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        facts.prepare(parent(), Path('/out'), 'VOL075')
