from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import asyncio
import pytest

from sentinel import dual_reconciliation
from sentinel.execution import fill_integrity, reconcile
from sentinel.execution import feed_inputs, journal
from sentinel.execution.contract import (
    BrokerFill, BrokerInstrument, BrokerObservation, BrokerOrder,
    BrokerPosition, Completeness, Side,
)
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
from tests.sentinel.test_regular_quote_submission import QuoteBroker, instrument, wrap
from tests.sentinel.test_dual_regenesis_handover import _Conn, _observation_row


NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)


def test_authenticated_current_uuid_can_follow_multiple_historical_uuids():
    old = BrokerInstrument('canonical', 'AAA', 'old-uuid')
    current = replace(old, broker_id='current-uuid')
    commands = [SimpleNamespace(security_id='canonical', instrument=item)
                for item in (old, current)]
    observed = BrokerObservation(observed_at=NOW,
        positions=(BrokerPosition(current, D(10)),))
    assert reconcile._position_identity_conflicts(observed, commands,
        provider_asset_ids={'canonical': 'current-uuid'}) == ()
    assert reconcile._position_identity_conflicts(
        replace(observed, positions=()), commands,
        provider_asset_ids={'canonical': 'current-uuid'}) == ()
    wrong = replace(observed, positions=(BrokerPosition(
        replace(current, broker_id='unproven-uuid'), D(10)),))
    assert reconcile._position_identity_conflicts(wrong, commands,
        provider_asset_ids={'canonical': 'current-uuid'})
    assert reconcile._position_identity_conflicts(observed, commands)


def test_fresh_reserved_buying_power_defers_without_transport():
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(minutes=3)
    inner.cash = D(1000)
    inner.buying_power = D(40)
    broker = wrap(inner)
    with pytest.raises(OrderEvidenceNotReady, match='available cash'):
        asyncio.run(broker.submit(client_key='reserved-cash', instrument=instrument(),
            side=Side.BUY, quantity=D(1)))
    assert 'submit:reserved-cash' not in inner.calls


def _filled_observation(monkeypatch, *, average='10.016666667', quantity='1'):
    monkeypatch.setattr(calendar, 'session_window', lambda _: (
        NOW - timedelta(hours=1), NOW + timedelta(hours=6)))
    key = CommandIdentity(DeploymentIdentity('d', 'alpaca', 'a', 1), 'p', 's').client_key
    unit = D(quantity)
    order = BrokerOrder('order', key, BrokerInstrument('s', 'AAA', 'asset'),
        Side.BUY, CommandState.FILLED, unit * 3, unit * 3, D(average),
        NOW - timedelta(minutes=1))
    fills = tuple(BrokerFill(key, 'order', unit, D(price),
        NOW - timedelta(seconds=3-index))
        for index, price in enumerate(('10.01', '10.02', '10.02')))
    return BrokerObservation(observed_at=NOW, orders=(order,), fills=fills), order


@pytest.mark.parametrize('quantity', ['1', '0.125'])
def test_native_fill_gross_accepts_serialized_recurring_average(monkeypatch, quantity):
    observation, order = _filled_observation(monkeypatch, quantity=quantity)
    fill_integrity.validate(observation, {'order': order})


def test_native_fill_gross_still_refuses_outside_average_precision(monkeypatch):
    observation, order = _filled_observation(monkeypatch, average='10.016666670')
    with pytest.raises(ValueError, match='gross notional'):
        fill_integrity.validate(observation, {'order': order})


@pytest.mark.parametrize('average', ['100', '1E+2'])
def test_integer_average_does_not_infer_unspecified_fractional_precision(average):
    assert not fill_integrity.gross_matches_serialized_average(D(10), D(1005), D(average))
    assert fill_integrity.gross_matches_serialized_average(D(10), D(1000), D(average))


