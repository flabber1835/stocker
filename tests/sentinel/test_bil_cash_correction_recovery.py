"""The authenticated defensive cash addition routes knowledge, never payment."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel.execution import cash_corrections as cc, feed_cash, feed_inputs
from sentinel.execution.reconcile import CorpusActionLookup
from sentinel.feed import action_history
from sentinel.feed.rolling_contract import digest

DAY = '2026-11-02'
SID = 'SENTINEL:BIL'
FIXTURE = Path(__file__).with_name('fixtures') / 'bil_cash_addition_20261102.json'


@pytest.fixture
def witness():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '738c7ea4beaeb10fbce3a2ae53d034aaf05dccb58d2e3a622bd8f7ffcdbce228'
    return json.loads(raw)


def classify(w):
    parents = w['parents']
    return cc.classify(w['marker'], w['old_day'], w['new_correction_day'],
        publication_version=15, coverage_sha256=parents['15']['coverage_sha256'],
        original_coverage_sha256=parents['12']['coverage_sha256'],
        correction_coverage_sha256=parents['15']['coverage_sha256'],
        publication_receipt_sha256=parents['15']['receipt_sha256'],
        original_receipt_sha256=parents['12']['receipt_sha256'],
        correction_receipt_sha256=parents['15']['receipt_sha256'])


def test_actual_defensive_addition_preserves_marks_and_archives(witness):
    before = deepcopy(witness)
    addition = classify(witness)
    assert addition is not None
    assert addition.proof.security_id == SID and addition.proof.ticker == 'BIL'
    assert addition.proof.per_share == Decimal('0.308493')
    assert addition.proof.original_record_sha256 == witness['old_day_sha256']
    assert not addition.proof.broker_payment_claimed and not addition.proof.economic_equivalence_claimed
    assert addition.bar is addition.predecessor is addition.identity is None
    projected = cc.CashCorrectionView((addition,)).material(DAY, witness['old_day'])
    assert len(projected['sources']) == len(witness['old_day']['sources']) + 1
    for key in ('bars', 'predecessors', 'identity_rows', 'defensive', 'scalar', 'unsupported', 'unresolved'):
        assert projected[key] == witness['old_day'][key]
    assert witness == before


@pytest.mark.parametrize('case', ['changed_mark', 'missing_pair', 'wrong_predecessor',
    'nonpositive_mark', 'bool_mark', 'wrong_identity', 'wrong_symbol', 'old_cash',
    'new_split', 'new_identity', 'duplicate_cash', 'wrong_source', 'invalid_source_id',
    'cash_removal', 'negative_cash', 'unknown_source_field', 'unknown_material_field'])
def test_unproved_defensive_changes_remain_restricted(witness, case):
    old, observed = witness['old_day'], witness['new_correction_day']['observed']
    source = next(row for row in observed['sources'] if row['ticker'] == 'BIL')
    if case == 'changed_mark': observed['defensive'][-1][1] += 1
    elif case == 'missing_pair': observed['defensive'].pop(0)
    elif case == 'wrong_predecessor': observed['defensive'][0][0] = DAY
    elif case == 'nonpositive_mark': observed['defensive'][-1][2] = 0
    elif case == 'bool_mark': observed['defensive'][-1][2] = True
    elif case == 'wrong_identity': witness['marker']['security_id'] = 'OTHER'
    elif case == 'wrong_symbol': witness['marker']['ticker'] = 'OTHER'
    elif case == 'old_cash': old['sources'].append(deepcopy(source))
    elif case == 'new_split': observed['scalar'].append({'security_id': SID, 'ticker': 'BIL', 'action': 'split'})
    elif case == 'new_identity': observed['identity_rows'].append({'permaticker': SID, 'ticker': 'BIL'})
    elif case == 'duplicate_cash': observed['sources'].append(deepcopy(source))
    elif case == 'wrong_source': source['ticker'] = 'OTHER'
    elif case == 'invalid_source_id': source['source_row_id'] = 'x' * 64
    elif case == 'cash_removal': observed['sources'].remove(source)
    elif case == 'negative_cash': source['value'] = '-0.3'
    elif case == 'unknown_source_field': source['share_ratio'] = '2'
    else: observed['unexpected'] = []
    witness['new_correction_day']['sources'] = deepcopy(observed['sources'])
    witness['marker']['source_row_id'] = digest(observed['sources'])
    assert classify(witness) is None


def test_only_exact_defensive_marker_is_removed(witness):
    addition = classify(witness)
    marker = action_history._event(witness['marker'])
    other = action_history._event(dict(witness['marker'], source_row_id='a' * 64))
    actions = CorpusActionLookup(start=date(2026, 10, 30), events={}, unresolved_events=(marker, other))
    wrapped = cc.ClassifiedActions(actions, cc.CashCorrectionView((addition,)))
    assert wrapped.unresolved_events == (other,)
    assert wrapped.material_events_for(security_ids=(SID,)) == (other,)
    assert wrapped(SID) == actions(SID)


@pytest.mark.parametrize('shares', ['0', '246'])
def test_cash_view_uses_dated_defensive_ownership_without_crediting_account(monkeypatch, witness, shares):
    from types import SimpleNamespace
    from sentinel.trial import _expected_defensive_dividends

    addition = classify(witness)
    view = cc.CashCorrectionView((addition,))
    source = object.__new__(feed_cash.SnapshotCashInputs)
    source.conn = None
    source.pub = SimpleNamespace(version=15, window_end='2026-11-05')
    source._retained_cache = {}
    monkeypatch.setattr(action_history, 'coverage', lambda *args, **kwargs: {})
    monkeypatch.setattr(action_history, 'records', lambda *args, **kwargs: {DAY: witness['old_day']})
    monkeypatch.setattr(cc, 'load', lambda *args, **kwargs: view)
    assert DAY in source.days(date(2026, 10, 30), date(2026, 11, 5))
    result = _expected_defensive_dividends(None, date.fromisoformat(DAY), {SID: Decimal(shares)}, [], source=source)
    assert result == _expected_defensive_dividends(None, date.fromisoformat(DAY), {SID: Decimal(shares)}, [], source=source)
    if shares == '0': assert result == []
    else:
        assert result[0]['amount'] == '75.889278'
        assert result[0]['source_row_ids'] == [addition.source['source_row_id']]
    assert not addition.proof.broker_payment_claimed


def test_removed_defensive_mark_guard_is_detected(monkeypatch, witness):
    body = inspect.getsource(cc._defensive_mark)
    guard = "_require(digest(original['defensive']) == digest(pair))"
    assert body.count(guard) == 1
    namespace = {}
    exec(compile(body.replace(guard, 'pass'), '<defensive-cash-mark-falsifier>', 'exec'), vars(cc), namespace)
    monkeypatch.setattr(cc, '_defensive_mark', namespace['_defensive_mark'])
    with pytest.raises(AssertionError):
        test_unproved_defensive_changes_remain_restricted(witness, 'changed_mark')
