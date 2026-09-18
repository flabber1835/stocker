"""Audit-only fault probes: preservation of publication-bound action coverage."""
from datetime import date, datetime, timezone
import asyncio
from dataclasses import asdict
from decimal import Decimal

import psycopg
import pytest

from sentinel.execution import feed_actions, feed_inputs
from sentinel.feed import action_history, rolling_store, runtime_schema
from tests.sentinel.test_rolling_history_retention import (  # noqa: F401
    conn, pg, source, operational_source, aged)


@pytest.mark.parametrize('version,expected_after', [(1, Decimal(3)), (2, Decimal(2))])
def test_missing_historical_coverage_is_silently_treated_as_no_event(
        conn, aged, version, expected_after):
    start, end = date(2024, 12, 13), date(2026, 9, 14)
    before = feed_actions.action_lookup(conn, start=start, end=end)
    assert before('1') == before('SENTINEL:BIL') == Decimal(6)
    from sentinel import binding, schema
    from sentinel.execution import journal, reconcile
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.states import CommandState, RuntimeState
    from sentinel.execution.simulator import SimulatedBroker
    schema.ensure_schema(conn)
    bound = binding.bind(conn, deployment_id='retained-action-audit', broker='sim', broker_account_id='SIM-ACCOUNT')
    created = datetime(2024,12,13,15,tzinfo=timezone.utc)
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s', (created,))
    conn.commit()
    command = Command(identity=CommandIdentity(bound.identity, 'aged-command', '1'),
        instrument=BrokerInstrument('1', 'AAA'), side=Side.BUY,
        quantity=Decimal(10), filled_quantity=Decimal(10),
        filled_average_price=Decimal(600), broker_order_id='old-broker-order',
        state=CommandState.FILLED, created_at=created)
    journal.save_command(conn, command)
    # Model the historical execution time in the durable fixture.
    conn.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s', (created, command.client_key))
    conn.commit()
    broker = SimulatedBroker(now=datetime(2026,9,14,20,tzinfo=timezone.utc),
        equity=Decimal(10000), cash=Decimal(4000))
    broker.seed_position(command.instrument, '60')
    good = asyncio.run(reconcile.reconcile(broker=broker, conn=conn,
        binding=bound, deployment=bound.identity, actions=before))
    assert good.runtime_state == RuntimeState.RUNNING, good.detail
    original = asdict(journal.load_commands(conn, bound.identity)[0])
    rows = conn.execute('SELECT publication_version,payload_sha256 FROM sentinel_action_coverage ORDER BY publication_version').fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert conn.execute('SELECT count(*) FROM sentinel_action_history WHERE publication_version=%s', (version,)).fetchone()[0] > 0
    # Isolated disposable-DB corruption: erase one prior coverage row while
    # preserving publications, their receipts, current coverage and event rows.
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('DELETE FROM sentinel_action_coverage WHERE publication_version=%s', (version,))
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        runtime_schema.require_feed_schema(restarted)
        pub = feed_inputs.require_current(restarted)
        assert pub.version == 3
        feed_inputs.coherent(restarted)
        after = feed_actions.action_lookup(restarted, start=start, end=end)
        assert after('1') == after('SENTINEL:BIL') == expected_after
        assert not after.unresolved_events
        assert not after.unsupported_events
        # Oracle: unchanged, authenticated original source economics = 2 * 3.
        assert after('1') != Decimal(2) * Decimal(3)
        assert reconcile.expected_book_from_commands([command], after) == {'1': Decimal(10) * expected_after}
        bad = asyncio.run(reconcile.reconcile(broker=broker, conn=restarted,
            binding=bound, deployment=bound.identity, actions=after))
        assert bad.runtime_state == RuntimeState.FOREIGN_ACTIVITY, bad.detail
        assert asdict(journal.load_commands(restarted, bound.identity)[0]) == original
        assert not any(c.startswith('submit:') for c in broker.calls)
        print('reconciliation_after_loss:', bad.runtime_state, bad.detail)
        assert restarted.execute('SELECT count(*) FROM sentinel_action_history WHERE publication_version=%s', (version,)).fetchone()[0] > 0
        print(f'coverage_version={version}; independent_multiplier=6; accepted_multiplier={after("1")}; current_publication={pub.version}; unresolved=0')


@pytest.mark.parametrize('fault', ['history_row', 'current_coverage', 'normal_delete'])
def test_adjacent_integrity_guards_refuse(conn, aged, fault):
    start, end = date(2024, 12, 13), date(2026, 9, 14)
    assert feed_actions.action_lookup(conn, start=start, end=end)('1') == 6
    if fault == 'normal_delete':
        with pytest.raises(Exception, match='immutable'):
            conn.execute('DELETE FROM sentinel_action_coverage WHERE publication_version=1')
        conn.rollback()
        assert feed_actions.action_lookup(conn, start=start, end=end)('1') == 6
        return
    conn.execute('SET LOCAL session_replication_role=replica')
    if fault == 'history_row':
        conn.execute('DELETE FROM sentinel_action_history WHERE publication_version=1')
        expected = 'RETAINED_ACTION_EVIDENCE_CORRUPT'
    else:
        conn.execute('DELETE FROM sentinel_action_coverage WHERE publication_version=3')
        expected = 'RETAINED_ACTION_COVERAGE_MISSING'
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        with pytest.raises(ValueError, match=expected):
            feed_actions.action_lookup(restarted,start=start,end=end)
