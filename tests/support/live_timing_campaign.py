"""Generated external inputs only for the real-clock private timing campaign.

No clock, calendar, runtime guard, authority result or canonical book is replaced.
The issuer and native-shaped broker live in their existing independent helpers.
"""
from datetime import datetime, timezone
from decimal import Decimal
import uuid


class Source:
    def __init__(self, frontier, *, assets):
        from sentinel.feed.rolling_contract import CurrentFormationWindow
        self.window = CurrentFormationWindow.through(frontier)
        self.assets = assets
        self.description = {'schema': 'sentinel.generated-timing-source/1', 'assets': assets,
            'sessions': len(self.window.sessions), 'first_session': str(self.window.start),
            'last_session': str(self.window.end), 'bar_count': assets * len(self.window.sessions),
            'prices': 'DETERMINISTIC_POSITIVE_DIVERSE_LINEAR_RAW_NO_ACTIONS_V1',
            'limitations': 'generated coverage and prices; no native data/finality or market-liquidity claim'}

    def get(self, endpoint, params):
        from sentinel.feed.alpaca_transport import ASSETS
        assert endpoint == ASSETS
        return [{'id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'private-timing-security:{index}')),
                 'symbol': f'T{index:05}', 'name': f'Generated company {index}', 'class': 'us_equity',
                 'status': 'active', 'tradable': True, 'exchange': 'NASDAQ'}
                for index in range(self.assets)], {'observed_at': datetime.now(timezone.utc).isoformat()}

    def pages(self, endpoint, params, *, key):
        from sentinel.feed.alpaca_source import _bounds
        from sentinel.feed.alpaca_transport import ACTION_URL, BAR_URL
        proof = {'observed_at': datetime.now(timezone.utc).isoformat()}
        if endpoint == ACTION_URL:
            yield {'forward_splits': []}, proof
            return
        assert endpoint == BAR_URL and key == 'bars'
        low, high = params['start'][:10], params['end'][:10]
        rows = {}
        for symbol in params['symbols'].split(','):
            number = int(symbol[1:]) if symbol.startswith('T') else 0
            result = []
            for index, session in enumerate(self.window.sessions):
                if not low <= str(session) <= high:
                    continue
                # Whole cents avoid creating unrepresentable source prices.
                # Distinct slopes/rankings exercise more than identical bars.
                cents = 3000 + number % 12000 + index * (2 + number % 19)
                price = cents / 100
                stamp = datetime.fromisoformat(_bounds(str(session), str(session))[0]).astimezone(timezone.utc).isoformat()
                result.append({'t': stamp, 'o': price, 'c': price, 'v': 1_000_000 + number})
            rows[symbol] = result
        yield rows, proof


class Classifier:
    batch_size = 100

    def mapping(self, assets):
        from sentinel.feed import openfigi
        return [{'data': [{'ticker': openfigi.job(asset)['idValue'], 'exchCode': 'US',
            'marketSector': 'Equity', 'securityType': 'Common Stock', 'securityType2': 'Common Stock',
            'compositeFIGI': 'GENERATED-' + asset['asset_id'],
            'shareClassFIGI': 'GENERATED-SHARE-' + asset['asset_id']}]} for asset in assets], {
                'observed_at': datetime.now(timezone.utc).isoformat()}


def assets_for_publication(conn, published):
    """Read exact authenticated RAW marks/IDs through the current storage layout."""
    from sentinel.feed import normalized_layout
    candidate = published['candidate_id']
    day = conn.execute('SELECT window_end FROM sentinel_price_candidates WHERE candidate_id=%s',
                       (candidate,)).fetchone()[0]
    rows = conn.execute(normalized_layout.candidate_query(conn,
        'SELECT security_id,ticker,close_unadjusted FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND session=%s ORDER BY security_id'), (candidate, day)).fetchall()
    result = {symbol: {'id': sid, 'security_id': sid, 'symbol': symbol, 'price': Decimal(str(price))}
              for sid, symbol, price in rows}
    bil = conn.execute(normalized_layout.candidate_query(conn,
        'SELECT bil_close_unadjusted FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s'),
        (candidate, day)).fetchone()[0]
    result['BIL'] = {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'private-timing-security:BIL')),
        'security_id': 'SENTINEL:BIL', 'symbol': 'BIL', 'price': Decimal(str(bil))}
    conn.rollback()
    return result
