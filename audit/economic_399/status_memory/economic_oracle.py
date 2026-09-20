"""Independent Decimal accounting check of the synthetic flat-price admission."""
from decimal import Decimal
import json
from pathlib import Path

import psycopg


def main():
    fixture = json.loads(Path('/evidence/fixture.json').read_text())
    assert fixture['session'] == '2026-09-15'
    name = 'shadow-observation:v1:full-status-resource-probe:session:2026-09-15'
    with psycopg.connect(fixture['dsn']) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cash, nav = conn.execute(
            "SELECT state#>>'{state,wealth_core,cash}',state#>>'{strategy_economics,strategy_nav}' "
            'FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
        rows = conn.execute(
            "SELECT value->>'security_id',value->>'current_shares',value->>'entry_raw_open',"
            " state#>>ARRAY['state','feed','series',value->>'security_id','raw_closes','-1'] "
            'FROM sentinel_processed_sessions,'
            " LATERAL jsonb_each(state#>'{state,wealth_core,episodes}') "
            'WHERE cursor_name=%s ORDER BY key', (name,)).fetchall()
    assert len(rows) == 20
    notional = Decimal(0)
    marked = Decimal(0)
    for sid, shares, opened, closed in rows:
        assert Decimal(shares) > 0 and Decimal(shares) == int(Decimal(shares)), sid
        notional += Decimal(shares) * Decimal(opened)
        marked += Decimal(shares) * Decimal(closed)
    # Independently apply the frozen 10 bps entry cost, no strategy helper calls.
    fees = notional * Decimal('0.001')
    expected_cash = Decimal(100000) - notional - fees
    market_pnl = marked - notional
    # The copied input bars are flat; reconstructed float marks may differ by
    # binary roundoff. Report that difference separately, never fold it into fees.
    assert abs(market_pnl) < Decimal('0.00000001')
    expected_nav = Decimal(100000) - fees + market_pnl
    cash_error, nav_error = Decimal(cash)-expected_cash, Decimal(nav)-expected_nav
    assert abs(cash_error) < Decimal('0.00000001')
    assert abs(nav_error) < Decimal('0.00000001')
    print(json.dumps({'scope': 'SYNTHETIC_ACCOUNTING_ONLY', 'positions': len(rows),
        'notional': str(notional), 'fees_10bps': str(fees), 'mark_pnl': str(market_pnl),
        'expected_cash': str(expected_cash), 'retained_cash': cash, 'cash_error': str(cash_error),
        'expected_nav': str(expected_nav), 'retained_nav': nav, 'nav_error': str(nav_error)}))


if __name__ == '__main__':
    main()
