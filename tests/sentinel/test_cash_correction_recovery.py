"""Exact late DELL cash knowledge never becomes a structural or cash waiver."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.execution import cash_corrections as cc, feed_cash, feed_inputs
from sentinel.execution.reconcile import CorpusActionLookup
from sentinel.feed import action_history, publication
from sentinel.feed.rolling_contract import digest

SID = '91ee1b57-f36c-40cf-a8b7-84583daaafc9'
DAY = '2026-10-20'
START, END = date(2026, 10, 17), date(2026, 10, 30)
FIXTURE = Path(__file__).with_name('fixtures') / 'dell_cash_addition_20261020.json'


@pytest.fixture
def witness():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'b083e214a89bf278212e9dcfee40d7b5ab375d16354bc245c95d991fd445cf1c'
    return json.loads(raw)


def classify(w):
    parents = w['parents']
    return cc.classify(w['marker'], w['old_day'], w['new_correction_day'],
        publication_version=11, coverage_sha256=parents['11']['coverage_sha256'],
        original_coverage_sha256=parents['3']['coverage_sha256'],
        correction_coverage_sha256=parents['11']['coverage_sha256'],
        publication_receipt_sha256=parents['11']['receipt_sha256'],
        original_receipt_sha256=parents['3']['receipt_sha256'],
        correction_receipt_sha256=parents['11']['receipt_sha256'])


def rebind_sources(w):
    current = w['new_correction_day']
    current['sources'] = deepcopy(current['observed']['sources'])
    w['marker']['source_row_id'] = digest(current['sources'])


def test_actual_authenticated_incident_routes_new_cash_without_payment_claim(witness):
    before = deepcopy(witness)
    addition = classify(witness)
    assert addition is not None
    assert addition.proof.classification == 'CASH_ONLY_ADDITION'
    assert addition.proof.security_id == SID
    assert addition.proof.per_share == Decimal('0.63')
    assert addition.proof.broker_payment_claimed is False
    assert addition.proof.economic_equivalence_claimed is False
    assert addition.proof.original_record_sha256 == witness['old_day_sha256']
    assert witness == before


@pytest.mark.parametrize('case', [
    'old_cash', 'old_identity', 'old_bar', 'new_split', 'new_unsupported',
    'new_identity_event', 'duplicate_identity', 'wrong_identity', 'identity_range', 'bad_split',
    'cash_bar_mismatch', 'cash_source_mismatch', 'negative', 'nonfinite',
    'unknown_action', 'unknown_source_field', 'bad_source_id', 'missing_preimage',
    'unknown_old_field', 'ambiguous_policy', 'wrong_snapshot_shape', 'wrong_predecessor',
])
def test_mixed_changed_or_unproved_corrections_remain_restricted(witness, case):
    old = witness['old_day']
    new = witness['new_correction_day']['observed']
    source = next(item for item in new['sources'] if item['ticker'] == 'DELL')
    bar = next(row for row in new['bars'] if row[0] == SID)
    identity = next(row for row in new['identity_rows'] if row['permaticker'] == SID)
    event = {'security_id': SID, 'ticker': 'DELL', 'action': 'split'}
    if case == 'old_cash': old['sources'].append(deepcopy(source))
    elif case == 'old_identity': old['identity_rows'].append(deepcopy(identity))
    elif case == 'old_bar': old['bars'].append(deepcopy(bar))
    elif case == 'new_split': new['scalar'].append(event)
    elif case == 'new_unsupported': new['unsupported'].append(event)
    elif case == 'new_identity_event': new['identity_actions'].append(event)
    elif case == 'duplicate_identity': new['identity_rows'].append(deepcopy(identity))
    elif case == 'wrong_identity': identity['permaticker'] = 'OTHER'
    elif case == 'identity_range': identity['firstpricedate'] = '2026-10-21'
    elif case == 'bad_split': bar[5] = 2.0
    elif case == 'cash_bar_mismatch': bar[4] = 0.64
    elif case == 'cash_source_mismatch': source['value'] = '0.64'
    elif case == 'negative': source['value'] = '-0.63'
    elif case == 'nonfinite': source['value'] = 'NaN'
    elif case == 'unknown_action': source['action'] = 'spinoffdividend'
    elif case == 'unknown_source_field': source['child_ratio'] = '1'
    elif case == 'bad_source_id': source['source_row_id'] = 'x' * 64
    elif case == 'missing_preimage': witness['old_day'] = None
    elif case == 'unknown_old_field': old['unknown_structural_terms'] = []
    elif case == 'ambiguous_policy': new['identity_policy'] = [{'ticker': 'DELL'}]
    elif case == 'wrong_snapshot_shape': new['unknown'] = []
    elif case == 'wrong_predecessor':
        next(row for row in new['predecessors'] if row[0] == SID)[1] = DAY
    rebind_sources(witness)
    assert classify(witness) is None


def test_classified_view_keeps_scalars_other_securities_and_original_bytes(witness):
    addition = classify(witness)
    marker = action_history._event(witness['marker'])
    other = action_history._event(dict(witness['marker'], security_id='OTHER', ticker='OTHER'))
    actions = CorpusActionLookup(start=START, events={SID: ((date(2026, 10, 25), Decimal(2)),)},
        unresolved_events=(marker, other))
    view = cc.CashCorrectionView((addition,))
    wrapped = cc.ClassifiedActions(actions, view)
    assert wrapped(SID) == actions(SID) == Decimal(2)
    assert wrapped.unresolved_events == (other,)
    assert wrapped.material_events_for(security_ids=(SID, 'OTHER')) == (other,)
    assert wrapped.scalar_evidence_for((SID,)) == actions.scalar_evidence_for((SID,))
    old = deepcopy(witness['old_day'])
    projected = view.material(DAY, old)
    assert projected == view.material(DAY, old)
    assert old == witness['old_day']
    assert len([s for s in projected['sources'] if s['ticker'] == 'DELL']) == 1
    assert projected['defensive'] == old['defensive']


class Rows:
    def __init__(self, values): self.values = values
    def fetchall(self): return self.values
    def fetchone(self): return self.values[0] if self.values else None


def bound_reader(monkeypatch, w, change=None):
    old = {'basis': '2025-08-12', 'through': DAY, 'added': {DAY: digest(w['old_day'])},
           'corrections': [], 'correction_evidence': {}}
    current = {'basis': '2025-08-12', 'through': '2026-10-30', 'added': {},
               'corrections': [w['marker']], 'correction_evidence': {DAY: w['new_correction_day']}}
    if change: change(old, current)
    parents = {3: old, 11: current}
    pub = SimpleNamespace(version=11, evidence={'action_history': digest(current)})
    calls = []
    class Connection:
        def __init__(self): self.parents = parents
        def execute(self, query, args=()):
            if query.startswith('SELECT required_after_version'):
                return Rows([(0,)])
            assert 'WHERE c.publication_version=%s' in query
            value = self.parents[args[0]]
            return Rows([(value, digest(value), {'action_history': digest(value),
                'publication_validation': {'receipt_sha256': 'a' * 64}}, 'a' * 64)])
    monkeypatch.setattr(feed_inputs, 'is_rolling', lambda value: True)
    monkeypatch.setattr(feed_inputs, 'require_current', lambda conn: pub)
    monkeypatch.setattr(publication, '_verify_receipt_chain',
        lambda conn, through_version: calls.append(through_version))
    return Connection(), pub, current, calls


def test_live_reader_checks_parent_links_and_native_authentication(monkeypatch, witness):
    conn, pub, covered, calls = bound_reader(monkeypatch, witness)
    view = cc.load(conn, pub, start=START, end=END, covered=covered,
                   records={DAY: witness['old_day']})
    assert len(view.additions) == 1
    assert calls == [11]


@pytest.mark.parametrize('change', ['old_link', 'origin_marker', 'origin_evidence', 'native_auth'])
def test_authenticated_parent_changes_refuse(monkeypatch, witness, change):
    conn, pub, covered, _ = bound_reader(monkeypatch, witness,
        (lambda old, current: old['added'].update({DAY: 'b' * 64}))
        if change == 'old_link' else None)
    if change == 'native_auth':
        def refuse(*args, **kwargs): raise ValueError('publication HMAC refused')
        monkeypatch.setattr(publication, '_verify_receipt_chain', refuse)
    if change in {'origin_marker', 'origin_evidence'}:
        # Current-held data and its originating publication must be identical.
        covered['corrections'][0]['publication_version'] = 10
        conn.parents[10] = deepcopy(covered)
        if change == 'origin_marker': conn.parents[10]['corrections'] = []
        else: conn.parents[10]['correction_evidence'] = {}
        pub.evidence['action_history'] = digest(covered)
    with pytest.raises((ValueError, KeyError)):
        cc.load(conn, pub, start=START, end=END, covered=covered,
                records={DAY: witness['old_day']})


def cash_source(monkeypatch, witness):
    from sentinel.feed.universe import IdentityResolver, listings_from_rows
    addition = classify(witness)
    identities = [addition.identity]
    refs = SimpleNamespace(tickers=identities, projection=SimpleNamespace(alias_rows=[]),
        resolver=IdentityResolver(listings_from_rows(identities)))
    monkeypatch.setattr(feed_inputs, 'references', lambda conn, pub: refs)
    monkeypatch.setattr(action_history, 'coverage', lambda *args, **kwargs: {'test': True})
    monkeypatch.setattr(action_history, 'records', lambda *args, **kwargs: {DAY: witness['old_day']})
    monkeypatch.setattr(cc, 'load', lambda *args, **kwargs: cc.CashCorrectionView((addition,)))
    pub = SimpleNamespace(window_end='2026-10-30', version=11,
                          to_dict=lambda: {'version': 11})
    return feed_cash.SnapshotCashInputs(None, pub), addition


@pytest.mark.parametrize('ex_date_shares', ['0', '2'])
def test_cash_view_reaches_entitlement_without_adding_broker_cash(
        monkeypatch, witness, ex_date_shares):
    from sentinel.trial import _expected_effective_equity_dividends
    source, addition = cash_source(monkeypatch, witness)
    assert DAY in source.days(START, END)
    first = _expected_effective_equity_dividends(None, date.fromisoformat(DAY),
        {SID: Decimal(ex_date_shares)}, [], source=source)
    second = _expected_effective_equity_dividends(None, date.fromisoformat(DAY),
        {SID: Decimal(ex_date_shares)}, [], source=source)
    assert first == second
    if Decimal(ex_date_shares):
        assert first[0]['amount'] == '1.26'
        assert first[0]['source_row_ids'] == [addition.source['source_row_id']]
    else:
        assert first == []
    assert addition.proof.broker_payment_claimed is False


@pytest.mark.parametrize('owned_before_ex_date', [False, True])
def test_late_cash_uses_dated_ownership_even_after_position_is_sold(
        monkeypatch, witness, owned_before_ex_date):
    from datetime import datetime, timezone
    from sentinel import paper_performance, trial
    from sentinel.execution import feed_actions, fill_integrity
    source, addition = cash_source(monkeypatch, witness)
    monkeypatch.setattr(feed_inputs, 'require_current', lambda conn: source.pub)
    monkeypatch.setattr(feed_inputs, 'is_rolling', lambda pub: True)
    monkeypatch.setattr(feed_cash, 'SnapshotCashInputs', lambda *args: source)
    monkeypatch.setattr(paper_performance, 'load', lambda *args: None)
    monkeypatch.setattr(fill_integrity, 'require_durable_coverage', lambda *args, **kwargs: True)
    monkeypatch.setattr(feed_actions, 'action_lookup', lambda conn, *, start, end:
        CorpusActionLookup(start=start, events={}, unresolved_events=(
            action_history._event(witness['marker']),)))
    monkeypatch.setattr(trial, '_cash_rows', lambda *args: ([], Decimal(0), Decimal(0)))
    bought = datetime(2026, 10, 19 if owned_before_ex_date else 21, 14, tzinfo=timezone.utc)
    fills = [(SID, 'BUY', Decimal(2), bought)]
    if owned_before_ex_date:
        fills.append((SID, 'SELL', Decimal(2), datetime(2026, 10, 23, 14, tzinfo=timezone.utc)))
    captured = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query, args): assert 'FROM sentinel_fills' in query
        def fetchall(self): return fills
    connection = SimpleNamespace(cursor=Cursor)
    def record(conn, verification):
        captured.append(verification)
        return {'paper_performance_quarantine': {'performance_valid': False}}
    monkeypatch.setattr(paper_performance, 'record_and_project', record)
    result = paper_performance.scan_entitlements(connection,
        binding={'deployment_id': 'cash-recovery-test', 'broker': 'alpaca',
                 'broker_account_id': 'paper-fixture', 'takeover_epoch': 1},
        through=END, account=SimpleNamespace(cash=Decimal(100), equity=Decimal(1000)))
    if owned_before_ex_date:
        assert result == {'performance_valid': False}
        assert captured[0]['paper_limitations']['expected_dividends'][0]['amount'] == '1.26'
        assert captured[0]['account_evidence']['account']['cash'] == '100'
    else:
        assert result is None and captured == []
    assert addition.proof.broker_payment_claimed is False


@pytest.mark.parametrize('guard,case', [
    ('canonical == per_share', 'cash_bar_mismatch'),
    ("for key in ('scalar', 'unsupported',", 'new_split'),
    ('IdentityResolver(listings_from_rows(identities)).resolve(ticker, session) == sid', 'identity_range'),
])
def test_removed_economic_guards_are_detected(monkeypatch, witness, guard, case):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(cc.classify))
    assert source.count(guard) == 1
    replacement = ("for key in ('unsupported'," if case == 'new_split' else 'True')
    namespace = dict(vars(cc))
    exec(compile(source.replace(guard, replacement), '<cash-correction-guard-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(cc, 'classify', namespace['classify'])
    with pytest.raises(AssertionError):
        test_mixed_changed_or_unproved_corrections_remain_restricted(witness, case)


def test_removed_native_authentication_is_detected(monkeypatch, witness):
    import inspect
    import textwrap
    conn, pub, covered, _ = bound_reader(monkeypatch, witness)
    def refuse(*args, **kwargs): raise ValueError('native publication HMAC refused')
    monkeypatch.setattr(publication, '_verify_receipt_chain', refuse)
    source = textwrap.dedent(inspect.getsource(cc.load))
    guard = 'publication._verify_receipt_chain(conn, through_version=pub.version)'
    assert source.count(guard) == 1
    namespace = dict(vars(cc))
    exec(compile(source.replace(guard, 'pass'), '<cash-native-auth-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(cc, 'load', namespace['load'])
    def require_refusal():
        try:
            cc.load(conn, pub, start=START, end=END, covered=covered,
                    records={DAY: witness['old_day']})
        except ValueError:
            return
        raise AssertionError('cash classification bypassed native authentication')
    with pytest.raises(AssertionError, match='bypassed native authentication'):
        require_refusal()
