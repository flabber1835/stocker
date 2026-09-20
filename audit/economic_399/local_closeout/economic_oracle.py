"""Independent fixture accounting from published input prices, not state marks."""
from decimal import Decimal
import json
from pathlib import Path

import psycopg


def check(conn, *, observation_id, session):
    name = f'shadow-observation:v1:{observation_id}:session:{session}'
    cash, nav = conn.execute(
        "SELECT state#>>'{state,wealth_core,cash}',state#>>'{strategy_economics,strategy_nav}' "
        'FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
    rows = conn.execute(
        "SELECT e.value->>'security_id',e.value->>'current_shares',e.value->>'entry_raw_open',"
        'b.open_unadjusted::text,b.close_unadjusted::text,b.split_ratio,b.dividend_per_share '
        'FROM sentinel_processed_sessions r '
        "CROSS JOIN LATERAL jsonb_each(r.state#>'{state,wealth_core,episodes}') e "
        'JOIN sentinel_snapshot_bars b ON b.candidate_id='
        "(r.state#>>'{publication,publication,evidence,rolling_snapshot,candidate_id}')::uuid "
        "AND b.session=r.session AND b.security_id=e.value->>'security_id' "
        'WHERE r.cursor_name=%s ORDER BY e.key', (name,)).fetchall()
    assert len(rows) == 20, 'fixture requires twenty priced occupied slots'
    notional, marked = Decimal(0), Decimal(0)
    for sid, shares, entry, opened, closed, split, dividend in rows:
        quantity = Decimal(shares)
        assert quantity > 0 and quantity == int(quantity), sid
        assert split == 1 and dividend == 0, 'oracle scope is action-free admission'
        assert abs(Decimal(entry) - Decimal(opened)) < Decimal('0.00000001'), sid
        notional += quantity * Decimal(opened)
        marked += quantity * Decimal(closed)
    fees = notional * Decimal('0.001')
    expected_cash = Decimal(100000) - notional - fees
    market_pnl = marked - notional
    assert abs(market_pnl) < Decimal('0.00000001'), 'fixture prices must be flat'
    expected_nav = Decimal(100000) - fees + market_pnl
    cash_error, nav_error = Decimal(cash) - expected_cash, Decimal(nav) - expected_nav
    assert abs(cash_error) < Decimal('0.00000001'), ('cash mismatch', cash_error)
    assert abs(nav_error) < Decimal('0.00000001'), ('NAV mismatch', nav_error)
    return {'scope': 'SYNTHETIC_ACCOUNTING_ONLY', 'price_source': 'published_snapshot_bars',
        'positions': len(rows), 'notional': str(notional), 'fees_10bps': str(fees),
        'mark_pnl': str(market_pnl), 'expected_cash': str(expected_cash),
        'retained_cash': cash, 'cash_error': str(cash_error),
        'expected_nav': str(expected_nav), 'retained_nav': nav, 'nav_error': str(nav_error)}


def main():
    fixture = json.loads(Path('/evidence/fixture.json').read_text())
    assert fixture['session'] == '2026-09-15'
    with psycopg.connect(fixture['dsn']) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        result = check(conn, observation_id='full-status-resource-probe', session=fixture['session'])
    print(json.dumps(result))


if __name__ == '__main__':
    main()