@pytest.mark.parametrize('quantity,filled,gross,average,valid,complete', [
    ('3', '3', '30.05', '10.016666667', True, True),
    ('3', '3', '30.05', '10.016666670', False, True),
    ('1.000000001', '1', '1', '0.999999999', True, False),
    ('1.000000001', '1', '1.000000001', '0.999999999', False, False),
])
def test_durable_native_fill_coverage_uses_the_same_average_precision(
        quantity, filled, gross, average, valid, complete):
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def execute(self, *_args):
            pass
        def fetchall(self):
            return [('key', 'FILLED', D(quantity), D(average), D(filled), D(gross))]
    class Connection:
        def cursor(self):
            return Cursor()
    from sentinel.trial import TrialEvidenceRefused
    binding = {'broker': 'alpaca', 'broker_account_id': 'paper'}
    if valid:
        assert fill_integrity.require_durable_coverage(
            Connection(), binding, allow_incomplete=True) is complete
    else:
        with pytest.raises(TrialEvidenceRefused):
            fill_integrity.require_durable_coverage(
                Connection(), binding, allow_incomplete=True)


@pytest.mark.parametrize('price,valid', [('1', True), ('1.000000001', False)])
def test_partial_native_fill_coverage_leaves_room_within_serialized_average(
        monkeypatch, price, valid):
    observation, order = _filled_observation(monkeypatch)
    order = replace(order, quantity=D('1.000000001'),
        filled_quantity=D('1.000000001'), filled_average_price=D('0.999999999'))
    observation = replace(observation, orders=(order,), fills=(
        replace(observation.fills[0], quantity=D(1), price=D(price)),))
    if valid:
        fill_integrity.validate(observation, {'order': order})
    else:
        with pytest.raises(ValueError, match='positive notional'):
            fill_integrity.validate(observation, {'order': order})


def test_regenesis_reader_accepts_actual_current_journal_provenance():
    row = list(_observation_row(NOW))
    row[-1] = dict(row[-1], exact_evidence=[])
    body, _, _ = dual_reconciliation._observation_evidence(
        _Conn(NOW, observation_row=tuple(row)), seq=row[0])
    assert body['positions'] == {}
    assert body['exact_evidence'] == []


def test_published_uuid_authority_is_read_from_bound_source_bundles(monkeypatch):
    from tests.sentinel.test_published_alpaca_identity import reference, source
    from tests.sentinel.test_alpaca_name_change_continuity import inputs
    from sentinel.feed import alpaca_identity
    bindings = alpaca_identity.bind(**inputs())
    refs = SimpleNamespace(manifest=SimpleNamespace(provider='ALPACA_OPENFIGI',
        reference_sha256='refs', source_evidence_sha256='source'),
        resolver=SimpleNamespace(resolve=lambda symbol, day: 'canonical-old'))
    monkeypatch.setattr(feed_inputs, '_snapshot_identity_authorities', lambda *a, **k: (
        refs, '2026-09-16', '2026-09-15', refs.resolver))
    payloads = {'refs': reference(modern=True, bindings=bindings),
                'source': source('3', bindings)}
    monkeypatch.setattr(feed_inputs.rolling_store, 'load_evidence', lambda conn, key: payloads[key])
    resolver = feed_inputs.resolver(object(), object(), session='2026-09-16')
    assert resolver.provider_asset_ids == {'canonical-old': 'new-provider'}
    broker = SimpleNamespace(_inner=SimpleNamespace(_resolve=resolver))
    assert feed_inputs.source_bound_provider_asset_ids(broker) == resolver.provider_asset_ids
    with pytest.raises(TypeError):
        resolver.provider_asset_ids['canonical-old'] = 'unproven'
    payloads['source']['identity_bindings_sha256'] = 'f' * 64
    from sentinel.feed.alpaca_transport import AlpacaTransportRefused
    with pytest.raises(AlpacaTransportRefused, match='digest mismatch'):
        feed_inputs.resolver(object(), object(), session='2026-09-16')


