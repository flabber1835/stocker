"""Audit #399 F19: contradictory native fills reach rolling entitlement scans.

Source/vendor and broker HTTP are local response fixtures. Real publication,
retained action readers, Alpaca parsing, reconciliation, SQL and quarantine run.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
import psycopg
import pytest
import test_fill_order_coherence as original
from sentinel import paper_performance as P
from sentinel.execution import journal, reconcile as R
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.states import RuntimeState
from sentinel.feed import operational_snapshot as op
from tests.conftest import isolated_image_backup_policy, isolated_source_cache
from tests.sentinel.test_rolling_snapshot_publisher import pg, conn, source
from tests.sentinel.test_operational_snapshot import operational_source, enqueue

UTC=timezone.utc
BEFORE=datetime(2026,8,19,17,tzinfo=UTC)
EXDAY=datetime(2026,8,20,17,tzinfo=UTC)
THROUGH=date(2026,9,14)
EXDATE=date(2026,8,20)

@pytest.mark.parametrize('quantities,submitted,filled,oracle,recorded', [
    (('10',), BEFORE, BEFORE.replace(minute=1), Decimal(20), Decimal(20)),
    (('20',), BEFORE, BEFORE.replace(minute=1), Decimal(20), Decimal(40)),
    (('6','6'), BEFORE, BEFORE.replace(minute=1), Decimal(20), Decimal(24)),
    (('10',), EXDAY, EXDAY.replace(minute=1), Decimal(0), Decimal(0)),
    (('10',), EXDAY, BEFORE.replace(minute=1), Decimal(0), Decimal(20)),
], ids=['valid-prior-fill','twenty-for-ten','six-plus-six-for-ten',
        'valid-exday-fill','false-prior-day-fill'])
def test_actual_dividend_scan_uses_contradictory_native_fill_history(
        conn, operational_source, monkeypatch, quantities, submitted, filled, oracle, recorded):
    # Fix the synthetic identity before publication; this models no rename.
    for table in ('SEP','TICKERS','ACTIONS'):
        for row in operational_source[table]:
            if row.get('ticker')=='AAA':
                row['ticker']='AAPL'
                if table=='ACTIONS':
                    row['date']=EXDATE.isoformat()
    publication=op.prepare(conn,enqueue(conn))
    assert publication['scope']=='DATA_ONLY'
    # Only an audit-helper constant is replaced. The actual broker receives its
    # permanent identity resolver through the normal constructor.
    monkeypatch.setattr(original,'INSTRUMENT',BrokerInstrument(
        security_id='1',symbol='AAPL',broker_id='asset-aapl'))
    owner,command,_unused,http,_events=original.fixture(
        conn,native_quantities=quantities,fill_time=filled)
    http.routes['/v2/orders/order-1']['submitted_at']=submitted.isoformat()
    conn.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s',
                 (submitted,command.client_key))
    conn.commit()
    broker=AssetIdAlpacaExecutionBroker(api_key='local-audit-k',secret_key='local-audit-s',
        base_url=original.PAPER,resolve_security_id=lambda symbol,_as_of=None:
            {'AAPL':'1','BBB':'2'}[symbol],http_provider=lambda:http)
    result=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    assert result.clean and result.runtime_state is RuntimeState.RUNNING,result.to_dict()
    assert result.expected==result.observed=={'1':Decimal(10)}
    # Independent oracle: 10 actual shares * $1 signal dividend * 100/50.
    # An ex-date acquisition has no entitlement.
    assert oracle==(Decimal(10)*Decimal(1)*Decimal(100)/Decimal(50)
                    if submitted.date()<EXDATE else Decimal(0))
    account=SimpleNamespace(cash=Decimal(9000),equity=Decimal(10000))
    marker=P.scan_entitlements(conn,binding=owner.identity.to_dict(),through=THROUGH,account=account)
    conn.commit()
    if recorded:
        assert marker['performance_valid'] is False
        assert marker['synthetic_adjustment'] is None
        entitlements=marker['canonical_entitlements']
        assert len(entitlements)==1
        assert Decimal(entitlements[0]['amount'])==recorded,entitlements
        assert Decimal(entitlements[0]['shares'])==sum(map(Decimal,quantities))
        assert entitlements[0]['accrued_session']==EXDATE.isoformat()
    else:
        assert marker is None
    for _ in range(2):
        with psycopg.connect(conn.info.dsn) as restarted:
            assert P.scan_entitlements(restarted,binding=owner.identity.to_dict(),
                through=THROUGH,account=account)==marker
    assert conn.execute('SELECT COUNT(*) FROM sentinel_cash_flows').fetchone()[0]==0
    current=journal.load_commands(conn,owner.identity)[0]
    assert current.filled_quantity==Decimal(10)
    assert current.filled_average_price==Decimal(100)
    assert not [call for call in http.calls if call[0]!='GET']
    print(json.dumps({'native_quantities':quantities,'submitted':submitted.isoformat(),
        'native_fill_time':filled.isoformat(),'independent_entitlement':str(oracle),
        'retained_entitlement':str(recorded),'quarantine':marker,'runtime':result.runtime_state.value},default=str))
