"""Ordinary retained dividend sparsity versus the production entitlement scan."""
from datetime import date, datetime
from decimal import Decimal as D
from types import SimpleNamespace
import psycopg
import pytest
from sentinel import binding, schema, paper_performance
from sentinel.execution import feed_inputs, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerFill, BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.feed_cash import SnapshotCashInputs
from sentinel.execution.states import CommandState
from tests.sentinel.test_rolling_history_retention import (
    conn, pg, source, operational_source, aged_source, publish)

CASES = [
    ('unheld-equity-dividend', (('1','AAA'),), 'BBB', True, D(0)),
    ('one-of-two-held-pays', (('1','AAA'),('2','BBB')), 'BBB', True, D(120)),
    ('held-payer-only-control', (('2','BBB'),), 'BBB', False, D(120)),
    ('unheld-bil-dividend', (('1','AAA'),), 'BIL', True, D(0)),
    ('held-bil-only-control', (('SENTINEL:BIL','BIL'),), 'BIL', False, D(60)),
]

@pytest.mark.parametrize('history', ['current','retired'])
@pytest.mark.parametrize('label,holdings,payer,refuses,oracle', CASES, ids=[x[0] for x in CASES])
def test_sparse_action_record_only_prices_affected_holdings(
        conn, operational_source, monkeypatch, history, label, holdings, payer, refuses, oracle):
    ex_date = '2026-09-14' if history == 'current' else '2024-12-16'
    fill_date = '2026-09-11' if history == 'current' else '2024-12-13'
    ends = ('2026-09-14',) if history == 'current' else ('2025-01-02','2025-12-01','2026-09-14')
    for end in ends:
        aged_source(operational_source, monkeypatch, end, actions=False)
        operational_source['ACTIONS'].append(dict(ticker=payer, date=ex_date,
            action='dividend', name='fixture', value='1', contraticker=None, contraname=None))
        publish(conn)
    schema.ensure_schema(conn)
    bound = binding.bind(conn, deployment_id='sparse-dividend-audit', broker='alpaca', broker_account_id='PA-SPARSE-DIV')
    stamp = datetime.fromisoformat(fill_date+'T15:00:00+00:00')
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s', (stamp,))
    conn.commit()
    for sid, symbol in holdings:
        cmd = Command(identity=CommandIdentity(bound.identity,'historical-entry',sid),
            instrument=BrokerInstrument(sid,symbol), side=Side.BUY, quantity=D(10),
            filled_quantity=D(10), filled_average_price=D(600), broker_order_id='order-'+symbol,
            state=CommandState.FILLED, created_at=stamp)
        journal.save_command(conn, cmd)
        conn.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s', (stamp,cmd.client_key))
        conn.commit()
        journal.record_fills(conn,[BrokerFill(cmd.client_key,cmd.broker_order_id,D(10),D(600),stamp)])
    pub = feed_inputs.require_current(conn)
    feed_inputs.coherent(conn)
    source = SnapshotCashInputs(conn,pub)
    assert ex_date in source.days(stamp.date(),date(2026,9,14))
    held_ids = [sid for sid,_ in holdings if sid != 'SENTINEL:BIL']
    sparse_ids = [str(row[0]) for row in source.bars(ex_date, held_ids)]
    if refuses:
        assert '1' in held_ids and '1' not in sparse_ids
        if history == 'current':
            # The full, authenticated current snapshot HAS the required bar.
            row = conn.execute('SELECT close_signal,close_unadjusted,dividend_per_share '
                'FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s AND security_id=%s',
                (source.refs.candidate_id,ex_date,'1')).fetchone()
            assert row is not None and row[2] == 0
    # Independent entitlement: only held payers receive the normalized source
    # amount. Equity 600/50 = 12 per share; BIL 306/51 = 6 per share.
    independently_due = sum((D(10)*(D(6) if symbol=='BIL' else D(12))
        for _,symbol in holdings if symbol==payer),D(0))
    assert independently_due == oracle
    account = SimpleNamespace(cash=D(94000),equity=D(100000))
    mapping = bound.to_dict()
    conn.commit()
    for attempt in range(3):
        with psycopg.connect(conn.info.dsn) as restarted:
            marker = paper_performance.scan_entitlements(restarted, binding=mapping,
                through=date(2026,9,14), account=account)
            if oracle:
                assert marker['performance_valid'] is False
                assert sum((D(x['amount']) for x in marker['canonical_entitlements']), D(0)) == oracle
            else:
                assert marker is None
            restarted.commit()
            assert restarted.execute('SELECT count(*) FROM sentinel_cash_flows').fetchone()[0] == 0
            assert restarted.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == len(holdings)


@pytest.mark.parametrize('damage', ['missing-held-identity', 'ambiguous-held-payer'])
def test_sparse_scope_cannot_ignore_unresolved_possible_ownership(damage):
    from sentinel.feed.universe import IdentityResolver, listings_from_rows
    rows = [dict(permaticker='1', ticker='AAA', firstpricedate='2020-01-01'),
            dict(permaticker='2', ticker='AAA', firstpricedate='2020-01-01')]
    if damage == 'missing-held-identity':
        rows = rows[1:]
    inputs = object.__new__(SnapshotCashInputs)
    inputs.refs = SimpleNamespace(tickers=rows, projection=SimpleNamespace(alias_rows=[]),
        resolver=IdentityResolver(listings_from_rows(rows)))
    inputs._retained = lambda _: dict(identity_rows=rows, identity_aliases=[],
        sources=[dict(ticker='AAA', action='dividend')])
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match='IDENTITY_UNAVAILABLE'):
        inputs.affected_equities('2026-09-14', ['1'])

__all__ = ['conn', 'operational_source', 'pg', 'source']