@pytest.mark.parametrize('fault', ['negative_power', 'missing_power', 'margin', 'blocked'])
def test_fresh_purchase_funding_rechecks_account_envelope(fault):
    from sentinel.execution.guarded import PreTransportAuthorityRefused
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(minutes=3)
    if fault == 'negative_power':
        inner.buying_power = D(-1)
    elif fault == 'margin':
        inner.multiplier = D(2)
    elif fault == 'blocked':
        inner.trading_blocked = True
    else:
        original = inner.account_snapshot
        async def missing():
            return replace(await original(), buying_power=None)
        inner.account_snapshot = missing
    with pytest.raises(PreTransportAuthorityRefused):
        asyncio.run(wrap(inner).submit(client_key='invalid-funds', instrument=instrument(),
            side=Side.BUY, quantity=D(1)))
    assert 'submit:invalid-funds' not in inner.calls


@pytest.mark.parametrize('fault', ['foreign_account', 'unknown_field', 'working_order'])
def test_regenesis_exact_evidence_is_validated_and_cannot_hide_work(fault):
    row = list(_observation_row(NOW))
    exact = {'client_key': 'sntl-key',
        'request_started_at': (NOW-timedelta(seconds=1)).isoformat(),
        'request_completed_at': NOW.isoformat(),
        'identity_before': {'broker': 'alpaca', 'account_id': 'paper-1'},
        'identity_after': {'broker': 'alpaca', 'account_id': 'paper-1'},
        'initial_order_id': None, 'order': None}
    if fault == 'foreign_account':
        exact['identity_after']['account_id'] = 'other'
    elif fault == 'unknown_field':
        exact['unexpected'] = True
    else:
        exact['order'] = {'broker_order_id': 'working', 'client_key': 'sntl-key',
            'security_id': 's', 'symbol': 'AAA', 'broker_id': 'asset',
            'side': 'BUY', 'state': 'ACKNOWLEDGED', 'quantity': '1',
            'filled_quantity': '0', 'filled_average_price': None,
            'submitted_at': (NOW-timedelta(seconds=5)).isoformat(),
            'external_replacement': False, 'replaced_by': None, 'replaces': None}
    row[-1] = dict(row[-1], exact_evidence=[exact])
    with pytest.raises((dual_reconciliation.DualReconciliationRefused,
                        dual_reconciliation.DualReconciliationPending)):
        body, _, _ = dual_reconciliation._observation_evidence(
            _Conn(NOW, observation_row=tuple(row)), seq=row[0])
        dual_reconciliation._require_flat_observation_body(body)


class _PagedRows:
    def __init__(self, count):
        self.count = count
        self.pages = []
        self.params = None
        self.account_binding = ('sim', 'account', NOW)
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params
    def fetchone(self):
        if 'SELECT COALESCE(MAX(o.seq),0)' in self.sql:
            return (self.count, *self.account_binding)
        return self.account_binding
    def fetchall(self):
        after, upper, broker, account, established, limit = self.params
        if (broker, account, established) != self.account_binding:
            return []
        rows = [(seq, ('%016d' % seq) + 'x' * 16384)
                for seq in range(after+1, min(upper, after+limit)+1)]
        self.pages.append(len(rows))
        return rows


def test_observation_integrity_history_is_bounded_and_checks_every_page():
    conn = _PagedRows(1025)
    sequences = [row[0] for row in journal._observation_integrity_rows(conn)]
    assert sequences == list(range(1, 1026))
    assert max(conn.pages) == journal.OBSERVATION_INTEGRITY_PAGE_SIZE
    assert len(conn.pages) == 9


def test_observation_integrity_scan_pins_upper_boundary():
    conn = _PagedRows(256)
    scan = journal._observation_integrity_rows(conn)
    assert next(scan)[0] == 1
    assert conn.pages == [journal.OBSERVATION_INTEGRITY_PAGE_SIZE]
    conn.count = 300
    assert [row[0] for row in scan][-1] == 256
    assert len(list(journal._observation_integrity_rows(conn))) == 300


@pytest.mark.parametrize('change_after_last_page', [False, True])
def test_observation_integrity_scan_refuses_concurrent_rebind(change_after_last_page):
    conn = _PagedRows(256)
    scan = journal._observation_integrity_rows(conn)
    take = 256 if change_after_last_page else 1
    for _ in range(take):
        next(scan)
    conn.account_binding = ('sim', 'other-account', NOW)
    with pytest.raises(journal.ObservationEvidenceUncertifiable, match='binding changed'):
        list(scan)
