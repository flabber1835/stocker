"""Exact native account share movements can be explained but remain restricted."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.execution import alpaca_stock_mergers as mergers
from sentinel.execution import broker_cash, reconcile, share_units
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerFill, BrokerInstrument, BrokerObservation,
    BrokerPosition, Completeness)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.states import CommandState
from tests.sentinel.test_journal_and_reconcile import conn, pg, run  # noqa: F401


NATIVE = '11111111-1111-4111-8111-111111111111'
OLD = BrokerInstrument('old', 'ABC', '22222222-2222-4222-8222-222222222222')
NEW = BrokerInstrument('new', 'ABC', '33333333-3333-4333-8333-333333333333')
FOREIGN = BrokerInstrument('foreign', 'XYZ', '44444444-4444-4444-8444-444444444444')
DAY = date(2026, 11, 23)
CLOSE = datetime(2026, 11, 23, 21, 0, tzinfo=timezone.utc)
NOW = CLOSE + timedelta(days=1)
DETAILS = dict(ca_id='ca', group_id='group', position_date=DAY.isoformat(),
    effective_date=DAY.isoformat(), acquiree_cusip='123456789', acquirer_cusip='987654321',
    acquiree_qty='0.25', acquirer_qty='0.375', acquiree_rate='2', acquirer_rate='3')


def legs():
    return tuple(dict(activity_type='MA', activity_subtype='SMA', qty=qty, net_amount='0',
        details=dict(DETAILS), currency='USD', status='executed',
        ref_id=f'00000000-0000-4000-8000-00000000000{i}', event_id=f'01{i:024d}',
        executed_at=(NOW - timedelta(minutes=1)).isoformat(), settle_date=NOW.date().isoformat(),
        asset=dict(id=instrument.broker_id, symbol=instrument.symbol, cusip=cusip))
        for i, qty, instrument, cusip in (
            (1, '-0.25', OLD, DETAILS['acquiree_cusip']),
            (2, '0.375', NEW, DETAILS['acquirer_cusip'])))


def statement(rows, identity, *, through=NOW):
    return broker_cash.BrokerCashActivityBatch(
        processed_through=through, completeness=Completeness.COMPLETE,
        last_event_id=max((raw['event_id'] for raw in rows), default=None),
        last_activity_id=rows[-1]['ref_id'] if rows else None,
        activities=tuple(broker_cash.BrokerCashActivity(raw['ref_id'], 'MA',
            date.fromisoformat(raw['settle_date']), Decimal(raw['net_amount']), raw)
            for raw in rows), native_account=(identity.broker, identity.account_id, NATIVE))


def position_view(identity=None, *, quantity='0.375', add=()):
    return BrokerObservation(observed_at=NOW, completeness=Completeness.COMPLETE,
        orders=(), positions=(BrokerPosition(NEW, Decimal(quantity)), *add), account_identity=identity)


def prior_command(**changes):
    return SimpleNamespace(instrument=OLD, security_id=OLD.security_id, state=CommandState.FILLED,
        client_key='cmd', filled_quantity=Decimal('0.25'),
        identity=SimpleNamespace(plan_id='ordinary-plan'),
        created_at=CLOSE-timedelta(hours=1), **changes)


def test_exact_fractional_merger_works_in_both_arrival_orders_and_restricts_both_roles():
    old, new = legs()
    for raw in ((old, new), (new, old)):
        movement, = mergers.movements(raw, observed_at=NOW)
        assert movement.old_asset == OLD.broker_id and movement.new_asset == NEW.broker_id
        restricted = mergers.explain(movements=(movement,), commands=(prior_command(),),
            expected={'old': Decimal('0.25')}, observation=position_view(add=(
                BrokerPosition(FOREIGN, Decimal(4)),)), eligible=lambda *_: True)
        assert restricted == dict.fromkeys(('old', 'new'), 'CORPORATE_ACTION_RECEIPT_RESTRICTED: ca:group')


@pytest.mark.parametrize('damage', [None, 'missing asset', 'bad balance', 'wrong actual'])
def test_dividend_requires_one_exact_same_asset_share_receipt(damage):
    raw, _ = legs()
    raw.update(activity_type='DIV', activity_subtype='SDIV', qty='0.002709921')
    raw['details'] = dict(ca_id='div', group_id='group', position_date=DAY.isoformat(),
        ex_date=NOW.date().isoformat(), entitled_qty='0.09140625', paid_qty='0.002709921',
        new_qty='0.094116171', rate='1.029647')
    if damage == 'missing asset':
        del raw['asset']
    if damage == 'bad balance':
        raw['details']['new_qty'] = '0.09411617'
    actual = '0.09411617' if damage == 'wrong actual' else '0.094116171'
    observation = replace(position_view(), positions=(BrokerPosition(OLD, Decimal(actual)),))
    restricted = mergers.explain(movements=mergers.movements((raw,), observed_at=NOW),
        commands=(prior_command(),), expected={'old': Decimal('0.09140625')},
        observation=observation, eligible=lambda *_: True)
    assert set(restricted) == ({'old'} if damage is None else set())


def test_empty_migration_markers_do_not_trigger_a_second_reconciliation():
    from sentinel.feed.rolling_contract import digest

    assert not share_units.has_native_position_receipts(None)
    state = SimpleNamespace(stock_merger_proof={'sha256': digest({})},
                            security_transfer_commitment=None)
    assert not share_units.has_native_position_receipts(state)
    state.security_transfer_commitment = {'sha256': digest({'receipt': 'asset'})}
    assert share_units.has_native_position_receipts(state)


@pytest.mark.parametrize('damage', ['single leg', 'missing asset', 'split groups',
    'changed ratio', 'unequal amount', 'extra cash leg', 'distinct group overlap', 'revision'])
def test_native_proof_does_not_adopt_an_ambiguous_or_nonzero_cash_group(damage):
    old, new = legs()
    rows = [old, new]
    if damage == 'single leg':
        rows.pop()
    elif damage == 'missing asset':
        del new['asset']
    elif damage == 'split groups':
        new['details']['group_id'] = 'other'
    elif damage == 'changed ratio':
        old['details']['acquirer_rate'] = new['details']['acquirer_rate'] = '3.1'
    elif damage == 'unequal amount':
        new['qty'] = '0.375000001'
    elif damage == 'extra cash leg':
        rows.append({**new, 'activity_type': 'CIL', 'net_amount': '0.1'})
    elif damage == 'distinct group overlap':
        rows += [{**row, 'details': {**row['details'], 'group_id': 'other'}} for row in rows]
    else:
        new['previous_id'] = old['ref_id']
    assert not mergers.movements(rows, observed_at=NOW)


@pytest.mark.parametrize('damage', ['old inventory', 'wrong new quantity', 'unknown', 'journal scope'])
def test_posting_lag_or_unknown_cannot_be_classed_as_explained(damage):
    observation = position_view()
    command = prior_command()
    if damage == 'old inventory':
        observation = position_view(add=(BrokerPosition(OLD, Decimal('0.25')),))
    elif damage == 'wrong new quantity':
        observation = position_view(quantity='0.374999999')
    elif damage == 'unknown':
        command.state = CommandState.UNKNOWN
    else:
        command.instrument = replace(OLD, broker_id=FOREIGN.broker_id)
    assert not mergers.explain(movements=mergers.movements(legs(), observed_at=NOW),
        commands=(command,), expected={'old': Decimal('0.25')},
        observation=observation, eligible=lambda *_: True)


@pytest.mark.parametrize('namespace,number', [('alpaca', 'PA-proof'), ('alpaca-live', NATIVE)])
def test_native_merger_persists_across_cash_cursor_polls_and_restores(conn, namespace, number):
    from sentinel.execution import journal

    identity = BrokerAccountIdentity(namespace, number, {'id': NATIVE})
    deployment = DeploymentIdentity('nas-1', namespace, number, 1)
    conn.execute('UPDATE sentinel_account_binding SET broker=%s,broker_account_id=%s,established_at=%s',
                 (namespace, number, CLOSE))
    conn.commit()

    class Broker:
        financial_activity_sse = True

        def __init__(self):
            self.events = ()
            self.reads = []

        async def account_cash_activities(self, *, after, through, since_event_id=None):
            self.reads.append((after, through, since_event_id))
            return statement(self.events, identity, through=through)

    adapter = Broker()

    def ingest(through):
        state = run(broker_cash.ingest_account_cash(conn, broker_adapter=adapter,
            broker=namespace, account_id=number, through=through))
        conn.commit()
        return state

    old, new = legs()
    adapter.events = (old,)
    first = ingest(NOW - timedelta(seconds=1))
    assert first.balance_total == 0
    assert mergers.reconciled_restrictions(conn, state=first, deployment=deployment,
        actions=reconcile.CorpusActionLookup(start=DAY, events={}),
        commands=(prior_command(),), expected={'old': Decimal('0.25')},
        observation=position_view(identity)) == {}
    adapter.events = (new,)
    later = ingest(NOW)
    assert adapter.reads[-1][2] == old['event_id']
    assert later.stock_merger_proof != first.stock_merger_proof and later.balance_total == 0
    checkout = broker_cash.load_activity_state(conn, broker=namespace, account_id=number)
    assert checkout == later
    mergers.verify_restored(conn, state=checkout)

    journal.record_fills(conn, [BrokerFill(client_key='cmd', broker_order_id='old-order',
        quantity=Decimal('0.25'), price=Decimal(10), filled_at=CLOSE-timedelta(minutes=5))])
    def explain():
        return mergers.reconciled_restrictions(conn, state=checkout, deployment=deployment,
            actions=reconcile.CorpusActionLookup(start=DAY, events={}),
            commands=(prior_command(),), expected={'old': Decimal('0.25')},
            observation=position_view(identity))
    assert set(explain()) == {'old', 'new'}
    conn.execute('UPDATE sentinel_fills SET filled_at=%s', (CLOSE + timedelta(seconds=1),))
    assert not explain()

    conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
                 (mergers.PREFIX + '%' + new['ref_id'],))
    with pytest.raises(mergers.StockMergerEvidenceRefused, match='differs from its commitment'):
        mergers.verify_restored(conn, state=checkout)
